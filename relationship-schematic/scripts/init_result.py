#!/usr/bin/env python3
"""init_result.py - write the保底 (floor) result.json scaffold before any work starts.

Step 1 of the skill workflow: read /input/case.json, create the work and
output directories, and immediately write /app/output/result.json with EVERY
output_contract field present and explicitly null, status "partial", and a
partial_reasons entry. If the session dies later, the contract-shaped result
survives instead of a missing file.

Field names come from case.json's own output_contract when present (dict
keys, or list items that are strings or {name: ...} objects); otherwise a
default contract for the editable_relationship_schematic workorder is used.
Re-running the script will NOT overwrite a result.json that has progressed
(status other than "partial" or a non-empty artifacts list) unless --force.

Usage:
  python init_result.py --case /input/case.json --work /app/work --output /app/output
  (all three flags default to the paths above; --case may point anywhere)
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

DEFAULT_CONTRACT = [
    "editable_source",
    "exported_artifacts",
    "rendered_preview",
    "entity_relation_table",
    "verification_report",
    "sources",
]


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")


def extract_case_id(case: dict, path: str) -> str | None:
    for key in ("case_id", "caseId", "id", "caseID"):
        v = case.get(key)
        if isinstance(v, str) and v:
            return v
    # fall back to any *_id-ish string field at top level
    for k, v in case.items():
        if isinstance(v, str) and v and k.lower().endswith(("_id", "id")):
            return v
    stem = os.path.splitext(os.path.basename(path))[0]
    return stem or None


def contract_keys(case: dict) -> list[str]:
    oc = case.get("output_contract")
    if isinstance(oc, dict):
        keys = [str(k) for k in oc.keys()]
    elif isinstance(oc, list):
        keys = []
        for item in oc:
            if isinstance(item, str):
                keys.append(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("field") or item.get("key")
                if name:
                    keys.append(str(name))
    else:
        keys = []
    # de-duplicate, keep order, always ensure a non-empty contract
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out or list(DEFAULT_CONTRACT)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", default="/input/case.json")
    ap.add_argument("--work", default="/app/work")
    ap.add_argument("--output", default="/app/output")
    ap.add_argument("--force", action="store_true",
                    help="overwrite even a progressed result.json")
    args = ap.parse_args()

    os.makedirs(args.work, exist_ok=True)
    os.makedirs(args.output, exist_ok=True)
    result_path = os.path.join(args.output, "result.json")

    case: dict = {}
    input_problem = None
    if not os.path.isfile(args.case):
        input_problem = f"input case file not found at {args.case}"
    else:
        try:
            with open(args.case, "r", encoding="utf-8") as f:
                case = json.load(f)
            if not isinstance(case, dict):
                input_problem = f"case file {args.case} is valid JSON but not an object"
                case = {}
        except (OSError, json.JSONDecodeError) as e:
            input_problem = f"case file {args.case} unreadable: {type(e).__name__}: {e}"

    # do not clobber progress
    if os.path.isfile(result_path) and not args.force:
        try:
            with open(result_path, "r", encoding="utf-8") as f:
                prev = json.load(f)
            if (prev.get("status") not in (None, "partial")
                    or prev.get("artifacts")):
                print(json.dumps({
                    "status": "kept_existing",
                    "result": os.path.abspath(result_path),
                    "note": "existing result.json has progressed; not overwritten "
                            "(use --force to reset)",
                }, ensure_ascii=False, indent=2))
                sys.exit(0)
        except (OSError, json.JSONDecodeError):
            pass  # unreadable previous file -> rewrite the scaffold

    keys = contract_keys(case)
    case_id = extract_case_id(case, args.case)
    reasons = []
    if input_problem:
        reasons.append(input_problem)
    reasons.append("scaffold written before extraction; all contract fields are "
                   "explicitly null until filled by later steps")

    result = {
        "case_id": case_id,
        "status": "partial",
        "output_contract": {k: None for k in keys},
        "partial_reasons": reasons,
        "artifacts": [],
        "sources": [],
        "uncertainty": [],
        "warnings": [],
        "change_log": [
            {"time": now_iso(),
             "action": "result.json scaffold written by init_result.py",
             "detail": {"case": args.case, "contract_fields": keys,
                        "input_problem": input_problem}}
        ],
    }
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(json.dumps({
        "status": "scaffold_written",
        "result": os.path.abspath(result_path),
        "case_id": case_id,
        "contract_fields": keys,
        "input_problem": input_problem,
    }, ensure_ascii=False, indent=2))
    sys.exit(0 if input_problem is None else 2)


if __name__ == "__main__":
    main()
