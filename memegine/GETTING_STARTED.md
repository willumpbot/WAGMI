# Getting started with memegine

Memegine is a director's assistant for photo/video content. It doesn't
generate media — it turns rough intent into production-grade briefs you
paste into Grok, and it compounds your style memory so every brief is
sharper than the last.

This is the 10-minute onboarding.

---

## Install

```bash
cd memegine
pip install -e .
```

Optional:

```bash
pip install -e '.[online]'    # Claude API execution
pip install -e '.[telegram]'  # phone bot
pip install -e '.[dev]'       # tests
```

Then run the health check:

```bash
memegine doctor
memegine validate
memegine self-test
```

All three should end in `PASS`. If doctor flags missing ffmpeg, that's
OK unless you plan to use the editor / music modules.

---

## The five commands that matter first

### 1. Seed your codex

Your codex is your style memory — the single most important file.
Start it with the template:

```bash
memegine codex init
```

Open `data/codex/style.md` and fill in:
- **North Star**: 1-3 sentences describing who the content is for, what
  register it lives in
- **Voice & Tone**: adjectives and syntactic patterns that sound like
  you
- **Visual DNA**: preferred film stocks, lenses, times of day
- **Kill List**: words / formats / aesthetics that don't work for this
  project

This is a living doc. Add to it every session.

### 2. Grade an idea before you brief it

```bash
memegine grade-idea "trader at 3am, cope face, 12% drawdown"
```

Returns a 0-100 score and a letter grade. A or B → proceed. C → tighten
first. D or F → don't brief it yet.

### 3. Pipeline a piece

```bash
memegine piece "trader at 3am, cope face"
```

Auto-picks a format, produces a brief bundle in `data/outputs/`. Open
each `.md` file in the bundle and paste into Claude Code (or Grok) to
get the finished prompt, variants, and captions.

### 4. Log a winner

A piece lands on X. You want to compound it.

```bash
memegine refs add /path/to/image.png \
  --winner \
  --prompt "the full prompt that produced it" \
  --notes "why it landed" \
  --auto-variants --n-variants 3
```

This does four things:
- Adds the image to your reference library (tagged `winner`)
- Appends the prompt to "Proven Prompt Patterns" in the codex
- Auto-extracts craft tokens (35mm, Portra 400, window light, etc.)
  into "Compounded Patterns"
- Enqueues 3 variant intents as topics for the next session

### 5. Log engagement

```bash
memegine perf paste "820 likes 140 RT 35 replies 12.4K views"
```

That's it — the parser handles every common X layout. From now on,
`memegine format-health` and `memegine perf summary` know which formats
actually land.

---

## The morning and evening rituals

```bash
memegine flow morning --name "afternoon-hero"
# opens a session + shows dashboard + shows last activity

memegine flow evening
# closes session + distills codex + prints daily stats
```

If you do these two every day, your codex grows by itself.

---

## The phone setup

See [MOBILE.md](./MOBILE.md) for Termux / iSH / a-Shell setup. Quick
recipe:

```bash
# On Android via Termux:
pkg install python git
git clone <your-memegine-remote>
cd memegine && pip install -e .
```

Set up shell aliases (from MOBILE.md) so `m`, `mn`, `ml`, `mq` are all
3 characters.

Then add the Telegram bot for push delivery:

```bash
export MEMEGINE_TELEGRAM_BOT_TOKEN=...
export MEMEGINE_TELEGRAM_ALLOWED_USER_IDS=12345
memegine bot run
```

Drop it in `tmux` so it survives phone-lock:

```bash
tmux new -s mem
memegine serve    # bot + scheduler in one process
# Ctrl-B D to detach
```

---

## The unlock

Once you're 10-20 winners in, these commands start feeling magic:

```bash
memegine like-winner "a CEO at a rooftop"
# inherits the craft of your last winner, composes a new prompt

memegine variants-last -n 6
# 6 single-axis tweaks on your latest winner

memegine codex graduate --threshold 5
# patterns seen 5+ times get promoted to Core Patterns

memegine next
# one-screen "what should I make?" with queue + winner + perf-leader
```

That's the compounding loop. Every winner makes the next one easier.

---

## When things break

```bash
memegine doctor        # env / paths / deps
memegine validate      # YAML integrity
memegine self-test     # full integration walk
```

If all three pass, the system is healthy. If doctor or validate fail,
the message tells you what to fix.

---

## Read next

- **MOBILE.md** — phone setup + thumb-friendly aliases
- **COOKBOOK.md** — 10 common workflows in full detail
- **README.md** — the full feature inventory
- **data/playbooks/*.md** — the craft knowledge memegine reads on every
  brief. Worth reading yourself.
