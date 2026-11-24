#!/usr/bin/env python3
"""check_result.py — validate result.json against the case output contract.

The case file (case.json) may define an output_contract (list of field names,
or dict of field -> description). Every contract field must appear in
result.json; a field that could not be answered must be present but explicitly
null WITH a reason, so partial results stay honest and checkable.

Also enforces the always-on baseline: case_id, status, sources, uncertainty,
and that any artifact path claimed in result.json actually exists on disk.

Usage:
  python check_result.py --result result.json [--case case.json] [--strict]
Exit codes: 0 = pass, 1 = hard failure, 2 = bad invocation.
"""
import argparse
import json
import os
import sys

BASELINE = ["case_id", "status", "sources", "uncertainty"]


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_contract(case):
    if not case:
        return []
    oc = case.get("output_contract") or case.get("outputContract")
    if isinstance(oc, dict):
        return list(oc.keys())
    if isinstance(oc, list):
        return [x if isinstance(x, str) else x.get("name", "?") for x in oc]
    return []


def find_reason(result, field):
    """A null/missing field is acceptable only with an explicit reason."""
    nr = result.get("null_reasons") or result.get("nullReasons") or {}
    if isinstance(nr, dict) and field in nr:
        return nr[field]
    v = result.get(field)
    if isinstance(v, dict) and v.get("reason"):
        return v["reason"]
    if isinstance(v, dict) and v.get("status") in ("null", "missing", "gap",
                                                  "unavailable"):
        return v.get("reason") or v.get("status")
    return None


def check_artifacts(result, errors, bases):
    def exists_anywhere(v):
        for b in bases:
            if os.path.exists(v if os.path.isabs(v) else os.path.join(b, v)):
                return True
        return False

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("path", "pptx", "pdf", "deck", "file") and \
                        isinstance(v, str) and ("\\" in v or "/" in v or
                                                v.endswith((".pptx", ".pdf",
                                                            ".png", ".md"))):
                    if v and not exists_anywhere(v):
                        errors.append("artifact path does not exist (checked "
                                      "under: %s): %s (%s)"
                                      % (", ".join(bases) or "cwd", v, path))
                else:
                    walk(v, path + "." + str(k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, "%s[%d]" % (path, i))

    walk(result, "$")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", required=True)
    ap.add_argument("--case", default=None)
    ap.add_argument("--base", default=None,
                    help="root for resolving relative artifact paths "
                         "(default: directory containing result.json)")
    ap.add_argument("--strict", action="store_true",
                    help="also require every baseline field non-null")
    args = ap.parse_args()
    if not os.path.isfile(args.result):
        print(json.dumps({"status": "error",
                          "reason": "result.json not found: %s" % args.result}))
        sys.exit(2)
    try:
        result = load(args.result)
    except json.JSONDecodeError as e:
        print(json.dumps({"status": "error",
                          "reason": "result.json is not valid JSON: %s" % e}))
        sys.exit(1)

    case = None
    if args.case and os.path.isfile(args.case):
        try:
            case = load(args.case)
        except json.JSONDecodeError as e:
            print(json.dumps({"status": "error",
                              "reason": "case.json not valid JSON: %s" % e}))
            sys.exit(1)

    errors, warnings = [], []
    for f in BASELINE:
        if f not in result:
            errors.append("missing baseline field: %s" % f)
        elif result[f] is None and not find_reason(result, f):
            errors.append("baseline field %s is null without a reason" % f)

    contract = extract_contract(case)
    missing, nulled_ok, filled = [], [], []
    for field in contract:
        if field not in result:
            missing.append(field)
        elif result[field] is None:
            if find_reason(result, field):
                nulled_ok.append(field)
            else:
                errors.append("contract field %s is null without a reason"
                              % field)
        else:
            filled.append(field)
    if missing:
        errors.append("contract fields absent from result.json: %s"
                      % ", ".join(missing))

    bases = [os.path.dirname(os.path.abspath(args.result))]
    if args.base:
        bases.append(os.path.abspath(args.base))
    bases.append(os.getcwd())
    check_artifacts(result, errors, bases)

    if args.strict:
        for f in BASELINE:
            if result.get(f) is None:
                warnings.append("strict mode: baseline field %s is null" % f)

    coverage = (len(filled) + len(nulled_ok)) / len(contract) if contract else 1.0
    out = {"status": "pass" if not errors else "fail",
           "contract_fields": len(contract),
           "filled": len(filled), "nulled_with_reason": len(nulled_ok),
           "coverage": round(coverage, 3), "errors": errors,
           "warnings": warnings}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    sys.exit(0 if not errors else 1)


if __name__ == "__main__":
    main()
