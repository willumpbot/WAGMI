> # 🔧 CORRECTED 2026-10-11 — I used file coverage as a liveness measure. It is log rotation.
>
> **The server's answer:** `bot_YYYYMMDD.log` is named by **process-start date** and **rotates weekly**,
> so a missing day is lost log text, not a dead bot. `entry_gate_log` and `signal_filtered` are both
> extracted from those rotating logs, so **their day coverage was never evidence of inactivity** — and my
> headline "23 of 40 days show no activity at any stage" is wrong. I framed it as a question, which was
> right, but the framing still carried a conclusion I could not support.
>
> **Using only the files that never rotate** (`trade_events.jsonl`, `trades.csv`), 2026-09-01 → 10-10:
>
> | | days of 40 |
> |---|---|
> | **bot alive and emitting events** | **23 (58%)** |
> | **confirmed DOWN** (09-15 06:24Z → 09-18 12:54Z) | **4** |
> | **DEGRADED** — process up, LLM login expired (10-05 → 10-07) | **3** |
> | unknown — no events, and no uptime record existed | 6 |
> | a trade actually opened | 11 |
>
> **So the real gap is ~9 alive days with no trade and no known cause** — not 23. Much smaller and much
> more tractable. The 3 degraded days explain themselves: no LLM-first entry was possible.
>
> **The decomposition below still stands** — it came from `trades.csv`, which does not rotate — and the
> server agrees: mark ~3.3d down + 3d degraded, treat the rest as quiet.
>
> **🔴 Two operational findings survive this correction, and they matter more than the statistics:**
>
> 1. **`auto_restart=False`.** The watchdog logged "BOT DOWN: process dead" and nothing relaunched it for
>    **3.3 days** — it waited for the scheduled Sunday restart. A watchdog that detects death and does
>    not act is a monitor, not a watchdog.
> 2. **An expired LLM login degraded the bot for 3 days while the process looked healthy.** Since
>    LLM-first is the only live entry path, it **could not have traded at all** while reporting itself up.
>
> Both are the same failure class as the clip-queue bug: **it looked fine and it was not.** The server has
> added `uptime.jsonl` every 15-minute cycle so future droughts split cleanly into down vs quiet.
>
> **My own lesson, third time today: file coverage is not activity.** I read rotation as silence on the
> floor log and again here.

# Why the bot stopped trading: it is not the gates. **23 of the last 40 days show no activity at any stage** — and I cannot tell from the exports whether the bot was even running.

_2026-10-11. `entry_gate_log.jsonl.gz` (5,383 events, 2026-05-30 → 10-10) plus `signal_filtered.jsonl.gz`
(9,845), `trades.csv`, `scan_log.jsonl`. Answers the server's live question._

---

## 🔴 The decomposition

**Trades fell 91%, from 216 in Jun–Jul to 20 in Sep–Oct.** That splits almost evenly in two:

| | Jun+Jul | Sep+Oct | change | share of the log drop |
|---|---|---|---|---|
| **active days** | 46 | **12** | **−74%** | **56%** |
| **trades per active day** | 4.70 | **1.67** | **−65%** | **44%** |

**Neither alone explains it — they compound.** Fewer days is the larger half, but a single-cause story
would be wrong in either direction.

## The funnel by calendar day, 2026-09-01 → 10-10 (40 days)

| stage | days | share |
|---|---|---|
| `SIGNAL_FILTERED` fired | 10 | 25% |
| reached the **ENTRY GATE** | 13 | 32% |
| **a trade actually opened** | **11** | **28%** |
| **no activity at ANY stage** | **23** | **58%** |

**🔴 The gate is not the bottleneck. It converts well — 11 trade-days out of 17 with any activity.**
The binding constraint sits *upstream of everything I had been analysing*, including the confidence
floor, the IC gate and the LLM pipeline.

## What the visible layers actually do, for completeness

**The LLM pipeline's reasoned skips (274 since Sep) say the market has no direction:**

