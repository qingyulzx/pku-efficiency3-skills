# Exception playbook — signature → remedy

Every failure mode below has been exercised against the real pipeline. When
you hit one, apply the remedy, then record what happened in `limits` /
`uncertainty` of result.json. Never fabricate data to make a check pass.

## Material problems

### The material lacks a number the figure needs
- Signature: you want to draw X but no sentence states it.
- Remedy: **do not draw it.** Either (a) drop the element, (b) draw the
  qualitative statement as a `text`-layout claim with its quote, or (c) put
  the number in `notes`/caption only if the material states it somewhere
  less prominent. Record the gap in `uncertainty`: "figure omits <X>
  because the material does not report it."

### Entity ambiguity (two entities with similar names, unclear referent)
- Signature: worksheet has two candidate entities for one label.
- Remedy: disambiguate in the label itself ("GR metformin (weekly tablet)"),
  use `groups` to keep same-level entities together, and quote the sentence
  that defines each. If the material genuinely conflates them, say so in
  `uncertainty` and use one entity.

### Entity hierarchy / level confusion (cell vs. molecule vs. device)
- Remedy: map material hierarchy to `layer` (higher level = smaller layer
  number = higher on canvas) or to `groups` (dashed containers). One level
  per row; never put a compartment and its content on the same layer.

### Relation direction is uncertain
- Signature: sentence uses passive or correlational wording.
- Remedy: use the exact direction the material states; if it only supports
  association, drop the arrow or use `style: "dashed"` and explain in
  `edges[].meaning`. An arrow is a claim — do not upgrade correlation to
  causation.

## Model problems

### Model invalid (build exit 2)
- Signature: `[build] MODEL INVALID:` + bullet list.
- Remedy: read the bullets — they name the panel and the exact problem
  (unknown edge endpoint, duplicate id, non-numeric value, missing series).
  Fix `figure_model.json`, rebuild. Common cases: `from`/`to` referencing a
  node id that was renamed; `values` matrix shape not matching
  `categories` × `groups`.

### Text overflows its panel (`panel-content-overflow`)
- Signature: `panel 'p-x' bullets need 248px but 190px available`.
- Remedy, in order of preference: shorten labels (keep quotes intact in
  `source`, shorten only `label`/`text`); move detail to `notes`; split the
  panel into two; increase `canvas.height` (also widen if < 1600). The
  check measures real rendered text — it clears only when it fits.

### Legend overflows the canvas width (`legend-overflow`)
- Remedy: shorten legend labels or reduce series count; the legend row is
  auto-centered and wraps are not supported.

## Rendering / export problems

### matplotlib missing (PDF export fails)
- Signature: `PDF export FAILED: ... No module named 'matplotlib'` with the
  remedy embedded in the error.
- Remedy: SVG is unaffected (it is pure text — always keep it). For PDF:
  render the SVG through browser-automation (print to PDF) or pdf-render-
  tool, then verify the file starts with `%PDF`. Record the substitution in
  `export_checks` and `limits`. PNG falls back to Pillow automatically
  (report shows `backend: pillow`); Pillow output is anti-aliased at 2× and
  downscaled — acceptable for preview, note it in `export_checks`.

### PNG/PDF export failure of any other kind
- Signature: entry in `export_report.json.failures`.
- Remedy: the SVG is the source of truth and already written — re-export it
  with whatever tool the environment offers (browser-automation screenshot
  at ≥300 dpi; pdf-render-tool). Keep `status: partial` if the target format
  could not be produced, and say which preview stands in for it.

### Font substitution warnings
- The SVG declares a font stack `Helvetica, Arial, 'Noto Sans', 'DejaVu
  Sans', sans-serif` and never outlines text, so any editor substitutes
  within the stack. Matplotlib exports use DejaVu Sans. If the environment
  offers font-discovery and the case demands a specific font, note the
  actually-available font in `export_checks.fonts`; do not silently pretend
  a font was embedded.

### Canvas limits (`canvas-overflow`, `font-too-small`)
- `canvas-overflow`: an element sits outside the viewBox — enlarge
  `canvas.width/height` or shorten the overflowing label.
- `font-too-small`: any text < 12 px — raise the source font size in the
  model (axis ticks are the usual culprits; drop tick count or widen the
  panel rather than shrinking ticks).

## Verification problems

### `quote-not-in-source`
- Signature: quote for element 'x' not found in <file>.
- Meaning: the quote is not a verbatim substring (rewording, wrong page,
  paraphrase).
- Remedy: re-copy the sentence from the material exactly (watch hyphens,
  en-dashes, %, unit spacing). This check existing is the point — a number
  you cannot quote is a number you may not draw.

### `value-not-in-quote`
- Meaning: the drawn number is derived (difference, mean, unit conversion)
  rather than stated.
- Remedy: extend the quote to include the inputs and describe the
  derivation in `encoding.detail`, or replace with the stated value. Derived
  numbers are legitimate only when the derivation is recorded.

### `missing-source` / `no-source` / `no-quote` / `no-file` / `no-locator`
- Remedy: attach a complete `source` object (file + locator + quote) to the
  element, or move the element to `notes`/caption. Structural elements
  (reading-order arrows, axis ticks) are exempt via kind `layout`/`axis`.

### `grayscale-collision` / `low-contrast-fill`
- Meaning: two series colours, or a fill vs. the white background, are hard
  to separate in grey scale.
- Remedy: pick series colours with different lightness (the built-in
  Okabe–Ito order is chosen for this); if the collision is intrinsic
  (e.g. mandated brand colours), keep distinct value labels on every bar
  and record the limit.

## result.json problems

### A contract field has no natural producer
- Remedy: leave it `null` — the scaffold keeps it explicit with a reason.
  Do not stuff an unrelated object into it and do not reshape other fields'
  values; reviewers read shape mismatches as fabrication.

### Matcher paired a field with the wrong content (level-3 match)
- Signature: `_match_notes` flags `matched by description keywords`.
- Remedy: add the correctly-named key to `values.json` and re-run
  `make_result.py --stage final`; level-1 exact names always win.

### Everything failed mid-run
- The Step-0 scaffold is already in `/app/output/result.json` with honest
  nulls. Fill `status: partial`, describe the failure in `uncertainty`,
  attach whatever artifacts exist (the SVG usually survives). A documented
  partial beats an invented complete.
