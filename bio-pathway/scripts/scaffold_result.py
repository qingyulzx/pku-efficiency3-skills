#!/usr/bin/env python3
"""scaffold_result.py - write a contract-complete result.json with explicit nulls.

Run this FIRST, before any drawing work: it guarantees /app/output always holds
a result.json covering every output-contract field. Fields not yet produced are
explicit null with a reason. Later steps replace nulls with real values; fields
that end up unproduced keep their null + reason (never delete a contract field).

Usage:
  python scaffold_result.py --input /input/case.json --outdir /app/output
If --input is missing/unreadable the script still writes a result.json with
case_id null and the failure reason recorded.
"""
import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_FIELDS = [
    "editable_source", "exports", "entity_table", "edge_table", "legend_basis",
    "sources", "uncertainties", "verification", "status",
]
CONTRACT_KEYS = ["output_contract", "outputContract", "contract", "required_outputs",
                 "outputs_spec", "output_fields"]
CASE_KEYS = ["case_id", "caseId", "id", "case"]


def deep_find(obj, keys, depth=0):
    """Breadth-first search for the first matching key."""
    if depth > 4 or not isinstance(obj, dict):
        return None
    for k in keys:
        if k in obj:
            return obj[k]
    for v in obj.values():
        found = deep_find(v, keys, depth + 1)
        if found is not None:
            return found
    return None


def contract_fields(contract):
    """Return the list of top-level contract field names."""
    if isinstance(contract, dict):
        return list(contract.keys())
    if isinstance(contract, list):
        fields = []
        for item in contract:
            if isinstance(item, str):
                fields.append(item)
            elif isinstance(item, dict) and item.get("name"):
                fields.append(item["name"])
            elif isinstance(item, dict) and item.get("field"):
                fields.append(item["field"])
        return fields or DEFAULT_FIELDS
    return DEFAULT_FIELDS


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", default="/input/case.json")
    ap.add_argument("--outdir", default="/app/output")
    ap.add_argument("--task", default="/input/task.md")
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    result_path = outdir / "result.json"

    case, error = None, None
    try:
        with open(args.input, encoding="utf-8") as fh:
            case = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        error = f"could not read case input {args.input}: {exc}"

    contract_source = "case.json"
    if case is not None:
        contract = deep_find(case, CONTRACT_KEYS)
        case_id = None
        for k in CASE_KEYS:
            v = deep_find(case, [k]) if k != "case" else None
            if isinstance(v, (str, int)):
                case_id = v
                break
        if contract is None:
            contract_source = "default (no output_contract key found in case.json)"
            contract = DEFAULT_FIELDS
    else:
        case_id = None
        contract_source = ("default (case.json unreadable; cross-check the real "
                           "contract fields against task.md before finalizing)")
        contract = DEFAULT_FIELDS

    reasons = {f: "not yet produced - scaffold stage" for f in contract_fields(contract)}
    result = {"case_id": case_id}
    for f in contract_fields(contract):
        result[f] = None
    result["_unanswered_reasons"] = reasons
    result["_meta"] = {
        "stage": "scaffold",
        "script": "biopathway scaffold_result.py 1.0.0",
        "contract_source": contract_source,
        "input": args.input,
        "status": "in_progress",
        "error": error,
        "note": ("Fields are null until produced; keep null + reason for anything "
                 "not delivered. Do not remove or rename contract fields."),
    }
    result_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "written": str(result_path),
        "case_id": case_id,
        "contract_fields": contract_fields(contract),
        "contract_source": contract_source,
        "error": error,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
