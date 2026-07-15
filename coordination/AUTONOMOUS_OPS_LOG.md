# WAGMI — Autonomous Ops Log

Claude is running this bot autonomously under `coordination/THE_STANDARD.md` v1.4 while Nunu is away.
Validated + reversible + flag-gated changes SHIP without approval (veto-after, revert line always given).
Only real-money flips / spending / irreversible actions wait for the owner.
**Skim newest entry first. Nothing here needs a reply.**

Quota discipline (non-negotiable): the shared Claude subscription is what the BOT trades on. Every tick
checks the bot's logs for 429 / "hit your limit" / OAuth errors FIRST; if the bot shows quota pressure,
the tick is monitor-only (no agent spawns). Heavy work uses **Fable** (cheapest tier); Opus/Sonnet are
reserved for synthesis and code. Leave the bot its headroom — quota exhaustion was half of the Jul 5-11 starve.

---

## 2026-07-13 ~01:15 UTC — Session start / autonomy engaged

**Bot health (verified):** ONLINE, pid 9364 (supervisor 8112, Task Scheduler "WAGMI-Bot"). Uptime 16.2h,
scan_count 2085, errors 0, `llm_first_degraded=false`, equity **$4935.82** (‑1.8% from $5025). Brain sharp —
exit agents actively reasoning (regime flipped bullish → flagging shorts as thesis-invalidated).
Health signal = `bot/logs/bot_YYYYMMDD.log` + `bot/data/heartbeat.json`. **Do NOT trust `decisions.jsonl`
freshness** (live path logs via coordinator, not that file).

**Open positions (3 live):** HYPE SHORT @66.91, XRP SHORT @1.0975 (137), SOL LONG @77.43 (1.2). ETH flat (qty 0).

**Shipped this session (live in prod as of the 09:00 UTC Jul 12 daily restart):**
- **Runtime LLM-degrade detector** (`bot/multi_strategy_main.py` `_note_llm_pipeline_health`). After N consecutive
  "LLM pipeline failure" skips it sets heartbeat `llm_first_degraded=true` + a loud Discord/Telegram alert
  (names both auth-expiry AND quota/429), auto-recovers after M good decisions. Fixes the invisible Jul 5-11
  starve. Hardened per adversarial review (thread-lock, recovery hysteresis, honest text). Corroborated by
  Fable (facts) + Sonnet (code). **Revert:** `LLM_RUNTIME_DEGRADE_DETECT=false`. Tunables: `LLM_RUNTIME_DEGRADE_STREAK`
  (3), `LLM_RUNTIME_RECOVER_STREAK` (2).

