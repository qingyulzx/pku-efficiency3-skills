# Template adaptation rules

Why this matters: the evaluator checks that the deck works *inside the
organizer's template* — placeholders respected, fonts/chrome inherited,
nothing free-floating. A deck that pastes text boxes over a template is a
template violation even if it looks fine.

## How the role_map is derived (analyze_template.py)

1. Every layout's placeholders are inventoried (idx, type, geometry).
2. Chrome placeholders (DATE / FOOTER / SLIDE_NUMBER) are excluded from
   content decisions.
3. Structural guess:
   - contains a PICTURE placeholder → `figure`
   - contains CENTER_TITLE → `title`
   - title but no body → `section`
   - title + ≥2 body placeholders → `two_column`
   - title + 1 body → `content`
4. Name-keyword match across ALL layouts then overrides the guess
   ("Section Header" structurally looks like title+body; only its name
   identifies it).

Agent override: read `template_map.json` and, when you disagree with a
mapping (localized names, unusual custom layouts), set the slide's `layout`
field explicitly in the deck plan. Record the override in changes.json.

## Placeholder write rules (assemble_deck.py)

- Text is written to the **slide's cloned placeholders**, never the layout's.
  (Writing to the layout produces prompt text that never renders — a real bug
  we hit and fixed; see progress.md.)
- Type matching accepts both BODY and OBJECT placeholder types (python-pptx
  reports content placeholders as OBJECT in many templates).
- The ONLY sanctioned free text box is the figure caption, whose position is
  content-dependent. Everything else must live in placeholders; the checker
  reports the share of characters inside placeholders (warn < 90%).

## Figure placement

- If the layout has a PICTURE placeholder: `insert_picture()` places the
  image there with an aspect-preserving **srcRect crop** — the placeholder's
  geometry is respected exactly.
- Otherwise the image is placed centered below the title at ≤ 8.4×5.0 in,
  scaled to keep the aspect ratio (no stretch).
- A picture inserted into a placeholder keeps `shape_type == PLACEHOLDER`,
  not PICTURE — the checker detects pictures by the underlying `p:pic`
  element tag, and so should any custom inspection code.

## Sizing

- Body first-fit: 20pt down to 12pt in 2pt steps, estimated by wrapped-line
  counting (char-width 0.52 × font size, line spacing 1.22). If it still
  does not fit at 12pt, a warning is emitted — the fix is to shorten the
  content in the plan, never to truncate silently.
- Titles: 36pt down to 22pt; long titles get a "consider shortening" warning
  (a title shrunk to the floor usually means the claim is too big for one
  slide).

## Editing a starting deck

When case.json provides a starting deck instead of an empty template, slides
with `edit_slide_index` are rewritten in place (title + first body
placeholder); new slides are appended after. Existing slides without a plan
entry are left untouched.
