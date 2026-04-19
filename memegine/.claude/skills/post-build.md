# /post-build — pack a finished piece into a post-ready folder

## Description

Takes the final image/video plus a caption and writes a single folder you
can open on your phone to post from. Caption + alt text + reply hook +
README + linted check, all pre-packaged.

## Arguments

`$ARGUMENTS` — `<media_path> ||| <caption> ||| <alt_text> [||| <reply_hook>] [||| <tags>]`

## Workflow

### 1. Parse pipes
Split `$ARGUMENTS` on ` ||| `. First piece is media path; then caption,
alt text, optional reply hook, optional comma-separated tags.

### 2. Caption lint FIRST
```bash
cd memegine && python -c "from memegine import caption_linter as cl; \
  r = cl.lint('<caption>'); print(r.as_text())"
```
If lint FAILS, do not build. Rewrite the caption. Repeat until PASS.
(Remove emojis, hashtags, engagement-bait, banned words. Trim to <= 280.)

### 3. Build the post folder
```bash
cd memegine && python -m memegine.cli post build "$MEDIA" \
  --caption "$CAPTION" \
  --alt "$ALT_TEXT" \
  --reply "$REPLY_HOOK" \
  --tags "$TAGS"
```

### 4. Report
Return:
- Folder path (operator will open this on phone)
- Confirmation the caption lint is PASS
- The three files inside: `final.<ext>`, `caption.txt`, `alt_text.txt`

### 5. Post-posting reminder
When piece lands: run `/winner <image> <prompt> ||| <why>` to compound.
When it flops: `memegine codex flop "<what>" "<why>"` to populate the
kill list.
