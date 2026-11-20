# -*- coding: utf-8 -*-
"""check_deck.py — whole-deck consistency & template-inheritance audit.

Usage:
    python check_deck.py deck.pptx --out report.json [--template template.pptx]
        [--floor-title 20] [--floor-body 14] [--floor-caption 10]
        [--pdf deck.pdf]

Checks (each finding: slide, shape, code, severity, message, fix hint):
  OVERFLOW_EST        estimated text height exceeds placeholder (CJK-aware estimate)
  FONT_SIZE_FLOOR     a run is smaller than the readability floor
  FONT_OVERRIDE       a run overrides theme fonts by name (breaks inheritance)
  COLOR_OVERRIDE      a run carries an explicit srgb color outside the theme palette
  IMAGE_DISTORTION    displayed aspect deviates >3% from the (cropped) source aspect
  MISSING_TITLE       slide has no title text although its layout provides one
  TITLE_TOO_LONG      title estimated at more than 2 lines
  MISSING_NOTES       slide has no speaker notes / evidence block
  THEME_PALETTE       template palette summary (informational)
  PDF_PAGE_MISMATCH   pdf given and page count differs from slide count (if pypdf present)

Exit codes: 0 = pass/warn (deck usable), 1 = fail (error-level findings), 2 = unreadable.
The JSON report is the machine-readable contract for the agent's fix loop.
"""
from __future__ import annotations

import argparse
import io
import json
import sys

from PIL import Image

from tmpl_common import (
    AdaptError, DEFAULT_FLOORS, emu_to_pt, estimate_text_height_pt,
    force_utf8_stdout, master_text_styles, open_pptx, ph_type_name,
    run_color_override, run_font_override, run_size_pt, theme_of, write_json,
)

DISTORTION_TOL = 0.03  # 3% aspect deviation allowed
SEVERITY = {"OVERFLOW_EST": "error", "FONT_SIZE_FLOOR": "error",
            "IMAGE_DISTORTION": "error", "FONT_OVERRIDE": "warn",
            "COLOR_OVERRIDE": "warn", "MISSING_TITLE": "warn",
            "TITLE_TOO_LONG": "warn", "MISSING_NOTES": "info",
            "PDF_PAGE_MISMATCH": "error"}

FIX_HINTS = {
    "OVERFLOW_EST": "shorten bullets, drop one level, or split the slide; rebuild with build_deck.py",
    "FONT_SIZE_FLOOR": "raise size to the floor or cut content — never below the floor",
    "FONT_OVERRIDE": "remove the run-level font name so the theme font applies (or verify with font-discovery)",
    "COLOR_OVERRIDE": "use theme colors (accent1-6/dk/lt) instead of hardcoded srgbClr",
    "IMAGE_DISTORTION": "re-place the image aspect-true (placeholder center-crop or native fit)",
    "MISSING_TITLE": "write a title into the layout title placeholder",
    "TITLE_TOO_LONG": "shorten the title to <= 2 lines",
    "MISSING_NOTES": "add speaker notes and the [evidence] block via build_deck.py",
    "PDF_PAGE_MISMATCH": "re-export the PDF; page count must match the deck",
}


def add(findings, slide_no, shape_name, code, message):
    findings.append({
        "slide": slide_no, "shape": shape_name, "code": code,
        "severity": SEVERITY.get(code, "warn"),
        "message": message, "fix": FIX_HINTS.get(code, ""),
    })


