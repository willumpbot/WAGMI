# WAGMI Co-Pilot — Confluence Campaign Plan

**Created:** 2026-08-05. Status: PLAN ONLY — no test has been run under this
document. This is a pre-registration-style campaign, written BEFORE any
hypothesis below is peeked at against outcome data, exactly like
`data/copilot/PREREGISTRATION.md` (H1-H5) and the FDR discipline already
proven out in `tools/ic_factor_study.py`.

**Why this campaign exists:** `tools/copilot/SIGNAL_SCORECARD.md` and
`tools/copilot/STATE.md` record ~23 prior OOS tests of *isolated* mechanical
signals on the 14-month/25-coin corpus — every one of them null or dead
(ADD-read decayed, entry-signal panel "null across the board," market
weather refuted as a sizing gate, funding null). Testing a signal alone is
the noisiest possible form of a test. The owner's standing hypothesis,
never yet tested, is that edge is **conditional** — it shows up only when
several things align (confluence) or when a signal is restricted to the
regime it actually works in (conditioning). This document (A) locks a
methodology rigorous enough that a "survivor" means something, and (B)
enumerates the hypothesis space to run through it, across every angle:
multi-signal confluence, regime conditioning, multi-timeframe confirmation,
derivatives context, cross-sectional structure, and exit/risk-mechanics
confluence.

**This document is READ-ONLY planning.** No test in this campaign has been
executed. Building the batch scripts and running them is a separate,
future step.

---

## Part A — Locked Methodology

Every hypothesis below, when eventually run, MUST be tested through this
exact procedure. A test engine (human or agent) implementing any hypothesis
in Part B must apply every rule in this section identically — the whole
point of locking this first is that no individual test gets to pick its
own favorable methodology after seeing a promising number.

### A0. Success criterion — unlevered net expectancy (read this first, it sets the bar)

**Owner directive: leverage is NOT required and is not the target.** The
system this campaign is ultimately searching for is an **unlevered, small,
consistent, positive-after-real-cost expectancy** — accumulation-style:
buy on confluence, hold through noise, spot (or 1x), no liquidation
exposure. This changes what "a usable edge" means for every hypothesis
below:

- **Score every hypothesis on:** (1) mean **net-of-real-cost** return per
  trade/episode (using the per-liquidity-bucket cost hurdle in A6, not a
  flat assumption), (2) **hit-rate** (% of episodes with positive net
  return), (3) **average holding period** to realize the edge, and
  secondarily (4) a t-stat/Sharpe-style consistency check. This is the
  primary scorecard for Part B's results — not a leverage-survivability or
  liquidation-risk metric.
- **This LOWERS the usable-edge bar, deliberately.** A mild, real,
  statistically-clean edge that is nowhere near large enough to survive
  being levered (i.e. would have failed every leverage/liquidation test in
  `SIGNAL_SCORECARD.md`) is still a WIN under this criterion, because there
  is no liquidation path-risk to survive when unlevered — the entire class
  of "real but not big enough to lever safely" findings this project has
  already produced (2xATR stop, max-hold length) becomes directly usable
  if it clears net-of-cost, positive-expectancy, OOS+FDR+era-stable.
- **Consequence for Lens 6 (exit/risk-mechanics):** several Lens-6
  hypotheses (C15, C22, C23, C32, C34, C44) were originally framed around
  *leveraged*-liquidation path-risk (mirroring the already-validated
  WAIT-knife gate, which is explicitly a leverage/path-risk finding, not a
  return finding). Under the unlevered target, these hypotheses are
  reframed as secondary: still worth testing (avoiding a drawdown before
  a bounce shortens the unlevered holding period and improves capital
  efficiency even without liquidation risk), but they are not scored as
  primary expectancy hypotheses — Lens 1-5 and C36 (which are directly
  about return/expectancy) are the primary scorecard; Lens 6's
  liquidation-framed items are reported as secondary context.
- **A survivor's eventual pre-registration (A7) must also specify its
  success bar in these unlevered terms** — net-of-real-cost expectancy,
  hit-rate, and holding period on forward (call-ledger) data — not a
  leverage/liquidation bar, consistent with the vision in Part D.

### A1. Entry-time-safe, no look-ahead

- All signals must be computable from data available **at or before** the
  decision timestamp. Use `settled_close`/`settled_close_date` semantics
  (per `copilot.py::build_dip_read` and the 2026-08-01 correction in
  `PREREGISTRATION.md`) — the last **fully closed** daily candle, never a
  still-forming current-UTC-day bar.
- Any indicator using a rolling/trailing window (SMA, ATR percentile,
  breadth20, cross-sectional rank) must be computed using only bars up to
  and including the settled close, never bars that include or postdate the
  forward-return measurement window.
- Support/resistance (`swing_high`/`swing_low`) must exclude the
  signal-day bar itself (as `copilot.py` already does) — a support level
  computed using today's low to test whether today is "near support" is
  circular.
- 1h-timeframe confirmation signals (Lens 3) must use only 1h candles that
  closed strictly before the daily settled-close timestamp being tested,
  never candles from later in the same UTC day than the decision point
  claims to be at.

### A2. Train/test OOS split

- **Primary split**: chronological, per-coin, at the **60th percentile of
  each coin's date range** (matches `WALKFORWARD_SPLIT=0.60` already used
  in `research/longtail/xs_backtest.py` — reuse the same convention rather
  than inventing a new one). First 60% = TRAIN (hypothesis discovery /
  threshold tuning, if any), last 40% = TEST (confirmation).
- **A hypothesis is only reportable as a candidate if the effect has the
  same sign AND clears its statistical bar (A3) independently on the TEST
  fold.** A hypothesis that only "works" in TRAIN is discarded, not
  reported as a near-miss.
- No threshold in Part B may be re-tuned after looking at TEST-fold
  results. If a hypothesis's fixed threshold (e.g. `RSI_OVERSOLD=35`,
  `VOLSURGE_MULT=3.0`) needs adjustment, that adjustment happens using
  TRAIN data only, and the adjusted rule is then run once, cold, on TEST.
- **Secondary/confirmation split**: for hypotheses with enough N, also
  report a walk-forward result via `backtest/walk_forward.py`
  (`WalkForwardRunner`) as a robustness cross-check, not a replacement for
  the primary 60/40 split.

### A3. Multiple-comparisons control — the core anti-p-hacking lock

- **One family.** Every hypothesis actually run in this campaign (Part B,
  minus anything explicitly deferred as power-limited) goes into a single
  results table, tested once, TEST-fold only, and corrected together.
  There is no "run it, see if it's close, run a related variant" — each
  numbered hypothesis (C1, C2, ...) is one pre-committed test.
- **Benjamini-Hochberg FDR at q=0.10**, matching the convention already
  shipped in `tools/ic_factor_study.py` (`survives_fdr_pnl`). Compute BH
  across the full family's TEST-fold p-values. Report the BH-adjusted
  significance threshold and which hypotheses clear it.
- **Bonferroni reported alongside, never instead of.** A hypothesis that
  clears Bonferroni (the strict bar) is a stronger candidate than one that
  only clears BH; both bars are shown per finding.
- **Always report `N_tested`** (the family size) **and
  `expected_false_positives = N_tested x 0.05`** next to the results table,
  exactly as this document's own hypothesis count implies (see Part B
  summary) — if 36 hypotheses are tested, expect ~1.8 to look significant
  at raw p<0.05 by chance alone; a "survivor" is not "p<0.05," it is
  "clears BH-FDR q=0.10 in the TEST fold with the same sign as TRAIN."
