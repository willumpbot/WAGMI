# /corpus-review — inspect what memegine learned from the archive

## Description

After `corpus ingest` + `corpus reverse` + `corpus distill`, use this
to show the operator what was captured and surface anything off.

## Workflow

### 1. Stats overview
```bash
cd memegine && python -m memegine.cli corpus stats
```
Shows:
- total refs + winners
- how many have extracted_patterns
- top tags
- top lens / film / lighting / time-of-day / composition / color_palette /
  mood / location_type

### 2. Check the codex
```bash
memegine codex show
```
Read the Visual DNA + Core Patterns sections aloud to operator. Ask:
- Does this match your instinct for what your work looks like?
- Anything that surprises you?
- Anything missing that you'd expect?

### 3. Spot outliers
Export the corpus to CSV and look for refs where the extracted
patterns look weird (low-res thumbnails, bad lighting detection, etc.):

```bash
memegine corpus export /tmp/corpus.csv
```
The operator can open this in Excel / Numbers / pandas and sort by
any column to find refs that don't fit the pattern.

### 4. Compare editors / sub-genres (if applicable)
If the archive was ingested with `--tag-prefix editor:X`:

```bash
memegine corpus compare editor:alice editor:bob
```
Shows where the two editors' craft diverges. Useful for deciding
which look to canonize.

### 5. Propose adjustments
Based on the review, suggest:
- Run `memegine corpus reverse --all` if the operator wants to
  re-extract with a different model
- Manually edit `data/codex/style.md` to remove spurious entries or
  add missing ones
- Mark wrong extractions by appending `memegine codex flop "<item>"
  "extracted wrong: <why>"` so future briefs know to avoid that path

## Don't

- Don't blindly accept the distilled codex. The operator's taste is
  the arbiter — the extractor is a proposal, not a decree.
- Don't run the distill twice in a row without editing in between.
  Duplicates will appear in Visual DNA.

## Next step

Once the codex is validated, the operator is ready for production:
- `memegine flow morning` to open a session
- `memegine piece "..."` to generate a real brief
- `memegine refs add ... --winner` to start compounding for real
