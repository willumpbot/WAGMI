# /topic-add — append an intent to the topic queue

## Description

Drop a rough intent / trend / news hook into the topic queue so the
scheduler can pull from it later. Use when something interesting crosses
the radar but isn't a piece yet.

## Arguments

`$ARGUMENTS` — topic text, optionally `--tags a,b,c --priority 1-5
--kind image|video|any --format <slug>`. Examples:
- `/topic-add ETH broke below $2800 at 4am`
- `/topic-add rooftop liquidation at sunset --tags hero,night --priority 5`

## Workflow

### 1. Parse
Topic text is everything before flags. Extract tags, priority, kind,
format if present.

### 2. Grade first
Before queuing, gut-check with:
```bash
cd memegine && python -m memegine.cli grade-idea "$TOPIC"
```
If grade is F, suggest tightening before queuing. Don't pollute the queue
with vague topics.

### 3. Queue it
```bash
cd memegine && python -m memegine.cli topics add "$TOPIC" \
  --tags "$TAGS" --priority $PRIORITY --kind $KIND --format $FORMAT
```

### 4. Confirm
Report: topic id, priority, the queue's current count, and when the next
scheduled batch will fire (check `memegine schedule list`).
