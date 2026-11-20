# Exception handling matrix

Every row below is implemented: the detection point is in code (script) or is
an explicit agent checkpoint, and the disposition is recorded in
result.json / render_report.json / verification_report.json. Never silently
drop or "fix" data.

| # | Situation | Detected by | Disposition | Recorded in |
|-|-|-|-|-|
| 1 | Missing value in source table (empty cell) | agent extraction; `values:[...]` uses `null` | glyph omitted; note "no source value" | `render_report.null_value_notes`, glyphs.json, result.json uncertainty |
| 2 | Column short/long vs categories | `chartgen.py` validate_spec | exit 2 with message naming series and both counts; agent realigns | stderr message; agent logs fix |
| 3 | Duplicate category labels | validate_spec | exit 2 listing the rule | stderr |
| 4 | Unit unknown / ambiguous | agent judgement at spec time | axis label without unit + explicit uncertainty in result.json; never invent a unit | result.json |
| 5 | Series name/legend mismatch vs source table | agent compares spec series names with source table header | correct spec, re-render | result.json notes |
| 6 | Non-positive values with log axis requested | validate_spec | exit 2 naming the offending values; linear fallback suggested | stderr |
| 7 | NaN/Inf in values | validate_spec | exit 2 | stderr |
| 8 | Negative pie values / non-positive sum | validate_spec | exit 2 | stderr |
| 9 | Heatmap matrix shape mismatch | validate_spec | exit 2 with expected shape | stderr |
| 10 | Box series values not replicate lists | validate_spec | exit 2 | stderr |
| 11 | Long category labels overflowing axis | chartgen heuristic (rotation) | rotates labels 30 deg right-aligned | visual; agent checks PNG |
| 12 | Font family missing on system | chartgen filters fallback chain against installed fonts | falls back to first available (DejaVu Sans last resort); missing fonts listed | `render_report.fonts_requested_but_missing` |
| 13 | CJK glyphs needed but no CJK font | same as 12; agent must confirm CJK font in fallback chain or expect boxes in PNG | choose profile with SimHei/Microsoft YaHei/Noto fallback; if none available, note the limitation | render_report + result.json |
| 14 | SVG/PDF/PNG export failure (disk, format error) | chartgen per-format try/except | other formats still export; failed format marked with error string | `render_report.exports[fmt].status` |
| 15 | Verification failure (value mismatch, geometry off, text outlined) | `verify_svg.py` exit 1 | agent inspects report, fixes spec/style, re-renders, re-verifies; if unfixable, report as partial with limits | verification_report.json checks[] |
| 16 | Calibration impossible (no readable ticks) | verify_svg calibration fallback | uses axis-end calibration from glyphs.json and says so in `calibration.source` | verification_report.json |
| 17 | Source file unreadable / no table found | agent at extraction | result.json with explicit null fields + reason; do not fabricate | result.json |
| 18 | Spec/style JSON malformed | chartgen load | exit 2 with parse error | stderr |
| 19 | Font size outside journal range | verify_svg `svg/font_size_range` check | agent re-renders with corrected profile sizes | verification_report.json |
| 20 | Edit request on existing figure | agent workflow | edit source data / spec, re-render (never re-draw from screenshot); keep prior version, record change | result.json change_records |

Exit-code contract (both scripts, both platforms): 0 = success; 1 =
verification failures (verify_svg only); 2 = input/spec error the agent must
fix; 3 = render error after which partial outputs may exist.
