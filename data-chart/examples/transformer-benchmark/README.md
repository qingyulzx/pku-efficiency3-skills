# Example: Transformer WMT'14 BLEU benchmark (grouped bar)

This is a worked example of the full pipeline on real published data. It is
an example derived from the cited paper - it is NOT an official test case
result.

## Source (real paper)

- Paper: Vaswani, A. et al. "Attention Is All You Need", NeurIPS 2017.
- arXiv: `1706.03762v7` (latest version, fetched 2026-11-20)
- Stable URL: https://arxiv.org/abs/1706.03762
- PDF used for hashing: https://arxiv.org/pdf/1706.03762 (2,215,244 bytes)
- PDF sha256:
  `bdfaa68d8984f0dc02beaca527b76f207d99b666d31d1da728ee0728182df697`

## Verbatim data quote and location

Table 2, "The Transformer achieves better BLEU scores than previous
state-of-the-art models on the English-to-German and English-to-French
newstest2014 tests at a fraction of the training cost." (Section 6.1 Machine
Translation, page 8 of the NeurIPS version; Table 2 rows):

> | Model | BLEU EN-DE | BLEU EN-FR | Training Cost (FLOPs) EN-DE | EN-FR |
> | ByteNet [18] | 23.75 | | |
> | GNMT + RL [38] | 24.6 | 39.92 | 2.3·10^19 | 1.4·10^20 |
> | ConvS2S [9] | 25.16 | 40.46 | 9.6·10^18 | 1.5·10^20 |
> | MoE [32] | 26.03 | 40.56 | 2.0·10^19 | 1.2·10^20 |
> | GNMT + RL Ensemble [38] | 26.30 | 41.16 | 1.8·10^20 | 1.1·10^21 |
> | ConvS2S Ensemble [9] | 26.36 | 41.29 | 7.7·10^19 | 1.2·10^21 |
> | Transformer (base model) | 27.3 | 38.1 | 3.3·10^18 | |
> | Transformer (big) | 28.4 | 41.8 | 2.3·10^19 | |

Empty table cells (ByteNet EN-FR, Transformer base EN-FR cost, Transformer
big EN-FR cost) are `null` in the spec - not zero, not interpolated. This
example deliberately includes empty cells to exercise the missing-value path.

Also quoted from the abstract, for context on the single-model result:

> "our model establishes a new single-model state-of-the-art BLEU score of
> 41.8"

## Files

- `spec.json` - chart spec for a grouped bar of EN-DE and EN-FR BLEU across
  8 models (fills nulls where the paper's cell is empty)
- `run.md` - exact commands and the outputs they produced (marked as example
  outputs)

## Reproduce

```
python scripts/chartgen.py --spec spec.json \
    --style references/styles/nature.json --outdir out/
python scripts/verify_svg.py --svg out/transformer_wmt_bleu.svg \
    --glyphs out/transformer_wmt_bleu.glyphs.json \
    --style references/styles/nature.json
```

With matplotlib 3.11 this yields: 3 exports ok, 16 glyphs (2 null cells
skipped), all bar read-backs within tolerance (see run.md; numbers there are
example outputs from the author's environment).
