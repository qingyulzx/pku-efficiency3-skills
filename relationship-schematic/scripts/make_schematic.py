#!/usr/bin/env python3
"""make_schematic.py - render an entity-relation model as an editable layered SVG.

The figure model (JSON) is the single source of truth. Every node and every
edge in the SVG carries:
  - a stable element id        (node-<id>, edge-<id>, group-<id>)
  - data-* attributes recording label, relation type, direction and the
    verbatim evidence quote + locator from the source material

so that verify_svg.py can read the drawing back and check it against the
model, and a human reviewer can trace any element to its source.

Usage:
  python make_schematic.py model.json -o figure.svg [--report layout.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from xml.sax.saxutils import escape, quoteattr

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schematic_lib import (  # noqa: E402
    RELATION_TYPES_RANKED, check_model, est_text_width, fmt_float,
    load_model, load_symbols, sanitize_id, wrap_label,
)

GENERATOR = "relationship-schematic make_schematic 1.1"

FONT_STACK = "Helvetica, Arial, 'DejaVu Sans', sans-serif"
C_TEXT = "#1F2933"
C_SUB = "#6B7280"
C_EDGE = "#1F2933"
C_GROUP_LABEL = "#4B5563"

F_TITLE = 19.0
F_LABEL = 15.0
F_SUB = 10.5
F_ELABEL = 11.5
F_LEGEND = 12.5
F_GLABEL = 11.5

PAD_X, PAD_Y = 16.0, 11.0
RANK_VGAP = 80.0
NODE_HGAP = 46.0
MARGIN = 44.0
NODE_MAX_W = 260.0
ARROW_SHORTEN = 11.0


class Box:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h

    @property
    def cx(self): return self.x + self.w / 2
    @property
    def cy(self): return self.y + self.h / 2

    def union(self, other: "Box", pad_x=14.0, pad_top=26.0, pad_bottom=14.0):
        x0 = min(self.x, other.x) - pad_x
        y0 = min(self.y, other.y) - pad_top
        x1 = max(self.x + self.w, other.x + other.w) + pad_x
        y1 = max(self.y + self.h, other.y + other.h) + pad_bottom
        return Box(x0, y0, x1 - x0, y1 - y0)


class Node(Box):
    def __init__(self, eid, label, etype, evidence, color):
        super().__init__(0, 0, 0, 0)
        self.eid = eid
        self.label = label
        self.etype = etype
        self.evidence = evidence
        self.color = color
        self.rank = 0
        self.lines = [label]

    def measure(self):
        self.lines = wrap_label(self.label, NODE_MAX_W - 2 * PAD_X, F_LABEL) or [""]
        w_text = max(est_text_width(ln, F_LABEL) for ln in self.lines)
        w_sub = est_text_width(self.etype, F_SUB) if self.etype else 0
        self.w = max(w_text, w_sub) + 2 * PAD_X
        self.h = len(self.lines) * (F_LABEL + 3.5) + 2 * PAD_Y
        if self.etype:
            self.h += F_SUB + 4.0


def classify_color(etype: str, symbols: dict) -> str:
    palette = symbols["node_palette"]
    if not etype:
        return palette[0]
    idx = sum(ord(c) for c in etype) % len(palette)
    return palette[idx]


# ------------------------------------------------------------------ ranking

def compute_ranks(model, nodes: dict[str, Node], warnings: list):
    """Longest-path layering on A_to_B rank edges; cycles broken via DFS."""
    rank_edges = []
    seen_pairs = set()
    for r in model["relations"]:
        if (r["type"] in RELATION_TYPES_RANKED and r["direction"] == "A_to_B"
                and r["from"] in nodes and r["to"] in nodes):
            key = (r["from"], r["to"])
            if key not in seen_pairs:
                rank_edges.append(key)
                seen_pairs.add(key)

    # DFS cycle detection -> back edges excluded from layering
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in nodes}
    back = set()

    def dfs(u):
        color[u] = GRAY
        for a, b in rank_edges:
            if a != u:
                continue
            if color[b] == GRAY:
                back.add((a, b))
            elif color[b] == WHITE:
                dfs(b)
        color[u] = BLACK

    for n in nodes:
        if color[n] == WHITE:
            dfs(n)

    layer_edges = [e for e in rank_edges if e not in back]
    for (a, b) in back:
        warnings.append({
            "code": "cycle_broken_for_layout",
            "detail": f"edge {a}->{b} is part of a directed cycle; ignored for "
                      f"layering only, still drawn"})

    for n in nodes.values():
        n.rank = 0
    for _ in range(len(nodes) + 2):
        changed = False
        # rank[b] = max(rank[b], rank[a]+1): A_to_B edges always point DOWNWARD
        for a, b in layer_edges:
            if nodes[b].rank < nodes[a].rank + 1:
                nodes[b].rank = nodes[a].rank + 1
                changed = True
        if not changed:
            break
    return back


def order_ranks(model, nodes: dict[str, Node]):
    """Within-rank ordering: cluster contiguity + barycenter sweeps."""
    # top-level cluster for each entity
    top_cluster: dict[str, str] = {}
    group_members = {g["id"]: g["members"] for g in model["groups"]}
    for e in model["entities"]:
        top_cluster[e["id"]] = ""
    for g in model["groups"]:
        stack = [g["id"]]
        while stack:
            gid = stack.pop()
            for m in group_members.get(gid, []):
                if m in top_cluster:
                    top_cluster[m] = g["id"]
                if m in group_members:
                    stack.append(m)
    cluster_order: dict[str, int] = {}
    for e in model["entities"]:
        c = top_cluster[e["id"]]
        if c and c not in cluster_order:
            cluster_order[c] = len(cluster_order)

    by_rank: dict[int, list[str]] = {}
    for eid, n in nodes.items():
        by_rank.setdefault(n.rank, []).append(eid)

    pos: dict[str, float] = {}
    for r in sorted(by_rank):
        by_rank[r].sort(key=lambda eid: (
            cluster_order.get(top_cluster[eid], 10 ** 6),
            nodes[eid].eid))
        for i, eid in enumerate(by_rank[r]):
            pos[eid] = float(i)

    adjacency: dict[str, list[str]] = {}
    for rel in model["relations"]:
        if rel["from"] in nodes and rel["to"] in nodes:
            adjacency.setdefault(rel["from"], []).append(rel["to"])
            adjacency.setdefault(rel["to"], []).append(rel["from"])

    for _ in range(3):
        for r in sorted(by_rank):
            for eid in by_rank[r]:
                nbrs = [pos[m] for m in adjacency.get(eid, [])
                        if m in pos and nodes[m].rank != r]
                if nbrs:
                    pos[eid] = sum(nbrs) / len(nbrs)
        for r in sorted(by_rank, reverse=True):
            by_rank[r].sort(key=lambda eid: (
                cluster_order.get(top_cluster[eid], 10 ** 6), pos[eid]))
            for i, eid in enumerate(by_rank[r]):
                pos[eid] = float(i)
    return by_rank


def place(model, nodes, by_rank, warnings):
    """Assign x/y. Returns content width/height."""
    rank_widths = {}
    for r, eids in by_rank.items():
        rank_widths[r] = sum(nodes[e].w for e in eids) + NODE_HGAP * (len(eids) - 1)
    content_w = max(rank_widths.values()) if rank_widths else 0

    y = MARGIN
    for r in sorted(by_rank):
        row_h = max(nodes[e].h for e in by_rank[r])
        x = MARGIN + (content_w - rank_widths[r]) / 2
        for eid in by_rank[r]:
            n = nodes[eid]
            n.x, n.y = x, y + (row_h - n.h) / 2
            x += n.w + NODE_HGAP
        y += row_h + RANK_VGAP
    content_h = y - RANK_VGAP + MARGIN
    return content_w, content_h


# -------------------------------------------------------------- group boxes

def build_group_boxes(model, nodes, warnings):
    members_map = {g["id"]: g["members"] for g in model["groups"]}
    depth: dict[str, int] = {}

    def gdepth(gid, seen=()):
        if gid in depth:
            return depth[gid]
        if gid in seen:
            return 0
        d = 1 + max((gdepth(m, seen + (gid,)) for m in members_map.get(gid, [])
                     if m in members_map), default=0)
        depth[gid] = d
        return d

    for g in model["groups"]:
        gdepth(g["id"])

    boxes: dict[str, Box] = {}
    ordered = sorted(model["groups"], key=lambda g: -depth[g["id"]])
    for g in ordered:
        parts = []
        for m in g["members"]:
            if m in nodes:
                parts.append(nodes[m])
            elif m in boxes:
                parts.append(boxes[m])
            else:
                warnings.append({"code": "group_member_not_laid_out",
                                 "detail": f"group '{g['id']}': member '{m}' unknown"})
        if not parts:
            continue
        acc = Box(parts[0].x, parts[0].y, parts[0].w, parts[0].h)
        for p in parts[1:]:
            acc = acc.union(p, pad_x=16.0, pad_top=30.0, pad_bottom=12.0)
        acc = acc.union(acc, pad_x=6.0, pad_top=8.0, pad_bottom=6.0)
        boxes[g["id"]] = acc
    return boxes


# --------------------------------------------------------------- edge paths

def attach_points(src: Box, dst: Box):
    """Choose border attachment points based on relative position."""
    if abs(dst.cy - src.cy) < 24 and dst.cx != src.cx:
        # side-by-side
        if dst.cx > src.cx:
            return (src.x + src.w, src.cy), (dst.x, dst.cy)
        return (src.x, src.cy), (dst.x + dst.w, dst.cy)
    if dst.cy > src.cy:
        return (src.cx, src.y + src.h), (dst.cx, dst.y)
    return (src.cx, src.y), (dst.cx, dst.y + dst.h)


def shorten(p0, p1, amount):
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    d = (dx * dx + dy * dy) ** 0.5
    if d < 1e-6 or d <= amount:
        return p1
    k = amount / d
    return (p1[0] - dx * k, p1[1] - dy * k)


def cubic_mid(p0, p1, p2, p3):
    return ((p0[0] + 3 * p1[0] + 3 * p2[0] + p3[0]) / 8.0,
            (p0[1] + 3 * p1[1] + 3 * p2[1] + p3[1]) / 8.0)


def edge_path(src: Box, dst: Box, same_rank_backward: bool):
    p0, p3 = attach_points(src, dst)
    if same_rank_backward:
        # dip below both nodes
        ydip = max(src.y + src.h, dst.y + dst.h) + 46.0
        p1 = (p0[0], ydip)
        p2 = (p3[0], ydip)
        return p0, p1, p2, p3
    dy = p3[1] - p0[1]
    if abs(dy) < 24 and abs(p3[0] - p0[0]) < 24:
        # vertical-ish
        p1 = (p0[0], p0[1] + dy * 0.4)
        p2 = (p3[0], p3[1] - dy * 0.4)
    else:
        p1 = (p0[0], p0[1] + dy * 0.45)
        p2 = (p3[0], p3[1] - dy * 0.45)
    return p0, p1, p2, p3


# ------------------------------------------------------------------- svg

def attr(name, value):
    return f' {name}={quoteattr(str(value))}'


def evidence_attrs(ev: dict, prefix: str = "data-evidence") -> str:
    parts = []
    if ev.get("quote"):
        parts.append(attr(f"{prefix}-quote", ev["quote"]))
    if ev.get("locator"):
        parts.append(attr(f"{prefix}-locator", ev["locator"]))
    if ev.get("source"):
        parts.append(attr(f"{prefix}-source", ev["source"]))
    return "".join(parts)


def generate(model, symbols, out_path, warnings):
    nodes: dict[str, Node] = {}
    for e in model["entities"]:
        nodes[e["id"]] = Node(e["id"], e["label"], e.get("type", ""),
                              e.get("evidence", {}),
                              e.get("color") or classify_color(e.get("type", ""), symbols))
        nodes[e["id"]].measure()

    compute_ranks(model, nodes, warnings)
    by_rank = order_ranks(model, nodes)
    content_w, content_h = place(model, nodes, by_rank, warnings)
    group_boxes = build_group_boxes(model, nodes, warnings)

    # canvas size: requested width or content width, whichever is larger
    req_w = float(model.get("canvas_width") or 0) or 0
    width = max(req_w, content_w + 2 * MARGIN)
    if req_w and content_w + 2 * MARGIN > req_w:
        warnings.append({
            "code": "canvas_expanded",
            "detail": f"requested canvas width {req_w:.0f} is smaller than content "
                      f"({content_w + 2 * MARGIN:.0f}); canvas widened to fit - no element was clipped"})

    # title block
    title_lines = []
    if model.get("figure_label"):
        title_lines.append((model["figure_label"], F_SUB * 1.05, False, C_SUB))
    if model.get("title"):
        title_lines.append((model["title"], F_TITLE, True, C_TEXT))
    title_h = sum(f + 10 for _, f, _, _ in title_lines) if title_lines else 0

    # legend: used relation types + custom entries
    used_types = sorted({r["type"] for r in model["relations"]} |
                        {"contains" for g in model["groups"]})
    legend_items = []
    for t in used_types:
        spec = symbols["relation_types"].get(t)
        if spec:
            legend_items.append((t, spec.get("legend_text", t)))
    legend_items += [(None, f"{it.get('key', '')}: {it.get('meaning', '')}")
                     for it in model.get("legend_extra", [])]

    # measure legend
    leg_sample_w = 46.0
    leg_gap = 26.0
    leg_rows, cur, cur_w = [], [], 0.0
    avail = width - 2 * MARGIN
    for t, text in legend_items:
        w = leg_sample_w + 10 + est_text_width(text, F_LEGEND) + leg_gap
        if cur and cur_w + w > avail:
            leg_rows.append(cur)
            cur, cur_w = [], 0.0
        cur.append((t, text, w))
        cur_w += w
    if cur:
        leg_rows.append(cur)
    legend_h = len(leg_rows) * 26 + (18 if leg_rows else 0)

    height = MARGIN + title_h + content_h + legend_h + MARGIN
    # shift everything down by title block
    dy = MARGIN + title_h
    for n in nodes.values():
        n.y += dy
    for b in group_boxes.values():
        b.y += dy

    s = []
    s.append(f'<?xml version="1.0" encoding="UTF-8"?>')
    s.append(f'<!-- generated by {GENERATOR}; model-driven, elements carry evidence in data-* attributes -->')
    phys = model.get("physical_width_mm")
    if phys:
        s.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{fmt_float(phys)}mm" '
                 f'height="{fmt_float(phys * height / width)}mm" '
                 f'viewBox="0 0 {fmt_float(width)} {fmt_float(height)}">')
    else:
        s.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{fmt_float(width)}" '
                 f'height="{fmt_float(height)}" viewBox="0 0 {fmt_float(width)} {fmt_float(height)}">')
    s.append(f'<title>{escape(model.get("title") or "relationship schematic")}</title>')
    s.append('<desc>Entity-relationship schematic generated from a verified relation table. '
             'Each node/edge group carries data-evidence-quote and data-evidence-locator.</desc>')

    # defs / markers
    s.append('<defs>')
    s.append('<marker id="mk-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="12" '
             'markerHeight="12" markerUnits="userSpaceOnUse" orient="auto-start-reverse">'
             f'<path d="M0,0 L10,5 L0,10 z" fill="{C_EDGE}"/></marker>')
    s.append('<marker id="mk-bar" viewBox="0 0 10 10" refX="2" refY="5" markerWidth="14" '
             'markerHeight="14" markerUnits="userSpaceOnUse" orient="auto">'
             f'<path d="M2,0 L2,10" stroke="{C_EDGE}" stroke-width="2.6"/></marker>')
    s.append('</defs>')

    s.append(f'<rect x="0" y="0" width="{fmt_float(width)}" height="{fmt_float(height)}" '
             f'fill="#FFFFFF" id="background"/>')

    # ---------------------------------------------------------- groups
    for g in model["groups"]:
        b = group_boxes.get(g["id"])
        if b is None:
            continue
        s.append(f'<g id="group-{sanitize_id(g["id"])}"'
                 + attr("data-group-id", g["id"])
                 + attr("data-label", g.get("label", ""))
                 + evidence_attrs(g.get("evidence", {})) + '>')
        s.append(f'<rect x="{fmt_float(b.x)}" y="{fmt_float(b.y)}" width="{fmt_float(b.w)}" '
                 f'height="{fmt_float(b.h)}" rx="10" fill="{symbols["group_fill"]}" '
                 f'stroke="#9CA3AF" stroke-width="1.2"/>')
        if g.get("label"):
            s.append(f'<text x="{fmt_float(b.x + 10)}" y="{fmt_float(b.y + 17)}" '
                     f'font-family="{FONT_STACK}" font-size="{fmt_float(F_GLABEL)}" '
                     f'fill="{C_GROUP_LABEL}">{escape(g["label"])}</text>')
        s.append('</g>')

    # ----------------------------------------------------------- edges
    for r in model["relations"]:
        rtype = r["type"]
        if rtype in ("contains", "parallels"):
            if rtype == "contains":
                has_group = any(r["to"] in g["members"] for g in model["groups"])
                if not has_group:
                    warnings.append({
                        "code": "contains_without_group",
                        "detail": f"relation '{r['id']}' is containment but no group lists "
                                  f"'{r['to']}' as a member; containment must be drawn as nesting, "
                                  f"add a group or the relation stays unverifiable"})
            continue
        spec = symbols["relation_types"][rtype]
        direction = r["direction"]

        # geometric endpoints: 'from' is the semantic source for A_to_B/bidirectional;
        # for B_to_A the arrow points from model['to'] to model['from'].
        if direction == "B_to_A":
            src, dst = r["to"], r["from"]
        else:
            src, dst = r["from"], r["to"]

        if src == dst:
            # self loop
            n = nodes[src]
            x0, y0 = n.x + n.w, n.y + n.h * 0.30
            x3, y3 = n.x + n.w, n.y + n.h * 0.70
            bulge = 48.0
            d_attr = (f'M {fmt_float(x0)},{fmt_float(y0)} '
                      f'C {fmt_float(x0 + bulge)},{fmt_float(y0)} '
                      f'{fmt_float(x3 + bulge)},{fmt_float(y3)} '
                      f'{fmt_float(x3)},{fmt_float(y3)}')
            mid = (x0 + bulge * 0.75, (y0 + y3) / 2)
            p_start, p_end = (x0, y0), (x3, y3)
        else:
            sb = nodes.get(src) or group_boxes.get(src)
            db = nodes.get(dst) or group_boxes.get(dst)
            if sb is None or db is None:
                warnings.append({"code": "edge_endpoint_missing",
                                 "detail": f"relation '{r['id']}': endpoint box not found"})
                continue
            backward = (src in nodes and dst in nodes
                        and nodes[src].rank == nodes[dst].rank
                        and nodes[dst].cx < nodes[src].cx)
            p0, p1, p2, p3 = edge_path(sb, db, backward)
            # shorten end so the marker sits at the border, not inside the node
            pe = shorten(p0, p3, ARROW_SHORTEN)
            d_attr = (f'M {fmt_float(p0[0])},{fmt_float(p0[1])} '
                      f'C {fmt_float(p1[0])},{fmt_float(p1[1])} '
                      f'{fmt_float(p2[0])},{fmt_float(p2[1])} '
                      f'{fmt_float(pe[0])},{fmt_float(pe[1])}')
            mid = cubic_mid(p0, p1, p2, p3)
            p_start, p_end = p0, pe

        line_style = spec["line"]
        if direction == "unknown":
            line_style = "dashed"
        dash = symbols["line_styles"][line_style]["stroke_dasharray"]
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""

        marker_end = ""
        marker_start = ""
        if direction != "unknown":
            if spec.get("end"):
                marker_end = f' marker-end="url(#{symbols["markers"][spec["end"]]["svg_id"]})"'
            if direction == "bidirectional" and spec.get("end"):
                marker_start = f' marker-start="url(#{symbols["markers"][spec["end"]]["svg_id"]})"'

        s.append(f'<g id="edge-{sanitize_id(r["id"])}"'
                 + attr("data-relation-id", r["id"])
                 + attr("data-from", r["from"])
                 + attr("data-to", r["to"])
                 + attr("data-type", rtype)
                 + attr("data-direction", direction)
                 + evidence_attrs(r.get("evidence", {})) + '>')
        s.append(f'<path d="{d_attr}" fill="none" stroke="{C_EDGE}" '
                 f'stroke-width="1.6"{dash_attr}{marker_end}{marker_start}/>')
        # direction marker coordinates for raster fallback + verification
        s.append(f'<path d="M {fmt_float(p_start[0])},{fmt_float(p_start[1])} '
                 f'{fmt_float(p_end[0])},{fmt_float(p_end[1])}" stroke="none" fill="none" '
                 + attr("data-role", "edge-axis") + '/>')

        # edge label
        elabel = r.get("label") or ""
        if not elabel and rtype == "modifies":
            elabel = "P"
        if not elabel and direction == "unknown":
            elabel = "?"
        if elabel:
            tw = est_text_width(elabel, F_ELABEL)
            s.append(f'<rect x="{fmt_float(mid[0] - tw / 2 - 3)}" y="{fmt_float(mid[1] - F_ELABEL * 0.72)}" '
                     f'width="{fmt_float(tw + 6)}" height="{fmt_float(F_ELABEL * 0.95)}" fill="#FFFFFF" '
                     f'fill-opacity="0.9" stroke="none"/>')
            s.append(f'<text x="{fmt_float(mid[0])}" y="{fmt_float(mid[1])}" '
                     f'font-family="{FONT_STACK}" font-size="{fmt_float(F_ELABEL)}" '
                     f'text-anchor="middle" fill="{C_TEXT}">{escape(elabel)}</text>')
        s.append('</g>')

    # ----------------------------------------------------------- nodes
    for eid, n in nodes.items():
        s.append(f'<g id="node-{sanitize_id(eid)}"'
                 + attr("data-entity-id", eid)
                 + attr("data-label", n.label)
                 + attr("data-type", n.etype)
                 + evidence_attrs(n.evidence) + '>')
        s.append(f'<rect x="{fmt_float(n.x)}" y="{fmt_float(n.y)}" width="{fmt_float(n.w)}" '
                 f'height="{fmt_float(n.h)}" rx="8" fill="{n.color}" '
                 f'stroke="{symbols["node_stroke"]}" stroke-width="1.4"/>')
        ty = n.y + PAD_Y + F_LABEL * 0.78
        for ln in n.lines:
            s.append(f'<text x="{fmt_float(n.cx)}" y="{fmt_float(ty)}" '
                     f'font-family="{FONT_STACK}" font-size="{fmt_float(F_LABEL)}" '
                     f'text-anchor="middle" fill="{C_TEXT}">{escape(ln)}</text>')
            ty += F_LABEL + 3.5
        if n.etype:
            s.append(f'<text x="{fmt_float(n.cx)}" y="{fmt_float(ty - 1)}" '
                     f'font-family="{FONT_STACK}" font-size="{fmt_float(F_SUB)}" '
                     f'text-anchor="middle" fill="{C_SUB}">{escape(n.etype)}</text>')
        s.append('</g>')

    # ----------------------------------------------------------- title
    if title_lines:
        s.append('<g id="title">')
        ty = MARGIN + F_SUB
        role = "figure-label"
        for text, f, bold, color in title_lines:
            fw = ' font-weight="bold"' if bold else ''
            s.append(f'<text x="{fmt_float(width / 2)}" y="{fmt_float(ty)}" '
                     f'font-family="{FONT_STACK}" font-size="{fmt_float(f)}"{fw} '
                     f'text-anchor="middle" fill="{color}"'
                     f' data-role="{role}">{escape(text)}</text>')
            ty += f + 10
            role = "title"
        s.append('</g>')

    # ---------------------------------------------------------- legend
    if leg_rows:
        ly = height - MARGIN - len(leg_rows) * 26 + 20
        legend_extra_counter = [0]
        s.append('<g id="legend">')
        for row in leg_rows:
            lx = MARGIN
            for t, text, w in row:
                extra_i = legend_extra_counter[0]
                legend_extra_counter[0] += 1
                item_id = (f'legend-item-{sanitize_id(t)}' if t
                           else f'legend-extra-{extra_i}')
                s.append(f'<g id="{item_id}"' + (attr("data-type", t) if t else '') + '>')
                if t == "contains":
                    s.append(f'<rect x="{fmt_float(lx)}" y="{fmt_float(ly - 9)}" width="34" '
                             f'height="16" rx="4" fill="{symbols["group_fill"]}" '
                             f'stroke="#9CA3AF" stroke-width="1.1"/>')
                elif t:
                    spec = symbols["relation_types"][t]
                    dash = symbols["line_styles"][spec["line"]]["stroke_dasharray"]
                    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
                    mk = ""
                    if spec.get("end"):
                        mk = f' marker-end="url(#{symbols["markers"][spec["end"]]["svg_id"]})"'
                    s.append(f'<line x1="{fmt_float(lx)}" y1="{fmt_float(ly - 3)}" '
                             f'x2="{fmt_float(lx + leg_sample_w)}" y2="{fmt_float(ly - 3)}" '
                             f'stroke="{C_EDGE}" stroke-width="1.6"{dash_attr}{mk}/>')
                s.append(f'<text x="{fmt_float(lx + leg_sample_w + 10)}" y="{fmt_float(ly)}" '
                         f'font-family="{FONT_STACK}" font-size="{fmt_float(F_LEGEND)}" '
                         f'fill="{C_TEXT}">{escape(text)}</text>')
                s.append('</g>')
                lx += w
            ly += 26
        s.append('</g>')

    s.append('</svg>\n')

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(s))
    return {"width": width, "height": height, "nodes": len(nodes),
            "edges_drawn": sum(1 for r in model["relations"]
                               if r["type"] not in ("contains", "parallels"))}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model", help="figure model JSON (entities+relations)")
    ap.add_argument("-o", "--output", required=True, help="output SVG path")
    ap.add_argument("--report", help="optional JSON layout report path")
    args = ap.parse_args()

    symbols = load_symbols()
    model = load_model(args.model)
    warnings = []
    findings = check_model(model, symbols)
    errors = [f for f in findings if f["severity"] == "error"]
    if errors:
        print(json.dumps({"status": "refused", "errors": errors},
                         ensure_ascii=False, indent=2))
        sys.exit(2)

    stats = generate(model, symbols, args.output, warnings)
    report = {
        "status": "ok",
        "generator": GENERATOR,
        "svg": os.path.abspath(args.output),
        "canvas": stats,
        "warnings": warnings + [f for f in findings if f["severity"] == "warn"],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
