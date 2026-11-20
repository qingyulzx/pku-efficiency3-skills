# deck-plan.json schema (v1)

The deck plan is the agent-authored single source of truth. The assembler
never invents content; it only places what the plan says.

```jsonc
{
  "case_id": "string",
  "meta": {
    "title": "paper title",
    "source_paper": { "citation": "...", "pages": 15, "sha256": "..." },
    "audience": "from case.json",
    "duration_minutes": 15,
    "max_slides": 10,
    "template": { "path": "...", "note": "optional" }
  },

  "narrative": {                      // the four-element spine, Step 3
    "problem":  { "statement": "...", "evidence": [EV, ...] },
    "method":   { "statement": "...", "evidence": [EV, ...] },
    "results":  { "statement": "...", "evidence": [EV, ...] },
    "limitations": {
      "statement": "...", "evidence": [EV, ...],
      "uncertainty_flag": "optional: mark presenter-inferred caveats"
    },
    "talk_order": ["problem", "core idea", "..."]
  },

  "slides": [
    {
      "index": 1,                     // final slide number
      "role": "title|section|content|two_column|figure",
      "layout": "optional explicit layout name, overrides role_map",
      "edit_slide_index": null,       // 1-based when EDITING a starting deck
      "claim": "one full-sentence claim",
      "title": "short slide title (<= ~60 chars)",
      "subtitle": "title slides only",
      "bullets": [ { "text": "<= 90 chars", "level": 0 } ],
      "left":  { "bullets": [...] },  // two_column only
      "right": { "bullets": [...] },
      "figures": [
        { "paper_ref": "Figure 1", "page": 3,
          "image": "path/to/p3_img0.png",
          "caption_note": "what the figure shows + source" }
      ],
      "caption": "figure caption text under the image",
      "notes": "speaker notes: transitions, emphasis, Q&A backup -- NOT slide text",
      "evidence": [ EV, ... ]         // >= 1 per slide, mandatory
    }
  ],

  "open_issues": [ "honest uncertainties..." ]
}
```

### Evidence object (EV)

```jsonc
{
  "type": "figure|table|section|quote|data",
  "locator": "Figure 1 | Table 2 | Section 3.2 | Abstract",
  "page": 3,
  "quote": "verbatim text from the paper (fix only line-wrapping)",
  "note": "what this evidence supports"
}
```

Rules:
1. `quote` is verbatim from `paper_pages.json`. If the PDF text is
   line-wrapped mid-word, join it and note the normalization in `note`.
2. `page` is the 1-based PDF page where the quote/figure was found.
3. Numbers on slides must appear in (or be directly computable from) the
   cited evidence. If a number is recalled rather than verified, flag it in
   `open_issues` (see example: slide 8 parsing F1 values).
4. `notes` is checked against slide text for overlap; word-Jaccard > 0.6
   is a warning that the notes are just repetition.
