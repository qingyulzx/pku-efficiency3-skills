---
name: paper-to-academic-ppt
description: Turn a research paper (PDF) into a structured, evidence-traceable, template-compliant academic slide deck. Two phases: agent-authored narrative spine and page-level claims (each with paper locators and verbatim quotes), then scripted template adaptation that writes content into real master/layout placeholders, embeds original paper figures, checks overflow/aspect/notes, and exports a PDF preview. Handles missing conclusions, figure-trimming, layout mismatch and over-limit slide counts with explicit rules.
---

# Paper to Academic PPT (evidence-traceable)

## What this skill does

Convert a research paper into an academic presentation where:

- the **narrative spine** (problem / method / results / limitations) is extracted
  from the paper itself, not the paragraph order;
- **every slide carries one claim** backed by a paper locator
  (figure / table / section / quote + page);
- the deck is **assembled inside the provided template** — text goes into
  master/layout placeholders, template fonts and chrome survive;
- **speaker notes** add what to say, not a repetition of slide text;
- the deck is **checked** (overflow, aspect ratio, placeholder usage, evidence
  coverage) and **rendered to PDF** for inspection;
- the result is **machine-verifiable**: result.json maps every slide to its
  paper evidence.

The scripts do parsing, assembly and checking. **You (the agent) do the
judgment**: what the narrative is, which claims deserve pages, what to cut when
the slide budget is tight, which figures prove which claim. Do not delegate
these decisions to the scripts.

## Inputs

| input | where | notes |
|-|-|-|
| `/input/case.json` | fixed path | case_id, paper path, template path, audience, duration, max_slides, output_contract |
| paper PDF | path from case.json | parsed for real; no pre-extracted answer layer |
| template .pptx | path from case.json | may be a template (0 slides) or a starting deck (>0 slides) |

Work under `/app/work`; deliverables go to `/app/output`.

## Pipeline (7 steps)

### Step 0 — Read the case yourself, then write the floor BY HAND (before anything else)

1. Read `/input/case.json` and task.md yourself (cat the file — do not assume
   its shape). Note: `case_id`, paper/template paths, constraints
   (audience/duration/max_slides), and `output_contract` — **which may be a
   dict, a list of `{name, type}` items, or absent**. Read actual files;
   never assume content from labels.
2. **Write `/app/output/result.json` BY HAND right now** (do not run any
   script for this): `case_id` + one field per contract entry (dict → its
   keys; list → each item's `name`; absent → use
   `/skills/weekly-skill/references/deck-plan-schema.md` output defaults),
   every field `null` + `null_reasons: {"<field>": "Step N produces this"}`,
   `status: "partial"`. This skeleton is the floor: it must exist before
   anything else, and every later step only strengthens it.
3. The skill is installed at `/skills/weekly-skill`; invoke its scripts by
   absolute path only, never a bare `scripts/...`.

Only after the hand-written floor exists may you optionally regenerate or
extend it with:

```
python /skills/weekly-skill/scripts/build_result.py --case /input/case.json --out /app/output/result.json --status partial --note "run started"
```

(the hand-written floor already satisfies the contract; the script is a
convenience, not a dependency).

### Step 1 — Extract the paper inventory

```
python /skills/weekly-skill/scripts/extract_paper.py --pdf <paper.pdf> \
    --out /app/work/paper_pages.json \
    --figdir /app/work/figs --extract-images
```

Outputs per-page text, figure/table caption index with page numbers, and
embedded figure images (p{n}_img{i}.png). If it exits with code 3 (no Python
PDF backend), use the container pdf-text-tool / pdf-render-tool instead and
write the same JSON shape yourself — the downstream steps only read that JSON.

### Step 2 — Analyze the template

```
python /skills/weekly-skill/scripts/analyze_template.py --pptx <template.pptx> --out /app/work/template_map.json
```

Produces the layout inventory and a role_map (title / section / content /
two_column / figure). **Read it**: check whether role_map matches your reading
of the template (names can mislead in localized templates); override the deck
plan's `layout` fields per slide if needed. If the template is a starting deck
(slide_count > 0), existing slides are edited via `edit_slide_index` in the
plan.

### Step 3 — Design the narrative spine (agent judgment)

Read the extracted pages (abstract, intro, results tables, conclusion) and
write the four elements of `narrative` in the deck plan:

- **problem** — what the paper attacks, with a verbatim quote;
- **method** — the core idea in one sentence, with figure/section pointers;
- **results** — the headline numbers WITH units and the table they come from;
- **limitations** — prefer the paper's own limitations section; if absent,
  state that explicitly and mark presenter-inferred caveats as such.

