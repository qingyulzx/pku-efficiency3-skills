# relationship-schematic

An Agent skill for **scientific entity-relationship schematics** — mechanism
diagrams, pathway chains, experimental workflows, structural containment —
where the figure must be *scientifically correct*, not just pretty: right
entities, right arrow directions, right hierarchy, every claim traceable to
the source material, and a genuinely editable SVG as the master source.

It exists because generic image generation fails on exactly these axes:
inhibition drawn as activation, upstream/downstream reversed, containment
drawn as juxtaposition, invented gene names, bitmap-only output. This skill
makes those failures structurally hard to ship:

- **Evidence-first extraction** — nothing is drawn that is not in an
  entity/relation table, and every table row carries a verbatim quote +
  locator. A relation without a quote is refused by the tooling.
- **Draw-time self-check** — `model_check.py` refuses invalid models
  (dangling endpoints, unknown relation types, containment cycles).
- **Read-back verification** — `verify_svg.py` re-parses the rendered SVG and
  checks every relation INCLUDING the *geometric* direction of each arrow
  (the arrowhead must be nearer the semantic target), containment boxes
  actually enclosing their members, node overlaps, label fit, legend
  coverage.
- **Source-preserving edits** — `edit_svg.py` patches addressed elements in
  place and *proves* untouched elements are unchanged; meaning-flipping edits
  (silently reversing an arrow) are refused by design.
- **Layered, traceable SVG** — every `node-*` / `edge-*` / `group-*` group
  carries `data-evidence-quote/-locator/-source`; the SVG is the master
  source for PNG (300 dpi) and vector PDF export with compliance checks and
  backend fallback.

## Layout

```
SKILL.md                      # agent-facing workflow (start here)
README.md                     # this file
scripts/
  init_result.py              # contract-shaped result.json scaffold (floor deliverable)
  model_check.py              # pre-render validation of the figure model
  make_schematic.py           # model.json -> layered SVG (with schematic_lib.py)
  schematic_lib.py            # shared validation/geometry/text utilities
  verify_svg.py               # SVG read-back verification (semantics + geometry)
  edit_svg.py                 # source-preserving local edits with preservation proof
  export_svg.py               # PNG/PDF export, backend fallback, compliance checks
symbols/symbols.json          # machine-readable semantic symbol library
references/
  model-schema.md             # figure model JSON schema + finding codes
  symbol-conventions.md       # drawing grammar and the failure modes it prevents
examples/                     # real-paper-derived examples (CC BY 4.0, quoted)
GITHUB_URL.txt
```

## Requirements

- Python 3.9+ (standard library only for the core chain: check/render/verify/edit).
- For export, ONE of: `cairosvg` (with a working cairo), Microsoft Edge or
  Google Chrome (headless, auto-detected at standard Windows paths), or
  Pillow + matplotlib fonts (a built-in fallback rasteriser for PNG; PDF then
  requires a browser). Every backend failure is recorded, never skipped.
- No network access needed. No installation step: run the scripts in place.

## Quick start (2 minutes)

```
python scripts/model_check.py examples/tankyrase-axin/model.json
python scripts/make_schematic.py examples/tankyrase-axin/model.json -o fig.svg
python scripts/verify_svg.py examples/tankyrase-axin/model.json fig.svg
python scripts/export_svg.py fig.svg -o exports --pdf
```

Open `exports/fig_300dpi.png` and `fig.svg` (any text editor or Inkscape:
everything is real text and real shapes). See `examples/README.md` for the
full example documentation, sources and checksums.

To draw your own figure: write a `model.json` (schema in
`references/model-schema.md`) from your source text — entities and relations,
each with a verbatim quote — then run the four commands above. The skill's
`SKILL.md` documents the agent workflow around the same scripts, including
how to handle ambiguity, unknown directions and edit requests.

## Limitations

- Layout is automatic (longest-path layering + barycentre ordering); very
  dense graphs (>40 relations) may produce long edges — widen
  `canvas_width` or split into sub-figures via groups.
- The PIL fallback rasteriser handles this skill's SVG profile (rects,
  M/L/C paths, markers, text); exotic SVG features from other tools are
  flagged, not drawn.
- Colour is decorative grouping only; all semantics live on edge tokens
  (line style, arrow vs bar), so grayscale printing loses nothing.
- Statistical charts (values, axes, error bars) are out of scope by design.

## Maintenance

Version stamps live in each script's docstring and in
`symbols/symbols.json` (`version`). The symbol library is the single point
to change when adding a new relation type: add the entry, its line/marker
mapping and legend text — renderer, verifier, editor and legend all read
from it.