- **No family-splitting to dodge the correction.** Grouping hypotheses
  into 6 lenses (Part B) is for prioritization and batching only — the FDR
  correction is applied ONCE across all hypotheses actually run, not
  per-lens. Per-lens sub-families are for organization, not for getting a
  smaller, easier-to-clear correction.

### A4. Era-awareness — the "died in Feb 2026" trap

- Every hypothesis that clears A2+A3 must additionally be checked:
  - **Pre/post split** at 2026-02-01 (the date the ADD-read decay was
    pinned to in `SIGNAL_SCORECARD.md`) — same sign and comparable
    magnitude required in both halves, or the finding is labeled
    ERA-UNSTABLE, not a candidate.
  - **Per-quarter breakdown** (2025-Q3, 2025-Q4, 2026-Q1, 2026-Q2,
    2026-Q3-partial) — report the effect in each quarter that has enough
    episodes; a finding driven by one quarter only is flagged, never
    silently averaged away.
- A survivor that is era-stable is a stronger candidate than one that
  isn't, but era-instability alone does not disqualify a hypothesis from
  being *reported* — it disqualifies it from being called anything more
  than "descriptive, not stable" (mirrors how `SIGNAL_SCORECARD.md`
  handles the ADD-read decay finding: reported honestly, not buried).

### A5. Refute-yourself checklist (mandatory, per hypothesis)

Every hypothesis report must include all five of these, following the
precedent in `tools/copilot/signal_panel_test.py`:

1. **Episode-collapse** — consecutive-day, same-symbol triggers of the
   same signal collapse to one episode (matches `signal_panel_test.py`'s
   convention and `oi_hypothesis_harness.py`'s independent-window /
   episode-collapse logic for derivatives data, where lag-1 autocorrelation
   of raw ticks has been measured at 0.97-0.99 — raw row counts are NEVER
   a valid N for anything touching `funding_oi_history.jsonl` or
   `liq_events.jsonl`).
2. **Single-coin dominance check** — report the effect both pooled
   (all episodes) and per-coin-equal-weighted (average the per-coin effect,
   then average across coins). If pooled is significant but 1-2 coins
   are driving it (check via leave-one-coin-out), label
   SINGLE-NAME-DRIVEN, not a broad edge.
3. **Net-of-realistic-cost.** For hypotheses tested on a single liquid
   name or pooled across the whole universe without a liquidity cut, the
   house-standard flat 9bps round-trip (`FEE_RT = 0.0009` from
   `signal_panel_test.py`, matching `taker_fee_bps_round_trip: 9.0` in
   `universe.json`) remains the default. **But 9bps is a liquid-majors
   number and must NOT be applied uniformly once a hypothesis is being
   read by liquidity bucket (Lens 7 / A6)** — thin alts have materially
   wider spreads and worse slippage, so every liquidity-bucketed result
   must be net of that bucket's own realistic round-trip cost (A6's cost
   table: LIQUID ≈9-15bps, MID ≈25-40bps, THIN ≈50-100bps+, with the
   coin's own `cost_bps_est`/`spread_bps` from `universe.json` used in
   place of the tier default whenever available). Always show the
   pre-cost number alongside the net number, never hide either.
4. **Minimum sample bar** — `SIGNIFICANCE_N=30` independent episodes per
   compared bucket (matches `resolve_calls.py`, `liq_hypothesis_harness.py`,
   `oi_hypothesis_harness.py`). Below n=30/bucket in either the TRAIN or
   TEST fold, the hypothesis is not run to a p-value at all — it is logged
   as `[UNDERPOWERED, n=X]` and deferred (see Part C batching, "power-gated"
   hypotheses).
5. **Direction/regime honesty** — if a hypothesis's own natural
   population splits meaningfully by side (long vs short) or by weather
   regime, that split must be reported even if not part of the original
   rule (the SIDE_LEVEL_EDGE finding — longs 9%WR/-$654 vs shorts
   42%WR/+$810 — is exactly the kind of asymmetry a pooled-only report
   would have hidden).

### A6. Liquidity/size conditioning — the cross-cutting 7th lens

**Owner thesis (analytically sound, first-class in this campaign, not an
afterthought): market efficiency scales with liquidity — a confluence edge
is far likelier to survive in the thinner, less-watched alts than in
BTC/SOL/majors, because thin names are less arbed, less algo-covered, and
slower to price-in new information.** Every hypothesis in Lenses 1-6 above,
and every future hypothesis added to this campaign, must be run through a
liquidity cut, not just tested pooled. This section locks how that cut is
computed so it can't be gerrymandered after the fact.

- **Liquidity proxy, entry-time-safe:** `liq_proxy(coin, t)` = trailing
  20-day mean daily dollar volume, `mean(close_i * volume_i)` for the 20
  daily bars up to and including day `t` (same rolling-window,
  no-look-ahead convention as every other signal in this document — a
  coin's liquidity bucket on a given day is computed from data available
  by that day only, never from its current/2026-08 liquidity rank applied
  retroactively to 2025-07). A coin that grew more liquid over the 14-month
  window must be bucketed as thin in its early history and liquid later,
  not fixed to one bucket for the whole span.
- **Secondary/confirmatory proxy:** `universe.json` / `universe_history.jsonl`
  snapshot fields (`vol24h`, `oi_usd`, `depth5_bid_usd`, `depth5_ask_usd`,
  `spread_bps`) from `research/longtail/universe_screener.py`, wherever
  multiple historical screener runs exist — use only as a cross-check on
  the rolling $-volume proxy, never as the primary bucketing variable
  (single-snapshot fields can't provide the time-varying, entry-time-safe
  bucketing the primary proxy gives).
- **The buckets must span the TRUE available liquidity range, not just
  re-slice an already-thin universe.** The 25-alt `data/longtail` universe
  is itself already liquidity-screened (`min_day_ntl_vlm_usd=1M`,
  `max_day_ntl_vlm_usd=150M`, majors excluded) — comparing its top vs.
  bottom tercile alone tests "thin-alt vs. slightly-less-thin-alt," not
  the owner's actual thesis. Buckets must include the liquid end using the
  major-coin data that already exists (`data/cache`'s BTC/ETH/SOL/HYPE/XRP
  `1h_420d`/`daily_420d` series, and/or the 5 majors with ≥500 rows in
  `data/funding_oi_history.jsonl`):
  - **LIQUID** — BTC, ETH, SOL, XRP, HYPE (majors, excluded from the
    25-alt universe by design, now used as the liquid reference class).
  - **MID** — top half of the 25-alt longtail universe by trailing
    `liq_proxy`, recomputed dynamically (see below).
  - **THIN** — bottom half of the 25-alt longtail universe by trailing
    `liq_proxy`, recomputed dynamically.
  - Bucket membership is **re-evaluated monthly** (not fixed once at the
    start of the corpus) using each coin's trailing `liq_proxy` as of that
    month's start — a static, whole-period bucketing is reported only as a
    secondary robustness cross-check, not the primary read.
