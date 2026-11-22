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
python /skills/weekly-skill/scripts/parse_sources.py --input paper.pdf --out /app/work/materials_index.json
#   ... agent authors outline.json per references/output-schema.md §2 ...
python /skills/weekly-skill/scripts/build_deck.py --outline /app/work/outline.json \
    --template template.pptx --out /app/output/deck.pptx --report /app/work/assembly_report.json
python /skills/weekly-skill/scripts/render_preview.py --pptx /app/output/deck.pptx --outdir /app/output/render
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
