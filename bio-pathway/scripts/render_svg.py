#!/usr/bin/env python3
"""render_svg.py - render a biopathway model.json into a layered, id-addressable SVG.

The SVG is the editable primary source:
  - layers:   <g id="layer-compartments|edges|nodes|legend|title">
  - nodes:    <g id="node-<ID>" data-type data-compartment data-source-loc>
  - edges:    <g id="edge-<ID>" data-type data-confidence data-directed data-source-loc>
  - evidence: full entity/edge quote table embedded in <desc>
Rendering is deterministic: the same model.json produces a byte-identical SVG.

Usage:
  python render_svg.py --model model.json --out pathway.svg [--report render-report.json]
"""
import argparse
import json
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

GENERATOR = "biopathway render_svg.py 1.0.0"
FONT = "Helvetica, Arial, 'Noto Sans', sans-serif"

MIN_BAND_H = {"membrane": 70, "nucleus": 130, "open": 110, "region": 120,
              "organelle": 110, "unspecified": 110}
PAD = 26
VGAP = 22
HGAP = 46
LEFT_MARGIN = 30
TITLE_H = 86
LEGEND_W = 320
MAX_CANVAS = (2400, 1800)
LABEL_FS = 15
SUB_FS = 11


def q(tag):
    return f"{{{SVG_NS}}}{tag}"


def load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def text_w(s, fs):
    return max(1, len(s)) * fs * 0.64


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------- layout ----

class Box:
    def __init__(self, ent, spec):
        self.ent = ent
        self.id = ent["id"]
        self.label = ent.get("label", ent["id"])
        self.sub = ent.get("sub")
        self.type = ent.get("type", "protein")
        self.spec = spec
        self.w = max(74, text_w(self.label, LABEL_FS) + 26)
        h = 40 if self.type in ("protein", "receptor", "gene", "rna", "family") else 46
        if self.type in ("molecule",):
            h = 48
        if self.type == "cell":
            h = 52
        if self.sub:
            h += 15
        self.h = h
        self.col = 0
        self.row = 0
        self.x = 0.0
        self.y = 0.0
        self.band = None

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    def anchor(self, side):
        if side == "right":
            return self.x + self.w, self.cy
        if side == "left":
            return self.x, self.cy
        if side == "top":
            return self.cx, self.y
        return self.cx, self.y + self.h


