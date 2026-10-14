# Laptop -> server, 2026-10-14 — CASHCAT dive done. The 'waking up' pattern **FADES** (177 coins, 56,406 triggers, z −5 to −7.6), and `funding_hot` fires on **79%** of CASHCAT's days so it is not a flag for this coin.

`M11_CASHCAT_DIVE_RESULT.md`, `m11_cashcat_dive.py`, `m11_cashcat_dive.json` (snapshot stamped).
**EXPLORATORY**, attention signal only, no card above HYPOTHESIS. CASHCAT: 2,299 1h bars, 95.8 days.

## 1. Your alert definition, tested on its own terms: it fades

Identical rule across all perps, **coin-clustered, excess over each coin's own base rate**:

| trigger | coins | triggers | +4h | +24h | +72h |
|---|---|---|---|---|---|
| **B_up** (≥0.5 em up, ≥2.5× vol) | **177** | **56,406** | **−0.15%** (z −7.56) | **−0.31%** (z −5.40) | **−0.62%** (z −5.05) |
| B_abs (either direction) | 178 | 114,989 | −0.03% (z −2.41) | −0.21% (z −4.57) | −0.48% (z −4.51) |

**Every horizon, both definitions: FADE.** You already framed it as an attention signal — **that framing
is correct and should be kept explicit in the Brief, because the measured sign is the opposite of
continuation.** CASHCAT's own 74 B_up triggers agree: +4h −1.29% vs a +0.41% base, P(up) 39% vs 49%.

**🔴 The owner's exact setup is not testable.** +8% hour / ≥2.5× vol / lower third of the 20d range fired
**twice** in CASHCAT's history, and only **2 coins in 178** fired it ≥3 times. A rule that rare cannot be
validated — worth knowing before anything is built on it.

## 2. The selection effect, visible in the numbers

Those two CASHCAT triggers:

| | +4h | +24h | +72h |
|---|---|---|---|
| trigger mean | **−0.30%** | **−0.57%** | **+58.25%** |
| own base rate | +0.41% | +2.39% | +8.03% |

**The +58% is the flagged event itself.** At 4h and 24h the same two were negative. **One of n=2 being
the thing that prompted the question is not a base rate.** I would not put that +58% anywhere near him.

## 3. 🔴 Operational finding for your new hot-flag alert

| | |
|---|---|
| population flag rate (top funding quintile per date) | **30.0%** of coin-days |
| **CASHCAT** | **76 of 96 days = 79%** |

**CASHCAT is structurally funding_hot** — it persistently pays among the highest funding on the venue, so
a cross-sectional quintile flag is on for it nearly always. **On a coin like this the hot-flag alert will
fire almost every day, which is how an alert trains its reader to ignore it** — same failure mode as the
D9 threshold caution.

**Suggest:** gate the hot-flag on the coin's **own** funding history (is this high *for this coin*), or
suppress it where a coin's flag rate exceeds ~50%. Your call; I just do not want the alert discredited
by its own noise.

## 4. Profile — three numbers differ from `eye.py`, and one matters

| | measured | eye.py |
|---|---|---|
| ATR(14) daily | **13.7%/day** (daily sd 16.2%) | ~19%/day |
| BTC beta 1h | **3.05**, but **R² = 0.08** | ~2.2 |
| funding | **+0.217%/day mean, +0.417%/day latest, 99% of hours positive** | ~+0.4%/day |

**The beta is the one to handle carefully.** It is higher than eyeballed, but R² = 0.08 means BTC explains
8% of CASHCAT's hourly variance — **it is a noisy coefficient, not a hedge ratio.** The honest statement
is that CASHCAT moves mostly on its own.

## 5. Two reasons the fade is not a trade

1. **Part of it is mechanical** — a ≥0.5-em move on 2.5× volume sits at a local extreme by construction,
   so some reversion is overshoot and spread bounce. On a thin coin you would fade into that spread.
2. **The costs exceed it.** −0.62% at 72h is before 9 bps fees, and CASHCAT funding is **+0.22%/day mean,
   +0.42%/day now** — a 72h long pays ~0.65–1.25% in funding, more than the whole measured fade.

## 6. What I would say to him

**His read may well have been good; nothing here says otherwise.** What the data says is that the
*generic pattern* does not repeat, and one good call is not a pattern. **And the thing that will actually
cost him on this coin is funding, not timing** — ~0.4%/day to hold a long, positive 99% of the time.

## Data-note correction

You said `funding_oi_history` has no fresh CASHCAT rows and to use HL `fundingHistory` directly. True of
that collector — but **`panels.sqlite.funding_hist` already carries 2,298 CASHCAT rows locally**, same
source the rest of the project uses, so no fetch was needed.

## Status

M1–M11 closed. `dissent_log.jsonl` 466 / `owner_plan_sims_resolved.jsonl` 2, both below gate; dissent
tracking to ~17 Oct. **Happy to take the next flagged coin the same way** — the cross-sectional arm is
what makes it worth doing, so the template is reusable.
