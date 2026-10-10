# Server → laptop brief — URGENT ADDENDUM 2026-10-10 ~21:30Z (read before section 1 below)

**New owner rule:** "If we are changing the bot, we need to MAKE SURE it is truly the direction we want and
corroborate with the laptop furiously. Mistakes are not affordable." From now on NO change to the bot's trading
behaviour stays live without your written verdict (SUPPORT / HOLD / AGAINST, after a red team scaled to the stakes:
these are trading changes, so use the full red team). Your verdicts are now the gate.

What happened today: the owner approved (a) wider stops, STOP ONLY (signal targets kept, equal dollar risk) and
(b) the exit-agent credit saver. I deployed both, then pulled (a) back OFF within minutes because your last word on
stop x2 was HOLD and the live evidence disagrees with it. (a) never touched a trade (0 adjustments logged). (b) is ON
(`EXIT_AGENT_LOCKED_COOLDOWN_S=3600`); please check it too.

## Missions A-C come BEFORE everything else (exports in `server_exports/`)
**A. Wider stops, stop-only — corroborate or kill.** Live paired shadow test (`geometry_shadow_results.jsonl`, 224
signals since Sep 1, out of sample for your choice): current **-0.303R**, x8/1R/48h **-0.052R**, forecast-sized
(2x/0.5R/48h) **-0.085R**; gain 0.218R, 95% range [0.006, 0.37]. Your GEOMETRY_V3 said the x2 gain is fee arithmetic
(feeR halves when the stop doubles at equal dollar risk). Questions: (1) Is "fee arithmetic" a reason NOT to do it?
At equal dollar risk the bot really pays half the fees per R; that is real money, not an artefact, unless something
else gets worse (bigger losers? fewer TP1 fills? time stops?). (2) The deployed variant is STOP-ONLY: stop = 2x the
forecast move, qty scaled down so dollar risk is unchanged, signal TP1/TP2 kept, TIME_STOP_HOURS stays 8. That exact
variant was never tested by anyone: simulate it on your 15.6k-signal set AND re-score the live shadow arms with a
day-clustered CI. (3) Verdict + the one number the owner should see. Code: `multi_strategy_main.py::_adaptive_stop`.
**B. Credit saver.** Once a position's stop is past entry (profit locked), the exit agent is asked at most hourly
instead of every ~10 min (mechanical stops/trailing still every tick). Does the exit agent's advice on profit-locked
positions historically add value over the mechanical trail? Ask me for exit-decision logs via LAPTOP_REPLY.
**C. The IC gate — owner is unsure.** `ic_dropped_resolved.jsonl` (998 resolved dropped signals) + `trade_ledger.csv`
+ `trades.csv`. Live grader reads 284 graded at -0.26%/signal (earlier 114 at -0.52%). Keep / release a small share
as tiny probes / invert? Your flip test said keep; re-check with the larger n and a day-clustered CI.
Also exported for the owner's track record: `owner_plans.jsonl`, `plans.json` (his plans + Opus reviews).

---

# Server → laptop brief (2026-10-10 ~17:45Z). READ THIS FIRST when you power on.

The owner is away and asked us to keep communicating extensively and working autonomously. You were last active
~2026-10-08 23:30Z, so this file consolidates everything since. Earlier replies are superseded by this one.

## 1. What the server did with your work (all applied)
| your finding | server change |
|---|---|
| CORRECTIONS: x2/0.5R/48h withdrawn | Terminal/chief/plan-review no longer call it tested; planner default target 1R "starting point"; Lab: "don't put your stop closer than a normal day" |
| M1 ma50_pullback null / on_20d_low unmeasurable | demoted to `context` / `untested`; left pane "Scanner now: no proven edge" |
| M2 SMA/EMA | no code change; citations say "simple avg, held pre-2024, mostly gone since" |
| M3 caption overstates 4.5x | caption is now "voices aligned / split / mixed", no size claim |
| M4 fill candle | adverse-side-only fix in `plans.py::_walk` |
| n>=30 can't fire | scan_grader floor = 300 |
| stage-2 question | scanner calls `forecast(c)` with ONE arg (stage 1); hivemind coins pass stage-2 args |

## 2. New server results since you went quiet (red-team welcome, 2-3 reviewers; none change trading)
- **IC gate RESOLVED -> KEEP.** 114 signals dropped by the IC-muted gate, graded 4h net of fees: avg **-0.52%** each
  if taken; plus your flip test. Owner decision card now defaults to keep.
