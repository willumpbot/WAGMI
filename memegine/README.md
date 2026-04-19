# Memegine — Director's Assistant for Elite Photo/Video Content

A zero-cost, offline-first toolkit that turns rough operator intent into
production-grade prompts you paste into **Grok** (Nano Banana / Aurora /
Ideogram / Grok Imagine video). You supply the taste and the edits. Memegine
handles the briefs, the style memory, the reference library, the copywriting,
and the FFmpeg-based editing so you never open CapCut.

**Stack: free. Claude Code + Grok (via X Premium). Nothing else.**

> **New here?** Run `memegine guide` for the 7-step getting-started flow.
> Or read [GETTING_STARTED.md](./GETTING_STARTED.md), [COOKBOOK.md](./COOKBOOK.md),
> and [MOBILE.md](./MOBILE.md).
>
> **Want a quick list of what's actually there?** 500+ tests, 30+ formats,
> 200+ craft fragments, corpus bootstrap from any Dropbox/Drive folder,
> Telegram bot, Claude-powered brainstorm/morning-brief/weekly-report,
> sessions + journal + dashboard + perf tracking + consistency checker +
> contact sheet + lookbook. Full inventory below.

---

## The iron triangle

| Free? | Elite? | Push-button? |
|---|---|---|
| ✅ | ✅ | ❌ |

You can have two of three. Memegine picks free + elite. Push-button means
paid APIs ($100-300/mo), and we don't need them. Your hands stay on the
wheel; memegine removes everything else.

---

## What's inside

### The workflow

```
rough intent
    │
    ▼
 /piece <intent>          ← Claude Code slash command (or `memegine pipeline`)
    │
    ▼
Director assembles brief  ← reads style codex + craft playbooks + format
    │
    ▼
You paste prompt into Grok (Nano Banana / Aurora / Ideogram / Grok Imagine)
    │
    ▼
You iterate in Grok until it lands
    │
    ▼
memegine refs add <file>   (your best outputs grow the reference library)
memegine codex winner      (patterns compound into future briefs)
    │
    ▼
memegine edit ...          (FFmpeg-based stitching/aspect/grade/caption — no CapCut)
    │
    ▼
Post on X
```

### The modules

- **`prompt_engine`** — assembles a SYSTEM + USER brief from intent + format
  + style codex + craft playbooks
- **`shot_list`** — shot-list brief for short (3-12s) video pieces
- **`copy_writer`** — X caption brief that doesn't sound AI
- **`variants`** — variant generator (one winning prompt → N axis-varied
  versions)
- **`reverse_engineer`** — image → recreate-the-look prompt (uses Claude's
  vision)
- **`linter`** — catches banned words (cinematic, epic, 4k...) and warns
  when a prompt lacks named lens/film/lighting/time/composition
- **`deep_linter`** — extends linter with a 0-100 craft-coverage score
  across 8 weighted dimensions, with operator-facing tips per miss
- **`format_suggest`** — infers image vs video from the intent and ranks
  the top-N format slugs via keyword heuristics
- **`auto_codex`** — extracts named craft tokens (35mm f/1.4, Portra 400,
  window light…) from winning prompts; auto-appends them to the codex so
  patterns compound
- **`topics`** — append-only queue of ideas/trends at
  `data/topics/queue.yaml`; drain in batches on a schedule
- **`scheduler`** — tiny cron-style runner: every minute, fire any job
  whose time has come; jobs pull N topics, build bundles, deliver
- **`telegram_bot`** — brief delivery on your phone. Commands match the
  CLI. Photo uploads → reference library. `/winner` auto-extracts
  patterns into the codex.
- **`export`** — pack a finished piece into a post-ready folder with
  `final.<ext>`, `caption.txt`, `alt_text.txt`, `reply_hook.txt`,
  `README.md` — one folder to open on your phone and post from
- **`idea_grader`** — score an intent 0-100 for landability before you
  spend a brief on it. Checks specificity, emotion, format-friendliness,
  concrete hooks, subject naming; flags vague words and AI-slop.
- **`executor`** — optional Claude API path. If `ANTHROPIC_API_KEY` is
  set, run the brief through Claude and return the finished Grok prompt
  directly instead of a paste-able SYSTEM+USER block.
- **`batch`** — N briefs across varied formats for one theme. `/batch 4
  "<theme>"` produces four angles in one pass so you can pick the one
  that lands.
