#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_deck.py — assemble an editable PPTX from an agent-authored page outline,
INSIDE the case template (masters / layouts / theme).

Skeleton: the w07 content-org builder — outline.json driven, slide-budget
demotion (P3->P2 to backup, never silent deletion), honest fallback report,
[图缺失] markers instead of fabricated figures.

W08 template-adaptation assets grafted on top (see references/adaptation-rules.md):
  * per-page "layout" field — the agent picks an explicit layout name/index from
    the analyze_template.py manifest; it always wins over role matching
    (resolve_layout in tmpl_common), unknown names fall back with a
    LAYOUT_NOT_FOUND reason code;
  * the capacity ladder: trim bullets -> shrink sizes (never below the floor)
    -> needs_split; every step is recorded in the per-page report;
  * safe_add_slide — partname-collision-free slide creation (python-pptx 1.0.2
    derives partnames from len(sldIdLst)+1 and collides after deletions);
  * zero hardcoded visuals: no font names, no RGB colors are ever written;
    typography inherits master/layout/theme. The only explicit typography is
    a font SIZE from the readability ladder, recorded in the report;
  * images keep their aspect ratio: picture placeholders use insert_picture
    (center-crop to fill), free-area placement fits the native aspect, and
    captions sit under the picture (falling back to the page bottom strip).

Usage:
  python build_deck.py --outline outline.json --out deck.pptx \
      [--template template.pptx] [--max-slides N] \
      [--report build_report.json] \
      [--floor-title 20] [--floor-body 14] [--floor-caption 10]

Exit codes: 0 ok/partial (see report.status), 2 fatal (bad inputs).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

from PIL import Image

from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml.ns import qn
from pptx.parts.slide import SlidePart
from pptx.util import Inches, Pt

from tmpl_common import (
    AdaptError, DEFAULT_FLOORS, body_level_size, effective_geometry,
    estimate_text_height_pt, force_utf8_stdout, master_text_styles, open_pptx,
    para_dicts_from_bullets, ph_type_name, resolve_layout, title_default_size,
    write_json,
)

MIN_BULLETS_AFTER_TRIM = 4
MAX_LEVEL = 4
BODY_TYPES = ("BODY", "OBJECT")  # OOXML uses both ph types for content


# --------------------------------------------------------------------------
# low-level slide surgery (w08 asset)
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


def find_placeholder(slide, want_types, prefer_idx=None, n=0):
    """Return the n-th placeholder whose type is in want_types (or by idx)."""
    matches = []
    for ph in slide.placeholders:
        if prefer_idx is not None and ph.placeholder_format.idx == prefer_idx:
            return ph
        if ph_type_name(ph) in want_types:
            matches.append(ph)
    return matches[n] if len(matches) > n else None


# --------------------------------------------------------------------------
# the readability ladder: trim -> shrink (never below floor) -> needs_split
# (w08 asset, verbatim from the v4 toolchain)
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
# bullets normalization: accept w07 outline strings and w08 dicts alike
# --------------------------------------------------------------------------

def normalize_bullets(raw):
    """Return [{"level": int, "text": str, "bold": bool}, ...].

    Accepts plain strings (leading spaces/'- ' prefix = level 1, w07 style)
    or dicts ({"level": 0, "text": "..."}, w08 style).
    """
    out = []
    for b in raw or []:
        if isinstance(b, str):
            if not b.strip():
                continue
            level = 1 if b.startswith((" ", "\t")) else 0
            out.append({"level": level, "text": b.lstrip(" -\t"), "bold": False})
        elif isinstance(b, dict) and str(b.get("text", "")).strip():
            out.append({"level": int(b.get("level", 0)), "text": str(b["text"]),
                        "bold": bool(b.get("bold", False))})
    return out


# --------------------------------------------------------------------------
# images (w08 asset: placeholder center-crop, free-area native fit, captions)
# --------------------------------------------------------------------------

def _native_size(path):
    with Image.open(path) as im:
        return im.size, im.format


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
    size enforced. No color is ever written (zero-hardcode rule).
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


