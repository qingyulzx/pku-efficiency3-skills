#!/usr/bin/env python3
"""schematic_lib.py - shared utilities for the relationship-schematic skill.

Pure standard library. Provides:
  - symbol library loading (symbols/symbols.json)
  - figure-model loading + validation (entities / relations / containment)
  - deterministic text width estimation (no font files required)
  - id sanitisation and geometry helpers

Used by make_schematic.py, verify_svg.py, model_check.py, edit_svg.py.
"""
from __future__ import annotations

import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SYMBOLS_PATH = os.path.join(HERE, "..", "symbols", "symbols.json")

RELATION_TYPES_RANKED = {
    "activates", "inhibits", "modifies", "transports", "indirect", "precedes"
}


# ---------------------------------------------------------------- utilities

def load_symbols(path: str | None = None) -> dict:
    p = path or SYMBOLS_PATH
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def sanitize_id(raw: str) -> str:
    """Make an arbitrary model id safe for use as an XML id / file-safe token."""
    s = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(raw)).strip("-")
    return s or "x"


def est_char_width(ch: str) -> float:
    """Approximate glyph advance in em units (deterministic, font-free)."""
    o = ord(ch)
    if o >= 0x2E80:            # CJK / fullwidth forms
        return 1.0
    if ch in "iIl.,':;|!()[]/":
        return 0.32
    if ch in "mwMW@":
        return 0.88
    if ch in " \u00a0":
        return 0.30
    if ch.isupper() or ch.isdigit():
        return 0.64
    if ch in "-_+~=*":
        return 0.55
    return 0.53


def est_text_width(text: str, font_size: float, bold: bool = False) -> float:
    """Estimated rendered width of a single-line text in svg user units."""
    w = sum(est_char_width(c) for c in text) * font_size
    return w * (1.06 if bold else 1.0)


def wrap_label(label: str, max_width: float, font_size: float) -> list[str]:
    """Greedy wrap of a label so each line fits max_width; honours explicit \n."""
    out: list[str] = []
    for para in label.split("\n"):
        if not para:
            out.append("")
            continue
        line = ""
        for word in para.split(" "):
            cand = word if not line else line + " " + word
            if est_text_width(cand, font_size) <= max_width or not line:
                line = cand
            else:
                out.append(line)
                line = word
        out.append(line)
    return out


def fmt_float(v: float) -> str:
    """Compact float for svg attributes."""
    s = f"{v:.2f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


# ------------------------------------------------------------ model loading

def _norm_evidence(ev) -> dict:
    if ev is None:
        return {}
    if isinstance(ev, dict):
        return {
            "quote": str(ev.get("quote", "") or ""),
            "locator": str(ev.get("locator", "") or ""),
            "source": str(ev.get("source", "") or ""),
        }
    return {"quote": str(ev), "locator": "", "source": ""}


