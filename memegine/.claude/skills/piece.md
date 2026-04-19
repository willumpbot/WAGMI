# /piece — one-shot intent → ready-to-post bundle

## Description

The main memegine slash command. Takes rough operator intent and produces
a complete bundle: brief, caption brief, format choice, all in one folder
ready to paste into Grok.

## Arguments

`$ARGUMENTS` — intent string, optionally followed by `--kind image|video`
and `--format <slug>`. Examples:
- `/piece trader dumping at 3am`
- `/piece trader dumping at 3am --kind image --format photoreal_portrait`
- `/piece slow push on a kitchen at dusk --kind video`

## Workflow

### 1. Parse arguments
Extract intent, optional `--kind`, optional `--format`.

### 2. Resolve defaults
If `--kind` omitted, use `memegine suggest` to infer and pick the top format:
```bash
cd memegine && python -m memegine.cli suggest "$INTENT" -n 1
```

### 3. Run the pipeline
```bash
cd memegine && python -m memegine.cli pipeline "$INTENT" --kind $KIND --format $FORMAT
```
This writes the bundle folder and prints the location.

### 4. Read and process each brief
Open each `*.md` file in the bundle folder. For each one:
- Read the SYSTEM + USER blocks.
- Generate the JSON result directly in this Claude Code session (you are
  Claude — run the brief yourself; no need to paste it anywhere).
- Lint the resulting `prompt` with `memegine lint "<prompt>"` and
  `memegine score "<prompt>"`. If lint fails or score < 70, revise and
  re-grade.

### 5. Report
Print to the operator:
- Bundle id + folder path
- Format chosen (and why, if auto-picked)
- For image briefs: the final Grok-ready prompt, 3 caption options, alt
  text
- For video briefs: shot list with per-shot still_prompt + motion_prompt
- Suggested next moves (variants, reverse, post)

### 6. Archive note
Remind operator: when the piece lands, run
`memegine refs add <file> --winner --prompt "..." --notes "why"` to
compound the style codex.

## Notes

- Always run the brief yourself in-session; don't ask operator to paste.
- Prefer formats already in the style codex's "Core Patterns" or
  "Compounded Patterns" sections when ambiguous — they're proven.
- If intent is vague, run `memegine grade-idea "<intent>"` first and
  suggest tightening before spending a brief on it.