def compute_layout(model, nodespec):
    warnings = []
    compartments = list(model.get("compartments", []))
    if not compartments:
        compartments = [{"id": "unspecified", "label": "Location not stated",
                         "kind": "unspecified", "rank": 0}]
        warnings.append("no compartments in model; using a single 'unspecified' band")
    compartments.sort(key=lambda c: (c.get("rank", 0), c["id"]))
    comp_by_id = {c["id"]: c for c in compartments}
    band_rank = {c["id"]: i for i, c in enumerate(compartments)}

    ents = model.get("entities", [])
    boxes = [Box(e, nodespec.get(e.get("type", "protein"), nodespec["protein"]))
             for e in ents]
    box_by_id = {b.id: b for b in boxes}

    # column assignment from 'order' (default: first-mention index)
    order_vals = []
    for i, b in enumerate(boxes):
        o = b.ent.get("order", i + 1)
        order_vals.append(o)
    for b, o in zip(boxes, order_vals):
        b.col = sorted(set(order_vals)).index(o)
    n_cols = max((b.col for b in boxes), default=-1) + 1

    # compartment per box (unknown -> unspecified band + warning)
    for b in boxes:
        cid = b.ent.get("compartment")
        if cid not in comp_by_id:
            warnings.append(
                f"entity {b.id}: compartment '{cid}' not defined; placed in 'unspecified' band")
            b.ent["compartment"] = "unspecified"
        b.band = b.ent["compartment"]

    # rows within each (band, col)
    for band in compartments:
        for col in range(n_cols):
            group = sorted((b for b in boxes if b.band == band["id"] and b.col == col),
                           key=lambda b: b.id)
            for r, b in enumerate(group):
                b.row = r
                b.rows_in_col = len(group)

    col_w = [70.0] * max(n_cols, 1)
    for b in boxes:
        col_w[b.col] = max(col_w[b.col], b.w)

    band_h = {}
    for band in compartments:
        rows = max((b.rows_in_col for b in boxes if b.band == band["id"]), default=0)
        maxnh = max((b.h for b in boxes if b.band == band["id"]), default=40)
        needed = PAD * 2 + max(rows, 1) * maxnh + (max(rows, 1) - 1) * VGAP
        band_h[band["id"]] = max(MIN_BAND_H.get(band.get("kind", "region"), 120), needed)

    y = TITLE_H
    for band in compartments:
        band["_y"] = y
        band["_h"] = band_h[band["id"]]
        y += band_h[band["id"]] + 14

    x = LEFT_MARGIN
    col_x = []
    for w in col_w:
        col_x.append(x)
        x += w + HGAP

    for b in boxes:
        b.x = col_x[b.col] + (col_w[b.col] - b.w) / 2
        band = comp_by_id[b.band]
        stack_h = b.rows_in_col * b.h + (b.rows_in_col - 1) * VGAP
        top = band["_y"] + (band["_h"] - stack_h) / 2
        b.y = top + b.row * (b.h + VGAP)

    # translocation edges need target bands even if the band has no entities
    used_bands = [c for c in compartments]
    canvas_w = LEFT_MARGIN + sum(col_w) + HGAP * max(n_cols - 1, 0) + 40 + LEGEND_W
    canvas_h = y + 46
    if canvas_w > MAX_CANVAS[0] or canvas_h > MAX_CANVAS[1]:
        warnings.append(
            f"canvas {int(canvas_w)}x{int(canvas_h)} exceeds recommended max "
            f"{MAX_CANVAS[0]}x{MAX_CANVAS[1]}; consider splitting into panels or "
            "reducing simultaneous branches (figure still rendered)")
    return {"compartments": used_bands, "comp_by_id": comp_by_id,
            "band_rank": band_rank, "boxes": boxes, "box_by_id": box_by_id,
            "canvas": (int(canvas_w), int(canvas_h)), "warnings": warnings}


# ------------------------------------------------------------------ svg ----

def add(parent, tag, **attrs):
    el = ET.SubElement(parent, q(tag))
    for k, v in attrs.items():
        if v is not None:
            el.set(k, str(v))
    return el


def add_text(parent, x, y, s, fs, cls=None, italic=False, bold=False, anchor=None,
             fill="#111111"):
    t = add(parent, "text", x=round(x, 1), y=round(y, 1), **{
        "font-family": FONT, "font-size": fs, "fill": fill,
        "font-style": "italic" if italic else None,
        "font-weight": "bold" if bold else None,
        "text-anchor": anchor, "class": cls})
    t.text = str(s)
    return t


def shape_for(box):
    """Return the node outline element according to node type."""
    spec = box.spec
    g = box.group
    fill, stroke = spec.get("fill", "#dbe9f6"), spec.get("stroke", "#2c5f8a")
    dash = spec.get("stroke_dasharray")
    if spec.get("shape") == "hexagon":
        pts = [(box.x + box.w * 0.12, box.y), (box.x + box.w * 0.88, box.y),
               (box.x + box.w, box.cy), (box.x + box.w * 0.88, box.y + box.h),
               (box.x + box.w * 0.12, box.y + box.h), (box.x, box.cy)]
        pts = " ".join(f"{round(px,1)},{round(py,1)}" for px, py in pts)
        return add(g, "polygon", points=pts, fill=fill, stroke=stroke,
                   stroke_width=1.6, stroke_dasharray=dash)
    if spec.get("shape") == "circle":
        r = max(box.w / 2, 26)
        return add(g, "ellipse", cx=round(box.cx, 1), cy=round(box.cy, 1),
                   rx=round(r, 1), ry=26, fill=fill, stroke=stroke, stroke_width=1.6,
                   stroke_dasharray=dash)
    if spec.get("shape") == "ellipse":
        return add(g, "ellipse", cx=round(box.cx, 1), cy=round(box.cy, 1),
                   rx=round(box.w / 2, 1), ry=26, fill=fill, stroke=stroke,
                   stroke_width=1.6, stroke_dasharray=dash)
    rx = 8 if spec.get("shape") == "roundrect" else 0
    return add(g, "rect", x=round(box.x, 1), y=round(box.y, 1), width=round(box.w, 1),
               height=round(box.h, 1), rx=rx, fill=fill, stroke=stroke,
               stroke_width=1.6, stroke_dasharray=dash)


