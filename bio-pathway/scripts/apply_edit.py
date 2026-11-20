#!/usr/bin/env python3
"""apply_edit.py - source-preserving edits to an existing biopathway model/SVG pair.

Edits change model.json (the single source of truth) and re-render the SVG via
render_svg.py; the old figure is kept as figure.svg.bak (never overwritten in
place). Every edit is appended to a change log embedded in the model.

Operations:
  rename-entity --id X --new-label Y [--new-type protein|gene|...]
  add-entity    --id X --label Y --type T --compartment C --order N
                 --loc L --quote Q          (evidence required)
  remove-entity --id X [--cascade]          (default: refuses if edges attached)
  add-edge      --id E --src A --tgt B --type T --directed true|false
                 [--sign positive|negative] [--confidence direct|indirect]
                 [--target-kind compartment] --loc L --quote Q
  remove-edge   --id E
  add-compartment --id C --label L --kind K --rank R

Usage:
  python apply_edit.py --model model.json --op add-edge ... [--out model.json]
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

EDGE_TYPES_FILE = Path(__file__).parent.parent / "references" / "edge-types.json"
TZ = timezone(timedelta(hours=8))
ENTITY_TYPES = {"protein", "receptor", "gene", "rna", "complex", "molecule",
                "cell", "family"}
COMPARTMENT_KINDS = {"open", "membrane", "region", "nucleus", "organelle",
                     "unspecified"}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save(model, path):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n",
                 encoding="utf-8")


def log_change(model, op, detail, result):
    model.setdefault("change_log", []).append({
        "ts": datetime.now(TZ).isoformat(timespec="seconds"),
        "op": op, "detail": detail, "result": result})


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", help="output model path (default: in place, with .bak)")
    ap.add_argument("--op", required=True, choices=[
        "rename-entity", "add-entity", "remove-entity", "add-edge", "remove-edge",
        "add-compartment"])
    ap.add_argument("--id")
    ap.add_argument("--new-label")
    ap.add_argument("--new-type")
    ap.add_argument("--label")
    ap.add_argument("--type")
    ap.add_argument("--compartment")
    ap.add_argument("--order", type=int)
    ap.add_argument("--sub")
    ap.add_argument("--src")
    ap.add_argument("--tgt")
    ap.add_argument("--directed", choices=["true", "false"])
    ap.add_argument("--sign")
    ap.add_argument("--confidence", choices=["direct", "indirect"])
    ap.add_argument("--target-kind", choices=["entity", "compartment"])
    ap.add_argument("--loc")
    ap.add_argument("--quote")
    ap.add_argument("--cascade", action="store_true")
    args = ap.parse_args()

    spec = json.loads(EDGE_TYPES_FILE.read_text(encoding="utf-8"))
    model = load(args.model)
    ents = {e["id"]: e for e in model.get("entities", [])}
    edges = model.get("edges", [])
    errors, warnings = [], []

    if args.op == "rename-entity":
        if args.id not in ents:
            errors.append(f"entity '{args.id}' not found")
        else:
            old = ents[args.id]["label"]
            if args.new_label:
                ents[args.id]["label"] = args.new_label
            if args.new_type:
                if args.new_type not in ENTITY_TYPES:
                    errors.append(f"unknown entity type '{args.new_type}'")
                else:
                    ents[args.id]["type"] = args.new_type
            if not errors:
                log_change(model, "rename-entity",
                           f"{args.id}: label '{old}'->'{args.new_label or old}', "
                           f"type -> {args.new_type or ents[args.id]['type']}", "ok")

    elif args.op == "add-entity":
        for k, v in (("id", args.id), ("label", args.label), ("type", args.type),
                     ("compartment", args.compartment), ("loc", args.loc),
                     ("quote", args.quote)):
            if not v:
                errors.append(f"missing required --{k.lower() if k != 'loc' else 'loc'}"
                              if k != "quote" else "missing --quote (verbatim evidence)")
        if args.id and args.id in ents:
            errors.append(f"entity id '{args.id}' already exists")
        if args.type and args.type not in ENTITY_TYPES:
            errors.append(f"unknown entity type '{args.type}'")
        comp_ids = {c["id"] for c in model.get("compartments", [])}
        if args.compartment and args.compartment not in comp_ids:
            errors.append(f"compartment '{args.compartment}' not defined; add it "
                          f"first with add-compartment")
        if not errors:
            model["entities"].append({
                "id": args.id, "label": args.label, "type": args.type,
                "compartment": args.compartment,
                **({"order": args.order} if args.order is not None else {}),
                **({"sub": args.sub} if args.sub else {}),
                "source": {"loc": args.loc, "quote": args.quote}})
            log_change(model, "add-entity", f"{args.id} ({args.type}) in "
                        f"{args.compartment}", "ok")

    elif args.op == "remove-entity":
        if args.id not in ents:
            errors.append(f"entity '{args.id}' not found")
        else:
            attached = [e["id"] for e in edges if args.id in (e["source"], e["target"])]
            if attached and not args.cascade:
                errors.append(
                    f"entity '{args.id}' has edges {attached}; removing it would "
                    f"orphan them. Confirm with --cascade to remove them too, or "
                    f"remove-entity is refused (source-preserving policy).")
            elif attached and args.cascade:
                edges[:] = [e for e in edges if args.id not in (e["source"], e["target"])]
                model["uncertainties"].append({
                    "item": f"entity {args.id}",
                    "reason": "removed by edit request",
                    "handling": "removed-with-cascade",
                    "detail": f"cascade-removed edges: {attached}"})
                log_change(model, "remove-entity",
                           f"{args.id} with cascade edges {attached}", "ok")
            if not errors:
                model["entities"] = [e for e in model["entities"] if e["id"] != args.id]
                log_change(model, "remove-entity", f"{args.id}", "ok")

    elif args.op == "add-edge":
        for k in ("id", "src", "tgt", "type", "directed", "loc", "quote"):
            if not getattr(args, k if k != "src" else "src", None):
                errors.append(f"missing required --{k}")
        if args.id and any(e["id"] == args.id for e in edges):
            errors.append(f"edge id '{args.id}' already exists")
        if args.type and args.type not in spec["edge_types"]:
            errors.append(f"unknown edge type '{args.type}' (see "
                          "references/edge-types.json)")
        comp_ids = {c["id"] for c in model.get("compartments", [])}
        tk = args.target_kind or "entity"
        if args.src and args.src not in ents:
            errors.append(f"source '{args.src}' is not an entity id")
        if args.tgt and tk == "entity" and args.tgt not in ents:
            errors.append(f"target '{args.tgt}' is not an entity id")
        if args.tgt and tk == "compartment" and args.tgt not in comp_ids:
            errors.append(f"target compartment '{args.tgt}' not defined")
        if not errors:
            edges.append({
                "id": args.id, "source": args.src, "target": args.tgt,
                "target_kind": tk, "type": args.type,
                "directed": args.directed == "true",
                **({"sign": args.sign} if args.sign else {}),
                "confidence": args.confidence or "direct",
                "evidence": {"loc": args.loc, "quote": args.quote}})
            log_change(model, "add-edge",
                       f"{args.id}: {args.src} -{args.type}-> {args.tgt} "
                       f"(directed={args.directed})", "ok")

    elif args.op == "remove-edge":
        before = len(edges)
        edges[:] = [e for e in edges if e["id"] != args.id]
        if len(edges) == before:
            errors.append(f"edge '{args.id}' not found")
        else:
            model["uncertainties"].append({
                "item": f"edge {args.id}", "reason": "removed by edit request",
                "handling": "removed"})
            log_change(model, "remove-edge", args.id, "ok")

    elif args.op == "add-compartment":
        if not args.id or not args.label or not args.kind or args.rank is None:
            errors.append("add-compartment needs --id --label --kind --rank")
        elif args.kind not in COMPARTMENT_KINDS:
            errors.append(f"unknown compartment kind '{args.kind}'")
        else:
            model.setdefault("compartments", []).append({
                "id": args.id, "label": args.label, "kind": args.kind,
                "rank": args.rank})
            log_change(model, "add-compartment", f"{args.id} ({args.kind})",
                       "ok")

    if errors:
        print(json.dumps({"applied": False, "errors": errors}, indent=2,
                         ensure_ascii=False))
        return 2

    out = Path(args.out or args.model)
    # validate on a temporary copy first: an edit that breaks the scientific
    # contract (e.g. a directed edge with no directional cue) must never be
    # persisted into the working model.
    import os
    import tempfile
    fd, tmpname = tempfile.mkstemp(suffix=".json", prefix="biopathway-edit-")
    os.close(fd)  # Windows: an open handle would block later unlink/rename
    tmp = Path(tmpname)
    try:
        save(model, tmp)
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        rc = subprocess.run([sys.executable, str(Path(__file__).parent /
                                                  "validate_model.py"),
                             "--model", str(tmp)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", env=env)
        try:
            validation = json.loads(rc.stdout)
        except (json.JSONDecodeError, TypeError):
            print(json.dumps({"applied": False, "errors": [
                {"code": "E-INT-01", "item": "validation",
                 "message": f"validator did not return JSON: {rc.stderr[-400:]}"}]},
                indent=2, ensure_ascii=False))
            return 2
        if not validation.get("valid", False):
            print(json.dumps({
                "applied": False,
                "errors": validation.get("errors", []),
                "message": "edit refused: the edited model fails validation "
                           "(nothing was written)"},
                indent=2, ensure_ascii=False))
            return 2
        # validation passed - persist, keeping a backup of the original
        if out == Path(args.model) and Path(args.model).exists():
            bak = Path(str(args.model) + ".bak")
            shutil_copy(args.model, bak)
            warnings.append(f"original model saved to {bak.name}")
        shutil_copy(tmp, out)
        print(json.dumps({
            "applied": True, "model": str(out.resolve()),
            "change_log_entries": len(model.get("change_log", [])),
            "validation": {"valid": True,
                           "warnings": validation.get("warnings", [])},
            "warnings": warnings}, indent=2, ensure_ascii=False))
        return 0
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass  # best effort cleanup; the edit itself has completed


def shutil_copy(src, dst):
    import shutil
    shutil.copy2(src, dst)


if __name__ == "__main__":
    sys.exit(main())
