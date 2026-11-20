# Exception playbook

Real failure modes of this pipeline, the detection signal, and the honest
disposition. Rule zero: never invent results — when something cannot be done,
deliver what exists and mark the gap in result.json (`uncertainty` /
`unanswered` with a reason).

## 1. Material has no conclusion / results section

- Signal: outline drafting cannot fill `result` roles from the material.
- Disposition: state the finding on the limitation slide ("材料未含结论，
  本页为方法含义的推断，已标注"), record in `decisions` with action
  `inferred`, and add an `uncertainty` entry. Do not invent results.

## 2. Too many figures for the page budget

- Signal: `assembly-report.json` budget check / outline slide count exceeds
  `target_slides`.
- Disposition (cut priority, in order):
  1. merge secondary figures into one "其他结果" page (crops at thumbnail
     size, full versions in backup pages);
  2. keep the single main-result figure on its own page;
  3. move methodology-detail figures to backup pages after the closing slide;
  4. only then cut content, lowest-evidence first.
- Record every cut in `decisions`.

## 3. Template layout does not match the planned page

- Signal: `pick_layout` reports `fallback:nearest`, or assembly warnings show
  "no body placeholder".
- Disposition: re-map the page to the hint the template actually supports
  (e.g. two_content instead of image_content when no picture placeholder
  exists — the image then shares the body region). Never edit the template's
  layouts/masters during generation.

## 4. Fonts missing at render time

- Signal: `render_check.py` reports `fonts_declared` containing faces absent
  from the system (font-discovery in the eval container).
- Disposition: keep the template fonts in the .pptx (the deliverable must
  stay editable and template-faithful); note in result.json `uncertainty`
  which fonts were substituted in the PDF preview. Do not rewrite the deck
  to system fonts just to make the preview pretty.

## 5. Figures are bitmaps with no extractable data

- Signal: the material's figure is a raster image; no table/numbers.
- Disposition: cite the original figure image (`insert_image`) with its
  verbatim caption; do NOT redraw curves from eyeballed values. Record
  `{"action": "cited_original", "reason": "bitmap figure, no data"}` in
  `decisions`.

## 6. Render fails outright (no LibreOffice / timeout)

- Signal: `render_check.py` exits non-zero with `render_status: failed`.
- Disposition: keep the .pptx + notes as the deliverable, write the failure
  into result.json honestly (`render_preview: null` + reason), and flag the
  deck for manual export. Never fake a PDF.

## 7. Slide budget exceeded after assembly

- Signal: `assembly-report.json` `budget.within_budget: false`.
- Disposition: apply playbook #2 priorities, regenerate the outline (never
  delete slides post-hoc on the generated deck — fix the outline and
  re-assemble so the deck and the decisions log stay consistent).

## 8. Edit instruction touches content the source deck does not have

- Signal: `resolve_target` LookupError / inventory shows no matching
  placeholder.
- Disposition: fail the op loudly (edit_deck exits non-zero with the failed
  op in edit-report.json), re-read the inventory, and either retarget
  (`idx:`/`name:`) or `add_slide`. Do not silently skip.

## 9. Preservation check fails after editing

- Signal: untouched slides not even structurally identical, or
  masters/layouts digests changed.
- Disposition: treat as a regression — the edit leaked outside its scope.
  Re-run with a minimal op set; if a requested op inherently rewrites the
  whole deck (e.g. replace_text on a deck where the target body shares a
  part), surface it in result.json instead of hiding it.

## 10. Edit intent is actually a full rebuild

- Signal: instruction reorders most pages and rewrites most content.
- Disposition: switch to the generation path (new deck from the same
  template), and keep the starting deck as version N-1. Record the route
  decision with its evidence.
