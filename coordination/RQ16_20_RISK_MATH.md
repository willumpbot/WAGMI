# RQ16+RQ20 — Streak Structure & Monte Carlo Ruin Math (2026-07-01)

Script: `bot/tools/research/rq16_20_risk_math.py` (reuses the exit-geometry backtest
engine read-only). Machine output: `bot/data/cache/exit_geometry_bt/rq16_20_risk_math.json`.
Everything below: n=90 live trades (2026-06-01→07-01, trades.csv), MC = 10k paths.

---

## PART A — Are the losing streaks random, or structural?

Win = pnl>0 (crumb-honest: 24/90 wins, median win $17, 9 wins under $5; median loss -$4.35).

| Slice | n | WR | max losing streak | shuffle median max | p(max ≥ obs) | runs-test p (clustered) |
|---|---|---|---|---|---|---|
| ALL | 90 | 26.7% | **16** (Jun 9 → Jun 19) | 11 | 0.099 | **0.012** |
| pre-Jun7 | 13 | 61.5% | 2 | 2 | 0.90 | 0.58 |
| Jun7+ | 77 | 20.8% | 16 | 13 | 0.25 | **0.024** |

**Verdict: losses are clustered beyond chance, even within the bad era.** 10k permutations
of the *same* outcomes produce this few win/loss runs only 1.2% of the time (2.4% inside
Jun7+ alone — so it is not just era-mixing). Direct autocorrelation: **WR after a loss =
20.0% (n=65) vs after a win = 45.8% (n=24)**. The bot's next-trade odds roughly double
after a win. A 16-loss streak at true 26.7% WR is p≈0.10 under IID — long but the streak
*length* alone isn't the anomaly; the *clustering* is.

Where do streak-losses (runs ≥3; 57 of 90 trades sit inside one) live?
- **By session: nowhere special.** Asia 16 / EU 22 / US 19 streak-losses vs session totals 28/30/32 — proportional. Session is not the cluster driver.
- **By symbol: nowhere special** for streaks; but HYPE is the only net-negative symbol overall (n=20, WR 25%, **-$574**).
- **By regime: labels are junk for this question** — "unknown" (n=30) holds +$1,722 (the golden era rows are mostly unlabeled). One real pocket: all trend-labeled regimes combined (trend/trending/trending_bear/trending_bull) = **1 win in 15** (-$498). Small-n (15) — flag, don't act; fragility: still 1/14 after dropping the best.

**Interpretation:** clustering is *temporal* (bad regimes-in-time produce runs of bad
trades), not a fixed session/symbol pocket you can filter out. Consequence for risk math:
IID Monte Carlo understates drawdown risk → block bootstrap (block=5) is the honest
headline, shown below. Killed hypothesis (a win): "streaks live in one session/symbol —
filter it" is dead; the fix is streak-aware sizing, not a filter.

## PART B — Monte Carlo ruin (10k paths, $2k start, 250 trades ≈ 4 months at ~2/day)

Per-trade R distributions from the exit-geometry engine replay of all 90 trades
(fees in, funding excluded — 536h hole; slight pessimism for shorts):

| Distribution | n | WR | mean R | median R | min R |
|---|---|---|---|---|---|
| **S3 forward** (restored BE 0.3R/lock 0.6R) | 90 | 70.0% | **+0.031** | +0.076 | -1.15 |
| S3 on Jun7+ entries only | 77 | 68.8% | **-0.082** | +0.074 | -1.15 |
| V0 pessimistic (current geometry) | 90 | 45.6% | -0.008 | -1.01 | -1.15 |
| V0 Jun7+ (stress) | 77 | 41.6% | -0.141 | -1.01 | -1.15 |

**The killer number: even the S3-restored geometry has NEGATIVE mean R on the Jun7+ entry
mix.** 70% WR with +0.03R mean = crumb wins vs full-R losses. Leverage multiplies edge
AND variance; with edge ≈ 0, it only buys ruin. Kelly check: S3-all full-Kelly ≈
mean/var = 0.031/0.81 ≈ **3.8% risk/trade → current 1x (1%) is already ~quarter-Kelly**.
S3-Jun7+ Kelly = **zero** (negative edge → optimal leverage is 0).