- **`caption_linter`** — X caption validator: no emojis, no hashtags, no
  banned phrases (gm/wagmi/lfg/engagement-bait), length <= 280. Wired
  into post export so every post-ready bundle gets a lint report.
- **`discord_webhook`** — fire-and-forget Discord webhook delivery via
  stdlib urllib. No persistent bot. Scheduler can POST results here the
  same way it pushes to Telegram.
- **`stats`** — daily / weekly / all-time activity report across
  briefs + refs + codex + topics + posts.
- **`performance`** — operator logs engagement (likes, RT, replies) per
  post. Aggregates by format, by codex pattern, by hour-of-day so the
  operator can see *which formats/patterns/times actually land*.
- **`doctor`** — health check that validates data dirs are writable,
  ffmpeg is on PATH, format library + playbooks load cleanly, codex is
  readable, optional API keys (Anthropic/Telegram/Discord) are
  consistent.
- **`fragments`** — named reusable craft snippets at
  `data/fragments/library.yaml`. Operator references them by code
  (`LENS.35mm_1_4`, `FILM.cinestill_800t`, `LIGHTING.harsh_window`) and
  memegine expands them inline. Ten categories seeded: LENS, FILM,
  LIGHTING, TIME_OF_DAY, COMPOSITION, MOOD, SUBJECT, LOCATION, NEGATIVE,
  CAMERA_MOVE. Operator adds more as patterns prove out.
- **`session`** — mark the start and end of a working block. Stats can
  bucket by session instead of calendar day — different energy, different
  output. CLI: `memegine session start/end/list`.
- **`journal`** — reverse-chronological unified feed across archive,
  refs, posts, and session markers. One view of "what have I done
  lately?". CLI: `memegine journal --days 7`.
- **`next_action`** — one-screen "what should I make?" dashboard.
  Summarizes queue, last winner, top-performing format, and produces a
  ranked list of concrete next moves tailored to the current state.
  CLI: `memegine next`.
- **`x_post`** — final pre-flight before posting to X: loads a post
  bundle, runs the caption linter, produces a clipboard-ready block
  with media path + caption + alt text + reply hook. No API, no paid
  tier. Free-first. CLI: `memegine x prepare <post_id>`.
- **`codex_audit`** — detects duplicate codex bullets, contradiction
  candidates (entries that 'use X' and 'avoid X' at once), and heavy
  sections that are candidates for `codex distill` / `codex graduate`.
  CLI: `memegine codex audit`. Bot: `/codex_audit`.
- **`batch_exec`** — if `ANTHROPIC_API_KEY` is set, runs every item in
  a batch through Claude in one call, writes per-item JSON, lints each
  resulting prompt, and flags a winner. CLI: `memegine batch-execute`.
- **`trend_reader`** — pulls topic candidates from configured RSS /
  Atom / JSON / JSONL feeds, dedupes against the topic queue, and
  appends new ones. stdlib-urllib only; no external deps.
  Config at `data/trends/feeds.yaml`. CLI: `memegine trends
  add-feed/list/fetch`.
- **`exports_csv`** — dump archive, refs, or performance logs to CSV
  for Excel/pandas analysis. CLI: `memegine export-csv
  archive/refs/perf <dst>`.
- **`serve`** — start the Telegram bot AND the scheduler in a single
  process, with graceful SIGINT shutdown. One command, one tmux pane,
  one tail. CLI: `memegine serve`.
- **`morning_brief`** scheduler action — composes a daily intelligence
  drop (dashboard + last 48h journal + top perf formats + top queued
  topics) and delivers it via telegram/discord at a fixed time. Add
  with `memegine schedule add morning --hour 7 --action morning_brief`.
- **`prompt_fixer`** — auto-inserts fragments to plug missing craft
  categories in a weak prompt and reports the score delta. CLI:
  `memegine fix-prompt "<prompt>"`. Bot: `/fix_prompt`.
- **`refs add --winner --auto-variants`** — post-winner compounding
  shortcut: when a winner is logged, automatically enqueue N axis-
  varied re-shoot intents as topics so the next session builds on
  what just worked.
- **`like_winner`** — "do it again, a little different." Takes a new
  intent, extracts the craft tokens (lens / film / lighting / time /
  composition) from the most recent winner's prompt, and composes a
  ready-to-paste Grok prompt that inherits the same look. CLI:
  `memegine like-winner "a CEO on a rooftop"`. Bot: `/like_winner`.
