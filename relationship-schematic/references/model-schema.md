# Figure model schema (model.json)

The figure model is the single source of truth for a schematic. The Agent
extracts it from the source material (paper, case description, data table);
every script downstream (make_schematic, model_check, verify_svg, export_svg,
edit_svg) reads it. Nothing is drawn that is not in the model, and everything
in the model carries a verbatim evidence quote, so any element in the final
figure can be traced back to the source text.

## Top-level fields

| field | type | required | meaning |
|-|-|-|-|
| `title` | string | recommended | figure title drawn at the top |
| `figure_label` | string | optional | e.g. "Figure 3a" drawn above the title |
| `canvas_width` | number | optional | requested width in svg units (default 900). If content needs more, the canvas is widened (never clipped) and a `canvas_expanded` warning is emitted |
| `physical_width_mm` | number | optional | if set, svg width/height carry physical mm units for print |
| `entities` | array | yes | see below |
| `relations` | array | yes | see below |
| `groups` | array | optional | containment boxes; see below |
| `legend_extra` | array | optional | extra legend entries `{key, meaning}` (e.g. colour semantics) |

## Entity

```json
{
  "id": "APC",
  "label": "APC",
  "type": "protein",
  "evidence": {
    "quote": "the degradation complexes consisting of adenomatous polyposis coli (APC), glycogen synthase kinase-3β (GSK-3β), Axin, casein kinase 1(CK1)",
    "locator": "Background, paragraph 1",
    "source": "Wang et al. 2021, doi:10.1186/s40364-021-00323-7"
  }
}
```

- `id` — stable token used by relations/groups and in SVG element ids.
- `label` — what is drawn inside the node (can wrap to multiple lines).
- `type` — small subtitle under the label (e.g. "ligand", "receptor",
  "complex"). Drives nothing semantic; useful for readers.
- `evidence` — **mandatory in spirit**: a missing quote triggers
  `entity_no_evidence` (warn) — the entity is drawn but flagged in
  result.json as unverifiable.
- `color` — optional explicit `#rrggbb`; otherwise derived from `type`.

## Relation

```json
{
  "id": "r1",
  "from": "Wnt",
  "to": "Frizzled",
  "type": "binds",
  "direction": "A_to_B",
  "label": "",
  "direct": true,
  "evidence": {
    "quote": "Wnt ... The ligands of the frizzled family",
    "locator": "Table 1, row Wnt",
    "source": "Wang et al. 2021, doi:10.1186/s40364-021-00323-7"
  }
}
```

- `from` / `to` — entity ids or group ids. **`from` is the semantic source of
  the statement** ("A inhibits B" ⇒ from=A, to=B, type=inhibits), NOT a
  drawing hint. The renderer decides geometry.
- `type` — one of the relation types in `symbols/symbols.json`:
  `activates` `inhibits` `binds` `modifies` `transports` `indirect`
  `precedes` `contains` `parallels`.
- `direction` — `A_to_B` (statement reads from→to), `B_to_A` (statement
  reads to→from; drawn with the arrow from `to` towards `from`),
  `bidirectional`, or `unknown`. Unknown direction is drawn dashed with a `?`
  label and flagged `direction_uncertain` — never guessed.
- `label` — optional text on the edge (e.g. `"Ub"` for ubiquitination, `"P"`
  default for modifies).
- `direct` — false ⇒ rendered as `indirect`-style dashed even for activating
  statements, when the source only supports an indirect effect.
- `evidence` — **mandatory**: a relation without a verbatim quote is an
  ERROR; the model is refused. A relation that cannot be quoted cannot be
  verified and must not be drawn.

## Group (containment)

```json
{
  "id": "destruction_complex",
  "label": "β-catenin destruction complex",
  "members": ["APC", "GSK3B", "Axin", "CK1", "BTRCP"],
  "evidence": { "quote": "...", "locator": "...", "source": "..." }
}
```

- Groups may nest (a member can be another group id).
- Containment is drawn as a nested rounded box, NEVER as an edge or as
  side-by-side nodes. A `contains` relation whose target is in no group fails
  verification (`contains_without_group` / `relation_coverage` fail).
- `parallels` relations assert co-listing without interaction; they are
  rendered by adjacency and skipped by edge verification on purpose.

## Validation findings (model_check / make_schematic refuse list)

errors (refuse to draw): `entity_missing_id`, `duplicate_entity_id`,
`group_missing_id`, `duplicate_group_id`, `dangling_group_member`,
`group_self_containment`, `relation_missing_id`, `duplicate_relation_id`,
`dangling_relation_endpoint`, `unknown_relation_type`, `invalid_direction`,
`relation_no_evidence`.

warns (draw, but flag): `entity_no_evidence`, `id_needs_sanitising`,
`empty_group`, `direction_uncertain`, `self_loop`, `cycle_in_rank_graph`,
`canvas_expanded`, `contains_without_group` (also a verify fail),
`cycle_broken_for_layout`, `group_member_not_laid_out`,
`edge_endpoint_missing`.
