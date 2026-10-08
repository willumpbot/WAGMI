# Slice rule hunt (mission 4)

> **SUPERSEDED in part by `VALIDATION.md` (2026-10-08).** On the validated,
> extended history one rule does clear the bar: `avoid {agree:3+, side:SHORT}`
> (train -54.8 bps, CI [-90.8,-16.3]; oos -37.4). The multiple-comparison caveat
> still applies - it is a shadow candidate, not shippable.

_Companion prose for `RULE_CANDIDATES.json`. 2026-10-08._

## Headline

**No slice rule survives. Zero of 29 candidate slices had a training CI excluding 0, so nothing
is promoted and nothing should be shipped.** Four slices held the same sign in both halves of the
sample and belong on a forward watchlist, not in the rulebook.

## Method

Grammar and scoring taken from `bot/tools/rules_manager.py`: slices over
`symbol | side | agree(1,2,3+) | regime`, actions `avoid | favor`, and the metric is
**in-slice minus out-of-slice** mean `e_4h` in bps net of 9 bps fees — a rule must beat the rest
of the book, not merely be negative. Promotion required **both**:

1. training CI (cluster bootstrap over symbol-day, 3,000 draws) excluding 0 in the rule's direction, and
2. the sign holding out of sample.

Train 2026-03-16 → 04-29 (n=11,574). Test 2026-05-01 → 06-05 (n=3,902). Minimum 30 in-slice.

## The correction that matters

**My mission-3 write-up called BTC "the strongest slice signal and a direct candidate for the
rules manager." That was wrong, and the in-minus-out metric is why.**

| framing | BTC result |
|---|---|
| in-slice level (REGRADE.md) | −15.9 bps, CI [−30.6, −3.7] — looks significant |
| **in-slice minus out-of-slice** (correct metric) | **−9.8 bps, CI [−36.7, +15.7] — no signal** |

BTC is negative because the entire book is negative, not because BTC is distinctively worse.
An avoid-BTC rule would have been a false positive. Do not ship it.

## Watchlist (sign consistent in both halves, none significant)

| slice | action | train diff | train CI | oos diff | oos n |
|---|---|---|---|---|---|
| `agree=3+, side=SHORT` | avoid | −33.1 | [−66.6, +14.0] | −37.4 | 27 |
| `regime=rs_hi` | avoid | −31.6 | [−63.5, +62.1] | −25.5 | 494 |
| `agree=3+` | avoid | −7.6 | [−52.5, +35.1] | −31.0 | 60 |
| `symbol=BTC` | avoid | −9.8 | [−36.7, +15.7] | −7.1 | 1,787 |

The `agree=3+` pair is the most interesting because it contradicts a design assumption: more
strategies agreeing produced *worse* forward returns, consistently across both halves and at
12h in the mission-3 table (−72.6 bps). n_eff is 6–16, so it is a hypothesis. It is cheap for the
server to watch forward and would matter if real.

## Why nothing could be confirmed

- **The handoff's key criterion cannot be met.** It asks for slices where "trades AND
  forward-graded signals agree independently." Every closed-trade series on this laptop is
  corrupt (fixture flooding, fill over-credit — see `INVENTORY.md` §3), so there is no
  independent trade axis. These rest on signals alone. The server should cross-check anything
  here against its own 290-trade ledger.
- **Cluster counts are small.** Effects of 30+ bps sit inside CIs 100+ bps wide because
  n_eff is 5–16 for the interesting slices. The sample has 15,476 rows but only 177 symbol-days.
- **The regime axis is unusable.** `regime_score` buckets to rs_lo 14,818 / rs_hi 658 / rs_mid 0,
  so any rs_lo rule is near-tautological. A real regime label must be joined before the regime
  half of the grammar means anything.

## What to do instead

The largest measured effect in this whole exercise is **not a slice rule**. It is geometry:
SL-first 53.9% vs TP1-first 16.8% at a designed R:R of 1.50, i.e. roughly **−0.40R per setup**
before direction is considered (`REGRADE.md`). That is bigger than every slice effect above and
it is mechanical, not statistical. Widening stops relative to targets is the testable change
this data actually supports.