- **`style_codex.init_template`** — seeds a blank codex with every
  expected section (North Star, Voice & Tone, Visual DNA, Proven
  Patterns, Compounded Patterns, Core Patterns, Weekly Distill, Kill
  List, Voice Notes). CLI: `memegine codex init`.
- **`last`** — show the most recent brief, winner, post, and session
  in one view. The "where was I?" command. CLI: `memegine last`.
  Bot: `/last`.
- **`search`** — unified substring search across briefs, refs, posts,
  codex entries, and topics. Answers "when did I brief this?" /
  "which winner was about X?". CLI: `memegine search "<query>"`.
  Bot: `/search`.
- **`format_health`** — classifies each format as healthy / watch /
  candidate-for-deprecation based on average engagement vs. the median
  across formats. Flags under-performers once they have ≥ 5 posts of
  data. CLI: `memegine format-health`.
- **`flow morning` / `flow evening`** — convenience bundles. `morning`
  opens a session + prints the `next` dashboard + prints last activity.
  `evening` closes the session, runs codex distill, prints daily stats.
- **`env`** — prints every memegine env var with secrets masked.
- **`archive`** — every brief saved to `data/logs/briefs-YYYY-MM-DD.jsonl`;
  `memegine history` surfaces them
- **`pipeline`** — one command, one folder, every brief for a whole piece
- **`reference_lib`** — local tagged library of your winners, indexed JSON
- **`style_codex`** — living markdown doc of winners + kill list + visual DNA
- **`editor`** — FFmpeg wrappers: probe, to_aspect, ken_burns, concat,
  crossfade, drawtext, add_audio, speed
- **`image_ops`** — PIL wrappers: to_aspect, caption (auto-sized Impact
  style), grid, two_panel, blur_background_portrait
- **`grading`** — 10 filmic color presets via FFmpeg (cinestill_800t,
  portra_400, tri_x_bw, teal_orange, moody_film, kodachrome, golden_hour,
  neon_night, faded_print, bleach_bypass)

### The data

- **`data/formats/library.yaml`** — 20 format templates (photoreal_portrait,
  meme_two_panel, drake_yes_no, photoreal_scene_motion, lore_drop,
  cope_chart, npc_wojak_row, split_screen_then_now, photoreal_product_shot,
  photoreal_street_scene, reaction_shot_meme, fake_news_headline,
  video_single_take_reaction, video_kenburns_still, photoreal_self_avatar,
  screenshot_terminal, ticker_scroll_overlay, found_footage_still,
  zine_pullquote, vhs_ad_spoof)
- **`data/playbooks/`** — four craft bibles Claude reads on every brief:
  - `grok-imagine-patterns.md` — prompt craft for Nano Banana / Aurora /
    Ideogram / Flux via Grok
  - `video-img2vid-patterns.md` — img2vid and shot recipes
  - `meme-typography.md` — text-on-image rules
  - `x-content-playbook.md` — caption patterns, cadence, what works on X
- **`data/codex/style.md`** — your living style memory (empty skeleton to
  start; grows every session)
- **`data/references/`** — your tagged reference library (local, .gitignored)
- **`data/outputs/`** — pipeline bundle folders per piece (.gitignored)
- **`data/logs/`** — archived briefs JSONL per day (.gitignored)

---

## Install

```bash
cd memegine
pip install -e .              # core, offline-only
# optional:
# pip install -e '.[online]'    # adds Anthropic SDK for programmatic use
# pip install -e '.[telegram]'  # adds python-telegram-bot (bot + scheduler push)
# pip install -e '.[dev]'       # adds pytest
```

**Requires**: Python 3.10+, FFmpeg on PATH (for the editor module).

---

## Commands

### Brief generation
```bash
memegine formats                                   # list 14 formats
memegine prompt "<intent>" -f <format>             # one brief, printed
memegine shots "<intent>"                          # shot-list brief for video
memegine copy "<concept>" --kind image|video      # X caption brief
memegine pipeline "<intent>" --kind image -f <fmt> # bundle (brief + copy)
memegine pipeline "<intent>" --kind video          # bundle (shots + copy)
memegine variants "<winning prompt>" -n 6          # variant brief
memegine reverse <image.png> --context "..."       # reverse-engineer a look
memegine lint "<prompt>"                           # catch banned words
memegine lint "<prompt>" --motion                  # lint motion prompts
```

