# 🎛️ NUNU COMMAND CENTER
_Single source of truth. Last synced: **2026-10-11**_

> **Laptop = the factory** (analysis, code, content prep). **Desktop = live trading bot** (owns live ops).
> **Phone = the storefront** (10 hrs/day: posting + replying). Telegram is the conveyor between them.
> If a project isn't listed here with a location, it doesn't exist on this machine.
>
> **📱 Phone-readable version of this file: https://claude.ai/code/artifact/99e9aa9a-807a-41df-a815-aef414a550fe**

---

## ⚡ START HERE — the one next action

**Open Telegram, post the 12 Hello Kitty clips in the 🐱 channel.**

🔴 **The queue had been empty for 74 days and I did not notice.** `sent_to_phone.json` had not moved
since **2026-07-28**. Root cause: `send_clips_to_phone.py` crashed with `UnicodeEncodeError` printing
an emoji to a cp1252 console — at the line immediately *before* the send loop, so it authenticated,
picked clips, sent nothing, and **exited 0**. Nothing looked broken.

- **Fixed** at the console level (`e0f03ba` on `claude/tiktok-scraper-tool-hXD41`). Cannot recur for
  any other emoji in any other print.
- **Restocked:** 12 clips sent → **22 of 80 sent, 58 still staged.**
- **Top up with:** `cd ~/wagmi-project && py send_clips_to_phone.py --count 12`
  — then **verify** by checking `sent_to_phone.json` changed. A zero exit code proves nothing.

**Standing rule this violated:** keep the queue multi-day deep. A dry queue wastes the 10 best growth
hours of the day, and 74 days of them are gone.

### The bot needs nothing from you
It is flat on purpose — 19 trades since September against 274 before, all test-size, and that is
correct. The $190 loss since June was really **one month**: July −$317, June +$99, October +$66. I
checked whether any currently-blocked trade is worth taking: **none is.** Revisit in ~8 weeks when the
desktop's new data matures. Detail in `WAGMI/bot/data/laptop_mining/` (see `BLOCKED_PROPOSALS.md`,
`LONG_SIDE.md`, `CONF_FLOOR.md`).

---

## 🔴 ONLY NUNU CAN DO THESE (I'm blocked without you)

1. **Change the password `InstagramPassword1` anywhere else you use it.** It sat in a PUBLIC GitHub
   repo's history since April. I removed it from the code (commit `a9a4c8b`), but **git history still
   has it** — rotation is the only real fix. If it's reused on email or any exchange, do that first.
2. **Decide: make `github.com/Vince2kLyleStyle/wagmi-project` private?** It's public right now.
3. **Export Hyperliquid trade history from the desktop** → drop the CSV in `~/finances/`.
   Without it the finances ledger stays a template and I can't tell you what the bot actually did.
4. **Appeal the IG link restriction from your phone** — needs a "Confirm you're human" CAPTCHA that
   only you can complete. Do not let automation touch it.

---

## 📊 WHERE THE ANALYSIS STANDS (current as of 2026-10-11)

Everything lives in `WAGMI/bot/data/laptop_mining/`, branch `laptop-mining-2026-10`. The desktop reads
the same folder.

### What has actually survived review

| finding | number | status |
|---|---|---|
| **Crowded funding → bigger day, size down** | **+7.7%** vs forecast | survived 4 reviewers (`SIZE_FLAGS.md`) |
| **Crowded funding → stop hit more often** | **+12%** relative (21.7% → 24.4%) | survived 17 leave-one-out tests (`FUNDING_STOP.md`) |
| **Don't tighten the stop** | −0.13 to −0.20R at ½× | holds (`GEOMETRY_V3.md`) |
| **Funding persistence** | 83.2% → **99.3%** top quintile | survives clustering at z=4.8 (`M10_AUDIT.md`) |
| Squeeze column measures stretch, not agreement | — | relabelled live |

**The stop-width change was NOT shipped.** The fix works out to 2.9% wider — five basis points — so the
desktop warns on the planner instead. Size down on crowded-funding days; leave the stop alone.

### The facts worth remembering about the bot

- **The $190 loss was one month.** June **+$99**, **July −$317**, Sep −$38, Oct **+$66**.
- **It barely trades now, on purpose.** 274 closes Jun–Aug vs **19** in Sep–Oct, all test-size. Recent
  P&L carries no information.
- **No blocked trade is worth taking.** 0 of 22 groupings clears a credible bar — but *nothing proves
  they lose either*, and the number that looked like proof was two days of market drift
  (`BLOCKED_PROPOSALS.md`). **Flat is right by default, revisit in ~8 weeks.**
