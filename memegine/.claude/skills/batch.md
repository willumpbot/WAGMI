# /batch — N briefs across varied formats for one theme

## Description

Produce N briefs for a single theme across different visual registers.
When the operator has a topic but isn't sure which angle will land, batch
gives them 4-6 angles to pick from in one pass.

## Arguments

`$ARGUMENTS` — `<n> <theme>`. Examples:
- `/batch 4 the ETF flow number nobody's reading`
- `/batch 6 trader at 3am`

## Workflow

### 1. Parse N and theme
Default to `n=4` if operator didn't specify.

### 2. Run the batch generator
```bash
cd memegine && python -m memegine.cli batch "$THEME" -n $N
```
This writes a batch folder under `data/outputs/<date>_batch_<slug>_<id>/`
with N brief `.md` files, one per format.

### 3. Execute each brief
For each `.md` in the batch folder:
- Read the SYSTEM + USER blocks
- Generate the JSON result in-session (you are Claude — run it)
- Lint + score the resulting `prompt`
- If score < 70, note which category is weak, revise, re-score

### 4. Compare
Present the N prompts side-by-side with their scores and formats. Flag:
- Which 1-2 land best given the current style codex
- Which are redundant (e.g., two formats produced near-identical images)
- Which trigger the operator's kill list

### 5. Recommend
Pick the ONE angle most likely to compound. Justify in one sentence.
Mention the 2nd best as a fallback.

## Notes

- batch only outputs image formats. For video themes, use `/shots`.
- If the theme scores D or F on `memegine grade-idea`, stop and fix the
  theme before batching — don't waste briefs on a vague intent.
