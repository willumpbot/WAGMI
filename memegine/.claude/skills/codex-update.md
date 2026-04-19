# /codex-update — end-of-session codex compaction

## Description

After a session where 2-5 pieces landed, compact learnings into the
codex. Promote frequent patterns. Log flops. Capture voice notes. This
is the end-of-day ritual that compounds style week over week.

## Arguments

`$ARGUMENTS` — freeform session notes. Examples:
- `/codex-update tonight kilroy-avatar + 3am kitchen landed hardest; drake yes/no
  format is stale, keep off rotation for a week`

## Workflow

### 1. Read the current codex
```bash
cd memegine && python -m memegine.cli codex show
```

### 2. Distill from session archive
Get the last 30-50 archived briefs:
```bash
cd memegine && python -m memegine.cli codex distill --n 50 --min 2
```
This writes frequent lens/film/lighting patterns into "Weekly Distill".

### 3. Check for promotion candidates
```bash
cd memegine && python -c "from memegine import archive, auto_codex; \
  p = [r.get('user','') for r in archive.read_recent(500)]; \
  pr = auto_codex.graduate_patterns(p, promotion_threshold=5); \
  print('promoted:', pr)"
```
This promotes any pattern seen 5+ times to "Core Patterns".

### 4. Log the session's flops (operator-supplied)
From the session notes, extract things that DIDN'T work:
```bash
cd memegine && python -m memegine.cli codex flop "<what>" "<why>"
```
(e.g., `codex flop "drake meme format" "feels stale; skip for a week"`)

### 5. Log voice notes
From the session notes, extract adjectives/frames the operator wants in
future captions:
```bash
cd memegine && python -c "from memegine import style_codex; \
  style_codex.append_entry('Voice Notes', '<voice observation>')"
```

### 6. Report
Print:
- N new entries added
- What was promoted to Core Patterns (if anything)
- Updated counts per section

## Notes

- Don't write duplicates; check existing codex first.
- If session had zero landed pieces, skip Winners promotion, only update
  voice notes + flops.
