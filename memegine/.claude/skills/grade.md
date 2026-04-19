# /grade — idea grader (pre-brief landability score)

## Description

Score a rough intent 0-100 for landability BEFORE spending a brief on it.
Checks specificity, emotion, format-friendliness, concrete hooks. Cheap
filter on what's worth turning into a piece.

## Arguments

`$ARGUMENTS` — the intent text. Example:
- `/grade trader at 3am, cope face, 12% drawdown`

## Workflow

### 1. Run the grader
```bash
cd memegine && python -m memegine.cli grade-idea "$INTENT"
```

### 2. Interpret
- A (90-100): ship it — run `/piece` or `/batch`.
- B (80-89): solid; one quick tweak and it's A-grade.
- C (70-79): missing an ingredient; ask operator to specify one more detail.
- D (60-69): underbaked; suggest a concrete edit (name the emotion, add
  a time/number, name the subject).
- F (< 60): don't brief it yet. Work the intent.

### 3. Return tips
The grader returns specific suggestions. Echo them to the operator. If
grade is D or F, do NOT proceed to `/piece` — force the operator to
tighten first.

### 4. Format hint
If the grader returns matching formats, mention them so the operator
knows the intent is already format-friendly.
