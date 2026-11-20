---
name: graphical-abstract-builder
description: Build a single-page graphical abstract (question, method, results, conclusion) from research material as a traceable, editable SVG with PNG/PDF exports. Use when asked to create or edit a graphical abstract, science summary figure, mechanism or flow diagram, or data chart from a paper, study notes or experimental records, especially when editable source files and element-to-source traceability are required.
---

# Graphical Abstract Builder

Turn research material (PDF, notes, records) into a single-page graphical
abstract whose every element is traceable to the material, plus a
contract-complete `result.json`.

Division of labour — **you do the science, the scripts do the drawing**:

- You (the agent): read the actual material, extract entities/relations/data,
  choose the visual encoding, decide what goes on the canvas vs. the caption,
  verify the figure against the material.
- The scripts (`scripts/`, pure Python + matplotlib): layout, rendering,
  checks, result assembly. Deterministic: same model in → same figure out.

## Environment & paths

- Skill root: `/skills/weekly-skill` (scripts under `scripts/`, schema doc
  under `/skills/weekly-skill/references/`). Work under `/app/work`; final deliverables go to
  `/app/output`.
- Input: `/input/case.json` (+ task.md; material files referenced by the case).
- Python with matplotlib is expected; if missing, PNG export falls back to
  Pillow automatically and PDF export raises with a remedy — see the playbook.
- Typical cost: 10–20 model requests, well inside the 64-request /
  900-second budget. Each build/verify script run is one tool call.

## Workflow

### Step 0 — Read the case and scaffold result.json (do this first)

Read `/input/case.json` fully. Note `case_id` and every field of
`output_contract` — these are your delivery obligations. Then immediately:

```bash
python /skills/weekly-skill/scripts/make_result.py --stage init \
  --case /input/case.json --out /app/output/result.json
```

If that command fails for any reason (wrong CWD, import error, anything), do NOT proceed without the floor: write /app/output/result.json by hand right now — case_id plus every output_contract field as explicit null with a reason, status "partial". The skeleton must exist before any other work. This skill is installed at /skills/weekly-skill; always invoke its scripts by absolute path.


This writes every contract field as an explicit `null` with a pending reason.
From now on a crash still leaves a contract-complete deliverable. Re-run
`--stage final` (Step 6) to fill it.

### Step 1 — Read the actual material

Open the real files the case points to (never assume content from labels).
For PDFs use the pdf-text-tool / scientific-python; scan pages only if OCR
is needed. Save a `sources.json` mapping each material file to its extracted
text — later steps verify quotes against it automatically:

```json
{ "materials/paper.pdf": "<full extracted text>" }
```

### Step 2 — Extract the science (your judgement, not a script's)

Fill in a worksheet (template: `/skills/weekly-skill/templates/agent_worksheet.md`) directly from
the material:

1. **Question** — what problem does the material pose? Quote it verbatim.
2. **Entities** — the things that must appear (molecules, cells, devices,
   methods, cohorts...). For each: label, one verbatim quote, locator
   (file + page/section/sentence).
3. **Relations** — directional connections that the material states
   (A activates B, dosing motivates the question...). Record direction and
   the sentence that states it.
4. **Data** — every number you might draw: value, unit, condition, and the
   sentence it comes from. If a number you want is *not* in the material,
   do not draw it; list it in `uncertainty`/`limits` instead.
5. **Conclusion** — claims the material itself makes.

Rules of evidence: quotes are verbatim substrings of the material; locators
are precise enough for a human to find in seconds; anything you cannot
source goes to the caption/notes, never onto the canvas as data.

### Step 3 — Author figure_model.json

Write `/app/work/figure_model.json` following the schema in
`/skills/weekly-skill/references/model_schema.md` (full worked example: `/skills/weekly-skill/examples/transformer-1706.03762/`).
Key decisions you make:

- **Panel plan**: usually 4–6 panels in reading order
  question → method → results (1–2) → conclusion; one finding per panel.
- **Layout per panel**: `flow` (boxes + arrows for entities/relations),
  `chart` (bar/hbar/grouped_bar/line for data), `stats` (big-number callouts
  for 2–4 headline values), `text` (bulleted conclusions).
- **Visual channels**: length for magnitudes with a common unit and zero
  baseline; position for time series; colour only for categorical series
  (Okabe–Ito palette is built in; never pure red-vs-green); shape/emphasis
  for the focal entity. One channel per meaning, one meaning per channel.
