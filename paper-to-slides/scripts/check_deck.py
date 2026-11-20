#!/usr/bin/env python3
"""check_deck.py -- verify the assembled deck before rendering.

Checks (report is JSON, every item is pass/warn/fail with evidence):
  slide_count   : deck length vs case limit
  placeholders  : share of body text living in template placeholders
                  (free text boxes = template violations), per slide + total
  overflow      : estimated wrapped-text height vs placeholder height
  images        : aspect ratio distortion of every picture (<2% tolerance)
  notes         : presence + overlap with slide text (notes must ADD, not
                  repeat: word-level Jaccard > 0.6 is flagged)
  evidence      : from the deck plan, every slide needs >=1 paper locator
                  (figure/table/section/quote with page)
Exit code 0 if no fail-level item, 5 otherwise.

Usage:
  python check_deck.py --deck out.pptx --plan deck_plan.json \
      [--max-slides N] --out check_report.json
"""
import argparse
import json
import math
import os
import sys

from pptx import Presentation
from pptx.util import Emu

from assemble_deck import (AVG_CHAR_W, LINE_SPACING, MIN_BODY_PT,
                           emu_to_pt, est_lines)

EMU_PER_PT = 12700


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def item(level, code, msg):
    return {"level": level, "code": code, "message": msg}


def check_placeholder_usage(prs, report):
    total_chars = in_ph_chars = 0
    per_slide = []
    for i, slide in enumerate(prs.slides, start=1):
        s_chars = s_in = 0
        for sh in slide.shapes:
            if not sh.has_text_frame:
                continue
            text = sh.text_frame.text.strip()
            if not text:
                continue
            is_ph = sh.is_placeholder
            # captions are the only sanctioned text box (see assembler)
            n_chars = len(text)
            s_chars += n_chars
            total_chars += n_chars
            if is_ph:
                s_in += n_chars
                in_ph_chars += n_chars
        per_slide.append({
            "slide": i,
            "chars": s_chars,
            "chars_in_placeholders": s_in,
            "textbox_chars": s_chars - s_in,
        })
    ratio = (in_ph_chars / total_chars) if total_chars else 1.0
    lvl = "pass" if ratio >= 0.9 else ("warn" if ratio >= 0.7 else "fail")
    report.append(item(lvl, "placeholders",
                       f"{in_ph_chars}/{total_chars} chars in placeholders "
                       f"({ratio:.0%})"))
    return per_slide, ratio


def check_overflow(prs, report):
    issues = []
    for i, slide in enumerate(prs.slides, start=1):
        for sh in slide.shapes:
            if not sh.has_text_frame or not sh.is_placeholder:
                continue
            tf = sh.text_frame
            text = tf.text.strip()
            if not text:
                continue
            font_pt = None
            for p in tf.paragraphs:
                for r in p.runs:
                    if r.font.size is not None:
                        font_pt = r.font.size.pt
                        break
                if font_pt:
                    break
            if font_pt is None:
                font_pt = 18.0
            width_pt = emu_to_pt(sh.width)
            height_pt = emu_to_pt(sh.height)
            lines = sum(est_lines(p.text, width_pt, font_pt)
                        for p in tf.paragraphs)
            need = lines * LINE_SPACING * font_pt
            if need > height_pt * 1.05:
                issues.append({
                    "slide": i, "shape": sh.name,
                    "est_lines": lines, "capacity_lines":
                        int(height_pt / (LINE_SPACING * font_pt)),
                    "font_pt": font_pt})
    lvl = "fail" if any(x["est_lines"] > 1.5 * x["capacity_lines"]
                        for x in issues) else ("warn" if issues else "pass")
    report.append(item(lvl, "overflow",
                       f"{len(issues)} overflowing placeholder(s)" if issues
                       else "no overflow estimated"))
    return issues


def is_picture_shape(sh):
    """a picture inserted into a placeholder keeps shape_type PLACEHOLDER,
    so detect via the underlying element tag (p:pic)"""
    if sh.shape_type == 13:
        return True
    return sh._element.tag.endswith("}pic")