- **THE HONEST COUNTERWEIGHT — per-bucket realistic round-trip cost, not
  a flat 9bps.** The whole point of this lens is that thin alts may carry
  more edge, but they also carry materially worse execution cost — a thin
  alt's edge must clear a HIGHER hurdle than a BTC-perp's 9bps to be real
  and tradeable, or "edge grows toward the thin end" is an illusion created
  by under-charging the thin bucket for its own execution cost. Locked
  per-bucket round-trip cost assumptions (defensible estimates, stated
  explicitly so they can be argued with, not hidden):
  | Bucket | RT cost assumption | Basis |
  |---|---|---|
  | LIQUID (majors) | **12bps** (range 9-15bps) | HL taker fee ≈4.5bps/side plus a small majors-typical slippage buffer; consistent with the existing house-standard 9bps floor, nudged up for a slippage margin |
  | MID (top-half 25-alt) | **30bps** (range 25-40bps) | Wider top-of-book spread + shallower depth than majors; use the coin's own `cost_bps_est`/`spread_bps` from the most recent `universe.json` screener snapshot in place of this default whenever available for that coin/period |
  | THIN (bottom-half 25-alt) | **75bps** (range 50-100bps+) | Materially wider spreads, thinner depth5, higher price-impact per $ of size; same rule — prefer the coin's own `cost_bps_est` when available, this is the fallback |
  A hypothesis's edge in a given bucket is only counted as real if its
  mean net-of-cost return (per A0's unlevered-expectancy scorecard)
  **exceeds that bucket's own cost, not the campaign's flat 9bps default**
  — report both the flat-9bps-net number (for comparability across the
  rest of this document) and the bucket-realistic-cost-net number side by
  side, and flag any case where a "thin-bucket edge" survives at 9bps but
  is erased at the 75bps realistic assumption as **COST-ILLUSORY**, not a
  candidate.
- **The test itself:** for a given hypothesis, compute its effect size
  (TEST-fold, net of that bucket's realistic cost above, same A0/A2/A3/A5
  discipline as every other hypothesis) separately in each of the 3
  buckets, then test whether effect size moves monotonically (correct
  sign, increasing magnitude, AND still clearing that bucket's own cost
  hurdle) from LIQUID → MID → THIN using a trend statistic (e.g.
  Jonckheere-Terpstra, or a simple regression of |effect| on ordered
  bucket rank). This produces **one additional p-value per parent
  hypothesis** (the "does this strengthen toward the thin end, net of
  realistic cost" trend test) which enters the SAME single BH-FDR family
  as every other test in this campaign (A3) — it is not a separate,
  easier-to-clear family.
- **Scope discipline (to avoid runaway family size):** the liquidity
  companion trend-test is run for every Tier A and Tier B hypothesis in
  Lenses 1-6 (31 of the 34 scored hypotheses — see Part B summary), but
  NOT for the three Tier C combinatorial/exploratory items (C7, C20, C28),
  to avoid compounding the campaign's already-highest multiple-comparisons
  items with a second cut on top.
- **THE MICRO-CAP DISCLOSURE (state this every time this lens's results
  are discussed):** true micro-caps (~$200k-$50M market cap, on-chain/DEX-
  traded) are the sharpest version of the owner's thesis and are **beyond
  this campaign's data and beyond what's tradeable on Hyperliquid today** —
  the thinnest end of `data/longtail`'s 25-alt universe (screened to
  ≥$1M/day volume, ≥$1.5M OI, on HL) is meaningfully more liquid than a
  true micro-cap. This campaign therefore tests the **principle** —
  does edge increase monotonically as liquidity decreases across the
  liquidity range we DO have (majors → mid-alts → thin-HL-alts) — not the
  micro-cap claim itself. **If edge demonstrably grows toward the thin end
  of what we have, that is the evidence base for a future decision to
  acquire true micro-cap/on-chain data and a DEX execution venue** — a
  separate, larger proposal this campaign only motivates, does not resolve.

### A7. THE HONESTY CEILING — read this before claiming anything

**Any hypothesis that survives A0 (real unlevered net-of-cost expectancy)
+ A2 (OOS) + A3 (FDR) + A4 (era-stable) + A5 (refute-yourself) + A6
(liquidity-honest, cost-hurdle-cleared) on this corpus is a CANDIDATE, not
a proven edge.**
This corpus (`data/longtail/ohlc`, 14 months, 25 coins) has already been
re-mined for every prior finding in this repo — `PREREGISTRATION.md`
states this explicitly as its own reason for existing. A new pattern found
on the same corpus, no matter how cleanly it clears every statistical bar
above, is still a pattern found by a research process that has now looked
at this data dozens of times. Multiple-comparisons correction inside one
campaign does not protect against multiple CAMPAIGNS across the project's
history re-mining the same underlying 25×~400 daily bars.

**Therefore: no survivor of this campaign may be described as "an edge,"
shipped to the live bot, or acted on directionally until it is
pre-registered as a new `Hn` in `data/copilot/PREREGISTRATION.md` (or a
dedicated locked harness, following the `oi_hypothesis_harness.py` /
`liq_hypothesis_harness.py` pattern) and confirmed on genuinely NEW,
forward-collected data** — via the call ledger (`call_logger.py` /
`resolve_calls.py`), the funding/OI collector, or the liquidation
collector, whichever the hypothesis needs. This mirrors exactly how H1-H5
already work: old-corpus findings are "origin" (disclosed, motivating, and
explicitly UNVALIDATED — see H4's framing), forward data is what actually
tests them. A survivor's deliverable at the end of this campaign is a new
pre-registered hypothesis with a fixed rule and success bar, not a "found
it" announcement.

---

## Part B — Prioritized Hypothesis Space

36 precise, testable rules across 6 lenses. Each entry: exact rule → data/
timeframe needed → direction → why it might beat the isolated version
already found null. Priority tiers (assigned by plausibility × testability
× distance-from-already-tested-null): **A** = run first, **B** = run if A
is inconclusive/promising, **C** = exploratory / high multiple-comparisons
risk / structurally novel-but-speculative. Hypotheses flagged
`[POWER-LIMITED]` are included for completeness but should not be scored
to a p-value until their data source clears `SIGNIFICANCE_N=30`
independent episodes (per A5.4) — see Part C.

Base daily signals referenced below (all from `data/longtail/ohlc`,
`copilot.py` / `signal_panel_test.py` definitions):
`S1` oversold (`rsi_1d<=35`), `S2` lower_bb (`bb_pos_1d<=0.25`), `S3`
near_support (`dist_to_low_pct<=6%`), `S4` uptrend_intact
(`trend_1d=="up"`, EMA20>EMA50 gated by ADX≥22), `S5` volume_surge
(`vol >= 3x` 20d avg, `VOLSURGE_MULT=3.0`), `S6` breakout (20d high
breakout, `BREAKOUT_N=20`), `S7` positive rel-strength (top-quintile
20d cross-sectional momentum, `xs_backtest.py` convention).

### Lens 1 — Multi-signal confluence (daily, `data/longtail/ohlc`)

| # | Tier | Rule | Direction | Why it might beat the isolated version |
|---|---|---|---|---|
| C1 | A | `(S1 OR S2) AND S4` — oversold/lower-BB dip that occurs *while the daily trend is still up* | Long | Isolated S1/S2 were tested pooled across all trend states, including downtrends where "oversold" often means "still falling." Restricting to `trend_1d=="up"` removes exactly the falling-knife contamination that `_classify_dip`'s WAIT gate exists to catch — this asks whether the ADD signal's decayed edge was actually hiding inside a trend-conditional subset. |
| C2 | A | `S1 AND S2 AND S4` — the existing (already-DEAD, per `SIGNAL_SCORECARD.md`) triple dip-structure signal, PLUS the uptrend filter it never had | Long | This is the most direct test of "does adding the missing trend-context ingredient revive the already-refuted `add_score>=2` rule" — a clean, pre-registered re-test of a known-dead signal with one new conditioning variable, not a fresh fishing expedition. |
| C3 | A | `S6 AND S5` — 20d breakout confirmed by same-day 3x volume surge | Long | Isolated breakout (null) and isolated volume-surge (null) were never tested together. A breakout without volume is exactly the kind of low-conviction move a mechanical breakout rule would false-positive on; volume confirmation is the textbook fix, untested here. |
| C4 | A | `S7 AND S1` — oversold dip restricted to names already in the top rel-strength quintile | Long | "Buy dips in strong names, not weak ones" — uses cross-sectional rank as a quality filter on a mean-reversion signal instead of testing either factor alone. Distinct mechanism from C1/C2 (relative strength vs. absolute trend). |
| C5 | B | `S7 AND S6` — top-quintile momentum name posting a fresh 20d breakout | Long | Momentum continuation confirmed by structural breakout; tests whether combining two null-alone signals from different families (cross-sectional momentum, price-structure breakout) produces a real signal neither carries alone. |
| C6 | B | `S3 AND S5` — price near 20d support with a same-day volume surge | Long | "Accumulation at support" — volume surge distinguishes real demand stepping in at a level from a low-liquidity drift down to it. Isolated S3 and S5 both null; untested together. |
| C7 | C | All-pairs and all-triples screen across `{S1,S2,S3,S5,S6,S7}` not already enumerated above (combinatorial sweep, ~15 pairs + ~15 triples not covered by C1-C6) | Long | Structured fishing expedition to make sure no meaningful combo is missed by hand-picking — explicitly the highest multiple-comparisons risk in this campaign; MUST be its own labeled sub-family count going into the one BH-FDR family (A3), never cherry-picked after the fact. |
| C8 | A | Mirror of C1 for shorts: `(S1' overbought rsi>=65 OR S2' bb_pos>=0.75) AND S4' downtrend (trend_1d=="down")` | Short | The SIDE_LEVEL_EDGE finding (memory: shorts 42%WR/+$810 vs longs 9%WR/-$654, real data n=22/38) already shows shorts carry the live edge — this is the direct entry-side analogue of C1, prioritized because it targets the side already empirically shown to work, not a symmetric assumption. |

### Lens 2 — Regime/vol conditioning (daily signals restricted to a regime)

Regimes from `tools/copilot/weather.py::compute_market_weather`
(`STORMY`/`WASHED_OUT`/`HEADWIND`/`NEUTRAL`, `breadth20`, `btc_above_ema50`)
and `core/quant_regime.py` (ATR-percentile vol regime, panic/trending/
consolidation/range).

| # | Tier | Rule | Direction | Why it might beat the isolated version |
|---|---|---|---|---|
| C9 | A | `S1` (oversold) restricted to `weather_regime == "WASHED_OUT"` only | Long | Isolated S1 was tested pooled across all weather regimes. WASHED_OUT is specifically breadth<20% AND BTC<50dEMA — a genuine capitulation backdrop; a mean-reversion signal may only fire cleanly when the whole market, not just one name, is oversold. |
| C10 | A | `S1` restricted to `weather_regime == "STORMY"` only | Long | Complementary test to C9 — STORMY is breadth>50% AND BTC>50dEMA (a "buy the dip in a bull market" backdrop), mechanistically different from C9's capitulation framing; both must be run since the isolated pooled test could have washed out two opposite-sign sub-regime effects that cancel. |
| C11 | B | `S2` (lower-BB bounce) restricted to `btc_above_ema50 == True` vs. `False`, reported as two separate buckets | Long | Isolated lower-BB was tested without any market-backdrop split; BTC's own trend regime is a cheap, always-available conditioning variable not yet applied to this specific signal. |
| C12 | B | `S6` (breakout) restricted to top-tercile ATR-percentile (vol-expansion) regime only | Long | Breakouts in a low-vol/chop regime are the textbook false-breakout trap; restricting to genuine volatility expansion (via `core/quant_regime.py`'s ATR-percentile) tests whether the isolated-null breakout signal was diluted by chop-regime false positives. |
| C13 | B | `S5` (volume surge) restricted to prior-day `consolidation` regime (surge OUT of quiet, not surge during already-loud markets) | Long | A volume surge means something different breaking out of consolidation vs. adding fuel to an already-volatile tape; isolated S5 pooled both cases together. |
| C14 | B | `S7` (rel-strength/momentum) restricted to `breadth20 > 50%` vs. `<50%` | Long | Cross-sectional momentum is known in traditional markets to work better in "rising tide" conditions; breadth is the market's own rising-tide gauge and hasn't been used to condition the existing `xs_backtest.py` momentum book. |
| C15 | A | Falling-knife WAIT gate (`is_falling_knife`, already VALIDATED per `SIGNAL_SCORECARD.md`) — does its forward drawdown risk (currently 42-55% chance of ≥10% 3d drawdown) get MORE extreme specifically within `WASHED_OUT` (the already-identified widest-drawdown regime)? | Risk-sizing (not directional) | Sharpens an ALREADY-validated gate rather than proposing a new entry signal — lowest-risk, highest-confidence item in this lens; a regime-conditioned leverage cap on top of the existing knife gate is a direct, actionable refinement if confirmed. |
| C16 | B | `S3` (near-support bounce) restricted to `trend_1d == "up"` only (support tests in an uptrend = pullback-to-trendline-like structure; support tests in a downtrend = "dead cat" risk) | Long | Distinct from C1 (which combines S1/S2, not S3, with trend) — isolates whether trend-context specifically rescues the support signal. |

### Lens 3 — Multi-timeframe confluence (daily + 1h)

`[POWER-LIMITED]` note: 1h OHLC (`data/longtail/ohlc/{coin}_1h.csv`) is
only available from **2026-01-12 onward** (~7 months), not the full
14-month daily span — every hypothesis in this lens has materially fewer
independent episodes available than a daily-only test, and the A2 60/40
split must be computed on the 1h-covered sub-window only, not the full
daily range.

| # | Tier | Rule | Direction | Why it might beat the isolated version |
|---|---|---|---|---|
| C17 | A | Daily `S1` (oversold) AND 1h RSI (`llm/agents/technicals.compute_rsi` on 1h OHLCV) crosses back above 30 within the trailing 6-12h of the daily settled close | Long | Daily oversold alone says "cheap," not "turning" — the 1h RSI cross adds a timing trigger that the isolated daily signal structurally cannot provide. Direct test of "does the bounce actually have to have started yet." |
| C18 | A | Daily `S2` (lower-BB) AND 1h EMA9/20/50 alignment flips to "bull" (`compute_emas` alignment field) within the trailing 6h | Long | Same logic as C17, different confirmation mechanism (trend-alignment turn vs. oscillator turn) — testing both since they may capture different failure modes of "daily says cheap, but nothing has turned yet." |
| C19 | B | Daily `S6` (breakout) AND 1h higher-high/higher-low structure sustained for ≥4h after the breakout bar | Long | Filters out breakouts that immediately fail intraday (a classic false-breakout pattern invisible at the daily-bar resolution alone). |
| C20 | C `[POWER-LIMITED]` | Daily `S3` (near-support) AND 1h volume-surge occurring in the same window as the daily support test | Long | Tightest possible confluence in this lens (3-way conjunction across 2 timeframes) — flagged lowest-tier because the expected N, after the 7-month 1h window and episode-collapse, is likely to land well under `SIGNIFICANCE_N=30`; include for completeness, defer execution until/unless 1h history is backfilled further. |

### Lens 4 — Derivatives-intertwined (funding / OI / liquidations as context)

Data: `data/funding_oi_history.jsonl` (23 symbols, ~58-60 days, lag-1
autocorrelation 0.97-0.99 on raw ticks — MUST use
`oi_hypothesis_harness.py`'s independent-window collapse, never raw rows),
`data/copilot/liquidations/liq_events.jsonl` (419 conservative episodes as
of 2026-08-03, growing daily — MUST use
`liq_hypothesis_harness.py`'s episode collapse), `data/longtail/funding/`
(per-coin funding history, full 14mo span). All items in this lens are
`[POWER-LIMITED]` relative to the daily-corpus lenses — see Part C for
exact gating.

| # | Tier | Rule | Direction | Why it might beat the isolated version |
|---|---|---|---|---|
| C21 | A `[POWER-LIMITED]` | Daily `S1` (oversold) AND `funding_extreme` (existing `DipRead.funding_extreme` flag, funding z-score > 2.5 over trailing 30d, negative-extreme side) | Long, or non-directional vol-context | "Capitulation confirmed by a crowded-short unwind premium" — funding-alone was already tested and found null (`funding_predictiveness_test.py`), but as a CONFIRMING layer on top of a price-based oversold read (not standalone), it's a structurally different claim: does funding add information conditional on price already being oversold, rather than funding predicting direction on its own. |
| C22 | A `[POWER-LIMITED]` | Daily `S1` (oversold) co-occurring with a liquidation-cascade episode (from the `liq_hypothesis_harness.py` episode set) in the same symbol within the trailing 60-120min of the daily close | Path-risk reducer (frame like WAIT-knife, not a return generator) | Extends the already-validated WAIT-knife logic (which cuts PATH risk, not return) — the hypothesis is that a cascade that has already fired means the leveraged-liquidation risk the knife gate exists to catch has already resolved, i.e. this is a candidate for WHEN it's safer to re-add after a knife WAIT, not a new directional signal. |
| C23 | A `[POWER-LIMITED]` | OI-unwind state (top-quantile OI rate-of-decline, vol-tercile-controlled per `oi_hypothesis_harness.py`) coincident with daily oversold, vs. OI-buildup-into-oversold (trapped leveraged longs still adding) | Risk-conditioning on the WAIT-knife gate | Directly extends H4 (still pre-registered, unvalidated) into a risk-modulation role on top of the ALREADY-validated knife gate: does knowing whether leverage is unwinding or still building change the 42-55% forward-drawdown risk the knife gate already measures? This is the most concrete, most defensible derivatives hypothesis in the campaign because it doesn't need a NEW directional claim, only a refinement of an existing validated one. |
| C24 | B `[POWER-LIMITED]` | Intraday funding-rate sign flip (negative→positive) as a timing trigger layered on top of a same-day daily-oversold snapshot | Long, timing refinement | Daily oversold is a static once-a-day read; a funding flip is an event that can fire mid-window and may mark the moment crowded shorts start covering — tests whether an event-based trigger beats the static daily snapshot used everywhere else in this campaign. |
| C25 | C `[POWER-LIMITED, deferred to existing harness]` | Liquidation-cascade cluster (H3, once mature) co-occurring with a live co-pilot ADD call | Diagnostic / alignment check, not a new directional claim | This is `PREREGISTRATION.md` H3's own bullet 3 ("co-pilot alignment"), listed here only so the confluence campaign's index is complete — do not build a parallel test; defer entirely to `liq_hypothesis_harness.py` and H3's existing pre-registered success bar. |

### Lens 5 — Cross-sectional (25-alt universe, `xs_backtest.py` infra)

| # | Tier | Rule | Direction | Why it might beat the isolated version |
|---|---|---|---|---|
| C26 | A | Each rebalance day, restrict `xs_backtest.py`'s top-quintile momentum names to those that ALSO show `S1` or `S2` (dip structure) that same day | Long | Distinct from C4/C5 methodologically: C4/C5 apply a fixed per-symbol threshold, C26 uses the full 25-coin panel's live cross-sectional rank each day (matches the actual `xs_backtest.py` mechanism: pullback within the current cross-sectional leadership group, not a static screen). |
| C27 | B | Gate the existing `xs_backtest.py` long-top/short-bottom quintile momentum book on trailing 10-20d cross-sectional DISPERSION (spread between top- and bottom-quintile realized returns) — only trade when dispersion is above its own trailing median | Long top-quintile / short bottom-quintile | Momentum strategies are known to need dispersion to have anything to rank; the existing XS momentum backtest (`T_STAT_BAR=2.5` in-sample, `OOS_T_BAR=2.0`) has never been conditioned on the market's own dispersion state — tests whether the unconditional book's weak/null result hides a working strategy inside high-dispersion days. |
| C28 | C | Within highly-correlated meme-coin clusters (pairwise correlation ≥0.7 over trailing 60d, using the correlation machinery implicit in `tools/copilot/book.py`'s ~0.51-0.73 avg-alt-correlation finding), test: does one coin's `S1`/`S2` dip WHILE its correlated peer is NOT dipping predict short-horizon convergence (long laggard) | Long (pairs-style) | Genuinely new mechanism not covered by any prior OOS test in `SIGNAL_SCORECARD.md` — flagged Tier C because it requires building a correlation-cluster definition first (not just applying an existing threshold), raising both implementation risk and multiple-comparisons risk if cluster boundaries are tuned post-hoc. |
| C29 | A | Market-level (not symbol-level) mean reversion: when `breadth20` hits an extreme low (`<10%`, deeper than the existing `WASHED_OUT<20%` cutoff), does the WHOLE 25-coin universe show a short-horizon (1-3d) bounce, equal-weighted | Long, universe-wide | The coarser `WASHED_OUT` bucket (breadth<20%) was already tested and REFUTED as a sizing gate (`SIGNAL_SCORECARD.md`) — this asks whether refuted-at-threshold-20% still has signal at a more extreme threshold (10%), a legitimate, pre-committed (not post-hoc-tuned) follow-up to a null result, not a re-test of the same claim. |
| C30 | B | Bottom-quintile momentum names specifically when `breadth20 > 70%` (most of the market already up) — a rotation/catch-up hypothesis | Long | Opposite mechanism from standard momentum (C5, C26): tests laggard rotation during broad strength rather than momentum continuation — distinct claim, not a variant of the same signal. |

### Lens 6 — Exit/management confluence (sharpens WAIT-knife / risk mechanics, not entries)

**Reframed under the unlevered success criterion (A0):** C15, C22, C23,
C32, C34, and C44 were originally framed around leveraged-liquidation
path-risk, mirroring the already-validated WAIT-knife gate. With leverage
not required, these are demoted to secondary/context findings — still
worth running (a shorter/shallower drawdown before a bounce still improves
unlevered capital efficiency and holding-period), but they are not part of
the primary expectancy scorecard. C35 and C36 remain primary — both are
directly about net return/expectancy, not liquidation survival.

| # | Tier | Rule | Direction | Why it might beat the isolated version |
|---|---|---|---|---|
| C31 | — | (Canonical home of derivatives-conditioned knife gate is C23 above; not duplicated here — cross-reference only.) | — | — |
| C32 | B | Does requiring 2-of-3 {`trend_1d=="down"` AND `trend_strength=="strong"`, `ret_7d_pct <= -25%`, price piercing the prior `swing_low`} sharpen the knife gate's precision vs. the current 2-condition rule (fewer WAITs on names that were actually fine)? | Risk gate precision | The existing knife gate is validated but uses only 2 conditions; testing whether a 3rd confirming condition reduces false-WAITs (unnecessary sit-outs) without eroding the real protective value already measured. |
| C33 | B | Does a `S5` volume-surge breakout OUT of the existing `is_tight_range` chop-WAIT regime override/deserve to override that WAIT (i.e., is the tight-range gate suppressing genuinely live breakouts)? | Entry-timing refinement of an existing gate | `is_tight_range` currently forces WAIT unconditionally on low daily-vol chop; this tests whether a volume-confirmed breakout signal, which is itself the exact condition that would end a tight range, should punch through that gate rather than being blocked by it. |
| C34 | B | Does the already-found "2xATR stop is NOT real tail insurance at 3-5d" result (`SIGNAL_SCORECARD.md`) change specifically when restricted to top-tercile ATR-percentile / `panic` regime (`core/quant_regime.py`) — i.e. is a fixed 2xATR stop only under-protective in calm regimes and actually fine in genuine panic? | Risk-mechanics refinement | Regime-conditions an already-tested-and-refuted risk mechanic rather than re-testing it pooled; a regime-conditioned stop distance (wider in panic, tighter in calm) is directly actionable if confirmed. |
| C35 | A | Does extending the current flat 3-5d max-hold specifically for positions where `trend_1d=="up"` AND unrealized P&L is positive (i.e., a winner riding an intact trend) outperform the flat universal cutoff, measured via MFE capture? | Exit-rule refinement | Directly operationalizes the CAPTURE WINNERS memory thread (MFE reconstruction: 68% capture, leak = winners round-tripping to losses) as a formal conditional-hold hypothesis, rather than the flat max-hold rule already found "real but not an optimum" (monotonically rising ruin with hold length, pooled across all trend states). |
| C36 | A | Is the long-side drain (SIDE_LEVEL_EDGE: longs 9%WR/-$654 vs. shorts 42%WR/+$810, n=22/38) specifically concentrated in LOW-confluence long entries (0-1 of the S1-S7 signals aligned, i.e. "solo signal" per the ENTRY-QUALITY ALPHA memory finding), while multi-signal-confluence longs (2+ aligned, per C1/C2) are NOT similarly impaired? | Diagnostic — validates or refutes whether Lens-1 confluence gates would have specifically fixed the known long-side problem | The highest-value single hypothesis in the whole campaign if confirmed: it would mean the SIDE_LEVEL_EDGE and ENTRY-QUALITY-ALPHA findings (both already independently discovered live) and the Lens-1 confluence hypotheses (C1-C8, discovered here) are the SAME underlying mechanism — i.e. confluence gating IS the fix for the long-side drain, not a separate, unrelated lever. |

### Lens 7 — Liquidity/size conditioning (CORE lens: does edge grow toward the thin end?)

**This is the owner's core thesis for the whole campaign, treated as
first-class, not an afterthought:** market efficiency scales with
liquidity, so any real confluence edge found in Lenses 1-6 is far likelier
to survive — and likely be BIGGER — in the thinner, less-watched alts than
in BTC/SOL/majors. This lens has two parts: (1) a **companion
liquidity-monotonicity trend-test** attached to every Tier A/B hypothesis
already listed above (the general protocol locked in A6), and (2) a
handful of **dedicated hypotheses** below that test the thesis directly,
prioritizing signals ALREADY found null pooled — because "null pooled, real
in the thin bucket" is exactly the isolated-signal-noise story this whole
campaign exists to re-examine, sliced by liquidity instead of by
confluence/regime. See A6 for the full liquidity-proxy, bucketing, and
per-bucket realistic-cost methodology (LIQUID≈12bps / MID≈30bps /
THIN≈75bps default RT costs) — every result in this lens is net of its
OWN bucket's realistic cost, not the flat 9bps used elsewhere in this
document. See A6's micro-cap disclosure: this lens tests the PRINCIPLE on
the thinnest HL-tradeable alts we have, not true micro-caps.

| # | Tier | Rule | Direction | Why it might beat the isolated version |
|---|---|---|---|---|
| C37 | A | **General companion protocol** (not a single test — see A6): every Tier A/B hypothesis from Lenses 1-6 (31 of them) gets one additional LIQUID→MID→THIN monotonicity trend-test, net of each bucket's realistic cost | (inherits parent's direction) | This is how the campaign checks "is Lens 1-6's edge, if any, concentrated in the thin end" systematically rather than one-off — the single most direct operationalization of the owner's thesis, applied everywhere at once instead of guessed at. |
| C38 | A | `S1` (oversold, already tested pooled-null in `signal_panel_test.py`) tested purely within THIN bucket only vs. purely within LIQUID bucket only (two flat net-of-bucket-cost comparisons, not a trend regression) | Long | The cleanest, lowest-machinery test of the owner's thesis: was the original null result actually an average of "no edge in majors" and "real edge in thin alts" cancelling out via pooling? Uses the very first signal this project ever found null. |
| C39 | A | `S2` (lower-BB bounce, pooled-null) THIN-only vs. LIQUID-only, same logic as C38 | Long | Same rationale as C38, second base signal — running both since a structural (BB) and momentum-style (RSI) oversold definition may respond differently to liquidity. |
| C40 | A | `S6` (20d breakout, pooled-null) THIN-only vs. LIQUID-only | Long | Breakouts in illiquid names are plausibly less pre-empted/arbed by algos (more real information content) but also noisier (wider spreads, gappier moves) — the realistic THIN cost hurdle (A6) is what keeps this test honest rather than just finding illusory thin-alt "edge" that's really just wider-spread noise. |
| C41 | B | `xs_backtest.py`'s cross-sectional momentum book (currently weak/marginal pooled per `xs_backtest.py`'s own `OOS_T_BAR`), restricted to bottom-liquidity tercile of the ALREADY-thin 25-alt universe (an internal re-slice, distinct from C37's majors-inclusive companion approach) | Long top-quintile / short bottom-quintile | Tests whether the existing marginal XS momentum result hides a real edge specifically in the thinnest quartile of an already-thin universe — a narrower, more internal version of the thesis worth checking even though it can't include the true LIQUID (majors) reference class. |
| C42 | B | Funding-extremity signal (already null per `funding_predictiveness_test.py`, pooled) restricted to MID/THIN bucket only vs. LIQUID (majors) only | Long/short (crowding-reversal) | Funding on illiquid perps may be less efficiently arbed by cross-exchange funding-carry desks, potentially more informative than on majors where funding is a heavily-traded, efficiently-priced factor. |
| C43 | C | Alternative/higher-power design: a single pooled regression across ALL Lens 1-6 hypotheses' episodes, `net_return ~ signal_dummy + liquidity_rank + signal_dummy:liquidity_rank interaction`, rather than 31 separate C37 trend-tests | (inherits parents' directions) | More statistically powerful and tests the thesis in one shot rather than 31 separate companion tests, but higher implementation/bug risk and harder to audit per-hypothesis. Flagged as a BUILD-TIME DESIGN CHOICE — use C43 OR the C37 companion protocol, not both stacked (stacking would double-count the same underlying question and inflate the FDR family for no informational gain). |
| C44 | A | Does the WAIT-knife path-risk gate's protective value (currently 42-55% forward drawdown risk pooled) differ by liquidity bucket — is the gate more valuable in THIN names (wider slippage/harder to size out on the way down)? | Risk-sizing refinement (secondary under A0's unlevered reframing — see Lens 6 note) | Ties Lens 7 back to the one gate already validated project-wide; a liquidity-conditioned version of an already-real finding is a safer place to find a liquidity effect than in an unvalidated new signal, and is directly actionable for position sizing even unlevered (avoiding entries right before a hard-to-exit drawdown in a thin name). |

### Summary count for A3 (multiple-comparisons family)

- **Lenses 1-6: 36 hypotheses enumerated (C1-C36)**, with C25 and C31
  explicitly deferred to existing harnesses / cross-referenced, not
  independently scored — scored family from Lenses 1-6 = **34**.
- **Lens 7 adds:** 31 companion liquidity-monotonicity trend-tests (C37's
  protocol, one per Tier A/B hypothesis from Lenses 1-6 — Tier C items C7/
  C20/C28 excluded per A6's scope discipline) **+ 6 dedicated Lens-7
  hypotheses actually committed to the family (C38, C39, C40, C41, C42,
  C44)**. C43 is a build-time ALTERNATIVE to the C37 companion protocol,
  not additive — it is not counted in the family total below; whichever
  design is actually built (C37's 31 separate trend-tests, OR C43's single
  pooled interaction regression) is what counts, not both.
- **Total scored family, assuming the C37 companion design is used:**
  34 + 31 + 6 = **71**. At raw p<0.05 per test, **expected false positives
  ≈ 71 × 0.05 ≈ 3.6** — i.e., 3-4 hypotheses are expected to look
  "significant" by chance alone even if NONE of them carry real edge. Any
  campaign report showing 3-4 raw-significant survivors and no BH-FDR
  survivors should be read as **consistent with pure noise**, not as "a
  handful of real small edges." If the C43 pooled-regression design is
  used instead of C37, recompute this total accordingly before running
  BH-FDR (34 + 1 + 6 = 41, expected false positives ≈2.05) — whichever
  design is chosen, the family size used for BH-FDR MUST be fixed and
  disclosed BEFORE results are read, per A3's no-family-splitting rule.
- Only hypotheses that clear BH-FDR at q=0.10 (A3), on the TEST fold (A2),
  era-stable (A4), pass the refute-yourself checklist (A5), and — for any
  liquidity-bucketed result — clear that bucket's realistic cost hurdle
  (A6) qualify as CANDIDATES — and even then, are subject to the Honesty
  Ceiling (A7).

---

## Part C — Batching Plan (RAM-safe execution)

The project's own operating note (machine RAM tight, ~8GB, keep concurrent
processes low) applies here even though these are backtests, not agent
swarms — the 25-coin daily corpus is small (~400 rows × 25 coins) but the
1h corpus (Lens 3) and derivatives corpus (Lens 4) are meaningfully
larger, and indicator recomputation across 34 hypotheses would be wasteful
if done independently per hypothesis. Batches are also natural units for
review — one lens's results should be read and reasoned about before the
next lens compounds the picture.

**General rules for whoever builds and runs this:**
- Run batches **strictly sequentially, one Python process at a time** —
  do not parallelize batch execution, and do not run a batch concurrently
  with anything else RAM-heavy (the live/paper bot, another research
  swarm).
- Precompute once, reuse across a batch — do not reload/re-parse the same
  CSVs once per hypothesis inside a batch.
- Every batch script is READ-ONLY against `data/`. None of these tests
  write to `data/copilot/call_ledger.jsonl`, `PREREGISTRATION.md`, or any
  live-bot state. Output goes to new files under `data/analysis/` or
  `tools/copilot/` following existing naming (`*_test.py` for hypothesis
  scripts, a results `.md`/`.json` per batch).
- The A3 multiple-comparisons correction is computed ONCE, across all
  batches' pooled TEST-fold results, after the last batch that will run —
  not per-batch. A single results table / script (e.g.
  `confluence_campaign_fdr_summary.py`) should ingest every batch's raw
  p-values and apply BH-FDR + Bonferroni across the full family, mirroring
  `tools/ic_factor_study.py`'s existing FDR block.

### Batch 0 — Shared signal panel precompute (infrastructure, run once)

Build one cached per-coin dataframe (parquet or CSV under
`data/longtail/` or a new `data/longtail/signal_panel/` dir) with columns
for every base signal S1-S7, the regime tags from `weather.py` and
`core/quant_regime.py`, and the settled-close-anchored forward returns
(1d/3d/5d, net-of-fee) already used by `resolve_calls.py`'s convention.
This feeds Batches 1, 2, and 5 without re-parsing 25 CSVs per hypothesis.
Cheapest, lowest-risk batch — build and validate this first (spot-check a
handful of rows against `copilot.py`'s live `DipRead` output to confirm
the offline panel matches the live indicator math exactly).

### Batch 1 — Lens 1: Multi-signal confluence (C1-C8)

Daily-only, uses Batch 0's panel directly. Small memory footprint
(~400 rows × 25 coins × a handful of boolean columns). Run C1-C6 first
(Tier A/B, hand-picked, high-value); run C7 (Tier C combinatorial sweep)
and C8 (short-side mirror) as a clearly separated sub-section of the same
batch output so the combinatorial sweep's larger sub-family is visible
and auditable, not blended into the hand-picked results.

### Batch 2 — Lens 2: Regime conditioning (C9-C16)

Reuses Batch 0's panel plus `weather.py`/`quant_regime.py` regime tags
(also cheap to precompute once and merge in). Same memory class as
Batch 1. C15 (knife-gate regime sharpening) should be run and read
FIRST within this batch — it's the highest-confidence, lowest-novelty-risk
item in the whole campaign (refining an already-validated gate), and a
good sanity check that the batch's regime-tagging is wired correctly
before trusting C9/C10/C14 (net-new directional claims).

### Batch 3 — Lens 3: Multi-timeframe (C17-C20)

Loads the 1h CSVs (25 coins × ~5,000 rows, ~7-month window) in addition
to Batch 0's daily panel — meaningfully heavier. Process one coin's 1h
file at a time, extract only the needed confirmation flags per daily
signal-day, discard the raw 1h frame before moving to the next coin
(explicit `del`/gc between coins if using pandas) rather than holding all
25 coins' 1h data in memory simultaneously. Run C17/C18 (Tier A) before
C19 (Tier B); treat C20 as optional/deferred per its `[POWER-LIMITED]`
flag — do not spend the batch's time budget on it unless C17-C19 show
something worth chasing further.

### Batch 4 — Lens 4: Derivatives (C21-C24; C25 deferred to existing harness)

Separate data source entirely (`funding_oi_history.jsonl`,
`liq_events.jsonl`, `data/longtail/funding/`). **Do not write new
ad-hoc collapse logic** — import and reuse
`oi_hypothesis_harness.py`'s `build_independent_windows()` and
`liq_hypothesis_harness.py`'s episode-collapse function directly, so this
batch inherits their already-verified (synthetic-selftest-passed)
pseudoreplication fixes rather than risking a second, subtly different
implementation. Per A5.4 and the harnesses' own `MIN_SPAN_DAYS_FOR_TRUST`
guards (60 days for OI, 14 days for liq — both currently unmet as of the
last recorded run 2026-08-03), **this batch's hypotheses (C21-C24) should
be scored to a p-value only once the underlying harness clears its own
maturity guard.** Before that, run the batch in "descriptive only" mode
(numbers shown, explicitly labeled `[YOUNG-SAMPLE, PROVISIONAL]`, no
p-value computed, no FDR family membership yet) — mirrors exactly how
`oi_hypothesis_harness.py` and `liq_hypothesis_harness.py` already handle
their own immaturity. Re-run this batch periodically as the collectors
accrue more days rather than treating it as a one-shot.

### Batch 5 — Lens 5: Cross-sectional (C26-C30)

Reuses Batch 0's panel plus `xs_backtest.py`'s cross-sectional ranking
machinery (whole-panel-per-day, so this batch is naturally structured
around iterating trading days rather than coins — different access
pattern from Batches 1-3, keep it a separate batch for that reason too).
C28 (correlated-pairs) requires building a 25×25 rolling correlation
matrix once (compute and cache in this batch, do not recompute per
rebalance day). Run C26/C29 (Tier A) first; C28 (Tier C, new
infrastructure) last, and treat any correlation-cluster boundary choice
made while building it as TRAIN-fold-only per A2 — do not eyeball cluster
membership using TEST-fold data.

### Batch 6 — Lens 6: Exit/risk-mechanics confluence (C32-C36)

Different underlying data (`data/trades.csv` / paper-trade history,
following the convention of `risk_mechanics_test.py`, `dd_tilt_test.py`,
`lev_band_test.py`) rather than the OHLC panel — keep separate from
Batches 1-5 for that reason. **Run C36 first** (the SIDE_LEVEL_EDGE ×
confluence diagnostic) — it directly cross-references Batch 1's C1/C2
output, so Batch 6 should not start until Batch 1 has produced results to
join against. C35 (conditional max-hold / MFE capture) should reuse
whatever MFE reconstruction logic already exists from the CAPTURE WINNERS
work rather than re-deriving it.

### Batch 7 — Lens 7: Liquidity/size conditioning (C37-C44, the core cross-cutting lens)

**Sequenced LAST, deliberately** — the C37 companion trend-tests (or the
C43 pooled-regression alternative, per the build-time choice noted in
Part B) need Batches 1-6's per-hypothesis effect sizes as their input, so
this batch cannot start until Batches 1-6 have produced results. Steps:
(1) build the `liq_proxy` panel (trailing 20d $-volume per coin per day,
entry-time-safe, monthly bucket re-evaluation) plus the majors LIQUID
reference series from `data/cache` — this is its own precompute, cache it
once, reuse across C37-C44; (2) attach the per-bucket realistic-cost table
(A6) to every return computed in this batch — no result in this batch is
reported net of the flat 9bps default, only net of its bucket's own cost;
(3) run the C37 companion trend-test across all 31 Tier A/B hypotheses
from Batches 1-6 (or build C43's pooled interaction regression instead —
pick one, document the choice, do not run both); (4) run the 6 dedicated
hypotheses C38-C42 + C44, in priority order (C38/C39/C40/C44 first, Tier
A; C41/C42 after, Tier B). Because this batch spans the full liquidity
range including majors, it additionally needs the `data/cache` majors
series loaded (BTC/ETH/SOL/HYPE/XRP `daily_420d`) — a different data
source from the rest of the campaign, so treat coverage/quality of that
cache (explicitly flagged elsewhere as "STALE, only through 2026-07-13"
for some series) as a batch-specific data-quality check before trusting
the LIQUID bucket's numbers.

### Final step — pooled FDR summary (after all batches whose data is mature enough to score)

One script ingests every batch's TEST-fold p-values (excluding any
`[YOUNG-SAMPLE, PROVISIONAL]`-only results from Batch 4 until they clear
their maturity guard, and excluding C25/C31/C43-if-C37-was-used which are
cross-references or unused design alternatives, not independent tests),
computes BH-FDR at q=0.10 and Bonferroni across the full family (using
whichever fixed family size — 71 or 41 — was disclosed before results were
read, per Part B's Summary count), and reports: total N_tested, expected
false positives, raw-p<0.05 count, Bonferroni-survivor count,
BH-FDR-survivor count, and for every survivor: TRAIN vs. TEST sign
agreement, era-stability (A4), the A5 refute-yourself checklist results,
unlevered net expectancy/hit-rate/holding-period (A0), and — for any
liquidity-bucketed survivor — whether it clears its bucket's realistic
cost hurdle (A6) or is COST-ILLUSORY. This is the single document that
gets read at the end of the campaign — individual batch outputs are
working material, this summary is the deliverable.

**Any BH-FDR survivor from that summary becomes a candidate for a new
`Hn` entry in `data/copilot/PREREGISTRATION.md`, per the Honesty Ceiling
(A7) — not a claim, not a ship, not a directional block or unblock. The
campaign's job ends at "candidate, pre-registered for forward
validation."**

---

## Part D — Vision: the incremental path from candidate to live edge

This campaign's output is a short list of CANDIDATES (A7) — the following
is the pre-committed path from candidate to anything real, so the campaign
doesn't dead-end at a results table:

1. **Prove it small, unlevered, on a few pairs.** Per A0, the target is an
   unlevered, small, consistent, positive-after-real-cost expectancy —
   not a leveraged system. Any BH-FDR survivor is first pre-registered
   (A7) as a new `Hn` with an unlevered success bar (net-of-real-cost
   expectancy, hit-rate, holding period — not a leverage/liquidation bar),
   scoped to the 1-3 symbols where the candidate was strongest (typically
   the thinnest bucket where Lens 7 showed the effect, since that's both
   where the thesis predicts the biggest edge and where the realistic-cost
   hurdle (A6) is highest — the toughest, most honest place to first prove
   it).
2. **Forward-validate, not another cut of old data.** Per A7's Honesty
   Ceiling, the pre-registered candidate is tested against genuinely new,
   forward-collected outcomes via the existing engines — the call ledger
   (`call_logger.py`/`resolve_calls.py`) for price-signal candidates, the
   funding/OI or liquidation collectors for derivatives-conditioned
   candidates — at the same `SIGNIFICANCE_N=30`-per-bucket bar already
   locked in `PREREGISTRATION.md`. No lowering the bar to get a faster
   answer (the same escape-hatch clause H1-H5 already commit to).
3. **Expand pair-by-pair, only as alpha is confirmed.** This matches the
   project's existing, already-stated convention (memory: "symbol
   expansion approved but one new symbol at a time, monitor calibration
   before next"; "no new symbols/features/ideas added without vigorous
   backtest + adversarial review first"). A confirmed candidate is added
   to the live symbol set one name at a time, each addition re-checked
   against the same forward-validation bar before the next is added — not
   a blanket "the thin-alt effect is real, unlock all 25 alts" rollout.
4. **The micro-cap/DEX question is downstream, not part of this
   campaign.** If Lens 7 shows edge genuinely growing toward the thin end
   of what we already have (HL-tradeable alts), that is the evidence base
   for a SEPARATE future proposal — acquiring true micro-cap/on-chain data
   and a DEX execution venue — to be scoped, backtested, and
   adversarially reviewed on its own, not greenlit by this campaign
   alone (per A6's micro-cap disclosure).
