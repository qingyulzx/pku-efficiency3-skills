# Entity naming and disambiguation rules (references/naming-rules.md)

Wrong entity naming makes a pathway figure scientifically wrong even when the
topology is right. These rules are applied when building model.json; the
validator enforces the mechanical parts.

## 1. Gene vs protein — the highest-frequency error

- **Human gene symbols**: uppercase, italic — *TP53*, *CTNNB1*, *MYC*.
- **Human protein names**: non-italic, usually the same symbol — p53 (or TP53
  protein), β-catenin, MYC. When the source itself uses one form, follow the
  source; record the other as `synonyms`.
- **Rodent genes**: initial-capital italic — *Trp53*, *Apc*. Mouse/rat protein:
  Trp53/p53 per source. If the organism is not stated, mark it as an
  uncertainty instead of assuming human.
- In model.json the `type` field (`gene` vs `protein`) is authoritative; the
  renderer auto-italicizes `gene` labels, so the figure carries the convention
  even if the label string is identical.
- **Never connect regulatory arrows to a gene node when the source talks about
  the protein** (and vice versa). If a mechanism mentions both ("*MYC*
  deletion rescues..."), create both entities and link them with an explicit
  `transcriptional_regulation`-derived relationship only if the source states
  it.

## 2. Same symbol, two meanings

If one symbol appears in the material as both gene and protein (or as both a
family and a member), give them distinct `id`s (e.g. `MYC` protein vs
`MYC_gene`) and cross-list in `synonyms`. The validator flags duplicate labels
with different types for review.

## 3. Synonyms and legacy names

- Map to the current preferred symbol where the source uses an older one
  (e.g. ERBB1 → EGFR, Wntless/Evi → WLS, TCF7L2 → TCF4 protein). Keep the
  source's spelling as `label` **when quoting**, but use the preferred symbol
  as the node label and record the source spelling in `synonyms` + evidence
  quote, so the reader can trace both.
- Authoritative references for preferred symbols (for the agent to consult
  from its own knowledge, no network needed): HGNC (genenames.org) for human
  genes/proteins; MGI for mouse; UniProt for protein IDs; NCBI Gene for
  cross-species. Record which reference you relied on in the entity's
  `x_ref` field when you normalize a name.

## 4. Families vs members

- "RAS", "MAPK", "ERK", "TCF/LEF", "SMAD" are families/classes. When the
  source names a specific member (*K-RAS*, ERK1/MAPK1, TCF4/TCF7L2, SMAD1),
  the **member** gets the node; the family goes in `synonyms`/notes.
- Use the `family` node type only when the mechanism is genuinely stated at
  family level ("ERK phosphorylates ... transcription factors"). Edges
  attached to a family node are flagged for review: check whether the source
  actually names a member.

## 5. Complexes

- A named complex ("Destruction complex", "FZD–LRP coreceptor", "β-catenin–TCF4
  complex") becomes ONE `complex` node with `members` listed in the note.
  Representing a complex as one box implies the source states the members
  co-exist as a unit; if membership is uncertain, draw members separately and
  use binding edges for the stated pairwise interactions only.

## 6. Species prefixes

- Only add species qualifiers (h/m/r prefixes, "human", "mouse") when the
  material states or clearly implies the species. Mixed-species mechanistic
  statements (mouse data generalized to human) get an uncertainty note.

## 7. Non-gene entities

- Small molecules/ligands (EGF, WNT3A, BMP4) → `molecule`; they are never
  italicized and never gene nodes even though they have gene names too.
- Cell types (intestinal stem cell, Paneth cell) → `cell`.
- Drugs/inhibitors (e.g. "MEK inhibitor") → `molecule` with a note; an
  inhibition edge from an inhibitor node must be supported by the source.
