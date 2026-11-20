# Journal style profiles

Profiles live in `references/styles/*.json`. Pick by what the case asks for:

| Case says | Profile | Width | Fonts |
|-|-|-|-|
| "Nature" / 89 mm single column | `nature.json` | 89 mm | Arial/Helvetica 5-7 pt |
| "IEEE" / one column 3.5 in | `ieee.json` | 88.9 mm | Times New Roman/Arial ~9-10 pt |
| "PLOS" / PLOS ONE | `plos.json` | 132 mm | Arial 8-12 pt |
| no target journal named | `default.json` | 120 mm | DejaVu Sans 8-10 pt |

Each profile JSON carries:

- `source_urls` + `retrieved` + `requirements_notes` - the verbatim
  requirements the profile was derived from (quotes from the journal's own
  author guidelines). Cite these in result.json when asked why a style was
  applied.
- figure width/height, margins
- font family + fallback chain, `min_pt`/`max_pt` journal limits (used by
  verify_svg.py to check the rendered font sizes stay in range)
- line widths for axes, data, bar edges, error bars
- colour palette (Okabe-Ito colour-blind-safe set as published by the Nature
  research figure guide)

## Applying a custom template

If the case supplies its own style requirements (font sizes, line weights,
brand colours), copy `default.json`, edit the values, and record the source of
each requirement in `requirements_notes`. Never hard-code style numbers in the
spec - they belong in the profile so they stay reusable.

## What each parameter maps to in the output

| Profile key | Effect in the rendered figure |
|-|-|
| `figure.width_mm`/`height_mm` | SVG/PDF physical size, PNG pixel size at `png_dpi` |
| `font.tick_pt`/`label_pt`/`title_pt` | tick labels / axis labels / title font size |
| `font.min_pt`/`max_pt` | verified by verify_svg.py (tolerance 0.5 pt) |
| `lines.axis_linewidth_pt` | axis spine weight |
| `colors.palette` | series colours in order; `series[].color` overrides |
| `export.png_dpi` | raster export resolution (default 300) |
