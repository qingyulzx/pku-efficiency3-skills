---
name: relationship-schematic
description: Generate or edit scientific entity-relationship schematics (mechanism diagrams, pathway chains, experimental workflows, structural containment) as traceable, editable SVG with verified relation semantics. Extracts an evidence-quoted entity/relation table first, renders a layered SVG from it, reads the drawing back to verify every relation type, direction and containment, then exports 300-dpi PNG and vector PDF. Use for any "draw a mechanism/workflow/relationship figure from this paper or case material" task where scientific correctness of entities, arrow directions and hierarchy matters.
---

# Relationship schematics: extract → model → render → verify → export

You are drawing figures whose scientific correctness is judged by an LLM
reviewer against the source material. The dominant failure modes of generic
image generation are exactly the things this skill refuses to do: inhibition
drawn as activation, upstream/downstream reversed, containment drawn as
side-by-side boxes, invented gene names or numbers, untraceable claims. Every
mechanism here exists to make those failures impossible to ship silently.

## Non-negotiables

1. **Nothing is drawn that is not in the relation table.** The figure model
   (`model.json`) is the single source of truth; the SVG is generated from it
   and read back against it.
2. **Every entity and relation carries a verbatim quote + locator** from the
   source material. A relation without a quote is refused by the tooling
   (`relation_no_evidence`). If you cannot quote it, you may not draw it.
3. **`from`/`to` encode the statement, not the layout.** "A inhibits B" ⇒
   `from: A, to: B, type: inhibits`. The renderer decides geometry; the
   verifier checks the arrow tip really lands on B.
4. **Unknown is drawn as unknown.** If the material does not state a
   direction, use `direction: "unknown"` — it renders dashed with a `?` and is
   flagged in result.json. Never guess to make the figure look cleaner.
5. **Deliver the保底 result.json first, improve later.** Step 1 writes a
   contract-shaped scaffold with explicit nulls before any extraction, so a
   crash still leaves a valid partial deliverable.

Scripts live in `scripts/` (pure Python 3 stdlib + optional cairosvg/PIL;
auto-detect browser headless for export). Symbol semantics live in
`/skills/weekly-skill/symbols/symbols.json` and are documented in
`/skills/weekly-skill/references/symbol-conventions.md`; the model format in
`/skills/weekly-skill/references/model-schema.md`. Read both references before your first run.

## Workflow (7 steps)

Work under `/app/work`; final artifacts go to `/app/output`.

### Step 1 — Scaffold the floor deliverable

```
python /skills/weekly-skill/scripts/init_result.py --case /input/case.json --work /app/work --output /app/output
```

If that command fails for any reason (wrong CWD, import error, anything), do NOT proceed without the floor: write /app/output/result.json by hand right now — case_id plus every output_contract field as explicit null with a reason, status "partial". The skeleton must exist before any other work. This skill is installed at /skills/weekly-skill; always invoke its scripts by absolute path.


Reads the case, creates dirs, writes `/app/output/result.json` with every
`output_contract` field present and `null`, `status: "partial"`, and a
partial_reasons entry. If the case file is missing/unreadable it still writes
the scaffold and records the problem. Also read `task.md` and any material
files yourself — never assume content from labels or filenames.

### Step 2 — Extract the entity–relation table (your judgment, not a script's)

Read the actual material (PDF text via the platform tools, tables, case text)
and build `/app/work/model.json` per `/skills/weekly-skill/references/model-schema.md`:

- one entity per scientific actor; `label` = canonical name as printed in the
  source; `type` = functional role shown as a small subtitle;
- one relation per stated interaction, with `type` from the symbol library
  (`activates inhibits binds modifies transports indirect precedes contains
  parallels`) and `direction` (`A_to_B` / `B_to_A` / `bidirectional` /
  `unknown`);
- containment ("X complex consists of A, B, C") becomes a **group** with
  members, plus `contains` relations — never an edge, never juxtaposition;
- temporal/process order ("first … then …") becomes `precedes` with step
  labels;
- `evidence` = verbatim substring of the material + locator (section,
  paragraph, table row, page) + source id (DOI/filename).

Extraction rules for the hard cases:

- **Entity ambiguity** (synonyms/abbreviations, "β-catenin" vs "CTNNB1"):
  one entity, label as the source prints it, note the equivalence in
  result.json `uncertainty`. Two names that the source distinguishes stay two
  entities.
- **Direction not stated**: `direction: "unknown"` (dashed + `?`). State the
  ambiguity in `uncertainty`; do not resolve it by plausibility.
- **Indirect evidence** ("X leads to Y via Z" for the X→Y claim): use type
  `indirect` (dashed) or model the mechanistic chain X→Z→Y if each hop is
  quoted. Prefer the chain — reviewers can follow it.
- **Numbers/units/concentrations in the material** (e.g. "3.3–10.4%"): keep
  them in edge/node labels exactly as printed, never rounded or invented.
- If the case asks for a **chart of actual data values**, that is outside
  this skill's core (statistical charting) — still deliver what applies
  (entity table, data-to-legend mapping discipline) and mark the rest partial
  with the reason.

### Step 3 — Validate before drawing

```
python /skills/weekly-skill/scripts/model_check.py /app/work/model.json
```

Exit 0 = clean (warnings allowed). Fix every error — the renderer refuses on
errors anyway. Warnings (`entity_no_evidence`, `direction_uncertain`,
`cycle_in_rank_graph`, …) are legitimate scientific states: keep them and
carry them into result.json rather than "fixing" them by invention.

### Step 4 — Render the editable SVG

