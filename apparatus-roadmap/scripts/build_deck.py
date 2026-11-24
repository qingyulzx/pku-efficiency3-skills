#!/usr/bin/env python3
"""build_deck.py — assemble an editable PPTX from an agent-authored page outline.

The agent owns every content decision (claims, order, what to cut); this script
only renders those decisions into an editable deck that respects the case
template, and reports every adaptation it had to make so the run stays
verifiable.

Robustness contract (each has a real disposal path, never silent fabrication):
  * template missing/unreadable      -> fall back to the default template, log it
  * layout name not found            -> pick by placeholder signature, then blank
  * no body placeholder              -> add a text box, log an adaptation
  * figure file missing              -> explicit [图缺失] marker box, never a placeholder image
  * slide budget exceeded            -> demote lowest-priority pages to backup appendix
  * bad outline                      -> precise error, nothing half-built

Usage:
  python build_deck.py --outline outline.json --out deck.pptx \
      [--template template.pptx] [--max-slides N] [--report build_report.json]
"""
import argparse
import hashlib
import json
import os
import sys

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu, Inches, Pt

EMU_W, EMU_H = None, None  # set after template load
FALLBACK_FONT = "Calibri"  # overridable via outline "font_fallback"
GREY = RGBColor(0x77, 0x77, 0x77)
DARK = RGBColor(0x20, 0x20, 0x20)
WARN = RGBColor(0x9A, 0x2E, 0x2E)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_template(path, report):
    if path and os.path.isfile(path):
        try:
            prs = Presentation(path)
            report["template"] = {
                "path": path, "sha256": sha256_file(path),
                "source": "case template",
                "slide_size": [prs.slide_width, prs.slide_height],
            }
            return prs
        except Exception as e:  # noqa: BLE001
            report["warnings"].append(
                "template unreadable (%s) — using default template" % e)
    elif path:
        report["warnings"].append(
            "template path not found (%s) — using default template" % path)
        report["template"] = {"source": "default python-pptx template"}
    else:
        report["template"] = {"source": "default python-pptx template"}
    return Presentation()


def layout_inventory(prs):
    inv = []
    for master in prs.slide_masters:
        for lay in master.slide_layouts:
            inv.append(lay)
    return inv


def pick_layout(prs, page, report):
    """page.type -> layout, by name then by placeholder signature, then blank."""
    ptype = page.get("type", "content")
    want_name = {
        "title": ["title slide"],
        "section": ["section header", "section"],
        "content": ["title and content", "title & content", "content"],
        "two_column": ["two content", "comparison", "two-column"],
        "closing": ["title slide", "closing"],
        "backup": ["title and content", "content", "blank"],
    }.get(ptype, ["content", "blank"])

    layouts = layout_inventory(prs)
    for frag in want_name:
        for lay in layouts:
            if frag in lay.name.lower():
                return lay, "name match (%s)" % lay.name

    def sig(lay):
        kinds = sorted(str(ph.placeholder_format.type) for ph in lay.placeholders)
        return kinds

    need = {  # signature: (title?, body count)
        "title": (1, 0), "section": (1, 0),
        "content": (1, 1), "two_column": (1, 2), "closing": (1, 0),
        "backup": (1, 1),
    }.get(ptype, (1, 1))
    best, best_score = None, -1
    for lay in layouts:
        kinds = sig(lay)
        t = sum(1 for k in kinds if "TITLE" in k)
        b = sum(1 for k in kinds
                if "BODY" in k or "CONTENT" in k or "OBJECT" in k)
        score = 0
        if t >= need[0]:
            score += 2
        if b >= need[1]:
            score += 2
        if score > best_score:
            best, best_score = lay, score
    if best is not None and best_score >= 2:
        return best, "signature match (%s)" % best.name
    for lay in layouts:
        if "blank" in lay.name.lower():
            return lay, "blank fallback"
    report["warnings"].append("no usable layout for page type %r" % ptype)
    return layouts[-1], "last-resort layout (%s)" % layouts[-1].name


