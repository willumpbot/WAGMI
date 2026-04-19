# /brief — assemble a single image brief

## Description

Produce ONE image brief (without caption, without shot list) for the given
intent and format. Lighter weight than `/piece` — use when you already
know you only need the Grok prompt, not the whole bundle.

## Arguments

`$ARGUMENTS` — intent + optional format. Examples:
- `/brief trader at 3am -f photoreal_portrait`
- `/brief setup/payoff about ETF flows -f meme_two_panel`

## Workflow

### 1. Parse arguments
Extract intent and `-f <slug>`.

### 2. Auto-pick format if missing
```bash
cd memegine && python -m memegine.cli suggest "$INTENT" -n 1 --kind image
```
Use the top slug.

### 3. Assemble the brief
```bash
cd memegine && python -m memegine.cli prompt "$INTENT" -f $FORMAT
```
This prints SYSTEM + USER blocks and archives to
`data/logs/briefs-YYYY-MM-DD.jsonl`.

### 4. Execute the brief
Read the SYSTEM + USER blocks. Act as the Director per the SYSTEM
instructions. Produce the JSON result directly in-session.

### 5. Lint & score
```bash
cd memegine && python -m memegine.cli lint "<the prompt field>"
cd memegine && python -m memegine.cli score "<the prompt field>"
```
If lint fails or score < 70, revise the prompt — add named lens,
lighting, time, composition, negatives — and re-score.

### 6. Report
Return just the finished Grok-ready prompt, the 3 caption options from
`post_caption_ideas`, and the variants_to_try list.

## Notes

- If operator insists on a motion brief, suggest `/shots` instead (better
  structured for video).
- Always include the negative-prompt clause in the final output
  ("no extra fingers, no warped text, no logo watermarks").