### Style memory
```bash
memegine codex show
memegine codex winner "<prompt>" "why it worked"
memegine codex flop "<what>" "why"
```

### Reference library
```bash
memegine refs add <image> --tags "night,neon" --source grok --prompt "..." --notes "the one"
memegine refs search --tags "night,neon"
memegine refs recent -n 20
```

### Brief archive
```bash
memegine history recent -n 20
memegine history show <id>
memegine history search "<text>"
```

### Topic queue (trend intake → scheduled batches)
```bash
memegine topics add "trader dumping at 3am" --tags reaction,night --priority 4
memegine topics list
memegine topics pop -n 3                # take top 3, mark used
memegine topics stats
memegine topics remove <id>
```

### Scheduler (automated daily batches)
```bash
memegine schedule add morning --hour 8 --n 3 --kind any
memegine schedule add distill  --hour 23 --action weekly_distill --days 6  # Sunday
memegine schedule list
memegine schedule fire <id>             # manual trigger (use from cron)
memegine schedule run --poll 30         # blocking loop (tmux / screen)
memegine schedule run --telegram        # deliver results to your bot chat
```

### Format suggest & deep lint
```bash
memegine suggest "trader dumping at 3am" -n 3
memegine score "<prompt>"               # 0-100 craft-coverage score + tips
memegine score "<prompt>" --motion      # grades a motion prompt
```

### Idea grader (pre-brief landability score)
```bash
memegine grade-idea "trader at 3am, cope face, 12% drawdown"
# → grade A  score 100/100
```

### Live Claude execution (optional, requires API key)
```bash
export ANTHROPIC_API_KEY=sk-...
memegine execute "trader at 3am" --format photoreal_portrait
# → prints finished Grok-ready prompt + variants + captions directly
```

### Batch (N briefs, one theme)
```bash
memegine batch "the ETF flow number nobody reads" -n 4
# → data/outputs/<date>_batch_<slug>_<id>/01-photoreal_portrait.md,
#    02-meme_two_panel.md, 03-reaction_shot_meme.md, 04-lore_drop.md
```

### Caption lint
```bash
memegine caption-lint "it's 3am and no one is home"
# → PASS, score 100/100
memegine caption-lint "🚀 gm wagmi #crypto"
# → FAIL, 4 errors
```

### Activity report
```bash
memegine stats daily
memegine stats weekly
memegine stats all
```

### Discord webhook (scheduler delivery alternative to Telegram)
```bash
export MEMEGINE_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
memegine discord-test "webhook is live"
```

### Topic → bundle convenience
```bash
memegine from-topic <topic_id>       # builds a pipeline bundle, marks topic used
```

### Codex graduation (promote frequent patterns)
```bash
memegine codex graduate --threshold 5 --n 500
# → scans recent briefs, promotes lens/film/lighting seen >= 5 times
#   to 'Core Patterns' section at the top of the codex
```

### Doctor (health check)
```bash
memegine doctor
# validates data dirs, ffmpeg, format library, playbooks, codex, config
```

### Fragments (named reusable craft snippets)
```bash
memegine fragments list
memegine fragments show LENS.35mm_1_4
memegine fragments expand "Trader, LENS.35mm_1_4, LIGHTING.harsh_window, TIME_OF_DAY.3am"
# → fully expanded prompt, ready for Grok
memegine fragments validate "LENS.35mm_1_4 FILM.unknown_stock"
# → reports unknown tokens
```

### Variants from last winner (one-command compounding)
```bash
memegine variants-last -n 6
# → uses the prompt from your most recent ref tagged `winner`
```

### X posting (dry-run, no API)
```bash
memegine x prepare <post_bundle_id>
# → caption lint + media check + clipboard-ready block of every field
#   you need to copy into X on your phone, plus a manual posting checklist
```

### Codex audit (keep the style memory clean)
```bash
memegine codex audit
# → reports duplicate entries, contradictions (e.g. "use X" AND "avoid X"),
#   and heavy sections that should be distilled/graduated
```

### Batch execute (API-key only)
```bash
memegine batch-execute "a theme" -n 4 --by-perf
# → generates 4 briefs, runs each through Claude, lints the results,
#   returns the winner. Zero copy-paste for key-holders.
```

### Trend intake from external feeds
```bash
memegine trends add-feed nyt https://www.nytimes.com/svc/.../rss --kind rss --priority 3
memegine trends list
memegine trends fetch          # dry-run: --dry-run
# → new titles appended to the topic queue with source=trend:<feed-name>
```

