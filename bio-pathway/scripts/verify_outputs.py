#!/usr/bin/env python3
"""verify_outputs.py - read-back verification of the delivered figure bundle.

Re-opens the produced SVG (never trusting in-memory state) and checks that the
figure, the model and result.json agree:
  - every model entity/edge has its SVG element (id match, read back)
  - legend lists exactly the edge/node types used (both directions)
  - no node label overflows its box; canvas within limits
  - exports exist, are non-blank, and their claimed files are real
  - result.json: every contract field is either non-null or has a reason

Usage:
  python verify_outputs.py --model model.json --svg pathway.svg \
      --result result.json [--exports exports_dir] [--report verification-report.json]
"""
import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SVG_NS = "http://www.w3.org/2000/svg"


def q(tag):
    return f"{{{SVG_NS}}}{tag}"


def text_w(s, fs):
    return len(s) * fs * 0.64


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--svg", required=True)
    ap.add_argument("--result")
    ap.add_argument("--exports", nargs="*")
    ap.add_argument("--report")
    args = ap.parse_args()

    checks, errors, warnings = [], [], []

    model = json.loads(Path(args.model).read_text(encoding="utf-8"))
    try:
        tree = ET.parse(args.svg)
    except ET.ParseError as exc:
        print(json.dumps({"errors": [{"message": f"SVG does not parse: {exc}"}],
                          "passed": False}))
        return 2
    root = tree.getroot()

    # ---- 1. element read-back -------------------------------------------
    svg_ids = {el.get("id") for el in root.iter() if el.get("id")}
    node_ids = {f"node-{e['id']}" for e in model.get("entities", [])}
    edge_ids = {f"edge-{e['id']}" for e in model.get("edges", [])}
    missing_nodes = [i[5:] for i in sorted(node_ids - svg_ids)]
    missing_edges = [i[5:] for i in sorted(edge_ids - svg_ids)]
    checks.append({
        "check": "svg_readback_nodes", "passed": not missing_nodes,
        "detail": f"{len(node_ids)} entities -> {len(node_ids & svg_ids)} matched"
                  + (f"; missing: {missing_nodes}" if missing_nodes else "")})
    checks.append({
        "check": "svg_readback_edges", "passed": not missing_edges,
        "detail": f"{len(edge_ids)} edges -> {len(edge_ids & svg_ids)} matched"
                  + (f"; missing: {missing_edges}" if missing_edges else "")})
    for m in missing_nodes:
        errors.append(f"node-{m} missing from SVG")
    for m in missing_edges:
        errors.append(f"edge-{m} missing from SVG")

    # evidence table embedded?
    desc = root.find(q("desc"))
    checks.append({"check": "svg_desc_evidence_table", "passed": desc is not None and
                   "EDGES:" in (desc.text or ""),
                   "detail": "SVG embeds the entity/edge quote table" if desc is not None
                   else "no <desc> block"})
    if desc is None or "EDGES:" not in (desc.text or ""):
        errors.append("SVG missing embedded evidence table (<desc>)")

    # layers present
    layers = {el.get("id") for el in root.findall(q("g")) if el.get("id", "").startswith("layer-")}
    need_layers = {"layer-compartments", "layer-edges", "layer-nodes", "layer-legend"}
    checks.append({"check": "svg_layers", "passed": need_layers <= layers,
                   "detail": f"layers found: {sorted(layers)}"})
    if not need_layers <= layers:
        errors.append(f"missing SVG layers: {need_layers - layers}")

    # ---- 2. legend consistency (both directions) -------------------------
    used_edge_types = {e["type"] for e in model.get("edges", [])}
    used_node_types = {e.get("type", "protein") for e in model.get("entities", [])}
    legend = root.find("*[@id='layer-legend']")
    legend_text = "".join(legend.itertext()) if legend is not None else ""
    legend_missing = []
    spec = json.loads((Path(__file__).parent.parent / "references" /
                       "edge-types.json").read_text(encoding="utf-8"))
    for t in used_edge_types:
        if spec["edge_types"][t]["label"].split(" /")[0].split(" (")[0] not in legend_text:
            legend_missing.append(t)
    for t in used_node_types:
        if f"{t} node" not in legend_text:
            legend_missing.append(t)
    checks.append({"check": "legend_covers_used_types", "passed": not legend_missing,
                   "detail": f"legend covers all {len(used_edge_types)} edge types "
                             f"and {len(used_node_types)} node types used"
                             + (f"; missing: {legend_missing}" if legend_missing else "")})
    if legend_missing:
        errors.append(f"legend missing entries for: {legend_missing}")

    # legend must not advertise unused semantic entries
    legend_edge_labels = [spec["edge_types"][t]["label"].split(" /")[0].split(" (")[0]
                          for t in spec["edge_types"]]
    advertised_unused = [lab for lab in legend_edge_labels
                         if lab in legend_text
                         and not any(spec["edge_types"][e["type"]]["label"].split(" /")[0]
                                     .split(" (")[0] == lab
                                     for e in model.get("edges", []))]
    checks.append({"check": "legend_no_phantom_entries", "passed": not advertised_unused,
                   "detail": "; ".join(advertised_unused) or
                             "no legend entries for unused edge types"})
    if advertised_unused:
        warnings.append(f"legend advertises unused edge types: {advertised_unused}")

    # ---- 3. label overflow ------------------------------------------------
    overflow = []
    for g in root.iter(q("g")):
        gid = g.get("id", "")
        if not gid.startswith("node-"):
            continue
        rect = next((r for r in (g.find(q("rect")), g.find(q("polygon")),
                                  g.find(q("ellipse"))) if r is not None), None)
        label_el = None
        for t in g.findall(q("text")):
            if t.get("class") == "node-label":
                label_el = t
                break
        if label_el is None or rect is None:
            continue
        fs = float(label_el.get("font-size", 15))
        w = text_w(label_el.text or "", fs)
        if rect.tag == q("rect"):
            bw = float(rect.get("width", 0))
        elif rect.tag == q("polygon"):
            xs = [float(p.split(",")[0]) for p in rect.get("points").split()]
            bw = max(xs) - min(xs)
        else:
            bw = 2 * float(rect.get("rx", 0))
        if w > bw + 2:
            overflow.append({"node": gid, "label": label_el.text,
                             "est_width": round(w, 1), "box_width": round(bw, 1)})
    checks.append({"check": "label_overflow", "passed": not overflow,
                   "detail": f"{len(overflow)} labels wider than their boxes"
                             + (f": {overflow[:5]}" if overflow else "")})
    if overflow:
        errors.append(f"label overflow in {len(overflow)} nodes (shorten labels or "
                      "widen nodes via model order)")

    vb = root.get("viewBox", "0 0 0 0").split()
    vw, vh = (vb[2], vb[3]) if len(vb) == 4 else ("0", "0")
    big = int(vw) > 2400 or int(vh) > 1800
    checks.append({"check": "canvas_limits", "passed": not big,
                   "detail": f"canvas {vw}x{vh} (recommended max 2400x1800)"})
    if big:
        warnings.append(f"canvas {vw}x{vh} exceeds recommended maximum; consider "
                        "splitting panels")

    # ---- 4. exports -------------------------------------------------------
    if args.exports:
        for exp in args.exports:
            p = Path(exp)
            if not p.exists():
                errors.append(f"declared export missing: {exp}")
            elif p.stat().st_size == 0:
                errors.append(f"declared export empty: {exp}")
        checks.append({"check": "exports_exist", "passed": not any(
            not Path(e).exists() for e in args.exports),
            "detail": f"{len(args.exports)} declared exports checked"})

    # ---- 5. result.json contract completeness -----------------------------
    if args.result:
        result = json.loads(Path(args.result).read_text(encoding="utf-8"))
        reasons = result.get("_unanswered_reasons", {})
        unexplained_nulls = []
        for k, v in result.items():
            if k.startswith("_"):
                continue
            if v is None and k not in reasons:
                unexplained_nulls.append(k)
        checks.append({"check": "result_contract_nulls_explained",
                       "passed": not unexplained_nulls,
                       "detail": f"{len(unexplained_nulls)} unexplained null fields"
                                 + (f": {unexplained_nulls}" if unexplained_nulls
                                    else "; all nulls carry a reason")})
        if unexplained_nulls:
            errors.append(f"result.json null fields without reason: "
                          f"{unexplained_nulls}")

    out = {"passed": not errors,
           "checks": checks, "errors": errors, "warnings": warnings,
           "model": str(Path(args.model).resolve()),
           "svg": str(Path(args.svg).resolve())}
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(out, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if not errors else 2


if __name__ == "__main__":
    sys.exit(main())
