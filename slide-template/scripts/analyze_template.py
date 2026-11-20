# -*- coding: utf-8 -*-
"""analyze_template.py — template capability manifest for academic PPT adaptation.

Usage:
    python analyze_template.py <template.pptx> [--out manifest.json]

Read-only. Never modifies the pptx. Output (stdout and optional --out JSON):
  - slide size
  - per-master theme colors + theme fonts (major/minor, latin/ea)
  - per-master default text-style ladders (title/body sizes per level)
  - every layout with its placeholders (idx/type/geometry/cloneable), capability flags
  - which layouts existing slides already use (starting-deck awareness)
  - suggested role->layout mapping (title/section/content/two_content/picture/closing)
  - anomalies that the builder must compensate for (missing titles, tiny boxes...)

Exit codes: 0 ok, 2 unreadable file (see references/exceptions.md).
"""
from __future__ import annotations

import argparse
import json
import sys

from pptx.enum.shapes import PP_PLACEHOLDER

from tmpl_common import (
    AdaptError, DEFAULT_FLOORS, effective_geometry, emu_to_in, emu_to_pt,
    force_utf8_stdout, layout_caps, master_text_styles, open_pptx, ph_type_name,
    suggest_layouts, theme_of, write_json,
)

# python-pptx clones these placeholder types onto new slides (SlideLayout.iter_cloneable_placeholders)
CLONEABLE = {
    PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.CENTER_TITLE,
    PP_PLACEHOLDER.SUBTITLE, PP_PLACEHOLDER.PICTURE, PP_PLACEHOLDER.CHART,
    PP_PLACEHOLDER.TABLE, PP_PLACEHOLDER.MEDIA_CLIP, PP_PLACEHOLDER.BITMAP,
    PP_PLACEHOLDER.OBJECT, PP_PLACEHOLDER.VERTICAL_BODY, PP_PLACEHOLDER.VERTICAL_OBJECT,
}


def placeholder_info(ph, layout, master):
    left, top, width, height = effective_geometry(ph, layout, master)
    try:
        idx = ph.placeholder_format.idx
    except Exception:  # noqa: BLE001
        idx = None
    tname = ph_type_name(ph)
    try:
        cloneable = ph.placeholder_format.type in CLONEABLE
    except Exception:  # noqa: BLE001
        cloneable = False
    # smallest default body size advertised by this placeholder's prompt text runs
    prompt_sizes = []
    try:
        for p in ph.text_frame.paragraphs:
            for r in p.runs:
                if r.font.size is not None:
                    prompt_sizes.append(round(r.font.size.pt, 1))
    except Exception:  # noqa: BLE001 — corrupted placeholder text
        pass
    return {
        "idx": idx,
        "type": tname,
        "name": ph.name,
        "cloneable": cloneable,
        "x_in": round(emu_to_in(left), 2) if left is not None else None,
        "y_in": round(emu_to_in(top), 2) if top is not None else None,
        "w_in": round(emu_to_in(width), 2) if width is not None else None,
        "h_in": round(emu_to_in(height), 2) if height is not None else None,
        "area_in2": round(emu_to_in(width) * emu_to_in(height), 2)
        if width and height else None,
        "prompt_text": (ph.text_frame.text or "")[:120] if ph.has_text_frame else "",
        "prompt_sizes_pt": sorted(set(prompt_sizes)),
    }


def layout_info(layout, master, used_by):
    caps = layout_caps(layout, master)
    phs = [placeholder_info(ph, layout, master) for ph in layout.placeholders]
    return {
        "index": list(master.slide_layouts).index(layout),
        "name": layout.name,
        "used_by_slides": sorted(used_by.get(layout.name, [])),
        "capabilities": caps,
        "placeholders": phs,
    }


def analyze(path):
    prs = open_pptx(path)
    used_by = {}
    for i, slide in enumerate(prs.slides, start=1):
        try:
            ln = slide.slide_layout.name
        except Exception:  # noqa: BLE001
            ln = None
        if ln:
            used_by.setdefault(ln, []).append(i)

    masters_out = []
    for master in prs.slide_masters:
        layouts = [layout_info(l, master, used_by) for l in master.slide_layouts]
        masters_out.append({
            "name": master.name or "Slide Master",
            "text_style_ladders_pt": master_text_styles(master),
            "layout_count": len(layouts),
            "layouts": layouts,
        })

    anomalies = []
    for m in masters_out:
        for lay in m["layouts"]:
            if not (lay["capabilities"]["has_title"] or lay["capabilities"]["has_center_title"]):
                anomalies.append("LAYOUT_WITHOUT_TITLE:%s/%s" % (m["name"], lay["name"]))
            for ph in lay["placeholders"]:
                if ph["type"] in ("BODY", "SUBTITLE") and ph["h_in"] is not None and ph["h_in"] < 0.8:
                    anomalies.append(
                        "TINY_BODY_PLACEHOLDER:%s/%s idx=%s h=%.2fin" %
                        (m["name"], lay["name"], ph["idx"], ph["h_in"]))
                if ph["w_in"] is None or ph["h_in"] is None:
                    anomalies.append(
                        "UNPOSITIONED_PLACEHOLDER:%s/%s idx=%s (inherits nothing)" %
                        (m["name"], lay["name"], ph["idx"]))
    if not any(l["capabilities"]["picture_count"] for m in masters_out for l in m["layouts"]):
        anomalies.append("NO_PICTURE_LAYOUT: images will be placed in computed free areas")

    return {
        "file": path,
        "slide_count": len(list(prs.slides)),
        "slide_size": {
            "width_emu": prs.slide_width, "height_emu": prs.slide_height,
            "width_in": round(emu_to_in(prs.slide_width), 2),
            "height_in": round(emu_to_in(prs.slide_height), 2),
        },
        "themes": theme_of(prs),
        "masters": masters_out,
        "suggested_role_mapping": suggest_layouts(prs),
        "readability_floors_pt": DEFAULT_FLOORS,
        "anomalies": anomalies,
        "notes": "Estimator detail: text heights are estimated (CJK-aware), not rendered; "
                 "the exported PDF remains the ground truth for overflow.",
    }


def main(argv=None):
    force_utf8_stdout()
    ap = argparse.ArgumentParser(description="Academic PPT template capability analyzer")
    ap.add_argument("pptx")
    ap.add_argument("--out", default=None, help="write manifest JSON here")
    args = ap.parse_args(argv)
    try:
        manifest = analyze(args.pptx)
    except AdaptError as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, ensure_ascii=False))
        return 2
    if args.out:
        write_json(args.out, manifest)
    print(json.dumps({"status": "ok", "manifest": manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
