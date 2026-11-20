---
name: biopathway-mechanism-diagram
description: Build or edit publication-grade biological mechanism/pathway diagrams from research materials (PDF/text) as a challengeable mechanism statement - three-layer model (typed entities, typed directed edges with verbatim evidence, compartment layout), semantics-correct SVG source, PNG/PDF exports and a traceable, uncertainty-aware result.json. Use for tasks asking to draw, generate or edit signaling pathways, mechanism figures, crosstalk diagrams or pathway flowcharts; refuses to guess regulation direction and marks unstated information instead.
---

# biopathway-mechanism-diagram

A pathway figure is a **mechanism statement that readers will challenge one
arrow at a time**. This skill's contract: every entity and every edge on the
canvas traces to a verbatim quote with a location; interaction semantics
(activation / inhibition / binding / modification / transport) are visually
distinct and never conflated; anything the source does not state (direction,
location, numbers) is visibly marked as unstated, not guessed. Deliverables are
a layered, id-addressable editable SVG plus PNG/PDF exports and a
contract-complete result.json.

## When to use / when not

Use for: mechanism figures, signaling pathway diagrams, receptor-to-nucleus
cascades, pathway crosstalk, "draw Figure N from this paper" tasks, and edits
to an existing pathway figure (add/remove entity or edge, relabel).
Not for: statistical charts (bar/box/volcano), experimental schemas, or
aesthetic-only retouching; those belong to adjacent skills.

## Execution contract (platform runtime)

- Input: `/input/case.json` (+ task.md). Work under `/app/work`; deliverables
  under `/app/output`.
- First action of the whole run (before reading the case in depth):
  `python scripts/scaffold_result.py --input /input/case.json --outdir /app/output`
  This writes a result.json with **every output-contract field present**,
  unproduced ones null + reason. Keep updating it stepwise; never delete a
  contract field.
- All scripts below take `--model`/`--svg` style paths and are pure Python 3
  (stdlib only) unless noted. `references/` is read by the scripts; read the
  `.md` files yourself before Step 1.

## Step 0 - Read the contract and scaffold (1 request)

Run the scaffold. Skim task.md + case.json: identify the figure target (which
mechanism, which figure if reproducing one, generate vs edit scenario), the
required export formats, and the evidence scope. Record the contract field
list you must fill. **Budget awareness: aim to finish in 5-8 model steps;
scripts do the heavy lifting, you do the science.**

## Step 1 - Extract the mechanism model (the scientific core - do it yourself)

Read the actual material (parse the PDF for real; read files, never assume
content from labels). Build `/app/work/model.json` per
`references/layout-conventions.md` by YOUR OWN judgement:

1. **Entities** — gene / protein / receptor / RNA / complex / molecule / cell /
   family. Apply `references/naming-rules.md`: gene symbols italic and gene
   nodes distinct from their proteins (*MYC* vs MYC); preferred symbols with
   source spellings in synonyms; families vs members; one node per stated
   complex. Each entity carries `source: {loc, quote}` — a VERBATIM quote and
   a location precise enough to re-find (section/paragraph/page/figure-caption).
2. **Edges** — type from the closed set in `references/edge-types.json`
   (activation, inhibition, binding, phosphorylation, ubiquitination,
   transcriptional_regulation, translocation, complex_formation, ...).
   `directed` must be set explicitly. **Never guess direction**: if the quote
   has no directional cue, set `directed: false` and log an uncertainty
   (`references/uncertainty-policy.md`). Binding/recruitment is undirected.
   Transcriptional regulation targets a gene node and needs a sign.
3. **Compartments** — extracellular / membrane / cytoplasm / nucleus (+ ER,
   Golgi, organelle sub-regions if the mechanism needs them). Entities whose
   location is unstated go to the `unspecified` band — never silently into
   the cytoplasm. Receptors anchor on the membrane band.
4. **Order** — set `order` per pathway position (topological order, not text
   order); feedback loops emerge naturally as backward edges.
5. Numbers on the canvas (expression, significance) only if they exist verbatim
   in the source; otherwise leave data mappings as explicit nulls.

Practical extraction order: read once for the overall flow; second pass
sentence-by-sentence for entities + quotes; third pass for edges including
inhibitors, feedback and crosstalk (they hide in "however/whereas" sentences).

## Step 2 - Validate the model (script)

```
python scripts/validate_model.py --model /app/work/model.json \
    --report /app/work/validation-report.json
```

Fix every `E-*` error. E-DIR-01 (directed edge without a directional cue) is
the core scientific guard: either quote a sentence that states direction or
downgrade to undirected + uncertainty. Warnings need a conscious decision:
family nodes, receptor placement, sign-vs-quote mismatches. Re-run until
valid. If the material cannot support a required contract item, note it now
(it becomes a null + reason in Step 5).

