# M11 — CASHCAT dive. **The 'waking up' pattern FADES, not continues** — 177 coins, 56,406 triggers, z −5 to −7.6. And `funding_hot` fires on 79% of CASHCAT's days, so it is not a flag for this coin.

_2026-10-14. `m11_cashcat_dive.py`. **EXPLORATORY**, attention signal only, no card above HYPOTHESIS.
Source snapshot stamped. CASHCAT: 2,299 1h bars, 95.8 days (listed 2026-07-11)._

**Owner flagged CASHCAT near 0.102–0.104 and it ran ~+27%.** First leg 21:00Z, +8.3% on 2.9× volume.

---

## 1. 🔴 The structural problem, first, because it decides what any of this can claim

**The pattern was described after watching it work.** So I ran the identical rule across all ~178 perps
and treated CASHCAT's own history as a count, not as evidence. **Every forward number below is excess
over that same coin's own unconditional base rate** — "continuation" can only mean *beat the base rate*,
never *went up*.

**And the selection shows up in the numbers in the clearest possible way.** The owner's exact setup
(+8% hour, ≥2.5× volume, close in the lower third of the 20d range) fired **twice** in CASHCAT's whole
history:

| horizon | trigger mean | its own base rate |
|---|---|---|
| +4h | **−0.30%** | +0.41% |
| +24h | **−0.57%** | +2.39% |
| +72h | **+58.25%** | +8.03% |

**That +58% at 72h is the flagged event itself.** At 4h and 24h the same two triggers were *negative*.
**One of n=2 being the thing that prompted the question is not a base rate — it is the anecdote with a
mean taken over it.**

## 2. The evidence arm: the alert fades

Identical rules, all perps, **coin-clustered**, excess over each coin's own base rate:

| trigger | coins | triggers | +4h | +24h | +72h |
|---|---|---|---|---|---|
| **B_up** (≥0.5 em up, ≥2.5× vol) | **177** | **56,406** | **−0.15%** (z −7.56) | **−0.31%** (z −5.40) | **−0.62%** (z −5.05) |
| **B_abs** (either direction) | 178 | 114,989 | −0.03% (z −2.41) | −0.21% (z −4.57) | −0.48% (z −4.51) |
| A (owner's setup) | **2** | — | **too rare to pool** | | |

**Every horizon, both definitions: FADE.** This is the best-powered thing in the dive and it points the
opposite way to what an attention alert implicitly hopes for.

**CASHCAT's own B_up (n=74) agrees:** +4h **−1.29%** against a +0.41% base, **P(up) 39% vs 49%**, and it
never beat its base rate at any horizon.

**🔴 And the owner's exact setup is not testable at all.** Only **2 coins** in 178 fired it ≥3 times.
**A rule that rare cannot be validated** — which is worth knowing before anyone builds on it.

## 3. Two caveats that stop this being a trade

1. **Part of the fade is mechanical.** A ≥0.5-em move on 2.5× volume puts price at a local extreme by
   construction, so some of the reversion is overshoot and spread bounce — on thin coins you would be
   fading *into* that spread. **Excess over base rate controls for drift, not for microstructure.**
2. **The magnitudes are smaller than the costs.** −0.62% at 72h is before 9 bps fees, and **CASHCAT's
   funding is +0.217%/day on average, +0.417%/day now, positive in 99% of hours** — so a 72h long pays
   roughly **0.65%–1.25% in funding alone**, more than the entire measured fade.

## 4. Profile — and three numbers differ from `eye.py`

| | measured here | reported by eye |
|---|---|---|
| ATR(14), daily | **13.7%/day** (daily sd 16.2%) | ~19%/day |
| BTC beta, 1h | **3.05** — but **R² = 0.08** | ~2.2 |
| funding | **+0.217%/day mean, +0.417%/day latest, 99% of hours positive** | ~+0.4%/day |

**The beta is the one to be careful with.** 3.05 is higher than the eyeballed 2.2, but **R² = 0.08 means
BTC explains 8% of CASHCAT's hourly variance** — so the beta is a noisy regression coefficient, not a
usable hedge ratio. **Quoting "beta 3" as if it were stable would be the mistake here**; the honest
statement is that CASHCAT moves mostly on its own.

## 5. 🔴 `funding_hot` is not a flag for CASHCAT — it is a constant

| | |
|---|---|
| population flag rate (top funding quintile per date) | **30.0%** of coin-days |
| **CASHCAT** | **76 of 96 days = 79%** |

**CASHCAT is structurally funding_hot.** It persistently pays among the highest funding on the venue, so
a cross-sectional top-quintile flag is on for it nearly all the time.

**Operational consequence for the new `position_watch` hot-flag alert: on a coin like this it will fire
almost every day, which is how an alert teaches its reader to ignore it** — the same failure mode I
flagged for the D9 staleness threshold. **Suggest gating the hot-flag alert on a coin's own funding
history (is this high *for this coin*) rather than the cross-sectional quintile**, or suppressing it for
coins whose flag rate exceeds, say, 50%.

For completeness: CASHCAT's next-day |move| on hot days is **13.32% vs 8.67%** on its 20 not-hot days
(+53.6%). Directionally consistent with the replicated funding_hot finding, but **n=20 on the not-hot
side and 12× the replicated +4.77% effect — so I am reporting it as a count, not a magnitude.**

## 6. What I would tell the owner

1. **The alert is an attention signal and should be labelled as one — not a buy.** Measured across 56k
   triggers it mildly *fades*.
2. **His CASHCAT read may well have been good.** Nothing here says otherwise — it says the *generic
   pattern* does not repeat, and one good call is not the pattern.
3. **The thing that will actually cost him on this coin is funding**, not timing: ~0.4%/day to hold a
   long right now, positive 99% of the time.

## Limits
- 95.8 days of CASHCAT history; it listed 2026-07-11. Every CASHCAT-specific number is thin.
- Correcting the request's data note: `panels.sqlite.funding_hist` already carries **2,298 CASHCAT
  rows** locally, so no HL `fundingHistory` fetch was needed — the stale collector is
  `funding_oi_history`, a different table.
- Sign claims are reported because the owner asked; my standing rule treats direction findings with
  extra suspicion, and the fade result's value is mostly in ruling continuation *out*.
- One venue. Triggers computed on closed hourly bars with a 480h (20d) warmup for the volume median and
  the range position.
