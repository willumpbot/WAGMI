# WAGMI Co-Pilot — Signal Scorecard

**Last updated:** 2026-08-06. One honest page: every signal the co-pilot shows,
what it was claimed to be worth, what a rigorous out-of-sample (OOS) test actually
found, and whether you should trust it. All tests are entry-time-safe (no
look-ahead), net-of-fees (~9bps round-trip), OOS/era-split, and refute-yourself.
The standalone `*_test.py` scripts in this folder reproduce every number.

## The one-line summary

**The co-pilot has NO directional entry edge — every "which way / when to buy"
signal is dead or was never real.** What it DOES have, and what survived every
attempt to kill it, is **risk- and path-management value for a leveraged trader**:
correct liquidation math, honestly-calibrated leverage, a falling-knife path-risk
gate, correlated-exposure math, and volatility context. Use it to *not blow up*,
not to *pick winners*. It will not lie to you about which of those it is.

## Scorecard

| Signal | Was claimed | OOS verdict | Now framed as | Trust? |
|---|---|---|---|---|
| **ADD (dip) read** | "+0.5%/3d timing tilt" | **DEAD** — decayed to noise post-Feb-2026 (was +t=3.6 in 2025Q3 only, went *negative* t=-2.8 in 2026Q1). Old t=4.7 unreproducible. | "Disciplined-deployment ZONE (oversold/support structure), NOT a timing edge" | Structure yes, timing NO |
| **WAIT (falling knife)** | "avoid the drop" | **VALIDATED + era-stable** — knives actually bounce (+4%/3d), but 42-55% hit a ≥10% drawdown first that can liquidate a levered add | "Not a return-avoider; the risk is the PATH — sit out if levered, add unlevered if you want" | **YES (if levered)** |
| **Safe leverage** | "~5% liq risk" | **Was overclaimed** — single-day calc, 25-40% liq over a 3-5d hold. **Recalibrated** to horizon-aware. | Dual numbers: "single-day ceiling Nx / multi-day (3-5d) safe Mx (~4% OOS liq)" | **YES (recalibrated)** |
| **2×ATR disaster stop** | "tail insurance" | **Not insurance at 3-5d** — ~return-neutral, doesn't cut CVaR/ruin there (real tail-cut needs ~1-1.5×ATR) | "A loose 'I'm wrong' backstop, NOT validated tail insurance" | As a discipline line, not a proven hedge |
| **3-5d max-hold** | "the single most important rule" | **Real but not an optimum** — ruin rises monotonically with hold length; shorter is always safer | "A practical floor (thesis-time vs churn), not a proven sweet spot" | Yes, as discipline |
| **Market weather** | "size up in WASHED_OUT" | **Backwards + refuted as a sizing gate** — WASHED_OUT is the *widest-drawdown* regime; a regime sizing rule lost to a flat baseline | **Rewritten** to "volatility CONTEXT only; WASHED_OUT = caution, do NOT upsize" | Context only, never a size rule |
| **Mover scanner** | "look here" | **Honest** — no directional edge (~50% next-day hit-rate) but flagged names do carry elevated forward volatility (real) | "Attention/volatility only, ~50% hit-rate — not a direction" | For attention, not direction |
| **Funding line** | "carry cost, not a signal" | **Null confirmed + hard OOS test (2026-08-06)** — "fade the crowd" on majors: 8h net −0.04%, p=0.56; at 24h the random control (+0.28%) *beat* the signal (+0.12%). HL major funding sits ≈0, so "extreme funding" carries no reversion payload. `funding_crowding_calibration.py` | Unchanged — the label was already honest; now measured worth ≈ 0 | Label is correct |
| **Order-book depth / taker-flow** (L2 imbalance, taker buy/sell, long/short ratio) | (underused collected data — "intertwine it") | **NOISE — hard OOS test (2026-08-06)** on 5 majors, ~35d each, n≫30/cell. Every cell net-negative after 9bps fees; long/short ratio significant in-sample (t=+2.7) → collapsed OOS (t=+0.3); negative control centered at zero. `depth_flow_calibration.py` | "Current-STATE context only ('book is bid-heavy', 'takers lifting offers') — never a forward edge or entry tilt" | Context only, never direction |
| **Micro-cap mechanical history** (Solana cat/meme, 12 clean coins) | (owner's real arena — "edge in the thin tail") | **Clean NULL — full-moat harness (2026-08-06)**, 7 hypotheses × 12 coins, 0 survived BH-FDR+OOS; planted-edge control recovered so the null is real. Structural reason: the only place edge could live (a coin's first &lt;90d) is invisible to history (GeckoTerminal's ~180d window predates every survivor). `microcap_history_harness.py` | "History exhausted; early-life is FORWARD-only by construction" | NO (history); forward TBD |
| **Session volatility** | (new) | **VALIDATED risk-context** — US session (13-21 UTC, peak 14-15) ~25-45% more prone to sharp 1h moves; era-stable, 26/27 coins | New briefing line (time-aware): "modest but era-stable" | **YES (as vol context)** |
| **Correlation (book)** | "optimistic floor" | **Quantified** — avg alt corr 0.51 calm → 0.73 in stress; a 3-position book's ~1.5 independent bets → ~1.2 | `book.py` now prints the real number | **YES (sharpened)** |
| **Entry-signal panel** (Bollinger bounce, breakout, vol-surge, trend, rel-strength) | (owner interest) | **Null across the board.** Bollinger bounce specifically = a pre-Feb-2026 relic (t=+8.1 → -3.3, dead) | Not surfaced — entry stays discretionary | NO |
| **Maker-vs-taker execution** | (semi-auto value prop) | **Not a confident edge** — chase-on-miss negative; never-chase saving is likely sample drift, fails era-split | #5 semi-auto harness NOT built on this | NO (unproven) |
| **OI-buildup cascade risk** | (new) | **Plausible but underpowered** — 33 days only, no OOS, mostly vol-clustering | Not shipped; pre-registered (H4) to revisit at 60-90d | Pending |
| **Liquidation magnets** (`eye --deep`) | (new — "where stops sit") | **NULL, well-powered (2026-08-06)** — `liq_magnet_calibration.py`, n=193 BTC+SOL episodes: price reaches a prior-liq cluster NO more than a distance+side-matched RANDOM level (38% vs 41%, CI [−0.10,+0.04] spans 0, TRAIN −0.087 → TEST +0.048 sign-flip). The distance-matched control killed the apparent pull = it was pure proximity. | `eye --deep` line now says "price does NOT gravitate to these more than random — read as where it could ACCELERATE if tagged, not where it's headed" | Path context only, NOT a pull |

## Why "no edge" isn't a failure

The historical price data (~14 months, 25 coins) has been re-mined for every prior
idea in this project — so any "edge" found in it now is more likely an overfit than
a real pattern. The Bollinger bounce and the ADD signal are the proof: both were
genuinely real in 2025, then died in Feb-2026. A tool that kept showing them as
"edges" would cost you money on a pattern that no longer exists. Every reframe above
is the co-pilot refusing to sell you a dead signal.

## The actual path forward: forward evidence

The only honest way past the overfit ceiling is testing on data that didn't exist
when the idea was formed. That engine is running now:

- **Call ledger** (`call_ledger.jsonl`) — logs the co-pilot's own ADD/HOLD/WAIT calls
  before their outcomes exist (H1/H2 in `PREREGISTRATION.md`).
- **Liquidation collector** (`liq_events.jsonl`) — un-backfillable cascade data,
  live now (H3).
- **Pre-registered H4/H5** — OI-cascade-risk and session-liquidation clustering,
  committed with n≥30 bars and no peeking.
- **Micro-cap early-life tracker** (`early_life_watchlist.json`, live 2026-08-06) —
  the three signal nulls above all point to the SAME place any edge could live:
  thin/young names (majors are efficient; funding≈0; meme funding spikes exist but
  had only ~4-5d history). This instrument tracks freshly-discovered Solana coins
  from birth, mint-keyed and survivorship-free (it logs the deaths). ~30-60d to
  n≥30 independent young cohorts with mature outcomes. The funding-crowding and
  depth/flow tests are pre-registered to re-run on thin names once they mature.

These need **time** (60-90 days, a second market regime), not more swarms on the
exhausted history. Three more honest nulls on 2026-08-06 (funding-crowding,
depth/flow, micro-cap history) confirmed it: the testable-NOW space is picked
clean, and forcing more tests on it would be the multiple-comparisons trap, not
diligence. That's the real lever, and it's compounding daily.

## Bottom line for how to use it

- **Trust it for:** not getting liquidated (leverage, liq price, WAIT-knife, book
  correlated-exposure), fee/funding math, and volatility context (weather, session).
- **Don't trust it for:** telling you which coin goes up or when to buy. That's your
  read — and the data says your discretionary judgment genuinely beats every
  mechanical entry rule tested.
