# biopathway-mechanism-diagram

A skill for building **biological mechanism / pathway diagrams that can survive
being challenged**. It turns mechanism text (papers, figure captions, case
descriptions) into a three-layer model — typed entities, typed directed edges
with verbatim evidence, compartment layout — and renders it to a layered,
editable SVG with PNG/PDF exports and a traceable result.json.

The design principle: a pathway figure is a **mechanism statement**, not
decoration. Every arrow is an assertion. This skill makes each assertion
traceable (verbatim quote + location per entity and edge), semantically
distinct (activation / inhibition / binding / phosphorylation / transport each
have their own unambiguous glyphs) and honest about what the source did not
state (undirected edges, unspecified compartments, null fields with reasons —
**it never guesses regulation direction**).

## Install

Copy this directory (SKILL.md at the root) into your agent's skills location
(the evaluation platform installs it at `/skills/weekly-skill`). Runtime needs:
Python 3.8+ standard library only for the core chain (validate → render →
verify). PNG/PDF export is best with `cairosvg` or `rsvg-convert`; without
them a native Pillow fallback re-renders from the model (and the failure is
recorded, never hidden).

## Quick start

```bash
# 0. contract-complete result.json first (null + reason for anything absent)
python scripts/scaffold_result.py --input /input/case.json --outdir /app/output

# 1. you (the agent) build /app/work/model.json by reading the real material
#    (schema: references/layout-conventions.md; rules: references/*.md)

# 2. validate the science-bearing model
python scripts/validate_model.py --model /app/work/model.json

# 3. render + export
python scripts/render_svg.py --model /app/work/model.json --out /app/output/pathway.svg
python scripts/export_assets.py --svg /app/output/pathway.svg \
    --outdir /app/output --model /app/work/model.json

# 4. verify the delivered bundle by reading it back
python scripts/verify_outputs.py --model /app/work/model.json \
    --svg /app/output/pathway.svg --result /app/output/result.json \
    --exports /app/output/pathway.png /app/output/pathway.pdf
```

Edits to an existing figure (source-preserving; original kept as `.bak`;
changes logged in the model):

```bash
python scripts/apply_edit.py --model /app/work/model.json --op add-edge \
    --id e-noggin --src NOGGIN --tgt BMP4 --type binding --directed false \
    --loc "Fig. 3 caption" --quote "the BMP dimer is bound by Noggin"
python scripts/render_svg.py --model /app/work/model.json --out /app/output/pathway.svg
```

## What the scripts check (and why)

- **E-DIR-01** — a directed edge whose evidence quote contains no directional
  cue is rejected. This is the "never guess direction" rule made mechanical.
- **Naming rules** — gene nodes (italic) vs proteins, families vs members,
  complexes as single hexagons; same-label collisions flagged.
- **Receptor/membrane** — receptors belong on the membrane band; free-floating
  receptors are flagged.
- **Legend ↔ figure consistency, both directions** — every used semantic has a
  legend entry; no phantom entries for unused types.
- **Read-back verification** — the delivered SVG is re-opened and every model
  entity/edge must be present; labels must fit their boxes; exports must exist
  and not be blank.
- **result.json completeness** — every contract field present; every null
  carries a reason.

## Model schema (short)

`model.json` = `{compartments[], entities[], edges[], uncertainties[]}` with
per-entity `type`/`compartment`/`order`/`source{loc,quote}` and per-edge
`type`/`directed`/`sign`/`confidence`/`evidence{loc,quote}`. Full schema and
the layout algorithm: [references/layout-conventions.md](references/layout-conventions.md).
Edge semantics: [references/edge-types.json](references/edge-types.json) +
[references/symbol-semantics.md](references/symbol-semantics.md).

## Example

[examples/ras-mapk-case/](examples/ras-mapk-case/) walks the full chain
(model → validation → SVG → exports → verification) on real published text:
the RAS–MAPK pathway as described in Brown & Ried 2022 (Cancers 14:784,
doi:10.3390/cancers14030784, CC BY 4.0), with verbatim quotes and locations.
The outputs there are labeled as example material derived from that source.

## Limits

- The scientific judgement (entity typing, edge typing, direction) is the
  agent's; the scripts enforce the contract, they do not do biology.
- Layout is band-based (compartment rows × pathway-order columns); extremely
  dense crosstalk graphs may need panel splitting (warned, not hidden).
- The native PNG fallback re-renders text with approximate metrics; the SVG is
  always the authoritative vector source.
- No network access is assumed anywhere; name normalization relies on the
  agent's own knowledge plus the recorded reference (HGNC/UniProt/MGI).

## Maintenance

Version 1.0.0. All scripts are single-file stdlib Python with `--report` JSON
outputs so they compose into agent loops. The semantics library
(`references/edge-types.json`) is the single place to extend edge/node types;
validators and renderer read it, so additions propagate automatically.
