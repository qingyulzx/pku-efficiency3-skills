#!/usr/bin/env python3
"""assemble_deck.py -- build the editable .pptx from a deck plan + template.

Reads:
  --plan    deck_plan.json  (agent-authored, see references/deck-plan-schema.md)
  --map     template_map.json (from analyze_template.py)
  --out     output .pptx path
Optional:
  --max-slides N   hard cap from case.json; exceeding is an error unless
                   --allow-overflow is given (forces a conscious trim decision)

Guarantees:
  * text goes into template PLACEHOLDERS (title / body / subtitle), never into
    free-floating text boxes, unless a slide explicitly asks for a caption text
    box (captions under figures)
  * pictures keep their aspect ratio; picture placeholders used when present
  * per-slide speaker notes are written into the notes slide
  * first-fit font sizing: body text is shrunk in 2pt steps (floor 12pt) to fit
    the placeholder; if it still does not fit a warning is emitted so the agent
    can trim content -- text is never silently truncated
  * slide count is enforced against the case limit
"""
import argparse
import copy
import json
import math
import os
import sys

from pptx import Presentation
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

EMU_PER_PT = 12700
AVG_CHAR_W = 0.52   # fraction of font size, Calibri-like
LINE_SPACING = 1.22
MIN_BODY_PT = 12.0
MIN_TITLE_PT = 22.0


def emu_to_pt(v):
    return (v or 0) / EMU_PER_PT


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def est_lines(text, width_pt, font_pt):
    """estimate wrapped line count for one paragraph"""
    if not text:
        return 1
    cpl = max(8, int(width_pt / (AVG_CHAR_W * font_pt)))
    return max(1, math.ceil(len(text) / cpl))


def fit_font(paras, width_pt, height_pt, start_pt, min_pt):
    """largest font (start_pt down to min_pt, 2pt steps) fitting all paras"""
    font_pt = start_pt
    while font_pt > min_pt:
        lines = sum(est_lines(t, width_pt, font_pt) for t, _ in paras)
        if lines * LINE_SPACING * font_pt <= height_pt:
            return font_pt, lines
        font_pt -= 2
    return min_pt, sum(est_lines(t, width_pt, min_pt) for t, _ in paras)


def find_layout(prs, name):
    for master in prs.slide_masters:
        for layout in master.slide_layouts:
            if layout.name == name:
                return layout
    return None


def layout_placeholder(layout, want):
    """probe a LAYOUT for placeholder kinds (existence/shape checks only).

    Writing text must go to the SLIDE's cloned placeholder, not the layout's:
    layout placeholder text is editing prompt text and never renders on the
    slide. Use slide_placeholder() for actual writes.
    """
    return _find_placeholder(layout, want)


def slide_placeholder(slide, want):
    """find a placeholder on a SLIDE (the write target)"""
    return _find_placeholder(slide, want)


def _find_placeholder(container, want):
    body_seen = 0
    for ph in container.placeholders:
        tn = str(ph.placeholder_format.type).upper()
        idx = ph.placeholder_format.idx
        if want == "title" and (tn.startswith("CENTER_TITLE") or
                                (tn.startswith("TITLE") and idx == 0)):
            return ph
        if want == "subtitle" and tn.startswith("SUBTITLE"):
            return ph
        if want == "picture" and "PICTURE" in tn:
            return ph
        if want in ("body", "body2") and (
                tn.startswith("BODY") or tn.startswith("OBJECT")) and idx != 0:
            body_seen += 1
            if (want == "body" and body_seen == 1) or \
               (want == "body2" and body_seen == 2):
                return ph
    return None


def apply_bullets(ph, bullets, warnings, slide_no):
    """write bullet list into a body placeholder with first-fit sizing"""
    tf = ph.text_frame
    tf.word_wrap = True
    paras = []
    for i, b in enumerate(bullets):
        text = b["text"] if isinstance(b, dict) else str(b)
        level = b.get("level", 0) if isinstance(b, dict) else 0
        paras.append((text, level))
    width_pt = emu_to_pt(ph.width)
    height_pt = emu_to_pt(ph.height)
    font_pt, lines = fit_font(paras, width_pt, height_pt, 20.0, MIN_BODY_PT)
    needed = lines * LINE_SPACING * font_pt
    if needed > height_pt * 1.02:
        warnings.append(
            f"slide {slide_no}: body text still overflows at {MIN_BODY_PT}pt "
            f"(~{lines} lines vs capacity "
            f"{int(height_pt / (LINE_SPACING * font_pt))}); trim content")
    for i, (text, level) in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = text
        p.level = min(level, 4)
        for run in p.runs:
            run.font.size = Pt(font_pt)