def svg_document(model, layout, edgespec):
    W, H = layout["canvas"]
    root = ET.Element(q("svg"), {
        "width": str(W), "height": str(H),
        "viewBox": f"0 0 {W} {H}",
        "id": "biopathway-figure", "class": "biopathway",
        "data-generator": GENERATOR, "data-model-version":
            model.get("model_version", "1.0.0")})
    desc = ET.SubElement(root, q("desc"))
    desc.text = evidence_text(model)

    defs = ET.SubElement(root, q("defs"))
    mk = add(defs, "marker", id="arrow", viewBox="0 0 10 10", refX=9, refY=5,
             markerWidth=9, markerHeight=9, orient="auto-start-reverse")
    add(mk, "path", d="M 0 0 L 10 5 L 0 10 z", fill="#222222")
    mk = add(defs, "marker", id="open-arrow", viewBox="0 0 10 10", refX=9, refY=5,
             markerWidth=10, markerHeight=10, orient="auto-start-reverse")
    add(mk, "path", d="M 1 1 L 9 5 L 1 9 z", fill="#ffffff", stroke="#222222",
        stroke_width=1.2)
    mk = add(defs, "marker", id="tbar", viewBox="0 0 10 10", refX=9, refY=5,
             markerWidth=9, markerHeight=9, orient="auto-start-reverse")
    add(mk, "path", d="M 9 0 L 9 10", stroke="#222222", stroke_width=2.2)

    # ---- compartments ------------------------------------------------------
    gc = ET.SubElement(root, q("g"), {"id": "layer-compartments"})
    palette = edgespec["palette"]["compartment_fills"]
    for band in layout["compartments"]:
        kind = band.get("kind", "region")
        y, h = band["_y"], band["_h"]
        bid = band["id"]
        if kind == "membrane":
            add(gc, "rect", id=f"compartment-{bid}", x=0, y=round(y + h / 2 - 6, 1),
                width=W, height=12, fill=palette.get("membrane", "#f2e9dc"),
                stroke="#b08d57", stroke_width=1.4, data_kind="membrane")
            add(gc, "line", x1=0, y1=round(y + h / 2 - 6, 1), x2=W,
                y2=round(y + h / 2 - 6, 1), stroke="#b08d57", stroke_width=1.2)
            add(gc, "line", x1=0, y1=round(y + h / 2 + 6, 1), x2=W,
                y2=round(y + h / 2 + 6, 1), stroke="#b08d57", stroke_width=1.2)
        elif kind == "nucleus":
            add(gc, "rect", id=f"compartment-{bid}", x=10, y=round(y, 1), width=W - 20,
                height=round(h, 1), rx=26, fill=palette.get("nucleus", "#eef2fb"),
                stroke="#4a5f8a", stroke_width=1.6)
            add(gc, "rect", x=16, y=round(y + 6, 1), width=W - 32,
                height=round(h - 12, 1), rx=20, fill="none", stroke="#4a5f8a",
                stroke_width=0.8)
        else:
            fill = palette.get(kind, palette.get(bid, "#ffffff"))
            add(gc, "rect", id=f"compartment-{bid}", x=0, y=round(y, 1), width=W,
                height=round(h, 1), fill=fill,
                stroke="#c9c9c9" if kind == "unspecified" else "none",
                stroke_dasharray="4,4" if kind == "unspecified" else None)
        add_text(gc, 14, y + 20, band.get("label", bid), 12, cls="band-label",
                 fill="#666666")

    # ---- edges ---------------------------------------------------------------
    ge = ET.SubElement(root, q("g"), {"id": "layer-edges"})
    for ed in model.get("edges", []):
        draw_edge(ge, ed, layout, edgespec)

    # ---- nodes ---------------------------------------------------------------
    gn = ET.SubElement(root, q("g"), {"id": "layer-nodes"})
    for box in layout["boxes"]:
        g = ET.SubElement(gn, q("g"), {
            "id": f"node-{box.id}", "data-type": box.type,
            "data-compartment": box.band,
            "data-source-loc": (box.ent.get("source") or {}).get("loc", "")})
        box.group = g
        shape_for(box)
        italic = bool(box.spec.get("font_style") == "italic") or box.type in ("gene", "rna")
        ty = box.cy + 5 if not box.sub else box.y + box.h / 2 - 3
        add_text(g, box.cx, ty, box.label, LABEL_FS, cls="node-label", italic=italic,
                 bold=True, anchor="middle")
        if box.sub:
            add_text(g, box.cx, ty + 15, box.sub, SUB_FS, cls="node-sub",
                     anchor="middle", fill="#555555")

    # ---- legend + title ------------------------------------------------------
    draw_legend(root, model, layout, edgespec)
    gt = ET.SubElement(root, q("g"), {"id": "layer-title"})
    add_text(gt, W / 2 - LEGEND_W / 2, 34, model.get("title", "Mechanism diagram"),
             20, cls="figure-title", bold=True, anchor="middle")
    add_text(gt, W / 2 - LEGEND_W / 2, 56,
             f"Mechanism statement traceable to source material - case {model.get('case_id', 'n/a')}",
             12, cls="figure-subtitle", anchor="middle", fill="#666666")
    add_text(gt, LEFT_MARGIN, H - 14,
             "Editable SVG source; every node/edge id maps to model.json evidence entries.",
             10, cls="figure-footer", fill="#888888")
    return root


