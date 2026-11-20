# Data contracts used by the scripts

All JSON is UTF-8. These schemas are the contract between the agent (who
authors judgment files) and the scripts (which parse, assemble, verify).

## outline.json — generation path (authored by the agent)

```json
{
  "meta": {
    "title": "deck title",
    "audience": "e.g. 课题组同行 / 中期评审专家",
    "duration_min": 10,
    "target_slides": 6,
    "language": "zh"
  },
  "slides": [
    {
      "role": "title|problem|method|result|limitation|outline|backup",
      "layout_hint": "title|title_content|two_content|image_content|title_only|blank",
      "title": "page claim (one sentence, the page's message)",
      "subtitle": "optional, title slide only",
      "bullets": [{"text": "short point", "level": 0}],
      "image": {
        "path": "absolute or outline-relative path",
        "caption": "图 1：...（与原文图注一致或明确标注转述）",
        "source_loc": "paper Figure 2 / 材料图 1"
      },
      "notes": "speaker script for this slide",
      "evidence": [{"loc": "paper Sec.3.2 / Table 1", "quote": "verbatim text"}]
    }
  ],
  "decisions": [
    {"action": "kept|cut|merged|reordered|split",
     "item": "what content",
     "reason": "why — audience/time/page-budget driven"}
  ]
}
```

Rules the agent must follow when authoring:
- Numbers on slides are copied verbatim from the material (no rounding,
  no "约"). Each number's source goes into `evidence`.
- Every slide carries `notes` (the talk script) — a deck without notes is
  incomplete under this skill.
- `decisions` records every kept/cut/merged/reordered item with a reason.
  Empty decisions are a bug, not a courtesy.

## ops.json — edit path (authored by the agent)

```json
{
  "ops": [
    {"op": "replace_text", "slide": 3, "target": "body",
     "bullets": [{"text": "...", "level": 0}]},
    {"op": "append_bullets", "slide": 5, "target": "body",
     "bullets": [{"text": "...", "level": 0}]},
    {"op": "set_notes", "slide": 3, "notes": "..."},
    {"op": "insert_image", "slide": 4, "image": "path.png",
     "rect_in": [0.6, 1.5, 5.0, 4.0], "caption": "图 2：...",
     "target": "idx:1"},
    {"op": "delete_slide", "slide": 7},
    {"op": "move_slide", "from": 4, "to": 6},
    {"op": "duplicate_slide", "slide": 2},
    {"op": "add_slide", "after": 6, "layout_hint": "title_content",
     "title": "...", "bullets": [{"text": "...", "level": 0}],
     "notes": "..."}
  ]
}
```

- `slide` / `from` / `to` are 1-based indices into the deck state at the
  moment the op runs (ops apply in order).
- `target` selects a shape on the slide: `title`, `body`, `idx:<placeholder
  idx>` (from inventory.json), or `name:<shape name>`.
- Author ops ONLY for the parts the instruction asks to change. A full-deck
  rewrite via ops is a misuse — use the generation path instead.

## case-parsed.json — written by parse_case.py

Route hint, constraint scan results, file inventory, output-contract field
list. See `parse_case.py --help`.

## assembly-report.json — written by assemble_deck.py

Per-slide layout choice, placeholder provenance (slide/cloned), image
geometry, text-fit estimate, warnings, and the slide-budget check.

## edit-report.json — written by edit_deck.py

Ops log plus the preservation matrix:
- `slides_identical_raw` — edited-deck slides byte-identical to some source
  slide (raw part sha256).
- `slides_identical_structural` — same after c14n + relationship-id
  normalization (catches serializer renumbering).
- `masters_untouched` / `layouts_untouched` — digest equality.

A healthy local edit shows `slides_identical_raw >= (source slides − touched
slides)`. If untouched slides are not even structurally identical, the edit
leaked outside its scope — investigate before delivering.

## render-report.json — written by render_check.py

Render status, soffice path used, PDF path, page count vs slide count,
declared fonts, issues. Honest failure record when rendering is impossible.
