#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_consistency.py -- bidirectional consistency verification.

This is the "did we draw what the material says" gate. It verifies, in both
directions, that the figure and the input material agree:

  Forward (无中生有 / nothing-from-nothing check):
    every element's verbatim source quote must appear in the extracted
    material text (whitespace-normalized). An element whose quote cannot be
    found is either fabricated or mistranscribed and is a HARD FAIL.

  Backward (覆盖 / coverage check):
    the extraction_index lists every component / step the agent found in the
    material; each item must map to a drawn element or carry an explicit
    omission reason. Items left unmapped and unexplained are reported.

  Internal integrity:
    - every IR element id appears as data-id in the rendered SVG
    - every data-id in the SVG exists in the IR
    - connection polylines end on the target element's anchor (no dangling
      arrows), using the sidecar geometry report
    - the four editing layers exist in the SVG

Usage:
  python check_consistency.py intermediate.json material_text.txt figure.svg
       figure.geometry.json --out consistency_report.json

Exit 0 = pass (warnings allowed), 1 = hard failure.
"""
import json
import re
import sys
import xml.etree.ElementTree as ET


def normalize(t):
    if t is None:
        return ""
    t = t.replace("\u00ad", "")           # soft hyphen
    t = t.replace("\u2019", "'").replace("\u2018", "'")
    t = t.replace("\u201c", '"').replace("\u201d", '"')
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def check_quote(quote, norm_material):
    q = normalize(quote)
    return bool(q) and q in norm_material


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 4:
        print(__doc__)
        return 2
    ir_path, mat_path, svg_path, geom_path = args[:4]
    out_path = "consistency_report.json"
    if "--out" in sys.argv:
        out_path = sys.argv[sys.argv.index("--out") + 1]

    with open(ir_path, "r", encoding="utf-8") as f:
        ir = json.load(f)
    with open(mat_path, "r", encoding="utf-8") as f:
        material = f.read()
    with open(geom_path, "r", encoding="utf-8") as f:
        geom = json.load(f)
    norm_mat = normalize(material)

    checks = []
    hard_fail = False

    def report(name, ok, detail, hard=True):
        nonlocal hard_fail
        checks.append({"check": name, "pass": bool(ok), "detail": detail,
                       "severity": "hard" if hard else "soft"})
        if not ok and hard:
            hard_fail = True

    ftype = ir.get("figure_type", "apparatus")
    if ftype == "apparatus":
        elements = list(ir.get("components", []))
        relations = list(ir.get("connections", []))
        rel_key = "connections"
    else:
        elements = list(ir.get("nodes", []))
        relations = list(ir.get("edges", []))
        rel_key = "edges"

    # 1. quote verification (forward, anti-fabrication)
    quote_failures = []
    checked = 0
    for el in elements:
        q = (el.get("source") or {}).get("quote")
        if q:
            checked += 1
            if not check_quote(q, norm_mat):
                quote_failures.append({"id": el.get("id"),
                                       "quote": q[:120]})
    for rl in relations:
        q = (rl.get("source") or {}).get("quote")
        if q:
            checked += 1
            if not check_quote(q, norm_mat):
                quote_failures.append({"id": rl.get("id"), "quote": q[:120]})
    report("source_quotes_verbatim", not quote_failures,
           {"checked": checked, "failures": quote_failures}
           if quote_failures else {"checked": checked,
                                   "note": "all quotes found in material"})

    # 2. coverage via extraction_index (backward)
    idx = ir.get("extraction_index") or []
    unmapped = [it for it in idx
                if it.get("status") != "omitted" and not it.get("mapped_id")]
    bad_idx_quotes = []
    for it in idx:
        if not check_quote(it.get("quote", ""), norm_mat):
            bad_idx_quotes.append(it.get("mention"))
    drawn = [it for it in idx if it.get("mapped_id")]
    omitted = [it for it in idx if it.get("status") == "omitted"]
    report("extraction_index_quotes", not bad_idx_quotes,
           {"bad_quotes": bad_idx_quotes} if bad_idx_quotes else
           {"items": len(idx)})
    report("extraction_index_mapping", not unmapped,
           {"unmapped_items": [it.get("mention") for it in unmapped]}
           if unmapped else
           {"mentioned": len(idx), "drawn": len(drawn),
            "omitted_with_reason": len(omitted)}, hard=True)

    # 3. SVG <-> IR id sets
    try:
        tree = ET.parse(svg_path)
        root = tree.getroot()
    except Exception as exc:
        report("svg_parse", False, {"error": str(exc)})
        print(json.dumps({"pass": False, "checks": checks},
                         ensure_ascii=False, indent=1))
        return 1
    ns = {"svg": "http://www.w3.org/2000/svg"}
    svg_ids = set()
    layers = set()
    for g in root.iter("{http://www.w3.org/2000/svg}g"):
        lid = g.get("id") or ""
        if lid.startswith("layer-"):
            layers.add(lid)
        did = g.get("data-id")
        if did:
            svg_ids.add(did)
    ir_ids = set(el.get("id") for el in elements) | \
        set(r.get("id") for r in relations if r.get("id"))
    missing_in_svg = sorted(ir_ids - svg_ids)
    extra_in_svg = sorted(svg_ids - ir_ids)
    report("svg_covers_ir", not missing_in_svg,
           {"missing_in_svg": missing_in_svg} if missing_in_svg
           else {"elements_with_data_id": len(svg_ids)})
    report("ir_covers_svg", not extra_in_svg,
           {"extra_in_svg": extra_in_svg} if extra_in_svg else
           {"note": "no foreign elements"})
    report("layers_present",
           layers >= {"layer-structure", "layer-annotation", "layer-source",
                      "layer-frame"},
           {"found": sorted(layers)})

    # 4. geometry: arrow endpoints land on target anchors (no dangling arrows)
    dangling = []
    for cid, cinfo in (geom.get("connections") or {}).items():
        end = cinfo.get("end") or [None, None]
        exp = cinfo.get("expected_end") or [None, None]
        if end[0] is None or exp[0] is None:
            continue
        d = ((end[0] - exp[0]) ** 2 + (end[1] - exp[1]) ** 2) ** 0.5
        if d > 2.5:
            dangling.append({"id": cid, "distance": round(d, 2)})
    report("no_dangling_arrows", not dangling,
           {"dangling": dangling} if dangling else
           {"checked": len(geom.get("connections") or {})})

    # 5. warnings collected (soft)
    warns = []
    for el in elements:
        if el.get("certainty") in ("unspecified_spec", "uncertain"):
            warns.append("element %s marked uncertain: %s"
                         % (el.get("id"), el.get("certainty_note", "")))
    for rl in relations:
        if rl.get("certainty") == "inferred":
            warns.append("%s %s is an inferred connection (not verbatim in "
                         "material)" % (rel_key[:-1], rl.get("id")))
    overflow = geom.get("overflow") or []
    if overflow:
        warns.append("text overflow: %s" % overflow)
    checks.append({"check": "warnings", "pass": True, "detail": warns,
                   "severity": "soft"})

    result = {
        "pass": not hard_fail,
        "hard_fail": hard_fail,
        "summary": {
            "elements": len(elements),
            "relations": len(relations),
            "quotes_checked": checked,
            "coverage": {"mentioned": len(idx), "drawn": len(drawn),
                         "omitted": len(omitted)},
        },
        "checks": checks,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if not hard_fail else 1


if __name__ == "__main__":
    sys.exit(main())
