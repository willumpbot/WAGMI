# /corpus-bootstrap — seed memegine from a real-editor archive

## Description

The fast path to a working style memory. Point memegine at a folder
of confirmed-good work (from editors, prior projects, or a reference
archive), and in one session seed the codex from real ground-truth
instead of an empty template.

This is the single highest-leverage use of the system for a new
operator.

## Arguments

`$ARGUMENTS` — path to the archive folder. Dropbox / Google Drive sync
paths work fine (they're just local directories on the operator's
machine).

## Workflow

### 1. Confirm the path exists
```bash
ls "$FOLDER" | head
```
If empty or missing, prompt the operator to verify the sync is done.

### 2. Bulk ingest
```bash
cd memegine && python -m memegine.cli corpus ingest "$FOLDER" --frames 5
```
- Images (.png/.jpg/.webp/.gif) go straight to refs.
- Videos (.mp4/.mov/etc) get 5 evenly-spaced stills extracted, each
  becomes its own ref tagged `video:<stem>` + `frame:N`.
- Folder hierarchy becomes tags (`photoreal/portraits/xyz.png` →
  `['photoreal', 'portraits']`).
- Dedupes by content-hash, so re-running is safe.

### 3. Offer the reverse-engineer path
```bash
# If ANTHROPIC_API_KEY is set, this adds named craft tokens per ref.
memegine corpus reverse
```
- ~$0.003 per image via Sonnet vision
- For 100 images, that's ~$0.30 — worth it

If the operator doesn't have a key or wants to skip, this step is
optional. Everything downstream still works, just with fewer dimensions
of craft signal to distill from.

### 4. Distill into codex
```bash
memegine corpus distill
```
Writes:
- Dominant lens / film / lighting / time-of-day (seen in 30%+ of refs)
  into **Visual DNA**
- Every token seen 5+ times absolute into **Core Patterns**

### 5. Inspect + quality-check
```bash
memegine corpus stats      # aggregated view
memegine codex show        # read the seeded codex
```

Read the codex by eye. Anything wrong? The operator can edit
`data/codex/style.md` directly. Anything great? Highlight it so the
operator knows what memegine captured.

### 6. Generate thumbnails (optional, but recommended for phone)
```bash
memegine refs thumbs
```
256px JPEGs into `data/references/thumbs/` so browsing the library
on phone is fast.

## After bootstrap

The operator can now run:

- `memegine like-winner "..."` — inherits the corpus's craft for a new subject
- `memegine variants-last -n 6` — tweaks on their latest addition
- `memegine piece "..."` — all future briefs read the seeded codex
- `memegine next` — shows a dashboard informed by the corpus

This is a one-time setup. After it, every `piece` / `brief` is as
sharp as an experienced operator's week-12 briefs.

## Pro tip — multiple editors

If the archive contains work from different editors whose looks differ:

```bash
memegine corpus ingest ~/archive/alice --tag-prefix editor:alice
memegine corpus ingest ~/archive/bob --tag-prefix editor:bob
memegine corpus reverse
memegine corpus compare editor:alice editor:bob
```

This reveals where the two editors actually differ (lens choice,
lighting, palette). The operator can then decide which editor's
approach to canonize, or merge deliberately.