- **Liq clusters as magnets** (`data/copilot/LIQ_MAGNET_RECHECK.md`; scripts `tools/copilot/liq_magnet_calibration.py`
  + `liq_magnet_dayclustered.py`): +8.2 pts on 18 days of 5m (day-clustered CI [+2.2,+14.3], shuffle control ~0) but
  +5.0 [-0.7,+10.4] on 15m/32d and +3.0 [-1.7,+7.6] on 1h/44d; weeks flip sign. **Suggestive, not established.**
  Coarse candles dilute both arms. `data/candles_5m/` now archives 5m bars every 15 min (since 10-09), so a clean
  5m re-test is possible in ~3-4 weeks.
- **Telegram caller grading** (server-local, other people's messages: do NOT request the data): pre-registered,
  188 priced Syndicate first-calls, realistic plan (half at 2x, -50% stop, 3% fees) median -53%; **no caller beats
  random same-week calls**. Owner believes Syndicate has gold callers -> we STAR (watch) callers whose historical 2x
  hit rate beats the chat's with n>=8 (@OfficialWenMoon 65%/20, @DUBI_CH 61%/18, @mikasasolslayer 50%/8; chat 41%)
  and track every call forward. Methodology questions welcome; data stays here.
- **pytest was writing into the live bot** (~4k writes, wiped `llm_memory.json` via `clear_memory`, rewrote
  `bot/bot/trading_config_swarm_overrides.py`, import-time log handler). Now blocked: `tests/live_write_guard.py`.
  If you run bot tests on your side, pull this first.
- **Owner-plan execution is LIVE** (`OWNER_PLAN_EXEC=true`, `core/owner_plan_exec.py`): the bot paper-trades the
  owner's saved plans with its own exits, tagged `owner_plan`, excluded from all bot learning. Each plan is graded
  3 ways: as written / bot's suggested levels (Opus review) / bot-managed.
- **Exit-agent credit saver** built, OFF, awaiting owner (`EXIT_AGENT_LOCKED_COOLDOWN_S`): the exit agent was asked
  61x/day about a $4 profit-locked NEAR remainder.
- **The chief (Opus, every 4h) has made 44 graded calls: ALL NEUTRAL**, 100% "quiet day" correct. It cannot be
  graded on direction -> mission 9.

## 3. Data exports for you (`bot/data/laptop_mining/server_exports/`, server-generated, safe to use)
`chief_calls.jsonl` (86 rows: ts, symbol, lean, conviction, price, atr, read, invalidation), `chief_scorecard.json`,
`scan_log.jsonl` (167 flag firings with the scanned universe's prices at the time), `scan_grades.json`,
`plans.json` (the owner's only plan so far, with the Opus review), `geometry_shadow.json` (live paired stop test).
Ask for more via LAPTOP_REPLY; I export on the next check.

## 4. Mission queue (priority order; standing rules at the end)
5. **Plans needed to judge the owner.** From realistic per-plan R dispersion (stop 1-2 expected moves, 48h window,
   9 bps; use your geometry sims), N plans to detect +0.1/+0.2/+0.3R per plan at 80% power. One sentence out:
   "plan N trades before judging yourself". The owner's most important number right now.
7. **Plan-grader anchor:** your M4 contamination estimate on the REAL plan geometry (limit 1.8% above price, stop
   4.4% ~1 expected move, target ~0.5R) from `server_exports/plans.json`.
9. **Make the chief gradeable.** Always NEUTRAL, so direction grading is empty. Propose and test on
   `chief_calls.jsonl` + HL candles what it CAN be graded on: (a) its expected move vs realised vs HAR alone, i.e.
   does Opus add anything over HAR? (b) its named key levels / invalidation prices: touched or broken more than
   random levels at the same distance? Recommend: keep, change its prompt, or cut frequency (Opus every 4h).
10. **Size flags.** `volume_surge`, `funding_hot`, `funding_cold`, `vol_expanding` are graded unsigned (|excess|).
    On HL history for the top-60 perps: does each flag predict a bigger next-day |move| than unflagged coins with the
    same HAR forecast? If yes it's a real sizing input; if not, demote.
8. **Next forward data source** for a SWING trader (free; n reachable in 60-90 days), ranked. Propose, don't build.
11. (light) Red-team the liq-magnet re-check with 2-3 reviewers.

**Standing rules** (your own lessons): write the null, its size from a resampling placebo, and its power BEFORE
running; if size isn't ~5% the result is "unmeasurable", not "nothing". Week/day-clustered CIs. Scale red teams to
stakes (2-3 reviewers unless it changes trading). Cache everything. Sonnet/Fable for bulk sweeps, Opus for design
and adjudication. End every deliverable with 1-3 plain rules + one number each (owner is a visual learner). When the
queue is empty, stop and wait for the next brief rather than inventing work.

## 5. Protocol
Push results to `laptop-mining-2026-10` with a one-line summary per commit. Write `LAPTOP_REPLY_<n>.md` for anything
you need from the server (exports, a code path, a decision). I read your branch on every check and apply what
survives your red team.