def apply_title(ph, text, warnings, slide_no):
    tf = ph.text_frame
    tf.word_wrap = True
    width_pt = emu_to_pt(ph.width)
    height_pt = emu_to_pt(ph.height)
    font_pt, lines = fit_font([(text, 0)], width_pt, height_pt, 36.0,
                              MIN_TITLE_PT)
    if font_pt < 28:
        warnings.append(
            f"slide {slide_no}: long title shrunk to {font_pt}pt; "
            "consider shortening")
    tf.paragraphs[0].text = text
    for run in tf.paragraphs[0].runs:
        run.font.size = Pt(font_pt)


def add_figure(slide, pic_ph, fig, slide_no, warnings):
    """insert picture; prefer the picture placeholder, keep aspect ratio"""
    path = fig.get("image")
    if not path or not os.path.isfile(path):
        warnings.append(f"slide {slide_no}: figure image missing: {path}")
        return None
    if pic_ph is not None:
        # insert_picture into a placeholder keeps the placeholder's position
        # and crops to preserve aspect ratio
        try:
            return pic_ph.insert_picture(path)
        except Exception as e:
            warnings.append(
                f"slide {slide_no}: placeholder picture insert failed ({e}); "
                "falling back to positioned picture")
    from PIL import Image
    with Image.open(path) as im:
        iw, ih = im.size
    max_w, max_h = Inches(8.4), Inches(5.0)
    scale = min(max_w / iw, max_h / ih)
    w, h = int(iw * scale), int(ih * scale)
    return slide.shapes.add_picture(
        path, Inches((13.333 - w / 914400) / 2), Inches(1.6), width=w, height=h)


def add_caption(slide, text, top_in=6.6):
    """caption text box below a figure -- the one sanctioned non-placeholder
    text box, because caption position is content-dependent"""
    tb = slide.shapes.add_textbox(Inches(0.8), Inches(top_in), Inches(11.7),
                                  Inches(0.6))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = text
    p.alignment = PP_ALIGN.CENTER
    for run in p.runs:
        run.font.size = Pt(12)
    return tb


def edit_existing_slide(slide, spec, warnings, slide_no):
    """edit mode: rewrite placeholders of an existing slide in a starting deck"""
    title = spec.get("title") or spec.get("claim", "")
    if title:
        for ph in slide.placeholders:
            tn = str(ph.placeholder_format.type).upper()
            if tn.startswith("TITLE") or tn.startswith("CENTER_TITLE"):
                apply_title(ph, title, warnings, slide_no)
                break
    bullets = spec.get("bullets") or []
    if bullets:
        for ph in slide.placeholders:
            tn = str(ph.placeholder_format.type).upper()
            idx = ph.placeholder_format.idx
            if (tn.startswith("BODY") or tn.startswith("OBJECT")) and idx != 0:
                ph.text_frame.clear()
                apply_bullets(ph, bullets, warnings, slide_no)
                break