## Step 3 - Render SVG and export (scripts)

```
python scripts/render_svg.py --model /app/work/model.json \
    --out /app/output/pathway.svg --report /app/work/render-report.json
python scripts/export_assets.py --svg /app/output/pathway.svg \
    --outdir /app/output --model /app/work/model.json \
    --png-width 2400 --report /app/work/export-report.json
```

Read the render report warnings (canvas limits, unknown compartments). Look at
the PNG yourself; if the layout obscures the mechanism (edge crossings hiding
a fork, feedback over the cascade), adjust `order`/pin positions in the model
and re-render. The SVG is deterministic: identical model → identical SVG.

## Step 4 - Edit scenarios (if the case asks for edits to an existing figure)

Reconstruct the target figure's model first (Step 1 on the original figure's
source text), then use source-preserving edits — the original model/SVG are
backed up, every edit is logged in the model's change_log:

```
python scripts/apply_edit.py --model /app/work/model.json --op add-edge \
    --id e-new --src A --tgt B --type inhibition --directed true \
    --sign negative --loc "..." --quote "..."
```

Ops: add/rename/remove entity (remove refuses when edges are attached unless
--cascade, and cascade removals are logged as uncertainties), add/remove edge,
add compartment. Every added entity/edge REQUIRES verbatim --loc + --quote.
After edits, re-validate (automatic) and re-render (Step 3).

## Step 5 - Verify and finalize result.json (script + you)

```
python scripts/verify_outputs.py --model /app/work/model.json \
    --svg /app/output/pathway.svg --result /app/output/result.json \
    --exports /app/output/pathway.png /app/output/pathway.pdf \
    --report /app/output/verification-report.json
```

This re-reads the SVG and checks node/edge read-back, legend↔usage consistency
in both directions, label overflow, canvas limits, export existence, and that
every null in result.json has a reason. Then finalize result.json yourself:
fill the contract fields (editable_source paths, exports with backend/params,
entity_table/edge_table with quotes, legend_basis, sources with versions,
uncertainties, verification summary, honest status). Keep `_unanswered_reasons`
for anything null. Partial delivery must state its limits in plain words.

## Exception handling (real paths, not decoration)

| Failure | Detection | Action |
|---|---|---|
| PDF unreadable / no text layer | parse fails or empty text | pdf-render-tool / ocr-tool for the render, flag "text layer absent" in result.json |
| Entity name ambiguous (two readings) | your extraction | choose per context, record alternative + uncertainty; if undecidable, null + reason |
| Direction not stated | E-DIR-01 | downgrade to undirected edge (no arrowhead) + uncertainty. NEVER guess |
| Compartment unknown | E-CMP-01 / layout warning | `unspecified` band + note |
| Missing numeric data for data-encoded visuals | model has no verbatim numbers | draw topology, mark mapping null + "data absent from source" |
| Label overflow | verify label_overflow | shorten label / split into label+sub / reorder |
| Canvas exceeds limits | render warning | split into panels or reduce branches; note it |
| Export backend missing | export report status failed | fallback chain already tried; deliver SVG, record failure + guidance in result.json |
| Blank/degenerate PNG | blank_check | investigate render report; re-render; record |
| Validate errors persist | exit code 2 | fix model; if unfixable from the material, deliver the valid subset + explicit limits |

## Quality bar (self-check before finishing)

1. Could a reviewer point at any arrow and get its verbatim justification
   from the embedded table / model? (traceability)
2. Are activation/inhibition/binding/modification visually distinct, and does
   the legend match what is drawn — no missing, no phantom entries?
3. Is every unstated thing visibly unstated (undirected, unspecified band,
   null + reason)?
4. Can someone open the SVG, change one label, and re-export? (layered,
   id-addressable, standard font stack)
5. Does result.json cover every contract field with honest status?

## Files

- `scripts/scaffold_result.py` - contract-complete result.json with null+reason
- `scripts/validate_model.py` - schema + direction-evidence + naming checks
- `scripts/render_svg.py` - deterministic layered SVG from model.json
- `scripts/export_assets.py` - PNG/PDF with fallback chain + blank check
- `scripts/apply_edit.py` - source-preserving, logged edits
- `scripts/verify_outputs.py` - read-back verification of the bundle
- `references/edge-types.json` - machine-readable symbol semantics
- `references/symbol-semantics.md` - visual grammar and its reasoning
- `references/naming-rules.md` - gene/protein/family/complex conventions
- `references/uncertainty-policy.md` - downgrade rules; never-guess policy
- `references/layout-conventions.md` - model.json schema + layout algorithm
- `examples/ras-mapk-case/` - a real-material worked example (Brown & Ried 2022)
- `README.md` - standalone usage documentation