- **Canvas**: default 1800×1000 px (≈ A4 landscape at 150 dpi). Keep every
  font ≥ 12 px (checker enforces).
- Copy quotes/locators from your worksheet into each element's `source`.

### Step 4 — Build and iterate

```bash
python /skills/weekly-skill/scripts/build_figure.py --model /app/work/figure_model.json \
  --outdir /app/work/out --sources /app/work/sources.json
```

Produces `graphical_abstract.svg` (editable source of truth: named ids,
`layer-*` groups, provenance `<desc>` on every element), `.png` (300 dpi),
`.pdf`, `element_map.json`, `export_report.json`. Exit 2 = model invalid
(fix the JSON), 3 = SVG failure (fix per playbook). Rendering failures of
PNG/PDF never abort the run — they land in `export_report.json.failures`.

Iterate: if the report shows errors, edit the model (not the SVG) and
rebuild. The figure is wrong until every error code is cleared.

### Step 5 — Verify like a reviewer

```bash
python /skills/weekly-skill/scripts/check_figure.py --outdir /app/work/out --sources /app/work/sources.json
```

This re-runs all checks: SVG well-formedness, font floor, canvas bounds,
element-map completeness, quote-vs-material (catches invented numbers and
misquotes), grey-scale/contrast, export integrity. Then **look at the PNG
yourself** (read the rendered preview) and check: reading order obvious?
entities/arrow directions match the material? legend matches the encoding?
units on every axis? If a warning cannot be eliminated, record it — do not
hide it.

### Step 6 — Assemble the final result.json

Write `/app/work/values.json` with your contract-field values
(`scientific_summary`, `uncertainty`, path lists, `export_checks`...).
`element_source_map` and `export_checks` are auto-filled from the build.
Then:

```bash
python /skills/weekly-skill/scripts/make_result.py --stage final \
  --case /input/case.json --out /app/output/result.json \
  --values /app/work/values.json \
  --map /app/work/out/element_map.json \
  --export /app/work/out/export_report.json \
  --issues /app/work/out/issues.json \
  --status complete --uncertainty "<one honest sentence>"
```

The matcher fills contract fields by exact key, then containment, then
description keywords; unmatched fields stay explicit `null` with reasons.
If error-level issues remain, status is auto-downgraded to `partial` — never
claim `complete` over failing checks. Copy deliverables to `/app/output`:

`graphical_abstract.svg` + `figure_model.json` (editable sources),
`graphical_abstract.png` (preview) + `graphical_abstract.pdf` (export),
`result.json`.

### Step 7 — Final self-check

- [ ] result.json: `case_id` present; every contract field filled or explicit
      `null` with reason; status honest (auto-downgrade respected).
- [ ] SVG opens (well-formed XML), text is real `<text>` (editable), every
      element has an id, layers named.
- [ ] PNG and PDF exist and are non-empty; PNG ≥ 300 dpi.
- [ ] Every on-canvas number appears in a quote inside `element_map.json`.
- [ ] Legend matches the colour/series encoding exactly.
- [ ] `uncertainty`/`limits` mention every degraded or unsourced item.

## When things go wrong

All failure modes, their signatures and remedies (material missing key
numbers, entity ambiguity, text overflow, font substitution, canvas
overflow, export failures, no matplotlib...) are in
`/skills/weekly-skill/references/exception_playbook.md` — consult it on any red output. The
one rule that overrides everything: **record honestly, never fabricate.**
A `partial` result with documented limits scores better than a pretty
figure with invented evidence.

## References

- `/skills/weekly-skill/references/model_schema.md` — figure_model.json field-by-field with
  defaults and constraints.
- `/skills/weekly-skill/references/exception_playbook.md` — failure signatures → remedies.
- `/skills/weekly-skill/references/design_notes.md` — visual-encoding rules, colour-blind
  safety, layout conventions used by the builder.
- `/skills/weekly-skill/templates/agent_worksheet.md` — Step 2 extraction worksheet.
- `/skills/weekly-skill/templates/figure_model.template.json` — minimal starting model.
- `/skills/weekly-skill/examples/transformer-1706.03762/` — real-paper worked example
  (arXiv:1706.03762, verbatim quotes + sha256).
