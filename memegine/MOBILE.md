# Memegine on your phone

Memegine is a pure-Python CLI with no GUI dependencies. That means you
can run the full toolkit on your phone via a terminal app.

The killer workflow: you're walking, you have an idea, you pull out your
phone, `memegine grade-idea "..."` or `claude` directly, and the brief
is ready before you're home.

---

## Android — Termux

[Termux](https://termux.dev/) gives you a real Linux shell on Android.
F-Droid install (the Play Store version is outdated/broken):

1. Install F-Droid: https://f-droid.org
2. Install Termux from F-Droid
3. Open Termux, run:

```bash
pkg update
pkg install python git ffmpeg

git clone https://github.com/anthropics/claude-code   # if you want Claude CLI
git clone <your-memegine-remote> memegine
cd memegine
pip install -e .
```

Optional but recommended:

```bash
pkg install openssh  # so you can ssh into Termux from your laptop
termux-setup-storage  # lets Termux read photos from your gallery
```

Test:

```bash
memegine formats
memegine doctor
memegine self-test
```

### Claude CLI on Termux

If you have Claude Code CLI installed, Termux works for that too. Now
you can walk around and talk to Claude with the full memegine tool
surface available. Drop an idea, ask Claude to `/piece` it, get a
brief back in chat.

---

## iOS — iSH or a-Shell

iOS is harder. Two options:

### a-Shell (recommended)

[a-Shell](https://github.com/holzschu/a-shell) — "A Shell" on the App
Store. Lightweight, includes Python 3.11.

```bash
pip install memegine  # if published; otherwise clone and pip install -e .
```

a-Shell doesn't have ffmpeg, so the editor / music modules won't work.
Everything prompt/brief/codex/bot-related works fine.

### iSH

[iSH](https://ish.app) emulates Alpine Linux. Slower but more complete.
Install python3 + git via apk.

---

## Quick-access — terminal aliases

Put these in your `~/.bashrc` (or `.zshrc`) on phone and laptop:

```bash
alias m='memegine'
alias mn='memegine next'
alias ml='memegine last'
alias mq='memegine topics add'
alias mg='memegine grade-idea'
alias mp='memegine piece'
alias mfm='memegine flow morning'
alias mfe='memegine flow evening'
alias ms='memegine search'
alias mpaste='memegine perf paste'
```

After that, "what should I make?" becomes `mn`. "queue this idea"
becomes `mq "..."`. Three-character commands. Thumb-typable.

---

## Recommended mobile daily loop

```bash
# wake up
m flow morning

# as ideas land throughout the day
mq "trader at 3am cope face" -p 4
mq "etf flows chart meme"
mq "founder cooked on a rooftop"

# when you're on the bus and want a brief ready
m piece "trader at 3am cope face"   # → bot delivers when home

# when a piece lands on X
mpaste "820 likes 140 RT 35 replies"

# end of day
m flow evening
```

---

## Telegram bot (the PUSH complement to CLI PULL)

On the phone, running `memegine bot run` in a persistent Termux
session (see `tmux` section below) gives you the bot AND the CLI
simultaneously.

- **CLI on phone** = talk to memegine directly, conversational, text-mode
- **Bot on phone** = memegine sends you briefs when scheduled jobs fire

Both running = you can't miss an idea and nothing requires desktop.

---

## Persistent sessions with tmux

Terminal apps close in the background on phones. Use `tmux` to keep
memegine running:

```bash
pkg install tmux
tmux new -s mem

# inside tmux:
memegine serve  # bot + scheduler

# detach: Ctrl-B then D
# reattach later: tmux attach -t mem
```

`memegine serve` runs the bot + scheduler together. SIGINT stops both
cleanly.

---

## Sporadic capture loop

The real unlock: memegine on your phone means any random thought
becomes a queued topic in 3 seconds.

1. Idea hits → open phone terminal.
2. `mq "trader at 3am, quiet dread, 35mm cinestill"` (p=3 default).
3. 7am next day → bot pushes the morning brief. The topic is there.
4. You pick the best, `memegine from-topic <id>`.
5. Brief ready to paste into Grok.

Or via Claude CLI:

1. Idea hits → `claude`
2. "I just thought of X — can you `/grade` it, `/piece` it if it's a
   B or better, and queue it otherwise?"
3. Claude runs memegine, delivers brief or queue confirmation.

This is the workflow the tool was built for.

---

## Troubleshooting

**Unicode errors in output** → Termux handles UTF-8 natively, but set
this once:

```bash
echo 'export LANG=en_US.UTF-8' >> ~/.bashrc
echo 'export LC_ALL=en_US.UTF-8' >> ~/.bashrc
source ~/.bashrc
```

**ffmpeg not found on iOS** → expected. Use the brief / codex / bot
features. Editing happens on a desktop.

**"no such command: memegine"** → `pip install -e .` in the memegine
directory. Verify with `which memegine`.

**Slow first run** → Python startup on Android is ~1-2 seconds. Alias
to `m` so you only pay it once, not per-character.
