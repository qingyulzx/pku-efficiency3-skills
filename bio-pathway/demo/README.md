# Example: RAS–MAPK mechanism diagram (worked run)

**Everything in this directory is EXAMPLE material** demonstrating one full
run of the skill chain. It is not a platform case result.

- `source-excerpt.md` — the real source text with verbatim quotes + locations
  (Brown & Ried 2022, Cancers 14:784, doi:10.3390/cancers14030784, CC BY 4.0;
  see `provenance.json` for the sha256).
- `model.json` — the extracted mechanism model (12 entities, 13 edges,
  4 logged uncertainties), built by applying `references/naming-rules.md` and
  `references/uncertainty-policy.md` to the excerpt.
- `example.svg` — the rendered output (example output of
  `scripts/render_svg.py`), deterministic: the same model always renders
  byte-identically.

## Reproduce

```bash
python scripts/validate_model.py --model examples/ras-mapk-case/model.json
python scripts/render_svg.py --model examples/ras-mapk-case/model.json --out /tmp/example.svg
python scripts/export_assets.py --svg /tmp/example.svg --outdir /tmp \
    --model examples/ras-mapk-case/model.json
python scripts/verify_outputs.py --model examples/ras-mapk-case/model.json \
    --svg /tmp/example.svg --exports /tmp/example.png
```

Expected: validation valid (0 errors), verification passed (all read-back,
legend, overflow and export checks), and the rendered SVG matches
`example.svg` byte-for-byte.

## What this example demonstrates

1. **Typed entities** — protein vs gene (*FOS* is a gene node with italic
   label; EGFR is a receptor anchored on the membrane band; EGF is a
   molecule in the extracellular band).
2. **Typed, evidenced edges** — activation (SOS→RAS), inhibition
   (rasGAP⊣RAS), phosphorylation with P badges (RAF→MEK, MEK→ERK, ERK→ELK1),
   undirected binding (EGF–EGFR, GRB2–SOS: "recruits" is assembly order,
   not regulatory direction), translocation (ERK→nucleus, hollow arrow),
   transcriptional regulation onto a gene node (ELK1→*FOS*).
3. **Uncertainty handling** — family-level names flagged; undirected
   downgrades logged; the partial ERK transport noted.
4. **Traceability** — every SVG element id (`node-*`, `edge-*`) maps to a
   model entry with a verbatim quote and a re-findable location.