| stated reason | share |
|---|---|
| open-interest condition | 37% |
| consolidation / range | 26% |
| regime unfavourable | 26% |
| range-bound | 24% |
| chop | 11% |
| awaiting breakout confirmation | 10% |

**And those 274 skips are only 31 distinct (symbol, day) situations** — about 9 re-evaluations each, a
few minutes apart. It is not 274 deliberations; it is a few setups re-examined on a scan loop. Example:
ten consecutive NEAR skips between 05:40 and 06:52 on 10-08, all saying the same thing.

**ENTRY-GATE blocks since Sep:** 30 of 67 evals, reasons `long_drain_non_uptrend` (23),
`solo_below_breakeven` (18), `short_no_tailwind_shadow` (9), `neg_ev_shadow` (6).

**Worth saying plainly: declining directional trades in chop is defensible.** This project has run ~98
directional tests and never demonstrated a directional edge. A pipeline that says *"no direction here"*
and stands aside is behaving consistently with the evidence. **That layer is not the problem.**

## ⚠️ A correction to my own earlier read

My first cut found **26% of all gate events are `LLM-FIRST SKIP: LLM pipeline failure`** — a technical
failure, not a decision — and I nearly reported that as the cause. **The month cut kills it:**

| month | events | failures | failure rate |
|---|---|---|---|
| 2026-05 | 267 | 160 | **59.9%** |
| 2026-06 | 3,031 | 1,130 | **37.3%** |
| 2026-07 | 1,693 | 110 | 6.5% |
| 2026-08 | 33 | 0 | **0%** |
| 2026-09 | 338 | 0 | **0%** |
| 2026-10 | 21 | 0 | **0%** |

**The pipeline failures were real and large in May–June, and they were fixed.** Zero since August.
Quoting the pooled 26% would have been the era artifact for a fourth time.

## 🔧 The question I cannot answer from the exports — and it is the whole thing

**Were those 23 silent days days when the bot was not running?**

Both full-history exports independently cover **~47% of their own span**:

| file | span | days present |
|---|---|---|
| `signal_filtered.jsonl.gz` | 06-01 → 10-11 | **61 of 133 (46%)** |
| `entry_gate_log.jsonl.gz` | 05-30 → 10-10 | **64 of 134 (48%)** |

Two independent files landing at the same ~47% is suggestive — a logging bug in one would not reproduce
in the other — but they could share a cause, namely **the process being down.**

*(`scan_log.jsonl` and `agent_grades_resolved.jsonl` are rolling recent-only windows — 4 and 5 days —
so their sparseness is export design, not inactivity. I nearly misread that too.)*

**This is cheap for you to answer and I cannot:** process uptime, systemd/journal, or restart history
for 2026-09-01 → 10-10. **If the bot was down on most of those 23 days, that is the drought**, and
every gate analysis — mine included — has been studying the 42% of days when it was awake.

**If it was up and simply silent, that is a scanner/signal-generation question**, and the next place to
look is why `SIGNAL_FILTERED` fired on only 10 of 40 days: no signals generated at all, or signals
generated and discarded before the filter logs them.

## Trader rules — one number each
1. **The bot traded on 11 of the last 40 days.** On the days it is active it still opens 1.67 trades —
   so it is not frozen, it is absent.
2. **Trades fell 91%: 56% from fewer active days, 44% from a lower rate when active.** Both matter.
3. **The gates are not the cause.** 11 trade-days from 17 active days is a healthy conversion.

## Limits
- **I cannot distinguish bot-down from bot-silent from the exports.** That is the central caveat and the
  reason this doc ends in a question rather than a verdict.
- The 2026-10 month is 10 days, not 31, so its rate is noisier than the others.
- `trades.csv` counts closes, so a position opened on day *n* and closed on day *n+1* attributes to the
  close date. At a 3-hour median hold this misplaces few rows, but it is not exact.
- The keyword counts on the skip theses overlap — one thesis can mention both chop and OI — so they sum
  past 100% and are descriptive only.
