#!/usr/bin/env python3
"""verify_svg.py - read a rendered schematic SVG back and check it against its model.

This is the skill's core anti-failure check. After rendering, every node and
edge is read back from the SVG and compared with the relation table, INCLUDING
the geometric direction of each arrow: an 'activates' edge whose arrowhead
ends up nearer the source than the target FAILS verification even though its
data attributes claim the right direction. This is what catches the classic
failure modes (inhibition drawn as activation, upstream/downstream reversed,
containment drawn as juxtaposition).

Checks (each produces pass / fail / warn / skip rows):
  structure          svg parses, viewBox present, generator comment present,
                     all elements inside the canvas
  entity_coverage    every model entity has a node group with matching label
  relation_coverage  every drawable relation has an edge group, attrs match
  marker_semantics   marker (arrow / bar / none) + dash match relation type
                     and direction per the symbol library
  marker_geometry    arrow tip is geometrically near the semantic target and
                     the tail near the semantic source
  containment        group boxes actually enclose their members; every
                     'contains' relation is drawn as nesting; nodes that are
                     NOT members are not accidentally trapped inside a group
  text_fit           node labels fit inside their boxes (estimated width)
  legend_coverage    every drawn relation type appears in the legend

Usage:
  python verify_svg.py model.json figure.svg [--out verify_report.json]
Exit: 0 = all checks pass (warnings allowed); 1 = at least one check failed;
      2 = unusable input.
"""
from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schematic_lib import est_text_width, load_model, load_symbols, sanitize_id  # noqa: E402
from make_schematic import F_LABEL, PAD_X, GENERATOR  # keep in sync with renderer  # noqa: E402

TOL = 0.75  # geometry tolerance in svg user units

AXIS_RE = re.compile(r"M\s*(-?[\d.]+),(-?[\d.]+)\s+(-?[\d.]+),(-?[\d.]+)")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")


def local(el) -> str:
    t = el.tag
    return t.split("}")[-1] if isinstance(t, str) else ""


def children(el, name):
    return [c for c in el if local(c) == name]


def rect_of(el) -> tuple | None:
    try:
        return (float(el.get("x")), float(el.get("y")),
                float(el.get("width")), float(el.get("height")))
    except (TypeError, ValueError):
        return None


def center(box):
    return (box[0] + box[2] / 2.0, box[1] + box[3] / 2.0)


def dist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def parse_svg(path):
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    tree = ET.parse(path, parser)
    return tree.getroot()


class SVGIndex:
    def __init__(self, root, raw_text: str = ""):
        self.root = root
        self.nodes: dict[str, dict] = {}      # entity_id -> {rect, label, texts, el}
        self.edges: dict[str, dict] = {}      # relation_id -> {attrs, axis, marker...}
        self.groups: dict[str, dict] = {}     # group_id -> {rect, label}
        self.legend_types: set[str] = set()
        # generator comment lives BEFORE the root element, out of root.iter();
        # scan the raw text as well as in-tree comment nodes
        self.comments = [raw_text] + [
            el.text or "" for el in root.iter()
            if not isinstance(getattr(el, "tag", None), str)
        ]
        for el in root.iter():
            if not isinstance(getattr(el, "tag", None), str):
                continue
            if local(el) != "g":
                continue
            gid = el.get("id") or ""
            if gid.startswith("node-"):
                rects = children(el, "rect")
                texts = children(el, "text")
                self.nodes[el.get("data-entity-id") or gid[5:]] = {
                    "el": el, "rect": rect_of(rects[0]) if rects else None,
                    "label": el.get("data-label") or "",
                    "texts": [(t.text or "") for t in texts],
                }
            elif gid.startswith("edge-"):
                main_path = axis = None
                for p in children(el, "path"):
                    if p.get("data-role") == "edge-axis":
                        axis = p.get("d") or ""
                    elif p.get("stroke") not in (None, "none"):
                        main_path = p
                self.edges[el.get("data-relation-id") or gid[5:]] = {
                    "el": el, "from": el.get("data-from"),
                    "to": el.get("data-to"), "type": el.get("data-type"),
                    "direction": el.get("data-direction"),
                    "marker_end": (main_path.get("marker-end")
                                   if main_path is not None else None),
                    "marker_start": (main_path.get("marker-start")
                                     if main_path is not None else None),
                    "dasharray": (main_path.get("stroke-dasharray")
                                  if main_path is not None else None),
                    "axis": axis,
                }
            elif gid.startswith("group-"):
                rects = children(el, "rect")
                self.groups[el.get("data-group-id") or gid[6:]] = {
                    "el": el, "rect": rect_of(rects[0]) if rects else None,
                    "label": el.get("data-label") or "",
                }
            elif gid == "legend":
                for item in children(el, "g"):
                    t = item.get("data-type")
                    if t:
                        self.legend_types.add(t)

    def box_of(self, model_id: str):
        """Node rect or group rect for a model id (entities and groups can both
        be edge endpoints)."""
        if model_id in self.nodes and self.nodes[model_id]["rect"]:
            return self.nodes[model_id]["rect"]
        g = self.groups.get(sanitize_id(model_id)) or self.groups.get(model_id)
        return g["rect"] if g else None