Mapping (empirically anchored): risk/trade = 1.0% of equity per 1x leverage. Pre-Jun7
median risk was $199 at 2x lev on ~$10k ≈ 1%/x — matches. (Jun7+ median risk $9.31 =
the bot currently trades at ~0.05x on this scale; ruin risk today is ~nil and so is growth.)

Block-5 bootstrap (streak-preserving, per Part A). Ruin = 50% DD from peak; halving = equity ≤ $1k:

| Lev (risk/trade) | S3 fwd: P(ruin) / P(half) / med final | V0 pess: P(ruin) / P(half) / med final | V0-Jun7+ stress: P(ruin) |
|---|---|---|---|
| 1x (1%) | 0.0% / 0.0% / $2,131 | 0.5% / 0.3% / $1,922 | 10.5% |
| 2x (2%) | 2.8% / 1.3% / $2,235 | **29.8% / 17.9% / $1,767** | 78.0% |
| 3x (3%) | **20.5% / 10.0% / $2,280** | 67.6% / 41.3% / $1,553 | 95.6% |
| 4x (4%) | 43.9% / 21.5% / $2,304 | 87.8% / 57.8% / $1,340 | 99.2% |
| 5x (5%) | 65.3% / 32.9% / $2,257 | 96.2% / 69.0% / $1,145 | 99.8% |

Read the median-final column: from 2x→5x under S3, median growth is FLAT ($2,235→$2,257)
while P(ruin) goes 2.8%→65%. **Above ~2x there is no growth to buy — only variance.**
P(25% DD) is already 57% at 2x even under the forward assumption: a 25% drawdown is the
*expected* cost of doing business at 2x, not a failure signal.

Fragility (drop single best R obs, IID): S3 2x ruin 0.8→2.0%, median final $2,238→$1,905
(growth goes negative-ish — the edge is 1-2 trades thin). V0 2x ruin 19→29%. Direction
survives; magnitudes do not graduate (n=90, one month, one regime cycle — THE_STANDARD).

## The leverage-ramp table (what evidence justifies each step)

| Step | Risk/trade | Gate (all required) | MC basis |
|---|---|---|---|
| **1x — NOW** | 1% | none; this is ~quarter-Kelly of the *best* measured dist | ruin ≤0.5% even pessimistic |
| **2x** | 2% | (1) S3-style lock geometry live; (2) **n≥30 live trades, mean R ≥ +0.10** and WR ≥55%; (3) survives drop-best-trade; (4) owner accepts P(25%DD)≈57% | S3 fwd ruin 2.8%, pess 30% — gate exists to kill the pess branch |
| **3x** | 3% | n≥60 live at 2x with mean R ≥ +0.20, era-split positive both halves, streak-aware de-sizing live (Part A autocorr) | ruin 20.5% under today's fwd dist = NOT justified by any current evidence |
| **4x–5x** | 4-5% | n≥100 with mean R ≥ +0.30; re-run this MC on the live distribution first | today: 44-65% ruin under the OPTIMISTIC dist — unreachable |

**Bottom line:** the path back to bigger positions is not a leverage decision, it is a
**mean-R decision**. Fix expectancy first (exit geometry restore + entry mix — 28 longs
at 29% WR in a bear did the damage), collect 30 honest trades, and 2x self-justifies.
Every step beyond 2x currently buys ruin probability and zero median growth. Streak
clustering is real (p=0.012): any ramp must include after-loss de-sizing, since the
measured post-loss WR (20%) is half the post-win WR (46%).

Adversarial self-checks: (1) MC has no circuit breakers / LLM exit layer → overstates
live ruin somewhat; (2) R dists come from a mechanical sim that does not reproduce
post-Jun7 live behavior (sign agreement 71%) — they measure the *geometry*, not the live
stack; (3) funding excluded (536h hole); (4) regime labels unreliable pre-cleanup; (5)
250-trade horizon assumes ~2/day is actually achieved — at the current ~1/day it is 8 months.