def placeholder_by(phs, want):
    for ph in phs:
        t = str(ph.placeholder_format.type)
        if want in t:
            return ph
    if want in ("BODY", "CONTENT"):  # default template uses OBJECT(7)
        for ph in phs:
            t = str(ph.placeholder_format.type)
            if "OBJECT" in t or "BODY" in t or "CONTENT" in t:
                return ph
    return None


def set_text(tf, lines, font=None, size=None, color=None, bullet_glyph=None):
    """Write bullet lines into a text frame. '  - ' prefix = level 1."""
    tf.word_wrap = True
    first = True
    for raw in lines:
        level = 0
        s = raw
        if isinstance(raw, str) and raw.startswith((" ", "\t")):
            level = 1
            s = raw.lstrip(" -\t")
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.text = s
        p.level = level
        if size:
            for r in p.runs:
                r.font.size = Pt(size)
        if font:
            for r in p.runs:
                r.font.name = font
        if color:
            for r in p.runs:
                r.font.color.rgb = color


def add_textbox(slide, l, t, w, h, lines, font=None, size=14, color=None,
                italic=False):
    box = slide.shapes.add_textbox(l, t, w, h)
    tf = box.text_frame
    tf.word_wrap = True
    set_text(tf, lines, font=font, size=size, color=color)
    if italic:
        for p in tf.paragraphs:
            for r in p.runs:
                r.font.italic = True
    return box


def add_picture_fit(slide, path, box_l, box_t, box_w, box_h):
    """Insert picture scaled to fit the box, preserving aspect ratio."""
    from PIL import Image
    with Image.open(path) as im:
        iw, ih = im.size
    if iw <= 0 or ih <= 0:
        raise ValueError("bad image size")
    scale = min(box_w / iw, box_h / ih)
    w, h = int(iw * scale), int(ih * scale)
    left = box_l + (box_w - w) // 2
    top = box_t + (box_h - h) // 2
    return slide.shapes.add_picture(path, left, top, width=w, height=h)


def notes_text(page):
    parts = []
    if page.get("notes"):
        parts.append(page["notes"])
    qa = page.get("qa") or []
    if qa:
        parts.append("[问答预案]")
        for item in qa[:6]:
            parts.append("Q: %s\nA: %s" % (item.get("q", "?"), item.get("a", "")))
    return "\n\n".join(parts)


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