```
python /skills/weekly-skill/scripts/make_schematic.py /app/work/model.json -o /app/work/figure.svg --report /app/work/layout.json
```

Produces a layered SVG: `node-*` / `edge-*` / `group-*` / `legend` groups,
each carrying `data-evidence-quote/-locator/-source`. Layout is automatic
(longest-path layering, so `A_to_B` edges point downward); if content exceeds
`canvas_width` the canvas widens and a `canvas_expanded` warning is recorded —
nothing is ever clipped.

### Step 5 — Read the drawing back and verify

```
python /skills/weekly-skill/scripts/verify_svg.py /app/work/model.json /app/work/figure.svg --out /app/work/verify.json
```

This is the core anti-failure gate. It checks entity/relation coverage,
marker semantics per the symbol library, **geometric arrow direction**
(tip must be nearer the semantic target than the source), containment boxes
actually enclosing members (and not trapping non-members), node overlap,
label fit, and legend coverage. Exit 0 = pass.

If it fails: fix the **model or the edit**, re-render, re-verify. Never patch
the SVG by hand to silence a check. Two iterations is normal; if a check
cannot pass because the material is contradictory, keep the figure that the
quotes support, and record the conflict in result.json `uncertainty`.

### Step 6 — Export and compliance-check

```
python /skills/weekly-skill/scripts/export_svg.py /app/work/figure.svg -o /app/output --pdf
```

Writes `<name>_300dpi.png` and `<name>.pdf` into `/app/output`, trying
backends in order (cairosvg → Edge headless → Chrome headless → built-in PIL
rasteriser for PNG) and recording every backend failure. The report includes
per-artifact checks (resolution, white background, PDF header/page aspect,
vector content streams). Copy `figure.svg` and `model.json` to `/app/output`
as the editable sources, and the PNG doubles as the rendered preview.

### Step 7 — Finalize result.json (contract coverage, honestly)

Fill every `output_contract` field — a field you cannot fill stays `null`
with a reason in `partial_reasons`. Typical mapping (adapt names to the
case's contract):

- `editable_source` → `{svg, model, note: "layered SVG; every element carries data-evidence-*"}`
- `exported_artifacts` → the export report's artifacts (path, format, dpi, backend, checks)
- `rendered_preview` → the PNG path
- `entity_relation_table` → entities + relations incl. quotes/locators (or a
  path to model.json plus counts)
- `verification_report` → verify.json summary (pass/fail counts, warnings)
- `sources` → source documents/DOIs used, with the quote provenance
- `status` → `complete` only if verify passed and all exports ok; otherwise
  `partial` with reasons. `uncertainty` lists ambiguities (entity
  identification, unknown directions, unresolved conflicts).

## Editing an existing SVG (source-preserving)

When the case provides an SVG to modify rather than material to draw:

1. Read the SVG; locate `node-*`/`edge-*` groups and their `data-*`
   attributes (figures from this skill are fully self-describing).
2. **Local changes** (relabel, recolour, edge type/label, title, delete an
   unattached element) → write an edits JSON and run
   `python /skills/weekly-skill/scripts/edit_svg.py figure.svg edits.json -o figure_edited.svg`.
   Every op needs a `reason`; the report proves untouched elements are
   byte-identical (`preserved.ok`). Then re-export (Step 6).
3. **Structural changes** (add/remove entities or relations, flip a
   direction) → these are REFUSED by edit_svg by design (a flipped attribute
   without re-routing draws a lying arrow). Reconstruct/extend model.json
   from the SVG's data attributes, edit the model, re-render, re-verify.
4. If the existing SVG is from another tool (no data attributes), rebuild the
   model from the source material and re-render — do not hand-hack foreign
   SVG; record what you did in result.json `change_log`.

## Failure playbook (real paths, not prose)

| situation | detection | action | result.json |
|-|-|-|-|
| case/material unreadable | Step 1 or your own read | scaffold written, `partial_reasons` names the file/problem | status `partial`, fields null |
| relation you cannot quote | `model_check` error `relation_no_evidence` | drop the relation or find the quote; never draw unquoted | absent from figure (correct) |
| direction not stated | your extraction | `direction: "unknown"` | dashed + `?`; `uncertainty` entry |
| synonym/abbreviation entity | your extraction | single entity, equivalence noted | `uncertainty` entry |
| contradictory material | two quotes clash | draw what the stronger/more specific quote supports | both quotes + conflict in `uncertainty` |
| label overflows its box | `verify` `text_fit` warn | shorten label or add `\n`, re-render; box growth is a re-render decision | warning carried |
| canvas too small | `canvas_expanded` warning | already auto-widened; or raise `canvas_width` | warning carried |
| cairosvg DLL missing (Windows) | export backend attempt recorded | auto-fallback to browser headless, then PIL rasteriser | backend + attempts recorded |
| no browser, no cairosvg | all backends fail | PIL rasteriser (boxes/lines/text; markers approximated) + `notes` | status `partial` for PNG quality, PDF null with reason |
| PDF aspect wrong | export check | fixed by @page sizing; if a backend ignores it, recorded as `checks_fail` | status `partial` |
| verify cannot pass | `verify_svg` exit 1 | model-level fix loop; if impossible, ship the quoted subset | `verification_report` shows fails honestly |

## Self-check before you finish

- `verify_svg` exit 0 (or fails honestly reported);
- `/app/output` contains: result.json (all contract keys present, nulls
  explained), figure.svg, model.json, PNG (300 dpi), PDF;
- every drawn relation is quotable — spot-check three random `data-evidence-quote`
  values against the material;
- no entity/number appears in the SVG that is not in model.json;
- change_log tells the story of what you did, including this skill's steps.
