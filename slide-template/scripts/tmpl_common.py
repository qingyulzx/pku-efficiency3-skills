# -*- coding: utf-8 -*-
"""tmpl_common.py — shared helpers for the academic PPT template-adaptation scripts.

Used by analyze_template.py / build_deck.py / check_deck.py.
Design rule of the whole toolchain: never hardcode font names or RGB colors into
slides; let placeholders inherit master/layout/theme typography. The only
explicit typography we ever write is a *font size* (the readability ladder),
and every such override is reported so it can be audited.
"""
from __future__ import annotations

import io
import json
import math
import re
import sys

from lxml import etree

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.oxml.ns import qn

EMU_PER_PT = 12700.0
EMU_PER_IN = 914400.0

# Default text insets (python-pptx / OOXML defaults): 0.1in left/right, 0.05in top/bottom
DEFAULT_LINS_EMU = 91440
DEFAULT_TINS_EMU = 45720

# Readability red line — floors for the font-size ladder (points).
DEFAULT_FLOORS = {"title": 20.0, "body": 14.0, "caption": 10.0}

# Fallback body sizes per outline level when neither run, paragraph nor master
# defines one (used only for capacity estimation and ladder stepping).
FALLBACK_LEVEL_SIZES = {0: 24.0, 1: 20.0, 2: 18.0}
FALLBACK_LEVEL_SIZE_DEEP = 16.0
FALLBACK_TITLE_SIZE = 32.0
LINE_SPACING = 1.18          # effective line box as multiple of font size
PARA_SPACE = 0.40            # vertical space between paragraphs, multiple of font size

PH_TYPE_NAMES = {
    PP_PLACEHOLDER.TITLE: "TITLE",
    PP_PLACEHOLDER.CENTER_TITLE: "CENTER_TITLE",
    PP_PLACEHOLDER.SUBTITLE: "SUBTITLE",
    PP_PLACEHOLDER.BODY: "BODY",
    PP_PLACEHOLDER.PICTURE: "PICTURE",
    PP_PLACEHOLDER.CHART: "CHART",
    PP_PLACEHOLDER.TABLE: "TABLE",
    PP_PLACEHOLDER.MEDIA_CLIP: "MEDIA",
    PP_PLACEHOLDER.BITMAP: "CLIP_ART",
    PP_PLACEHOLDER.DATE: "DATE",
    PP_PLACEHOLDER.FOOTER: "FOOTER",
    PP_PLACEHOLDER.SLIDE_NUMBER: "SLIDE_NUMBER",
}


class AdaptError(Exception):
    """Raised with a machine-readable reason (see references/exceptions.md)."""


