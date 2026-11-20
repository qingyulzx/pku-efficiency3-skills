"""Output-contract matching: fill every field of /input/case.json's
output_contract, or record an honest null.

Three levels (best first):
  1. exact key match (case-insensitive, ignoring punctuation)
  2. containment match (contract key tokens appear inside a produced key)
  3. description-keyword match (with the lowest confidence)

Contract shapes handled: {field: description}, [field, ...],
[{name|field|key, description?, type?}, ...].
"""
from __future__ import annotations

import re


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _tokens(s: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", str(s).lower()) if len(t) > 2}


_EXTS = {"svg", "png", "pdf", "json", "txt", "md", "csv"}


def _score(cf: dict, key: str, value) -> int:
    """Match score between one contract field and one candidate key/value."""
    ctoks = _tokens(cf["field"]) | _tokens(cf.get("description") or "")
    ktoks = _tokens(key)
    s = len(ctoks & ktoks)
    # morphological variants: scientific/scientifically, export/exported
    s += sum(1 for a in ctoks for b in ktoks
             if a != b and len(a) > 5 and len(b) > 5 and a[:6] == b[:6])
    if _norm(cf["field"]) and _norm(cf["field"]) in _norm(key):
        s += 3
    # format hint: contract mentions 'svg'/'png'/... and the value is a path
    # or list of paths carrying that extension
    exts = {t for t in ctoks if t in _EXTS}
    if exts:
        cand = value if isinstance(value, str) else " ".join(
            str(x) for x in value) if isinstance(value, list) else ""
        if any("." + e in cand.lower() for e in exts):
            s += 2
    return s


def parse_contract(case: dict) -> list[dict]:
    """Returns [{'field': name, 'description': str, 'type': str|None}]"""
    oc = case.get("output_contract")
    if oc is None:
        oc = case.get("contract") or case.get("output_fields")
    out: list[dict] = []
    if isinstance(oc, dict):
        for k, v in oc.items():
            out.append({"field": k,
                        "description": v if isinstance(v, str) else json.dumps(v, ensure_ascii=False),
                        "type": None})
    elif isinstance(oc, list):
        for item in oc:
            if isinstance(item, str):
                out.append({"field": item, "description": "", "type": None})
            elif isinstance(item, dict):
                name = item.get("name") or item.get("field") or item.get("key")
                if name:
                    out.append({"field": name,
                                "description": str(item.get("description") or ""),
                                "type": item.get("type")})
    return out


import json  # noqa: E402  (used by parse_contract)


def match(contract_fields: list[dict], values: dict) -> dict:
    """Returns {field: (level, value_key)} plus leftovers."""
    used: set[str] = set()
    result: dict[str, tuple[int, str]] = {}
    vnorm = {_norm(k): k for k in values}
    # level 1
    for cf in contract_fields:
        n = _norm(cf["field"])
        if n in vnorm and vnorm[n] not in used:
            result[cf["field"]] = (1, vnorm[n])
            used.add(vnorm[n])
    # level 2
    for cf in contract_fields:
        if cf["field"] in result:
            continue
        best, best_score = None, 0
        for k in values:
            if k in used:
                continue
            score = _score(cf, k, values[k])
            if score > best_score:
                best, best_score = k, score
        if best and best_score >= 2:
            result[cf["field"]] = (2, best)
            used.add(best)
    # level 3: single shared token + type hint
    for cf in contract_fields:
        if cf["field"] in result:
            continue
        best, best_score = None, 0
        for k in values:
            if k in used:
                continue
            score = _score(cf, k, values[k])
            if score > best_score:
                best, best_score = k, score
        if best and best_score >= 1:
            result[cf["field"]] = (3, best)
            used.add(best)
    leftovers = [k for k in values if k not in used]
    return {"matches": result, "leftovers": leftovers}


def build_result(case: dict, values: dict, evidence: dict | None = None) -> dict:
    """Merge values into the contract; unmatched fields get explicit nulls."""
    fields = parse_contract(case)
    m = match(fields, values)
    result: dict = {"case_id": case.get("case_id") or case.get("id") or case.get("caseId")}
    unmatched_notes = []
    for cf in fields:
        hit = m["matches"].get(cf["field"])
        if hit:
            level, key = hit
            result[cf["field"]] = values[key]
            if level >= 3:
                result.setdefault("_match_notes", {})[cf["field"]] = (
                    f"matched by description keywords to '{key}' (level {level}); verify this is the intended content")
        else:
            result[cf["field"]] = None
            unmatched_notes.append(
                f"'{cf['field']}' produced no value"
                + (f" (description: {cf['description'][:120]})" if cf["description"] else ""))
    if unmatched_notes:
        result["_unmatched_reasons"] = unmatched_notes
    if m["leftovers"]:
        result.setdefault("evidence", {})["extra_fields"] = {k: values[k] for k in m["leftovers"]}
    if evidence:
        result.setdefault("evidence", {}).update(evidence)
    return result
