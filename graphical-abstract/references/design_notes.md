# Design notes — visual encoding rules used by the builder

These are the conventions the layout engine implements; they exist so that
a reviewer can decode the figure without a legend hunt, and so that the same
model always renders the same way.

## Reading order

- Panels sit in one row, ordered question → method → results → conclusion
  (role order unless `reading_order` overrides). Numbered badges (1, 2, 3…)
  and grey inter-panel arrows make the order explicit.
- Role accent strips across panel tops: question blue, method green, results
  orange, conclusion purple (Okabe–Ito, distinguishable in grey scale).

## Visual channels — what maps to what

| Meaning | Channel | Rules |
|---|---|---|
| Magnitude (same unit, natural zero) | **length** (bar height) | zero baseline drawn; scale shown by axis ticks; value labels on top |
| Magnitude with long labels | length (horizontal bar) | baseline at left; values at bar ends |
| Time series / ordered conditions | **position** (line + point) | y position encodes value; points carry per-point sources |
| Category / series identity | **colour** (Okabe–Ito) | one colour per series, reused across panels; legend required |
| Headline numbers | text + size (big-number callout) | exact value, explanatory label, never re-scaled |
| Hierarchy / containment | dashed container groups | members listed in the element map |
| Focal entity | border weight (`emph`) | at most one per panel |
| Footnote / caption material | small grey text at bottom | explicitly excluded from canvas claims in the map |

Hard rules:
- One channel per meaning and one meaning per channel — never encode the
  same variable in both colour and length in one panel.
- Colour is categorical only; never encode a continuous value as rainbow.
- No pure red vs. green pair anywhere (deuteranopia); the palette's
  vermillion/green pair differs in lightness and is checked for grey-scale
  separation.
- Every axis gets its unit; every bar/point keeps its value label available.

## Typography

- Font stack `Helvetica, Arial, 'Noto Sans', 'DejaVu Sans', sans-serif`;
  text is always real `<text>` in SVG (never outlined, never rasterized).
- Size ladder: panel heading 21 px bold, node text 16.5, edge labels 13.5,
  axis ticks 13, value labels 14, legend 14, notes 13. Floor: 12 px,
  enforced by the checker.
- Text measurement uses shared Helvetica AFM metrics for SVG, matplotlib
  and Pillow alike, so wrapping decisions are identical across outputs.
- CJK characters measure at 1.0 em; mixed CJK/Latin labels wrap correctly.

## Layout

- Canvas 1800×1000 px default (A4-landscape-like); margins 36 px;
  panel gap 20 px; inter-panel arrows at heading height.
- Panel width weights: question 1.0, method 1.18, results 1.55,
  conclusion 1.05 — results panels need room for axes and labels.
- Flow nodes: same layer → same row; rows top-to-bottom; node width capped
  at 330 px to keep ~3 columns max.
- Content that does not fit is **reported** (`panel-content-overflow`),
  never silently clipped — an invisible-clipping figure is worse than an
  honest build error.

## Traceability plumbing

- Every primitive gets a stable `id` (SVG `id`, matplotlib `gid`, map key).
- Every evidence-bearing element carries a `<desc>` in the SVG: kind, file,
  locator, verbatim quote — readable in any text editor or Inkscape's XML
  pane.
- Layers: single `layer-content` group by design; the model's panels remain
  addressable through element id prefixes (`p-question-*`, `p-method-*`...).
- `element_map.json` joins id → source → encoding, including numeric scale
  (`scale_px_per_unit`, `zero_baseline`) so a reviewer can audit the
  length encoding arithmetic.
