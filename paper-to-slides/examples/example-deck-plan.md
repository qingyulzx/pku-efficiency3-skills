# Minimal invocation example

**This is an example, not an official case result.** It is derived from the
real public paper *Attention Is All You Need* (Vaswani et al., NIPS 2017,
arXiv:1706.03762v7, sha256
`bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697`, 15
pages) and a template generated for local testing. Abridged to show shape.

## Input (abridged /input/case.json)

```json
{
  "case_id": "example-attention",
  "paper_path": "attention.pdf",
  "template_path": "template.pptx",
  "audience": "graduate ML seminar, familiar with seq2seq basics",
  "duration_minutes": 15,
  "max_slides": 10,
  "output_contract": {
    "editable_pptx": "path to the .pptx deliverable",
    "speaker_notes": "per-slide notes inside the pptx",
    "slide_evidence_map": "per-slide mapping to paper locators",
    "rendered_preview": "PDF export of the deck"
  }
}
```

## Commands (in order)

```
python scripts/build_result.py --case case.json --out output/result.json --status partial
python scripts/extract_paper.py --pdf attention.pdf --out work/paper_pages.json --figdir work/figs --extract-images
python scripts/analyze_template.py --pptx template.pptx --out work/template_map.json
# agent authors work/deck_plan.json (Steps 3-4 of SKILL.md)
python scripts/assemble_deck.py --plan work/deck_plan.json --map work/template_map.json --out output/deck.pptx --max-slides 10
python scripts/check_deck.py --deck output/deck.pptx --plan work/deck_plan.json --max-slides 10 --out work/check_report.json
# export PDF with office-renderer (locally: soffice --headless --convert-to pdf)
python scripts/build_result.py --case case.json --plan work/deck_plan.json --check work/check_report.json --pptx output/deck.pptx --pdf output/deck_preview.pdf --render-info work/render_info.json --changes work/changes.json --out output/result.json --status complete
```

## Excerpt of extract output

```json
{"ok": true, "engine": "pypdf", "num_pages": 15, "figures": 5, "tables": 4,
 "image_files": 3, "warnings": [], "out": "work/paper_pages.json"}
```

Figure index (abridged): Figure 1 → page 3, Figure 2 → page 4, Table 2 →
page 8, Table 4 → page 10.

## Excerpt of one planned slide (deck_plan.json)

```json
{
  "index": 7, "role": "content",
  "claim": "Headline results: 28.4 BLEU EN-DE (>2 BLEU over previous best including ensembles) and 41.8 BLEU EN-FR single-model SOTA, at a fraction of training FLOPs.",
  "title": "Results: new SOTA at a fraction of the cost (Table 2)",
  "bullets": [
    {"text": "WMT14 EN-DE: 28.4 BLEU - beats all prior models AND ensembles by >2 BLEU", "level": 0},
    {"text": "WMT14 EN-FR: 41.8 BLEU - new single-model SOTA (3.5 days, 8 GPUs)", "level": 0}
  ],
  "notes": "Slow down here - this is the payoff slide. Read the two BLEU numbers verbatim...",
  "evidence": [
    {"type": "table", "locator": "Table 2", "page": 8,
     "quote": "The Transformer achieves better BLEU scores than previous state-of-the-art models on the English-to-German and English-to-French newstest2014 tests at a fraction of the training cost.",
     "note": "headline table; numbers above read from Table 2 rows"}
  ]
}
```

The verbatim quote above is from the paper's Table 2 caption, page 8 of
arXiv:1706.03762v7.

## Excerpt of check + result output

```json
{"ok": true, "summary": {"slide_count": "pass", "placeholders": "pass",
  "overflow": "pass", "images": "pass", "notes": "pass", "evidence": "pass"}}
```

```json
{"ok": true, "out": "output/result.json", "contract_fields": 7,
 "null_fields": 0, "slides": 9}
```

The real end-to-end run of this example (9 slides, Figure 1 embedded on the
architecture slide from the extracted page-3 image, PDF preview with all
titles verified) is documented in the repository's progress notes.
