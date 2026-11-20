# Layout conventions and the model.json schema (references/layout-conventions.md)

## model.json schema (v1.0.0)

```jsonc
{
  "case_id": "string, copied from /input/case.json",
  "title": "figure title",
  "scenario": "generate | edit",
  "model_version": "1.0.0",
  "compartments": [
    // ordered bands; rank = vertical order (0 = top)
    {"id": "extracellular", "label": "Extracellular", "kind": "open|membrane|region|nucleus|organelle|unspecified", "rank": 0}
  ],
  "entities": [
    {
      "id": "EGFR",              // unique, used as SVG node-EGFR
      "label": "EGFR",           // canvas label
      "type": "protein|receptor|gene|rna|complex|molecule|cell|family",
      "compartment": "membrane", // must exist in compartments
      "order": 1,                // pathway order (column); default = first mention
      "sub": "receptor RTK",     // optional small subtitle under the label
      "synonyms": ["ERBB1", "HER1"],
      "x_ref": {"hgnc": "3236"}, // optional authoritative reference
      "source": {"loc": "§3.2 ¶1", "quote": "…verbatim…"}
    }
  ],
  "edges": [
    {
      "id": "e1",
      "source": "EGFR",          // entity id, or compartment id when target_kind=compartment
      "target": "GRB2",
      "target_kind": "entity",   // or "compartment" (for translocation)
      "type": "activation|inhibition|binding|phosphorylation|dephosphorylation|ubiquitination|methylation|acetylation|transcriptional_regulation|translocation|complex_formation|conversion|unspecified_interaction",
      "directed": true,
      "sign": "positive|negative|neutral|by-sign",
      "confidence": "direct|indirect",
      "evidence": {"loc": "§3.2 ¶1", "quote": "…verbatim…"},
      "notes": "optional"
    }
  ],
  "uncertainties": [
    {"item": "edge e12", "reason": "direction not stated", "handling": "undirected"}
  ]
}
```

Rules the validator enforces:
- ids unique; edge endpoints exist; types/enums valid; `directed: true`
  requires a directional cue in the evidence quote; `confidence: indirect`
  allowed on any type; transcriptional_regulation targets a `gene` node.

## Layout algorithm (what render_svg.py does)

1. **Vertical axis = compartments.** Bands stack by `rank`. Heights adapt to
   the number of entities; minimum band height keeps labels readable.
   The membrane band is a thin double-line band; the nucleus is a double
   bordered rounded region; `unspecified` renders last (bottom, grey).
2. **Horizontal axis = pathway order.** Entities get a column from `order`
   (default: order of first mention in `entities`/`edges`); multiple entities
   sharing a compartment stack vertically within the band at their column,
   in `order` then id sequence.
3. **Edges**:
   - different compartments: line from the source's band to the target's band
     (source bottom / target top edge anchors);
   - same compartment, forward: horizontal line left→right;
   - same compartment, backward (feedback): quadratic Bézier dipping below
     the band, so the forward cascade stays a straight read;
   - translocation: hollow arrowhead to the compartment band edge.
4. **Badges** (P, Ub, ...): drawn as a small circle attached to the target
   node's side; the edge terminates at the badge.
5. **Node sizing**: label length drives box width (estimated 0.62 em per
   character + padding); subtitle wraps under the label. If a single label
   exceeds the band width the renderer widens the canvas; if the canvas
   exceeds the max (default 2200×1700) it warns and suggests splitting into
   panels — it does not silently shrink labels below 11 px.
6. **Legend**: generated from the types actually used (edges, nodes, line
   styles, annotations) — see symbol-semantics.md §6.
7. **Determinism**: same model.json → byte-identical SVG (no timestamps in
   the SVG body), so re-runs are diffable and repeated executions produce
   structure-consistent output.

## Manual layout control

The model accepts optional `"x"`, `"y"` per entity for pinning (values are
column/band hints on a 0–100 scale, still snapped to bands). Use pinning only
when the auto layout demonstrably obscures the mechanism (crossing overload,
feedback hiding); every pinned entity should have a note explaining why.