def place_figures(slide, figures, prs, layout, master, floors, actions, warnings):
    """Place available figures aspect-true; mark missing ones honestly.

    figures: outline "figures" entries ({path, caption, status, locator}).
    Picture placeholders first (insert_picture -> center-crop, aspect kept),
    free areas second (native-aspect fit, slots split horizontally).
    Missing files get an explicit [图缺失] marker box — never a fake image.
    No colors are written (zero-hardcode rule); marker size >= caption floor.
    """
    avail = [fg for fg in figures if fg.get("status") == "available"]
    missing = [fg for fg in figures if fg.get("status") != "available"]
    if not figures:
        return

    picture_phs = [ph for ph in slide.placeholders if ph_type_name(ph) == "PICTURE"]
    slide_w, slide_h = prs.slide_width, prs.slide_height
    free_imgs = avail[len(picture_phs):] if len(avail) > len(picture_phs) else []

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
            x0, y0 = Inches(0.5), slide_h * 0.42
            w_max = slide_w - Inches(1.0)
            h_max = slide_h - y0 - Inches(0.7)
        if w_max < Inches(2.0):  # no room to the right -> bottom strip
            x0, w_max = Inches(0.5), slide_w - Inches(1.0)
            y0 = slide_h * 0.62
            h_max = slide_h - y0 - Inches(0.7)
        free_region = (x0, y0, w_max, h_max)

    for i, fg in enumerate(avail):
        path = fg.get("path", "")
        pic = None
        if not path or not os.path.isfile(path):
            # same honest marker as for status "missing" — no fake image
            warnings.append("IMAGE_FILE_MISSING:%s — marker box drawn" % path)
            tb = slide.shapes.add_textbox(Inches(0.5), prs.slide_height * 0.62,
                                          prs.slide_width - Inches(1.0), Inches(0.6))
            tf = tb.text_frame
            tf.word_wrap = True
            run = tf.paragraphs[0].add_run()
            run.text = "[图缺失] %s（声明 available 但文件不存在：%s）" % (
                fg.get("caption", ""), fg.get("locator", "材料中未提供"))
            run.font.size = Pt(max(floors["caption"], 11.0))
            actions.append({"figure": path, "caption": fg.get("caption"),
                            "status": "declared available but file missing — "
                                      "marked, not fabricated"})
            continue
        try:
            (nw, nh), fmt = _native_size(path)
        except Exception as exc:  # noqa: BLE001
            warnings.append("IMAGE_UNREADABLE:%s:%s" % (path, type(exc).__name__))
            actions.append({"figure": path, "status": "unreadable: %s" % type(exc).__name__})
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
                            "aspect_strategy": "native-aspect fit"})
        cap = fg.get("caption")
        if cap:
            add_caption(slide, cap, prs, pic, floors)

    for fg in missing:
        # marker box, theme-inherited text, floor-compliant size, no color
        tb = slide.shapes.add_textbox(Inches(0.5), prs.slide_height * 0.62,
                                      prs.slide_width - Inches(1.0), Inches(0.6))
        tf = tb.text_frame
        tf.word_wrap = True
        run = tf.paragraphs[0].add_run()
        run.text = "[图缺失] %s（源：%s）" % (fg.get("caption", ""),
                                            fg.get("locator", "材料中未提供"))
        run.font.size = Pt(max(floors["caption"], 11.0))
        actions.append({"figure": fg.get("path"), "caption": fg.get("caption"),
                        "status": "missing in materials — marked, not fabricated"})


# --------------------------------------------------------------------------
# notes + evidence (w07 talking script + w08 [evidence] block)
# --------------------------------------------------------------------------

def notes_text(page):
    parts = []
    if page.get("notes"):
        parts.append(page["notes"])
    qa = page.get("qa") or []
    if qa:
        parts.append("[问答预案]")
        for item in qa[:6]:
            parts.append("Q: %s\nA: %s" % (item.get("q", "?"), item.get("a", "")))
    ev = page.get("evidence")
    if ev:
        parts.append("[evidence]")
        items = ev if isinstance(ev, list) else [ev]
        for e in items:
            loc = e.get("locator") or " ".join(
                x for x in (e.get("source", ""), e.get("location", "")) if x)
            parts.append("location=%s" % (loc or "unknown"))
            if e.get("quote"):
                parts.append("quote=%s" % e["quote"])
    return "\n\n".join(parts)


