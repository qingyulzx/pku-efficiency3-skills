#!/usr/bin/env python3
"""Build a graphical abstract from a figure_model.json.

Usage:
  python scripts/build_figure.py --model figure_model.json --outdir out/ [--png-dpi 300]

Outputs (all deterministic for the same model):
  out/graphical_abstract.svg     editable source (ids, layers, provenance descs)
  out/graphical_abstract.png     raster export (default 300 dpi)
  out/graphical_abstract.pdf     vector export
  out/element_map.json           element -> source -> encoding mapping
  out/export_report.json         which exports succeeded, sizes, checks

Exit codes: 0 = SVG built (other exports may have failed, see report);
            2 = model invalid; 3 = SVG build failed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ga_lib import load_model, build_from_model, ModelError  # noqa: E402
from ga_lib.svg_writer import write_svg  # noqa: E402
from ga_lib import validate as V  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--png-dpi", type=float, default=300.0)
    ap.add_argument("--sources", default=None,
                    help="optional JSON {file: text} to verify quotes against material")
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    try:
        model = load_model(args.model)
    except ModelError as e:
        print(f"[build] MODEL INVALID:\n{e}")
        return 2

    svg_path = os.path.join(args.outdir, "graphical_abstract.svg")
    png_path = os.path.join(args.outdir, "graphical_abstract.png")
    pdf_path = os.path.join(args.outdir, "graphical_abstract.pdf")
    map_path = os.path.join(args.outdir, "element_map.json")
    rep_path = os.path.join(args.outdir, "export_report.json")

    scene, report, elements = build_from_model(model)

    # --- SVG: the non-negotiable editable source --------------------------
    try:
        svg_info = write_svg(scene, svg_path)
    except Exception:
        print("[build] SVG write FAILED (this is fatal):")
        traceback.print_exc()
        return 3
    print(f"[build] SVG  {svg_path}  ({svg_info['elements']} elements, {svg_info['layers']} layers)")

    # --- exports: each failure degrades, never aborts ----------------------
    export_report = {"svg": {"path": svg_path, "bytes": svg_info["bytes"],
                             "elements": svg_info["elements"]}, "failures": []}
    from ga_lib.mpl_writer import write_png, write_pdf
    try:
        info = write_png(scene, png_path, dpi=args.png_dpi)
        export_report["png"] = {"path": png_path, "bytes": os.path.getsize(png_path),
                                **info}
        print(f"[build] PNG  {png_path}  (backend {info['backend']}, {args.png_dpi} dpi)")
    except Exception as e:
        export_report["failures"].append({"file": "png", "error": str(e),
                                          "remedy": "see references/exception_playbook.md #png-export-failed"})
        print(f"[build] PNG export FAILED: {e}")
    try:
        info = write_pdf(scene, pdf_path)
        export_report["pdf"] = {"path": pdf_path, "bytes": os.path.getsize(pdf_path),
                                **info}
        print(f"[build] PDF  {pdf_path}  (backend {info['backend']})")
    except Exception as e:
        export_report["failures"].append({"file": "pdf", "error": str(e),
                                          "remedy": "see references/exception_playbook.md #pdf-export-failed"})
        print(f"[build] PDF export FAILED: {e}")

    export_report["layout"] = report
    export_report["model_file"] = os.path.abspath(args.model)

    # --- element map + quick checks ----------------------------------------
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(elements, f, ensure_ascii=False, indent=1)
    print(f"[build] MAP  {map_path}  ({len(elements)} mapped elements)")

    source_texts = None
    if args.sources and os.path.exists(args.sources):
        with open(args.sources, "r", encoding="utf-8") as f:
            source_texts = json.load(f)
    issues = V.run_all(model, svg_path,
                       {"svg": svg_path, "png": png_path if os.path.exists(png_path) else "",
                        "pdf": pdf_path if os.path.exists(pdf_path) else ""},
                       elements, source_texts)
    export_report["issues"] = issues
    export_report["checks"] = V.summarize(issues)
    with open(rep_path, "w", encoding="utf-8") as f:
        json.dump(export_report, f, ensure_ascii=False, indent=1)
    s = export_report["checks"]
    print(f"[build] checks: {s['n_errors']} errors, {s['n_warnings']} warnings "
          f"({rep_path})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