### CSV exports (external analysis)
```bash
memegine export-csv archive exports/archive.csv --n 5000
memegine export-csv refs exports/refs.csv
memegine export-csv perf exports/perf.csv
```

### One-command serve (bot + scheduler in one process)
```bash
memegine serve --poll 30
# → runs both in the same process; Ctrl-C stops cleanly.
memegine serve --scheduler-only   # no Telegram bot, just the scheduler
```

### Performance-weighted batch
```bash
memegine batch "a theme" -n 4 --by-perf
# → picks formats ranked by performance.by_format() instead of the
#   default curated rotation. Falls back to default rotation when there
#   isn't enough engagement history yet.
```

### Morning brief (scheduled daily intelligence drop)
```bash
# schedule a 7am morning brief, pushed via the telegram chat
export MEMEGINE_TELEGRAM_CHAT_ID=12345678
memegine schedule add morning-brief --hour 7 --action morning_brief
memegine schedule run --telegram
# → every morning at 7am: dashboard + last 48h journal + top perf + top topics
```

### Quick recall
```bash
memegine last                           # last brief/winner/post/session
memegine search "3am kitchen"           # find across all stores
memegine format-health                  # which formats are performing?
memegine env                            # config check (secrets masked)
```

### Workflow shortcuts
```bash
memegine flow morning --name "afternoon-hero"
# opens a session + prints the dashboard + shows last activity

memegine flow evening
# closes session + distills codex + prints daily stats
```

### Like-winner (clone your last winner's craft)
```bash
memegine like-winner "a CEO on a rooftop"
# → inherits lens + film + lighting + time + composition from the
#   last `--winner` ref, appends photoreal negatives, returns a
#   full prompt + score + grade.
```

### Codex init (seed a fresh style codex)
```bash
memegine codex init
# → writes the default section template to data/codex/style.md.
#   `memegine codex init --force` overwrites an existing codex.
```

### Prompt auto-formatter (fix weak prompts)
```bash
memegine fix-prompt "a trader in a kitchen"
# → inserts LENS.35mm_1_4, LIGHTING.harsh_window, TIME_OF_DAY.dusk,
#   COMPOSITION.thirds_left, NEGATIVE.photoreal_defaults
#   score: 20/100 → 82/100
```

### Post-winner auto-variants (compound the winning loop)
```bash
memegine refs add winner.png \
  --winner --prompt "trader at 3am, 35mm, Cinestill 800T" \
  --notes "the quiet-dread one" \
  --auto-variants --n-variants 3
# → enqueues 3 re-shoot topics (varied TIME_OF_DAY, LENS, FILM_STOCK)
#   so next session inherits the winning thread
```

### Sessions, journal, and "next moves" dashboard
```bash
memegine session start "afternoon-hero"    # mark the start of a working block
memegine session current
memegine session end
memegine session list                       # history with durations

memegine journal --days 7                   # unified chronological feed
memegine next                               # "what should I make?" dashboard
```

### Performance tracking (close the feedback loop)
```bash
memegine perf log --likes 820 --rt 140 --replies 35 \
  --format photoreal_portrait --patterns "35mm f/1.4,cinestill 800t" \
  --posted-at 2026-04-18T03:12:00Z --url https://x.com/me/status/123
memegine perf summary        # by format, by pattern, by hour
memegine perf by-format      # sorted by avg engagement
memegine perf top -n 10      # top-N posts by score
```

### Post-ready export
```bash
memegine post build final.png \
  --caption "it's 3am and he is not ok" \
  --alt "portrait of a trader at 3am, neon + tungsten mix" \
  --tags reaction,night
memegine post list
# → data/posts/<date>_<slug>_<id>/final.png + caption.txt + README.md
```

### Codex (extended)
```bash
memegine codex auto-winner "<prompt>" "why it worked"   # logs + auto-extracts
memegine codex distill --n 200 --min 2                  # mine frequent patterns
```