**Corroborated findings (2 independent Claudes):**
- Jul 5-11 starve root cause = TWO phases: quota/429 (Jul 5→7) then OAuth expiry (Jul 7→11). Now restored.
- V-TRUE A/B verdict is **BLOCKED**: treatment arms C1t-C5t died at the Jul-3 429, C6t never created (0/6).
  Needs a full treatment-campaign re-run = heavy shared-quota spend → **DEFERRED** (won't starve the bot for it).
- Depth stream carries real edge: `spread_bps` 4h IC **+0.278, 5/5 symbols** (reproduced). Bot already ingests
  depth (`coordinator.py:194,500`). Highest-EV intertwining candidate — validate before wiring into decisions.

**Observations flagged for owner (no autonomous action taken):**
- Exit-engine 0.80-confidence gate held a regime-invalidated HYPE short (exit agent wanted close at 0.75 conf).
  Gate is backtest-backed (`BT_EXITAGENT_CLOSES` value-negative below 0.80). Possible calibration tension when
  regime *explicitly* contradicts the thesis — worth a look, but it's a validated capital-safety threshold so
  I'm not touching it unattended.

**Plan while you're away:** (1) keep the bot alive + catch any outage loudly; (2) Fable builds a ranked,
validated, reversible, quota-cheap improvement backlog; (3) I implement the top items flag-gated and log each
here with its revert line; (4) hold anything irreversible or quota-heavy for you.

---

## 2026-07-13 ~01:25 UTC — Fable backlog in; shipped collector-staleness alert (#2)

**Health recheck:** healthy, no quota pressure (no 429/OAuth in recent logs). Equity $4935.82, 3 live positions.

**SHIPPED — Collector staleness alert** (Fable backlog item #2; alert-only, zero trading-path contact):
`bot/multi_strategy_main.py` — new `_check_collector_freshness()` + `_collector_last_age_min()`, called from the
heartbeat daemon (signal-independent, throttled 5min). Alerts (Discord/Telegram, fresh↔stale hysteresis) when
`market_depth_history.jsonl` (`ts`) or `funding_oi_history.jsonl` (`timestamp`) goes >45min stale. Protects the
highest-IC, **non-backfillable** datasets — precedent: funding collector died silently 536h (H61), and the
depth collector (Task Scheduler `WAGMI-MarketCollector`) had zero alerting.
- **Validated (LLM-free):** py_compile OK; standalone functional test passed — real files read fresh (depth 6.1m,
  funding 15.1m → no false alarm), synthetic stale=200m detected, missing/garbage-line handled, hysteresis fires
  once per episode. Test: `scratchpad/test_collector_fresh.py`.
- **Revert:** `COLLECTOR_STALE_ALERT=false`. Tunables: `COLLECTOR_STALE_DEPTH_MIN`/`_FUNDING_MIN` (45),
  `COLLECTOR_STALE_CHECK_S` (300). **Takes effect next restart** (daily 09:00 UTC).

**Fable opportunity backlog (ranked; work top-down in later ticks):**
1. **spread_bps → depth prompt with 7d-percentile context** (`market_depth.py` `format_depth_line`). VALIDATED:
   passes the project's pre-registered graduation gate at **1h** (n=1,180≥780, 5/5, era-stable); 4h on track,
   n=295, verdict ~Jul 29. Prompt-context only, flag `EXT_DEPTH_PCTILE_ENABLED`. **HOLD for adversarial review
   first** (touches the live decision prompt → my backtest-before-adding rule). ← next substantive ship.
2. ✅ DONE — collector staleness alert (this entry).
3. **Resolved skip-outcome stats into agent context** (`comprehensive_snapshot.py:694`). Mine the 74k resolved
   counterfactuals (pure-python) → per-reason/symbol-side {n, tp1_rate, avg_hypo_pnl}. Flag `SKIP_OUTCOME_CONTEXT`.
   Low risk (read-only context). Validate with the 14-day aggregation Fable already ran.
4. **Weekly no-LLM research auto-rerun** (Task Scheduler job cloning `WAGMI-MarketCollector`): lane_b IC +
   graduation gate + rq14 + skip-mine → dated reports. ~zero risk, matures the 4h spread_bps verdict automatically.
5. **RECALL block (F2), flag-OFF** (`llm/recall.py`, new). Inert until owner arms. Lower urgency.

**Explicitly NOT doing unattended (per Fable + THE_STANDARD):** maker-exits (new exit-path order code),
loosening any confidence floor / gate (cage is net-positive; RQ14), the exit-engine 0.80 gate (owner-gated),
wiring imbalance/funding/ls-ratio to prompts (killed at pilot; only spread_bps passed its gate), V-TRUE
treatment re-run (quota-heavy).

---

## 2026-07-13 ~02:16 UTC — Tick: healthy; commissioned adversarial review of backlog #1

**Health:** fresh heartbeat 02:15:50Z, uptime 17.3h, scan 2220, errors 0, `llm_first_degraded=false`, equity
$4935.49 (flat), 4 positions. Quota/auth scan CLEAN (no 429/OAuth/degrade/collector-stale). Brain active
(`Pipeline done action=proceed regime=trend consistency=1.00`, depth injecting). No position closes since last tick.

**Action:** did NOT ship this tick (correct gate discipline). Launched a **Fable adversarial review** to try to
REFUTE the spread_bps graduation claim before it touches the live decision prompt — attacking look-ahead/leakage,
overlapping-window inflation vs the pre-registered TABLE_B gate, era-stability on an ~11-day sample, multiple-
testing (28 tests scanned), and prompt-change harm (horizon mismatch: spread may predict short-horizon reversion
while the bot holds hours). Will implement #1 flag-gated ONLY if the review returns HOLDS; else fall to #3/#4.

---

## 2026-07-13 ~02:35 UTC — Review REFUTED #1; killed it; hardened the research tool instead

**Health:** unchanged/healthy (see prior tick). No new positions/closes.

**Adversarial review verdict on backlog #1 (spread_bps → prompt): REFUTED.** The gate arithmetic was honest but
the feature is a **price-level confound**: dollar spread is pinned at the min tick 78-98% of the time → spread_bps
≈ 1/price. Its "IC" is just "price near range-low → bounced" (short-horizon mean-reversion in an 11-day range),
which INVERTS in a trend. Shipping it would have injected an unvalidated buy-the-dip bias and misled the regime
agent (tightest 1-tick book misread as "low liquidity"). **#1 KILLED — will not ship.** (This is the review gate
doing its job — it caught a confound my own initial read missed.)

**SHIPPED instead — confound controls in the research tool** (`bot/tools/research/lane_b_newstream_ic.py`, zero
trading risk): added `inv_mid` (=1/price proxy) and `spread_dollar` (raw $ spread, price-level removed) to the IC
scan + a docstring warning. Now every run exposes the confound. **Validated:** compiles + run reproduces the
kill-shot — inv_mid IC +0.295/+0.169 (4h/1h) *beats* spread_bps +0.267/+0.140, spread_dollar IC ≈ 0 (p 0.26/0.38).
Revert: remove the two `inv_mid`/`spread_dollar` entries from `FEATURES` (additive/harmless; no env flag needed).
Memory corrected so no one re-chases this. **Net: no depth feature has graduated — the intertwining play needs a
genuinely price-orthogonal signal, defined in ticks not bps.**

**Backlog reprioritized:** #1 DEAD. Next candidates — #4 (weekly no-LLM research job; but must first add the
price-level control to any auto-run so it can't re-institutionalize the confound — now done in the script) and #3
(resolved skip-outcome context into prompt; needs its OWN adversarial review before shipping, same as #1 did).

---

## 2026-07-13 ~03:30 UTC — Shipped #4 (weekly no-LLM research job); HYPE short closed a clean win

**Health:** fresh heartbeat 03:26Z, uptime 18.4h, scan 2370, errors 0, `llm_first_degraded=false`, equity $4932
(flat). Positions 4→**1**: the exit agent closed the HYPE short (`LLM_EXIT_AGENT @66.72, CLEAN_WIN +$0.19`,
thesis invalidated as consensus_confidence collapsed to 0.05). Quota/auth/stale scan CLEAN.

**Usage snapshot (owner asked to "get calculated"):** bot made ~174 pipelines + ~310 exit-agent calls today ≈
**~1,180 LLM calls/day** — that's the real quota driver. `$` cost tracker ($0.056 today) is BLIND to CLI/
subscription usage (no token reporting) → measure by call volume, not dollars. **0 × 429 today.** Biggest free
lever remains throttling the exit agent (~310/day, every position every scan) — owner-gated (touches exit timing).

**SHIPPED — weekly LLM-free research job** (Fable backlog #4; zero trading risk, read-only, no quota):
- New `bot/tools/research/weekly_research.py` — defensive subprocess wrapper (each analysis timeboxed, one failure
  can't abort the rest) running the confound-safe `lane_b_newstream_ic.py` + `rq14_cf_model.py`, writing dated
  reports to `bot/data/reports/weekly_research_YYYYMMDD.md`.
- Registered Task Scheduler job **`WAGMI-WeeklyResearch`** (weekly Sun 05:00 local, State=Ready).
- **Validated (LLM-free):** both sub-scripts confirmed LLM-free + headless-clean (rq14 exit 0: confidence AUC
  0.48 ≈ coin-flip, per RQ14); wrapper compiled + ran end-to-end (exit 0), report written. This matures the 4h
  spread_bps verdict (~Jul 29) and RQ14 automatically — with the inv_mid/spread_dollar confound guard baked in.
- **Revert:** `schtasks /delete /tn WAGMI-WeeklyResearch /f` (or `Unregister-ScheduledTask WAGMI-WeeklyResearch`)
  + delete `bot/tools/research/weekly_research.py`.

**Backlog remaining:** #3 (resolved skip-outcome stats → agent prompt) — touches the live prompt, so it needs its
OWN adversarial refute-review before shipping (same gate that killed #1). #5 (RECALL block, flag-OFF) low urgency.
Pattern noticed: prompt-touching items keep getting gated/refuted; the reliably-shippable-unattended work is
observability/tooling (like #2, #4). May pivot next backlog toward more of that.

---

## 2026-07-13 ~04:31 UTC — Tick: healthy, +2 clean wins; commissioned #3 adversarial review

**Health:** fresh heartbeat 04:30Z, uptime 19.5h, scan 2503, errors 0, `llm_first_degraded=false`, equity $4932
(flat), positions 1→4 (new entries). **Wins:** XRP short hit **TP2 +$2.60 CLEAN_WIN** (03:15); HYPE short closed
+$0.19 (prior tick). **New trade:** BTC SHORT @ $62,816 (LLM-FIRST, thesis "downtrend toward $61.8k") at 04:00.
**Usage:** 197 pipelines + 337 exit calls today, **0× 429**. Quota/auth/stale scan CLEAN. Bot is trading on-merit
and the exit/TP machinery is banking clean wins — operating as designed.

**Action (no ship — gate discipline):** launched a **Fable adversarial refute-review of backlog #3** (inject
resolved skip-outcome stats into the live prompt). Attacking: leakage/validity of the counterfactual outcomes,
selection bias (resolved vs pending), regime-artifact/era-stability of the standout cells, multiple-testing across
symbol×side×reason cells, and THE key risk — a **perverse incentive**: surfacing "your skips missed wins Y%"
without full EV/fee framing could nudge the LLM to stop skipping genuinely -EV setups → more fee bleed (skips are
net-CORRECT overall, -0.18%/skip; cage saved ~$194/mo per TABLE_C). Will ship only if it HOLDS with a safe framing.

---

## 2026-07-13 ~04:35 UTC — #3 REFUTED; found a live-impacting resolver bug (filed for owner)

**Health:** unchanged/healthy (verified 04:30Z this tick: uptime 19.5h, errors 0, degraded=false, equity $4932,
0×429). Bot trading fine.

**#3 (skip-outcome → prompt): REFUTED, killed.** The cited stats were the last-14-day slice (RESOLVED_MEMORY_DAYS=14)
mislabeled as 74k; every standout cell flips sign across era-halves (momentum snapshot, not learning); the payload
lacked fee/EV framing → perverse incentive nudging toward longs (proven drain) + higher frequency (proven -EV).
Cannot be rescued by framing today (an honest n≥200 + era-stability + fee gate empties the table).

**BIGGER FIND — counterfactual resolver bugs (⚠️ OWNER DECISION, NOT fixed):** the review surfaced real defects
in `bot/llm/counterfactual_learner.py`, chiefly a **bar-counting bug** (`MAX_TRACKING_BARS=48` "48h" is really
~9h median — `is_new_candle` fires on any high/low change within a forming candle) that **also corrupts graduated-
rule veto outcome scoring** (`record_veto_outcome` :553-576) — i.e. it biases which learned vetoes arm/retire,
which gates live trades. Plus same-candle look-back leakage, optimistic TP1/SL tiebreak, contaminated resolved set
(812 forced-zero + 4,685 dupes + 41 test rows), and gross (no-fee) pnl. **Filed full report + proposed fix order
in `coordination/RESOLVER_AUDIT_2026-07-13.md`.** Not touching it unattended — it changes live veto behavior, needs
your OK + a backtest. This is now the **top owner-decision item**.

**Pattern confirmed (2/2):** every prompt-touching backlog item (spread_bps, skip-outcome) has been REFUTED by
adversarial review — both were regime-artifacts dressed as edges. Pivoting: the reliably-shippable-unattended work
is observability/tooling (like #2, #4). Prompt/behavior changes go on the owner queue, not the auto-ship path.

---

## 2026-07-13 ~05:38 UTC — Tick: healthy (+1 clean win); commissioned fresh zero-risk backlog

**Health:** fresh heartbeat 05:37Z, uptime 20.6h, scan 2645, errors 0, `llm_first_degraded=false`, equity $4933
(flat), positions 4. SOL short closed **CLEAN_WIN +$1.61** (trailing stop locked profit above entry). **Usage:**
208 pipelines + 353 exit calls today, **0× 429**. Quota/auth/stale scan CLEAN.
(Note: #2 collector-stale alert is on disk but not yet live — no restart since it shipped; goes live at the next
daily restart ~09:00 UTC. Expected/tracked.)

**Action:** original backlog's zero-risk items are exhausted (#2, #4 shipped; #1, #3 refuted). Commissioned ONE
Fable pass for a fresh ranked batch of ZERO-trading-risk-only candidates (observability/tooling/alerting/analysis/
docs) to feed several future ticks — explicitly instructed to say if the high-value well is DRY so I lengthen
cadence instead of shipping make-work, and to sanity-check the two shipped alert methods are correctly wired.

---

## 2026-07-13 ~05:47 UTC — Shipped #1: external watchdog now RUNNING (closes silent-death gap)

**Health:** healthy (status one-shot: heartbeat 11s old, pid 9364 alive, 4 SHORT positions HYPE/BTC/XRP/ETH,
equity ~$4933). 0×429.

**Fresh Fable backlog returned** (zero-risk only): 2 genuinely valuable items (#1 watchdog, #2 daily digest), both
fixing the same truth — *if the bot dies/degrades while owner is away, the failure mode is SILENCE*. Also
sanity-checked my two shipped alerts: both correctly wired (one noted residual blind spot below). Beyond #1-#4 the
well is thin (heartbeat field-stuffing = churn once #2 exists) → will lengthen cadence after these.

**SHIPPED — #1 external watchdog** (alert-only, zero trading contact): `bot/watchdog.py` already existed complete
but was NEVER SCHEDULED. Registered Task Scheduler job **`WAGMI-Watchdog`** (at-logon trigger — user context, no
elevation; -AtStartup was Access-denied) and **started it now** — process live PID 9976, log confirms
`monitor started: check_interval=60s, stale_threshold=300s, auto_restart=False`. If the bot/supervisor dies or
heartbeat goes stale >5min → Telegram alert (10-min throttle, recovery msg). `.env` verified NOT to force
AUTO_RESTART (stays alert-only — never touches the bot).
- **Validated (LLM-free):** `watchdog.py status` reads healthy; `.env` AUTO_RESTART unset; task Running; process
  running; watchdog.log shows healthy monitor loop. Did NOT fire a forced false "BOT DOWN" test (would alarm the
  owner) — alert path is code-verified.
- **Revert:** `Unregister-ScheduledTask -TaskName WAGMI-Watchdog -Confirm:$false` + `Stop-Process -Id <watchdog pid>`.

**Owner-queue additions (from Fable's wiring review — do NOT act unattended):**
- `_note_llm_pipeline_health` residual blind spot: if `coordinator.get_entry_decision()` *raises* (import error/
  crash) instead of returning a "pipeline failure" skip, it re-raises before the health call → that failure class
  doesn't increment the streak. The Jul 5-11 auth-starve (skip-thesis path) IS covered; this is a narrower gap.
  Fix touches the decision-path exception flow → owner queue.
- `_send_daily_summary`/evolution daily reports fire on a broken `% 1440` cadence (assumes 60s ticks; real ~28s +
  resets on restart). Don't fix in-place (evolution block feeds LLM memory/tuner = trading path) — #2 daily digest
  routes around it externally.

---

## 2026-07-13 ~06:57 UTC — 🚨 CRITICAL: bot has NO WORKING ALERT CHANNEL; shipped #2 digest (writes to file)

**Health:** healthy (heartbeat 0m, uptime 21.9h, equity $4936, 5 shorts, 0×429). Today 7 trades (4W/3L), PnL
−$2.54.

### 🚨 TOP OWNER ITEM (discovered this tick) — NO OWNER-ALERT CHANNEL IS CONFIGURED
While wiring the digest's Telegram send, found `bot/.env` has **empty** `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, AND
`DISCORD_WEBHOOK` (under a `# Alerts (not configured yet — TODO)` comment). No secrets file, supervisor doesn't
inject creds, `python-dotenv` isn't installed, and the bot log shows no alert delivery. **Consequence: every alert
the bot tries to send — the shipped `_note_llm_pipeline_health` degrade detector, `_check_collector_freshness`, the
new watchdog, ordinary market updates — goes NOWHERE.** If the bot dies/degrades while the owner is away, they get
**silence**. I cannot fix this unattended: it needs a secret only the owner has. **ACTION FOR OWNER (2 min, fixes
ALL alerting at once):** add ONE of these to `bot/.env` — a Discord webhook URL (`DISCORD_WEBHOOK=…`, easiest) or a
Telegram bot token + chat id (`TELEGRAM_TOKEN=…`, `TELEGRAM_CHAT_ID=…`). The moment one is set, the watchdog +
digest + all in-bot alerts start delivering (no restart of the bot needed for the external tools).

**SHIPPED — #2 external daily digest** (`bot/tools/daily_digest.py` + Task Scheduler `WAGMI-DailyDigest`, daily
15:00 local; read-only, zero trading contact): equity/uptime/heartbeat-age/degrade, today W-L/PnL, LLM call
volume, CB state, collector staleness, open positions. Because there's no push channel, it **always writes
`data/reports/daily_digest_latest.txt`** (+ appends `daily_digest_log.txt`) — the working channel while away (read
via ops log / phone Claude); it also pushes Telegram+Discord *if* configured. Verified: runs clean, file written,
correctly reports "no push channel." **Revert:** `Unregister-ScheduledTask WAGMI-DailyDigest -Confirm:$false` +
delete `bot/tools/daily_digest.py`.

**Fixed en route (zero trading risk):** neither the digest nor `watchdog.py` could read `.env` (python-dotenv not
installed → bare Task Scheduler processes had no creds). Added a dependency-free inline `.env` parser to BOTH
(`daily_digest.py`, `watchdog.py`). Restarted the watchdog (PID 2564) to load the fix — so it can actually deliver
once a channel exists. **Corrected status of last tick's #1:** the watchdog is *running* but was (and is, until a
channel is set) unable to DELIVER — infrastructure ready, delivery blocked on the missing cred above.

**All 6 WAGMI scheduled tasks:** Bot (Running), Watchdog (Running), MarketCollector, LogRotate, WeeklyResearch,
DailyDigest (Ready).

---

## 2026-07-13 ~08:00 UTC — Shipped #3 (data-integrity report); +$6.87 HYPE win

**Health:** healthy — heartbeat 08:00Z fresh, uptime 23h, scan 2952, errors 0, degraded=false, equity **$4940.75**
(HYPE short closed **CLEAN_WIN +$6.87**), 4 positions, 0×429. Usage 216 pipelines + 419 exit calls. Watchdog alive.
Alert creds still empty (owner away). Daily bot restart ~09:00 UTC (≈1h out) — next tick confirms bot back + #2
collector-stale alert live.

**SHIPPED — #3 data-integrity report** (`bot/tools/data_integrity_report.py`; read-only, LLM-free, zero trading
contact; wired into `weekly_research.py` ANALYSES → runs weekly, no new task). Validated: runs clean and
**reproduces the RESOLVER_AUDIT contamination numbers** — counterfactual_resolved.jsonl: 74,368 lines / 69,636
unique / **DUPES 4,685** / test_rows 223 / unparsable 47 / zero_pnl 1,154; pending 323. Also surfaces:
trades.csv 146 vs trade_ledger.csv 212 (delta 66), and **disk 7% free (33GB/487GB)** — not urgent (LogRotate
manages logs) but now tracked weekly so the owner sees if it tightens. **Revert:** delete
`bot/tools/data_integrity_report.py` + remove its entry from `weekly_research.py` ANALYSES.

---

## 2026-07-13 ~09:05 UTC — Shipped #4 (scan-stall detector); backlog done → LENGTHENING cadence to 2h

**Health:** healthy — heartbeat 09:02Z, uptime 24h, scan 3090, errors 0, degraded=false, equity $4940, 4 pos,
0×429. Usage 221 pipelines + 453 exit. Watchdog alive. Creds still empty. (Daily ~09:00 UTC restart imminent —
next tick confirms clean cycle + #2 collector-stale alert going live.)

**SHIPPED — #4 scan-stall detector** (`bot/watchdog.py`, alert-only, watchdog is not the trading process): if the
heartbeat stays fresh but `scan_count` doesn't advance for `WATCHDOG_SCAN_STALL_MIN` min (default 45; 0=off), it
alerts "main loop hung, daemon alive" — closing the blind spot where a wedged scan loop looks healthy because the
heartbeat daemon thread keeps writing. **Validated (LLM-free):** py_compile OK; standalone logic test passed
(fires at threshold, 10-min re-alert throttle, resets on scan advance, off-gate silent). Watchdog restarted
(PID 7784) to load it. **Revert:** `WATCHDOG_SCAN_STALL_MIN=0` (or git-revert watchdog.py).

**ZERO-RISK BACKLOG COMPLETE.** Shipped this session: runtime LLM-degrade detector, collector-stale alert, weekly
research job (+confound controls +data-integrity report), external watchdog scheduling, daily digest (file+push),
scan-stall detector. Killed (adversarial review): spread_bps prompt, skip-outcome prompt. Per Fable's honest read,
the remaining zero-risk surface is churn. **→ Lengthening cadence to ~7200s (2h): monitor health, catch the daily
restart, watch for the owner adding an alert cred; only ship if a genuine new zero-risk need appears.**

**When owner returns — digest of everything since they left:** (a) 🚨 NO alert channel configured — add one cred to
bot/.env (top item, 2 min, turns on all alerting); (b) resolver bug corrupts live veto scoring
(RESOLVER_AUDIT_2026-07-13.md); (c) exit-agent ~450 calls/day = quota lever; (d) dedicated bot login for quota
isolation; (e) V-TRUE A/B verdict still blocked (treatment campaign never ran). Bot itself: healthy all session,
several clean wins (HYPE +$6.87, SOL +$1.61, XRP TP2 +$2.60), equity ~flat $4940, 0×429.

---

## 2026-07-13 ~10:07 UTC — MONITOR tick: healthy, nothing shipped

Heartbeat fresh 10:07Z, pid 9364, uptime **25.1h**, scan 3228, errors 0, degraded=false, equity $4940.75 (flat),
4 positions. Usage 230 pipelines + 476 exit. 0×429. Watchdog Running. Creds still empty.

**Correction:** the bot has NOT restarted (25h+ continuous uptime) — the "daily ~09:00 UTC restart" was a wrong
assumption (one-off/size-triggered log rotation, not a reliable daily cycle). So the queued **#2 collector-stale
alert stays inactive until a natural restart** (crash / manual / size-based rotation). Not forcing a restart on a
healthy bot managing live positions for a nice-to-have alert. Stop expecting a scheduled daily restart in ticks.

Nothing to ship. Steady state. Exit-agent volume ~476/day reinforces owner-queue item (2) throttle.

---

## 2026-07-13 ~14:45 UTC — OWNER BACK (remote control); loop paused; executing approved items 1,2,4

Owner returned, directive: **bot first — efficient + accurate**; alerting/webhook deferred. Approved items 1
(resolver fix), 2 (exit throttle), 4 (usage). Autonomous loop STOPPED. Bot healthy (uptime 29.7h→, eq $4942,
4-5 pos, 0 err, 0×429 real — the "90" was 429-in-price-digits noise).

**Item 4 (usage) — explained to owner:** ~700-1,200 LLM calls/day; biggest consumer = **exit agent ~476/day**
(every open position every scan) vs ~230 entry pipelines. $ tracker blind to CLI (counted 30 vs 700+). Measure by
call volume. Exit agent = #1 quota lever → motivates item 2.

**Item 2 (exit-agent throttle) — SHIPPED (owner-approved; validated):** `core/llm_integration.py`
`_run_exit_agent_checks` — added a per-position cooldown `EXIT_AGENT_COOLDOWN_S` (default 600s). Calm positions
skip the LLM exit re-eval within the cooldown; a position ≥50% of the way to its stop ("hot") ALWAYS re-evaluates;
the mechanical SL/TP (the real safety net) is untouched — exit agent is advisory only. py_compile OK + logic test
passed (skip/hot-bypass/off-gate). Est. ~50% cut to exit-agent calls. **Revert:** `EXIT_AGENT_COOLDOWN_S=0`.
Activates on next bot restart.

---

## 2026-07-13 ~15:10 UTC — Item 1 resolver fix SHIPPED (flag-gated); OWNER MISSION = toxicity audit for idle-safe

**Owner (autonomy-5):** "have confidence to autonomously continue toward our goals; ensure the system works as
intended." Then: "continue auditing our mass data extractions — if we can confidently let the bot run idle in the
background I'll be ecstatic; we've never managed that because there's always a toxic impact from something
somewhere." → **Mission: audit the data-extraction/measurement layer for silently-wrong stats that corrupt
decisions, so the bot is idle-safe.** This is the class of bug already found (spread_bps confound, resolver bug,
skip-outcome artifact).

**Item 1 — counterfactual resolver fix SHIPPED (flag-gated, DEFAULT OFF):** `llm/counterfactual_learner.py` — the
timeout now supports real wall-clock resolution (`CF_RESOLVE_TIME_BASED=true`, window `CF_MAX_TRACKING_HOURS`)
instead of the buggy `bars_to_resolve` counter (which increments on high/low EXTREME changes, not hours). py_compile
OK. **Evidence (proven from data):** resolution time median **8.1h** (p10 2.6, p90 12.2) vs intended 48h — the
window was ~8h and volatility-confounded; **60% of 69,690 counterfactuals resolve by timeout**; **846 veto-blocked
records feed live veto scoring, 49% (415) resolved on the buggy window** → veto arm/retire is corrupted. Revert:
`CF_RESOLVE_TIME_BASED=false`. Window still TBD (24h ≈ 3× pending ~1600; 16h ≈ 2× ~1100, safer, still captures the
4-8h thesis horizon) — finalize after audit; **not enabled yet** (batch with restart).

**Correction:** earlier "python-dotenv not installed" was WRONG (misread a truncated traceback) — dotenv 1.0.1 IS
installed; the bot loads `.env` fine (so env-gated fixes activate on restart). The empty alert creds finding
stands (creds genuinely blank). The inline `.env` parsers I added to watchdog/digest are harmless redundancy.

**Pending batch (activate on ONE restart, after audit):** exit-agent throttle `EXIT_AGENT_COOLDOWN_S=600` (item 2,
default-on in code), resolver `CF_RESOLVE_TIME_BASED=true` + window, plus whatever toxic fixes the audit surfaces.

**AUDIT LAUNCHED — 4 parallel Fable agents** (adversarial, read-only, quota-cheap), each on a data-extraction
subsystem: (A) prompt-injected stats/edge_data (WR/EV/verdict keying + staleness), (B) regime + signal-quality
pipeline, (C) learning/graduated-veto integrity, (D) collector data quality (dead/mis-scaled/stale fields).

_Next: synthesize the 4 audits → fix validated+reversible toxic findings (flag-gated) → ONE restart activating the
whole batch → verify idle-safe. Loop stays paused (owner present)._

---

## 2026-07-13 ~17:14 UTC — OVERDRIVE: audit complete; Batch-1 + Batch-2 flagship fixes SHIPPED + LIVE

(Full findings in coordination/TOXICITY_AUDIT_2026-07-13.md.) Owner shifted to full-execution/overdrive
(autonomy-5, "stop asking on the obvious, finish it"). Built a visual audit-briefing artifact for the owner.

**LIVE now (restart pid 20572, 17:13 UTC, 0 errors, equity preserved $4942.83):**
- BATCH 1 quota flags (PRE_CLOSE off, exit cooldown 600, overseer off) — ~½ calls cut, verified earlier.
- **B-T1 real ADX** (`QUANT_REGIME_TRUE_ADX=true`) — downstream-safety review SAFE; LIVE PROOF: ADX now 14.9-36.4
  (was 1.7-5.4 garbage), SOL/XRP "trend", ETH "range". The regime signal gating every decision is now correct.
- **D-T1 OI units** — fetcher returns USD notional (no more "$0M").

**Remaining (loop, overdrive):** D-T2 funding label, D-T3 basis, D-T4 forming candle, A-T1 pnl_pct filter,
A-T2 regime-fallback, F-1 thesis grading, F-3 confluence; then Batch-3 behavioral (NET_CAL, resolver, SOL block)
each adversarial-review-gated. Watch (ADX): solo-bypass freq + SL-widen rate first days. Owner-help: Discord webhook.

---

## 2026-07-13 ~17:38 UTC — SWARM: workflow specced 11 fixes; 3 SHIP fixes LIVE (restart pid 11736)

Owner: full swarm/autonomy-5, "utilize the mass data, capture what we built." Ran Workflow wf_62c00999 — 11 parallel
Fable agents, each drafting exact patch + LLM-free before/after + safety verdict. **All 11 cleared (3 ship, 8 tweak,
0 risky).** Specs saved to `coordination/FIX_SPECS_2026-07-13.md`.

**SHIPPED + LIVE (restart pid 20572→11736, 0 errors, equity $4942.83 preserved):**
- **D-T2 funding label** (`coordinator.py:642`, `WAGMI_FUNDING_1H_FIX=true` default) — %/8h→%/1h, thresh ±0.0025%.
  Before: 0/6815 crowding flags ever. After: 35 correctly flagged. Revert `=false`.
- **C-F1 resolver time-based** (`.env CF_RESOLVE_TIME_BASED=true CF_MAX_TRACKING_HOURS=16`) — real 16h window
  (capacity-safe vs MAX_PENDING) not the buggy ~9h. 434 veto records were scored on premature close. Revert `=false`.
- **C-F3 hardcoded SOL block disarmed** (`coordinator.py:5156`, `MERGE_GRAD_VETO_ENFORCE=false` default = guard on) —
  merge-site vetoes now require §2b provenance or shadow (LLM stands). sol_long_veto_v1 (SOL+BUY, no provenance) no
  longer flattens LLM-approved SOL longs. Fails safe (any error → shadow). LEDGER_VERSION import verified. Revert
  `MERGE_GRAD_VETO_ENFORCE=true`.

**Total shipped: 8 toxicity fixes** (E1/E2/E3 quota, B-T1 ADX, D-T1 OI, D-T2 funding, C-F1 resolver, C-F3 SOL).
**Next (8 tweaks, all cleared):** D-T3 basis, D-T4 forming candle, A-T1 pnl filter, A-T2 regime-fallback, D-T5 tape,
F-1 thesis grading, F-2 NET_CAL, F-3 confluence — specs in FIX_SPECS_2026-07-13.md; apply → restart → verify.
Then the data-opportunity swarm (owner's "utilize the mass data"). Owner-help open: Discord webhook.

## 2026-07-13 — Kelly/IC revival (KELLY_IC_FACTOR_FIX)
Root cause (verified from code + trade_dna, not deep-mine guess): the close-path
factor recorder read `entry_reasons["strategies"]` — a key that is NEVER set (real
key is `strategies_agree`). In LLM-FIRST mode `_factors` was always [] -> Kelly + IC
recorders looped 0 times -> kelly_weights.json + ic_history.json FROZE 2026-06-06,
and the ledger `contributing_factors` column went blank (212/216 rows empty).
Fix: multi_strategy_main.py ~3921 falls back through strategies_agree ->
primary_driver/setup_key -> event.strategy -> "llm_first" so every close now feeds
both loops with real per-factor names (verified: confidence_scorer/multi_tier_quality/
bollinger_squeeze/regime_trend present on 97/120 recent trades).
Revert: set KELLY_IC_FACTOR_FIX=false (default true).
Restart: pid 20872 -> 12632, clean init, Quant system loaded, 0 errors.
NOTE: files un-stale only after new closes accumulate (>=3/factor); did NOT seed from
ledger — recompute dry-run showed only 4 attributed rows (would collapse to a fluke).
Also VERIFIED FALSE ALARM: hypothesis graduation "deadlock" — 100 already graduated;
19 active at n>=10 correctly held on mixed 0.3-0.7 win/loss ratio. Loop is healthy.

## 2026-07-13 TICK — Accounting hole (EDGE_STATS_FROM_LEDGER) [SHIPPED default-OFF, review pending]
VERIFIED CURRENT + biased: trade_ledger.csv 216 rows 71W/142L = -$25.47 (truth) vs
trades.csv 149 rows 58W/89L = +$667.18. Drops 53 losers vs 13 winners -> flips sign.
trades.csv last write today 14:55 (live). Bias REACHES agents via 3 readers that
USE_MECHANICAL_BASELINE does NOT cover: dynamic_stats.get_current_edge_map (per-symbol
edge lines), prompt_enricher recent-trades list, self_analyst.
Writer divergence is STRUCTURAL (H2): 0 "Failed to log trade" warnings in logs, so it's
NOT the None-TypeError skip — trades.csv and ledger write from different close-handler
branches (3 duplicated close blocks 3750/3847/4430). Did NOT touch write path (risk).
FIX (read-side, reversible): dynamic_stats._load_recent_trades sources the COMPLETE
ledger when EDGE_STATS_FROM_LEDGER=true (default FALSE = byte-for-byte legacy). Maps
SHORT->SELL/LONG->BUY, net_pnl->pnl, regime_1h->regime, confidence_score->confidence;
falls back to legacy if <10 rows. RECENCY GUARD added (EDGE_STATS_LEDGER_DAYS=21) after
catching that naive last-200 = -$1585 (June blowup). Windowed truth: 7d 52%WR -$79 |
21d 44%WR -$164 | 45d 30%WR -$1585. Compiles; flag-off verified byte-for-byte.
Revert: EDGE_STATS_FROM_LEDGER=false. STATUS: adversarial review running (hard-veto risk
check) before enabling. NOT yet live.
Rule-graduation deadlock (tick item 2b): SKIPPED — debunked this session (100 graduated;
threshold n>=7-10 not n>=13). See project_learning_loops_audit memory.
WATCH: thesis graded still 0/774 (only 2 accum snapshots, no trend yet).

### ENABLED (same tick) — EDGE_STATS_FROM_LEDGER=true LIVE
Adversarial review (Fable) returned SAFE-TO-ENABLE: no consumer converts ledger WR into a
hard block/size-cut/confidence-tax; only gates (exploration_conviction_ok, TOXIC shadow) read
deep_memory/backtest data untouched; get_system_baseline insulated by USE_MECHANICAL_BASELINE=true;
data reaches agents as prompt text only + Critic prompts forbid mechanical low-WR blocking.
Applied reviewer's one hardening: window-or-legacy (never serve full-45d on total ts-parse fail).
Restart pid 12632->6008 clean. VERIFIED LIVE: recent-trade stats now n=100 WR=45% sum=-$165.69
(was +$667.18 biased); system baseline unchanged (0.54,2.3). Coupling constraints honored:
USE_MECHANICAL_BASELINE stays true; ml_data/strategy_stats.json + strategy_weights.json present.
FOLLOW-UPS (next tick, own review): prompt_enricher._load_recent_trades (llm/agents/prompt_enricher.py:287)
and self_analyst._load_recent_trades (llm/self_analyst.py:37) still read biased trades.csv —
apply same ledger source. Write-path branch divergence left untouched (execution risk).

## 2026-07-13 TICK 3 — accounting follow-ups LIVE + Kelly/IC diagnosis
HEALTH: green. pid 6008->12004 (restart to load fixes), eq $4952, 0 err, watchdog up.
15 closes/24h (bot actively trading; last full close ~18:35).

(a) FOLLOW-UPS SHIPPED + LIVE: prompt_enricher._load_recent_trades (llm/agents/prompt_enricher.py:287)
and self_analyst._load_recent_trades (llm/self_analyst.py:37) now source the COMPLETE ledger via the
reviewed recency-guarded dynamic_stats._load_recent_trades_from_ledger when EDGE_STATS_FROM_LEDGER=true
(already on). Text-injection only (no hard-veto consumer per prior review). Verified rows map correctly.
Revert: EDGE_STATS_FROM_LEDGER=false. Accounting hole now closed across ALL 3 trades.csv readers.

(c) KELLY/IC — DIAGNOSED, fix correct but not yet exercised (DO NOT rebuild externally):
- kelly_weights.json/ic_history.json STILL Jun 6 (37d) despite 15 closes/24h.
- Root: 0 "Kelly trade recorded" in logs. The recorder (multi_strategy_main.py:3935) sits inside
  `if event.action in _FULL_CLOSE` (3843). _FULL_CLOSE DOES include LLM_EXIT_AGENT (verified 3732), and
  the ledger writer next to it (3958) IS firing (216 rows) — so the block runs on full closes.
- The historical 0-count = closes ran under pids BEFORE KELLY_IC_FACTOR_FIX (empty _factors -> 0 loops).
  Since the fix went live, only PARTIAL closes (LLM_EXIT_PARTIAL, don't count) occurred; pid 12004 has
  had NO full close yet. => Fix will prove out on next full close; verify kelly_weights.json mtime then.
- Considered off-path rebuild from trade_dna but REJECTED: trade_dna 'pnl' is ambiguous ($ not pct) and
  kelly/ic on-disk formats are subtle -> reconstruction risks injecting WRONG stats into the prompt
  ("don't create MORE issues"). The in-process recorder has correct values; let it fire.

(b) graduation: debunked prior tick, skipped. (d) quality scorer: deferred (verify recency next tick).
WATCH next tick: kelly_weights.json/ic_history.json mtime > now (proves KELLY_IC_FACTOR_FIX); thesis
graded trend in accumulation_log (still 0/774, next accum snapshot ~22:00).

## 2026-07-13 TICK 4 — feedback-record wiring bug FIXED; Kelly/IC waiting on full closes
HEALTH: green. Bot pid 12004->19676 (restart, brief startup churn but settled to single proc,
0 err, HB fresh, no traceback). watchdog up.

FIXED (FEEDBACK_RECORD_FIX, default true, reversible): multi_strategy_main.py ~3789. The "quality
scorer boosts losers" trail led to a real CURRENT wiring bug: THREE recorders shared one try block
and ALL had wrong signatures — signal_quality.record_outcome(features_key=...) [invalid kwarg;
sig is features: QualityFeatures], parameter_tuner.record_outcome(...) [no such method; it is
record_trade_outcome(pnl)], continuous_backtest.record_outcome(side=,entry_price=,...) [wrong kwargs].
The first (signal_quality) threw TypeError on every full close, aborting the other two; swallowed at
debug. => parameter_tuner + continuous_backtest silently starved since it shipped. Fix: dropped the
redundant+broken SQ call (self.feedback path ~:3866 already records quality via its wired scorer),
corrected tuner->record_trade_outcome(total_pnl) and continuous_backtest kwargs to its real signature,
ISOLATED each in its own try, raised log to warning. Compiles; no runtime error on restart.
NOTE: the deeper "score by WR not payoff" scorer redesign (DEEP_MINE line 167, the systematic
boost-losers root) is BEHAVIORAL + needs adversarial review -> deferred to a reviewed tick.

VERIFIED-WAITING (not bugs): Kelly/IC files + ledger all frozen because ZERO full closes since 13:35
(4.25h) — bot is in holding mode, exit agent doing PARTIAL trims + gating full exits (ETH full_close
at 22:42 held by safety gate on n=2). Partials don't hit _FULL_CLOSE so don't record. KELLY_IC_FACTOR_FIX
+ this feedback fix + Kelly recorder are all staged correctly; they prove out on the next FULL close.
Quality-scorer "boosts losers": CONFIRMED real+current (scores by WR while edge is payoff), but corr(q,win)
=-0.01 (net noise, n=148); the wiring bug above was the actionable part. Redesign deferred (review).
RESTART DISCIPLINE: 4 restarts this session (spaced) — hold further restarts; let full closes accumulate.

## 2026-07-13 TICK 5 — PROVE-OUT: all staged fixes confirmed LIVE + safe
2 full closes since 13:35 (ledger 216->218, newest 18:50) exercised the staged fixes. VERIFIED:
- KELLY_IC_FACTOR_FIX: kelly_weights.json + ic_history.json un-staled (887h/37d -> 0.03h). "Kelly
  trade recorded" x3 in log. Kelly/IC REVIVED. New real factors: confidence_scorer(2), multi_tier(1),
  ensemble(1); IC ensemble(4)/confidence_scorer(2)/multi_tier(1).
- SAFE: all kelly weights at floor 0.15 (tiny n -> conservative, zero over-sizing). feedback_state
  stale-gate CLEARED -> kelly_fractions now re-enter the prompt (all 0.15). IC shows INSUFFICIENT(n)
  guards (won't act until n>=10). No garbage injected.
- FEEDBACK_RECORD_FIX: 0 "record error" across the closes -> parameter_tuner + continuous_backtest
  now recording cleanly (were TypeError-aborting every close before). All 3 recorders alive.
HEALTH: green. pid 19676 stable 64min, eq $4953.3 (+), 0 err, watchdog up. No restart this tick.

STEP-3: did NOT ship DEEP_MINE (a) [activate scorer's dead regime/side dims] — the scorer is
net-noise (corr q,win=-0.01) + scores by WR while edge is payoff, so activating more of its
dimensions adds ACTIVE noise without the (b) payoff-redesign. Commissioned adversarial review of
(b) [score-by-payoff vs clamp-influence vs leave] with recency-verification first, to ship next
tick if warranted. No unreviewed behavioral change forced.

## 2026-07-13 TICK 5b — scorer review verdict: STALE, no redesign; persist multiplier only
Fable adversarial review of the "quality scorer boosts losers" claim: VERDICT = STALE.
The WR-vs-payoff inversion is a Jun 1-7 blowup artifact. RECENT 21d (n=122): consensus=1 WR 28%
avg -$2.37, consensus=2 WR 67% avg +$0.10 — WR and avg-PnL now rank buckets the SAME; scorer's
dominant factor is directionally right-or-neutral, NOT net-harmful. Redesign (score-by-payoff)
is ANTI-INDICATED: state-file pnl is all-time-cumulative (no decay) -> scoring by it today would
recreate the inversion in reverse. Recommendation C (pre-authorized): don't touch scoring math;
persist the multiplier first for evidence. Also flagged (not acted): double-application in
ensemble.py (571-599 AND 819-840 both mutate confidence, ~q^2) — B-lite QUALITY_SINGLE_APPLY
available if ever needed, but scorer isn't currently harmful so NOT shipped.
SHIPPED (zero-behavior, additive): multi_strategy_main.py entry_reasons now carries
"quality_multiplier" (from signal_result.metadata, set ensemble.py:593/1116/1315) -> persists into
trades.csv entry_reasons JSON blob on every close. Unblocks GAP-6 (was unmeasurable). Compiles.
Restart DEFERRED (activates on next entry after next fix-batch restart; weeks-away value, avoid a
6th restart now). Revert: remove the one line.
LANDMINES noted for future: get_symbol_confidence_floor IS a gate input (already uses avg-PnL, do
NOT touch); two scorer instances share state (last-writer-wins); 4/8 dims still dead at scoring.

## 2026-07-13 TICK 6 — thesis grading 0/775 ROOT-CAUSED + FIXED (THESIS_ID_PRESERVE)
HEALTH: green pre-restart. Kelly/IC still fresh (0.85h, updating on closes), "Kelly recorded" 5,
0 record errors, 0 tracebacks, pid 19676 up 135min, eq ~$4952.
PROVE-OUT maintenance: Kelly/IC/feedback all healthy. BUT thesis grading stuck 0 graded / 775 pending
across 3 accum snapshots + multiple full closes — genuine verified-current gap (not waiting).
ROOT CAUSE (traced): theses recorded in coordinator.get_trading_decision (:1612), which appends
"| thesis_id=X" to the END of decision.notes. get_entry_decision calls get_trading_decision then
builds EntryDecision with notes=decision.notes[:500] (coordinator.py:2132) — TRUNCATING off the
thesis_id (sits ~char 750+). So entry_decision.notes has no id -> the F-1 extractor
(multi_strategy_main.py:8467) set entry_reasons["thesis_id"]="" -> close-path grader
(4177) never fired (verified: 0 "Closed thesis" AND 0 "not found in pending" in logs; 0/40 recent
trades.csv entry_reasons carry thesis_id). The earlier F-1 fix was applied one layer too late (after
the truncation). VERIFIED: coordinator embeds id (1628), get_entry_decision truncates it (2132).
FIX (THESIS_ID_PRESERVE=true, measurement-only, reversible): coordinator.py ~2120 — re-append the
thesis_id after the [:500] truncation so the linkage survives. Chain now: record_thesis -> notes ->
preserved-through-truncation -> entry_reasons["thesis_id"] -> close_thesis grades. Only helps NEW
entries post-restart (775 existing pending were entered without linkage; stay historical).
Batched with tick-5b quality_multiplier persist -> ONE restart (pid 19676 -> relaunching).
WATCH next tick: [THESIS] Graded lines appear + accumulation_log thesis.graded > 0 after new
post-restart entries close.

## 2026-07-13 TICK 7 — monitor-only (backbone repaired; no safe+verified gap left)
HEALTH: green. pid 22892 up 63min, eq $4952.39, 0 err, 0 tracebacks, 0 record errors, watchdog up.
PROVE-OUT: Kelly/IC fresh (2.11h, updating on closes). Feedback recorders clean. Thesis grading
still 0/775 BUT correctly waiting — last full close (2.11h ago) predates the pid-22892 thesis fix;
bot is currently FLAT (position_state.json position_count=0), so proving thesis grading now needs a
NEW post-fix entry to open AND fully close. No re-diagnose warranted (zero post-fix closes yet).
STEP-3: assessed remaining DEEP_MINE items, none warrant a change now:
- Thesis grading: fix live, waiting on entry+close cycle.
- Scorer redesign: deferred (quality_multiplier now persisting; re-evaluate in ~2-3 weeks on evidence).
- Stale-drop churn (DEEP_MINE ~258): VERIFIED CURRENT (~1470 drops/10.7h) but efficiency/log-spam
  ONLY — outcome is correct (stale rules correctly stay dropped); persisting the drop risks wrongly
  freezing a rule that could regain evidence. NOT worth a behavioral change. Logged low-priority.
CONCLUSION: learning backbone repaired end-to-end (accounting hole, Kelly, IC, 2 feedback recorders,
thesis grading — all were wiring bugs, all fixed; graduation/exit-regret/agent-grading were false
alarms). Verified-current gap surface exhausted. Staying MONITOR-ONLY — not inventing work. The
gating factor now is TRADE VOLUME/TIME to let the repaired loops accumulate clean data.

## 2026-07-13 TICK 8 (light) — monitor-only, green, waiting on volume
Health green (pid 22892 2h, eq $4952.39, 0 err, not degraded, watchdog up). Kelly/IC fresh (3.16h),
0 record errors, 0 tracebacks. 429/auth alarms = FALSE POSITIVES (timestamp substrings; tight patterns=0).
Thesis still 0/775: bot FLAT (0 positions), no full close 3h+, fix awaits an entry+close cycle. No regression.

## 2026-07-14 OVERNIGHT TICK ~00:00 — green, selective, flat (waiting on conviction)
Health green (pid 22892 3.8h, eq $4952.39, 0 err, not degraded, 0 pos, wd up). 0 record-err/traceback/429/auth.
Bot FLAT 4.85h — VERIFIED not a gate: 751 signals, LLM actively skipping low-conf (HYPE 66%, BTC 50%) = correct
selectivity (3 go / 24 skip; 167 dup_pos + 364 cooldown pre-LLM). Thesis 0/775 (no post-fix full close yet).
Kelly/IC fresh (4.85h, no new close to update). No accumulation growth -> skipped mine refresh. No fix needed.

## 2026-07-14 OVERNIGHT TICK ~01:00 — THESIS FIX CONFIRMED at entry-level + green
Health green (pid 22892 4.8h, eq $4952.39, 0 err, not degraded, wd up). 0 rec-err/tb/429/auth.
Bot entered 2 positions (SOL SHORT, HYPE SHORT) post-thesis-fix -> BOTH carry populated entry_reasons
["thesis_id"] (thesis_20260714_050526_1 / _050617_2). CONFIRMS THESIS_ID_PRESERVE works: id survives
truncation -> lands in position. On their full close, close_thesis will fire -> thesis grading >0.
Thesis pending 775->777 (+2). No full close yet (positions open); Kelly/IC fresh; no accumulation refresh.

## 2026-07-14 OVERNIGHT TICK ~02:00 — green; holding phase, no full close yet
Health green (pid 22892 5.8h, eq $4952.39, 0 err, not degraded, wd up). 0 rec-err/tb/429/auth.
Bot now holding 3 positions (pos 2->3, thesis pending ->778). NO full close in 6.9h -> thesis grading
still 0 (0 ClosedThesis/notFound = close_thesis not yet fired; awaits a FULL close). Kelly/IC unchanged
(no close). Equity flat = held positions ~break-even. No accumulation growth, no fix.

## 2026-07-14 OVERNIGHT TICK ~04:00 — REAL BUG FOUND: zombie qty=0 positions (HOLD FOR MORNING)
HEALTH green (pid 22892 7.9h, eq $4952.7, 0 err, not degraded, wd up, 0 rec-err/tb/429/auth).
FINDING (verified-current, ROOT of the "can't prove out" symptom): positions partial-closed down to
qty=0 are NOT finalized — they linger in the book as ZOMBIES (state != CLOSED, never recorded).
Evidence: position_state.json count=3 but SOL SHORT qty=0 (thesis_20260714_050526_1) + HYPE SHORT qty=0
(_050617_2) are zombies; only XRP SHORT qty=159 is live. heartbeat pos=1 (counts qty>0) vs
position_state count=3 (counts entries) — the 2 gap = zombies.
IMPACT: because these never hit the FULL-CLOSE path, they bypass ledger.record_trade (stuck 219 rows
~9h), kelly/ic recorders (stale 9h), close_thesis (thesis grading stuck 0/778), and feedback recorders.
This is WHY thesis grading / Kelly haven't proven out overnight and equity looks "flat/holding" — the
book is inflated by dead qty=0 entries. Earlier full closes (SL/TP2/LLM_EXIT_AGENT) DO record (Kelly
proved out tick 5); the leak is specifically the partial-to-zero path not finalizing.
LOCATION (for morning fix): execution/position_manager.py — _partial_close_tp1 (~1165-1233; see
remaining_after<=0 guard ~1206 and close_qty>=pos.qty ~1209) should, when a partial takes qty to 0,
transition to CLOSED + emit a full-close TradeEvent so _close_position (~1460) fires and downstream
recorders run. Currently qty hits 0 without that finalization.
DECISION: NOT fixed autonomously — exit/position-state-machine path, behavioral, can't be adversarially
validated safe overnight, and standing rule = never touch exits unattended. TOP MORNING ITEM: careful
reviewed fix + verify no double-record / no interference with live exits. Flag-gate it.
No restart, no exit-path change made. Continuing to guard.

## 2026-07-14 OVERNIGHT TICK ~05:00 — THESIS GRADING PROVEN + 04:00 zombie alarm RETRACTED
CORRECTION to the 04:00 entry: the "zombie qty=0 positions bypass recorders" alarm was a FALSE ALARM.
Verified: those positions are state=CLOSED lingering briefly in position_state.json AFTER a proper close
(HYPE: "[HYPE] State: OPEN->CLOSED (LLM_EXIT_AGENT)" + [TRADE_CLOSED] @08:18; SOL closed @09:04). No leak,
no bug — recently-closed positions just persist in the snapshot dict a short while. Recency/verify
discipline caught my own over-alarm (same as prior false alarms). Do NOT pursue a position_manager
"finalization" fix — there is nothing to fix there.
MILESTONE (real): THESIS GRADING PROVEN END-TO-END. SOL thesis_20260714_050526_1: entry (post-fix,
thesis_id linked) -> held 4h -> full close LLM_EXIT_AGENT +$0.63 -> close_thesis fired -> graded
"correct" (pnl_pct +0.013, closed_at 09:04). accumulation thesis.graded 0->1. THESIS_ID_PRESERVE
confirmed working round-trip. Kelly/IC also updated on the close (fresh 1.05h). ALL repaired loops now
proven live: accounting, Kelly, IC, 2 feedback recorders, thesis grading.
REAL (non-critical) GAP for morning: HYPE thesis_20260714_050617_2 ALSO fully closed (@08:18,
LLM_EXIT_AGENT) but its thesis did NOT grade (still pending) — so the close-path thesis grader fires on
SOME full closes but not all (likely the multi-branch close divergence: SOL's branch hit the grader at
multi_strategy_main.py:4177, HYPE's did not). Worth a morning trace of which close branches reach the
grader; LOW priority (grading demonstrably works; just incomplete coverage). Not fixed overnight
(close-path, subtle, verify-first).
HEALTH green (pid 22892 9h, eq $4953.02, 0 err, not degraded, wd up, 0 rec-err/tb/429/auth).
True P&L: trade_ledger.csv 220 closes sum net_pnl = -$23.67.

## 2026-07-14 OVERNIGHT TICK ~07:00 — thesis grading climbing (1->3), green
Health green (pid 22892 12h NO restart, eq $4950.54, 0 err, not degraded, flat, wd up). 0 rec-err/tb/429/auth.
Thesis grading 1->3 (1 correct + 2 incorrect) — proving out across multiple closes now (grader covers
more closes than the single-SOL milestone; HYPE-coverage gap less severe than feared). Ledger +2 (222,
total -$26.16, ~flat overnight). Kelly fresh (0.55h). (Heartbeat read None once = mid-write artifact, re-read OK.)

## 2026-07-14 ~14:15 — memecoin expansion validated-as-not-ready; loops green
Health green (pid 22892 stable no restart, kelly fresh, thesis 3 graded, 0 rec-err/tb/429/auth; heartbeat None=mid-write).
EXPANSION WORK (owner wants more tickers/POPCAT): POPCAT backtest FAILED (-$315, 32% WR<40% BE) -> not added.
Pre-screened 6 HL memecoins: most NOISE (naive momentum loses: WIF -37%, FARTCOIN -28%, PNUT -15%). GOAT only
screen-passer but 0-position backtest (insufficient multi-TF history). CONCLUSION: no memecoin validates now;
kept 5 majors. POPCAT/GOAT wiring dormant (commented) for re-validation. Owner POPCAT conviction logged as
personal call. Also this session: Discord webhook wired+tested (discord_notify.py), thesis pushed; proof_window.py built.

## 2026-07-14 ~14:40 — WALK-FORWARD capability confirmed + POPCAT full-history verdict
WALK-FORWARD: full-system LLM backtest EXISTS + works via CLI (run.py backtest --llm; USE_CLI_LLM bypasses API key,
real 9-agents fire — proof showed critic call model=claude-haiku-4-5). Supports --budget/--resume/--start-date/--learn.
CATCH: ~17s per CLI agent call -> full-history x all-tickers full-LLM = weeks wall-clock + heavy quota + competes with
live bot. Architecture: mechanical full-history (cheap/complete) + bounded checkpointed LLM windows + per-regime scoring.
POPCAT FULL-HISTORY MECHANICAL (208d, all HL 1h data): -$1,456.84, 30.6% WR (BE 50.9%), -68% equity, payoff 0.97:1,
BOTH substrats losing. DECISIVE: POPCAT has negative systematic edge across full history, not just 21d. Recommend hold
as owner personal conviction (logged), NOT in systematic bot. Live universe stays 5 majors. POPCAT dormant in config.
CoinGecko lowcaps CASHCAT(cash-cat)/NUB(sillynubcat) exist but very new/thin/daily-only. Live bot healthy pid 22892.

## 2026-07-14 — DE-HARDCODE BATCH 1 (living values). Restart to activate.
3-agent hardcode audit -> coordination/HARDCODE_AUDIT_2026-07-14.md (dozens of stale/fictional/contradictory
stats + static gates). Batch 1 shipped (all flag-gated/reversible; owner "all hands on deck"):
1. SIDE-MULTS -> LIVING (DEFAULT ON, DATA_DRIVEN_SIDE_MULT). feedback/live_edge.py computes symbol_side
   size mult from ledger PnL/trade, n>=13, self-refresh 15min. Kills the smoking gun: ETH_SELL 0.70->1.50
   (best edge un-suppressed), HYPE_BUY 0.70->0.25 (worst drain strangled). Revert flag=false.
2. QUANT_BRAIN win-prob prior -> LIVING (DEFAULT ON, WIN_PROB_PRIOR_DECAY). Prior weight now DECAYS to 0 by
   n=30 (was permanent 60/40 pinning a 2026-03 prior that capped ETH_SELL at 0.55 despite 90.9% live).
3. LEVERAGE CAP asymmetry (shorts 8/12/15 vs longs 10/15/20, no liq basis) -> flag LEV_CAP_SYMMETRIC
   DEFAULT OFF (raising a lev cap = risk change; owner flips consciously).
4. GRADUATED_RULES provenance gate -> flag GRAD_RULE_PROVENANCE_ENFORCE DEFAULT OFF. When on, shadows
   pre-standard (era="" / stale ledger_version) rules that enforce today regardless of §2b (e.g. -20 conf
   penalty on winning BTC SELL). Engine re-learns them with valid provenance.
5. premium_filter.py _SHADOW_EDGES/_SHADOW_BLOCKS EMPTIED — zombie 2026-04-16 pre-fee-fix poison that
   survived the 2026-06-05 purge; asserted "ETH BUY 100% WR execute-alone" + BLOCKED ETH_SELL (best edge).
6. signal_pipeline.py ~781 false "0% historical WR" log string REMOVED (earlier this session).
OWNER FLAGS TO FLIP when ready (default-off, risk/behavioral): LEV_CAP_SYMMETRIC, GRAD_RULE_PROVENANCE_ENFORCE.
QUEUED (Tier-2 fiction, zero trade risk, peripheral): dashboard 65%WR, manual/alerts 88.5%, telegram GROUND TRUTH.
QUEUED (Tier-3 gates, be exact): single-source the 3 conflicting conf defaults (40/55/20); shadow-flag the
LLM_MODE-dependent negative-EV block; probability_engine static EV/prob gates.
Restart pid 22892 -> relaunching. Universe = 5 majors (POPCAT/GOAT dormant).

## 2026-07-14 — DE-HARDCODE BATCH 2 LIVE (owner "go ahead for everything") + hands-off alerting
Restart pid 19908 -> 22596, clean (0 tb, LLM-FIRST active, HB fresh, eq $4941). Shipped:
- FLAGS FLIPPED ON: LEV_CAP_SYMMETRIC=true (un-bias short lev caps — RAISES short caps to match longs,
  still CB/liq/Kelly bounded, reversible), GRAD_RULE_PROVENANCE_ENFORCE=true (shadow era=""/stale rules
  incl the -20 conf penalty on winning BTC SELL).
- FICTION PURGED: telegram_bot.py:2223 fake "GROUND TRUTH: ETH=47%WR..." fed to LLM (removed);
  manual/alerts.py:139 "88.5% WR" (real 23%) removed; dashboard/server.py 3 fabricated WR cards stripped.
- HANDS-OFF MONITORING: tools/health_alert.py (LLM-free) + Task WAGMI-HealthAlert every 15min -> pings
  Discord ONLY on real problems (down/degraded/errors/429) + a recovered note. Owner QoL: silence=healthy.
Living values confirmed active in-process: ETH_SELL 1.5, HYPE_BUY 0.25.
STILL QUEUED (Tier-3, be exact): single-source 3 conflicting conf defaults (consistency_checker 40 /
trading_config 55 / .env 20); shadow-flag the LLM_MODE-dependent negative-EV block; probability_engine
static EV/prob gates. Owner wants speed + autonomy — continue without pausing.

## 2026-07-14 — DE-HARDCODE TIER-3 done (behavior-preserving; loads next restart)
(a) consistency_checker.py:213 conf-floor fallback 40->20 (single-source; matches .env=20 + comment; guard kept).
(b) ensemble.py:2610 negative-EV block TIME-BOMB removed: disarm no longer depends SOLELY on LLM_MODE>=4;
    EV_BLOCK_ENFORCE flag (default false=shadowed, current behavior preserved) keeps it disarmed even if
    LLM_MODE drops. Revert: EV_BLOCK_ENFORCE=true.
(c) probability_engine.py regime EV/prob gates: REVIEWED, LEFT AS-IS — legitimate per-strategy quality
    filter (regime-aware, no directional/fictional bias); shadowing would just flood the LLM w/ low-EV noise.
DE-HARDCODE STATUS: all HIGH/MED live-trade items done (batches 1+2+Tier3). Remaining = Tier-4 stale sizing
FALLBACKS (sizing_optimizer _DEFAULT_PRIORS, momentum_tracker, lead-lag, _quant_backtest_2026_03_26 LLM-context
fingerprint) — blended/decaying at n>=15 or peripheral (manual sniper). Lower priority. No restart needed now
(Tier-3 behavior-preserving). Gating factor now = TRADE VOLUME to prove the living values improve outcomes.

## 2026-07-14 — DOUBLE-LOG GLITCH found+fixed: TRUE P&L is +$337 (not -$33)
Owner flagged HYPE_LONG -$908 as possible glitch. AUDIT: found 12 DUPLICATE trade-pairs across ledger —
same sym/side/entry/exit/pnl/hold, different trade_ids, 34-420s apart, ALL losses. Verified each = one
COMPLETE record (fees+running_equity) + one INCOMPLETE phantom (blank fees/equity) = same close DOUBLE-LOGGED
by the multi-branch close handler (stale/re-fired close event on a lingering position). Ops-guard blocks real
dup positions, so identical entry+exit+hold = double-log, not 2 real trades.
FIXED: (1) backed up ledger, de-duped (removed 12 phantom rows, kept complete). 224->212 rows. TRUE net_pnl
= +$337.23 (was -$33.41 — the glitch hid $370 of phantom loss). (2) CLOSE_DEDUP_GUARD (default true, code fix
at multi_strategy_main.py:3963) — skips ledger write if same close-key recorded in last hour. Idempotency only,
no exit-logic change. Loads next restart. (3) live_edge refreshed from clean ledger.
INTEGRITY SCAN (rest of ledger): 0 remaining dups, 0 trades >20% equity (no amplification glitch), leverage
1-15x (in bounds). Ledger now trustworthy.
CORRECTED PICTURE: SHORTS +$1,248 / LONGS -$911 (HYPE_LONG -$685 real, oversized June-era; living values now
cap HYPE_BUY 0.25x). The bot HAS been profitable — edge was masked by the double-log + oversizing + hardcoded
fiction. Owner confidence high + wants continued audit. Living values now read clean data.