def marker_for(ed, edgespec):
    spec = edgespec["edge_types"][ed["type"]]
    head = spec["head"]
    if head == "by-sign":
        head = {"positive": "arrow", "negative": "tbar"}.get(ed.get("sign"), "arrow")
    if ed.get("directed") is False and spec.get("requires_direction") is False:
        head = "none"
    if ed.get("directed") is False and head not in ("none",):
        head = "none"  # undirected edge: never draw a head
    return {"arrow": "url(#arrow)", "tbar": "url(#tbar)",
            "open-arrow": "url(#open-arrow)", "none": None}[head]


def edge_geometry(ed, layout):
    """Return {'d': pathdata, 'end': (x,y), 'prev': point before end} or None."""
    boxes, rank = layout["box_by_id"], layout["band_rank"]
    src = boxes.get(ed["source"])
    tgt = boxes.get(ed["target"]) if ed.get("target_kind", "entity") == "entity" else None
    if src is None or (tgt is None and ed.get("target_kind", "entity") == "entity"):
        return None
    if tgt is None:  # translocation into a compartment
        band = layout["comp_by_id"].get(ed["target"])
        if band is None:
            return None
        by = band["_y"]
        sx, sy = src.anchor("bottom" if band["_y"] > src.y else "top")
        if band["_y"] > src.y:
            return {"d": f"M {sx:.1f} {sy:.1f} L {sx:.1f} {by + 2:.1f}",
                    "end": (sx, by + 2), "prev": (sx, sy)}
        return {"d": f"M {sx:.1f} {sy:.1f} L {sx:.1f} {by + band['_h'] - 2:.1f}",
                "end": (sx, by + band["_h"] - 2), "prev": (sx, sy)}
    sb, tb = src.band, tgt.band
    if sb == tb:
        if src.col == tgt.col and src.row != tgt.row:
            if src.row < tgt.row:
                p1, p2 = src.anchor("bottom"), tgt.anchor("top")
            else:
                p1, p2 = src.anchor("top"), tgt.anchor("bottom")
            return {"d": f"M {p1[0]:.1f} {p1[1]:.1f} L {p2[0]:.1f} {p2[1]:.1f}",
                    "end": p2, "prev": p1}
        if tgt.x > src.x:
            p1, p2 = src.anchor("right"), tgt.anchor("left")
            return {"d": f"M {p1[0]:.1f} {p1[1]:.1f} L {p2[0]:.1f} {p2[1]:.1f}",
                    "end": p2, "prev": p1}
        # feedback: curve below the band
        band = layout["comp_by_id"][sb]
        p1, p2 = src.anchor("bottom"), tgt.anchor("bottom")
        cy = band["_y"] + band["_h"] + 44
        mx = (p1[0] + p2[0]) / 2
        return {"d": (f"M {p1[0]:.1f} {p1[1]:.1f} Q {mx:.1f} {cy:.1f} "
                      f"{p2[0]:.1f} {p2[1]:.1f}"),
                "end": p2, "prev": (mx, cy)}
    if rank.get(sb, 0) < rank.get(tb, 0):  # target lower
        p1, p2 = src.anchor("bottom"), tgt.anchor("top")
    else:
        p1, p2 = src.anchor("top"), tgt.anchor("bottom")
    return {"d": f"M {p1[0]:.1f} {p1[1]:.1f} L {p2[0]:.1f} {p2[1]:.1f}",
            "end": p2, "prev": p1}