def check_text(slide, slide_no, findings, floors, master_styles, palette):
    for shape in slide.shapes:
        if not shape.has_text_frame:
            continue
        name = shape.name or "shape"
        is_title = shape.is_placeholder and ph_type_name(shape) in ("TITLE", "CENTER_TITLE")
        is_ph = shape.is_placeholder

        # ---- collect paragraphs with effective sizes --------------------------
        paras = []
        for p in shape.text_frame.paragraphs:
            text = "".join(r.text for r in p.runs)
            if not text.strip():
                continue
            sizes = [run_size_pt(r) for r in p.runs if run_size_pt(r) is not None]
            paras.append({"level": p.level or 0, "text": text,
                          "size_pt": sizes[0] if sizes else None})
        if not paras:
            continue

        for p in paras:
            # title placeholders -> title floor; other placeholders -> body floor;
            # non-placeholder textboxes are auxiliary text (captions, annotations)
            # -> caption floor, matching what build_deck.py writes.
            if is_title:
                floor = floors["title"]
            elif is_ph:
                floor = floors["body"]
            else:
                floor = floors["caption"]
            if p["size_pt"] is not None and p["size_pt"] < floor:
                add(findings, slide_no, name, "FONT_SIZE_FLOOR",
                    "size %.1fpt < floor %.1fpt: %r" % (p["size_pt"], floor, p["text"][:40]))

        for p in shape.text_frame.paragraphs:
            for r in p.runs:
                fo = run_font_override(r)
                if fo:
                    add(findings, slide_no, name, "FONT_OVERRIDE",
                        "run font '%s' overrides theme fonts: %r" % (fo, r.text[:40]))
                co = run_color_override(r)
                if co and palette and co not in palette:
                    add(findings, slide_no, name, "COLOR_OVERRIDE",
                        "explicit color %s outside theme palette: %r" % (co, r.text[:40]))

        # ---- overflow estimate (placeholders only) -----------------------------
        if is_ph and shape.width and shape.height:
            resolved = []
            for p in paras:
                sz = p["size_pt"]
                if sz is None:
                    sz = (master_styles.get("title") or [None])[0] if is_title \
                        else None
                resolved.append({"level": p["level"], "text": p["text"], "size_pt": sz})
            est_h, avail_h, _ = estimate_text_height_pt(
                resolved, shape.width, shape.height, master_styles)
            if est_h > avail_h * 1.10:
                add(findings, slide_no, name, "OVERFLOW_EST",
                    "estimated %.0fpt of text in a %.0fpt box (ratio %.2f)" %
                    (est_h, avail_h, est_h / max(avail_h, 1)))


def check_title(slide, slide_no, findings, master_styles):
    has_layout_title = any(
        ph_type_name(ph) in ("TITLE", "CENTER_TITLE") for ph in slide.slide_layout.placeholders)
    title_ph = slide.shapes.title
    text = (title_ph.text_frame.text or "").strip() if title_ph is not None else ""
    if has_layout_title and not text:
        add(findings, slide_no, "(title)", "MISSING_TITLE",
            "layout provides a title placeholder but the slide has no title text")
    elif title_ph is not None and text:
        w = title_ph.width or 9144000
        paras = [{"level": 0, "text": text,
                  "size_pt": (master_styles.get("title") or [32.0])[0]}]
        _, _, detail = estimate_text_height_pt(paras, w, 12700 * 60, master_styles)
        lines = detail[0]["lines"] if detail else 1
        if lines > 2:
            add(findings, slide_no, "(title)", "TITLE_TOO_LONG",
                "estimated %d lines: %r" % (lines, text[:50]))


def check_pictures(slide, slide_no, findings):
    for shape in slide.shapes:
        # both Picture and PlaceholderPicture expose .image; text frames etc. do not
        if not hasattr(shape, "image"):
            continue
        name = shape.name or "picture"
        try:
            blob = shape.image.blob
            with Image.open(io.BytesIO(blob)) as im:
                nw, nh = im.size
        except Exception as exc:  # noqa: BLE001
            add(findings, slide_no, name, "IMAGE_DISTORTION",
                "cannot read image for aspect check: %s" % type(exc).__name__)
            continue
        cl = shape.crop_left or 0.0
        cr = shape.crop_right or 0.0
        ct = shape.crop_top or 0.0
        cb = shape.crop_bottom or 0.0
        src_w = nw * (1 - cl - cr)
        src_h = nh * (1 - ct - cb)
        if src_w <= 0 or src_h <= 0 or not shape.width or not shape.height:
            continue
        src_aspect = src_w / src_h
        disp_aspect = shape.width / shape.height
        dev = abs(disp_aspect - src_aspect) / src_aspect
        if dev > DISTORTION_TOL:
            add(findings, slide_no, name, "IMAGE_DISTORTION",
                "displayed aspect %.3f vs source aspect %.3f (%.0f%% deviation)" %
                (disp_aspect, src_aspect, dev * 100))