def evidence_locator_lines(page):
    """On-slide footer lines: source locators (+ gap warning). No color written."""
    ev = page.get("evidence")
    items = ev if isinstance(ev, list) else ([ev] if ev else [])
    locs = []
    for e in items:
        loc = e.get("locator") or " ".join(
            x for x in (e.get("source", ""), e.get("location", "")) if x)
        if loc:
            locs.append(loc)
    lines = ["源: " + " | ".join(locs[:3])] if locs else []
    if any(e.get("strength") == "gap" for e in items):
        lines.append("⚠ 本页存在证据缺口，见 result.json 不确定性说明")
    return lines


# --------------------------------------------------------------------------
# slide-budget demotion (w07 skeleton)
# --------------------------------------------------------------------------

def enforce_budget(pages, max_slides, report):
    """If content pages exceed the budget, demote lowest-priority pages to
    backup (kept as appendix, never silently deleted)."""
    content = [p for p in pages if p.get("type") != "backup"]
    over = len(content) - max_slides
    if over <= 0:
        return pages
    order = {"P3": 0, "P2": 1, "P1": 2, "P0": 3}
    demoted = []
    rank = sorted(range(len(pages)),
                  key=lambda i: order.get(pages[i].get("priority", "P1"), 2))
    for idx in rank:
        if over <= 0:
            break
        p = pages[idx]
        if p.get("type") in ("title", "closing") or p.get("priority") == "P0":
            continue
        if p.get("type") == "backup":
            continue
        p["type"] = "backup"
        demoted.append({"page": p.get("page_no"), "title": p.get("title"),
                        "priority": p.get("priority", "P1")})
        over -= 1
    if demoted:
        report["demotions"] = demoted
        report["warnings"].append(
            "slide budget exceeded: %d page(s) demoted to backup appendix "
            "(agent should re-check the cut list)" % len(demoted))
    return pages


# --------------------------------------------------------------------------
# template loading (w07 honesty + w08 clear_slides)
# --------------------------------------------------------------------------

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_template(path, report):
    """Load the case template and drop its sample slides (w08 clear_slides).

    Missing/unreadable template -> fall back to the default python-pptx
    template and record it (honesty contract); the deck still builds.
    """
    if path and os.path.isfile(path):
        try:
            prs = open_pptx(path)
            clear_slides(prs)  # keep masters/layouts/theme, drop sample slides
            report["template"] = {
                "path": path, "sha256": sha256_file(path),
                "source": "case template", "sample_slides_cleared": True,
                "slide_size": [prs.slide_width, prs.slide_height],
            }
            return prs
        except AdaptError as exc:
            report["warnings"].append(
                "TEMPLATE_UNREADABLE:%s — using default template (%s)" % (path, exc))
    elif path:
        report["warnings"].append(
            "TEMPLATE_MISSING:%s — using default template" % path)
    report["template"] = {"source": "default python-pptx template"}
    return None  # caller builds a fresh default Presentation


# --------------------------------------------------------------------------
# per-page assembly
# --------------------------------------------------------------------------

def normalize_role(page):
    """Outline page 'type'/'role' -> one of tmpl_common's six roles."""
    role = page.get("role") or page.get("type") or "content"
    return {"two_column": "two_content", "backup": "content"}.get(role, role)