- **The long side is where the money went**: longs −$795 vs shorts +$605, same win rate. Already fixed
  in late July (`SIDE_LEVEL_EDGE`, `LONG_REGIME_VETO`) before the analysis existed. One trade is 33% of
  that loss (`LONG_SIDE.md`).
- **The benchmark**: the six traded coins rose a median **+20.3%** over the window. But that drift
  explains only ~10% of the loss — a 3-hour trade does not feel a four-month trend.

### ⚠️ All six never-reviewed docs are now audited (2026-10-11)

| doc | verdict |
|---|---|
| `FUNDING_CARRY.md` | finding survives clustering; **don't widen to 60 coins** — +9% info for 3.8× rows (`M10_AUDIT.md`) |
| `SAFE_LEVERAGE.md` | **use the p95 column** — p99 is a sample max from n=68, biased toward unsafe leverage (`M9_AUDIT.md`) |
| `LEVELS.md` | ma50 "support" **fails its own table's multiplicity**; cluster unit binds nothing (`M11_AUDIT.md`) |
| `MEMECARD.md` | **passes.** Best reasoning in the folder; one 2× wording fix (`M12_AUDIT.md`) |
| `CROSS_SECTIONAL.md` + `BASIS_TRADE.md` | right calls, but MDEs of 90–128%/yr — nulls are quieter than they sound (`NULLS_AUDIT.md`) |

**The recurring fault was never fabrication — it was confidence outrunning evidence**, in both
directions. A sample max called a 99th percentile, a cluster unit that didn't bind, six tests reported
as one, and three findings that were really "June was good and July was bad".

**Reworded accordingly:** the old "~98 directional tests with nothing surviving" line is misleading.
Honest version: *"98 directional tests, none finding an edge large enough to clear detection floors
that mostly sit above 90% annualised."* That describes the data available, not the market.

### Standing research rules (earned the hard way)
- Put the **equal-weighted block mean** next to every pooled figure.
- **Read the baseline prior work actually used** — never re-derive it from a description.
- Ask whether the result **could ever have come out negative.** This has now caught things *before*
  publication twice, not just after.
- **Never convert a mean-level effect into a threshold-level action analytically.** Solve for the
  threshold on the data — assuming linearity over-corrected by 2.7× on the funding stop.
- **A zero exit code is not evidence of success** for anything outward-facing. Check the side effect.

## 🟢 ACTIVE — the only three things that get energy

### P1 — WAGMI TRADING BOT ⚠️ LIVE WITH REAL MONEY
- **Location:** `C:\Users\vince\WAGMI` — laptop is on `laptop-mining-2026-10`; desktop owns
  `desktop-overdrive-2026-05-30`. **Never push to the desktop's branch.** All my work lands on mine
  and the desktop pulls from it; `bot/data/laptop_mining/` is the shared channel both machines read.
- **Config fact-check:** `bot/data/laptop_mining/CONFIG_AUDIT.md` — two of the three July-swarm knobs
  turned out not to say what the table below claimed.
- **Dashboard:** `WAGMI/web` (Next.js 14, ~18 pages) + API `WAGMI/bot/api_server.py`
  - Run: `cd WAGMI\bot && python api_server.py` (:8000), then `cd WAGMI\web && npm run dev` (:3000)
  - Runbook: `~/WAGMI_DASHBOARD_RUNBOOK.md`
- **🔥 THE OPEN ISSUE — validated fix was never applied.** July's swarm (29 agents, ~1.2M tokens,
  report `coordination/backtest_results/alpha_swarm_2026_07_19/FINDINGS.md`) found 1/15 strategies
  survived, and the real edge = encode the validated backbone. **All three knobs are still stock:**
  | Knob | File:line | Now | Verdict (re-checked 2026-10-08) |
  |---|---|---|---|
  | ~~`ENSEMBLE_CONFIDENCE_FLOOR`~~ | `bot/trading_config.py:476` | **20.0** (not 55) | **backtest-only knob** — live floor is adaptive, [20,80], starts 30 |
  | ~~`TIME_STOP_HOURS`~~ | `bot/trading_config.py:283` | 2 | **leave it** — see `EXITS_V2.md` |
  | ~~`ADX_MIN_TRENDING`~~ | `bot/trading_config.py:263` | 10.0 | **UNMEASURABLE — leave at 10.** `ADX_GATE.md` |
