# Symbol conventions (semantic drawing grammar)

Every visual token in the schematic carries exactly ONE meaning, shared by
the renderer, the verifier and the reader. The machine-readable definition
lives in `symbols/symbols.json`; this document is the human-readable contract
and the rationale: each convention exists because its violation is one of the
observed failure modes of generic image generation.

## Edge tokens

| token | meaning | drawn as |
|-|-|-|
| solid line | directly supported interaction | `stroke-dasharray` absent |
| dashed line (`7 5`) | indirect / speculative / inferred, or direction unknown | `stroke-dasharray="7 5"` |
| filled triangle arrowhead at the END | activation, promotion, causal effect, process order, transport direction — **points from source to target** | `marker-end="url(#mk-arrow)"` |
| perpendicular bar at the END | inhibition / repression / blocking — **the bar sits AT the inhibited target** | `marker-end="url(#mk-bar)"` |
| no end marker | non-directional association (binds) | — |
| both ends marked | bidirectional interaction | `marker-start` + `marker-end` |

### Why these conventions

| classic failure mode | convention that prevents it | how it is enforced |
|-|-|-|-|
| inhibition drawn as activation | inhibition = bar, never a triangle | `marker_semantics` check in verify_svg.py |
| upstream/downstream reversed | arrowhead must sit geometrically near the semantic target | `marker_geometry` check compares the arrow tip position with both endpoint boxes |
| indirect evidence drawn as direct | dashed = not directly demonstrated | `direct: false` ⇒ dashed; `direction: unknown` ⇒ dashed + `?` |
| containment drawn as juxtaposition | containment = nested box | `containment` check: member box must lie inside the group box |
| juxtaposition misread as interaction | co-listed items get NO edge | `parallels` renders by adjacency; verifier skips it explicitly |
| relation with no source | every relation needs a verbatim quote | `relation_no_evidence` is a refuse-to-draw error |

## Relation type → visual mapping

| relation type | line | end marker | default edge label |
|-|-|-|-|
| `activates` | solid | arrow | — |
| `inhibits` | solid | bar | — |
| `binds` | solid | none | — |
| `modifies` | solid | arrow | `P` (phosphorylation unless overridden) |
| `transports` | solid | arrow | cargo name via `label` |
| `indirect` | dashed | arrow | — |
| `precedes` | solid | arrow | step number via `label` |
| `contains` | — | — | nested box (no edge) |
| `parallels` | — | — | adjacency (no edge) |

## Node and canvas tokens

- Node fill colours come from a fixed 10-colour pastel palette keyed by
  entity `type`; stroke is always the same dark ink. Colour is decorative
  grouping, never a semantic claim — semantics live on the EDGES, so a
  grayscale print of the figure loses nothing.
- Group (containment) boxes: light grey rounded rect behind their members,
  label at the top-left.
- Every legend entry is generated from the relation types actually drawn;
  there is no legend item without a drawn type and no drawn type without a
  legend item (`legend_coverage` check).

## Traceability tokens (machine-readable)

Each `<g>` in the SVG carries `id` plus `data-*` attributes:

- `node-<id>`: `data-entity-id`, `data-label`, `data-type`,
  `data-evidence-quote`, `data-evidence-locator`, `data-evidence-source`
- `edge-<id>`: `data-relation-id`, `data-from`, `data-to`, `data-type`,
  `data-direction`, plus the same three `data-evidence-*` attributes; an
  invisible `data-role="edge-axis"` path records the straight axis
  start→arrow-tip used by the geometric direction check
- `group-<id>`: `data-group-id`, `data-label`, `data-evidence-*`

This means a reviewer (human or LLM judge) can read any element of the
drawing and recover the exact sentence in the source that justifies it —
including inside the exported PDF/PNG pipeline, because the SVG is the
master source.

## Editing rules (source-preserving)

- Permitted local edits (edit_svg.py): relabel a node, recolour a node,
  change an edge's relation type, change an edge label, change the title,
  delete an unattached element. Every op requires a `reason`; untouched
  elements are byte-compared and reported as `preserved`.
- REFUSED by design: flipping an edge's direction in place (the arrow
  geometry is layout-derived; flipping only the attribute would draw a lying
  arrow — edit the model and re-render), deleting a node with edges attached.
