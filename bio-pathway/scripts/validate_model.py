#!/usr/bin/env python3
"""validate_model.py - schema, naming and direction-evidence checks for a biopathway model.

The scientific judgement is the agent's; this script enforces the mechanical
contract so mistakes cannot reach the canvas silently:
  - schema/enums, endpoint existence, compartment existence
  - E-DIR-01: a directed edge whose evidence quote contains no directional cue
    (the 'never guess direction' rule)
  - sign-vs-quote consistency, binding-is-not-directional, family-node edges,
    receptor-not-on-membrane, gene/protein label collisions
  - uncertainty bookkeeping for downgraded edges

Usage:
  python validate_model.py --model model.json [--report validation-report.json]
Exit codes: 0 ok (warnings allowed), 2 errors present, 1 crash.
"""
import argparse
import json
import re
import sys
from pathlib import Path

EDGE_TYPES = None  # loaded from references/edge-types.json

DIRECTION_CUES = re.compile(
    r"(?<!in)activat|inactivat|inhibit|phosphorylat|dephosphorylat|ubiquitinat|"
    r"methylat|acetylat|promot|suppress|repress|\binduc|stimulat|recruit|"
    r"block|sequester|enhanc|reduc|decreas|increas|upregulat|downregulat|"
    r"catalyz|targets?|drives?|leads to|results in|exchange of|"
    r"激活|失活|抑制|磷酸化|去磷酸化|泛素化|甲基化|乙酰化|促进|阻断|募集|"
    r"上调|下调|诱导|正调控|负调控|增强|降低|调控", re.I)

POSITIVE_CUES = re.compile(
    r"(?<!in)activat|phosphorylat|promot|\binduc|stimulat|enhanc|increas|"
    r"upregulat|激活|促进|诱导|上调|增强", re.I)
NEGATIVE_CUES = re.compile(
    r"inactivat|inhibit|suppress|repress|block|sequester|reduc|decreas|"
    r"downregulat|ubiquitinat|失活|抑制|阻断|下调|降低", re.I)
TRANSPORT_CUES = re.compile(
    r"translocat|transport|migrat|travel|moves to|shuttl|enter(s|ing)? the nucleus|"
    r"转运|易位|迁移|进入细胞核|入核", re.I)


class Report:
    def __init__(self):
        self.errors = []
        self.warnings = []

    def error(self, code, item, msg):
        self.errors.append({"code": code, "item": item, "message": msg})

    def warn(self, code, item, msg):
        self.warnings.append({"code": code, "item": item, "message": msg})


def check_schema(model, rep):
    for key in ("entities", "edges"):
        if not isinstance(model.get(key), list):
            rep.error("E-SCH-01", key, f"'{key}' must be a list")
            return False
    return True


def check_entities(model, rep):
    comp_ids = {c["id"] for c in model.get("compartments", [])}
    seen_ids, labels_by_type = set(), {}
    for e in model.get("entities", []):
        eid = e.get("id")
        if not eid:
            rep.error("E-SCH-02", "entity", "entity without id")
            continue
        if eid in seen_ids:
            rep.error("E-REF-04", eid, "duplicate entity id")
        seen_ids.add(eid)
        etype = e.get("type", "protein")
        if etype not in EDGE_TYPES["node_types"] and etype != "receptor":
            rep.error("E-SCH-03", eid, f"unknown entity type '{etype}'")
        labels_by_type.setdefault(e.get("label", eid), set()).add(etype)
        if e.get("compartment") not in comp_ids:
            rep.error("E-CMP-01", eid,
                      f"compartment '{e.get('compartment')}' not defined in "
                      f"compartments {sorted(comp_ids)}")
        src = e.get("source") or {}
        if not src.get("loc"):
            rep.error("E-EVID-01", eid,
                      "entity lacks source.loc - every node must be traceable")
        if etype == "receptor" and e.get("compartment") not in ("membrane",):
            rep.warn("W-MEM-01", eid,
                     "receptor not anchored on the membrane band; receptors are "
                     "transmembrane unless the source says otherwise")
        if etype == "family":
            rep.warn("W-FAM-01", eid,
                     "family/class node; check whether the source names a specific "
                     "member that should carry the edges instead")
    for label, types in labels_by_type.items():
        if len(types) > 1:
            rep.warn("W-NAM-01", label,
                     f"same label '{label}' used for types {sorted(types)}; give the "
                     "gene and the protein distinct ids (naming-rules.md §2)")


