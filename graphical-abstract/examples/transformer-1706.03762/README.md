# Example: graphical abstract of "Attention Is All You Need"

This example is derived entirely from a real published paper. It demonstrates
the full skill workflow on genuine material: source text, a complete
`figure_model.json` with verbatim quotes and locators, and the commands that
render it.

## Provenance

| Item | Value |
|---|---|
| Title | Attention Is All You Need |
| Authors | Vaswani et al. |
| arXiv id | 1706.03762 (v7, last revised 2 Aug 2023) |
| DOI | 10.48550/arXiv.1706.03762 |
| Abstract page | https://arxiv.org/abs/1706.03762 |
| Local material file | `material_abstract.md` (verbatim abstract, unmodified) |
| Material sha256 | see `SHA256SUMS.txt` |
| Fetched | 2026-11-20, from https://export.arxiv.org/abs/1706.03762 |

The material file contains the abstract exactly as published; every quote
used in `figure_model.json` is a verbatim substring of it, and every locator
is `Abstract, sentence N` (sentences counted from 1 in the material file).

## Run it

```bash
# 1. quote-verify + build (from the skill root)
python scripts/build_figure.py \
  --model examples/transformer-1706.03762/figure_model.json \
  --outdir /app/work/example-out \
  --sources examples/transformer-1706.03762/sources.json

# 2. verify
python scripts/check_figure.py --outdir /app/work/example-out \
  --sources examples/transformer-1706.03762/sources.json
```

`sources.json` maps the material file to its extracted text so the checker
can verify that every quote is really present in the material.

## What the figure shows

Reading order: question (can attention replace recurrence/convolution in
sequence transduction?) → method (the Transformer: encoder-decoder using
attention only) → results (28.4 BLEU EN→DE, 41.8 BLEU EN→FR, trained 3.5
days on eight GPUs) → conclusion (generalizes to English constituency
parsing with large and limited training data).
