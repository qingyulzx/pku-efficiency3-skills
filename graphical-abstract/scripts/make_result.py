#!/usr/bin/env python3
"""Assemble result.json from the case's output_contract.

Stage 1 (do this FIRST, before any drawing):
  python scripts/make_result.py --case /input/case.json --out result.json --stage init
  -> writes every contract field as explicit null + pending reasons, so a
     crash later still leaves a contract-complete deliverable.

Stage 2 (after the figure is built and checked):
  python scripts/make_result.py --case /input/case.json --out result.json --stage final \
      --values values.json --map out/element_map.json \
      --export out/export_report.json --issues out/issues.json \
      --status complete|partial [--limits-file limits.json]

values.json is written by you (the agent): {any_key: value}. Keys are matched
to contract fields by name, then containment, then description keywords;
unmatched contract fields stay null with an explicit reason - never invent.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ga_lib import contract as C  # noqa: E402


def load_json(path):
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True, help="/input/case.json")
    ap.add_argument("--out", required=True, help="result.json path")
    ap.add_argument("--stage", choices=["init", "final"], default="init")
    ap.add_argument("--values", help="agent-authored {key: value} JSON")
    ap.add_argument("--map", help="out/element_map.json")
    ap.add_argument("--export", help="out/export_report.json")
    ap.add_argument("--issues", help="out/issues.json")
    ap.add_argument("--status", default="partial", choices=["complete", "partial"])
    ap.add_argument("--limits-file", help="JSON list of limitation strings")
    ap.add_argument("--uncertainty", default="")
    args = ap.parse_args()

    case = load_json(args.case)
    if case is None:
        print(f"[result] case file not found: {args.case}")
        return 1
    fields = C.parse_contract(case)
    case_id = case.get("case_id") or case.get("id") or case.get("caseId")
    print(f"[result] case_id={case_id}, {len(fields)} contract fields")

    if args.stage == "init":
        result = {"case_id": case_id, "status": "pending"}
        for cf in fields:
            result[cf["field"]] = None
            result.setdefault("_pending_reasons", {})[cf["field"]] = (
                "not yet produced; will be filled by make_result.py --stage final")
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        print(f"[result] init scaffold -> {args.out} ({len(fields)} null fields)")
        return 0

    values = load_json(args.values) or {}
    element_map = load_json(args.map) or []
    export = load_json(args.export) or {}
    issues = load_json(args.issues) or []
    limits = load_json(args.limits_file) or []

    # auto-inject evidence bundles as candidate values so standard contract
    # field names (element_source_map, export_checks, ...) match even when the
    # agent did not restate them in values.json
    auto = {}
    if element_map:
        auto["element_source_map"] = element_map
        auto["element_map"] = element_map
    if export:
        auto.setdefault("export_checks", {"layout": export.get("layout"),
                                          "svg": export.get("svg"),
                                          "png": export.get("png"),
                                          "pdf": export.get("pdf"),
                                          "failures": export.get("failures", []),
                                          "checks": export.get("checks")})
        auto.setdefault("export_report", export)
    if issues:
        auto.setdefault("issues", issues)
    for k, v in auto.items():
        values.setdefault(k, v)

    evidence = {
        "element_source_map": element_map,
        "export_report": {k: v for k, v in export.items() if k != "issues"},
        "issues": issues,
    }
    result = C.build_result(case, values, evidence)
    result["status"] = args.status
    result["limits"] = limits + [
        i["detail"] for i in issues if i["severity"] == "warning"]
    n_err = sum(1 for i in issues if i.get("severity") == "error")
    if n_err and args.status == "complete":
        result["status"] = "partial"
        result["limits"].append(
            f"status downgraded complete->partial: {n_err} error-level check(s) failed; see evidence.issues")
    if args.uncertainty:
        result["uncertainty"] = args.uncertainty
    for f in export.get("failures", []):
        result["limits"].append(f"export failure ({f['file']}): {f['error']}")

    out_dir = os.path.dirname(os.path.abspath(args.out))
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)

    unfilled = [k for k, v in result.items()
                if v is None and k not in ("case_id",) and not k.startswith("_")]
    m = C.match(fields, values)
    print(f"[result] final -> {args.out}  status={args.status}")
    print(f"[result] matched {len(m['matches'])}/{len(fields)} contract fields "
          f"(level counts: "
          + ", ".join(f"L{i}={sum(1 for _, (l, _) in m['matches'].items() if l == i)}" for i in (1, 2, 3))
          + ")")
    if unfilled:
        print(f"[result] UNFILLED (null) fields: {unfilled}")
        print("[result] add the missing keys to values.json and re-run this command")
    return 0


if __name__ == "__main__":
    sys.exit(main())
