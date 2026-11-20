---
name: science-chart-craft
description: Generate, restyle and edit publication data charts (bar, grouped bar, line, scatter, heatmap, pie, box) from real source tables with guaranteed value-to-glyph traceability. Renders editable SVG/PDF plus 300dpi PNG via matplotlib, applies journal style profiles (Nature/IEEE/PLOS/default) for fonts, line widths and colours, and verifies the rendered figure by reading glyph geometry back out of the SVG and comparing against the source values. Use when a task asks to draw, plot, restyle or edit a scientific figure from source data, or to export charts in journal-compliant formats.
---

# Science chart craft: source-value charts with verifiable data mapping

Produce a chart whose every glyph can be traced back to a source value, in
journal-compliant style, with editable vector outputs and an automated
read-back verification that proves the mapping. The failure mode this skill
exists to prevent: a figure that looks right but whose bar heights, point
positions, colours or angles do not correspond to the source numbers.

Runtime layout: work under /app/work, deliver results under /app/output.
Every step below writes something durable to disk - do not keep intermediate
judgements only in your head.

## Step 0 - Read the actual input

Read /input/case.json and the task materials completely before anything else.
Read actual files; never assume content from their names. Identify: the source
data table(s), the requested chart type(s), the target journal/template (if
any), required export formats, and the output_contract fields of result.json.

## Step 1 - Extract data and build the spec (your judgement)

Extract the data table from the materials (parse the PDF/CSV/JSON as needed;
the source data for charts is provided in the case). For each numeric series
record its exact source locator (file, table, row/column) - you will need it
for traceability and it cannot be recovered later. Then write a chart spec
per /skills/weekly-skill/references/chart-spec.md:

- Choose the chart type yourself (see the decision table in chart-spec.md);
  justify the choice in one sentence for result.json.
- Missing table cells become `null` - never 0, never interpolated.
- Check units: if a unit is ambiguous or absent, decide how to label the axis
  and record the uncertainty.
- Series names in the spec must equal the series names in the source table
  (legend-series correspondence is checked).

Save as /app/work/<chart_id>.spec.json. If the source cannot yield a usable
table, go directly to Step 6 with an explicit null result and reason.

## Step 2 - Pick the style profile and render

Select /skills/weekly-skill/references/styles/<profile>.json per /skills/weekly-skill/references/journal-profiles.md
(nature / ieee / plos / default, or a copy edited to a custom template, with
requirements noted). Then:

```
python /skills/weekly-skill/scripts/chartgen.py --spec /app/work/<chart_id>.spec.json \
    --style /skills/weekly-skill/references/styles/<profile>.json --outdir /app/output/
```

Outputs per chart: editable SVG (text as <text>, never outlined), vector PDF,
300dpi PNG, plus <chart_id>.glyphs.json (the value->glyph mapping table) and
<chart_id>.render_report.json (export status, skipped nulls, font fallbacks).

Exit codes: 0 ok; 2 spec/style error (fix the spec as the message says, this
is the normal repair loop); 3 render error (partial outputs may exist).

## Step 3 - Verify by read-back (do not skip)

```
python /skills/weekly-skill/scripts/verify_svg.py --svg /app/output/<chart_id>.svg \
    --glyphs /app/output/<chart_id>.glyphs.json \
    --style /skills/weekly-skill/references/styles/<profile>.json
```

This re-measures glyph geometry from the SVG itself, re-derives the
pixel->value calibration from the SVG's own tick marks, and checks: bar
heights, point positions, error-bar extents, heatmap cell colours, pie sector
angles, that text is still editable (not outlined), and that font sizes are
within the journal's allowed range. Exit 0 = pass, 1 = failures, 2 = unreadable.

If verification fails: fix the spec or profile and re-run Steps 2-3. A chart
that fails read-back must not be delivered as final.

## Step 4 - Inspect the rendering (your judgement)

Open the PNG and judge what automation cannot: label collisions, legend
placement, readability, whether the chart type actually suits the data. For
CJK text confirm a CJK font was available (render_report.fonts_requested_but_missing)
and that no characters render as boxes. Fix and re-render if needed.

## Step 5 - Edit scenarios (if the case asks for edits)

When asked to change data or style of an existing figure: modify the spec /
source data and re-render. Never re-draw from a screenshot. Keep the previous
version, and record what changed and why in result.json change_records.

## Step 6 - Write result.json (deliver early)

Write /app/output/result.json with case_id and every output_contract field.
Fields that could not be produced are explicit null with a reason string -
never silently omitted, never fabricated. Structure:

```json
{
  "case_id": "<from case.json>",
  "chart_type_chosen": "grouped_bar",
  "chart_type_rationale": "two metrics across 8 models",
  "editable_source_files": [{"path": "output/<id>.svg", "format": "svg",
    "editable": true, "text_as_text_elements": true},
    {"path": "output/<id>.pdf", "format": "pdf"}],
  "exported_files": [{"path": "output/<id>.png", "format": "png",
    "dpi": 300, "width_px": 1051, "height_px": 708}],
  "data_mapping": {"path": "output/<id>.glyphs.json",
    "description": "value->glyph mapping table with source locators"},
  "verification": {"path": "output/<id>.verification_report.json",
    "passed": true, "checks_passed": 17, "checks_failed": 0,
    "calibration_source": "svg_ticks"},
  "style_profile": {"name": "nature", "source_urls": ["..."]},
  "source_data": {"locator": "Table 2 of ...", "version": "...",
    "sha256": "..."},
  "null_values": [{"series": "EN-FR", "category": "ByteNet",
    "reason": "empty cell in source table"}],
  "uncertainty": ["unit of column X not stated in source; axis left unitless"],
  "change_records": [{"change": "re-rendered with rotated tick labels",
    "reason": "label collision", "step": 2->3 rerun"}],
  "run_status": "complete | partial",
  "partial_limits": null
}
```

Write a first version of result.json as soon as Step 2 produces any output
(even with partial fields), then improve it - a partial honest result beats a
complete one that never lands.

## Step 7 - Final check

Re-read result.json against the output_contract: every field present or
explicitly null; SVG and PDF exist and open; verification report exists and
passed; source locators present for every series; uncertainties honest.

## Reference files

- /skills/weekly-skill/references/chart-spec.md - spec format, value rules, chart-type table
- /skills/weekly-skill/references/journal-profiles.md - profile selection, what each key controls
- /skills/weekly-skill/references/exceptions.md - full exception matrix (detection, disposition,
  where recorded) - read it when anything fails or looks wrong
- /skills/weekly-skill/references/styles/*.json - style profiles with journal-quoted requirements
- /skills/weekly-skill/examples/transformer-benchmark/ - worked example on real published data
  (arXiv:1706.03762v7 Table 2) with verbatim quotes, locators and sha256

## Dependencies

Python 3 with matplotlib (>= 3.7; developed on 3.11). The scripts use only
matplotlib + stdlib. Font availability differs per machine; chartgen filters
the profile's font fallback chain against installed fonts and records what
was missing - check render_report.json when glyphs could be missing (CJK).