def draw_edge(parent, ed, layout, edgespec):
    spec = edgespec["edge_types"][ed["type"]]
    ev = ed.get("evidence") or {}
    g = ET.SubElement(parent, q("g"), {
        "id": f"edge-{ed['id']}", "data-type": ed["type"],
        "data-confidence": ed.get("confidence", "direct"),
        "data-directed": str(ed.get("directed", False)).lower(),
        "data-source-loc": ev.get("loc", "")})
    geom = edge_geometry(ed, layout)
    if geom is None:
        add_text(g, 40, 40, f"edge {ed['id']}: unresolvable endpoints", 12,
                 cls="edge-error", fill="#b00020")
        return
    d, end, prev = geom["d"], geom["end"], geom["prev"]
    dash = edgespec["evidence_confidence"].get(
        ed.get("confidence", "direct"), {}).get("dash")
    badge = spec.get("badge")
    marker = marker_for(ed, edgespec)
    if badge:
        # the line stops at the badge circle's edge, arrowhead pointing at it
        bx, by = badge_pos(ed, layout, end)
        dx, dy = bx - prev[0], by - prev[1]
        n = max((dx * dx + dy * dy) ** 0.5, 1.0)
        ex, ey = bx - dx / n * 11.0, by - dy / n * 11.0
        d = d.rsplit("L", 1)[0] + f"L {ex:.1f} {ey:.1f}"
        end = (bx, by)
    line = add(g, "path", d=d, fill="none", stroke="#222222", stroke_width=1.8,
               stroke_dasharray=dash, marker_end=marker, id=f"edge-{ed['id']}-line")
    if badge:
        bx, by = end
        bl = add(g, "circle", cx=round(bx, 1), cy=round(by, 1), r=10,
                 fill="#ffffff", stroke="#222222", stroke_width=1.4,
                 id=f"edge-{ed['id']}-badge")
        add_text(g, bx, by + 4.5, badge, 12, cls="edge-badge", anchor="middle",
                 bold=True)
        if ed["type"] == "dephosphorylation":
            add(g, "line", x1=round(bx - 7, 1), y1=round(by + 7, 1),
                x2=round(bx + 7, 1), y2=round(by - 7, 1), stroke="#222222",
                stroke_width=1.4)
    if ed["type"] == "unspecified_interaction":
        add_text(g, (end[0] + 24), end[1] - 8, "?", 15, cls="edge-q", bold=True,
                 fill="#555555")
    return g