def check_edges(model, rep):
    ent_ids = {e["id"] for e in model.get("entities", [])}
    comp_ids = {c["id"] for c in model.get("compartments", [])}
    ent_type = {e["id"]: e.get("type", "protein") for e in model.get("entities", [])}
    seen, unc_items = set(), {u.get("item") for u in model.get("uncertainties", [])}
    for ed in model.get("edges", []):
        eid = ed.get("id")
        if not eid:
            rep.error("E-SCH-04", "edge", "edge without id")
            continue
        if eid in seen:
            rep.error("E-REF-05", eid, "duplicate edge id")
        seen.add(eid)
        etype = ed.get("type")
        if etype not in EDGE_TYPES["edge_types"]:
            rep.error("E-SCH-05", eid, f"unknown edge type '{etype}'")
            continue
        spec = EDGE_TYPES["edge_types"][etype]
        for end in ("source", "target"):
            if ed.get(end) not in ent_ids and not (
                    ed.get("target_kind") == "compartment" and end == "target"
                    and ed.get(end) in comp_ids):
                rep.error("E-REF-01", eid,
                          f"edge endpoint '{ed.get(end)}' is neither an entity id "
                          f"nor (for target) a compartment id")
        ev = ed.get("evidence") or {}
        quote = (ev.get("quote") or "") + " " + (ed.get("notes") or "")
        if not ev.get("quote"):
            rep.error("E-EVID-02", eid, "edge lacks evidence.quote (verbatim)")
        if not ev.get("loc"):
            rep.error("E-EVID-03", eid, "edge lacks evidence.loc")
        if ed.get("confidence") not in ("direct", "indirect"):
            rep.error("E-SCH-06", eid, "confidence must be 'direct' or 'indirect'")
        directed = ed.get("directed")
        if directed is None:
            rep.error("E-SCH-07", eid, "'directed' must be set explicitly "
                                       "(true or false) - silence is a guess")
        if directed:
            if not DIRECTION_CUES.search(quote):
                rep.error("E-DIR-01", eid,
                          "directed edge but no directional cue in the evidence "
                          "quote; downgrade to directed=false or quote a sentence "
                          "that states direction (uncertainty-policy.md §1)")
            if etype == "binding":
                rep.warn("W-BIND-01", eid,
                         "binding edge marked directed; binding/recruitment does "
                         "not imply regulatory direction - prefer directed=false")
            if etype == "translocation" and not TRANSPORT_CUES.search(quote):
                rep.error("E-DIR-02", eid,
                          "translocation edge without a transport cue in the quote")
            if etype == "transcriptional_regulation":
                tgt = ed.get("target")
                if ed.get("target_kind", "entity") == "entity" and \
                        ent_type.get(tgt) != "gene":
                    rep.error("E-TXN-01", eid,
                              f"transcriptional_regulation target '{tgt}' is not a "
                              "gene node")
                if ed.get("sign") not in ("positive", "negative"):
                    rep.error("E-TXN-02", eid,
                              "transcriptional_regulation needs sign "
                              "positive|negative")
            sign = ed.get("sign")
            if sign == "by-sign" and etype != "transcriptional_regulation":
                rep.error("E-SCH-08", eid, "sign 'by-sign' only valid for "
                                           "transcriptional_regulation")
            if etype == "activation" and quote and \
                    not POSITIVE_CUES.search(quote) and NEGATIVE_CUES.search(quote):
                rep.warn("W-SIGN-01", eid,
                         "activation edge whose quote contains only negative cues; "
                         "check the sign")
            if etype == "inhibition" and quote and \
                    not NEGATIVE_CUES.search(quote) and POSITIVE_CUES.search(quote):
                rep.warn("W-SIGN-02", eid,
                         "inhibition edge whose quote contains only positive cues; "
                         "check the sign")
        else:
            if etype not in ("binding", "complex_formation", "unspecified_interaction"):
                if eid not in unc_items and f"edge {eid}" not in unc_items:
                    rep.warn("W-UNC-01", eid,
                             "downgraded (undirected) edge without a matching "
                             "entry in uncertainties - add one so result.json "
                             "reports it")
        if etype == "translocation" and ed.get("target_kind") != "compartment":
            rep.error("E-TRN-01", eid,
                      "translocation target must be a compartment "
                      "(target_kind=compartment)")
    return ent_ids


def main():
    global EDGE_TYPES
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--edgespec", default=str(Path(__file__).parent.parent /
                                               "references" / "edge-types.json"))
    ap.add_argument("--report")
    args = ap.parse_args()
    try:
        with open(args.model, encoding="utf-8") as fh:
            model = json.load(fh)
        with open(args.edgespec, encoding="utf-8") as fh:
            EDGE_TYPES = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"errors": [{"code": "E-IO-01", "item": args.model,
                                      "message": str(exc)}],
                          "warnings": [], "valid": False}, indent=2))
        return 2

    rep = Report()
    if check_schema(model, rep):
        check_entities(model, rep)
        check_edges(model, rep)

    edges = model.get("edges", [])
    stats = {
        "n_entities": len(model.get("entities", [])),
        "n_edges": len(edges),
        "edge_types_used": sorted({e.get("type") for e in edges}),
        "directed": sum(1 for e in edges if e.get("directed") is True),
        "undirected": sum(1 for e in edges if e.get("directed") is False),
        "indirect_evidence": sum(1 for e in edges if e.get("confidence") == "indirect"),
        "n_uncertainties": len(model.get("uncertainties", [])),
    }
    result = {"valid": not rep.errors, "errors": rep.errors,
              "warnings": rep.warnings, "stats": stats,
              "model": str(Path(args.model).resolve())}
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(result, indent=2, ensure_ascii=False),
                                     encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if not rep.errors else 2


if __name__ == "__main__":
    sys.exit(main())
