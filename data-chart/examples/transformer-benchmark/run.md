# Run commands and outputs (EXAMPLE OUTPUTS from the author's environment)

Environment: Windows, Python 3.13, matplotlib 3.11.2. These are example
outputs, not official case results.

## Commands

```
python scripts/chartgen.py --spec examples/transformer-benchmark/spec.json \
    --style references/styles/nature.json --outdir out_example/
python scripts/verify_svg.py --svg out_example/transformer_wmt_bleu.svg \
    --glyphs out_example/transformer_wmt_bleu.glyphs.json \
    --style references/styles/nature.json
```

## chartgen stdout

```json
{"ok": true, "exports": {"svg": "ok", "pdf": "ok", "png": "ok"}, "glyph_count": 15,
 "null_values_skipped": 1, "render_report": "transformer_wmt_bleu.render_report.json"}
```

15 glyphs = 8 EN-DE bars + 7 EN-FR bars; the ByteNet EN-FR null is skipped
and noted in `render_report.json` -> `null_value_notes`:
`series 'EN-FR' category 'ByteNet': no source value (null); bar omitted`.

## verify_svg stdout

```json
{"pass": true, "glyphs_total": 15, "checks_passed": 17, "checks_failed": 0,
 "calibration": {"y": "svg_ticks", "x": "glyphs_axis_ends"},
 "report": "out_example/transformer_wmt_bleu.verification_report.json"}
```

All 15 bar read-backs agree with the source values from Table 2 within
tolerance (relative 0.5% of axis span, ~0.22 BLEU); y calibration derived
independently from the SVG's own tick marks. Font sizes stayed within
Nature's 5-7 pt range (`svg/font_size_range` check).

## Sample read-back check (from the verification report)

```json
{
 "glyph": "bar/EN-DE/Transformer (big)",
 "pass": true,
 "expected_value": 28.4,
 "readback_value": 28.4,
 "abs_error": 0.0,
 "tolerance": 0.2212,
 "source_locator": "Table 2, column 'BLEU EN-DE', rows ByteNet..Transformer (big)"
}
```
