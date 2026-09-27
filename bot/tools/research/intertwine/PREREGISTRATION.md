# Frontier-2 Pre-Registration — Intertwined Non-Price Information Test

Written and committed BEFORE any outcome (win-rate, return, p-value) is computed.
Timestamp of writing: 2026-07-31 (research session).

## 0. Critical data-availability deviation (disclosed BEFORE seeing any results)

The task brief names `data/shadow/signals_*.csv` (~26 files) as the primary high-n
signal surface ("thousands of rows"). Inspection shows **every one of the 22 files
in `data/shadow/` for the live period (Jul 23–31) contains only a header row, zero
data rows.** The only files with any rows are stale `paper_trades/signals_*.csv`
files from May 30–Jun 6 (max 36 rows in one file), which predate the funding/OI
history (Jun 6+) and depth history (Jul 1+) entirely and cannot be joined to them.

**Substitution (pre-registered, not a post-hoc choice):** the signal surface used for
this study is `data/llm/decisions.jsonl`, which is the other named data source in the
brief ("Sub-signals + ensemble ... snapshot.m[].sg, snapshot.sd"). It has 4,592 total
lines; 1,825 contain a `snapshot` block spanning 2026-06-01 17:39 UTC to 2026-07-30
17:09 UTC. Each such record's `snapshot.sd` dict gives one ensemble reading per symbol
(`side`, `agree`, `dissent`, `avg_conf`, `pass_votes`) and `snapshot.m` gives per-symbol
market context (price `p`, `d1h`, `d24h`, volume ratio `vr`, per-strategy sub-signal
list `sg`). Universe: BTC, ETH, SOL, XRP, HYPE (NEAR appears only 23 times, dropped).

**Event definition:** one event = one (record_ts, symbol) pair where
`snapshot.sd[symbol].side` is `BUY` or `SELL` and `agree >= 1`. This yields on the
order of 1,825 × ~4.4 symbols ≈ 7,700 raw rows before dedup. This is the closest
faithful substitute for "every scanner signal" available in this repo snapshot, and
is still a large-n surface. This substitution is logged as a limitation in the final
report regardless of outcome.

Price labels come from Hyperliquid `candleSnapshot` 1h OHLCV, fetched **read-only over
the public HTTP API** (no bot module imports, nothing written to `data/`, `.env`, or
`data/replay/`) for BTC/ETH/SOL/XRP/HYPE, 2026-05-25→2026-08-01, saved under the
scratchpad and under `tools/research/intertwine/`. This is necessary because the
locally cached candle files under `tools/research/candle_cache/` stop at 2026-07-03,
short of the decisions.jsonl window (through 07-30).

## 1. Label

