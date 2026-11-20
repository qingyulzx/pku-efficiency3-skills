# Examples

Both examples are derived from ONE real open-access paper (quoted verbatim
under its CC BY 4.0 license, with attribution). They demonstrate the full
chain: `model.json` (evidence-quoted entity/relation table extracted by the
agent from the paper) → `figure.svg` (rendered, verifiable) → exports.

**Source of all quoted material**

> Zhuo Wang, Tingting Zhao, Shihui Zhang, Junkai Wang, Yunyun Chen,
> Hongzhou Zhao, Yaxin Yang, Songlin Shi, Qiang Chen, Kuancan Liu.
> "The Wnt signaling pathway in tumorigenesis, pharmacological targets,
> and drug development for cancer therapy." *Biomarker Research* 2021 9:68.
> doi:[10.1186/s40364-021-00323-7](https://doi.org/10.1186/s40364-021-00323-7)
> PMC8422786. Published open access under CC BY 4.0.

Quotes were taken from the Background section and Table 1/3 of the article
HTML as served by PMC (fetched 2026-11-20). Each `evidence` object inside the
models records the verbatim quote, its locator (section/paragraph or table
row) and this source citation, so every node and edge in the rendered SVG can
be traced back to the paper by a third party (the same information is
embedded in the SVG as `data-evidence-*` attributes).

These are **demonstration outputs marked as examples** — they are not results
of any evaluation case and make no claim to be.

## Example 1 — `wnt-canonical/`

Canonical Wnt/β-catenin signaling: receptor-level bind/inhibit, the
β-catenin destruction complex as a containment group (APC, GSK-3β, CK1, Axin,
β-TrCP), phosphorylation/ubiquitination edge labels (P, Ub), nuclear
translocation, and an indirect (dashed) ligand→TCF/LEF edge. 14 entities,
17 relations (12 drawn edges + 5 containment), 1 group.

## Example 2 — `tankyrase-axin/`

A compact pharmacology module: the tankyrase inhibitor XAV939, PARylation
edges to Axin1/2, direct activation vs dashed indirect inhibition of the
pathway. 5 entities, 6 relations. Shows `modifies` with a custom `PAR` label
and legend extras.

## Reproduce (minimal invocation example)

From the submission root:

```
# 1. validate the evidence-quoted model
python scripts/model_check.py examples/wnt-canonical/model.json

# 2. render the editable layered SVG
python scripts/make_schematic.py examples/wnt-canonical/model.json -o figure.svg

# 3. read the drawing back and verify relation semantics + arrow geometry
python scripts/verify_svg.py examples/wnt-canonical/model.json figure.svg

# 4. export 300-dpi PNG + vector PDF with compliance checks
python scripts/export_svg.py figure.svg -o exports --pdf
```

Expected outcomes: step 1 exit 0 with `status: ok`; step 2 writes a layered
SVG (~26 KB) with `node-*`/`edge-*`/`group-*` groups carrying
`data-evidence-*` attributes; step 3 exit 0 with `status: pass` (only the two
`binds` edges are `skip` for geometric direction, as they carry no arrow);
step 4 exit 0 with PNG (≥300 dpi, white background) and PDF (vector page).

## File inventory (sha256)

| file | sha256 |
|-|-|
| `wnt-canonical/model.json` | `fa2de611ab93d27ac4c8a0548aa5ff71980f5c44f5c576efa09ace0f00240cf3` |
| `wnt-canonical/figure.svg` | `a7100aaae12875a571abf4a177384ea90b8275058e78c42ffeb4d4bb84c959cb` |
| `tankyrase-axin/model.json` | `c23caf9a8decf3e721807e4dfa89ab4528424c4dfca1660ad02796439ac941e4` |
| `tankyrase-axin/figure.svg` | `35c78e143e656875c4e4a074349c2bd4da984fb95d2b4c03d70892b844ecaa32` |

`figure.svg` files are the exact outputs of `make_schematic.py` on the
shipped `model.json` (generator stamp inside the file confirms it).