def inside(inner: tuple, outer: tuple, tol=TOL) -> bool:
    return (inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol
            and inner[0] + inner[2] <= outer[0] + outer[2] + tol
            and inner[1] + inner[3] <= outer[1] + outer[3] + tol)


def marker_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"#([\w.-]+)", url)
    return m.group(1) if m else None


def verify(model: dict, symbols: dict, svg_path: str) -> dict:
    with open(svg_path, "r", encoding="utf-8") as f:
        raw_text = f.read()
    idx = SVGIndex(parse_svg(svg_path), raw_text)
    rows: list[dict] = []

    def row(check, target, status, detail):
        rows.append({"check": check, "target": target,
                     "status": status, "detail": detail})

    # ------------------------------------------------------------ structure
    vb = idx.root.get("viewBox")
    if not vb:
        row("structure", "svg", "fail", "root svg has no viewBox")
        vb_w = vb_h = float("inf")
    else:
        try:
            vb_w, vb_h = float(vb.split()[2]), float(vb.split()[3])
        except (IndexError, ValueError):
            row("structure", "svg", "fail", f"unparsable viewBox {vb!r}")
            vb_w = vb_h = float("inf")
    gen_ok = any("generated by" in c for c in idx.comments)
    row("structure", "svg", "pass" if gen_ok else "warn",
        "generator comment present" if gen_ok else
        "no generator comment (SVG may not come from make_schematic)")
    for eid, n in idx.nodes.items():
        r = n["rect"]
        if r and (r[0] < -TOL or r[1] < -TOL
                  or r[0] + r[2] > vb_w + TOL or r[1] + r[3] > vb_h + TOL):
            row("structure", eid, "fail",
                f"node box ({r[0]:.1f},{r[1]:.1f},{r[2]:.1f},{r[3]:.1f}) "
                f"falls outside the canvas ({vb_w:.0f}x{vb_h:.0f})")

    # ------------------------------------------------------ entity coverage
    for e in model["entities"]:
        n = idx.nodes.get(e["id"])
        if n is None:
            row("entity_coverage", e["id"], "fail", "no node group in the SVG")
        elif n["rect"] is None:
            row("entity_coverage", e["id"], "fail", "node group has no rect")
        elif n["label"] != e["label"]:
            row("entity_coverage", e["id"], "fail",
                f"data-label {n['label']!r} != model label {e['label']!r}")
        else:
            row("entity_coverage", e["id"], "pass", "node present, label matches")

    # ---------------------------------------------------- relation coverage
    drawable = [r for r in model["relations"]
                if r["type"] not in ("contains", "parallels")]
    for r in model["relations"]:
        if r["type"] == "contains":
            backed = any(r["to"] in g["members"] for g in model["groups"])
            row("relation_coverage", r["id"],
                "pass" if backed else "fail",
                "containment drawn as group nesting" if backed else
                f"'{r['to']}' is not a member of any group; containment was "
                f"NOT drawn as nesting")
        elif r["type"] == "parallels":
            row("relation_coverage", r["id"], "skip",
                "parallel/co-listed: rendered as adjacency, no edge to check")
    for r in drawable:
        e = idx.edges.get(r["id"])
        if e is None:
            row("relation_coverage", r["id"], "fail", "no edge group in the SVG")
            continue
        mism = [f"{k}: svg={e[k]!r} model={r[k]!r}" for k in
                ("from", "to", "type", "direction") if e[k] != r[k]]
        if mism:
            row("relation_coverage", r["id"], "fail", "; ".join(mism))
        else:
            row("relation_coverage", r["id"], "pass", "edge present, attrs match")

    # ---------------------------------------------------- marker semantics
    for r in drawable:
        e = idx.edges.get(r["id"])
        if e is None:
            continue  # already failed above
        spec = symbols["relation_types"].get(r["type"], {})
        want_end = spec.get("end")
        want_start = want_end if r["direction"] == "bidirectional" else None
        if r["direction"] == "unknown":
            want_end = want_start = None
        got_end = marker_id_from_url(e["marker_end"])
        got_start = marker_id_from_url(e["marker_start"])
        want_end_id = (symbols["markers"][want_end]["svg_id"]
                       if want_end else None)
        want_start_id = (symbols["markers"][want_start]["svg_id"]
                         if want_start else None)
        if got_end != want_end_id or got_start != want_start_id:
            row("marker_semantics", r["id"], "fail",
                f"marker end: got {got_end}, want {want_end_id}; "
                f"marker start: got {got_start}, want {want_start_id}")
        else:
            row("marker_semantics", r["id"], "pass",
                f"end marker {got_end or 'none'} matches type "
                f"'{r['type']}' direction '{r['direction']}'")
        # dash: unknown direction and 'indirect' must be dashed; direct solid types solid
        want_dashed = (r["direction"] == "unknown"
                       or spec.get("line") == "dashed")
        got_dashed = bool(e["dasharray"])
        if want_dashed != got_dashed:
            row("marker_semantics", r["id"], "fail",
                f"stroke style: got {'dashed' if got_dashed else 'solid'}, "
                f"want {'dashed' if want_dashed else 'solid'}")

    # ---------------------------------------------------- marker geometry
    for r in drawable:
        e = idx.edges.get(r["id"])
        spec = symbols["relation_types"].get(r["type"], {})
        if e is None or not e["axis"]:
            continue
        if r["direction"] == "unknown" or spec.get("end") is None:
            row("marker_geometry", r["id"], "skip",
                "no directional marker on this edge")
            continue
        if r["from"] == r["to"]:
            row("marker_geometry", r["id"], "skip", "self-loop")
            continue
        m = AXIS_RE.match(e["axis"].strip())
        if not m:
            row("marker_geometry", r["id"], "fail",
                f"cannot parse edge axis {e['axis']!r}")
            continue
        start = (float(m.group(1)), float(m.group(2)))
        end = (float(m.group(3)), float(m.group(4)))
        # geometric src/dst as drawn (see make_schematic): for B_to_A the
        # arrow is drawn from model['to'] towards model['from']
        if r["direction"] == "B_to_A":
            gsrc, gdst = r["to"], r["from"]
        else:
            gsrc, gdst = r["from"], r["to"]
        bsrc, bdst = idx.box_of(gsrc), idx.box_of(gdst)
        if bsrc is None or bdst is None:
            row("marker_geometry", r["id"], "fail",
                f"missing box for endpoint {gsrc if bsrc is None else gdst}")
            continue
        csrc, cdst = center(bsrc), center(bdst)
        ok = (dist(end, cdst) < dist(end, csrc)
              and dist(start, csrc) < dist(start, cdst))
        if ok:
            row("marker_geometry", r["id"], "pass",
                f"arrow tip is on the {gdst!r} side (semantic target)")
        else:
            row("marker_geometry", r["id"], "fail",
                f"ARROW POINTS THE WRONG WAY: tip is nearer {gsrc!r} "
                f"(semantic source) than {gdst!r} (semantic target) - "
                f"upstream/downstream is reversed in the drawing")

    # ---------------------------------------------------------- containment
    def member_closure(gid, seen=None):
        seen = seen or set()
        if gid in seen:
            return set()
        seen.add(gid)
        out = set()
        for g in model["groups"]:
            if g["id"] == gid:
                for m in g["members"]:
                    if m in {x["id"] for x in model["entities"]}:
                        out.add(m)
                    else:
                        out |= member_closure(m, seen)
        return out

    all_members: dict[str, set] = {g["id"]: member_closure(g["id"])
                                   for g in model["groups"]}
    for g in model["groups"]:
        gsvg = idx.groups.get(sanitize_id(g["id"])) or idx.groups.get(g["id"])
        if gsvg is None or gsvg["rect"] is None:
            row("containment", g["id"], "fail", "group box missing in the SVG")
            continue
        grect = gsvg["rect"]
        for m in g["members"]:
            mbox = idx.box_of(m)
            if mbox is None:
                row("containment", f"{g['id']}/{m}", "fail",
                    f"member {m!r} has no drawn box")
            elif not inside(mbox, grect):
                row("containment", f"{g['id']}/{m}", "fail",
                    f"member box ({mbox[0]:.1f},{mbox[1]:.1f},"
                    f"{mbox[2]:.1f},{mbox[3]:.1f}) is NOT inside group box "
                    f"({grect[0]:.1f},{grect[1]:.1f},{grect[2]:.1f},"
                    f"{grect[3]:.1f}) - containment drawn as juxtaposition")
            else:
                row("containment", f"{g['id']}/{m}", "pass",
                    "member enclosed by its group box")
        # false containment: non-member nodes trapped inside the group box
        member_ids = all_members[g["id"]]
        for eid, n in idx.nodes.items():
            if eid in member_ids or n["rect"] is None:
                continue
            c = center(n["rect"])
            if (grect[0] <= c[0] <= grect[0] + grect[2]
                    and grect[1] <= c[1] <= grect[1] + grect[3]):
                row("containment", g["id"], "fail",
                    f"node {eid!r} is NOT a member but its box center "
                    f"({c[0]:.1f},{c[1]:.1f}) lies inside the group box - "
                    f"the drawing implies a containment the model does not "
                    f"assert")

    # ------------------------------------------------------------- text fit
    for eid, n in idx.nodes.items():
        if not n["texts"] or n["rect"] is None:
            continue
        # main label lines are the texts at F_LABEL size
        sizes = []
        for t in children(n["el"], "text"):
            try:
                sizes.append(float(t.get("font-size") or F_LABEL))
            except ValueError:
                sizes.append(F_LABEL)
        main = [ln for ln, fs in zip(n["texts"], sizes) if abs(fs - F_LABEL) < 0.5]
        lines = main or n["texts"]
        maxw = max((est_text_width(ln, F_LABEL) for ln in lines), default=0)
        avail = n["rect"][2] - 2 * PAD_X
        if maxw > avail + 1.0:
            row("text_fit", eid, "warn",
                f"estimated label width {maxw:.1f} exceeds box width "
                f"{n['rect'][2]:.1f} - 2*{PAD_X:.0f} = {avail:.1f}; text may "
                f"overflow, consider a shorter label or re-render")
        else:
            row("text_fit", eid, "pass", "label fits its box")

    # ------------------------------------------------------ layout overlap
    def overlap_area(a, b):
        w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
        h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
        return (w * h) if (w > TOL and h > TOL) else 0.0

    node_ids = sorted(n for n, v in idx.nodes.items() if v["rect"])
    for i, a in enumerate(node_ids):
        for b in node_ids[i + 1:]:
            ov = overlap_area(idx.nodes[a]["rect"], idx.nodes[b]["rect"])
            if ov > 0:
                row("layout_overlap", f"{a}|{b}", "fail",
                    f"node boxes overlap by {ov:.1f} svg units - labels are "
                    f"colliding; use shorter labels or a wider canvas_width")
    group_ids = sorted(g for g, v in idx.groups.items() if v["rect"])
    for i, a in enumerate(group_ids):
        for b in group_ids[i + 1:]:
            # sibling groups may legitimately nest; flag only partial overlaps
            ra, rb = idx.groups[a]["rect"], idx.groups[b]["rect"]
            ov = overlap_area(ra, rb)
            if ov > 0 and not inside(ra, rb) and not inside(rb, ra):
                row("layout_overlap", f"{a}|{b}", "fail",
                    f"group boxes partially overlap by {ov:.1f} svg units "
                    f"(neither contains the other) - containment is ambiguous")
    if not any(r["check"] == "layout_overlap" for r in rows):
        row("layout_overlap", "nodes+groups", "pass",
            "no node/node or ambiguous group/group overlaps")

    # ----------------------------------------------------- legend coverage
    drawn_types = {r["type"] for r in drawable}
    if model["groups"]:
        drawn_types.add("contains")
    for t in sorted(drawn_types):
        if t in idx.legend_types:
            row("legend_coverage", t, "pass", "legend item present")
        else:
            row("legend_coverage", t, "fail",
                "relation type is drawn but has no legend item")

    fails = [r for r in rows if r["status"] == "fail"]
    warns = [r for r in rows if r["status"] == "warn"]
    return {
        "status": "fail" if fails else "pass",
        "model_entities": len(model["entities"]),
        "model_relations": len(model["relations"]),
        "svg_nodes": len(idx.nodes),
        "svg_edges": len(idx.edges),
        "svg_groups": len(idx.groups),
        "fail_count": len(fails),
        "warn_count": len(warns),
        "checks": rows,
        "verified_at": now_iso(),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model", help="figure model JSON the SVG was rendered from")
    ap.add_argument("svg", help="rendered SVG file")
    ap.add_argument("--out", help="optional JSON report path")
    args = ap.parse_args()

    try:
        symbols = load_symbols()
        model = load_model(args.model)
        report = verify(model, symbols, args.svg)
    except (OSError, ValueError, json.JSONDecodeError, ET.ParseError) as e:
        print(json.dumps({"status": "invalid_input",
                          "error": f"{type(e).__name__}: {e}"},
                         ensure_ascii=False, indent=2))
        sys.exit(2)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    sys.exit(0 if report["status"] == "pass" else 1)


if __name__ == "__main__":
    main()
