# figure_model.json — schema reference

Version: `graphical-abstract/1`. A model is a JSON object describing the whole
figure. The builder validates it before rendering (exit code 2 lists every
problem), lays it out deterministically, and emits SVG/PNG/PDF plus the
element map. All coordinates are in canvas pixels, y grows downward (SVG
convention).

## Top level

| Field | Type | Required | Meaning |
|---|---|---|---|
| `schema` | string | yes | must be `"graphical-abstract/1"` |
| `case_id` | string | yes | copied from the case |
| `title` | string | no | figure title (drawn as heading) |
| `caption_note` | string | no | one-line provenance note in the SVG `<desc>` |
| `canvas` | object | no | `{width, height}` px; default 1800×1000 |
| `panels` | list | yes | 1–6 panels (see below) |
| `legend` | object | no | `{auto: true}` derives from chart groups; or `items: [{id, label, color, meaning, source}]` |
| `notes` | list[str] | no | footnotes drawn small at the bottom (caption material, not canvas claims) |
| `checks` | object | no | `{min_font_px: 12}` — font floor for the checker |
| `reading_order` | list[str] | no | explicit panel-id order; default role order question→method→results→conclusion |
| `link_panels` | bool | no | draw grey reading-order arrows between panels (default true) |

## Panel (all layouts)

| Field | Type | Required | Meaning |
|---|---|---|---|
| `id` | string | yes | stable prefix for all element ids (use `p-*`) |
| `role` | string | yes | `question` \| `method` \| `results` \| `conclusion` \| `custom` — sets accent colour and default order |
| `heading` | string | yes | panel heading text |
| `layout` | string | yes | `flow` \| `chart` \| `stats` \| `text` |
| `source` | object | no | panel-level provenance |

Panel widths are allocated by role weight (results panels get ~1.5× the
width of a question panel). All panels share one row; keep total content
within the canvas height or the overflow check fires.

## `source` object (used everywhere evidence is attached)

```json
{ "file": "materials/paper.pdf", "locator": "p. 5, Results, sentence 3",
  "quote": "Mean HbA1c change at week 12: GR metformin -0.83% ..." }
```

- `file` — path as the case sees it.
- `locator` — precise enough for a human: page + section + sentence/line.
- `quote` — verbatim substring of that file (checker verifies against
  `sources.json` when provided). Keep it short but include any number you
  draw.

## layout: `flow` — entities and relations

```json
{
  "nodes": [
    { "id": "ent-xyz", "label": "Entity label", "layer": 0,
      "accent": "blue", "emph": false, "shape": "rounded_box",
      "note": "optional small grey line inside the box",
      "source": { ... } }
  ],
  "edges": [
    { "id": "rel-xyz", "from": "ent-a", "to": "ent-b",
      "label": "activates", "meaning": "A activates B (direction matters)",
      "style": "solid" , "source": { ... } }
  ],
  "groups": [
    { "id": "grp-xyz", "label": "treatment arms", "members": ["ent-a", "ent-b"],
      "source": { ... } }
  ]
}
```

- `layer` (int, default = node index): nodes of the same layer share a row;
  rows stack top→bottom; arrows between consecutive layers are drawn
  automatically when `edges` is empty (`sequence: true` default).
- `accent`: any Okabe–Ito name (`blue orange sky green yellow vermillion
  purple grey black`) or `#RRGGBB`.
- `shape`: `rounded_box` (default) | `box` | `ellipse`.
- `emph: true` thickens the border — use for the focal entity only.
- Edge direction is scientific content: `from`/`to` must match the causal or
  temporal direction stated in the material.
- `groups` draw a dashed container — use for hierarchy (arms, compartments).

## layout: `chart` — data

Single-series bars:

```json
{ "type": "bar", "unit": "%", "y_max": 100, "show_values": true,
  "highlight": ["res-best"],
  "series": [ { "id": "res-a", "label": "Condition A", "value": 91,
                "source": { ... } } ] }
```

Grouped bars (one categorical × one series dimension):

```json
{ "type": "grouped_bar", "unit": "%", "y_max": 100,
  "categories": [ { "id": "cat-x", "label": "..." } ],
  "groups":    [ { "id": "grp-a", "label": "Series A", "color": "blue" } ],
  "values": [ [ { "value": 94.2, "source": { ... } },
                 { "value": 76.1, "source": { ... } } ],
               [ ... ] ] }
```

`values[catIndex][groupIndex]` — a plain number or `{value, source}` (use
the object form when the two numbers come from different sentences).

Line (position encoding, for time series):

```json
{ "type": "line", "unit": "mg/dL", "x_labels": ["0", "4", "8", "12"],
  "series": [ { "id": "ser-a", "label": "Arm A", "color": "blue",
                "values": [ {"value": 8.2, "source": {...}}, 7.9, 7.4 ],
                "source": { ... } } ] }
```

Horizontal bars (long category labels):

```json
{ "type": "hbar", "unit": "µm", "series": [ { "id": "...", "label": "...",
  "value": 42, "source": { ... } } ] }
```

Chart rules enforced or checked: values must be numbers; every value needs a
`source` (its own, the series', or `series_source` on the chart); a number
that does not appear in its quote triggers `value-not-in-quote` (explain
derivations — differences, means — in the quote or the encoding note).

## layout: `stats` — headline callouts

```json
{ "stats": [ { "id": "stat-x", "value": "-0.83%", "accent": "blue",
               "label": "HbA1c change at week 12 (GR arm)",
               "source": { ... } } ] }
```

2–4 items, arranged in up to 2 columns. `value` is a short string; keep the
number exact and the label explanatory.

## layout: `text` — conclusions

```json
{ "bullets": [ { "id": "cl-1", "text": "Claim in the material's own terms.",
                 "source": { ... } } ] }
```

3–5 bullets, wrapped automatically; overflow is detected and reported
(`panel-content-overflow`) rather than clipped silently.

## Element ids

Every id becomes the SVG `id` and appears in `element_map.json`. Conventions
the builder also uses internally: `p-*` panels, `ent-*` entities, `rel-*`
relations, `grp-*` groups, `res-*`/`cat-*--grp-*` data, `stat-*` callouts,
`cl-*` claims, `lg-*` legend, `note-*` footnotes. Keep ids stable across
edits — they are the join key between the figure and the evidence.
