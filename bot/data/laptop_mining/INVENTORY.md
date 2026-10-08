# Laptop data inventory (mission 1)

_Compiled 2026-10-08 on the laptop, branch `laptop-mining-2026-10`._

**Headline: the laptop holds exactly one clean, genuinely new asset — 16,458 de-duplicated
signal proposals from 2026-02-11 to 2026-06-05, 72 trading days, all with a `trace_id`, almost
entirely before the server's grading window opens (2026-05-30). Every *numeric outcome* series
on this machine is unusable: three separate systems wrote warped PnL, and one 190k-row
counterfactual file is 70% corrupt. The owner's instinct was right — the value here is the
signal→decision chain, not the money columns.**

Also: the laptop has **no** live-trade data the server lacks, and **no** Aug 12 – Sep 6 outage
coverage. The laptop stopped producing bot data on 2026-06-06, two months before that outage.

---

## 1. The clean asset

### `bot/data/laptop_mining/signal_corpus.jsonl.gz` (built here)
| field | value |
|---|---|
| Source | `WAGMI PROJECT/WAGMI/bot/paper_trades/signals_*.csv` (1,418 session files) |
| Rows | 37,043 valid → **16,458 after dedupe** on (symbol, side, strategy, entry, 1h bucket) |
| Rejected | 59 total (57 geometry, 2 unparseable) — **0.16%**, i.e. clean |
| Span | 2026-02-11 02:53 → 2026-06-05 23:13 UTC, **72 distinct days** |
| Join key | `trace_id` on **16,458 / 16,458** rows |
| Fields | ts, trace_id, sym, strategy, side, conf, entry, sl, tp1, tp2, atr, regime_score, num_agree, total_strategies, rr1, stop_pct |

Distribution: BTC 4,525 / ETH 4,072 / HYPE 3,878 / SOL 3,256, plus a 12-symbol tail
(PEPE, SEI, SUI, WIF, DOGE, ONDO, ARB, XRP, LINK, AVAX…). LONG 9,877 / SHORT 6,581.
By month: Feb 935, Mar 2,421, Apr 9,200, May 3,852, Jun 50.
Confidence spans 20–100 and is well spread (mode 60–79, n=8,724).
`num_agree`: 1 → 11,051, 2 → 5,060, 3 → 344, 4 → 3.
R:R to tp1 median **1.50** (p10 1.50, p90 2.00); stop width median **1.458%** (p10 0.65, p90 3.66).

**Why it survives when nothing else does:** these rows record what the bot *proposed*, written
before any simulated fill touched them. Grading them needs only real Hyperliquid candles, so
none of the broken fill arithmetic propagates. This is the input for missions 3 and 4.

**Sanity cross-check it enables:** R:R to tp1 is 1.50 by construction, so a TP1 exit can pay at
most ~1.5× what an SL exit costs. The paper-trade ledger credits TP1 at +23.2% against SL at
−4.1% (5.6×). That single comparison proves the fill simulator is broken, independent of any
other evidence.

---

## 2. What the server does NOT have

| Item | Span | Size | Verdict |
|---|---|---|---|
| `paper_trades/signals_*.csv` → signal_corpus | 2026-02-11 → 06-05 | 11 MB raw | ✅ **USE.** The clean asset above. |
| `paper_trades/trades_*.csv` | 2026-02-11 → 06-05 | 592 valid rows | ⚠️ exit *labels* usable (TP1/TP2/SL/TRAILING/TIME_STOP); **PnL is not** |
| `manual/sniper_signals.jsonl` | 2026-03-24 → 06-05 | 40,891 rows / 33 MB | ⚠️ rich fields, but **0 resolved outcomes** and no join key; `signal_context` is a 25-char canned label |
| `manual/trade_scorecards.jsonl` | 2026-03-28 → 06-06 | 35,002 rows / 14 MB | ⚠️ has `total_score` + `components` + pass/fail; weak join key (`setup_key` = symbol_side) |
| `logs/signal_outcomes_regime_backfilled.jsonl` | 2026-03-29 → 04-28 | 83,432 rows / 40 MB | ⚠️ gate annotations, `passed`, `hard_rej`, `rej_reason`; **no join key** |
| `llm/counterfactual_resolved.jsonl` | 2026-03-23 → 05-01 | 189,835 rows / 112 MB | ❌ **70% corrupt**, see §3. Yields only ~460 independent rows. |
| `Downloads/Paper Trades - jkh.csv` | **2025-08-30 → 2025-10-11** | 40,187 rows | ❓ truly independent period, 12+ symbols incl. WORM/HOME/PUMP. **Provenance unknown** ("jkh"); not verified as the owner's. Duplicated file. |
| `WAGMI/coordination/backtest_results/` | to 2026-06-09 | 115 MB, 196 files | ⚠️ 0 of these files exist on the server branch; laptop-only backtest artifacts |

### Explicitly NOT found
- **No pre-February data.** Oldest bot artifact on the machine is 2026-02-10. The machine has been
  in use ~1 year, but WAGMI data only goes back 8 months, and usable data only to 2026-02-11.