def badge_pos(ed, layout, end):
    boxes = layout["box_by_id"]
    tgt = boxes.get(ed["target"])
    if tgt is not None and end is not None:
        if abs(end[1] - tgt.y) < abs(end[1] - (tgt.y + tgt.h)):
            return tgt.cx, tgt.y - 16
        if abs(end[1] - (tgt.y + tgt.h)) < abs(end[1] - tgt.cy):
            return tgt.cx, tgt.y + tgt.h + 16
        if end[0] < tgt.cx:
            return tgt.x - 16, tgt.cy
        return tgt.x + tgt.w + 16, tgt.cy
    return end


def draw_legend(root, model, layout, edgespec):
    used_edge_types = sorted({e["type"] for e in model.get("edges", [])})
    used_node_types = sorted({b.type for b in layout["boxes"]})
    any_indirect = any(e.get("confidence") == "indirect" for e in model.get("edges", []))
    any_undirected = any(e.get("directed") is False for e in model.get("edges", []))
    badges = sorted({edgespec["edge_types"][t].get("badge") for t in used_edge_types
                     if edgespec["edge_types"][t].get("badge")})

    W, H = layout["canvas"]
    lx = W - LEGEND_W - 14
    ly = TITLE_H
    gl = ET.SubElement(root, q("g"), {"id": "layer-legend"})
    items = 1 + len(used_edge_types) + len(badges) + len(used_node_types) + \
        (1 if any_indirect else 0) + (1 if any_undirected else 0) + 2
    lh = 44 + items * 24 + 16
    add(gl, "rect", x=lx, y=ly, width=LEGEND_W, height=lh, fill="#ffffff",
        stroke="#bbbbbb", stroke_width=1, rx=6)
    add_text(gl, lx + 14, ly + 24, "Legend", 15, cls="legend-title", bold=True)
    yy = ly + 48
    for t in used_edge_types:
        spec = edgespec["edge_types"][t]
        head = spec["head"]
        demo = {"id": f"demo-{t}", "type": t, "directed": True,
                "sign": "positive" if head == "by-sign" else spec.get("sign")}
        m = marker_for(demo, edgespec)
        if t in ("binding", "complex_formation", "unspecified_interaction"):
            m = None
        add(gl, "line", x1=lx + 14, y1=yy - 4, x2=lx + 62, y2=yy - 4,
            stroke="#222222", stroke_width=1.8, marker_end=m)
        add_text(gl, lx + 72, yy, f"{spec['label']} ({spec['zh']})", 12,
                 cls="legend-item")
        yy += 24
    for b in badges:
        add(gl, "circle", cx=lx + 24, cy=yy - 4, r=9, fill="#ffffff",
            stroke="#222222", stroke_width=1.2)
        add_text(gl, lx + 24, yy, b, 11, cls="legend-item", anchor="middle", bold=True)
        btype = [t for t in used_edge_types
                 if edgespec["edge_types"][t].get("badge") == b]
        add_text(gl, lx + 72, yy,
                 f"{b} badge = {'/'.join(btype)}", 12, cls="legend-item")
        yy += 24
    for ntype in used_node_types:
        spec = edgespec["node_types"].get(ntype, {})
        fill, stroke = spec.get("fill", "#dddddd"), spec.get("stroke", "#888888")
        shape = spec.get("shape", "roundrect")
        if shape == "hexagon":
            pts = f"{lx+16},{yy-14} {lx+36},{yy-14} {lx+44},{yy-4} {lx+36},{yy+6} {lx+16},{yy+6} {lx+8},{yy-4}"
            add(gl, "polygon", points=pts, fill=fill, stroke=stroke, stroke_width=1.2)
        elif shape in ("circle", "ellipse"):
            add(gl, "ellipse", cx=lx + 26, cy=yy - 4, rx=16, ry=11, fill=fill,
                stroke=stroke, stroke_width=1.2)
        else:
            add(gl, "rect", x=lx + 10, y=yy - 14, width=32, height=20,
                rx=6 if shape == "roundrect" else 0, fill=fill, stroke=stroke,
                stroke_width=1.2, stroke_dasharray=spec.get("stroke_dasharray"))
        add_text(gl, lx + 72, yy, f"{ntype} node", 12, cls="legend-item")
        yy += 24
    if any_indirect:
        add(gl, "line", x1=lx + 14, y1=yy - 4, x2=lx + 62, y2=yy - 4,
            stroke="#222222", stroke_width=1.8, stroke_dasharray="6,4")
        add_text(gl, lx + 72, yy, "indirect/inferred evidence", 12, cls="legend-item")
        yy += 24
    if any_undirected:
        add(gl, "line", x1=lx + 14, y1=yy - 4, x2=lx + 62, y2=yy - 4,
            stroke="#222222", stroke_width=1.8)
        add_text(gl, lx + 72, yy, "no arrowhead = direction not stated", 12,
                 cls="legend-item")
        yy += 24
    add_text(gl, lx + 14, yy, "Every element id traces to model.json.", 10,
             cls="legend-note", fill="#777777")