def check_notes(slide, slide_no, findings):
    txt = ""
    if slide.has_notes_slide:
        txt = slide.notes_slide.notes_text_frame.text or ""
    if not txt.strip():
        add(findings, slide_no, "(notes)", "MISSING_NOTES",
            "no speaker notes / evidence block")


def palette_set(prs):
    colors = set()
    for th in theme_of(prs):
        for v in th.get("colors", {}).values():
            if isinstance(v, str) and v.startswith("#"):
                colors.add(v)
    return colors


def count_pdf_pages(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        return None, "pypdf not installed — page check skipped"
    try:
        return len(PdfReader(path).pages), None
    except Exception as exc:  # noqa: BLE001
        return None, "pdf unreadable: %s" % type(exc).__name__


def main(argv=None):
    force_utf8_stdout()
    ap = argparse.ArgumentParser(description="Whole-deck consistency auditor")
    ap.add_argument("pptx")
    ap.add_argument("--out", default=None)
    ap.add_argument("--pdf", default=None, help="optional exported PDF to cross-check")
    ap.add_argument("--floor-title", type=float, default=DEFAULT_FLOORS["title"])
    ap.add_argument("--floor-body", type=float, default=DEFAULT_FLOORS["body"])
    ap.add_argument("--floor-caption", type=float, default=DEFAULT_FLOORS["caption"])
    args = ap.parse_args(argv)
    floors = {"title": args.floor_title, "body": args.floor_body,
              "caption": args.floor_caption}

    try:
        prs = open_pptx(args.pptx)
    except AdaptError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, ensure_ascii=False))
        return 2

    findings = []
    try:
        master_styles = master_text_styles(prs.slide_masters[0])
    except Exception:  # noqa: BLE001
        master_styles = {}
    palette = palette_set(prs)

    slides = list(prs.slides)
    for i, slide in enumerate(slides, start=1):
        try:
            check_text(slide, i, findings, floors, master_styles, palette)
            check_title(slide, i, findings, master_styles)
            check_pictures(slide, i, findings)
            check_notes(slide, i, findings)
        except Exception as exc:  # noqa: BLE001 — record, keep scanning other slides
            add(findings, i, "(slide)", "OVERFLOW_EST",
                "slide check crashed: %s: %s" % (type(exc).__name__, exc))

    pdf_note = None
    if args.pdf:
        pages, pdf_note = count_pdf_pages(args.pdf)
        if pages is not None and pages != len(slides):
            add(findings, None, "(pdf)", "PDF_PAGE_MISMATCH",
                "pdf has %d pages, deck has %d slides" % (pages, len(slides)))

    by_code = {}
    for f in findings:
        by_code.setdefault(f["code"], 0)
        by_code[f["code"]] += 1
    errors = sum(1 for f in findings if f["severity"] == "error")
    warns = sum(1 for f in findings if f["severity"] == "warn")
    status = "fail" if errors else ("warn" if warns else "pass")

    report = {
        "status": status,
        "file": args.pptx,
        "slide_count": len(slides),
        "theme_palette": sorted(palette),
        "floors_pt": floors,
        "summary": {"errors": errors, "warnings": warns, "by_code": by_code},
        "findings": findings,
        "pdf_check": {"pdf": args.pdf, "note": pdf_note},
        "method_note": "text heights are CJK-aware estimates; verify against the rendered PDF",
    }
    if args.out:
        write_json(args.out, report)
    print(json.dumps({"status": status, "slide_count": len(slides),
                      "summary": report["summary"],
                      "pdf_check": report["pdf_check"]}, ensure_ascii=False, indent=2))
    return 1 if status == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