### Telegram bot
```bash
# one-time setup
export MEMEGINE_TELEGRAM_BOT_TOKEN=...
export MEMEGINE_TELEGRAM_ALLOWED_USER_IDS=12345678
# optional: chat id for scheduler deliveries
export MEMEGINE_TELEGRAM_CHAT_ID=12345678

memegine bot config-check               # verifies env vars, doesn't start bot
memegine bot run                        # blocking polling bot

# In the chat (from your phone):
#   /piece <intent>                      auto-picks format, full bundle
#   /brief <intent> [f:<slug>]           image brief
#   /shots <intent>                      shot list
#   /caption <concept>                   X caption brief
#   /variants <n> <prompt>               variant brief
#   /suggest <intent>                    top 3 format picks
#   /lint <prompt>                       deep lint with 0-100 score
#   /topic <text>                        append to topic queue
#   /topics                              list queued topics
#   /codex                               show codex head
#   /winner <prompt> ||| <why>           log + auto-extract patterns
#   /flop <what> ||| <why>               log to kill list
#   /refs                                10 most recent refs
#   /reverse [context]                   reverse the next photo you send
#   <send a photo>                       → added to reference library
```

### Music-synced edits
```bash
memegine music beats <audio.mp3>                              # BPM + beats + estimated drop
memegine music plan <audio.mp3> "<intent>" <clip1> <clip2>    # ask Claude to plan the edit
memegine music hardcut out.mp4 music.mp3 a.mp4 b.mp4 c.mp4    # N clips, 1 cut per beat
memegine music build out.mp4 music.mp3 clips...               # accelerating cuts into a drop
memegine music slam out.mp4 music.mp3 clip.mp4 --slam 3.0     # slow-mo into a beat, snap
memegine music impact out.mp4 music.mp3 clips...              # flashes between cuts
memegine music reveal out.mp4 music.mp3 still.png --duration 8 # slow push on a still
memegine music trailer out.mp4 music.mp3 clips... --slam 6.0  # build + slam + held hero
memegine music transitions                                     # list transition presets
memegine music transition out.mp4 a.mp4 b.mp4 --preset flash_white
```

### Editor (the "no CapCut" layer)
```bash
memegine edit aspect <src> <dst> --ratio 9:16 --fit cover
memegine edit kenburns <image.png> <out.mp4> -d 5 -r 9:16
memegine edit concat <out.mp4> <clip1.mp4> <clip2.mp4> <clip3.mp4>
memegine edit caption <src> <dst> "HELLO WORLD" --pos bottom
memegine edit grade <src> <dst> --preset cinestill_800t
memegine edit presets
memegine edit speed <src> <dst> 2.0
memegine edit audio <src> <audio> <dst> --mode mix --volume 0.8
memegine edit grid <dst> <img1> <img2> <img3> <img4> --cols 2
memegine edit two-panel <top> <bottom> <dst>
```

---

## Claude Code slash commands

If you're using memegine through a Claude Code session (recommended), these
slash commands are faster than the CLI:

- **`/piece <intent> [--kind image|video] [--format <slug>]`** — the main
  command. One-shot from intent to a ready-to-post bundle.
- **`/brief <intent> [-f <format>]`** — just the image brief, Claude returns
  JSON directly in the session
- **`/shots <intent>`** — shot list for video
- **`/caption <concept>`** — X captions
- **`/reverse <image_path> [context]`** — reverse-engineer a look
- **`/batch <n> <theme>`** — batch produce N briefs across varied formats
- **`/codex-update <learnings>`** — update style memory after a session

---

## The rhythm (what using this actually looks like)

### Morning session (10 min)
1. `/piece reactive meme about the overnight news`
2. Paste the prompt into Grok, iterate 3-5 times, pick the winner
3. `memegine refs add <file> --tags reaction,news --notes "landed because..."`
4. Post caption from the brief

### Afternoon hero piece (30-45 min)
1. `/piece photoreal trader at 3am market dumping --kind image -f photoreal_portrait`
2. Execute in Grok. Take multiple generations. If text comes back garbled,
   regenerate image without text and `memegine edit caption` locally.
3. Refine aspect: `memegine edit aspect out.png final.png --ratio 9:16`
4. Grade: `memegine edit grade final.png graded.png --preset cinestill_800t`
5. `refs add` + `codex winner` to compound
6. Post

### Evening video piece (45-60 min)
1. `/shots slow push on a trader, market dumping, 5 seconds`
2. Generate hero still for each shot in Grok (still_prompt from the brief)
3. Animate each still via img2vid in Grok (motion_prompt from the brief)
4. `memegine edit concat out.mp4 shot1.mp4 shot2.mp4 shot3.mp4`
5. `memegine edit grade out.mp4 graded.mp4 --preset moody_film`
6. `memegine edit caption graded.mp4 final.mp4 "THE END" --pos bottom`
7. `memegine edit audio final.mp4 music.mp3 posted.mp4 --mode replace`
8. Post