def evidence_text(model):
    lines = [f"biopathway evidence table - case {model.get('case_id', 'n/a')}",
             "ENTITIES:"]
    for e in model.get("entities", []):
        s = e.get("source") or {}
        lines.append(f"  - {e['id']} [{e.get('type')}, {e.get('compartment')}]: "
                     f"{s.get('loc', 'no loc')} | quote: {s.get('quote', '(none)')}")
    lines.append("EDGES:")
    for ed in model.get("edges", []):
        ev = ed.get("evidence") or {}
        lines.append(
            f"  - {ed['id']} {ed['source']} -{ed['type']}"
            f"{'->' if ed.get('directed') else '--'} {ed['target']}"
            f" [{ed.get('confidence', 'direct')}]: {ev.get('loc', 'no loc')} | "
            f"quote: {ev.get('quote', '(none)')}")
    unc = model.get("uncertainties") or []
    lines.append("UNCERTAINTIES:")
    for u in unc:
        lines.append(f"  - {u.get('item')}: {u.get('reason')} (handling: {u.get('handling')})")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--edgespec", default=str(Path(__file__).parent.parent /
                                               "references" / "edge-types.json"))
    ap.add_argument("--report")
    args = ap.parse_args()

    model = load_json(args.model)
    edgespec = load_json(args.edgespec)
    layout = compute_layout(model, edgespec["node_types"])
    root = svg_document(model, layout, edgespec)
    ET.indent(root, space="  ")
    xml = ET.tostring(root, encoding="unicode")
    # ET.tostring adds a stray 'nsmap' attribute never; ensure header:
    out = '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n' + xml + "\n"
    Path(args.out).write_text(out, encoding="utf-8")

    report = {
        "svg": str(Path(args.out).resolve()),
        "canvas": list(layout["canvas"]),
        "n_entities": len(layout["boxes"]),
        "n_edges": len(model.get("edges", [])),
        "layers": ["layer-compartments", "layer-edges", "layer-nodes",
                   "layer-legend", "layer-title"],
        "warnings": layout["warnings"],
        "generator": GENERATOR,
    }
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(report, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if layout["warnings"]:
        print("WARNINGS:", file=sys.stderr)
        for w in layout["warnings"]:
            print(" -", w, file=sys.stderr)


if __name__ == "__main__":
    main()
