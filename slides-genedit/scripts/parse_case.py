"""Parse /input/case.json, inventory the materials, extract constraints,
decide the route (generate vs edit) and write a skeleton result.json so a
contract-complete deliverable exists from step 1.

Usage:
    python parse_case.py --input /input/case.json --workdir /app/work \
        [--output-dir /app/output]

Outputs (under --workdir): case-parsed.json
Outputs (under --output-dir): result.json (all contract fields present,
status "in_progress", every field null with a reason until produced).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re

DOC_EXTS = (".pdf", ".pptx", ".docx", ".txt", ".md", ".tex", ".csv", ".xlsx",
            ".png", ".jpg", ".jpeg", ".svg", ".json", ".yaml", ".yml")

EDIT_INTENT_RE = re.compile(
    r"(修改|编辑|改编|压缩|扩写|换受众|调整|删掉|删去|替换|edit|revise|modify|adapt|compress|rewrite|shorten)",
    re.IGNORECASE,
)


def walk(node, out_strings, out_files):
    if isinstance(node, dict):
        for v in node.values():
            walk(v, out_strings, out_files)
    elif isinstance(node, list):
        for v in node:
            walk(v, out_strings, out_files)
    elif isinstance(node, str):
        out_strings.append(node)
        if node.lower().endswith(DOC_EXTS) and len(node) < 4096:
            out_files.append(node)


def find_key(node, names, depth=0):
    """Case-insensitive shallow-then-deep key lookup."""
    if depth > 6 or not isinstance(node, dict):
        return None
    for k, v in node.items():
        if str(k).lower() in names and isinstance(v, (str, int)):
            return v
    for v in node.values():
        got = find_key(v, names, depth + 1)
        if got is not None:
            return got
    return None


def extract_constraints(text):
    """Honest keyword-based constraint scan; reports found items only."""
    found = {}
    m = re.search(r"(\d+)\s*[-~到至]\s*(\d+)\s*页", text)
    if m:
        found["slide_count_range"] = [int(m.group(1)), int(m.group(2))]
    for m in re.finditer(r"(?:不超过|最多|至多|上限|within|at most|up to|max(?:imum)?)\s*(\d+)\s*页|(\d+)\s*页(?:以内|之内|为上限)", text):
        n = int(m.group(1) or m.group(2))
        found["slide_count_max"] = n
        break
    m = re.search(r"(?:恰好|正好|共|exactly)?\s*(\d+)\s*页(?:幻灯片|slides?)", text)
    if m and "slide_count_max" not in found and "slide_count_range" not in found:
        found["slide_count_exact"] = int(m.group(1))
    m = re.search(r"(\d+)\s*(?:分钟|分鐘|minutes?|min\b)", text, re.IGNORECASE)
    if m:
        found["duration_min"] = int(m.group(1))
    m = re.search(r"(受众|audience|听众|汇报对象)[^\n]{0,30}?([\u4e00-\u9fffA-Za-z]{2,12})", text)
    if m:
        found["audience_raw"] = m.group(2)
    aud = re.search(r"(组会|开题|中期|答辩|评审|基金|导师|同行|review|defense|proposal|committee)", text, re.IGNORECASE)
    if aud:
        found["audience_keyword"] = aud.group(1)
    lang = re.search(r"(中文|英文|汉语|英语|Chinese|English)", text)
    if lang:
        found["language_keyword"] = lang.group(1)
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, help="path to case.json")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--output-dir", default=None,
                    help="where the skeleton result.json is written (e.g. /app/output)")
    args = ap.parse_args()

    os.makedirs(args.workdir, exist_ok=True)
    input_dir = os.path.dirname(os.path.abspath(args.input))

    with open(args.input, "r", encoding="utf-8-sig") as f:
        case = json.load(f)

    strings, file_refs = [], []
    walk(case, strings, file_refs)
    big_text = "\n".join(strings)

    # ---- file inventory (resolve relative to case.json dir, then cwd) ----
    inventory = []
    for ref in dict.fromkeys(file_refs):
        cand = [ref]
        for base in (input_dir, os.getcwd()):
            cand.append(os.path.join(base, ref))
        path = next((c for c in cand if os.path.isfile(c)), None)
        entry = {"ref": ref, "exists": path is not None}
        if path:
            entry["path"] = os.path.abspath(path)
            entry["size_bytes"] = os.path.getsize(path)
            ext = os.path.splitext(path)[1].lower()
            entry["kind"] = {
                ".pdf": "pdf_document", ".pptx": "presentation",
                ".docx": "document", ".txt": "text", ".md": "text",
                ".tex": "latex", ".csv": "table", ".xlsx": "spreadsheet",
                ".png": "image", ".jpg": "image", ".jpeg": "image",
                ".svg": "image",
            }.get(ext, "other")
        inventory.append(entry)

    pptx_files = [e for e in inventory if e.get("kind") == "presentation" and e["exists"]]
    pdf_files = [e for e in inventory if e.get("kind") == "pdf_document" and e["exists"]]

    # ---- route decision (evidence recorded, agent confirms) ----
    edit_intent = bool(EDIT_INTENT_RE.search(big_text))
    route = "undetermined"
    route_evidence = {
        "presentation_files": [e["ref"] for e in pptx_files],
        "edit_intent_keywords": bool(edit_intent),
    }
    if pptx_files:
        route = "edit" if edit_intent else "edit-or-generate"
        route_evidence["note"] = (
            "a starting deck is present; edit-intent keywords %s -> follow the "
            "task wording: local edits => edit route, full rebuild => generate route"
            % ("found" if edit_intent else "not found")
        )
    else:
        route = "generate"
        route_evidence["note"] = "no starting deck in inputs"

    # ---- output contract ----
    contract_fields = None
    oc = case.get("output_contract") if isinstance(case, dict) else None
    if isinstance(oc, dict):
        contract_fields = list(oc.keys())
    elif isinstance(oc, list):
        contract_fields = []
        for item in oc:
            if isinstance(item, str):
                contract_fields.append(item)
            elif isinstance(item, dict):
                name = (item.get("name") or item.get("field")
                        or item.get("id") or item.get("key"))
                if name:
                    contract_fields.append(str(name))

    parsed = {
        "parsed_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "case_id": find_key(case, ("case_id", "caseid", "id")),
        "input_file": os.path.abspath(args.input),
        "constraints_found": extract_constraints(big_text),
        "constraints_note": "keyword scan; verify against task.md before trusting",
        "file_inventory": inventory,
        "pdf_count": len(pdf_files),
        "pptx_count": len(pptx_files),
        "route_hint": route,
        "route_evidence": route_evidence,
        "output_contract_fields": contract_fields,
        "top_level_keys": sorted(case.keys()) if isinstance(case, dict) else [],
    }
    out_path = os.path.join(args.workdir, "case-parsed.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)
    print("parsed case -> %s (route hint: %s)" % (out_path, route))

    # ---- skeleton result.json (deliverable floor) ----
    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)
        now = datetime.datetime.now().isoformat(timespec="seconds")
        skeleton = {
            "case_id": parsed["case_id"],
            "status": "in_progress",
            "generated_at": now,
            "route": route,
        }
        fields = contract_fields or [
            "presentation", "evidence_mapping", "render", "versions",
            "decisions", "edit_preservation", "uncertainty", "unanswered",
        ]
        for field in fields:
            skeleton[field] = None
        skeleton["unanswered"] = [
            {"field": f, "reason": "pipeline started; field not yet produced"}
            for f in fields
            if f not in ("unanswered", "case_id", "status")
        ]
        rj = os.path.join(args.output_dir, "result.json")
        with open(rj, "w", encoding="utf-8") as f:
            json.dump(skeleton, f, ensure_ascii=False, indent=2)
        print("skeleton result.json -> %s (fields: %s)" % (rj, ", ".join(fields)))


if __name__ == "__main__":
    main()
