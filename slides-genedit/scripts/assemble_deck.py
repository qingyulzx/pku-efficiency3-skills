"""Assemble an editable academic .pptx from an agent-authored outline JSON.

Usage:
    python assemble_deck.py --outline outline.json --out deck.pptx \
        [--template template.pptx] [--workdir DIR]

The outline schema is documented in reference/schemas.md. Key guarantees:
- content is written into slide-level placeholders (cloned from the layout
  when the slide lacks one) so it actually renders;
- images are center-cropped to the target aspect ratio (never distorted);
- speaker notes carry the talk script;
- the assembly report lists layout choices, overflow-risk warnings and any
  fallbacks so the agent can revise the outline and re-run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pptx import Presentation
from pptx.util import Emu, Inches

import pptx_tools as T


def load_outline(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_slide(prs, spec, workdir):
    hint = spec.get("layout_hint", "title_content")
    layout, how = T.pick_layout(prs, hint)
    slide = prs.slides.add_slide(layout)
    entry = {
        "index": None,
        "role": spec.get("role", ""),
        "layout": layout.name,
        "layout_match": how,
        "title_source": None,
        "body_source": None,
        "image": None,
        "warnings": [],
    }

    # ---- title ----
    title = (spec.get("title") or "").strip()
    if title:
        ph, src = T.ensure_placeholder(slide, "title")
        if ph is None:
            entry["warnings"].append("no title placeholder in layout; title dropped")
        else:
            T.set_text_preserving_format(ph.text_frame, [(title, 0)])
            entry["title_source"] = src

    # ---- subtitle (title slide only) ----
    if spec.get("subtitle"):
        ph, src = T.ensure_placeholder(slide, "subtitle") or T.ensure_placeholder(slide, "body")
        if ph is not None:
            T.set_text_preserving_format(ph.text_frame, [(str(spec["subtitle"]), 0)])
        else:
            entry["warnings"].append(
                "subtitle dropped: layout '%s' has no subtitle/body placeholder" % layout.name
            )

    # ---- bullets ----
    bullets = [b for b in (spec.get("bullets") or []) if str(b.get("text", "")).strip()]
    blocks = [(str(b["text"]).strip(), int(b.get("level", 0) or 0)) for b in bullets]
    ph_body, src = T.ensure_placeholder(slide, "body")
    entry["body_source"] = src
    image_spec = spec.get("image") or None

    if image_spec and ph_body is not None and not blocks:
        # image-only slide: picture into the body region
        rect = (ph_body.left, ph_body.top, ph_body.width, ph_body.height)
        _insert_image(slide, image_spec, rect, workdir, entry)
    elif image_spec:
        # text + image: split the body region (image takes the right share)
        if T.ph_type_name(ph_body) == "PICTURE" or _has_picture_placeholder(slide):
            pph = T.find_placeholder(slide, "picture")
            _insert_image(slide, image_spec, None, workdir, entry, target_ph=pph)
        else:
            share = 0.45
            body_l, body_t = ph_body.left, ph_body.top
            body_w, body_h = ph_body.width, ph_body.height
            img_w = int(body_w * share)
            rect = (body_l + body_w - img_w, body_t, img_w, body_h)
            ph_body.width = body_w - img_w - Emu(int(0.15 * T.EMU_PER_INCH))
            _insert_image(slide, image_spec, rect, workdir, entry)
            entry["warnings"].append(
                "layout has no picture placeholder; image placed in right %.0f%% of body area"
                % (share * 100)
            )
        if blocks:
            if ph_body is None:
                left = top = Inches(0.6)
                width = prs.slide_width - Inches(1.2)
                height = prs.slide_height - Inches(1.8)
                tb = slide.shapes.add_textbox(left, top, width, height)
                tb.text_frame.word_wrap = True
                T.set_text_preserving_format(tb.text_frame, blocks)
                entry["warnings"].append(
                    "layout '%s' has no body placeholder; used a plain textbox" % layout.name
                )
            else:
                T.set_body_bullets(ph_body, bullets)
    elif blocks:
        if ph_body is None:
            # layout has no body placeholder at all: plain textbox fallback
            left = top = Inches(0.6)
            width = prs.slide_width - Inches(1.2)
            height = prs.slide_height - Inches(1.8)
            tb = slide.shapes.add_textbox(left, top, width, height)
            tb.text_frame.word_wrap = True
            T.set_text_preserving_format(tb.text_frame, blocks)
            entry["warnings"].append(
                "layout '%s' has no body placeholder; used a plain textbox" % layout.name
            )
        else:
            T.set_body_bullets(ph_body, bullets)

    # overflow heuristic on the body placeholder
    if blocks and ph_body is not None:
        est = T.estimate_overflow(ph_body, blocks)
        if est and est["overflow_risk"]:
            entry["warnings"].append(
                "overflow_risk: est %s lines > capacity %s at %spt; trim bullets"
                % (est["est_lines"], est["est_capacity"], int(est["font_pt"]))
            )
        if est:
            entry["text_fit"] = est

    # ---- notes ----
    entry["notes"] = bool(T.set_notes(slide, spec.get("notes")))

    # ---- evidence (kept for the report; the agent lifts it into result.json)
    entry["evidence"] = spec.get("evidence") or []
    return slide, entry


def _has_picture_placeholder(slide):
    return T.find_placeholder(slide, "picture") is not None


def _insert_image(slide, image_spec, rect, workdir, entry, target_ph=None):
    path = image_spec.get("path")
    if not path or not os.path.exists(path):
        entry["warnings"].append("image not found: %s" % path)
        return
    try:
        pic = T.insert_image_undistorted(
            slide, path, target_ph=target_ph, rect=rect, workdir=workdir
        )
        entry["image"] = {
            "path": path,
            "left_in": round(pic.left / T.EMU_PER_INCH, 2),
            "top_in": round(pic.top / T.EMU_PER_INCH, 2),
            "width_in": round(pic.width / T.EMU_PER_INCH, 2),
            "height_in": round(pic.height / T.EMU_PER_INCH, 2),
        }
        caption = (image_spec.get("caption") or "").strip()
        if caption:
            left = pic.left
            top = pic.top + pic.height + Emu(int(0.06 * T.EMU_PER_INCH))
            width = pic.width
            T.add_caption(slide, caption, left, top, width)
            entry["image"]["caption"] = caption
    except Exception as exc:
        entry["warnings"].append("image insertion failed: %s" % exc)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--outline", required=True, help="outline JSON (agent-authored)")
    ap.add_argument("--out", required=True, help="output .pptx path")
    ap.add_argument("--template", default=None, help="template .pptx (optional)")
    ap.add_argument("--workdir", default=None, help="scratch dir for cropped images")
    args = ap.parse_args()

    outline = load_outline(args.outline)
    outdir = os.path.dirname(os.path.abspath(args.out)) or "."
    workdir = args.workdir or os.path.join(outdir, "_assembly_scratch")
    os.makedirs(workdir, exist_ok=True)

    if args.template:
        if not os.path.exists(args.template):
            raise SystemExit("template not found: %s" % args.template)
        prs = Presentation(args.template)
        template_used = args.template
    else:
        prs = Presentation()  # built-in default template (11 standard layouts)
        template_used = "python-pptx built-in default template"

    meta = outline.get("meta") or {}
    slides_report = []
    for i, spec in enumerate(outline.get("slides") or []):
        slide, entry = build_slide(prs, spec, workdir)
        entry["index"] = i + 1
        slides_report.append(entry)

    prs.save(args.out)

    target = meta.get("target_slides")
    n = len(slides_report)
    budget = {
        "target_slides": target,
        "actual_slides": n,
        "within_budget": (target is None) or (n <= int(target)),
    }
    if target is not None and n > int(target):
        budget["hint"] = (
            "over budget by %d slide(s); apply the cut priority rules and re-run"
            % (n - int(target))
        )

    report = {
        "template": template_used,
        "meta": meta,
        "slides": slides_report,
        "budget": budget,
        "decisions": outline.get("decisions") or [],
        "output": os.path.abspath(args.out),
    }
    report_path = os.path.join(outdir, "assembly-report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    n_warn = sum(len(s["warnings"]) for s in slides_report)
    print("assembled %d slides -> %s" % (n, args.out))
    print("report: %s (warnings: %d)" % (report_path, n_warn))
    if not budget["within_budget"]:
        print("WARNING: slide budget exceeded: %s > %s" % (n, target))
    if n_warn:
        for s in slides_report:
            for w in s["warnings"]:
                print("  slide %s: %s" % (s["index"], w))


if __name__ == "__main__":
    main()