def load_model(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        model = json.load(f)
    if not isinstance(model, dict):
        raise ValueError("model root must be a JSON object")
    model.setdefault("entities", [])
    model.setdefault("relations", [])
    model.setdefault("groups", [])
    model.setdefault("legend_extra", [])
    model.setdefault("title", "")
    model.setdefault("figure_label", "")
    model.setdefault("canvas_width", 900)
    for e in model["entities"]:
        e["evidence"] = _norm_evidence(e.get("evidence"))
        e.setdefault("type", "")
        e.setdefault("label", e.get("id", ""))
    for r in model["relations"]:
        r["evidence"] = _norm_evidence(r.get("evidence"))
        r.setdefault("direction", "A_to_B")
        r.setdefault("label", "")
        r.setdefault("direct", True)
    for g in model["groups"]:
        g["evidence"] = _norm_evidence(g.get("evidence"))
        g.setdefault("label", "")
    return model


def check_model(model: dict, symbols: dict) -> list[dict]:
    """Static validation of a figure model. Returns a list of findings.

    Finding: {severity: 'error'|'warn', code, detail}
    An 'error' blocks drawing (make_schematic refuses to run); 'warn' is
    carried into the verification report and result.json.
    """
    findings: list[dict] = []
    ent_ids = set()
    for e in model["entities"]:
        eid = e.get("id")
        if not eid:
            findings.append({"severity": "error", "code": "entity_missing_id",
                             "detail": f"entity without id: {e!r}"})
            continue
        if eid in ent_ids:
            findings.append({"severity": "error", "code": "duplicate_entity_id",
                             "detail": f"duplicate entity id: {eid}"})
        ent_ids.add(eid)
        if not e.get("evidence", {}).get("quote"):
            findings.append({"severity": "warn", "code": "entity_no_evidence",
                             "detail": f"entity '{eid}' has no verbatim evidence quote"})
        if sanitize_id(eid) != eid:
            findings.append({"severity": "warn", "code": "id_needs_sanitising",
                             "detail": f"entity id '{eid}' contains characters that will be sanitised"})

    group_ids = set()
    for g in model["groups"]:
        gid = g.get("id")
        if not gid:
            findings.append({"severity": "error", "code": "group_missing_id",
                             "detail": f"group without id: {g!r}"})
            continue
        if gid in group_ids or gid in ent_ids:
            findings.append({"severity": "error", "code": "duplicate_group_id",
                             "detail": f"duplicate group id: {gid}"})
        group_ids.add(gid)
        members = g.get("members", [])
        if not members:
            findings.append({"severity": "warn", "code": "empty_group",
                             "detail": f"group '{gid}' has no members"})
        for m in members:
            if m not in ent_ids and m not in group_ids:
                findings.append({"severity": "error", "code": "dangling_group_member",
                                 "detail": f"group '{gid}' references unknown member '{m}'"})
        # containment cycles
        if gid in members:
            findings.append({"severity": "error", "code": "group_self_containment",
                             "detail": f"group '{gid}' contains itself"})

    valid_types = set(symbols["relation_types"])
    valid_dirs = set(symbols["direction_values"])
    rel_ids = set()
    graph: dict[str, list[str]] = {e: [] for e in ent_ids}
    for r in model["relations"]:
        rid = r.get("id")
        if not rid:
            findings.append({"severity": "error", "code": "relation_missing_id",
                             "detail": f"relation without id: {r!r}"})
            continue
        if rid in rel_ids:
            findings.append({"severity": "error", "code": "duplicate_relation_id",
                             "detail": f"duplicate relation id: {rid}"})
        rel_ids.add(rid)
        src, dst = r.get("from"), r.get("to")
        for end in (src, dst):
            if end not in ent_ids and end not in group_ids:
                findings.append({"severity": "error", "code": "dangling_relation_endpoint",
                                 "detail": f"relation '{rid}' references unknown endpoint '{end}'"})
        if r.get("type") not in valid_types:
            findings.append({"severity": "error", "code": "unknown_relation_type",
                             "detail": f"relation '{rid}' has type '{r.get('type')}' not in {sorted(valid_types)}"})
        if r.get("direction") not in valid_dirs:
            findings.append({"severity": "error", "code": "invalid_direction",
                             "detail": f"relation '{rid}' has direction '{r.get('direction')}' not in {sorted(valid_dirs)}"})
        if r.get("direction") == "unknown":
            findings.append({"severity": "warn", "code": "direction_uncertain",
                             "detail": f"relation '{rid}' ({src}->{dst}) has unknown direction; "
                                       "it will be drawn dashed with a '?' label and flagged in result.json"})
        if not r.get("evidence", {}).get("quote"):
            findings.append({"severity": "error", "code": "relation_no_evidence",
                             "detail": f"relation '{rid}' has no verbatim evidence quote - a relation "
                                       "without source text cannot be verified and must not be drawn"})
        if src and dst and src == dst:
            findings.append({"severity": "warn", "code": "self_loop",
                             "detail": f"relation '{rid}' is a self-loop on '{src}'"})
        # rank graph for cycle detection
        if src in ent_ids and dst in ent_ids and r.get("direction") == "A_to_B" \
                and r.get("type") in RELATION_TYPES_RANKED:
            graph[src].append(dst)

    # cycle detection (DFS)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    cycle_edges: list[str] = []

    def dfs(u: str) -> None:
        color[u] = GRAY
        for v in graph[u]:
            if color[v] == GRAY:
                cycle_edges.append(f"{u}->{v}")
            elif color[v] == WHITE:
                dfs(v)
        color[u] = BLACK

    for n in list(graph):
        if color[n] == WHITE:
            dfs(n)
    for ce in cycle_edges:
        findings.append({"severity": "warn", "code": "cycle_in_rank_graph",
                         "detail": f"edge {ce} participates in a directed cycle; layout will break the "
                                   f"cycle by ignoring it for layering (edge is still drawn)"})
    return findings


def findings_report(findings: list[dict]) -> dict:
    return {
        "error_count": sum(1 for f in findings if f["severity"] == "error"),
        "warn_count": sum(1 for f in findings if f["severity"] == "warn"),
        "findings": findings,
    }


if __name__ == "__main__":
    # quick CLI: python schematic_lib.py <model.json>
    if len(sys.argv) != 2:
        print("usage: schematic_lib.py <model.json>   (validation only; see model_check.py)")
        sys.exit(2)
    sym = load_symbols()
    m = load_model(sys.argv[1])
    rep = findings_report(check_model(m, sym))
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    sys.exit(1 if rep["error_count"] else 0)