Rules for quotes: copy verbatim from `paper_pages.json` (fix only PDF
line-wrapping); keep the page number; never paraphrase inside a `quote` field.

### Step 4 — Write the page-level deck plan (agent judgment)

Author `/app/work/deck_plan.json` following
[references/deck-plan-schema.md](references/deck-plan-schema.md). Key rules:

- one **claim** per slide (a full sentence, not a topic label);
- 3–5 bullets per content slide, each ≤ ~90 chars so first-fit sizing does not
  shrink below 16pt;
- every slide has ≥1 **evidence** entry (locator + page + quote);
- figures: reference the extracted image file and the paper figure label;
  check the image actually shows that figure before embedding;
- **notes** must add information (transitions, emphasis, Q&A backup), never
  repeat bullets;
- slide budget: (mandatory pages) title, problem, method core, method detail,
  headline results, limitations/takeaways — then optional pages
  (training recipe, generalization, ablations) until max_slides is reached.
  If the paper has too many figures, prefer the ones the claims rest on and
  reference the rest textually.

### Step 5 — Assemble the deck

```
python /skills/weekly-skill/scripts/assemble_deck.py --plan /app/work/deck_plan.json \
    --map /app/work/template_map.json --out /app/output/<case_id>.pptx \
    --max-slides <from case.json>
```

Writes text into slide placeholders (never the layout's), keeps template
chrome, inserts pictures into picture placeholders with aspect-preserving
crop, shrinks fonts in 2pt steps (floor 12pt) to fit, and writes notes.
If it errors with the slide-count message, trim the plan — do not use
--allow-overflow unless the case explicitly permits it.

### Step 6 — Check and render

```
python /skills/weekly-skill/scripts/check_deck.py --deck /app/output/<case_id>.pptx \
    --plan /app/work/deck_plan.json --max-slides <N> --out /app/work/check_report.json
```

Fix every `fail` and most `warn` items by editing the **plan** (not the pptx)
and re-running Step 5 — the plan is the single source of truth. Then export
the PDF preview with the container office-renderer (locally:
`soffice --headless --convert-to pdf`) and verify: page count, titles
present, images on the right pages.

### Step 7 — Finalize result.json

```
python /skills/weekly-skill/scripts/build_result.py --case /input/case.json \
    --plan /app/work/deck_plan.json --check /app/work/check_report.json \
    --pptx /app/output/<case_id>.pptx --pdf /app/output/<case_id>_preview.pdf \
    --render-info /app/work/render_info.json --changes /app/work/changes.json \
    --out /app/output/result.json --status complete
```

## Exception handling (real paths)

| situation | detection | action |
|-|-|-|-|
| no Python PDF backend | extract exit 3 | use pdf-text-tool / pdf-render-tool; same JSON shape |
| encrypted/broken PDF | extract warnings/exception | state in result.json uncertainty; proceed with whatever pages parsed |
| paper has no explicit limitations | narrative step | say so on the slide; mark inferred caveats `[presenter's reading]` |
| figure cannot be extracted | figdir empty for that page | render the figure region with pdf-render-tool, or reference it textually + note in uncertainty |
| extracted image is not the cited figure | image↔caption mismatch | do not embed; fall back to textual reference |
| template lacks a needed layout | role_map nulls | use closest layout + warn in result.json |
| slide count exceeds limit | assembler error 4 | trim plan per Step 4 priority order |
| text overflows at 12pt floor | check_deck fail/warn | shorten bullets (agent edits plan) |
| notes would repeat slide text | check_deck warn | rewrite notes to add transitions/Q&A info |
| PDF export unavailable | renderer failure | deliver pptx + explicit null for preview + reason |

## Output contract

`/app/output/result.json` carries: case_id, status, source, constraints,
output_contract (every field from case.json, null + reason if absent),
deliverables (pptx/pdf paths), narrative, slide_evidence_map (per-slide
claims + evidence), quality_checks summary, rendering info, changes, and
uncertainty. See the example in
[examples/example-deck-plan.md](examples/example-deck-plan.md).

## Scope and limits

In scope: narrative extraction, page structuring, evidence mapping, template
adaptation, notes generation, render checking. Out of scope: re-plotting
figures, scientific quality assessment of the paper itself, prose polishing
beyond slide-sized phrasing. The skill assumes an English ML-style paper;
caption regexes cover `Figure N:` / `Fig. N:` / `Table N:` and localized
variants need manual index fixes (record in changes).