### End of day (5 min)
1. `/codex-update <session notes>` — log what worked, what flopped
2. Your style memory is sharper for tomorrow

---

## Philosophy

- **Every piece is handmade.** The tool removes friction, never replaces
  judgment.
- **Style compounds.** Week 10 is sharper than week 1 because the codex +
  reference library + winning patterns all accumulate.
- **Never ships AI-slop words.** The linter fails prompts containing
  cinematic, epic, stunning, 4k, etc.
- **Names the craft.** Lenses, film stocks, lighting setups, camera moves —
  by name, not by adjective.
- **Captions that don't sound AI.** No emojis, no hashtags, no "gm/wagmi/
  lfg", no engagement-bait.
- **Offline-first.** No external API calls unless you opt in. Everything
  runs locally on disk.

---

## Testing

```bash
cd memegine && python -m pytest tests/ -v
```

Current: 110+ tests in the core (offline) path, plus editor/grading/music
FFmpeg-backed tests. Skip FFmpeg-dependent tests if FFmpeg isn't
installed (they auto-skip via pytest marker).

V2 test files:
- `test_topics.py` — topic queue (add, pop, stats, priority)
- `test_format_suggest.py` — intent → format ranking
- `test_deep_linter.py` — 0-100 craft-coverage score
- `test_auto_codex.py` — pattern extraction from winners
- `test_export.py` — post-ready folder layout
- `test_scheduler.py` — cron matching, daily batch, fire
- `test_telegram_bot.py` — bot module imports + helpers (no network)
- `test_idea_grader.py` — pre-brief landability scoring
- `test_executor.py` — Claude-powered live execution (mocked)
- `test_refs_winner.py` — --winner flag pattern compounding
- `test_new_formats.py` — V2 formats load + assemble cleanly

---

## Next steps (when you're ready)

- **Seed the codex** — fill `data/codex/style.md` with real voice notes.
  Your first 10-20 refs tagged and noted is the biggest unlock.
- **Extend formats** — add a new format when you find a pattern Grok nails
  reliably for you.
- **Train your eye** — save 20-40 reference images from top creators you
  admire. Run `/reverse` on them. Internalize the patterns.
- **Wire up the bot** — set `MEMEGINE_TELEGRAM_BOT_TOKEN` and allowlist,
  run `memegine bot run` in tmux. Now your brief pipeline lives on your
  phone.
- **Schedule a daily batch** — `memegine schedule add morning --hour 8
  --n 3 --delivery telegram`, then drop topics in throughout the day
  via `/topic` from your phone. Next morning, the bot delivers three
  briefs.
- **V3 ideas**: Discord integration for ref library, auto-posting to X
  via dry-run + confirm flow, reference vision-embedding search (local,
  via CLIP), idea grading (predict which topic will land before you
  run it).

---

## Directory layout (reference)

```
memegine/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── src/memegine/
│   ├── __init__.py
│   ├── cli.py                  # Typer entrypoint (memegine <cmd>)
│   ├── config.py               # pydantic settings
│   ├── prompt_engine.py        # brief assembly + playbooks + codex
│   ├── shot_list.py            # video shot-list brief
│   ├── copy_writer.py          # X caption brief
│   ├── variants.py             # variant brief
│   ├── reverse_engineer.py     # image → look prompt
│   ├── pipeline.py             # bundle (brief + shots + copy per piece)
│   ├── linter.py               # ban words + craft coverage
│   ├── archive.py              # briefs JSONL archive
│   ├── reference_lib.py        # local tagged library
│   ├── style_codex.py          # living style doc read/write
│   ├── editor.py               # FFmpeg ops (video + still)
│   ├── image_ops.py            # PIL ops (aspect/caption/grid/panel)
│   ├── grading.py              # 10 filmic color presets
│   └── claude_client.py        # optional Anthropic SDK wrapper
├── data/
│   ├── codex/style.md          # living style memory
│   ├── formats/library.yaml    # 14 format templates
│   ├── playbooks/              # 4 craft bibles
│   ├── references/             # your refs (gitignored)
│   ├── outputs/                # pipeline bundles (gitignored)
│   └── logs/                   # archived briefs (gitignored)
└── tests/
    └── test_*.py               # 61 passing tests
```
