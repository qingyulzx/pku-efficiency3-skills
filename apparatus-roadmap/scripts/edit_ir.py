#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""edit_ir.py -- source-preserving edits on a figure IR.

Editing scenario: the user asks to change a component, add a line, or
remove a unit on an ALREADY GENERATED figure. The editable source of
truth is the intermediate representation (IR), never the exported SVG --
so edits happen on the IR and the figure is re-rendered and re-verified.
This is what "source-preserving edit" means here: every surviving element
keeps its original source {location, quote}, and every NEW element must
carry a source quote that is verified verbatim against the (new) material
text before the edit is accepted.

Supported operations (given as a JSON list in an edits file):
  {"op": "add_component", "component": {...}}
  {"op": "add_connection", "connection": {...}}
  {"op": "update_component", "id": "C1", "set": {...}, "reason": "..."}
  {"op": "update_node", "id": "S1", "set": {...}, "reason": "..."}
  {"op": "add_node", "node": {...}}
  {"op": "add_edge", "edge": {...}}
  {"op": "remove_component", "id": "C9", "reason": "..."}   # removes
      attached connections too, and records the removal
  {"op": "remove_node", "id": "S2", "reason": "..."}

Verification rules:
  - added components/connections/nodes/edges must carry source.location
    and source.quote; the quote must appear verbatim (whitespace-
    normalized) in --material text. A failed verification aborts the
    whole edit batch (exit 1) -- no partial application.
  - every edit is appended to ir["change_log"] with a timestamp, the op
    summary and the user-supplied reason.

Usage:
  python edit_ir.py intermediate.json edits.json --material material.txt
         [--out intermediate_v2.json]

