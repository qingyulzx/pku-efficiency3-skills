# Pathway symbol semantics (references/symbol-semantics.md)

This is the visual grammar used by every figure the biopathway skill produces. The
rules below are the standard conventions of signaling-pathway figures in molecular
biology journals; deviating from them silently is treated as a scientific error, not
a style choice. Machine-readable specs live in `edge-types.json`; this document
explains the reasoning so an agent (or human) can apply them to cases the spec
does not enumerate.

## 1. Encoding channels are orthogonal — never overload one channel

A pathway figure has a small number of visual channels. Assign each semantic
dimension to exactly one channel:

| Semantic dimension | Visual channel | Values |
|---|---|---|
| regulation direction/sign | **arrowhead style** | filled arrow = positive/activation; blunt T-bar = negative/inhibition; no head = no direction stated |
| evidence directness | **line solidity** | solid = stated directly in source; dashed = inferred/indirect |
| modification type | **letter badge** | P (phosphorylation), Ub (ubiquitination), Me, Ac |
| transport | **hollow arrowhead** | open arrow into a compartment |
| entity class | **node shape + label style** | see §3 |
| compartment | **background region** | bands with membrane/nucleus styling |

Two classic mistakes this table forbids:

- Using dashed lines to mean "indirect interaction" in one figure region and
  "weak interaction" in another. Pick one meaning per channel per figure.
- Using red/green to mean both "activation/inhibition" and "expression
  up/down". If color encodes data (e.g. fold-change), it must NOT also encode
  regulation sign — sign is the arrowhead's job.

## 2. Edge semantics (detail)

- **Activation** (`activation`): solid line, filled arrowhead. Requires the
  source to state increase of activity, level, or transcription.
- **Inhibition** (`inhibition`): solid line ending in a **blunt T-bar**
  (⊥), never a pointed arrowhead. Includes enzymatic inactivation, degradation
  promotion, sequestration-away-from-target, and blocking statements
  ("DKK ... binding LRP and **blocking** WNT binding").
- **Binding / recruitment** (`binding`): plain line, **no arrowhead**. Binding
  is not inherently directional; "recruits" gives an assembly order, not a
  regulatory direction — still render undirected unless the source states a
  downstream effect.
- **Phosphorylation** (`phosphorylation`): arrowhead terminating at a small
  **P badge** attached to the target node. If the source states the
  phosphorylation *inhibits* the target, use `dephosphorylation`-style T-bar
  plus crossed-P badge and explain in the edge note — do not silently draw a
  plain activation arrow.
- **Ubiquitination** (`ubiquitination`): arrowhead + **Ub** badge; usually
  implies proteasomal degradation, which the note should state if the source
  does.
- **Transcriptional regulation** (`transcriptional_regulation`): edge whose
  target is a **gene** node (italic label). Arrowhead = transactivation,
  T-bar = transrepression. The gene node is the DNA locus/target-gene
  rectangle, not the protein.
- **Translocation** (`translocation`): **hollow (open) arrowhead** pointing
  into the destination compartment, target = compartment id. Kept visually
  distinct from dashed "indirect evidence" so the two never collide.
- **Complex formation** (`complex_formation`): plain lines from member nodes
  into a hexagonal complex node. Do not fan a complex out as pairwise binding
  edges between all members — that asserts pairwise affinities the source may
  not state.
- **Unspecified interaction** (`unspecified_interaction`): plain line with a
  "?" annotation. Use when the source only says "interacts with /
  associated with". **Guessing a typed arrow is the single worst error in
  this domain** — see uncertainty-policy.md.

## 3. Node semantics

| Type | Shape | Label style | Notes |
|---|---|---|---|
| protein | rounded rectangle | upright | |
| receptor | rounded rectangle, anchored on membrane band | upright | membrane-anchored; drawing it free-floating in cytoplasm is a correctness error |
| gene | rectangle | **italic** | target of transcriptional regulation |
| rna | rectangle | italic | |
| complex | hexagon | upright, members listed in note | one node per named complex (e.g. "Destruction complex") |
| molecule | circle | upright | ligands, metabolites, drugs |
| cell | ellipse | upright | cell types |
| family | rounded rect, dashed grey outline | upright | e.g. "MAPK", "TCF/LEF" — prefer member nodes when the source names members |

## 4. Compartment semantics

- Compartments are background **bands** stacked vertically; every node sits in
  exactly one.
- **Plasma membrane**: band rendered as a double line. Receptors anchor on it;
  transmembrane topology (extracellular vs cytoplasmic domain) is implied by
  the node straddling the band.
- **Nucleus**: rounded region with a double border, enclosing nuclear entities
  and target genes.
- **Extracellular**: top region above the membrane, containing ligands.
- Default stack order (top → bottom): extracellular → membrane → cytoplasm →
  nucleus. Organelles (ER, Golgi, mitochondrion) render as labeled sub-regions
  inside cytoplasm when the mechanism needs them (e.g. WNT secretion).
- An entity whose location the source does not state goes in an **unspecified**
  band with a note — never silently assigned to cytoplasm.

## 5. Layout conveys mechanism

- Signal flow runs **top-to-bottom and left-to-right**: ligand top-left,
  receptor on the membrane, cytoplasmic cascade left-to-right in pathway order,
  nuclear events / target genes at the bottom right.
- Feedback edges (target upstream of source) route as curves below their band,
  so the forward cascade stays readable as a straight line.
- Parallel branches occupy separate columns at the same rank; a fork or merge
  must be visible as such, not hidden by overlapping lines.
- Ranks come from the mechanism (topological order), not from text order of
  first mention — although first mention is the default when the mechanism is
  linear.

## 6. Legend contract

The legend is generated from the model, listing every edge type, node type,
line style and annotation actually **used** in that figure. A legend entry for
an unused type is a bug (implies a mapping that does not exist); a used type
missing from the legend is a worse bug (unexplained semantics). The verify
script checks both directions (see verify_outputs.py).

## 7. Traceability on the canvas

Every node and edge element carries `id="node-<ID>"` / `id="edge-<ID>"`, a
`data-source-loc` attribute (where in the source material it comes from), and
the SVG embeds a `<desc>` block with the full entity/edge evidence table, so
the figure remains auditable even when separated from model.json. If a reader
cannot answer "which sentence is this arrow based on?", the figure fails its
purpose as a challengeable mechanism statement.
