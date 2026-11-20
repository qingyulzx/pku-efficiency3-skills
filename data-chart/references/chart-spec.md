# Chart spec format

The chart spec is a JSON file the agent writes after reading the source data.
It is the single input to `chartgen.py` and the contract that makes every glyph
traceable. Fields:

```json
{
  "chart_id": "fig1_ende_bleu",
  "chart_type": "grouped_bar",
  "title": "WMT 2014 EN-DE BLEU by model",
  "x": { "label": "Model", "unit": null },
  "y": { "label": "BLEU", "unit": null, "log": false },
  "categories": ["ByteNet", "GNMT + RL", "ConvS2S", "Transformer (big)"],
  "series": [
    {
      "name": "BLEU score",
      "values": [23.75, 24.6, 25.16, 28.4],
      "errors": [null, null, null, null],
      "error_meaning": "SD",
      "color": null,
      "source": {
        "file": "case.json / paper.pdf",
        "locator": "Table 2, column EN-DE, rows ByteNet..Transformer (big)",
        "version": "arXiv:1706.03762v7"
      }
    }
  ],
  "notes": "Data from Vaswani et al. 2017, Table 2.",
  "color_scale": { "vmin": null, "vmax": null, "label": "value" }
}
```

## Field rules

| Field | Required | Notes |
|-|-|-|
| `chart_id` | yes | safe file-name fragment; names all output files |
| `chart_type` | yes | one of `bar`, `grouped_bar`, `line`, `scatter`, `heatmap`, `pie`, `box` |
| `categories` | yes (not pie-only) | x-axis category labels; also heatmap rows |
| `columns` | heatmap only | heatmap column labels |
| `series[].name` | yes | legend label; must match the source table's series name |
| `series[].values` | yes | numbers or `null` for missing; heatmap: matrix rows x columns; box: list of replicate lists |
| `series[].errors` | optional | same length as `values`; +/- magnitude, one-sided |
| `series[].error_meaning` | with errors | SD / SEM / 95% CI - what the error bar means |
| `series[].color` | optional | hex override; default comes from the style profile palette |
| `series[].source` | yes | `locator` mandatory: which file/table/row/column the numbers came from |
| `x`/`y` | recommended | `label`, `unit`, `log` |
| `color_scale` | heatmap | `vmin`/`vmax`/`label` |

## Value rules

- Missing / not-reported numbers are `null`, never 0 and never invented. Each
  null is skipped in rendering and recorded in `render_report.json` and the
  glyphs table `null_value_notes`.
- Percentages: keep the unit in the axis label (`%`), values as plain numbers.
- Series with unequal category coverage still list `null` placeholders so the
  category alignment stays explicit.

## Choosing a chart type (agent judgement)

| Situation | Type |
|-|-|
| one metric across few categories, single series | `bar` |
| several metrics/models side by side | `grouped_bar` |
| trend over ordered x (time, dose) | `line` |
| two continuous variables per observation | `scatter` |
| matrix (samples x genes, models x tasks) | `heatmap` |
| parts of one whole (shares summing to 100%) | `pie` |
| replicate distributions per condition | `box` |

Do not use `pie` for shares that do not sum to a whole, and do not use a
truncated y-axis (starting above 0) with `bar` - either start at 0 or state
the truncation in `notes`.