Exit 0 = edits applied, 1 = rejected (nothing written).
"""
import datetime as _dt
import json
import re
import sys


def normalize(t):
    if t is None:
        return ""
    t = t.replace(u"\u00ad", "")
    t = t.replace(u"\u2019", "'").replace(u"\u2018", "'")
    t = t.replace(u"\u201c", '"').replace(u"\u201d", '"')
    return re.sub(r"\s+", " ", t).strip()


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def elem_kind(ir):
    return ("components", "connections") if ir.get("figure_type") != "route" \
        else ("nodes", "edges")


def verify_source(obj, norm_material, label, errs):
    src = obj.get("source")
    if not isinstance(src, dict) or not src.get("location"):
        errs.append("%s: added element needs source.location" % label)
        return
    q = src.get("quote")
    if not q:
        errs.append("%s: added element needs a verbatim source.quote" % label)
        return
    if norm_material is not None and normalize(q) not in norm_material:
        errs.append("%s: quote not found in material (refusing to apply): %r"
                    % (label, q[:80]))


def apply_edit(ir, op, norm_material, errs, log):
    kind = op.get("op")
    coll, rel = elem_kind(ir)
    if kind == "add_component" or kind == "add_node":
        obj = op.get("component") or op.get("node")
        if not isinstance(obj, dict) or not obj.get("id"):
            errs.append("%s: needs an object with an id" % kind)
            return
        existing = {e.get("id") for e in ir.get(coll, [])}
        if obj["id"] in existing:
            errs.append("%s: id %s already exists" % (kind, obj["id"]))
            return
        label = "%s %s" % (kind, obj["id"])
        verify_source(obj, norm_material, label, errs)
        if errs:
            return
        ir.setdefault(coll, []).append(obj)
        # keep the coverage index in sync
        ir.setdefault("extraction_index", []).append({
            "mention": obj.get("label") or obj["id"],
            "quote": obj["source"]["quote"],
            "mapped_id": obj["id"],
        })
        log.append("added %s %s (%s) from %s"
                   % (coll[:-1], obj["id"], obj.get("label"),
                      obj["source"]["location"]))
    elif kind == "add_connection" or kind == "add_edge":
        obj = op.get("connection") or op.get("edge")
        if not isinstance(obj, dict):
            errs.append("%s: needs a connection/edge object" % kind)
            return
        ids = {e.get("id") for e in ir.get(coll, [])}
        if obj.get("from") not in ids or obj.get("to") not in ids:
            errs.append("%s: endpoints %s->%s not in IR" %
                        (kind, obj.get("from"), obj.get("to")))
            return
        label = "%s %s" % (kind, obj.get("id") or "%s->%s" %
                           (obj.get("from"), obj.get("to")))
        if obj.get("certainty") != "inferred":
            verify_source(obj, norm_material, label, errs)
            if errs:
                return
        if not obj.get("id"):
            obj["id"] = "X%d" % (len(ir.get(rel, [])) + 1)
        ir.setdefault(rel, []).append(obj)
        log.append("added %s %s (%s -> %s)" % (rel[:-1], obj["id"],
                                               obj["from"], obj["to"]))
    elif kind in ("update_component", "update_node"):
        target = None
        for e in ir.get(coll, []):
            if e.get("id") == op.get("id"):
                target = e
                break
        if target is None:
            errs.append("%s: id %s not found" % (kind, op.get("id")))
            return
        updates = op.get("set") or {}
        protected = {"id", "source"}
        for k, v in updates.items():
            if k in protected:
                errs.append("%s: refusing to overwrite protected key %r"
                            % (kind, k))
                return
            target[k] = v
        log.append("updated %s %s (keys: %s)" % (coll[:-1], op.get("id"),
                                                 sorted(updates)))
    elif kind == "remove_component":
        cid = op.get("id")
        before = len(ir.get(coll, []))
        ir[coll] = [e for e in ir.get(coll, []) if e.get("id") != cid]
        if len(ir[coll]) == before:
            errs.append("remove_component: id %s not found" % cid)
            return
        removed_rel = [c for c in ir.get(rel, [])
                       if c.get("from") == cid or c.get("to") == cid]
        ir[rel] = [c for c in ir.get(rel, [])
                   if c.get("from") != cid and c.get("to") != cid]
        for it in ir.get("extraction_index", []):
            if it.get("mapped_id") == cid:
                it["mapped_id"] = None
                it["status"] = "omitted"
                it["reason"] = "removed by edit: %s" % (op.get("reason") or
                                                        "no reason given")
        log.append("removed component %s and %d attached connection(s)"
                   % (cid, len(removed_rel)))
    elif kind == "remove_node":
        nid = op.get("id")
        before = len(ir.get(coll, []))
        ir[coll] = [e for e in ir.get(coll, []) if e.get("id") != nid]
        if len(ir[coll]) == before:
            errs.append("remove_node: id %s not found" % nid)
            return
        removed_rel = [e for e in ir.get(rel, [])
                       if e.get("from") == nid or e.get("to") == nid]
        ir[rel] = [e for e in ir.get(rel, [])
                   if e.get("from") != nid and e.get("to") != nid]
        for it in ir.get("extraction_index", []):
            if it.get("mapped_id") == nid:
                it["mapped_id"] = None
                it["status"] = "omitted"
                it["reason"] = "removed by edit: %s" % (op.get("reason") or
                                                        "no reason given")
        log.append("removed node %s and %d attached edge(s)"
                   % (nid, len(removed_rel)))
    else:
        errs.append("unknown op %r" % kind)


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return 2
    ir_path, edits_path = args[0], args[1]
    out_path = None
    material = None
    if "--out" in args:
        out_path = args[args.index("--out") + 1]
    if "--material" in args:
        with open(args[args.index("--material") + 1], "r",
                  encoding="utf-8") as f:
            material = f.read()

    ir = load(ir_path)
    edits = load(edits_path)
    if isinstance(edits, dict):
        edits = edits.get("edits", [])
    if not isinstance(edits, list) or not edits:
        print(json.dumps({"applied": False,
                          "errors": ["edits file must contain a non-empty "
                                     "list of operations"]},
                         ensure_ascii=False))
        return 1

    norm_material = normalize(material) if material is not None else None
    if norm_material is None:
        print(json.dumps({"applied": False,
                          "errors": ["--material is required: new elements "
                                     "must be verifiable against material "
                                     "text"]},
                         ensure_ascii=False))
        return 1

    errs, log = [], []
    for op in edits:
        apply_edit(ir, op, norm_material, errs, log)
        if errs:
            break  # no partial application
    if errs:
        print(json.dumps({"applied": False, "errors": errs,
                          "note": "nothing written; IR unchanged"},
                         ensure_ascii=False, indent=1))
        return 1

    ir.setdefault("change_log", []).append({
        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        "edits": log,
        "reason": (load(edits_path).get("reason")
                   if isinstance(load(edits_path), dict) else None),
    })
    if out_path is None:
        base, ext = ir_path.rsplit(".", 1) if "." in ir_path else (ir_path,
                                                                   "json")
        out_path = base + "_edited." + ext
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(ir, f, ensure_ascii=False, indent=1)
    print(json.dumps({"applied": True, "out": out_path, "edit_log": log},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
