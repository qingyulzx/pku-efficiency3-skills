# Uncertainty and downgrade policy (references/uncertainty-policy.md)

**Core rule: a pathway figure is a mechanism claim. When the source does not
state something, the figure must show that it is not stated — never fill the
gap with a plausible guess.**

## 1. Direction not stated → undirected edge

- Source says "X interacts with Y", "X is associated with Y", "X–Y complex"
  without stating who acts on whom → `directed: false`,
  `type: binding` or `unspecified_interaction`. The figure renders **no
  arrowhead** and the legend states "no arrowhead = direction not stated in
  source".
- The validator searches every `directed: true` edge's evidence quote for a
  directional cue (activates / inhibits / phosphorylates / promotes /
  recruits / blocks / 激活 / 抑制 / 促进 / 阻断 ...). No cue found → error
  E-DIR-01; you must either supply a quote that states direction or downgrade
  to `directed: false`.
- Guessing direction from "sounds right biologically" (e.g. assuming a kinase
  phosphorylates everything it binds) is forbidden even when you are confident.
  If background knowledge strongly suggests a direction, put it in the edge
  `notes` and in result.json uncertainties — the canvas stays source-faithful.

## 2. Interaction type not stated → unspecified_interaction

- "A regulates B" without mechanism → do not pick activation; use
  `unspecified_interaction` with the quote, unless "regulates" is explicitly
  qualified ("positively regulates" → activation).

## 3. Compartment not stated → unspecified band

- The renderer has an `unspecified` compartment band (bottom, grey). Entities
  whose location the material does not state go there with a note in
  uncertainties — not silently into cytoplasm.

## 4. Indirect evidence → dashed line

- A statement made in a different context, via an intermediate, from another
  species/cell type, or from a figure caption of a *different* figure than
  the one being reproduced → `confidence: "indirect"`, rendered dashed, listed
  in the legend ("dashed = inferred/indirect evidence").
- Direct verbatim support → `confidence: "direct"`, solid.

## 5. Conflicting statements

- If the material states both X→Y activation and X–Y inhibition (different
  contexts, mutants, or figure panels): draw **both** edges with distinct
  notes, or draw the one the task targets and record the conflict in
  uncertainties. Never average them into one ambiguous edge.

## 6. Missing numeric data on the canvas

- If the task asks for data-encoded visuals (node color = fold change) but the
  material lacks the numbers: draw the topology correctly, mark the mapping as
  "data not provided in source" in result.json (field = null + reason), and add
  a legend note "quantitative mapping not shown: data absent from source".
- Never fabricate expression values, p-values, or fold-changes. Numbers that
  appear on the canvas must exist verbatim in the source (page/line recorded).

## 7. Entity ambiguity

- A name that could be two different entities (e.g. "p38" the kinase vs an
  unrelated protein, or gene vs protein of the same symbol): choose the reading
  the source context supports, record the alternative in `synonyms` and add an
  uncertainty note. If context does not disambiguate, stop and flag it in
  result.json instead of drawing.

## 8. How uncertainties reach result.json

Every downgrade above appends one entry to the model's `uncertainties` array
(`{"item": "...", "reason": "...", "handling": "undirected" | "indirect" |
"unspecified-compartment" | "flagged" | "null-field"}`), which the finalize
step copies into result.json. An empty uncertainties list must mean "no
uncertainty found", not "uncertainties were not collected".
