# -*- coding: utf-8 -*-
"""build_deck.py — assemble an academic deck INSIDE a real template (masters/layouts/theme).

Usage (new deck from template):
    python build_deck.py --template template.pptx --content content.json \
        --out deck.pptx --report build_report.json

Usage (source-preserving edit of a starting deck):
    python build_deck.py --template template.pptx --start-deck starting.pptx \
        --content content.json --out adapted.pptx --report build_report.json

Hard rules implemented here (see references/adaptation-rules.md):
  * new slides are created with prs.slides.add_slide(layout) — real layout clones,
    never copied existing slides;
  * no font names and no RGB colors are ever written; typography inherits from
    master/layout/theme. The only explicit typography is a font SIZE from the
    readability ladder, and every override is recorded in the report;
  * font-size floors (default title>=20pt, body>=14pt, caption>=10pt) are never
    crossed. If content still does not fit, the slide is flagged "needs_split"
    instead of being squeezed unreadably;
  * images keep their aspect ratio: picture placeholders use insert_picture
    (center-crop to fill), free-area placement fits the native aspect.

Exit codes: 0 ok/partial (see report.status), 2 fatal (bad inputs).
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys

from PIL import Image

from pptx import Presentation
from pptx.dml.color import RGBColor  # noqa: F401 — deliberately unused: we never hardcode colors
from pptx.enum.shapes import PP_PLACEHOLDER
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.parts.slide import SlidePart
from pptx.util import Emu, Inches, Pt

from tmpl_common import (
    AdaptError, DEFAULT_FLOORS, body_level_size, effective_geometry, emu_to_in,
    estimate_text_height_pt, force_utf8_stdout, master_text_styles, open_pptx,
    para_dicts_from_bullets, ph_type_name, resolve_layout, title_default_size,
    write_json,
)

MIN_BULLETS_AFTER_TRIM = 4
MAX_LEVEL = 4


# --------------------------------------------------------------------------
# low-level slide surgery
# --------------------------------------------------------------------------

def safe_add_slide(prs, layout):
    """Add a slide with a collision-free partname.

    python-pptx 1.0.2's Slides.add_slide derives the new partname from
    len(sldIdLst)+1. After deleting a middle slide, that number collides with
    a still-existing trailing slide (duplicate 'ppt/slides/slideN.xml' zip
    entries -> PowerPoint repair prompt / dropped slide). This mirrors
    add_slide but allocates the partname from the package's real partname set.
    """
    partname = prs.part.package.next_partname("/ppt/slides/slide%d.xml")
    slide_part = SlidePart.new(partname, prs.part.package, layout.part)
    rId = prs.part.relate_to(slide_part, RT.SLIDE)
    slide = slide_part.slide
    slide.shapes.clone_layout_placeholders(layout)
    prs.slides._sldIdLst.add_sldId(rId)
    return slide


def clear_slides(prs):
    """Remove all slides (template sample slides) while keeping masters/layouts/theme."""
    sldIdLst = prs.slides._sldIdLst
    for sldId in list(sldIdLst):
        prs.part.drop_rel(sldId.get(qn("r:id")))
        sldIdLst.remove(sldId)


def delete_slide(prs, one_based_index):
    sldIdLst = prs.slides._sldIdLst
    sldIds = list(sldIdLst)
    sldId = sldIds[one_based_index - 1]
    prs.part.drop_rel(sldId.get(qn("r:id")))
    sldIdLst.remove(sldId)


BODY_TYPES = ("BODY", "OBJECT")  # OOXML uses both ph types for content placeholders


def find_placeholder(slide, want_types, prefer_idx=None, n=0):
    """Return the n-th placeholder whose type is in want_types (or by idx)."""
    matches = []
    for ph in slide.placeholders:
        if prefer_idx is not None and ph.placeholder_format.idx == prefer_idx:
            return ph
        if ph_type_name(ph) in want_types:
            matches.append(ph)
    return matches[n] if len(matches) > n else None


def write_paragraphs(tf, bullets, size_overrides=None):
    """Write bullets into a text frame WITHOUT touching fonts/colors (inherit theme).

    size_overrides: {level: pt} from the readability ladder — the only explicit
    typography ever written. Returns the runs that received an override.
    """
    tf.clear()
    overridden_runs = []
    first = True
    for b in bullets:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        lvl = min(int(b.get("level", 0)), MAX_LEVEL)
        p.level = lvl
        run = p.add_run()
        run.text = str(b.get("text", ""))
        if b.get("bold"):
            run.font.bold = True
        if size_overrides and lvl in size_overrides:
            run.font.size = Pt(size_overrides[lvl])
            overridden_runs.append(run)
    return overridden_runs


# --------------------------------------------------------------------------
# the readability ladder: trim -> shrink (never below floor) -> needs_split
# --------------------------------------------------------------------------

def fit_bullets(bullets, width_emu, height_emu, master_styles, floors, log):
    """Return (kept_bullets, size_overrides, needs_split).

    Ladder (every step recorded in `log`):
      1. drop deepest-level bullets first, then tail level-0 bullets
         (never below MIN_BULLETS_AFTER_TRIM);
      2. shrink level sizes proportionally, clamped at the body floor;
      3. if still overflowing -> needs_split=True (the agent splits the slide).
    """
    kept = [dict(b) for b in bullets]
    overrides = {}

    def est(bl, sizes=None):
        paras = para_dicts_from_bullets(bl, master_styles, sizes)
        h, avail, _ = estimate_text_height_pt(paras, width_emu, height_emu, master_styles)
        return h, avail

    h, avail = est(kept)
    if h <= avail * 1.02:
        return kept, overrides, False

    # --- step 1a: drop deepest-level bullets --------------------------------
    while h > avail and any(int(b.get("level", 0)) >= 2 for b in kept):
        deepest = max(int(b.get("level", 0)) for b in kept)
        for i in range(len(kept) - 1, -1, -1):
            if int(kept[i].get("level", 0)) == deepest:
                log.append({"action": "trim_deep_bullet", "level": deepest,
                            "text": kept[i].get("text", "")[:80]})
                kept.pop(i)
                break
        h, avail = est(kept)
    # --- step 1b: drop tail level-0 bullets ----------------------------------
    while h > avail and len(kept) > MIN_BULLETS_AFTER_TRIM:
        log.append({"action": "trim_tail_bullet",
                    "text": kept[-1].get("text", "")[:80]})
        kept.pop()
        h, avail = est(kept)
    if h <= avail * 1.02:
        return kept, overrides, False

    # --- step 2: proportional shrink, floored --------------------------------
    base = {}
    for b in kept:
        lvl = int(b.get("level", 0))
        base.setdefault(lvl, body_level_size(master_styles, lvl))
    floor = floors["body"]
    scale = min(1.0, (avail / h) * 0.96)
    for lvl, sz in base.items():
        new = max(floor, round(sz * scale * 2) / 2.0)
        if new < sz:
            overrides[lvl] = new
    if overrides:
        log.append({"action": "shrink_font_sizes", "overrides_pt": dict(overrides),
                    "floor_pt": floor})
        h2, _ = est(kept, overrides)
        if h2 <= avail * 1.05:
            return kept, overrides, False

    # --- step 3: give up squeezing, ask for a split ---------------------------
    log.append({"action": "needs_split",
                 "reason": "content exceeds placeholder even at floor size"})
    return kept, overrides, True


# a title placeholder is ~one text line high for estimation purposes
EMU_PER_LINE_PLACEHOLDER_HEIGHT = 12700 * 60  # 60pt tall box


def fit_title(title_text, width_emu, size_pt, floors):
    """Return (size_override_or_None, lines_est). Titles shrink to floor, never below."""
    paras = [{"level": 0, "text": title_text, "size_pt": size_pt}]
    h, avail, detail = estimate_text_height_pt(
        paras, width_emu, int(EMU_PER_LINE_PLACEHOLDER_HEIGHT), None)
    lines = detail[0]["lines"] if detail else 1
    if lines <= 2:
        return None, lines
    shrunk = max(floors["title"], round(size_pt * 0.85 * 2) / 2.0)
    paras[0]["size_pt"] = shrunk
    _, _, detail2 = estimate_text_height_pt(
        paras, width_emu, int(EMU_PER_LINE_PLACEHOLDER_HEIGHT), None)
    lines2 = detail2[0]["lines"] if detail2 else 1
    return (shrunk if lines2 <= 2 else None), (lines2 if shrunk else lines)


# --------------------------------------------------------------------------
# images
# --------------------------------------------------------------------------

def _native_size(path):
    with Image.open(path) as im:
        return im.size, im.format


def place_images(slide, spec, prs, layout, master, floors, actions, warnings):
    """Place 1-2 images aspect-true. Picture placeholders first, free areas second."""
    images = []
    if spec.get("image"):
        images.append(spec["image"])
    images.extend(spec.get("images") or [])
    if not images:
        return
    picture_phs = [ph for ph in slide.placeholders if ph_type_name(ph) == "PICTURE"]
    slide_w, slide_h = prs.slide_width, prs.slide_height
    free_imgs = images[len(picture_phs):] if len(images) > len(picture_phs) else []

    # free-area region shared by all images that miss a picture placeholder
    free_region = None
    if free_imgs:
        body = find_placeholder(slide, BODY_TYPES)
        if body is not None and body.left is not None:
            x0 = body.left + body.width + Inches(0.25)
            y0 = body.top
            w_max = slide_w - x0 - Inches(0.35)
            h_max = body.height
        else:
            x0, y0 = Inches(0.5), prs.slide_height * 0.42
            w_max = slide_w - Inches(1.0)
            h_max = slide_h - y0 - Inches(0.7)
        if w_max < Inches(2.0):  # no room to the right -> bottom strip
            x0, w_max = Inches(0.5), slide_w - Inches(1.0)
            y0 = prs.slide_height * 0.62
            h_max = slide_h - y0 - Inches(0.7)
        free_region = (x0, y0, w_max, h_max)

    for i, img in enumerate(images):
        pic = None
        path = img.get("path", "")
        if not path or not os.path.isfile(path):
            warnings.append("IMAGE_FILE_MISSING:%s — placeholder frame kept empty" % path)
            continue
        try:
            (nw, nh), fmt = _native_size(path)
        except Exception as exc:  # noqa: BLE001
            warnings.append("IMAGE_UNREADABLE:%s:%s" % (path, type(exc).__name__))
            continue
        if i < len(picture_phs):
            ph = picture_phs[i]
            # capture BEFORE insert_picture: the placeholder's <p:sp> element is
            # replaced by the returned PlaceholderPicture, detaching `ph`
            ph_idx = ph.placeholder_format.idx
            pic = ph.insert_picture(path)  # center-crops to fill -> aspect preserved
            actions.append({"path": path, "native_px": [nw, nh], "format": fmt,
                            "placed_in": "picture placeholder idx=%s" % ph_idx,
                            "aspect_strategy": "center-crop to placeholder"})
        elif free_region is not None:
            # split the free region horizontally across the remaining images
            k = len(free_imgs)
            j = i - len(picture_phs)  # 0-based among free images
            x0, y0, w_max, h_max = free_region
            slot_w = (w_max - Inches(0.2) * (k - 1)) / k
            slot_x = x0 + j * (slot_w + Inches(0.2))
            scale = min(slot_w / nw, h_max / nh)
            w, h = int(nw * scale), int(nh * scale)
            pic = slide.shapes.add_picture(path, slot_x, y0, width=w, height=h)
            actions.append({"path": path, "native_px": [nw, nh], "format": fmt,
                            "placed_in": "free area slot %d/%d" % (j + 1, k),
                            "display_in": [round(emu_to_in(w), 2), round(emu_to_in(h), 2)],
                            "aspect_strategy": "native-aspect fit"})
        cap = img.get("caption")
        if cap:
            add_caption(slide, cap, prs, pic, floors)


def _rects_overlap(a, b, tol_emu=9144):
    """True if EMU rects (l, t, w, h) overlap; tol ~0.01in absorbs rounding."""
    return not (a[0] + a[2] <= b[0] + tol_emu or b[0] + b[2] <= a[0] + tol_emu or
                a[1] + a[3] <= b[1] + tol_emu or b[1] + b[3] <= a[1] + tol_emu)


def add_caption(slide, caption, prs, pic, floors):
    """Caption below the picture (typically the returned PlaceholderPicture).

    Default position: directly under the picture, aligned to its left edge and
    width. If that strip overlaps a layout placeholder (some caption/picture
    layouts put title+body right below the image), fall back to the bottom
    strip of the slide so nothing ever overlaps. Inherits theme fonts; floor
    size enforced.
    """
    if pic is not None:
        left = pic.left
        top = pic.top + pic.height + Inches(0.06)
        width = pic.width
    else:
        left, top, width = Inches(0.5), prs.slide_height - Inches(0.75), prs.slide_width - Inches(1.0)
    height = Inches(0.4)
    ph_rects = [(ph.left, ph.top, ph.width, ph.height) for ph in slide.placeholders
                if ph.left is not None and ph.top is not None and ph is not pic]
    if any(_rects_overlap((left, top, width, height), r) for r in ph_rects):
        top = prs.slide_height - Inches(0.55)
    tb = slide.shapes.add_textbox(left, top, width, height)
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    run = p.add_run()
    run.text = caption
    run.font.size = Pt(max(floors["caption"], 11.0))


# --------------------------------------------------------------------------
# per-slide assembly
# --------------------------------------------------------------------------

def notes_block(spec):
    parts = []
    if spec.get("notes"):
        parts.append(spec["notes"])
    ev = spec.get("evidence")
    if ev:
        parts.append("[evidence]")
        parts.append("source=%s" % ev.get("source", "unknown"))
        parts.append("location=%s" % ev.get("location", "unknown"))
        if ev.get("quote"):
            parts.append("quote=%s" % ev["quote"])
    return "\n\n".join(parts)


def build_new_slide(prs, spec, master, master_styles, floors, warnings):
    layout = resolve_layout(prs, spec, warnings)
    slide = safe_add_slide(prs, layout)
    rep = {"role": spec.get("role", "content"),
           "layout": layout.name,
           "warnings": [],
           "fit": {}, "images": [], "trims": []}

    # ---- title ---------------------------------------------------------------
    title_text = spec.get("title", "")
    title_ph = slide.shapes.title  # works for TITLE and CENTER_TITLE
    t_w = None
    if title_text:
        if title_ph is None:
            tb = slide.shapes.add_textbox(Inches(0.5), Inches(0.25),
                                          prs.slide_width - Inches(1.0), Inches(0.9))
            tb.text_frame.text = title_text
            rep["warnings"].append(
                "NO_TITLE_PLACEHOLDER: title written into a textbox (does not follow "
                "the layout title style)")
        else:
            _, _, w, _ = effective_geometry(title_ph, layout, master)
            t_w = w or (prs.slide_width - Inches(1.0))
            base_sz = title_default_size(master_styles)
            override, lines = fit_title(title_text, t_w, base_sz, floors)
            title_ph.text_frame.text = title_text
            if override:
                for p in title_ph.text_frame.paragraphs:
                    for r in p.runs:
                        r.font.size = Pt(override)
                rep["fit"]["title_size_override_pt"] = override
            if lines > 2:
                rep["warnings"].append("TITLE_TOO_LONG: estimated %d lines — shorten it" % lines)
            rep["fit"]["title_lines_est"] = lines

    # ---- subtitle (title/section slides) --------------------------------------
    if spec.get("subtitle"):
        sub = find_placeholder(slide, ("SUBTITLE", "BODY", "OBJECT"))
        if sub is not None:
            sub.text_frame.text = spec["subtitle"]
        else:
            rep["warnings"].append("NO_SUBTITLE_PLACEHOLDER: subtitle skipped")

    # ---- body bullets ----------------------------------------------------------
    bullets = spec.get("bullets") or []
    if bullets:
        body = find_placeholder(slide, BODY_TYPES, prefer_idx=spec.get("body_idx"))
        if body is None:
            body = find_placeholder(slide, ("SUBTITLE", "BODY", "OBJECT"))
        if body is None:
            rep["warnings"].append("NO_BODY_PLACEHOLDER: bullets skipped")
        else:
            _, _, w, h = effective_geometry(body, layout, master)
            w = w or int(prs.slide_width * 0.9)
            h = h or int(prs.slide_height * 0.6)
            kept, overrides, needs_split = fit_bullets(
                bullets, w, h, master_styles, floors, rep["trims"])
            write_paragraphs(body.text_frame, kept, overrides or None)
            est_h, avail_h, detail = estimate_text_height_pt(
                para_dicts_from_bullets(kept, master_styles, overrides or None), w, h, master_styles)
            rep["fit"].update({
                "est_h_pt": est_h, "avail_h_pt": avail_h,
                "ratio": round(est_h / max(avail_h, 0.1), 2),
                "size_overrides_pt": overrides or {},
                "needs_split": needs_split,
                "trimmed_count": len(bullets) - len(kept)})
            if needs_split:
                rep["warnings"].append(
                    "NEEDS_SPLIT: content does not fit even at floor size — split this slide")

    # ---- images -----------------------------------------------------------------
    place_images(slide, spec, prs, layout, master, floors, rep["images"], rep["warnings"])

    # ---- notes + evidence ----------------------------------------------------------
    nb = notes_block(spec)
    if nb:
        slide.notes_slide.notes_text_frame.text = nb
    rep["evidence"] = spec.get("evidence")
    rep["title"] = title_text
    return slide, rep


def edit_existing_slide(slide, spec, prs, master_styles, floors, warnings, change_log):
    """Source-preserving edit: only the placeholders named in the spec are touched.

    Needs the Presentation object (not just the master) because image placement
    measures against the real slide size.
    """
    rep = {"role": spec.get("role", "edit"),
           "slide_index": spec.get("slide_index"),
           "layout": slide.slide_layout.name,
           "warnings": [], "fit": {}, "images": [], "trims": [],
           "change_log": []}
    layout = slide.slide_layout

    if spec.get("title") is not None:
        title_ph = slide.shapes.title
        if title_ph is None:
            rep["warnings"].append("NO_TITLE_PLACEHOLDER_ON_TARGET: title unchanged")
        else:
            before = title_ph.text_frame.text
            title_ph.text_frame.text = spec["title"]
            rep["change_log"].append({"action": "replace_title", "before": before,
                                      "after": spec["title"]})
    if spec.get("bullets") is not None:
        body = find_placeholder(slide, BODY_TYPES, prefer_idx=spec.get("body_idx"))
        if body is None:
            rep["warnings"].append("NO_BODY_PLACEHOLDER_ON_TARGET: bullets unchanged")
        else:
            before = body.text_frame.text
            master = slide.slide_layout.slide_master
            _, _, w, h = effective_geometry(body, layout, master)
            w = w or 9144000
            h = h or 4572000
            kept, overrides, needs_split = fit_bullets(
                spec["bullets"], w, h, master_styles, floors, rep["trims"])
            write_paragraphs(body.text_frame, kept, overrides or None)
            rep["change_log"].append({"action": "replace_body",
                                      "before": before[:400],
                                      "after": "\n".join(b.get("text", "") for b in kept)[:400]})
            rep["fit"]["needs_split"] = needs_split
            if needs_split:
                rep["warnings"].append("NEEDS_SPLIT on edited slide %s" % spec.get("slide_index"))
    if spec.get("notes"):
        before = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
        nb = notes_block(spec)
        slide.notes_slide.notes_text_frame.text = nb
        rep["change_log"].append({"action": "replace_notes", "before_len": len(before)})
    if spec.get("image") or spec.get("images"):
        place_images(slide, spec, prs, layout, layout.slide_master,
                     floors, rep["images"], rep["warnings"])
    change_log.extend(rep["change_log"])
    return rep


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def load_content(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001
        raise AdaptError("CONTENT_UNREADABLE:%s:%s" % (path, type(exc).__name__))


def main(argv=None):
    force_utf8_stdout()
    ap = argparse.ArgumentParser(description="Template-faithful academic deck assembler")
    ap.add_argument("--template", required=True)
    ap.add_argument("--start-deck", default=None,
                    help="edit this deck instead of building from scratch")
    ap.add_argument("--content", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", default=None)
    ap.add_argument("--floor-title", type=float, default=DEFAULT_FLOORS["title"])
    ap.add_argument("--floor-body", type=float, default=DEFAULT_FLOORS["body"])
    ap.add_argument("--floor-caption", type=float, default=DEFAULT_FLOORS["caption"])
    args = ap.parse_args(argv)
    floors = {"title": args.floor_title, "body": args.floor_body,
              "caption": args.floor_caption}

    warnings = []
    change_log = []
    try:
        template = open_pptx(args.template)
        content = load_content(args.content)
    except AdaptError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, ensure_ascii=False))
        return 2

    if args.start_deck:
        prs = open_pptx(args.start_deck)
        mode = "edit"
        if len(prs.slide_masters) == 0:
            print(json.dumps({"status": "failed", "reason": "START_DECK_NO_MASTERS"},
                             ensure_ascii=False))
            return 2
    else:
        prs = template
        mode = "new"
        clear_slides(prs)

    master = prs.slide_masters[0]
    master_styles = master_text_styles(master)

    for idx in content.get("delete_slides", []):
        if 1 <= idx <= len(prs.slides._sldIdLst):
            delete_slide(prs, idx)
            change_log.append({"action": "delete_slide", "slide_index": idx})
        else:
            warnings.append("DELETE_SLIDE_OUT_OF_RANGE:%s" % idx)

    slide_reports = []
    existing = list(prs.slides)
    for spec in content.get("slides", []):
        si = spec.get("slide_index")
        if mode == "edit" and si is not None:
            if not (1 <= si <= len(existing)):
                warnings.append("SLIDE_INDEX_OUT_OF_RANGE:%s — appended instead" % si)
                slide, rep = build_new_slide(prs, spec, master, master_styles, floors, warnings)
            else:
                rep = edit_existing_slide(existing[si - 1], spec, prs, master_styles,
                                          floors, warnings, change_log)
                slide = existing[si - 1]
        else:
            slide, rep = build_new_slide(prs, spec, master, master_styles, floors, warnings)
        slide_reports.append(rep)

    try:
        prs.save(args.out)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "failed", "reason": "SAVE_FAILED:%s" % type(exc).__name__},
                         ensure_ascii=False))
        return 2

    needs_split = [i + 1 for i, r in enumerate(slide_reports) if r.get("fit", {}).get("needs_split")]
    status = "partial" if (needs_split or any(w for r in slide_reports for w in r.get("warnings", []))) else "ok"
    report = {
        "status": status,
        "mode": mode,
        "template": args.template,
        "start_deck": args.start_deck,
        "out": args.out,
        "slide_count": len(slide_reports),
        "needs_split_slides": needs_split,
        "slides": slide_reports,
        "warnings": warnings,
        "change_log": change_log,
        "floors_pt": floors,
        "hard_rules": [
            "slides created via add_slide(layout) — real layout clones",
            "no font names / RGB colors written; sizes only, via the ladder",
            "images aspect-preserved (placeholder center-crop or native fit)",
        ],
    }
    if args.report:
        write_json(args.report, report)
    print(json.dumps({"status": status, "out": args.out, "slide_count": report["slide_count"],
                      "needs_split_slides": needs_split,
                      "warnings": warnings + [w for r in slide_reports for w in r.get("warnings", [])]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
