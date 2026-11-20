# paper-to-academic-ppt — skill package

A DeepSeek Harness skill that turns a research paper PDF into a structured,
evidence-traceable, template-compliant academic slide deck.

- What it does, how to call it, inputs/outputs, 7-step pipeline and exception
  handling: see [SKILL.md](SKILL.md).
- Deck plan schema (the agent-authored source of truth): see
  [references/deck-plan-schema.md](references/deck-plan-schema.md).
- Template adaptation rules (placeholder writes, picture placement, sizing,
  starting-deck editing): see
  [references/template-adaptation.md](references/template-adaptation.md).
- Minimal invocation example derived from a real public paper:
  [examples/example-deck-plan.md](examples/example-deck-plan.md).

## Quick start

```
python scripts/build_result.py --case /input/case.json --out /app/output/result.json --status partial
python scripts/extract_paper.py --pdf <paper> --out paper_pages.json --figdir figs --extract-images
python scripts/analyze_template.py --pptx <template> --out template_map.json
#   ... agent authors deck_plan.json per references/deck-plan-schema.md ...
python scripts/assemble_deck.py --plan deck_plan.json --map template_map.json --out /app/output/deck.pptx --max-slides <N>
python scripts/check_deck.py --deck /app/output/deck.pptx --plan deck_plan.json --max-slides <N> --out check_report.json
python scripts/build_result.py --case /input/case.json --plan deck_plan.json --check check_report.json --pptx /app/output/deck.pptx --pdf /app/output/deck_preview.pdf --render-info render_info.json --changes changes.json --out /app/output/result.json --status complete
```

## Requirements

- Python 3.10+ with `python-pptx` and `Pillow` (both preinstalled in the
  grading container's scientific-python).
- A PDF text backend: `pypdf`, `pymupdf` or `pdfplumber` (any one). If none
  is present the extractor exits with code 3 and instructs using the
  container's pdf-text-tool / pdf-render-tool with the same JSON shape.
- PDF export: container office-renderer; locally any LibreOffice works.

## Scope and limits

Best fit: English ML/NLP-style papers with numbered figures/tables. Caption
regexes cover `Figure N:` / `Fig. N:` / `Table N:`; other formats need manual
index fixes (record them in changes). Not in scope: re-plotting figures,
assessing the science itself, prose polishing.

## Maintenance

Version 1. Scripts are single-purpose CLI tools with JSON contracts between
steps, so any step can be rerun or replaced independently. Bugs found in
real runs and their fixes are recorded in the repository progress notes.