def build_page(prs, page, master, master_styles, floors, report):
    role = normalize_role(page)
    # explicit per-page layout (w08 graft) always wins; falls back to role
    spec = {"layout": page.get("layout"), "role": role}
    layout = resolve_layout(prs, spec, report["warnings"])
    slide = safe_add_slide(prs, layout)
    rep = {"page": page.get("page_no"), "role": role,
           "layout": layout.name,
           "explicit_layout": page.get("layout"),
           "layout_source": "explicit" if page.get("layout") is not None else "role match",
           "warnings": [], "fit": {}, "trims": [], "figures": [],
           "title": page.get("title", "")}
    report["layout_usage"].append(
        {"page": page.get("page_no"), "role": role, "layout": layout.name,
         "selection": rep["layout_source"]})

    # ---- title (ladder: shrink to floor, never below) ------------------------
    title_text = page.get("title", "")
    if page.get("type") == "backup":
        title_text = "备用 | " + title_text
    title_ph = slide.shapes.title  # works for TITLE and CENTER_TITLE
    if title_text:
        if title_ph is None:
            tb = slide.shapes.add_textbox(Inches(0.5), Inches(0.25),
                                          prs.slide_width - Inches(1.0), Inches(0.9))
            tb.text_frame.text = title_text
            report["adaptations"].append(
                {"page": page.get("page_no"), "what": "title text box added",
                 "why": "layout has no title placeholder"})
            rep["warnings"].append(
                "NO_TITLE_PLACEHOLDER: title written into a textbox (does not "
                "follow the layout title style)")
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
                rep["warnings"].append(
                    "TITLE_TOO_LONG: estimated %d lines — shorten it" % lines)
            rep["fit"]["title_lines_est"] = lines

    # ---- subtitle (title/section slides) --------------------------------------
    if page.get("subtitle"):
        sub = find_placeholder(slide, ("SUBTITLE", "BODY", "OBJECT"))
        if sub is not None:
            sub.text_frame.text = page["subtitle"]
        else:
            rep["warnings"].append("NO_SUBTITLE_PLACEHOLDER: subtitle skipped")

    # ---- body bullets (capacity ladder) ----------------------------------------
    bullets = normalize_bullets(page.get("bullets"))
    if bullets:
        body = find_placeholder(slide, BODY_TYPES, prefer_idx=page.get("body_idx"))
        if body is None:
            body = find_placeholder(slide, ("SUBTITLE", "BODY", "OBJECT"))
        if body is None:
            # w07 honesty: never drop content silently — add a plain textbox
            body = slide.shapes.add_textbox(Inches(0.6), Inches(1.4),
                                            prs.slide_width - Inches(1.2),
                                            prs.slide_height - Inches(2.4))
            report["adaptations"].append(
                {"page": page.get("page_no"), "what": "body text box added",
                 "why": "layout has no body placeholder"})
            rep["warnings"].append("NO_BODY_PLACEHOLDER: bullets in a textbox "
                                   "(does not follow the layout body style)")
        layout_ref = slide.slide_layout
        master_ref = layout_ref.slide_master
        _, _, w, h = effective_geometry(body, layout_ref, master_ref)
        if w is None:
            w = int(prs.slide_width * 0.9)
        if h is None:
            h = int(prs.slide_height * 0.6)
        kept, overrides, needs_split = fit_bullets(
            bullets, w, h, master_styles, floors, rep["trims"])
        write_paragraphs(body.text_frame, kept, overrides or None)
        est_h, avail_h, _ = estimate_text_height_pt(
            para_dicts_from_bullets(kept, master_styles, overrides or None),
            w, h, master_styles)
        rep["fit"].update({
            "est_h_pt": est_h, "avail_h_pt": avail_h,
            "ratio": round(est_h / max(avail_h, 0.1), 2),
            "size_overrides_pt": overrides or {},
            "needs_split": needs_split,
            "trimmed_count": len(bullets) - len(kept)})
        if needs_split:
            rep["warnings"].append(
                "NEEDS_SPLIT: content does not fit even at floor size — split this slide")

    # ---- figures (aspect-true, honest markers) ---------------------------------
    place_figures(slide, page.get("figures") or [], prs, layout, master,
                  floors, rep["figures"], rep["warnings"])
    for fs in rep["figures"]:
        report["figure_status"].append({"page": page.get("page_no"),
                                        **{k: v for k, v in fs.items() if k != "page"}})

    # ---- evidence footer (on-slide source locators; no color, floor size) ------
    for line in evidence_locator_lines(page):
        tb = slide.shapes.add_textbox(Inches(0.5), prs.slide_height - Inches(0.42),
                                      prs.slide_width - Inches(1.0), Inches(0.35))
        tf = tb.text_frame
        tf.word_wrap = True
        run = tf.paragraphs[0].add_run()
        run.text = line
        run.font.size = Pt(floors["caption"])

    # ---- speaker notes (talking script + Q&A drill + [evidence] block) ----------
    nt = notes_text(page)
    if nt:
        slide.notes_slide.notes_text_frame.text = nt

    rep["evidence"] = page.get("evidence")
    return rep


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------

