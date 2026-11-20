"""Shared helpers for academic slide assembly and source-preserving editing.

Design notes (hard-won):
- Text is written into SLIDE-level placeholders. Writing into layout-level
  placeholders does not render on the slide (the file saves with exit 0 and the
  bug only shows when the deck is re-opened), so ensure_placeholder() clones a
  placeholder down from the layout when a slide lacks one.
- Existing run/paragraph formatting is captured and re-applied when rewriting
  text, so the template's fonts and bullet styles survive content edits.
- Images are center-cropped to the target aspect before insertion so they are
  never distorted by a placeholder's shape.
- Preservation digests come in two levels: raw part bytes, and a structural
  digest (c14n XML with relationship ids normalized). python-pptx reparses
  XML with remove_blank_text=True, so third-party decks may not round-trip
  byte-identically even when untouched; the structural digest catches that.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from copy import deepcopy

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

TITLE_TYPES = ("TITLE", "CENTER_TITLE")
SUBTITLE_TYPES = ("SUBTITLE",)
BODY_TYPES = ("BODY", "OBJECT")
EMU_PER_INCH = 914400


# --------------------------------------------------------------------------
# placeholder helpers
# --------------------------------------------------------------------------

def ph_type_name(ph) -> str:
    """Placeholder type as a plain string, e.g. 'TITLE', 'BODY', 'PICTURE'."""
    try:
        raw = str(ph.placeholder_format.type)
        return raw.split(" ")[0].split(".")[-1]
    except Exception:
        return "UNKNOWN"


def find_placeholder(container, kind):
    """Find a slide-level (or layout-level) placeholder of a kind.

    kind: 'title' | 'subtitle' | 'body' | 'picture'. SUBTITLE is kept distinct
    from BODY: a subtitle is a title-slide element, not a bullet container.
    Returns None when absent.
    """
    for ph in container.placeholders:
        t = ph_type_name(ph)
        if kind == "title" and t in TITLE_TYPES:
            return ph
        if kind == "subtitle" and t in SUBTITLE_TYPES:
            return ph
        if kind == "body" and t in BODY_TYPES:
            return ph
        if kind == "picture" and t == "PICTURE":
            return ph
    return None


def ensure_placeholder(slide, kind):
    """Return a slide-level placeholder of `kind`, cloning from the layout.

    Mandatory: content written into a layout placeholder does not render.
    """
    ph = find_placeholder(slide, kind)
    if ph is not None:
        return ph, "slide"
    lph = find_placeholder(slide.slide_layout, kind)
    if lph is None:
        return None, "absent"
    el = deepcopy(lph._element)
    slide.shapes._spTree.append(el)
    cloned = find_placeholder(slide, kind)
    return cloned, "cloned-from-layout"


# --------------------------------------------------------------------------
# text writing with format preservation
# --------------------------------------------------------------------------

def _capture_format(tf):
    """Capture pPr of the first paragraph and rPr of its first run (or the
    paragraph's endParaRPr) so template styling can be re-applied."""
    fmt = {}
    if not tf.paragraphs:
        return fmt
    p0 = tf.paragraphs[0]._p
    pPr = p0.find(qn("a:pPr"))
    if pPr is not None:
        fmt["pPr"] = deepcopy(pPr)
    rPr = None
    if tf.paragraphs[0].runs:
        rPr = tf.paragraphs[0].runs[0]._r.find(qn("a:rPr"))
    if rPr is None:
        rPr = p0.find(qn("a:endParaRPr"))
    if rPr is not None:
        fmt["rPr"] = deepcopy(rPr)
    return fmt


def set_text_preserving_format(tf, blocks):
    """Rewrite a text frame with blocks = [(text, level), ...] while re-using
    the captured paragraph/run formatting of the first existing paragraph."""
    fmt = _capture_format(tf)
    tf.clear()
    for i, (text, level) in enumerate(blocks):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = text
        try:
            p.level = max(0, min(8, int(level)))
        except (TypeError, ValueError):
            p.level = 0
        if fmt.get("pPr") is not None:
            old = p._p.find(qn("a:pPr"))
            if old is not None:
                p._p.remove(old)
            p._p.insert(0, deepcopy(fmt["pPr"]))
        if fmt.get("rPr") is not None and p.runs:
            r = p.runs[0]._r
            old = r.find(qn("a:rPr"))
            if old is not None:
                r.remove(old)
            r.insert(0, deepcopy(fmt["rPr"]))
    return tf


def set_body_bullets(ph, bullets):
    """Write bullet items into a body placeholder. bullets: [{text, level}]."""
    blocks = []
    for b in bullets or []:
        text = str(b.get("text", "")).strip()
        if not text:
            continue
        blocks.append((text, int(b.get("level", 0) or 0)))
    return set_text_preserving_format(ph.text_frame, blocks)


def set_notes(slide, text):
    """Write speaker notes (the talk script) for a slide."""
    if not text:
        return False
    slide.notes_slide.notes_text_frame.text = str(text)
    return True


def add_caption(slide, text, left, top, width, font_size=11):
    """Small caption text box (used under inserted figures)."""
    tb = slide.shapes.add_textbox(left, top, width, Inches(0.4))
    tf = tb.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = str(text)
    for run in p.runs:
        run.font.size = Pt(font_size)
        run.font.italic = True
    return tb


# --------------------------------------------------------------------------
# images
# --------------------------------------------------------------------------

def crop_image_to_aspect(image_path, aspect, workdir):
    """Center-crop an image (PIL) to a target aspect (width/height)."""
    if aspect is None or aspect <= 0:
        return image_path
    from PIL import Image

    img = Image.open(image_path)
    w, h = img.size
    if w == 0 or h == 0:
        return image_path
    cur = w / h
    if abs(cur - aspect) / max(cur, aspect) < 0.01:
        return image_path
    if cur > aspect:
        nw = max(1, int(round(h * aspect)))
        x0 = (w - nw) // 2
        box = (x0, 0, x0 + nw, h)
    else:
        nh = max(1, int(round(w / aspect)))
        y0 = (h - nh) // 2
        box = (0, y0, w, y0 + nh)
    out_name = "crop_%s_%s" % (
        hashlib.sha1(("%s:%s" % (image_path, aspect)).encode("utf-8")).hexdigest()[:10],
        os.path.basename(image_path),
    )
    os.makedirs(workdir, exist_ok=True)
    out_path = os.path.join(workdir, out_name)
    img.crop(box).save(out_path)
    return out_path


def insert_image_undistorted(slide, image_path, target_ph=None, rect=None, workdir="."):
    """Insert a picture so it fills the placeholder/rect without distortion.

    Pre-crops with PIL to the exact target aspect, then inserts. Prefers a
    real picture placeholder via insert_picture(); otherwise add_picture into
    the given rect (left, top, width, height in EMU).
    """
    if target_ph is not None and ph_type_name(target_ph) == "PICTURE":
        aspect = target_ph.width / float(target_ph.height or 1)
        cropped = crop_image_to_aspect(image_path, aspect, workdir)
        return target_ph.insert_picture(cropped)
    if rect is None and target_ph is not None:
        rect = (target_ph.left, target_ph.top, target_ph.width, target_ph.height)
    if rect is None:
        raise ValueError("insert_image_undistorted needs a placeholder or a rect")
    left, top, width, height = rect
    aspect = width / float(height or 1)
    cropped = crop_image_to_aspect(image_path, aspect, workdir)
    return slide.shapes.add_picture(cropped, left, top, width, height)


# --------------------------------------------------------------------------
# layout matching
# --------------------------------------------------------------------------

def layout_info(layout):
    info = {"name": layout.name, "title": False, "subtitle": False,
            "bodies": 0, "picture": False}
    for ph in layout.placeholders:
        t = ph_type_name(ph)
        if t in TITLE_TYPES:
            info["title"] = True
        elif t in SUBTITLE_TYPES:
            info["subtitle"] = True
        elif t in BODY_TYPES:
            info["bodies"] += 1
        elif t == "PICTURE":
            info["picture"] = True
    return info


LAYOUT_HINTS = (
    "title",
    "section",
    "title_content",
    "two_content",
    "image_content",
    "image_right",
    "title_only",
    "blank",
)


def pick_layout(prs, hint):
    """Pick the layout best matching a hint. Returns (layout, how).

    Subtitle placeholders do not count as content bodies (a 'Title Slide'
    layout must not win over 'Title and Content' for title_content).
    """
    hint = (hint or "title_content").strip().lower()
    if hint not in LAYOUT_HINTS:
        hint = "title_content"
    scored = []
    for i, layout in enumerate(prs.slide_layouts):
        info = layout_info(layout)
        s = 0
        if hint in ("title", "section"):
            if info["title"] and info["subtitle"]:
                s = 5
            elif info["title"] and info["bodies"] == 0 and not info["picture"]:
                s = 3
            elif info["title"]:
                s = 1
        elif hint == "title_content":
            if info["title"] and info["bodies"] == 1:
                s = 5
            elif info["title"] and info["bodies"] >= 2:
                s = 4
            elif info["title"] and info["subtitle"]:
                s = 2
            elif info["title"]:
                s = 1
        elif hint == "two_content":
            if info["title"] and info["bodies"] >= 2:
                s = 5
            elif info["title"] and info["bodies"] == 1:
                s = 3
            elif info["title"] and info["subtitle"]:
                s = 2
            elif info["title"]:
                s = 1
        elif hint in ("image_content", "image_right"):
            if info["title"] and info["picture"]:
                s = 5
            elif info["picture"]:
                s = 4
            elif info["title"] and info["bodies"] >= 1:
                s = 2
            elif info["title"]:
                s = 1
        elif hint == "title_only":
            if info["title"] and info["bodies"] == 0 and not info["subtitle"]:
                s = 4
            elif info["title"]:
                s = 2
        elif hint == "blank":
            s = 3 if (not info["title"] and info["bodies"] == 0) else 1
        if s > 0:
            scored.append((s, -i, layout))
    if not scored:
        return prs.slide_layouts[len(prs.slide_layouts) - 1], "fallback:last"
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    best = scored[0]
    exact = best[0] >= 4
    return best[2], "matched" if exact else "fallback:nearest"


# --------------------------------------------------------------------------
# overflow heuristic (report-only; the agent decides what to cut)
# --------------------------------------------------------------------------

def estimate_overflow(ph, blocks, default_pt=18):
    """Rough text-fit estimate. Returns dict or None. Heuristic only: flags
    overflow risk for the agent to fix by trimming the outline, never silently
    shrinks font."""
    try:
        w_in = ph.width / float(EMU_PER_INCH)
        h_in = ph.height / float(EMU_PER_INCH)
    except Exception:
        return None
    if w_in <= 0 or h_in <= 0:
        return None
    sizes = [
        r.font.size.pt
        for p in ph.text_frame.paragraphs
        for r in p.runs
        if r.font.size is not None
    ]
    fs = sizes[0] if sizes else float(default_pt)
    char_w = fs * 0.55 / 72.0  # inches per average latin glyph
    per_line = max(1, int(w_in / char_w))
    lines = 0
    for text, _level in blocks:
        wide = sum(1 for c in text if ord(c) > 0x2E00)
        eff = wide * 2 + (len(text) - wide)
        lines += max(1, math.ceil(eff / float(per_line)))
    line_h = fs * 1.35 / 72.0
    capacity = max(1, int(h_in / line_h))
    return {
        "font_pt": fs,
        "est_lines": lines,
        "est_capacity": capacity,
        "overflow_risk": lines > capacity,
    }


# --------------------------------------------------------------------------
# slide-level operations (edit path)
# --------------------------------------------------------------------------

def delete_slide(prs, index):
    xml_slides = prs.slides._sldIdLst
    slides = list(xml_slides)
    if index < 0 or index >= len(slides):
        raise IndexError("slide index out of range: %s" % index)
    rId = slides[index].get(qn("r:id"))
    prs.part.drop_rel(rId)
    xml_slides.remove(slides[index])


def move_slide(prs, old_index, new_index):
    lst = prs.slides._sldIdLst
    els = list(lst)
    n = len(els)
    if not (0 <= old_index < n) or not (0 <= new_index < n):
        raise IndexError("slide index out of range")
    el = els[old_index]
    lst.remove(el)
    els = list(lst)
    lst.insert(new_index, el)


def duplicate_slide(prs, index):
    src = prs.slides[index]
    dest = prs.slides.add_slide(src.slide_layout)
    for shp in list(dest.shapes):
        shp._element.getparent().remove(shp._element)
    for shp in src.shapes:
        dest.shapes._spTree.append(deepcopy(shp._element))
    for rId, rel in list(src.part.rels.items()):
        if rel.reltype.endswith("/slideLayout") or rel.reltype.endswith("/notesSlide"):
            continue
        if rel.is_external:
            dest.part.rels.get_or_add_ext_rel(rel.reltype, rel.target_ref)
        else:
            dest.part.relate_to(rel.target_part, rel.reltype)
    if src.has_notes_slide:
        dest.notes_slide.notes_text_frame.text = src.notes_slide.notes_text_frame.text
    return dest


# --------------------------------------------------------------------------
# digests: raw + structural (rId-normalized c14n)
# --------------------------------------------------------------------------

_RID_ATTRS = ("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed",
              "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id",
              "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}link")


def _normalize_rids(element):
    """Deep-copy an element with all r:id / r:embed values replaced by 'R#'."""
    el = deepcopy(element)

    def walk(node):
        for attr in _RID_ATTRS:
            if node.get(attr) is not None:
                node.set(attr, "R#")
        for child in node:
            walk(child)

    walk(el)
    return el


def slide_digests(slide):
    """Return {'raw': sha256(part bytes), 'structural': sha256(c14n xml)}.

    The structural digest normalizes relationship ids so a slide counts as
    preserved even when the serializer renumbers rels or normalizes whitespace.
    """
    from lxml import etree as _etree

    part = slide.part
    raw = hashlib.sha256(part.blob).hexdigest()
    c14n_bytes = _etree.tostring(_normalize_rids(part._element), method="c14n2")
    structural = hashlib.sha256(c14n_bytes).hexdigest()
    return {"raw": raw, "structural": structural}


def master_digests(prs):
    """Digests for slide masters (raw bytes)."""
    out = []
    for master in prs.slide_masters:
        try:
            out.append(hashlib.sha256(master.part.blob).hexdigest())
        except Exception as exc:  # pragma: no cover - defensive
            out.append("error:%s" % exc)
    return out


def layout_digests(prs):
    out = []
    for layout in prs.slide_layouts:
        try:
            out.append(hashlib.sha256(layout.part.blob).hexdigest())
        except Exception as exc:  # pragma: no cover - defensive
            out.append("error:%s" % exc)
    return out


def declared_fonts(prs):
    """Distinct typefaces referenced by run properties across the deck."""
    fonts = set()
    for slide in prs.slides:
        for el in slide.part._element.iter():
            if el.tag in (qn("a:latin"), qn("a:ea"), qn("a:cs")):
                tf = el.get("typeface")
                if tf:
                    fonts.add(tf)
    for master in prs.slide_masters:
        for el in master.part._element.iter():
            if el.tag in (qn("a:latin"), qn("a:ea"), qn("a:cs")):
                tf = el.get("typeface")
                if tf:
                    fonts.add(tf)
    return sorted(fonts)
