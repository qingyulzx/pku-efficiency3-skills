# Source excerpt — example case: RAS–MAPK signaling

Real published source for this example (CC BY 4.0, text reused under the
license; bracketed reference numbers stripped):

- **Article**: Brown MA, Ried T. "Shifting the Focus of Signaling
  Abnormalities in Colon Cancer." *Cancers* 2022;14(3):784.
- **DOI**: https://doi.org/10.3390/cancers14030784
- **PMC**: https://pmc.ncbi.nlm.nih.gov/articles/PMC8834070/ (PMCID PMC8834070,
  PMID 35159051)
- **License**: CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)
- **sha256 of this excerpt file**: see provenance.json (computed at packaging
  time; recompute with `sha256sum source-excerpt.md`)

The quotes below are verbatim from the article's Section 3 (RAS Signaling) and
the Figure 2 caption, as fetched from PMC on 2026-11-20. Locations use the
article's section numbering; paragraph numbers count within the section.

## §3.1 RAS Signaling Receptors and Ligands

> RAS signaling relies on the actions of the Epidermal Growth Factor
> Receptors (EGFR), which are Receptor Tyrosine Kinases (RTKs), for signal
> transduction through the plasma membrane.

> The major RAS ligands in the intestinal epithelium are EGF and TGF-α.

> EGF–EGFR binding results in EGFR dimerization into homo or heterodimers
> with other members of the EGFR family, such as ERBB2.

## §3.2 RAS Signal Transduction

> Oligomerization of the EGFR family of receptors results in
> transphosphorylation of the dimerized, cytoplasmic receptor domains.

> The phosphorylated residue Y1068 on EGFR forms a docking site for GRB2, via
> its SH2 domain, which recruits its binding partner, SOS, a RAS-specific
> Guanine nucleotide Exchange Factor (GEF).

> SOS activates the small guanosine triphosphatase (GTPase) RAS by inducing
> the exchange of GDP for GTP.

> When activated (bound by GTP), RAS activates a variety of downstream
> processes involving PI3K, RALGDS, and PLCε, as well as the protein
> serine/threonine kinase RAF.

> Once activated by RAS, RAF phosphorylates, and by doing so activates, the
> mitogen-activated protein kinase kinase, MEK.

> Subsequently, MEK phosphorylates ERK on its activation loop.

> A fraction of ERK is transported to the nucleus following activation,
> resulting in the phosphorylation of both cytosolic and nuclear substrates.

> Within the nucleus, ERK phosphorylates a variety of transcription factors,
> including MYC and members of the ETS family, such as ELK1.

> Phosphorylation of ELK1 allows it to form a ternary complex with serum
> response factor (SRF) at serum response elements (SREs).

> A notable transcriptional target of ELK1 is *FOS*, a member of the AP-1
> transcription factor.

## §3.3 Inactive RAS Signaling

> RAS proteins contain intrinsic GTPase activity and gradually exchange GTP
> for GDP, leading to their own inactivation, a process greatly facilitated
> by the GTPase-activating proteins (GAPs).

## Figure 2 caption (abridged; the RAS ON panel)

> EGF binds to EGFR with 2:2 stoichiometry at the plasma membrane. EGF
> binding results in dimerization of the receptors, and their
> autophosphorylation. GRB2 binds to the phosphorylated tyrosine on EGFR via
> its SH2 domain, and subsequently recruits the rasGEF, SOS. SOS catalyzes
> the exchange of GDP for GTP on RAS, activating it. Activated RAS then
> activates RAF, which phosphorylates MEK, which, in turn, phosphorylates
> ERK. [...] The complex then drives the expression of growth factor
> response genes, such as *FOS*, a component of the AP-1 transcription
> factor.

## Note on gene/protein typography

The source italicizes gene symbols (*FOS*) and keeps protein names upright
(EGFR, GRB2, SOS, RAS, RAF, MEK, ERK, ELK1, SRF). The example model preserves
this distinction: `FOS` is typed `gene` (rendered with an italic label),
everything else is typed `protein`/`receptor`/`molecule`.