- **No Aug 12 – Sep 6 outage coverage.** Laptop bot data ends 2026-06-06.
- **No dated-log advantage.** The laptop's logs stop in June, before the undated server logs begin.
- **No owner discretionary trades.** `manual/` is the bot's own "sniper" tier, not hand-placed trades.
- **No Claude Code transcripts.** `~/.claude/projects/*/` holds **0 `.jsonl`** files (only today's
  session). Mission 2 must fall back to the 160 surviving memory `.md` files + `~/.claude/history.jsonl`.

---

## 3. Corruption catalogue (for the server's awareness)

Four independent corruption mechanisms, all confirmed by arithmetic:

1. **Fixture flooding — `trade_events.jsonl`** (384,958 rows, 2026-03-31 → 06-06).
   40,150 TRADE_OPENED vs 5,563 TRADE_CLOSED. 1,482 closes on a single day (2026-03-31) and
   1,072/day even after filtering. Canned rows carry `strategy:""`, `confidence:0`, `regime:""`
   and round entries (3000.0 → 3050.0, exactly 80h hold). **All PnL unusable.**

2. **Envelope corruption — `counterfactual_resolved.jsonl`.** Of 189,835 rows:
   50,403 have `max_adverse_price` on the *wrong side* of entry, 53,814 the same for
   `max_favorable_price`, 29,820 missing numerics. Only 29.4% validate; dedupe on
   (symbol, side, gate, hour) then collapses 55,796 → **460**. This is the same class of defect
   the server recorded for `missed_trades_resolved.jsonl` (726/1,407 impossible prices).

3. **Fill over-credit — `paper_trades/trades_*.csv`.** TP1 +23.2%/trade vs SL −4.1% at a
   designed R:R of 1.50. Apparent profit of +$38,592 net on 592 trades (Feb alone +$41,578 at
   79% WR, FARTCOIN +46.4% at 96.6% WR, >10x bucket +47.6%) is an artifact. "Win rate" here is
   just TP-exits ÷ SL-exits, not predictive skill.

4. **Empty LLM layer — `agent_evals/consensus.jsonl`.** 20,745 rows, **100% pipeline failures**:
   every row is `MIXED_CONSENSUS` with 0 go/skip votes; 10,006 theses read literally
   "LLM pipeline failure", the other 10,739 are empty. There is **no April thought-process data**.
   `bot_perception/percepts.jsonl` (184 MB) is likewise inert — every sampled row has
   quality_score 0.0, consistency_score 0.0, gap 0.0.

---

## 4. Gate result already obtained (feeds mission 4)

From the 460 surviving counterfactual rows, aggregating gates by **family** rather than by
threshold (the log fragments one gate into 26 cells like `confidence_floor_65`, `_66`, `_67`),
with a cluster bootstrap over (symbol, UTC day):

| gate family | n | clusters | mean blocked PnL% | CI95 | verdict |
|---|---|---|---|---|---|
| `confidence_floor` | 304 | 65 | −0.017 | [−0.174, +0.140] | no signal |
| `trend_adj_floor` | 145 | 45 | −0.010 | [−0.315, +0.300] | no signal |
| `manager_advice` | 11 | 6 | −0.501 | [−0.931, +0.460] | n<13 insufficient |
| **null (all blocked)** | 460 | 86 | −0.026 | [−0.174, +0.132] | — |

- **Corroborates the server** on the confidence floor: trimmed mean ≈ 0 there, CI spanning 0 here,
  on a period two months earlier and an independent data source.
- **Does NOT corroborate** the server's trend-adjusted-floor finding (−0.30%, CI excludes 0).
  Per-threshold, `trend_adj_floor_66` looked like a match (−0.22% ± 0.11), but that was a
  fragment with an under-dispersed SE; aggregated and cluster-bootstrapped it is −0.010 with a
  CI spanning 0. **Treat the trend-floor edge as unreplicated, not confirmed.**
- One weak, non-significant hint worth re-testing forward: among confidence-floor blocks, higher
  thresholds blocked progressively *worse* trades (≤65 → +0.015%, 66–70 → −0.029%, >70 → −0.148%,
  n=40 in the top bucket, no CI computed). Hypothesis only.

---

## 5. Reproduce

All scripts in `bot/data/laptop_mining/`, no dependencies beyond the stdlib:

| script | does |
|---|---|
| `build_signal_corpus.py` | signals_*.csv → validated, de-duplicated `signal_corpus.jsonl` |
| `analyze_paper_trades.py` | aggregates trades_*.csv; exposes the TP/SL over-credit |
| `analyze_counterfactuals.py` | per-gate scorecard + the 4 validation rules |
| `gate_families.py` | gate-family aggregation + cluster bootstrap CIs |
| `profile_legacy.py`, `classify_real.py` | fixture detection in trade_events.jsonl |
| `measure_consensus.py` | proves consensus.jsonl is 100% pipeline failures |
| `probe_lineage.py`, `probe_big3.py` | join-key and reasoning-field discovery |
| `verify_provenance.py` | per-day close counts that expose the replay |
