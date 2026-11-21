#!/usr/bin/env python3
"""build_result.py -- assemble the final /app/output/result.json.

Every field of the case's output_contract (and the standard fields this task
always requires) is present exactly once; anything not delivered is explicit
null + reason. Never silently omits a contract field.

Usage:
  python build_result.py --case case.json --plan deck_plan.json \
      --check check_report.json --out result.json \
      [--pptx out.pptx] [--pdf preview.pdf] \
      [--render-info render.json] [--changes changes.json] \
      [--status complete|partial|failed] [--note "..."]
"""
import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def load_json(path):
    if not path or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def now_iso():
    return datetime.datetime.now(
        datetime.timezone.utc).replace(microsecond=0).isoformat()


def slide_evidence_map(plan):
    out = []
    for spec in plan.get("slides", []):
        out.append({
            "slide": spec.get("index"),
            "claim": spec.get("claim"),
            "role": spec.get("role"),
            "evidence": [
                {"type": e.get("type"),
                 "locator": e.get("locator"),
                 "page": e.get("page"),
                 "quote": e.get("quote"),
                 "supports": e.get("note")}
                for e in (spec.get("evidence") or [])
            ],
            "figures_used": [f.get("paper_ref") for f in
                             (spec.get("figures") or [])],
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--plan", default=None)
    ap.add_argument("--check", default=None)
    ap.add_argument("--pptx", default=None)
    ap.add_argument("--pdf", default=None)
    ap.add_argument("--render-info", default=None)
    ap.add_argument("--changes", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--status", default="complete",
                    choices=["complete", "partial", "failed"])
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    case = load_json(args.case) or {}
    plan = load_json(args.plan) or {}
    check = load_json(args.check) or {}
    render = load_json(args.render_info) or {}
    changes = load_json(args.changes) or []

    raw_contract = case.get("output_contract")
    if isinstance(raw_contract, dict):
        contract = raw_contract
    elif isinstance(raw_contract, list):
        # list form: [{"name": "slides", "type": "file"}, ...] -> use names
        contract = {}
        for item in raw_contract:
            if isinstance(item, str):
                contract[item] = None
            elif isinstance(item, dict):
                name = (item.get("name") or item.get("field")
                        or item.get("id") or item.get("key"))
                if name:
                    contract[str(name)] = item.get("type", None)
    else:
        contract = {}
    deliverables = {
        "editable_pptx": args.pptx if args.pptx and os.path.isfile(args.pptx)
        else None,
        "speaker_notes": "in-pptx notes slides (see slide_evidence_map notes "
                         "field)" if plan.get("slides") else None,
        "rendered_preview": args.pdf if args.pdf and os.path.isfile(args.pdf)
        else None,
    }
    null_reasons = {
        "editable_pptx": "assembly not completed in this run",
        "speaker_notes": "no deck plan was produced",
        "rendered_preview": "office-renderer PDF export not available or failed",
    }

    # map deliverable-ish contract keys to what we have
    value_map = {}
    for key in contract:
        k = key.lower()
        if any(w in k for w in ("pptx", "slide file", "editable")):
            value_map[key] = deliverables["editable_pptx"]
        elif any(w in k for w in ("preview", "pdf", "render")):
            value_map[key] = deliverables["rendered_preview"]
        elif "note" in k or "script" in k or "speaker" in k:
            value_map[key] = deliverables["speaker_notes"]
        elif "evidence" in k or "mapping" in k:
            value_map[key] = slide_evidence_map(plan) if plan.get("slides") \
                else None
        elif "narrative" in k or "summary" in k or "main" in k or "spine" in k:
            value_map[key] = plan.get("narrative") or None
        elif "uncertaint" in k or "limitation" in k or "missing" in k:
            value_map[key] = (plan.get("open_issues") or []) + \
                (render.get("issues") or [])
        elif "change" in k or "log" in k or "record" in k:
            value_map[key] = changes
        else:
            value_map[key] = None

    for key, val in value_map.items():
        if val is None and key not in contract:
            continue

    def null_reason_for(key):
        k = key.lower()
        if any(w in k for w in ("pptx", "editable", "slide file")):
            return null_reasons["editable_pptx"]
        if "note" in k or "speaker" in k or "script" in k:
            return null_reasons["speaker_notes"]
        if any(w in k for w in ("preview", "pdf", "render")):
            return null_reasons["rendered_preview"]
        return "not produced in this run"

    reasons = {k: null_reason_for(k)
               for k, v in value_map.items() if v is None}

    result = {
        "case_id": case.get("case_id"),
        "generated_at": now_iso(),
        "status": args.status,
        "status_note": args.note,
        "source": {
            "paper": plan.get("meta", {}).get("source_paper") or
            ({"path": case.get("paper_path")} if case.get("paper_path")
             else None),
            "template": plan.get("meta", {}).get("template") or
            ({"path": case.get("template_path")} if case.get("template_path")
             else None),
        },
        "constraints": {
            "audience": case.get("audience"),
            "duration_minutes": case.get("duration_minutes"),
            "max_slides": case.get("max_slides"),
        },
        "output_contract": {
            key: {"value": value_map.get(key),
                  "null_reason": reasons[key] if value_map.get(key) is None
                  else None}
            if isinstance(value_map.get(key), (str, type(None)))
            else {"value": value_map.get(key)}
            for key in contract
        },
        "deliverables": deliverables,
        "narrative": plan.get("narrative"),
        "slide_evidence_map": slide_evidence_map(plan) if plan.get("slides")
        else None,
        "quality_checks": {
            "summary": check.get("summary"),
            "checks": check.get("checks"),
            "details": check.get("details"),
        } if check else None,
        "rendering": render or None,
        "changes": changes,
        "uncertainty": (plan.get("open_issues") or []) +
                       (render.get("issues") or []),
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    n_null = sum(1 for v in result["output_contract"].values()
                 if v["value"] is None)
    print(json.dumps({"ok": True, "out": os.path.abspath(args.out),
                      "contract_fields": len(result["output_contract"]),
                      "null_fields": n_null,
                      "slides": len(result["slide_evidence_map"] or [])},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