def main(argv=None):
    force_utf8_stdout()
    ap = argparse.ArgumentParser(
        description="Template-faithful academic deck assembler (outline-driven)")
    ap.add_argument("--outline", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--template", default=None)
    ap.add_argument("--max-slides", type=int, default=0)
    ap.add_argument("--report", default=None)
    ap.add_argument("--floor-title", type=float, default=DEFAULT_FLOORS["title"])
    ap.add_argument("--floor-body", type=float, default=DEFAULT_FLOORS["body"])
    ap.add_argument("--floor-caption", type=float, default=DEFAULT_FLOORS["caption"])
    args = ap.parse_args(argv)
    floors = {"title": args.floor_title, "body": args.floor_body,
              "caption": args.floor_caption}

    if not os.path.isfile(args.outline):
        print(json.dumps({"status": "error",
                          "reason": "OUTLINE_NOT_FOUND:%s" % args.outline},
                         ensure_ascii=False))
        return 2
    try:
        with open(args.outline, "r", encoding="utf-8") as f:
            outline = json.load(f)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "error",
                          "reason": "OUTLINE_UNREADABLE:%s:%s" % (args.outline, type(exc).__name__)},
                         ensure_ascii=False))
        return 2
    for key in ("case_id", "pages"):
        if key not in outline:
            print(json.dumps({"status": "error",
                              "reason": "outline missing required key %r" % key}))
            return 2
    pages = outline["pages"]
    for i, p in enumerate(pages, 1):
        if "title" not in p:
            print(json.dumps({"status": "error",
                              "reason": "page %d has no title" % i}))
            return 2

    report = {"case_id": outline.get("case_id"), "mode": "new",
              "template": {}, "adaptations": [], "warnings": [],
              "demotions": [], "figure_status": [], "layout_usage": [],
              "slides": [], "needs_split_slides": [], "floors_pt": floors,
              "hard_rules": [
                  "slides created via safe_add_slide(layout) — real layout clones",
                  "no font names / RGB colors written; sizes only, via the ladder",
                  "images aspect-preserved (placeholder center-crop or native fit)",
              ]}

    prs = load_template(args.template, report)
    if prs is None:
        from pptx import Presentation
        prs = Presentation()
    master = prs.slide_masters[0]
    master_styles = master_text_styles(master)

    if args.max_slides:
        pages = enforce_budget(pages, args.max_slides, report)

    for page in pages:
        report["slides"].append(
            build_page(prs, page, master, master_styles, floors, report))

    try:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        prs.save(args.out)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "failed",
                          "reason": "SAVE_FAILED:%s" % type(exc).__name__},
                         ensure_ascii=False))
        return 2

    report["needs_split_slides"] = [
        s["page"] or (i + 1) for i, s in enumerate(report["slides"])
        if s.get("fit", {}).get("needs_split")]
    report["deck"] = args.out
    report["slide_count"] = len(report["slides"])
    report["status"] = "partial" if (
        report["needs_split_slides"] or report["warnings"] or
        any(r["warnings"] for r in report["slides"])) else "ok"
    if args.report:
        write_json(args.report, report)
    print(json.dumps(
        {k: report[k] for k in ("status", "deck", "slide_count",
                                "needs_split_slides")}
        | {"warnings": report["warnings"] + [w for r in report["slides"]
                                             for w in r.get("warnings", [])]},
        ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
