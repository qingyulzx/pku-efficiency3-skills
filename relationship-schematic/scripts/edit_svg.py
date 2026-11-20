#!/usr/bin/env python3
"""edit_svg.py - source-preserving local edits to a rendered schematic SVG.

Philosophy: edit the addressed elements in place; never re-layout, never
redraw. After editing, every surviving element is compared against the
pre-edit tree (tag + attributes + text, addressed by id or by
parent+tag+position) and the edit report contains a "preserved" section that
proves untouched elements did not change. A change log comment is appended
inside the SVG and a sidecar JSON report is written.

Edits that would silently alter MEANING are REFUSED with guidance instead of
being approximated:
  - set_edge_direction: arrow geometry is derived from the layout; flipping
    an attribute without re-routing the path would produce a lying arrow.
    Re-render from model.json instead (edit the model, not the SVG).
  - deleting a node that still has edges attached: would leave dangling
    arrows implying relations that no longer exist.
  - unknown ops / unknown ids.

Edit spec (JSON file or "-" for stdin): {"ops": [ ... ]}, each op needs a
"reason" that is recorded in the edit log:

  {"op": "relabel_node",   "id": "APC", "label": "APC (truncated)", "reason": "..."}
  {"op": "set_node_color", "id": "APC", "color": "#FBE3E4",        "reason": "..."}
  {"op": "set_edge_type",  "id": "r1",  "type": "inhibits",         "reason": "..."}
  {"op": "set_edge_label", "id": "r1",  "label": "Ub",              "reason": "..."}
  {"op": "set_title",      "text": "New figure title",              "reason": "..."}
  {"op": "delete_element", "id": "r1",                              "reason": "..."}

"id" accepts the model id (entity/relation/group) or the full element id
(node-APC, edge-r1, legend-item-inhibits, ...).

Usage:
  python edit_svg.py figure.svg edits.json -o figure_edited.svg [--out report.json]
Exit: 0 = at least one op applied, none refused; 3 = some ops refused (others
      may still be applied); 2 = unusable input / hard failure.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schematic_lib import load_symbols, sanitize_id, wrap_label, est_text_width  # noqa: E402
from make_schematic import (  # keep in sync with the renderer  # noqa: E402
    C_SUB, C_TEXT, F_ELABEL, F_LABEL, F_SUB, FONT_STACK, PAD_X, PAD_Y,
)

AXIS_RE = re.compile(r"M\s*(-?[\d.]+),(-?[\d.]+)\s+(-?[\d.]+),(-?[\d.]+)")


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")


def local(el) -> str:
    t = el.tag
    return t.split("}")[-1] if isinstance(t, str) else ""


def is_element(el) -> bool:
    return isinstance(getattr(el, "tag", None), str)


def children(el, name):
    return [c for c in el if local(c) == name]


def parent_map(root):
    return {c: p for p in root.iter() for c in p if is_element(c)}


# ---------------------------------------------------------- preservation

def collect_sigs(root) -> dict:
    """Signature of every element addressed stably (id, or parent+tag+nth).
    Comments/PIs are ignored (they carry no drawing state)."""
    sigs: dict = {}

    def key_of(el, parent):
        if el.get("id"):
            return ("id", el.get("id"))
        if parent is None:
            return ("root",)  # the root svg element itself
        pid = parent.get("id") if parent is not None and parent.get("id") else ""
        n = 0
        for c in parent:
            if not is_element(c):
                continue
            if c is el:
                return ("sub", pid, local(el), n)
            if local(c) == local(el):
                n += 1
        return ("sub", pid, local(el), n)

    def walk(el, parent):
        sigs[key_of(el, parent)] = {
            "tag": local(el),
            "attrib": sorted(el.attrib.items()),
            "text": (el.text or "").strip()[:120],
        }
        for c in el:
            if is_element(c):
                walk(c, el)

    walk(root, None)
    return sigs


# ------------------------------------------------------------- op helpers

def find_g_by_model_id(root, model_id: str):
    """Resolve a model id (entity / relation / group) or a full element id
    to its <g> element."""
    candidates = [model_id, f"node-{sanitize_id(model_id)}",
                  f"edge-{sanitize_id(model_id)}", f"group-{sanitize_id(model_id)}",
                  f"legend-item-{sanitize_id(model_id)}"]
    for el in root.iter():
        if is_element(el) and el.get("id") in candidates:
            return el
    return None


def resolve_targets(root, op_id: str):
    el = find_g_by_model_id(root, op_id)
    if el is not None:
        return el
    # exact id match on any element (e.g. legend-extra-0)
    for el in root.iter():
        if is_element(el) and el.get("id") == op_id:
            return el
    return None


def svg_text(x, y, content, size, fill, extra=""):
    t = ET.Element("text", {
        "x": f"{x:.2f}", "y": f"{y:.2f}", "font-family": FONT_STACK,
        "font-size": f"{size:.2f}", "text-anchor": "middle", "fill": fill,
    })
    if extra:
        t.set("data-role", extra)
    t.text = content
    return t


# ------------------------------------------------------------------- ops

def op_relabel_node(root, op, symbols, rows):
    el = resolve_targets(root, op["id"])
    if el is None or not (el.get("id") or "").startswith("node-"):
        rows.append({"op": "relabel_node", "id": op.get("id"), "status": "refused",
                     "detail": "no node element found for this id"})
        return
    rects = children(el, "rect")
    if not rects:
        rows.append({"op": "relabel_node", "id": op.get("id"), "status": "failed",
                     "detail": "node group has no rect; cannot place text"})
        return
    r = rects[0]
    x, y, w, h = (float(r.get("x")), float(r.get("y")),
                  float(r.get("width")), float(r.get("height")))
    label = str(op["label"])
    etype = el.get("data-type") or ""
    lines = wrap_label(label, w - 2 * PAD_X, F_LABEL) or [""]
    # remove existing texts, keep everything else
    for t in children(el, "text"):
        el.remove(t)
    ty = y + PAD_Y + F_LABEL * 0.78
    for ln in lines:
        el.append(svg_text(x + w / 2, ty, ln, F_LABEL, C_TEXT))
        ty += F_LABEL + 3.5
    if etype:
        el.append(svg_text(x + w / 2, ty - 1, etype, F_SUB, C_SUB))
    el.set("data-label", label)
    # honest fit warnings (box is preserved by design; growing it would move
    # neighbours, which is a re-render decision, not a local edit)
    notes = []
    maxw = max((est_text_width(ln, F_LABEL) for ln in lines), default=0)
    if maxw > w - 2 * PAD_X + 1.0:
        notes.append(f"label width {maxw:.1f} exceeds box {w:.1f}-2*{PAD_X:.0f}; "
                     f"text may overflow - prefer re-render for long labels")
    need_h = len(lines) * (F_LABEL + 3.5) + 2 * PAD_Y + ((F_SUB + 4.0) if etype else 0)
    if need_h > h + 1.0:
        notes.append(f"label needs ~{need_h:.0f} height but box is {h:.0f}")
    rows.append({"op": "relabel_node", "id": op.get("id"), "status": "applied",
                 "detail": "; ".join(notes) if notes else "label replaced in place"})


def op_set_node_color(root, op, symbols, rows):
    el = resolve_targets(root, op["id"])
    if el is None or not (el.get("id") or "").startswith("node-"):
        rows.append({"op": "set_node_color", "id": op.get("id"), "status": "refused",
                     "detail": "no node element found for this id"})
        return
    color = str(op["color"])
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        rows.append({"op": "set_node_color", "id": op.get("id"), "status": "refused",
                     "detail": f"color must be #rrggbb, got {color!r}"})
        return
    rects = children(el, "rect")
    if not rects:
        rows.append({"op": "set_node_color", "id": op.get("id"), "status": "failed",
                     "detail": "node group has no rect"})
        return
    rects[0].set("fill", color)
    rows.append({"op": "set_node_color", "id": op.get("id"), "status": "applied",
                 "detail": f"fill set to {color}"})


def op_set_edge_type(root, op, symbols, rows):
    el = resolve_targets(root, op["id"])
    if el is None or not (el.get("id") or "").startswith("edge-"):
        rows.append({"op": "set_edge_type", "id": op.get("id"), "status": "refused",
                     "detail": "no edge element found for this id"})
        return
    rtype = str(op["type"])
    spec = symbols["relation_types"].get(rtype)
    if spec is None:
        rows.append({"op": "set_edge_type", "id": op.get("id"), "status": "refused",
                     "detail": f"unknown relation type {rtype!r}; valid: "
                               f"{sorted(symbols['relation_types'])}"})
        return
    direction = el.get("data-direction") or "A_to_B"
    paths = [p for p in children(el, "path") if p.get("stroke") not in (None, "none")]
    if not paths:
        rows.append({"op": "set_edge_type", "id": op.get("id"), "status": "failed",
                     "detail": "edge group has no stroked path"})
        return
    p = paths[0]
    end_marker = spec.get("end")
    if direction == "unknown":
        p.attrib.pop("marker-end", None)
        p.attrib.pop("marker-start", None)
        p.set("stroke-dasharray", symbols["line_styles"]["dashed"]["stroke_dasharray"])
    else:
        if end_marker:
            p.set("marker-end", f"url(#{symbols['markers'][end_marker]['svg_id']})")
        else:
            p.attrib.pop("marker-end", None)
        if direction == "bidirectional" and end_marker:
            p.set("marker-start", f"url(#{symbols['markers'][end_marker]['svg_id']})")
        else:
            p.attrib.pop("marker-start", None)
        dash = symbols["line_styles"][spec["line"]]["stroke_dasharray"]
        if dash:
            p.set("stroke-dasharray", dash)
        else:
            p.attrib.pop("stroke-dasharray", None)
    el.set("data-type", rtype)
    rows.append({"op": "set_edge_type", "id": op.get("id"), "status": "applied",
                 "detail": f"type -> {rtype} (marker/line updated from symbol "
                           f"library; direction kept as {direction})"})


def op_set_edge_label(root, op, symbols, rows):
    el = resolve_targets(root, op["id"])
    if el is None or not (el.get("id") or "").startswith("edge-"):
        rows.append({"op": "set_edge_label", "id": op.get("id"), "status": "refused",
                     "detail": "no edge element found for this id"})
        return
    label = str(op["label"])
    texts = children(el, "text")
    if texts:
        texts[0].text = label
        rows.append({"op": "set_edge_label", "id": op.get("id"), "status": "applied",
                     "detail": "existing edge label replaced"})
        return
    # create a label at the axis midpoint (approximate placement)
    axis = None
    for p in children(el, "path"):
        if p.get("data-role") == "edge-axis":
            axis = p.get("d")
    if not axis:
        rows.append({"op": "set_edge_label", "id": op.get("id"), "status": "failed",
                     "detail": "edge has neither a label nor an edge-axis path "
                               "to place one on"})
        return
    m = AXIS_RE.match(axis.strip())
    if not m:
        rows.append({"op": "set_edge_label", "id": op.get("id"), "status": "failed",
                     "detail": f"cannot parse axis {axis!r}"})
        return
    mx = (float(m.group(1)) + float(m.group(3))) / 2
    my = (float(m.group(2)) + float(m.group(4))) / 2
    tw = est_text_width(label, F_ELABEL)
    bg = ET.Element("rect", {
        "x": f"{mx - tw / 2 - 3:.2f}", "y": f"{my - F_ELABEL * 0.72:.2f}",
        "width": f"{tw + 6:.2f}", "height": f"{F_ELABEL * 0.95:.2f}",
        "fill": "#FFFFFF", "fill-opacity": "0.9", "stroke": "none"})
    el.append(bg)
    el.append(svg_text(mx, my, label, F_ELABEL, C_TEXT))
    rows.append({"op": "set_edge_label", "id": op.get("id"), "status": "applied",
                 "detail": "label created at the edge axis midpoint (approximate "
                           "placement; re-render for exact bezier-mid placement)"})


def op_set_title(root, op, symbols, rows):
    text = str(op["text"])
    for el in root.iter():
        if not is_element(el):
            continue
        if (el.get("id") == "title" and local(el) == "g"):
            for t in children(el, "text"):
                if t.get("data-role") == "title":
                    t.text = text
                    rows.append({"op": "set_title", "id": "title", "status": "applied",
                                 "detail": "title text replaced in place"})
                    return
    # foreign SVG without our title group: replace the largest-font text
    best, best_size = None, -1.0
    for el in root.iter():
        if is_element(el) and local(el) == "text":
            try:
                size = float(el.get("font-size") or 0)
            except ValueError:
                size = 0.0
            if size > best_size:
                best, best_size = el, size
    if best is not None:
        best.text = text
        rows.append({"op": "set_title", "id": "title", "status": "applied",
                     "detail": "no g#title found; replaced the largest-font text "
                               "element (best-effort on a foreign SVG)"})
    else:
        rows.append({"op": "set_title", "id": "title", "status": "refused",
                     "detail": "no text element found to use as title"})


def op_delete_element(root, op, symbols, rows, pmap):
    el = resolve_targets(root, op["id"])
    if el is None:
        rows.append({"op": "delete_element", "id": op.get("id"), "status": "refused",
                     "detail": "no element found for this id"})
        return
    gid = el.get("id") or ""
    # refuse deleting a node that edges still point at
    if gid.startswith("node-"):
        entity = el.get("data-entity-id") or gid[5:]
        attached = []
        for e in root.iter():
            if is_element(e) and (e.get("id") or "").startswith("edge-"):
                if e.get("data-from") == entity or e.get("data-to") == entity:
                    attached.append(e.get("data-relation-id") or e.get("id"))
        if attached:
            rows.append({"op": "delete_element", "id": op.get("id"), "status": "refused",
                         "detail": f"node '{entity}' still has edges attached "
                                   f"({', '.join(sorted(set(attached)))}); deleting "
                                   f"it would leave arrows implying relations "
                                   f"without both endpoints - delete the edges "
                                   f"first or re-render from an edited model"})
            return
    parent = pmap.get(el)
    if parent is None:
        rows.append({"op": "delete_element", "id": op.get("id"), "status": "failed",
                     "detail": "element has no parent (root svg?)"})
        return
    parent.remove(el)
    rows.append({"op": "delete_element", "id": op.get("id"), "status": "applied",
                 "detail": f"element {gid!r} removed"})


OPS = {
    "relabel_node": op_relabel_node,
    "set_node_color": op_set_node_color,
    "set_edge_type": op_set_edge_type,
    "set_edge_label": op_set_edge_label,
    "set_title": op_set_title,
}


def apply_edits(svg_path, edits, out_path):
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    tree = ET.parse(svg_path, parser)
    root = tree.getroot()
    symbols = load_symbols()

    before = collect_sigs(root)
    rows: list[dict] = []
    pmap = parent_map(root)

    for i, op in enumerate(edits.get("ops", [])):
        if not isinstance(op, dict) or "op" not in op:
            rows.append({"op": f"#{i}", "id": op.get("id") if isinstance(op, dict) else None,
                         "status": "refused", "detail": "op must be an object with an 'op' key"})
            continue
        name = op["op"]
        reason = str(op.get("reason", "")).strip()
        if not reason:
            rows.append({"op": name, "id": op.get("id"), "status": "refused",
                         "detail": "every op needs a 'reason' for the edit log"})
            continue
        if name == "delete_element":
            op_delete_element(root, op, symbols, rows, pmap)
        elif name == "set_edge_direction":
            rows.append({"op": name, "id": op.get("id"), "status": "refused",
                         "detail": "REFUSED BY DESIGN: arrow geometry is derived "
                                   "from the layout; editing the direction "
                                   "attribute without re-routing would draw a "
                                   "lying arrow. Edit model.json and re-render "
                                   "with make_schematic.py instead."})
        elif name in OPS:
            OPS[name](root, op, symbols, rows)
        else:
            rows.append({"op": name, "id": op.get("id"), "status": "refused",
                         "detail": f"unknown op; valid: {sorted(OPS)} + delete_element"})
        # stamp the reason on the last row of this op
        for rrow in reversed(rows):
            if rrow.get("op") == name and rrow.get("id") == op.get("id") and "_reason" not in rrow:
                rrow["reason"] = reason
                break

    after = collect_sigs(root)
    # preservation diff: keys touched by applied ops are excluded. A key is
    # "touched" when the op's target id (or its sanitised form) appears in
    # the key tuple - this covers both ("id","node-X") and
    # ("sub","node-X","rect",0) style keys of the edited subtree.
    touched_keys = set()
    for rrow in rows:
        if rrow["status"] == "applied" and rrow.get("id"):
            ident = str(rrow["id"])
            sid = sanitize_id(ident)
            for k in set(before) | set(after):
                ks = str(k)
                if ident in ks or (sid != ident and sid in ks):
                    touched_keys.add(k)
    changed = []
    for k in sorted(set(before) | set(after), key=str):
        if k in touched_keys:
            continue
        if before.get(k) != after.get(k):
            changed.append({"element": str(k),
                            "before": before.get(k), "after": after.get(k)})
    removed = [str(k) for k in before if k not in after and k not in touched_keys]

    # edit-log comment appended inside the svg
    applied = [r for r in rows if r["status"] == "applied"]
    summary = "; ".join(f"{r['op']}:{r.get('id') or r.get('op')}" for r in applied)
    root.append(ET.Comment(
        f" edit_svg: {len(applied)} op(s) applied {now_iso()}: {summary} "))

    xml = ET.tostring(root, encoding="unicode")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n' + xml + "\n")

    refused = [r for r in rows if r["status"] == "refused"]
    failed = [r for r in rows if r["status"] == "failed"]
    return {
        "status": ("ok" if applied and not refused and not failed
                   else "partial" if applied else "failed"),
        "svg_in": os.path.abspath(svg_path),
        "svg_out": os.path.abspath(out_path),
        "ops": rows,
        "applied": len(applied), "refused": len(refused), "failed": len(failed),
        "preserved": {
            "elements_before": len(before),
            "elements_after": len(after),
            "changed_unexpectedly": changed,
            "removed_unexpectedly": removed,
            "ok": not changed and not removed,
        },
        "edited_at": now_iso(),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("svg", help="SVG to edit")
    ap.add_argument("edits", help="edits JSON file, or - for stdin")
    ap.add_argument("-o", "--output", required=True, help="edited SVG path")
    ap.add_argument("--out", help="optional JSON edit report path")
    args = ap.parse_args()

    try:
        raw = sys.stdin.read() if args.edits == "-" else open(
            args.edits, "r", encoding="utf-8").read()
        edits = json.loads(raw)
        if not isinstance(edits, dict):
            raise ValueError("edits root must be an object like {\"ops\": [...]}")
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(json.dumps({"status": "invalid_input",
                          "error": f"{type(e).__name__}: {e}"},
                         ensure_ascii=False, indent=2))
        sys.exit(2)

    try:
        report = apply_edits(args.svg, edits, args.output)
    except (OSError, ET.ParseError) as e:
        print(json.dumps({"status": "invalid_input",
                          "error": f"{type(e).__name__}: {e}"},
                         ensure_ascii=False, indent=2))
        sys.exit(2)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    if report["refused"] or report["failed"]:
        sys.exit(3)
    sys.exit(0)


if __name__ == "__main__":
    main()