def build_slide(prs, spec, role_map, slide_no, warnings, prs_size):
    role = spec.get("role", "content")
    layout_name = spec.get("layout") or role_map.get(role) or role_map.get("content")
    layout = find_layout(prs, layout_name)
    if layout is None:
        # fall back to any layout with a title, else layout 0
        layout = find_layout(prs, role_map.get("content")) or \
            prs.slide_masters[0].slide_layouts[0]
        warnings.append(
            f"slide {slide_no}: layout '{layout_name}' not found, "
            f"used '{layout.name}'")
    slide = prs.slides.add_slide(layout)

    # title / subtitle -- write into the SLIDE's cloned placeholders
    # (writing to the layout's placeholder produces invisible prompt text)
    title_text = spec.get("title") or spec.get("claim", "")
    if title_text:
        if layout_placeholder(layout, "title") is None:
            warnings.append(
                f"slide {slide_no}: layout '{layout.name}' has no title "
                "placeholder; title dropped into body")
        else:
            tph = slide_placeholder(slide, "title")
            apply_title(tph, title_text, warnings, slide_no)
    if role == "title":
        sph = slide_placeholder(slide, "subtitle")
        if sph is not None and spec.get("subtitle"):
            sph.text_frame.text = spec.get("subtitle")

    # two-column content
    if role == "two_column":
        left = spec.get("left") or {}
        right = spec.get("right") or {}
        ph1 = slide_placeholder(slide, "body")
        ph2 = slide_placeholder(slide, "body2")
        if ph1 is not None and (left.get("bullets") or left.get("text")):
            ph1.text_frame.clear()
            apply_bullets(ph1, left.get("bullets") or
                          [{"text": left.get("text", "")}], warnings, slide_no)
        if ph2 is not None and (right.get("bullets") or right.get("text")):
            ph2.text_frame.clear()
            apply_bullets(ph2, right.get("bullets") or
                          [{"text": right.get("text", "")}], warnings, slide_no)
        if ph1 is None or ph2 is None:
            warnings.append(
                f"slide {slide_no}: layout '{layout.name}' lacks two body "
                "placeholders; some two-column content may be missing")
    else:
        bullets = spec.get("bullets") or []
        if bullets:
            if layout_placeholder(layout, "body") is None:
                warnings.append(
                    f"slide {slide_no}: layout '{layout.name}' has no body "
                    "placeholder; bullets skipped (choose a content layout)")
            else:
                bph = slide_placeholder(slide, "body")
                bph.text_frame.clear()
                apply_bullets(bph, bullets, warnings, slide_no)

    # figures
    figs = spec.get("figures") or []
    if figs:
        pic_ph = slide_placeholder(slide, "picture")
        if pic_ph is not None:
            add_figure(slide, pic_ph, figs[0], slide_no, warnings)
        else:
            for fig in figs:
                add_figure(slide, None, fig, slide_no, warnings)
        cap = spec.get("caption") or figs[0].get("caption_note")
        if cap:
            add_caption(slide, cap)

    # speaker notes
    notes = spec.get("notes")
    if notes:
        slide.notes_slide.notes_text_frame.text = notes
    else:
        warnings.append(f"slide {slide_no}: no speaker notes")
    return slide


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--map", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-slides", type=int, default=None)
    ap.add_argument("--allow-overflow", action="store_true")
    args = ap.parse_args()

    plan = load_json(args.plan)
    tmap = load_json(args.map)
    warnings = []

    pptx_path = plan.get("meta", {}).get("template", {}).get("path") or \
        tmap.get("pptx_path")
    if not pptx_path or not os.path.isfile(pptx_path):
        print(json.dumps({"error": f"template pptx not found: {pptx_path}"}))
        sys.exit(2)

    prs = Presentation(pptx_path)
    role_map = tmap.get("role_map", {})
    slides = plan.get("slides", [])
    n_existing = len(prs.slides)

    if args.max_slides is not None:
        planned_total = n_existing + len(slides)
        if planned_total > args.max_slides and not args.allow_overflow:
            print(json.dumps({
                "error": f"plan has {planned_total} slides "
                         f"(existing {n_existing} + planned {len(slides)}) "
                         f"but case limit is {args.max_slides}; trim the plan "
                         "or pass --allow-overflow consciously"}))
            sys.exit(4)

    made = []
    for i, spec in enumerate(slides):
        slide_no = spec.get("index", n_existing + i + 1)
        edit_idx = spec.get("edit_slide_index")
        if edit_idx and 1 <= edit_idx <= n_existing:
            edit_existing_slide(prs.slides[edit_idx - 1], spec, warnings,
                                slide_no)
            made.append({"slide": edit_idx, "mode": "edit",
                         "layout": prs.slides[edit_idx - 1].slide_layout.name})
            continue
        slide = build_slide(prs, spec, role_map, slide_no, warnings,
                            (prs.slide_width, prs.slide_height))
        made.append({"slide": slide_no, "mode": "new",
                     "layout": slide.slide_layout.name})

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    prs.save(args.out)
    print(json.dumps({
        "ok": True, "out": os.path.abspath(args.out),
        "slides_total": len(prs.slides), "built": made,
        "warnings": warnings}, ensure_ascii=False))


if __name__ == "__main__":
    main()
