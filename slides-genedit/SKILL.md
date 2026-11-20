---
name: slides-genedit
description: Generate and edit academic presentation decks from research material. Two routes: (1) generate a new deck from a paper/notes under fixed audience, duration and slide-count constraints, with per-slide claims, verbatim-number evidence mapping, speaker notes, and a rendered PDF preview; (2) source-preserving edits of an existing starting deck - inventory it, apply only the requested local changes, and prove untouched slides stayed byte-identical. Use when asked to turn research material into slides, or to modify/compress/re-audience an existing deck without breaking it.
---

# slides-genedit — academic PPT generation & source-preserving editing

You turn research material (paper, notes, starting deck) into an editable,
evidence-traced academic presentation — and you edit existing decks without
breaking what you were not asked to touch. The hard part is **selection and
ordering**, not copying paragraphs: which result deserves its own page, how
many bullets a method needs, which figure comes first, what gets cut when the
page budget is exceeded. You make those judgment calls; the scripts in
`scripts/` do the deterministic work (parsing, assembly, verification,
rendering). Never hand-assemble XML when a script exists.

## Route dispatch (decide first, then never mix)

Read `/input/case.json` and task.md. Run step 1 below — `parse_case.py`
prints a route hint with its evidence. Confirm against the task wording:

- **GENERATE** — no starting deck in the inputs (research material +
  audience/time/slide-count constraints + template). Build a new deck.
- **EDIT** — a starting deck (.pptx) is provided AND the instruction asks
  for local changes (修改/压缩/换受众/加页/删页/调整). Inventory it and
  apply surgical ops. Editing must preserve: untouched slides byte-identical,
  masters/layouts untouched, template style, notes of untargeted slides.
- If a deck exists but the instruction rewrites most content or reorders the
  whole narrative, that is a **generate** run in disguise — build fresh from
  the same template and keep the starting deck as version N-1. Record the
  route decision and its evidence.

Budget discipline throughout: ~7 tool steps is the sweet spot, 64 model
requests / 900 s total. Step 1 already writes a contract-complete skeleton
result.json, so a crash anywhere after that still leaves a verifiable
deliverable. Improve it incrementally; never leave it as the skeleton.

## Step 1 — parse inputs, write the result.json floor (both routes)

```
python /skills/weekly-skill/scripts/parse_case.py --input /input/case.json --workdir /app/work --output-dir /app/output
```

If that command fails for any reason (wrong CWD, import error, anything),
write the floor by hand right now: `/app/output/result.json` with `case_id`
and every `output_contract` field as explicit `null` + reason, status
"partial". The skeleton must exist before any extraction work. The skill is
installed at `/skills/weekly-skill`; always invoke its scripts by absolute
path (or `cd /skills/weekly-skill` first), never a bare `scripts/...`.

Read the printed route hint AND the actual task text before committing to a
route (the hint is evidence, not a verdict). Verify the constraint scan
(`case-parsed.json`) against task.md yourself — keyword scans miss and
over-match; the task wording wins. Read every input file that exists
(`material*.md/pdf/tex`, figures); for PDFs use pdf-text-tool /
pdf-render-tool / ocr-tool as provided. Never assume content from filenames.

## Step 2 — extraction with verbatim capture (generate)

From the actual material, extract: research question, method, results,
limitations (the narrative spine). While reading, capture **verbatim quotes
with locations** (section, table, figure) for every number and claim that
might appear on a slide — this is the evidence map, collected once, reused in
steps 3 and 7. If the material lacks conclusions/results, apply
`reference/exception-playbook.md` #1: mark inferences, never invent.

## Step 3 — page-level outline: your judgment, recorded (generate)

Author `/app/work/outline.json` per `reference/schemas.md`. This is the core
intellectual step — do it yourself, not by template:

- **One page = one claim.** The title states the page's message ("结果：同压
  缩率下形状误差低 38.2%"， not "实验结果"). Every slide gets a `role`
  (problem/method/result/limitation/...) and speaker `notes` (the talk
  script — a deck without notes is incomplete).
- **Numbers verbatim.** Copy digits from the material exactly (28.4 BLEU,
  not ~28; 41.8, not 42). Each number's source goes in that slide's
  `evidence`. If you cannot find a number's source, it does not go on a
  slide.
