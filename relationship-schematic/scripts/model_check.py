#!/usr/bin/env python3
"""model_check.py - pre-render validation of a figure model ("draw-time self-check").

Runs the full static check battery on a figure model JSON before anything is
drawn: evidence quotes on every entity/relation, endpoint integrity, relation
type and direction vocabulary, containment cycles and dangling group members.

Prints a machine-readable findings report and exits:
  0  no errors (warnings allowed)
  1  errors found - make_schematic will refuse to draw until they are fixed
  2  unusable input (file missing, invalid JSON, wrong shape)

Usage:
  python model_check.py model.json [--out report.json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schematic_lib import check_model, findings_report, load_model, load_symbols  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model", help="figure model JSON (entities + relations)")
    ap.add_argument("--out", help="optional path for the JSON findings report")
    args = ap.parse_args()

    try:
        symbols = load_symbols()
        model = load_model(args.model)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(json.dumps({"status": "invalid_input",
                          "error": f"{type(e).__name__}: {e}"},
                         ensure_ascii=False, indent=2))
        sys.exit(2)

    findings = check_model(model, symbols)
    rep = findings_report(findings)
    rep["status"] = "ok" if rep["error_count"] == 0 else "errors"
    rep["model"] = os.path.abspath(args.model)
    rep["entities"] = len(model["entities"])
    rep["relations"] = len(model["relations"])
    rep["groups"] = len(model["groups"])
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
    sys.exit(0 if rep["error_count"] == 0 else 1)


if __name__ == "__main__":
    main()
