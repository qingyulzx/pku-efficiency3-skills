#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_ir.py -- structural validation of the intermediate representation.

Checks the IR against the schema rules in references/ir_schema.md:
  - figure_type present and supported
  - unique ids; connections/edges reference existing element ids
  - every element carries a source object with location; quotes where required
  - certainty values legal; omitted extraction_index items need a reason

Exit code 0 = valid, 1 = invalid (error list printed as JSON).

Usage: python validate_ir.py intermediate.json
"""
import json
import sys

FIGURE_TYPES = {"apparatus", "route"}
CERTAINTY = {"quoted", "inferred", "unspecified_spec", "uncertain"}


def fail(errs, msg):
    errs.append(msg)


def validate(ir):
    errs, warns = [], []
    if not isinstance(ir, dict):
        return ["IR root must be a JSON object"], []
    ftype = ir.get("figure_type")
    if ftype not in FIGURE_TYPES:
        fail(errs, "figure_type must be one of %s, got %r"
             % (sorted(FIGURE_TYPES), ftype))
    if not ir.get("title"):
        warns.append("title missing")
    if ftype == "apparatus":
        comps = ir.get("components") or []
        conns = ir.get("connections") or []
        if not comps:
            fail(errs, "apparatus figure has no components")
        ids = set()
        for c in comps:
            cid = c.get("id")
            if not cid:
                fail(errs, "component without id: %r" % c.get("label"))
                continue
            if cid in ids:
                fail(errs, "duplicate component id %s" % cid)
            ids.add(cid)
            src = c.get("source")
            if not isinstance(src, dict) or not src.get("location"):
                fail(errs, "component %s has no source.location" % cid)
            if src and not src.get("quote"):
                warns.append("component %s has no verbatim source quote" % cid)
            if c.get("certainty") and c["certainty"] not in CERTAINTY:
                fail(errs, "component %s illegal certainty %r"
                     % (cid, c["certainty"]))
        for cn in conns:
            cid = cn.get("id")
            if not cid:
                fail(errs, "connection without id")
            if cn.get("from") not in ids or cn.get("to") not in ids:
                fail(errs, "connection %s references unknown endpoint (%s -> %s)"
                     % (cid, cn.get("from"), cn.get("to")))
            if cn.get("certainty") and cn["certainty"] not in CERTAINTY:
                fail(errs, "connection %s illegal certainty %r"
                     % (cid, cn["certainty"]))
    else:
        nodes = ir.get("nodes") or []
        edges = ir.get("edges") or []
        if not nodes:
            fail(errs, "route figure has no nodes")
        ids = set()
        kinds = {"stage", "step", "decision", "start", "end", "milestone"}
        for n in nodes:
            nid = n.get("id")
            if not nid:
                fail(errs, "node without id: %r" % n.get("label"))
                continue
            if nid in ids:
                fail(errs, "duplicate node id %s" % nid)
            ids.add(nid)
            if n.get("kind") and n["kind"] not in kinds:
                fail(errs, "node %s illegal kind %r" % (nid, n["kind"]))
            src = n.get("source")
            if not isinstance(src, dict) or not src.get("location"):
                fail(errs, "node %s has no source.location" % nid)
        for e in edges:
            if e.get("from") not in ids or e.get("to") not in ids:
                fail(errs, "edge %r references unknown endpoint (%s -> %s)"
                     % (e.get("id"), e.get("from"), e.get("to")))
    # extraction index
    for it in ir.get("extraction_index") or []:
        if it.get("status") == "omitted" and not it.get("reason"):
            fail(errs, "extraction_index item %r omitted without reason"
                 % it.get("mention"))
        if not it.get("quote"):
            fail(errs, "extraction_index item %r has no quote"
                 % it.get("mention"))
    return errs, warns


def main():
    if len(sys.argv) < 2:
        print("usage: validate_ir.py intermediate.json")
        return 2
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        ir = json.load(f)
    errs, warns = validate(ir)
    print(json.dumps({"valid": not errs, "errors": errs, "warnings": warns},
                     ensure_ascii=False, indent=1))
    return 0 if not errs else 1


if __name__ == "__main__":
    sys.exit(main())
