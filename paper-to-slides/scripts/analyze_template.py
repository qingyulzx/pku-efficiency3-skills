#!/usr/bin/env python3
"""analyze_template.py -- inventory the masters/layouts/placeholders of a .pptx
template (or a starting deck), and emit a layout-choice map the assembler uses.

Output JSON:
{
  "pptx_path": ..., "sha256": ..., "slide_count": N,
  "slide_size": {"width_emu": ..., "height_emu": ..., "width_in": ..., "height_in": ...},
  "layouts": [
    {"name": "Title Slide", "layout_index": 0, "placeholders":
       [{"idx": 0, "type": "ctrTitle", "name": "Title 1",
         "left":..., "top":..., "width":..., "height":...,
         "font_size_pt": 40.0, "is_body": false}],
     "role_guess": "title"}
  ],
  "role_map": {"title": "Title Slide", "section": ..., "content": ...,
               "two_column": ..., "figure": ..., "table": ..., "conclusion": ...},
  "warnings": [...]
}

role_guess logic (see references/template-adaptation.md):
  - layout whose placeholders contain a ctrTitle (or a single title + subtitle) -> title
  - title + exactly one body placeholder                       -> content
  - title + >=2 body placeholders (or body with two columns)   -> two_column
  - layout with a picture placeholder                          -> figure
  - title only (no body)                                       -> section
The agent may override role_map after inspecting this report.

Usage:
  python analyze_template.py --pptx template.pptx --out template_map.json
"""
import argparse
import hashlib
import json
import os
import sys

from pptx import Presentation
from pptx.util import Emu

BODY_TYPES = {"BODY", "OBJECT"}                  # OBJECT = content placeholder
TITLE_TYPES = {"TITLE", "CENTER_TITLE"}
PIC_TYPES = {"PICTURE", "PICTURE_PLACEHOLDER"}
# placeholders that are chrome, never content targets
CHROME_TYPES = {"DATE", "FOOTER", "SLIDE_NUMBER"}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ph_type_name(ph):
    try:
        return str(ph.placeholder_format.type).split(".")[-1].split(" ")[0]
    except Exception:
        return "UNKNOWN"


def placeholder_record(ph):
    rec = {
        "idx": ph.placeholder_format.idx,
        "type": ph.placeholder_format.type,
        "type_name": ph_type_name(ph),
        "name": ph.name,
        "left": ph.left, "top": ph.top, "width": ph.width, "height": ph.height,
        "font_size_pt": None,
        "is_body": False,
        "is_title": False,
        "is_picture": False,
    }
    try:
        rec["type"] = int(rec["type"])
    except Exception:
        pass
    tn = rec["type_name"].upper()
    if tn in BODY_TYPES or tn.startswith("BODY"):
        rec["is_body"] = True
    if tn in TITLE_TYPES or tn.startswith("TITLE"):
        rec["is_title"] = True
    if tn in PIC_TYPES or tn.startswith("PICTURE"):
        rec["is_picture"] = True
    # first-run font size, if any (template designers set it on the prompt text)
    try:
        if ph.has_text_frame:
            for para in ph.text_frame.paragraphs:
                for run in para.runs:
                    if run.font.size is not None:
                        rec["font_size_pt"] = run.font.size.pt
                        break
                if rec["font_size_pt"]:
                    break
    except Exception:
        pass
    return rec


def guess_role(phs):
    phs = [p for p in phs if p["type_name"].upper() not in CHROME_TYPES]
    titles = [p for p in phs if p["is_title"]]
    bodies = [p for p in phs if p["is_body"]]
    pics = [p for p in phs if p["is_picture"]]
    if pics:
        return "figure"
    if not titles:
        return "content"
    if any(t["type_name"].upper() == "CENTER_TITLE" for t in titles):
        return "title"
    if not bodies:
        return "section"
    if len(bodies) >= 2:
        return "two_column"
    return "content"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pptx", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    if not os.path.isfile(args.pptx):
        print(json.dumps({"error": f"pptx not found: {args.pptx}"}))
        sys.exit(2)

    warnings = []
    try:
        prs = Presentation(args.pptx)
    except Exception as e:
        print(json.dumps({"error": f"cannot open pptx: {e}"}))
        sys.exit(2)

    layouts_out = []
    role_seen = {}
    for master in prs.slide_masters:
        for li, layout in enumerate(master.slide_layouts):
            phs = [placeholder_record(ph) for ph in layout.placeholders]
            role = guess_role(phs)
            # keep the FIRST layout per role, but record all candidates
            layouts_out.append({
                "name": layout.name,
                "master": master.name,
                "layout_index": li,
                "placeholders": phs,
                "role_guess": role,
            })
            role_seen.setdefault(role, layout.name)

    # role_map: prefer layout names that literally mention the role (works for
    # shipped templates), then fall back to the structural guess.
    name_keys = {
        "title": ("title slide",),
        "section": ("section",),
        "two_column": ("two content", "comparison", "two column"),
        "figure": ("picture", "image", "figure"),
        "content": ("title and content", "content"),
    }
    for role in ("title", "section", "content", "two_column", "figure",
                 "table", "conclusion"):
        if role in ("table", "conclusion"):
            continue
        # 1) name-keyword match across ALL layouts (a "Section Header" layout
        #    structurally looks like title+body, only its name identifies it)
        named = [l for l in layouts_out
                 if any(k in l["name"].lower() for k in name_keys[role])]
        if named:
            role_seen[role] = named[0]["name"]
            continue
        # 2) structural guess fallback
        cands = [l for l in layouts_out if l["role_guess"] == role]
        if cands:
            role_seen[role] = cands[0]["name"]

    role_map = {r: role_seen.get(r) for r in
                ("title", "section", "content", "two_column", "figure",
                 "table", "conclusion")}
    if role_map["conclusion"] is None:
        role_map["conclusion"] = role_map["content"]
    if role_map["table"] is None:
        role_map["table"] = role_map["two_column"] or role_map["content"]
    if role_map["figure"] is None:
        role_map["figure"] = role_map["content"]
    missing = [r for r, v in role_map.items() if v is None]
    if missing:
        warnings.append(f"no layout found for roles: {missing}")

    result = {
        "pptx_path": os.path.abspath(args.pptx),
        "sha256": sha256_file(args.pptx),
        "slide_count": len(prs.slides),
        "slide_size": {
            "width_emu": prs.slide_width, "height_emu": prs.slide_height,
            "width_in": round(Emu(prs.slide_width).inches, 2),
            "height_in": round(Emu(prs.slide_height).inches, 2),
        },
        "layouts": layouts_out,
        "role_map": role_map,
        "warnings": warnings,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print(json.dumps({
        "ok": True, "layouts": len(layouts_out), "role_map": role_map,
        "slide_count": result["slide_count"], "warnings": warnings,
        "out": os.path.abspath(args.out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
