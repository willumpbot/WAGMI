# /caption — X caption options for a finished piece

## Description

Produce caption options for a piece that's already been made. Output
obeys the hard copy rules (no emojis, no hashtags, no gm/wagmi/lfg, no
engagement-bait) and varies length so the operator can pick per mood.

## Arguments

`$ARGUMENTS` — concept description. What's actually in the image/video.
Be concrete: "trader at a laptop, kitchen, 3am, quiet dread" beats
"a crypto trader".

## Workflow

### 1. Run the caption brief
```bash
cd memegine && python -m memegine.cli copy "$CONCEPT" --kind image
```
(or `--kind video` for video pieces).

### 2. Execute in-session
Produce the JSON per the SYSTEM rules:
- One short caption (≤ 8 words)
- One medium (≤ 20 words)
- One two-line setup→payoff

### 3. Validate each caption
For each caption option, run:
```bash
cd memegine && python -c "from memegine.caption_linter import lint; r = lint('<caption>'); print(r.as_text())"
```
Any caption that FAILs gets rewritten. The linter enforces no emoji, no
hashtags, no banned phrases, length ≤ 280.

### 4. Report
Return the three validated options plus the alt_text. Note which option
would work best for each register (dry hero shot → short; joke → two-line
payoff; piece needing context → medium).

## Notes

- Never explain the joke in a caption.
- Zero-word captions (post with no text) are valid for strong hero shots.
- If the piece is serious, offer one option that's just a noun-phrase
  (no verb, no sentence).
