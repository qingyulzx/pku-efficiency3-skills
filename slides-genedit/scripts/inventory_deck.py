"""Dump the structure of an existing deck so the agent can locate edit targets.

Usage:
    python inventory_deck.py --deck starting.pptx --out inventory.json

The inventory lists, per slide: layout name, every shape (type, name,
placeholder idx/type, geometry, text with paragraph count), notes text and a
content digest. Read this before writing ops.json — the edit path must touch
only the slides and placeholders the instruction actually requires.
"""

from __future__ import annotations

import argparse
import json
import os

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

import pptx_tools as T


def shape_info(shp):
    d = {
        "name": shp.name,
        "shape_type": str(shp.shape_type).split(" ")[0],
        "is_placeholder": shp.is_placeholder,
        "is_picture": shp._element.tag == qn("p:pic"),
        "left_in": round(shp.left / T.EMU_PER_INCH, 2) if shp.left is not None else None,
        "top_in": round(shp.top / T.EMU_PER_INCH, 2) if shp.top is not None else None,
        "width_in": round(shp.width / T.EMU_PER_INCH, 2) if shp.width is not None else None,
        "height_in": round(shp.height / T.EMU_PER_INCH, 2) if shp.height is not None else None,
    }
    if shp.is_placeholder:
        try:
            d["ph_idx"] = shp.placeholder_format.idx
        except Exception:
            d["ph_idx"] = None
        d["ph_type"] = T.ph_type_name(shp)
    if shp.has_text_frame:
        paras = shp.text_frame.paragraphs
        d["text"] = "\n".join(p.text for p in paras)
        d["n_paragraphs"] = len(paras)
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--deck", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    prs = Presentation(args.deck)
    slides = []
    for i, slide in enumerate(prs.slides):
        notes = ""
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text or ""
        digests = T.slide_digests(slide)
        slides.append(
            {
                "index": i + 1,
                "layout": slide.slide_layout.name,
                "shapes": [shape_info(shp) for shp in slide.shapes],
                "notes": notes,
                "notes_present": bool(notes.strip()),
                "digest": digests["raw"],
                "digest_structural": digests["structural"],
            }
        )

    inv = {
        "deck": os.path.abspath(args.deck),
        "slide_count": len(slides),
        "slide_size": {
            "width_in": round(prs.slide_width / T.EMU_PER_INCH, 2),
            "height_in": round(prs.slide_height / T.EMU_PER_INCH, 2),
        },
        "layouts_available": [T.layout_info(l) for l in prs.slide_layouts],
        "fonts_declared": T.declared_fonts(prs),
        "slides": slides,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(inv, f, ensure_ascii=False, indent=2)
    print(
        "inventory: %d slides, %d layouts -> %s"
        % (len(slides), len(prs.slide_layouts), args.out)
    )


if __name__ == "__main__":
    main()
