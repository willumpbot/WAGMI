# Spong — Style Codex

> **Status:** SKELETON. The real codex will be seeded from the
> `@ghostmemes` / `memedepot.com/d/spong` corpus the same way the
> $MOTION codex was reverse-engineered from 47 reference videos.
>
> Until the corpus is ingested, the Director should treat this codex as
> an empty-handed brief and rely on craft playbooks only. Do NOT invent
> Spong signature moves — if you don't know, ASK THE OPERATOR.

## What we know so far

- Creator / operator: `@ghostmemes` on X.
- Home: `memedepot.com/d/spong` (depot #1401).
- Not to be confused with `$SPONGE` (the SpongeBob memecoin on Uniswap).
  Spong ≠ Sponge.

## Ingest workflow — one command

The Spong brand CANNOT be seeded from the web. `memedepot.com/d/spong`
renders no visible memes through a headless fetch, `@ghostmemes` on X
requires authentication, and no mainstream aggregator indexes the brand
yet. So the operator must drop references manually — screenshots,
saves, screen-recordings of any source where Spong content actually
lives (X likes, iMessage threads, Telegram saves, whatever).

**One-command path:**

```
memegine project use spong
# drop 20-50 representative stills / short clips into any folder
memegine corpus seed ./wherever-your-spong-saves-live/
```

That ingests every file into `data/projects/spong/references/` with
auto-generated IDs, extracts 5 frames from each video, and prints a
next-step briefing. The existing `corpus_reverse_local` path then lets
this Claude Code session look at each frame and extract craft tokens
WITHOUT any API key — the same path used to seed the $MOTION codex
from 47 Drive videos in wave 31.

**Once patterns exist:**

```
memegine corpus apply <patterns.json>   # propagate into refs + sibling frames
memegine corpus distill                 # aggregate into codex DNA + Core Patterns
# then edit data/projects/spong/brand.yaml to absorb the signature moves
```

Once the corpus is ingested, the Director will:

1. Identify recurring subject archetypes (pull into `brand.yaml:subject_archetypes`)
2. Extract the typography register(s) used
3. Extract the color palette
4. Name 5-10 signature moves
5. Update this codex with the actual ground-truth patterns

## Compounded Patterns

*(empty — ingest corpus first)*