def check_images(prs, report):
    from PIL import Image
    import io
    issues = []
    checked = 0
    for i, slide in enumerate(prs.slides, start=1):
        for sh in slide.shapes:
            if not is_picture_shape(sh):
                continue
            checked += 1
            try:
                blob = sh.image.blob
                with Image.open(io.BytesIO(blob)) as im:
                    nat_w, nat_h = im.size
                nat_ratio = nat_w / nat_h
                box_ratio = sh.width / sh.height
                # placeholders crop, so box_ratio >= nat_ratio is fine (cropped)
                # only stretching (both dims scaled differently) distorts:
                # a picture placed with only one explicit dim keeps ratio
                dist = abs(box_ratio - nat_ratio) / nat_ratio
                if sh.crop_left or sh.crop_right or sh.crop_top or sh.crop_bottom:
                    continue  # cropped to fit: aspect preserved by definition
                if dist > 0.02:
                    issues.append({"slide": i, "shape": sh.name,
                                   "distortion": round(dist, 3)})
            except Exception:
                issues.append({"slide": i, "shape": sh.name,
                               "distortion": "unreadable"})
    lvl = "warn" if issues else "pass"
    report.append(item(lvl, "images",
                       f"{checked} picture(s) checked, {len(issues)} distorted"
                       if checked else "no pictures"))
    return issues


def word_set(text):
    import re
    return set(w.lower() for w in re.findall(r"[A-Za-z0-9]+", text))


def check_notes(prs, report):
    issues = []
    for i, slide in enumerate(prs.slides, start=1):
        if not slide.has_notes_slide:
            issues.append({"slide": i, "issue": "missing"})
            continue
        notes = slide.notes_slide.notes_text_frame.text.strip()
        if not notes:
            issues.append({"slide": i, "issue": "empty"})
            continue
        slide_text = " ".join(sh.text_frame.text for sh in slide.shapes
                              if sh.has_text_frame)
        a, b = word_set(notes), word_set(slide_text)
        if a and b:
            jac = len(a & b) / len(a | b)
            if jac > 0.6:
                issues.append({"slide": i, "issue":
                               f"notes repeat slide text (jaccard {jac:.2f})"})
    lvl = "warn" if issues else "pass"
    report.append(item(lvl, "notes",
                       f"{len(issues)} note issue(s)" if issues
                       else "all slides have distinct speaker notes"))
    return issues


def check_evidence(plan, report):
    issues = []
    for spec in plan.get("slides", []):
        idx = spec.get("index", "?")
        ev = spec.get("evidence") or []
        if not ev:
            issues.append({"slide": idx, "issue": "no evidence pointer"})
            continue
        for e in ev:
            if not (e.get("locator") or e.get("quote")):
                issues.append({"slide": idx,
                               "issue": f"evidence without locator: {e}"})
    lvl = "fail" if issues else "pass"
    report.append(item(lvl, "evidence",
                       f"{len(issues)} evidence issue(s)" if issues
                       else "every slide maps to paper evidence"))
    return issues


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deck", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-slides", type=int, default=None)
    args = ap.parse_args()

    report = []
    prs = Presentation(args.deck)
    plan = load_json(args.plan)

    n = len(prs.slides)
    if args.max_slides is not None:
        report.append(item("pass" if n <= args.max_slides else "fail",
                           "slide_count",
                           f"{n} slides vs limit {args.max_slides}"))
    else:
        report.append(item("pass", "slide_count", f"{n} slides (no limit given)"))

    ph_detail, ph_ratio = check_placeholder_usage(prs, report)
    ov = check_overflow(prs, report)
    im = check_images(prs, report)
    nt = check_notes(prs, report)
    ev = check_evidence(plan, report)

    fails = [r for r in report if r["level"] == "fail"]
    result = {
        "deck": os.path.abspath(args.deck),
        "slide_count": n,
        "summary": {r["code"]: r["level"] for r in report},
        "checks": report,
        "details": {
            "placeholder_usage_per_slide": ph_detail,
            "placeholder_char_ratio": round(ph_ratio, 3),
            "overflow": ov,
            "images": im,
            "notes": nt,
            "evidence": ev,
        },
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps({"ok": not fails, "summary": result["summary"],
                      "out": os.path.abspath(args.out)}, ensure_ascii=False))
    sys.exit(0 if not fails else 5)


if __name__ == "__main__":
    main()
