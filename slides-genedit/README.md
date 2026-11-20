# slides-genedit — README

An Agent Skill for **academic slide generation and source-preserving
editing**: turn research material into an editable, evidence-traced
presentation under fixed audience/time/slide-count constraints, and edit an
existing deck without breaking the parts you were not asked to touch.

- Two routes: **generate** (material + constraints + template → new deck)
  and **edit** (starting deck + instruction → surgical, preservation-verified
  changes). SKILL.md dispatches on evidence (starting deck present? edit
  intent in the instruction?).
- The agent makes the judgment calls (page claims, order, cuts, edit scope);
  the scripts do deterministic parsing/assembly/verification/rendering.
- Every deck ships with: per-slide evidence mapping (verbatim quotes +
  locations), speaker notes, a rendered PDF preview, and a decisions log.

## Repository layout

```
SKILL.md                      skill entry: route dispatch + 7-step workflow
README.md                     this file
scripts/
  pptx_tools.py               shared library (placeholders, images, digests)
  parse_case.py               step 1: parse case.json, constraints, route hint,
                              writes the skeleton result.json (deliverable floor)
  assemble_deck.py            generate: outline.json -> .pptx + assembly report
  inventory_deck.py           edit: dump deck structure for target location
  edit_deck.py                edit: apply ops.json -> .pptx + preservation matrix
  render_check.py             render via LibreOffice; page-count and font checks
reference/
  schemas.md                  outline.json / ops.json / report contracts
  exception-playbook.md       10 real failure modes with honest dispositions
examples/
  generate/example-outline.json   EXAMPLE outline derived from arXiv:1706.03762v7
  edit/example-ops.json           EXAMPLE ops derived from the same paper
```

## Requirements

- Python 3.9+ with `python-pptx` (>= 0.6.21; developed on 1.0.2), `Pillow`
  (image aspect-cropping), `lxml` (c14n digests; comes with python-pptx).
- LibreOffice (`soffice`) on PATH or pointed to by `$SOFFICE` for PDF
  rendering. Without it the skill still produces the .pptx and records the
  render failure honestly (see exception-playbook.md #6).

No installation step: the scripts are plain stdlib + the packages above,
invoked as `python scripts/<name>.py --help` for full usage.

## Quick start (generation)

1. Prepare `case.json` describing the task, pointing at your material file
   (md/pdf/tex), optional template.pptx and figure images, and an
   `output_contract` listing the result fields you require.
2. `python scripts/parse_case.py --input case.json --workdir work --output-dir out`
   → route hint, constraint scan, skeleton `out/result.json`.
3. Read the material and author `work/outline.json` (schema in
   `reference/schemas.md`): one claim per page, verbatim numbers with
   evidence loc+quote, notes per slide, decisions log for every
   kept/cut/merged/reordered item.
4. `python scripts/assemble_deck.py --outline work/outline.json --template template.pptx --out out/deck_v1.pptx --workdir work/scratch`
   → review `out/assembly-report.json` (overflow warnings, layout fallbacks,
   budget check); fix the outline and re-run if needed.
5. `python scripts/render_check.py --pptx out/deck_v1.pptx --outdir out/render/`
   → PDF preview with page-count check.
6. Fill `out/result.json` with final values for every output_contract field.

## Quick start (editing)

1. `python scripts/parse_case.py` as above (route hint should say edit).
2. `python scripts/inventory_deck.py --deck starting.pptx --out work/inventory.json`
   → locate exact slide indices and placeholder idx/name targets.
3. Author `work/ops.json` covering ONLY the requested changes (schema in
   `reference/schemas.md`).
4. `python scripts/edit_deck.py --deck starting.pptx --ops work/ops.json --out out/deck_v2.pptx --workdir work/scratch`
   → check `out/edit-report.json`: all ops ok; untouched slides
   byte-identical (`slides_identical_raw`); masters/layouts untouched.
5. Render as above, then finalize result.json (add ops log + preservation
   matrix).

## Example

`examples/generate/example-outline.json` shows a complete outline (with
evidence quotes and decisions) derived from the abstract of *Attention Is All
You Need* (arXiv:1706.03762v7); `examples/edit/example-ops.json` shows the
matching ops file. **These are schema demonstrations marked as examples —
not official case outputs.** Source provenance (arXiv id, DOI, fetch date,
verbatim-quote location, sha256 of the quoted abstract) is recorded in each
file's `_source` block.

## Key design decisions

- **Slide-level placeholders only.** Content written into layout-level
  placeholders does not render (the file saves fine — the bug only appears on
  re-open). `pptx_tools.ensure_placeholder()` clones layout placeholders down
  to the slide when missing.
- **Two-level preservation digests.** Raw part sha256 proves byte-identity;
  a c14n structural digest with normalized relationship ids proves semantic
  identity when serializers renumber rels. The edit route requires untouched
  slides to pass at least the structural level, normally the raw level.
- **Aspect-crop, never stretch.** Images are center-cropped (PIL) to the
  target placeholder's aspect before insertion.
- **Report-only overflow heuristics.** The assembly report flags overflow
  risk; the agent trims the outline. The skill never silently shrinks fonts.
- **Numbers verbatim, evidence attached.** The outline schema couples every
  slide to `evidence` (loc + verbatim quote); the result.json evidence map is
  generated from it.

## Known limitations

- Overflow detection is a heuristic (font-size × average glyph width); it
  flags risk, it does not replace inspecting the rendered PDF.
- PDF page counting uses a regex scan of `/Type /Page` objects; PDFs using
  object streams report `null` count with the method stated.
- `duplicate_slide` re-creates shapes and relationships; the duplicate is
  content-identical but not byte-identical to its source slide (expected).
- LibreOffice rendering may substitute fonts absent from the system; the
  skill records this as uncertainty rather than altering template fonts.
- Charts are inserted as images (cited originals or agent-prepared
  matplotlib output); native editable PowerPoint charts are not generated.

## Self-check before delivering

1. Deck opens in PowerPoint/LibreOffice; slide count within budget.
2. Every slide has a title in a slide-level placeholder and speaker notes.
3. Spot-check three numbers on slides against their evidence quotes.
4. PDF preview exists; page count == slide count.
5. result.json covers every output_contract field (or `null` + reason).
6. Edit runs: preservation matrix green (untouched slides identical,
   masters/layouts untouched).
