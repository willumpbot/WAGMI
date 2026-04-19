# /winner — log a landed piece, extract patterns, compound the codex

## Description

When a piece lands on X, call this. It adds the image to the reference
library (tagged `winner`), appends the prompt to the codex under
"Proven Prompt Patterns", AND auto-extracts the named craft tokens
(35mm f/1.4, Portra 400, window light, dusk…) into "Compounded Patterns".

Every invocation makes the next brief sharper.

## Arguments

`$ARGUMENTS` — `<image_path> <winning_prompt> ||| <why it worked>`.

Alternative: `<ref_id> <winning_prompt> ||| <why>` — if the image is
already in the ref library, reference by id.

## Workflow

### 1. Parse
Split on ` ||| `. Left half is image path + prompt; right half is the
reason. The image path is the first token before the prompt starts.

### 2. Add to refs with `--winner`
```bash
cd memegine && python -m memegine.cli refs add "$IMAGE" \
  --winner --prompt "$PROMPT" --notes "$WHY" \
  --tags "winner,$EXTRA_TAGS"
```

This triggers the compounding chain:
- File is hashed and copied into `data/references/`.
- Prompt is logged to codex under "Proven Prompt Patterns".
- Named tokens in the prompt are extracted to "Compounded Patterns".

### 3. Report
List what got extracted:
- Lens (e.g., "35mm f/1.4")
- Film (e.g., "portra")
- Lighting (e.g., "window light")
- Time (e.g., "dusk")
- Composition (e.g., "rule of thirds")
- Camera move (for video)
- Wardrobe (for photoreal)

### 4. Promote check
If we've seen specific tokens 5+ times, suggest running:
```bash
cd memegine && python -c "from memegine import archive, auto_codex; \
  prompts = [r.get('user','') for r in archive.read_recent(500)]; \
  auto_codex.graduate_patterns(prompts, promotion_threshold=5)"
```
This elevates proven patterns to the "Core Patterns" section.