- **Caveat (do not skip):** swarm had no true out-of-sample. **Re-backtest before committing capital.**
- **✅ All three knobs are now closed — none is a pending action.** Two were wrong in this doc
  (stale line numbers, and a "current value" of 55 that had been 20 since July). The third,
  `ADX_MIN_TRENDING`, is **unmeasurable**: 14 weeks of signals cannot resolve it even at 0.40R, and
  gating at 60 would discard **92.5%** of signal flow. The July swarm's three recommendations are
  therefore all retired — not refuted, but not actionable either.
- **Uncommitted:** 41 modified tracked files (backtest results + `trading_config.py`). The 713
  untracked are mostly `__pycache__`/test scratch. Nothing lost, but unreviewed for 10 weeks.
- **Known trap:** strategy weight `"trend": 0.50` is flagged in-code as −$200, 18% WR, PF 0.15.

### P2 — INSTAGRAM @topcats.online 🐱 THE CONTENT PROJECT (promoted 2026-10-08)
_Was P3. Promoted because **X is retired** — see Archived. IG is now the only content channel._
- **🔴 THE QUEUE WAS DEAD FOR 74 DAYS — fixed 2026-10-11.** `sent_to_phone.json` had not moved since
  **2026-07-28**. Cause: `send_clips_to_phone.py` crashed with `UnicodeEncodeError` printing an emoji to
  a cp1252 console, at the line *before* the send loop — so it authenticated, picked clips, sent nothing,
  and **exited 0**. Patched at the console level (`e0f03ba`).
- **Queue state: 22 of 80 sent, 58 staged.** All **7 A-grade** clips are in the sent batch; the reserve
  is 40 B-grade and 18 ungraded.
- **Top up with:** `cd ~/wagmi-project && py send_clips_to_phone.py --count 12`, then **verify
  `sent_to_phone.json` changed.** A zero exit code proves nothing here.
- **🎀 Captions fixed (`d1ca9f2`).** `captions.py` was writing 514–639-char general-cat essays with
  general-cat hashtags — off-strategy, and Instagram truncates at ~125 chars so the hook was buried.
  `captions_hellokitty.py` leads with a 32–50 char hook, matches the footage, and uses Sanrio hashtags.
  **No performance claim** — there is no engagement data for this account; this is strategy alignment
  plus a truncation fix. The 12 already in Telegram still carry the old captions.
- **Supply is not the gap; delivery is.** 58 clips staged and nothing to produce.
- **🎀 HELLO KITTY ONLY.** popgak (57) + catsother (68) are off-strategy, not to be sent.
- Full detail in the P3 block below (location, the burned auto-poster, the working path).

### P3 — INSTAGRAM @topcats.online 🐱 — detail
- **Location:** `C:\Users\vince\wagmi-project` — branch `claude/tiktok-scraper-tool-hXD41`
  (lowercase-hyphen. `WAGMI PROJECT` is an old bot snapshot — not this.)
- **Account is HEALTHY.** 414 followers, ~24K views/mo as of July. Only restriction = "can't share
  links" (expired ~Aug 15 2026 — verify). Posting reels was never blocked.
- **☠️ THE EMULATOR AUTO-POSTER IS PERMANENTLY BURNED for this account.** IG silently holds
  `share_button` disabled forever — anti-automation flag from a 36/day burst. Diagnosed exhaustively
  (ui_dump confirmed, phone works, rottednunu works from the same emulator). **DO NOT RETRY IT.**
  Not a code bug. Nothing to fix.
- **✅ THE WORKING PATH = clips to phone.** `send_clips_to_phone.py --count N` → Telegram 🐱 channel
  → you post from your phone. Verify first: `py check.py`
- **Content runway:** `tiktok_videos/hellokitty` = **80 clips** (the only folder that matters now).
  popgak 57 + catsother 68 are off-strategy. 3 clips held in `_hold_pending_review/`.
- **⚠️ `.env` has `IG_USERNAME=godforbidyougot_motion`** — the pre-rebrand handle. Likely needs
  updating to the current one before any login-based script works.

---

## 🗄️ ARCHIVED — deliberately not getting energy

### ❌ X / Twitter @willumponchain — RETIRED 2026-10-08
Nunu has stopped using the account. **Do not restock the tweet queue, do not suggest X growth, do not
treat the 23 banked tweets or `tweets_x_to_phone.py` as live work.** Files stay at
`~/willumponchain/` and the 🎀/🐦 Telegram channels stay configured, but neither gets energy.
_(This supersedes "X = PRIMARY phone work", which was the standing priority since 2026-07-28.)_

