#!/usr/bin/env python3
"""Standalone verification of a finished output bundle.

Usage:
  python scripts/check_figure.py --outdir out/ [--sources sources.json]

Re-runs every check (SVG structure, font floor, canvas bounds, mapping
completeness, quote-vs-material, contrast, exports) and writes
out/issues.json. Exit 0 = no errors (warnings allowed); exit 1 = errors.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ga_lib import validate as V  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--sources", default=None,
                    help="JSON {file: extracted text} to verify quotes against the material")
    args = ap.parse_args()

    svg_path = os.path.join(args.outdir, "graphical_abstract.svg")
    map_path = os.path.join(args.outdir, "element_map.json")
    rep_path = os.path.join(args.outdir, "export_report.json")

    missing_dir = []
    if not os.path.exists(svg_path):
        missing_dir.append(svg_path)
    if not os.path.exists(map_path):
        missing_dir.append(map_path)
    if missing_dir:
        print(f"[check] MISSING: {missing_dir}")
        return 1

    with open(map_path, "r", encoding="utf-8") as f:
        elements = json.load(f)
    source_texts = None
    if args.sources and os.path.exists(args.sources):
        with open(args.sources, "r", encoding="utf-8") as f:
            source_texts = json.load(f)

    exports = {
        "svg": svg_path,
        "png": os.path.join(args.outdir, "graphical_abstract.png"),
        "pdf": os.path.join(args.outdir, "graphical_abstract.pdf"),
    }
    issues = V.run_all(None, svg_path, exports, elements, source_texts)
    # add layout issues recorded at build time
    if os.path.exists(rep_path):
        with open(rep_path, "r", encoding="utf-8") as f:
            rep = json.load(f)
        for i in rep.get("layout", {}).get("issues", []):
            issues.append(i)

    out_path = os.path.join(args.outdir, "issues.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(issues, f, ensure_ascii=False, indent=1)

    s = V.summarize(issues)
    for i in issues:
        tag = "ERROR" if i["severity"] == "error" else "WARN "
        where = f" [{i['where']}]" if i.get("where") else ""
        print(f"[check] {tag} {i['code']}: {i['detail']}{where}")
    print(f"[check] {s['n_errors']} errors, {s['n_warnings']} warnings -> {out_path}")
    print(f"[check] PASS={s['pass']}")
    return 0 if s["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
