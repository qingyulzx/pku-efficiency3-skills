#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""finalize_result.py -- result.json lifecycle for the setup-roadmap skill.

The evaluator expects /app/output/result.json with case_id and every
output_contract field filled; a field that cannot be answered must be
explicitly null WITH a reason. This tool manages that lifecycle:

  init      create the skeleton FIRST (before any analysis), so a crash
            later still leaves a well-formed result.json on disk:
              python finalize_result.py --init --case /input/case.json \
                     --out /app/output/result.json

  finalize  after the figure is rendered and verified, check completeness:
            every required field must be non-null, or null together with
            "null_reason". Also attaches artifact paths + file sizes and
            the consistency-check summary:
              python finalize_result.py --finalize \
                     --result /app/output/result.json \
                     --artifact-dir /app/output \
                     [--consistency /app/output/consistency_report.json]

Field names: if the case's output_contract lists fields, those exact
names are used (do not invent new ones); otherwise the built-in template
below is used. Field VALUE SHAPES always follow the case contract; the
agent fills values, this script only verifies presence / null + reason.

Exit codes: 0 ok; 1 incomplete (missing field or null without reason).
"""
import datetime as _dt
import json
import os
import sys

# Built-in fallback template (used only when the case gives no contract).
TEMPLATE = {
    "case_id": None,
    "run_status": None,            # e.g. {"status": "completed|partial|failed", "steps": [...]}
    "figure": None,                # {"figure_type", "title", "editable_source": {...}, "exports": [...]}
    "element_sources": None,       # [{"id", "label", "source_location", "quote"}]
    "data_mapping": None,          # line styles / media colors / uncertainty marks
    "provenance": None,            # source document, tool, change records
    "uncertainty": None,           # [{"item", "handling"}]
}

REQUIRED = ["case_id", "run_status", "figure", "element_sources",
            "data_mapping", "provenance", "uncertainty"]


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def contract_fields(case):
    """Field names from the case's output_contract, else the template."""
    oc = case.get("output_contract") if isinstance(case, dict) else None
    if isinstance(oc, dict):
        keys = [k for k in oc.keys()]
        return keys if keys else list(TEMPLATE)
    if isinstance(oc, list) and oc:
        return [str(k) for k in oc]
    return list(TEMPLATE)


def skeleton(case, fields):
    reason = "initialized before analysis; not yet generated"
    result = {}
    for k in fields:
        result[k] = {"value": None, "null_reason": reason}
    result["case_id"] = case.get("case_id") or case.get("id") or None
    if result["case_id"] is None:
        result["case_id"] = {"value": None,
                             "null_reason": "case.json carries no case_id"}
    return result


def do_init(args):
    case = load(args["case"])
    fields = contract_fields(case)
    result = skeleton(case, fields)
    os.makedirs(os.path.dirname(os.path.abspath(args["out"])) or ".",
                exist_ok=True)
    with open(args["out"], "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps({"initialized": args["out"], "fields": fields},
                     ensure_ascii=False, indent=1))
    return 0


def do_finalize(args):
    result = load(args["result"])
    case = load(args["case"]) if args.get("case") else {}
    fields = (contract_fields(case) if case
              else [k for k in result.keys() if k in REQUIRED] or
              list(TEMPLATE))
    problems = []

    if not result.get("case_id"):
        problems.append("case_id is missing/empty")

    for k in fields:
        if k == "case_id":
            continue
        v = result.get(k, "<absent>")
        if v == "<absent>":
            problems.append("field %r absent from result.json" % k)
            continue
        # accepted shapes: bare value, or {"value": ..., "null_reason": ...}
        if isinstance(v, dict) and set(v.keys()) <= {"value", "null_reason"}:
            if v.get("value") is None and not (v.get("null_reason") or
                                               "").strip():
                problems.append("field %r is null without a null_reason" % k)
        elif v is None:
            problems.append("field %r is null without a null_reason" % k)

    # attach artifact inventory + consistency summary (extra keys, never
    # renames or reshapes contract fields)
    inv = []
    adir = args.get("artifact_dir")
    if adir and os.path.isdir(adir):
        for fn in sorted(os.listdir(adir)):
            p = os.path.join(adir, fn)
            if os.path.isfile(p):
                inv.append({"file": fn, "bytes": os.path.getsize(p)})
    result["_artifacts"] = inv
    if args.get("consistency") and os.path.isfile(args["consistency"]):
        cr = load(args["consistency"])
        result["_consistency_summary"] = {
            "pass": cr.get("pass"),
            "summary": cr.get("summary"),
        }
    result["_finalized_at"] = _dt.datetime.now().isoformat(timespec="seconds")

    with open(args["result"], "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps({"complete": not problems, "problems": problems,
                      "fields": fields, "artifacts": len(inv)},
                     ensure_ascii=False, indent=1))
    return 0 if not problems else 1


def main():
    argv = sys.argv[1:]
    args = {}
    for i, a in enumerate(argv):
        if a.startswith("--"):
            key = a[2:]
            val = argv[i + 1] if i + 1 < len(argv) and \
                not argv[i + 1].startswith("--") else True
            args[key] = val
    mode = argv[0] if argv else ""
    if mode == "--init":
        if not args.get("case") or not args.get("out"):
            print(__doc__)
            return 2
        return do_init(args)
    if mode == "--finalize":
        if not args.get("result"):
            print(__doc__)
            return 2
        return do_finalize(args)
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