def force_utf8_stdout():
    """Reconfigure stdout/stderr to UTF-8 with replacement (Windows GBK consoles).

    Harmless on POSIX (already UTF-8); keeps JSON output printable everywhere.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and (stream.encoding or "").lower() not in ("utf-8", "utf8"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — redirected/non-tty streams may not support it
            pass


def ph_type_name(ph):
    try:
        t = ph.placeholder_format.type
    except Exception:  # noqa: BLE001 — corrupted placeholderFormat
        return "UNKNOWN"
    if t is None:
        return "UNKNOWN"
    # unmapped members: str(t) is e.g. "OBJECT (7)" — use the bare enum name
    return PH_TYPE_NAMES.get(t, getattr(t, "name", str(t).split(" (")[0]))


def ph_is_body_like(ph):
    # OOXML templates use both <p:ph type="body"> and type="obj" for content
    return ph_type_name(ph) in ("BODY", "OBJECT", "SUBTITLE", "CENTER_TITLE")


def open_pptx(path):
    """Open a pptx honestly: any failure raises AdaptError with a reason code."""
    try:
        prs = Presentation(path)
    except Exception as exc:  # noqa: BLE001 — we need the real reason
        raise AdaptError(
            "UNREADABLE_PPTX:%s:%s" % (path, type(exc).__name__)
        ) from exc
    return prs


# --------------------------------------------------------------------------
# geometry helpers
# --------------------------------------------------------------------------

def _master_placeholder(master, idx):
    for ph in master.placeholders:
        if ph.placeholder_format.idx == idx:
            return ph
    return None


def effective_geometry(ph, layout, master):
    """Return (left, top, width, height) in EMU, resolving layout->master inheritance."""
    vals = {}
    for attr in ("left", "top", "width", "height"):
        v = getattr(ph, attr)
        if v is None:
            src = _master_placeholder(master, ph.placeholder_format.idx) if master else None
            v = getattr(src, attr, None) if src is not None else None
        vals[attr] = v  # may still be None (template never positions it)
    return vals["left"], vals["top"], vals["width"], vals["height"]


def emu_to_pt(v):
    return None if v is None else v / EMU_PER_PT


def emu_to_in(v):
    return None if v is None else v / EMU_PER_IN


# --------------------------------------------------------------------------
# theme extraction (colors + fonts) — read-only, from the master's theme part
# --------------------------------------------------------------------------

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def _theme_part_for_master(master):
    for rel in master.part.rels.values():
        if rel.reltype.endswith("/theme"):
            try:
                return rel.target_part
            except Exception:  # noqa: BLE001
                continue
    return None


def _clr_val(el):
    if el is None:
        return None
    srgb = el.find("{%s}srgbClr" % A_NS)
    if srgb is not None:
        return "#" + (srgb.get("val") or "").upper()
    sysc = el.find("{%s}sysClr" % A_NS)
    if sysc is not None:
        v = sysc.get("lastClr")
        return ("#" + v.upper()) if v else "#" + (sysc.get("val") or "window").upper()
    return None


def theme_of(prs):
    """Extract theme colors/fonts for each slide master. Never writes anything."""
    themes = []
    for master in prs.slide_masters:
        part = _theme_part_for_master(master)
        info = {"master": master.name or "Slide Master", "colors": {}, "fonts": {}}
        if part is None:
            info["error"] = "NO_THEME_PART"
            themes.append(info)
            continue
        try:
            root = etree.fromstring(part.blob)
        except Exception as exc:  # noqa: BLE001
            info["error"] = "THEME_PARSE_FAILED:%s" % type(exc).__name__
            themes.append(info)
            continue
        scheme = root.find(".//{%s}clrScheme" % A_NS)
        if scheme is not None:
            for child in scheme:
                key = etree.QName(child).localname
                info["colors"][key] = _clr_val(child)
        fScheme = root.find(".//{%s}fontScheme" % A_NS)
        if fScheme is not None:
            for major, tag in ((True, "majorFont"), (False, "minorFont")):
                fs = fScheme.find("{%s}%s" % (A_NS, tag))
                if fs is None:
                    continue
                pref = "major" if major else "minor"
                latin = fs.find("{%s}latin" % A_NS)
                ea = fs.find("{%s}ea" % A_NS)
                info["fonts"][pref + "_latin"] = latin.get("typeface") if latin is not None else None
                info["fonts"][pref + "_ea"] = ea.get("typeface") if ea is not None else None
        themes.append(info)
    return themes


# --------------------------------------------------------------------------
# master text-style ladder (default sizes per outline level)
# --------------------------------------------------------------------------

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _lvl_sizes(style_el, max_lvl=5):
    out = []
    for lvl in range(1, max_lvl + 1):
        pr = style_el.find("{%s}lvl%dpPr" % (P_NS, lvl))
        if pr is None:
            out.append(None)
            continue
        for defRPr in pr.findall("{%s}defRPr" % A_NS):
            sz = defRPr.get("sz")
            out.append(float(sz) / 100.0 if sz else None)
            break
        else:
            out.append(None)
    return out


def master_text_styles(master):
    """Return {'title': [sz...], 'body': [sz...]} default ladders, None where unset."""
    res = {}
    tx = master.element.find("{%s}txStyles" % P_NS)
    if tx is None:
        return res
    for key, tag in (("title", "titleStyle"), ("body", "bodyStyle"), ("other", "otherStyle")):
        el = tx.find("{%s}%s" % (P_NS, tag))
        if el is not None:
            res[key] = _lvl_sizes(el)
    return res


def body_level_size(master_styles, level):
    ladder = (master_styles or {}).get("body") or []
    if level < len(ladder) and ladder[level] is not None:
        return ladder[level]
    if level in FALLBACK_LEVEL_SIZES:
        return FALLBACK_LEVEL_SIZES[level]
    return FALLBACK_LEVEL_SIZE_DEEP


def title_default_size(master_styles):
    ladder = (master_styles or {}).get("title") or []
    return ladder[0] if ladder and ladder[0] else FALLBACK_TITLE_SIZE


# --------------------------------------------------------------------------
# text-capacity estimation (explicitly an *estimate*; the PDF render is truth)
# --------------------------------------------------------------------------

_CJK_RE = re.compile(r"[\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff\u3000-\u303f]")


def _char_width_pt(text, size_pt):
    """Average glyph width: CJK ~0.98em, latin ~0.52em, digits/punct between."""
    n = max(len(text), 1)
    cjk = len(_CJK_RE.findall(text))
    ratio = cjk / n
    return size_pt * (0.98 * ratio + 0.52 * (1 - ratio))


def estimate_text_height_pt(paras, width_emu, height_emu, master_styles=None):
    """Estimate rendered text height (pt) of a list of paragraph dicts.

    paras: [{"level": int, "text": str, "size_pt": float|None}, ...]
    Width/height in EMU (the placeholder box). Returns (est_height_pt, avail_pt, detail).
    """
    w_pt = emu_to_pt(width_emu) or 0.0
    h_pt = emu_to_pt(height_emu) or 0.0
    usable_w = max(w_pt - 2 * emu_to_pt(DEFAULT_LINS_EMU), 10.0)
    avail_h = max(h_pt - 2 * emu_to_pt(DEFAULT_TINS_EMU), 6.0)
    total = 0.0
    detail = []
    for p in paras:
        size = p.get("size_pt")
        if size is None:
            size = body_level_size(master_styles, p.get("level", 0))
        text = p.get("text", "")
        indent = 0.30 * p.get("level", 0) * size  # per-level indent approximation
        line_w = max(usable_w - indent, 10.0)
        cw = _char_width_pt(text, size)
        lines = max(1, math.ceil((len(text) * cw) / line_w)) if text else 1
        para_h = lines * size * LINE_SPACING + PARA_SPACE * size
        total += para_h
        detail.append({"level": p.get("level", 0), "lines": lines, "size_pt": size,
                       "est_h": round(para_h, 1)})
    return round(total, 1), round(avail_h, 1), detail


# --------------------------------------------------------------------------
# layout capability scoring — the content->layout mapping used by analyzer & builder
# --------------------------------------------------------------------------

def layout_caps(layout, master):
    caps = {"has_title": False, "has_center_title": False, "has_subtitle": False,
            "body_count": 0, "picture_count": 0, "has_footer": False, "has_slidenum": False,
            "has_date": False}
    for ph in layout.placeholders:
        t = ph_type_name(ph)
        if t in ("TITLE",):
            caps["has_title"] = True
        elif t == "CENTER_TITLE":
            caps["has_center_title"] = True
        elif t == "SUBTITLE":
            caps["has_subtitle"] = True
        elif t in ("BODY", "OBJECT"):
            caps["body_count"] += 1
        elif t == "PICTURE":
            caps["picture_count"] += 1
        elif t == "FOOTER":
            caps["has_footer"] = True
        elif t == "SLIDE_NUMBER":
            caps["has_slidenum"] = True
        elif t == "DATE":
            caps["has_date"] = True
    return caps


ROLE_REQUIREMENTS = {
    # role: list of (predicate, score) — first layout maximizing score wins
    "title":      [(lambda c: c["has_center_title"] and c["has_subtitle"], 3),
                   (lambda c: c["has_title"] and c["has_subtitle"], 2),
                   (lambda c: c["has_center_title"], 2),
                   (lambda c: c["has_title"] and c["body_count"] >= 1, 1)],
    "section":    [(lambda c: c["has_center_title"], 3),
                   (lambda c: c["has_title"], 2)],
    "content":    [(lambda c: c["has_title"] and c["body_count"] == 1, 3),
                   (lambda c: c["has_title"] and c["body_count"] >= 1, 2),
                   (lambda c: c["body_count"] >= 1, 1)],
    "two_content": [(lambda c: c["has_title"] and c["body_count"] >= 2, 3),
                    (lambda c: c["body_count"] >= 2, 2),
                    (lambda c: c["has_title"] and c["body_count"] >= 1, 1)],
    "picture":    [(lambda c: c["has_title"] and c["picture_count"] >= 1 and c["body_count"] >= 1, 4),
                   (lambda c: c["picture_count"] >= 1, 3),
                   (lambda c: c["has_title"] and c["body_count"] >= 1, 1)],
    "closing":    [(lambda c: c["has_center_title"] and c["has_subtitle"], 3),
                   (lambda c: c["has_title"] and c["body_count"] >= 1, 2),
                   (lambda c: c["has_title"], 1)],
}


def score_layout_for_role(caps, role):
    best = 0
    for pred, sc in ROLE_REQUIREMENTS.get(role, ROLE_REQUIREMENTS["content"]):
        if pred(caps):
            best = max(best, sc)
    return best


def suggest_layouts(prs):
    """For each role, the best layout per master: {role: [{master, index, name, score}]}"""
    out = {}
    for master in prs.slide_masters:
        for i, layout in enumerate(master.slide_layouts):
            caps = layout_caps(layout, master)
            for role in ROLE_REQUIREMENTS:
                sc = score_layout_for_role(caps, role)
                if sc > 0:
                    out.setdefault(role, []).append(
                        {"master": master.name or "Slide Master", "index": i,
                         "name": layout.name or "Layout %d" % i, "score": sc})
    for role, lst in out.items():
        lst.sort(key=lambda d: -d["score"])
    return out


def resolve_layout(prs, spec, warnings):
    """Pick the layout for one slide spec. Explicit name/index always wins."""
    want = spec.get("layout")
    if want is not None:
        for master in prs.slide_masters:
            for i, layout in enumerate(master.slide_layouts):
                if want == i or (layout.name and want == layout.name):
                    return layout
        warnings.append("LAYOUT_NOT_FOUND:%s — fell back to role matching" % want)
    role = spec.get("role", "content")
    sugg = suggest_layouts(prs).get(role) or []
    if not sugg:
        # last resort: first layout with a title, else layout 0
        for master in prs.slide_masters:
            for i, layout in enumerate(master.slide_layouts):
                if layout_caps(layout, master)["has_title"]:
                    warnings.append("NO_LAYOUT_FOR_ROLE:%s — used first titled layout" % role)
                    return layout
        warnings.append("NO_LAYOUT_FOR_ROLE:%s — used layout index 0" % role)
        return prs.slide_masters[0].slide_layouts[0]
    top = sugg[0]
    for master in prs.slide_masters:
        layouts = master.slide_layouts
        if 0 <= top["index"] < len(layouts):
            return layouts[top["index"]]
    return prs.slide_masters[0].slide_layouts[0]


# --------------------------------------------------------------------------
# run/paragraph inspection (used by the consistency checker)
# --------------------------------------------------------------------------

def run_font_override(run):
    """Return latin typeface if the run overrides theme fonts, else None."""
    rPr = run._r.find(qn("a:rPr"))
    if rPr is None:
        return None
    for tag in ("a:latin", "a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is not None and el.get("typeface"):
            return el.get("typeface")
    return None


def run_color_override(run):
    """Return explicit srgbClr value if set at run level, else None."""
    rPr = run._r.find(qn("a:rPr"))
    if rPr is None:
        return None
    fill = rPr.find(qn("a:solidFill"))
    if fill is None:
        return None
    srgb = fill.find(qn("a:srgbClr"))
    if srgb is not None and srgb.get("val"):
        return "#" + srgb.get("val").upper()
    return None


def run_size_pt(run):
    rPr = run._r.find(qn("a:rPr"))
    if rPr is None or not rPr.get("sz"):
        return None
    try:
        return int(rPr.get("sz")) / 100.0
    except ValueError:
        return None


def iter_text_frames(slide):
    """Yield (shape, placeholder_or_None, text_frame) for shapes with text."""
    for shp in slide.shapes:
        if shp.has_text_frame:
            yield shp, (shp if shp.is_placeholder else None), shp.text_frame


def write_json(path, obj):
    with io.open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)


def para_dicts_from_bullets(bullets, master_styles, sizes=None):
    """Convert [{'level':..,'text':..}] to estimator paragraph dicts with sizes."""
    out = []
    for b in bullets:
        lvl = int(b.get("level", 0))
        size = (sizes or {}).get(lvl) if sizes else None
        if size is None:
            size = body_level_size(master_styles, lvl)
        out.append({"level": lvl, "text": b.get("text", ""), "size_pt": size})
    return out
