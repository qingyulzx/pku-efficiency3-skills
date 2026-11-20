# Graphical Abstract Builder — usage guide

A skill that turns research material into a single-page graphical abstract
(question → method → results → conclusion) as a **traceable, editable SVG**
with PNG/PDF exports and a contract-complete `result.json`. Every drawn
element keeps a verbatim quote and locator back to the source material.

## What you get from one run

| Artifact | What it is |
|---|---|
| `graphical_abstract.svg` | Editable source of truth: named element ids, provenance `<desc>` on every element, real editable `<text>` |
| `graphical_abstract.png` | 300 dpi raster export (matplotlib; Pillow fallback) — also the render preview |
| `graphical_abstract.pdf` | Vector export |
| `figure_model.json` | Your input: the structured, editable description of the figure (edit this, not the SVG) |
| `element_map.json` | Machine-readable element → source(quote+locator) → visual-encoding map |
| `export_report.json` / `issues.json` | Build report and verification results |
| `result.json` | Every `output_contract` field filled or explicitly null |

## Quick start

```bash
# 0. scaffold result.json (do this first, always)
python scripts/make_result.py --stage init --case /input/case.json --out /app/output/result.json

# 1. build the figure from a model you authored (see SKILL.md Step 2-3)
python scripts/build_figure.py --model figure_model.json --outdir out --sources sources.json

# 2. verify
python scripts/check_figure.py --outdir out --sources sources.json

# 3. assemble the final result
python scripts/make_result.py --stage final --case /input/case.json \
  --out /app/output/result.json --values values.json \
  --map out/element_map.json --export out/export_report.json \
  --issues out/issues.json --status complete --uncertainty "..."
```

Worked example on a real paper: `examples/transformer-1706.03762/`
(arXiv:1706.03762, verbatim quotes, sha256 of the material) — run it with
the commands in its README.

## Requirements

- Python 3.10+ (uses `X | Y` unions). Only standard library is strictly
  required for SVG; `matplotlib` for PNG/PDF (falls back to `Pillow` for
  PNG; PDF needs matplotlib or an external converter — the playbook covers
  it).
- No network access needed at run time. No installation — the scripts are
  self-contained under `scripts/`.

## File map

```
SKILL.md                          # the workflow (start here)
README.md                         # this file
scripts/build_figure.py           # model -> SVG/PNG/PDF + element map + report
scripts/check_figure.py           # independent verification pass
scripts/make_result.py            # result.json scaffold (init) + assembly (final)
scripts/ga_lib/                   # scene graph, writers, layout engine, checks
  scene.py                        #   primitives + Okabe-Ito palette + colour math
  helv.py                         #   shared text metrics (SVG/mpl/Pillow agree)
  model.py                        #   figure_model.json loader/validator/layout
  svg_writer.py                   #   editable SVG serialization
  mpl_writer.py                   #   PNG/PDF via matplotlib (+fallback hook)
  pillow_writer.py                #   PNG fallback rasterizer
  validate.py                     #   all post-build checks
  contract.py                     #   output-contract matching (3 levels)
templates/agent_worksheet.md      # Step 2 extraction worksheet
templates/figure_model.template.json
references/model_schema.md        # figure_model.json field-by-field
references/exception_playbook.md  # failure signature -> remedy (all tested)
references/design_notes.md        # encoding/colour/typography conventions
examples/transformer-1706.03762/  # real-paper worked example + provenance
```

## Limitations

- Panels share one row (no 2×2 grid yet); very panel-heavy figures need a
  taller/wider canvas.
- Chart types: bar, hbar, grouped_bar, line. No scatter/pie/heatmap yet —
  for those, extend `ga_lib/model.py` following the existing chart methods.
- The layout engine is pixel-deterministic but text metrics are Helvetica
  AFM estimates; exotic glyphs (wide unicode symbols) may render slightly
  wider than measured.
- PDF export requires matplotlib; in environments without it, use the
  documented browser-automation/pdf-render-tool substitution path.

## Maintenance

Schema version is pinned (`graphical-abstract/1`) and validated on load;
the element map format is the stable interface between the figure and
result.json. To extend: add a layout method in `ga_lib/model.py`
(`_panel_<layout>`), a chart branch, or a check in `ga_lib/validate.py`.
All scripts print actionable diagnostics and never abort a run after the
SVG is written.