def build(args):
    with open(args.outline, "r", encoding="utf-8") as f:
        outline = json.load(f)
    for key in ("case_id", "pages"):
        if key not in outline:
            print(json.dumps({"status": "error",
                              "reason": "outline missing required key %r" % key}))
            sys.exit(2)
    pages = outline["pages"]
    for i, p in enumerate(pages, 1):
        if "title" not in p:
            print(json.dumps({"status": "error",
                              "reason": "page %d has no title" % i}))
            sys.exit(2)

    report = {"case_id": outline.get("case_id"), "adaptations": [],
              "warnings": [], "demotions": [], "figure_status": [],
              "layout_usage": [], "font_fallback": FALLBACK_FONT}
    prs = load_template(args.template, report)
    if max(prs.slide_width, 1) > 0:
        global EMU_W, EMU_H
        EMU_W, EMU_H = prs.slide_width, prs.slide_height

    if args.max_slides:
        pages = enforce_budget(pages, args.max_slides, report)

    for page in pages:
        lay, how = pick_layout(prs, page, report)
        slide = prs.slides.add_slide(lay)
        report["layout_usage"].append(
            {"page": page.get("page_no"), "type": page.get("type"),
             "layout": lay.name, "selection": how})
        phs = list(slide.placeholders)

        title = placeholder_by(phs, "TITLE")
        title_txt = page.get("title", "")
        if page.get("type") == "backup":
            title_txt = "备用 | " + title_txt
        if title is not None:
            title.text = title_txt
        else:
            add_textbox(slide, Inches(0.5), Inches(0.25), EMU_W - Inches(1),
                        Inches(0.9), [title_txt], size=26, color=DARK)
            report["adaptations"].append(
                {"page": page.get("page_no"), "what": "title text box added",
                 "why": "layout has no title placeholder"})

        bullets = [b for b in (page.get("bullets") or []) if str(b).strip()]
        figs = page.get("figures") or []
        avail = [fg for fg in figs if fg.get("status") == "available"]
        missing = [fg for fg in figs if fg.get("status") != "available"]

        if not figs:
            body = placeholder_by(phs, "BODY") or placeholder_by(phs, "CONTENT")
            if body is not None and bullets:
                set_text(body.text_frame, bullets, size=16)
            elif bullets:
                add_textbox(slide, Inches(0.6), Inches(1.4), EMU_W - Inches(1.2),
                            EMU_H - Inches(2.4), bullets, size=16)
                report["adaptations"].append(
                    {"page": page.get("page_no"),
                     "what": "body text box added",
                     "why": "layout has no body placeholder"})
        else:
            # split: text left, figure(s) right
            if bullets:
                add_textbox(slide, Inches(0.5), Inches(1.35),
                            int(EMU_W * 0.52) - Inches(0.5),
                            EMU_H - Inches(2.3), bullets, size=15)
            fig_l = int(EMU_W * 0.54)
            fig_t = Inches(1.35)
            fig_w = int(EMU_W * 0.44)
            fig_h = EMU_H - Inches(2.3)
            for fg in avail:
                fpath = fg.get("path", "")
                try:
                    add_picture_fit(slide, fpath, fig_l, fig_t, fig_w, fig_h)
                    report["figure_status"].append(
                        {"page": page.get("page_no"), "figure": fpath,
                         "status": "inserted"})
                except Exception as e:  # noqa: BLE001
                    add_textbox(slide, fig_l, fig_t, fig_w, Inches(0.6),
                                ["[图缺失] %s（插入失败：%s）" % (
                                    fg.get("caption", fpath), e)],
                                size=12, color=WARN)
                    report["figure_status"].append(
                        {"page": page.get("page_no"), "figure": fpath,
                         "status": "insert failed: %s" % e})
            for fg in missing:
                add_textbox(slide, fig_l, fig_t, fig_w, Inches(0.6),
                            ["[图缺失] %s（源：%s）" % (
                                fg.get("caption", ""),
                                fg.get("locator", "材料中未提供"))],
                            size=12, color=WARN)
                report["figure_status"].append(
                    {"page": page.get("page_no"), "figure": fg.get("path"),
                     "status": "missing in materials — marked, not fabricated"})
            if not avail and not bullets:
                report["warnings"].append(
                    "page %s has neither usable figure nor bullets" %
                    page.get("page_no"))

        # evidence footer with source locators
        ev = page.get("evidence") or []
        locs = [e.get("locator", "") for e in ev if e.get("locator")][:3]
        strengths = {e.get("strength") for e in ev if e.get("strength")}
        if "gap" in strengths:
            locs.append("⚠ 本页存在证据缺口，见 result.json 不确定性说明")
        if locs:
            add_textbox(slide, Inches(0.5), EMU_H - Inches(0.42),
                        EMU_W - Inches(1), Inches(0.35),
                        ["源: " + " | ".join(locs)], size=9, color=GREY)

        # speaker notes (talking script + Q&A drill)
        nt = notes_text(page)
        if nt:
            slide.notes_slide.notes_text_frame.text = nt

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    prs.save(args.out)

    content_pages = sum(1 for p in pages if p.get("type") != "backup")
    backup_pages = sum(1 for p in pages if p.get("type") == "backup")
    report.update({"status": "ok", "deck": args.out,
                   "content_pages": content_pages, "backup_pages": backup_pages,
                   "total_slides": content_pages + backup_pages})
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: report[k] for k in
                      ("status", "deck", "content_pages", "backup_pages",
                       "total_slides", "warnings") if k in report},
                     ensure_ascii=False))
    if report["warnings"]:
        sys.exit(0)  # warnings are recorded, deck still built


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outline", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--template", default=None)
    ap.add_argument("--max-slides", type=int, default=0)
    ap.add_argument("--report", default=None)
    args = ap.parse_args()
    if not os.path.isfile(args.outline):
        print(json.dumps({"status": "error",
                          "reason": "outline not found: %s" % args.outline}))
        sys.exit(2)
    try:
        build(args)
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"status": "error", "reason": "build failed: %s" % e}))
        sys.exit(1)


if __name__ == "__main__":
    main()
