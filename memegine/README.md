# Memegine — Director's Assistant

A zero-cost, offline-first toolkit that turns rough operator intent into
production-grade prompts you paste into **Grok** (Nano Banana / Aurora /
Grok Imagine) for actual image + short-video generation.

You supply the taste and the hand-edits. The tool handles the briefs, the
style memory, the reference library, and the copywriting.

## Why

The iron triangle of AI content is **free × elite × push-button** — you can
pick two. With only Claude Code and Grok, push-button is off the table.
This tool maxes out the other two by making every hand-craft session faster
and sharper.

## Pipeline

```
rough intent
    │
    ▼
memegine prompt "..." -f photoreal_portrait
    │                    (prints a SYSTEM + USER brief)
    ▼
paste into Claude Code / Claude.ai
    │                    (returns JSON with prompt + variants + captions)
    ▼
paste the "prompt" field into Grok
    │                    (generate, iterate, pick winner)
    ▼
memegine refs add winner.png --tags ... --notes ...
memegine codex winner "..." "why it worked"
```

Over time the style codex + reference library mean the *first* Grok
generation you try is already sharp — because Claude wrote its prompt
with full awareness of what's landed for you before.

## Install

```
cd memegine
pip install -e .
cp .env.example .env    # optional; only needed if you later add an API key
```

## Commands

```
memegine formats                           # list available formats
memegine prompt "kilroy watching the fed announcement" -f meme_two_panel
memegine shots "15-second clip: phone slowly zooms on a market chart while the news goes silent"
memegine copy "photoreal portrait of a trader at 3am, lit by monitor glow" --kind image

memegine codex show
memegine codex winner "...prompt..." "why it worked"
memegine codex flop "...what flopped..." "why"

memegine refs add path/to/winner.png --tags "night,portrait,neon" --notes "the one"
memegine refs search --tags "night,portrait"
memegine refs recent -n 20
```

## Directory layout

```
memegine/
  src/memegine/         # the tool
  data/
    codex/style.md      # living style doc — Claude reads this every time
    formats/library.yaml # format templates (meme_two_panel, photoreal_portrait, etc.)
    references/         # your tagged winners (local; .gitignored by default)
    outputs/            # optional: saved brief outputs
    logs/               # usage logs (empty in offline mode)
```

## Offline vs online

- **Offline (default):** no API key, no network. `memegine prompt ...` prints the
  assembled SYSTEM + USER blocks. Paste into any Claude interface to get the JSON
  brief.
- **Online (optional):** set `ANTHROPIC_API_KEY`, install the `online` extra
  (`pip install -e .[online]`), and the client wrapper is wired for direct
  SDK calls with prompt caching. Use this only if you ever choose to fund API
  access — not required.

## Philosophy

- Every piece is handmade; the tool just removes friction.
- The style codex + reference library compound — week 10 is sharper than week 1.
- Never ships words like "cinematic", "epic", "stunning" in prompts.
- Names lenses, film stocks, lighting setups, camera moves by name.
- Captions must not sound AI — no emoji salad, no engagement bait.