Not deleted, just not on the board. Don't reopen without a reason.
- `~/finances/` — LEDGER.md + GAPS.md are **empty templates**. Blocked on your Hyperliquid + bank CSVs (see 🔴 #3).
- `~/WAGMI PROJECT/`, `~/projects/` — older snapshots of the bot/IG docs. Superseded.
- `~/textile-sales` (Apr), `~/crypto-site` + `~/CrazyonSol` ($CRAZY / crazyonsol.online, Jan),
  `~/LickedStats`, `~/JinVaultClone` — finished or abandoned web experiments. All clean/committed.
- `lylepinkard` — live Vercel project (created Jun 2026), never documented. Unknown purpose. Low priority.
- **`louis-lane` — PERMANENTLY DELETED 2026-10-04** at Nunu's request (unsafe). Local source, git
  history, memory file, and all references removed; verified zero copies across the user profile.
  Vercel project already gone. **Do not recreate.**

---

## 📲 PHONE ALERTS FROM THE BOT (new 2026-10-11)

The bot now tells you when it **cannot trade**. Alerts arrive in **Telegram Saved Messages** (not the
🐱 clips channel), within ~15 min, repeating every 6h, plus one "back to normal".

| alert | what it means | your action |
|---|---|---|
| **"bot DOWN"** | the process stopped | **nothing** — it is flat by design, so downtime costs ~nothing |
| **"AI DEGRADED, run /login"** | the LLM login expired; the bot **cannot place any trade** even though it looks healthy | **run `/login`** |

**Why it exists:** Sep 15–18 the bot was dead **3.3 days** (`auto_restart=False`, watchdog detected it
and nothing delivered the message) and Oct 5–7 the LLM login was expired for **3 days** while the
process reported healthy. Both were detected; **nobody was ever told.**

**Health is now checkable from here:** `server_exports/uptime.jsonl`, every 15 min —
`{alive, llm_ok, can_trade, scans, pid}`. **`can_trade` is the one that matters**; `alive` alone would
have read `true` straight through the October degradation.

**`auto_restart` stays False, deliberately.** A flat bot dying costs ~nothing; a crash-looping bot can
do real damage. Revisit only if there is a reason to trade again, and pair it with a restart-rate limit.

## 📌 STANDING RULES
- **Only ONE poster/watchdog process may run at a time, ever.** Duplicates collided in July and
  jammed IG's upload. Kill existing before launching.
- **Never run a second Claude against the desktop.** Desktop owns live ops + its own branch.
  Laptop never pushes to `main` or `desktop-overdrive-2026-05-30`.
- CLI subscription routing only — **never add `ANTHROPIC_API_KEY`**.
- "Nunu" in all docs, commits, and outputs. Never "Vince".
- Small commits, pushed often. No credential defaults in code — this repo is public.
- Keep the Telegram queue **multi-day deep**. A dry queue wastes your 10 best growth hours.
- **A gap in a log is rotation, a rolling window, or sync cadence until proven otherwise.** This nearly
  produced four wrong conclusions in one session. Check: does it rotate? is it a rolling window? what is
  the sync cadence? is the timestamp event-time or process-start time? Prefer files that never rotate
  (`trade_events.jsonl`, `trades.csv`) as liveness proxies. With an hourly sync, 60 min of staleness is
  normal — pick thresholds from the cadence, not by feel.
- **Verify the queue depth at the start of any session** — compare `sent_to_phone.json` against
  `~/wagmi-project/tiktok_videos/hellokitty/`, and check the json's mtime. It sat dead for 74 days
  because nobody looked. **Never trust an exit code for an outward-facing action; check the side effect.**

## 🧠 WHERE MEMORY LIVES (read this if a session feels lost)
Claude Code scopes memory per folder. **Always start sessions with `nunu` in a terminal** — it drops
you in `C:\Users\vince` where the real memory is. Launching from `C:\windows\System32` gives you an
empty memory dir and a blind session; that was the root cause of months of friction.
- `~/.claude/CLAUDE.md` — global, loads every session regardless of folder
- `~/.claude/projects/C--Users-vince/memory/` — main, 13 memories
- `~/.claude/projects/C--Users-vince-WAGMI-PROJECT-WAGMI/memory/` — trading archive, 140
- `~/.claude/projects/C--Users-vince-wagmi-project/memory/` — IG bot, 6

## 🔧 SHELL SHORTCUTS (new 2026-10-04)
| Command | Does |
|---|---|
| `nunu` | start Claude in the right folder, full memory loaded |
| `board` | open this file |
| `whatsrunning` | show live python/node processes |
