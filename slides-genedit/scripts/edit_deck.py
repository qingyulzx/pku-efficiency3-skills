"""Apply agent-authored edit operations to an existing deck, preserving
everything the instruction did not ask to change.

Usage:
    python edit_deck.py --deck starting.pptx --ops ops.json --out edited.pptx

ops.json schema is documented in reference/schemas.md. Ops are applied in
listed order; slide indices refer to the deck state at the moment each op runs
(1-based). After saving, the script re-opens source and edited decks and
produces an edit-report.json with a preservation matrix: every source slide is
matched in the edited deck by digest; a slide the ops never touched must come
back byte-identical (raw digest) or at least structurally identical (c14n with
normalized relationship ids). Masters and layouts must be untouched.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pptx import Presentation
from pptx.util import Emu

import pptx_tools as T


def resolve_target(slide, target):
    """Resolve a target spec to a shape. target: 'title' | 'body' |
    'idx:<n>' (placeholder idx) | 'name:<shape name>'."""
    if target in (None, "body"):
        return T.find_placeholder(slide, "body")
    if target == "title":
        return T.find_placeholder(slide, "title")
    if isinstance(target, str) and target.startswith("idx:"):
        try:
            idx = int(target.split(":", 1)[1])
        except ValueError:
            return None
        for ph in slide.placeholders:
            if ph.placeholder_format.idx == idx:
                return ph
        return None
    if isinstance(target, str) and target.startswith("name:"):
        want = target.split(":", 1)[1]
        for shp in slide.shapes:
            if shp.name == want:
                return shp
        return None
    return None


def apply_op(prs, op, workdir, log):
    kind = op.get("op")
    idx = op.get("slide")
    slide = prs.slides[idx - 1] if isinstance(idx, int) and 1 <= idx <= len(prs.slides) else None

    if kind == "replace_text":
        if slide is None:
            raise IndexError("replace_text: bad slide index %r" % idx)
        ph = resolve_target(slide, op.get("target", "body"))
        if ph is None:
            raise LookupError("replace_text: target %r not found on slide %s" % (op.get("target"), idx))
        blocks = [(str(b.get("text", "")), int(b.get("level", 0) or 0)) for b in op.get("bullets") or []]
        if not blocks and op.get("text") is not None:
            blocks = [(str(op["text"]), 0)]
        T.set_text_preserving_format(ph.text_frame, blocks)
        log.append({"op": kind, "slide": idx, "target": op.get("target"), "status": "ok"})
    elif kind == "append_bullets":
        if slide is None:
            raise IndexError("append_bullets: bad slide index %r" % idx)
        ph = resolve_target(slide, op.get("target", "body"))
        if ph is None or not ph.has_text_frame:
            raise LookupError("append_bullets: target %r not found on slide %s" % (op.get("target"), idx))
        tf = ph.text_frame
        for b in op.get("bullets") or []:
            text = str(b.get("text", "")).strip()
            if not text:
                continue
            p = tf.add_paragraph()
            p.text = text
            try:
                p.level = int(b.get("level", 0) or 0)
            except (TypeError, ValueError):
                p.level = 0
        log.append({"op": kind, "slide": idx, "target": op.get("target"), "status": "ok"})
    elif kind == "set_notes":
        if slide is None:
            raise IndexError("set_notes: bad slide index %r" % idx)
        T.set_notes(slide, op.get("notes"))
        log.append({"op": kind, "slide": idx, "status": "ok"})
    elif kind == "insert_image":
        if slide is None:
            raise IndexError("insert_image: bad slide index %r" % idx)
        path = op.get("image")
        if not path or not os.path.exists(path):
            raise FileNotFoundError("insert_image: image not found: %r" % path)
        rect = None
        if op.get("rect_in"):
            l, t, w, h = op["rect_in"]
            rect = (Emu(int(l * T.EMU_PER_INCH)), Emu(int(t * T.EMU_PER_INCH)),
                    Emu(int(w * T.EMU_PER_INCH)), Emu(int(h * T.EMU_PER_INCH)))
        ph = None
        if op.get("target"):
            ph = resolve_target(slide, op["target"])
        pic = T.insert_image_undistorted(slide, path, target_ph=ph, rect=rect, workdir=workdir)
        if op.get("caption"):
            T.add_caption(slide, op["caption"], pic.left,
                          pic.top + pic.height + Emu(int(0.06 * T.EMU_PER_INCH)), pic.width)
        log.append({"op": kind, "slide": idx, "image": path, "status": "ok"})
    elif kind == "delete_slide":
        T.delete_slide(prs, idx - 1)
        log.append({"op": kind, "slide": idx, "status": "ok"})
    elif kind == "move_slide":
        T.move_slide(prs, int(op["from"]) - 1, int(op["to"]) - 1)
        log.append({"op": kind, "from": op["from"], "to": op["to"], "status": "ok"})
    elif kind == "duplicate_slide":
        T.duplicate_slide(prs, idx - 1)
        log.append({"op": kind, "slide": idx, "status": "ok"})
    elif kind == "add_slide":
        layout, how = T.pick_layout(prs, op.get("layout_hint", "title_content"))
        slide = prs.slides.add_slide(layout)
        if op.get("title"):
            ph, _ = T.ensure_placeholder(slide, "title")
            if ph is not None:
                T.set_text_preserving_format(ph.text_frame, [(str(op["title"]), 0)])
        if op.get("bullets"):
            ph, _ = T.ensure_placeholder(slide, "body")
            if ph is not None:
                T.set_body_bullets(ph, op["bullets"])
        if op.get("notes"):
            T.set_notes(slide, op["notes"])
        if op.get("after") is not None:
            # move the newly appended slide into position
            T.move_slide(prs, len(prs.slides._sldIdLst) - 1, int(op["after"]))
        log.append({"op": kind, "layout": layout.name, "after": op.get("after"), "status": "ok"})
    else:
        raise ValueError("unknown op: %r" % kind)


def preservation_matrix(source_path, edited_path):
    """Compare source and edited decks by digest matching."""
    src = Presentation(source_path)
    edt = Presentation(edited_path)
    src_dig = [(T.slide_digests(s)["raw"], T.slide_digests(s)["structural"]) for s in src.slides]
    edt_dig = [(T.slide_digests(s)["raw"], T.slide_digests(s)["structural"]) for s in edt.slides]
    src_raw = {r for r, _ in src_dig}
    src_struct = {s for _, s in src_dig}
    matched_raw = sum(1 for r, _ in edt_dig if r in src_raw)
    matched_struct = sum(1 for _, s in edt_dig if s in src_struct)
    n_src, n_edt = len(src_dig), len(edt_dig)
    return {
        "source_slides": n_src,
        "edited_slides": n_edt,
        "slides_identical_raw": matched_raw,
        "slides_identical_structural": matched_struct,
        "masters_untouched": T.master_digests(src) == T.master_digests(edt),
        "layouts_untouched": T.layout_digests(src) == T.layout_digests(edt),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deck", required=True, help="starting deck (.pptx)")
    ap.add_argument("--ops", required=True, help="edit operations JSON")
    ap.add_argument("--out", required=True, help="edited deck path (.pptx)")
    ap.add_argument("--workdir", default=None)
    args = ap.parse_args()

    with open(args.ops, "r", encoding="utf-8") as f:
        ops_doc = json.load(f)
    outdir = os.path.dirname(os.path.abspath(args.out)) or "."
    workdir = args.workdir or os.path.join(outdir, "_edit_scratch")
    os.makedirs(workdir, exist_ok=True)

    prs = Presentation(args.deck)
    log = []
    for op in ops_doc.get("ops") or []:
        try:
            apply_op(prs, op, workdir, log)
        except Exception as exc:
            log.append({"op": op.get("op"), "slide": op.get("slide"), "status": "failed", "error": str(exc)})
            report = {
                "deck": os.path.abspath(args.deck),
                "ops_log": log,
                "saved": False,
                "error": "op failed: %s" % exc,
            }
            with open(os.path.join(outdir, "edit-report.json"), "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            raise SystemExit("EDIT FAILED at op %r: %s" % (op.get("op"), exc))

    prs.save(args.out)
    matrix = preservation_matrix(args.deck, args.out)

    report = {
        "deck": os.path.abspath(args.deck),
        "output": os.path.abspath(args.out),
        "ops_log": log,
        "ops_total": len(ops_doc.get("ops") or []),
        "saved": True,
        "preservation": matrix,
    }
    with open(os.path.join(outdir, "edit-report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("edited deck -> %s" % args.out)
    print(
        "preservation: %s/%s source slides raw-identical, %s structural; masters_untouched=%s"
        % (matrix["slides_identical_raw"], matrix["source_slides"],
           matrix["slides_identical_structural"], matrix["masters_untouched"])
    )
    expected_untouched = matrix["source_slides"] - _touched_slide_count(ops_doc)
    if matrix["slides_identical_raw"] < expected_untouched:
        print(
            "WARNING: expected >= %s untouched slides to stay raw-identical, got %s"
            % (expected_untouched, matrix["slides_identical_raw"])
        )


def _touched_slide_count(ops_doc):
    """Rough count of distinct source slides referenced by ops (for the
    untouched expectation). Move/duplicate/add also touch ordering but not
    necessarily slide content."""
    touched = set()
    for op in ops_doc.get("ops") or []:
        for key in ("slide", "from"):
            if isinstance(op.get(key), int):
                touched.add(op[key])
    return len(touched)


if __name__ == "__main__":
    main()