- **Primary horizon: forward 2h.** Secondary robustness check: forward 6h.
- Return is signed in the signal's direction: `signal_side * (fwd_price / entry_price - 1)`.
- Entry price = `snapshot.m[symbol].p` at event_ts (bot's own live-read price).
- Forward price = nearest HL 1h candle close at event_ts + horizon (±30min tolerance;
  NaN/dropped if no candle within tolerance).
- **Net return** = signed return − round-trip cost. Round-trip cost = 9bps (0.0009)
  fixed fee assumption + the contemporaneous `spread_bps` from `market_depth_history`
  (as-of joined, tol 10min) **when available**; if spread is not available for that
  event (pre-Jul-1, i.e. most of the window), cost = flat 9bps only. This is
  disclosed as an underestimate of true cost for the pre-Jul-1 majority of events.
- **Win** = net return > 0.

## 2. Dedupe rule (applied BEFORE any hypothesis test)

Group raw events by `(symbol, side, floor(event_ts to 4h bucket))`; keep only the
**first** occurrence per bucket. This collapses repeated LLM-cycle re-evaluations of
an unchanged read into one independent observation, per the project's documented
10–33× re-log inflation problem.

## 3. The 8 pre-registered hypotheses

All features are computed AS-OF event_ts using strictly-prior history (see §5 leak
tests). Regime mapping: decisions.jsonl top-level `regime` ∈
{trend, range, high_volatility, low_liquidity, panic}; "trending" ≡ `trend`,
"chop" ≡ `range` (documented approximation — regime is the trigger-cycle's global
read, applied to every symbol's event in that cycle, not symbol-specific).

| # | Hypothesis | Fire condition | Predicted sign | n_min |
|---|---|---|---|---|
| 1 | Crowded-side squeeze | `funding_rate` trailing pctile(30d, prior only) >90 (or <10, symmetric) for symbol × OI Δ24h same-sign-as-crowding (rising) × signal side is AGAINST the crowded side | net return of fired signals > baseline (unconditional) net return, one-sided | 30 |
| 2 | Liquidation-cascade continuation | OI Δ1h < −2% × `imbalance_0_5pct` sign == signal side sign × `vr` (volume ratio) > trailing 75th pctile ("high-vol") | net return of fired > baseline, one-sided (continuation wins) | 30 |
| 3 | Absorption fade | `imbalance_0_5pct` sign opposite `trades.buy_ratio−0.5` sign (book vs local taker prints disagree) × signal side == fade direction (opposite the taker side) | net return of fired > baseline, one-sided | 30 |
| 4 | Consensus × regime | `agree >= 2` × regime == `trend` × regime bias (via `d1h`/`d24h` sign of the *trigger* record's primary symbol as directional proxy) same-dir as signal side | net return of fired > baseline, one-sided (extends proven confluence result) | 30 |
| 5 | Crowd-vs-book contrarian | OKX `long_short_account_ratio` trailing pctile(30d) >85 (or <15, symmetric) × book `imbalance_0_5pct` opposing the crowd's implied side × signal side == contrarian (against crowd) | net return of fired > baseline, one-sided | 30 |
| 6 | Funding–premium divergence | sign(`basis_bps`) ≠ sign(`funding_rate`) (as-of joined from market_depth futures_ctx) × `spread_bps` < trailing median (tight) × signal side == sign(basis_bps) ("informed" = premium) | net return of fired > baseline, one-sided | 30 |
| 7 | Stale-positioning chop veto | `oi_volume_ratio` trailing pctile(30d) >75 × regime == `range` (chop) | net return of fired **< baseline**, one-sided (this is a veto/negative hypothesis — predicts the fired subset LOSES) | 30 |
| 8 | Depth-shock lead-lag | BTC `imbalance_0_1pct` 1-step change z-score (rolling, prior-only) \|z\| > 2 → any alt (ETH/SOL/XRP/HYPE) signal event within 30min after the shock, same direction as the shock sign | net return of fired > baseline, one-sided | 30 |

Baseline for each hypothesis = mean net return / win-rate of the **full deduped event
set for the same symbols and overlapping calendar window**, not a global constant, so
comparisons are apples-to-apples for whatever coverage window that hypothesis's inputs
allow.

## 4. Statistics

- Per hypothesis: n_fired, win-rate, mean net return (fired) vs baseline, one-sided
  Welch t-test / mean-difference test in the pre-registered direction.
- Block-bootstrap (block = 24h, since 2h/6h horizons overlap and autocorrelate),
  10,000 resamples, for the 90% CI of the mean-return difference.
- **Holm-Bonferroni correction across the 8 p-values, family α = 0.10.**
- n_fired < 30 flagged explicitly as "weak / insufficient power," reported but not
  treated as evidence either way.

## 5. Leak tests (mandatory; the run is void if any fails)

1. **As-of integrity:** assert `max(joined_source_ts) <= event_ts` for every joined
   funding/OI/depth column, for every row.
2. **Label shuffle:** randomly permute the net-return labels across events (breaking
   the true feature-outcome link) and rerun all 8 tests; every "significant" edge
   must disappear (p-values should look uniform / non-significant).
3. **Future-shift canary:** shift all joined feature timestamps forward by +1
   collector period (funding/OI: +26min median cadence; depth: +15min) relative to
   event_ts, i.e. deliberately let the join see the future, and rerun. Any hypothesis
   that becomes "significant" only under this forward-shifted join (or strengthens
   materially) is flagged as leak-driven and disqualified even if it looked clean
   under the correct join.

## 6. Tier-B model

L1-logistic regression on the full standardized feature set (all raw features behind
the 8 hypotheses, no interaction engineering), forward-chaining CV (train on earlier
folds, test on strictly later folds — no shuffling), judged **only** on OOS fee-adjusted
AUC (label = net-return-positive). This is counted as a 9th test against the same
overall budget; it is not part of the Holm family (no p-value claimed), and a
result is only "interesting" if OOS AUC materially exceeds 0.55 (arbitrary but
pre-set bar for "worth a second look" vs noise around 0.50).

## 7. Verdict rule (decided now, before results)

A hypothesis "survives" only if: (a) n_fired >= 30, (b) direction matches the
pre-registered sign, (c) p survives Holm-Bonferroni at family α=0.10, and (d) it is
not flagged by either leak test. Only a survivor is eligible for "Phase 2 shadow"
(forward-logged live, not yet acted on). Anything else is reported honestly as NO or
SUGGESTIVE (directionally right but underpowered / not Holm-significant), never
rounded up to a finding.