- **Selection for the audience/time budget.** ~1 slide per 1–2 minutes.
  Group peers: method detail matters. Review committee: progress and plan
  matter. Defense: contributions and evidence matter. Order results by
  narrative force (is it good? → how much? → does it hold?), not by paper
  section order.
- **Figures**: cite the original image with its verbatim caption when the
  source is a bitmap; only redraw when the data table exists. Image-only
  results deserve their own page; secondary figures merge or go to backup
  pages after the closing slide.
- **`decisions` log**: every kept/cut/merged/reordered item with a reason
  ("cut 表 2 消融 — 页数预算 6 页，主结果优先"). This is both your
  verifiability artifact and the case-study material; empty decisions are a
  bug.

## Step 4 — assemble the deck (generate)

```
python /skills/weekly-skill/scripts/assemble_deck.py --outline /app/work/outline.json \
  --template <template.pptx if provided> --out /app/output/deck_v1.pptx \
  --workdir /app/work/scratch
```

Read `assembly-report.json`. Fix the outline (not the deck) when it reports
overflow risk, layout fallbacks, or budget excess, then re-run — the deck and
the decisions log must stay consistent. The scripts guarantee: content lands
in slide-level placeholders (cloned from the layout when missing — writing
into layout placeholders does not render), images are aspect-cropped not
distorted, notes are attached.

## Step 2' — inventory the starting deck (edit)

```
python /skills/weekly-skill/scripts/inventory_deck.py --deck <starting.pptx> --out /app/work/inventory.json
```

Read the inventory. Locate the exact targets the instruction names (slide
index + placeholder idx / shape name). If an edit target does not exist,
apply playbook #8: fail loudly, retarget, or add — never silently skip.

## Step 3' — author surgical ops (edit)

Write `/app/work/ops.json` per `reference/schemas.md` (ops schema). Ops apply
in order to 1-based slide indices. Cover ONLY what the instruction asks:
`replace_text` for rewritten bullets (existing formatting is preserved),
`append_bullets`, `set_notes`, `insert_image` (aspect-cropped), `add_slide`,
`delete_slide`, `move_slide`, `duplicate_slide`. A full-deck rewrite through
ops is misuse — switch routes instead.

## Step 4' — apply edits and verify preservation (edit)

```
python /skills/weekly-skill/scripts/edit_deck.py --deck <starting.pptx> --ops /app/work/ops.json \
  --out /app/output/deck_v2.pptx --workdir /app/work/scratch
```

Check `edit-report.json`: all ops `ok`; `slides_identical_raw >= source
slides − touched slides`; `masters_untouched` and `layouts_untouched` true.
If untouched slides are not even structurally identical, the edit leaked —
playbook #9. Re-render, then deliver.

## Step 5 — render and check (both routes)

```
python /skills/weekly-skill/scripts/render_check.py --pptx /app/output/deck_v1.pptx --outdir /app/output/render/
```

The PDF preview must exist with page count == slide count. Inspect the
preview for overflow, font substitution, clipped images (use pdf-render-tool
/ office-renderer as available). Font substitution in the preview is recorded
as uncertainty — do NOT rewrite the deck's template fonts to please the
renderer (playbook #4). If rendering is impossible, keep the .pptx and
record the failure honestly (playbook #6).

## Step 6 — iterate deliberately (both routes)

User feedback arrives as a new edit instruction on the current deck: loop
back to step 2' (edit route) against the latest version. Keep prior versions
(`deck_v1.pptx`, `deck_v2.pptx`, ...) — never overwrite; each render-report
plus ops log/decisions diff is the version record. Regression check each
round: did untouched slides stay identical?

## Step 7 — finalize result.json (both routes)

Update `/app/output/result.json` (the skeleton from step 1) to final values:
every `output_contract` field from case.json filled — presentation file,
slide count, per-slide evidence mapping (loc + verbatim quote), render
preview path, speaker notes status; edit runs add the ops log and
preservation matrix. Fields you genuinely could not produce stay `null` with
the reason in `unanswered`. `status` ∈ complete | partial (name the limits).
Then stop — deliver the .pptx, notes, PDF preview, and result.json.

## Non-negotiables

- Numbers/quotes on slides trace to verbatim captured sources; no invented
  figures, no eyeballed redraws, no silent rounding.
- Edit route never touches masters/layouts or untargeted slides; the
  preservation matrix proves it.
- Honest failure over faked success in result.json, always.
- Templates, dependencies, schemas, and the exception playbook live in
  `README.md` and `reference/`; read them before deviating.
