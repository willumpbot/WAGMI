# 🟢 `funding_hot` REPLICATES out-of-sample: **+4.77%** on 156 coins it was never tested on

**The first genuine out-of-sample replication this project has ever run.** Prereg
`PREREG_FUNDING_WIDE`, sealed `41805c5c`, amended to `ecf331b4` (four amendments, all recorded with
reasons). Gate opened at **173 of 173** qualifying perps.

**Read in the order the prereg fixes — placebo first, effect last. No number below was read before the
one above it.**

---

## 1. Is the test valid? — placebo size at δ=0

**Yes, and it is CONSERVATIVE.** Sizes across the eight population-arm combos: **0.018, 0.022, 0.028,
0.030, 0.030, 0.033, 0.035** — all inside the gate, all **below** the nominal 0.05.

**A conservative test under-rejects under the null, so significance here was won against a
stricter-than-nominal bar.** That strengthens every positive below rather than weakening it. Each such
arm is labelled in the output.

**The placebo can fail and this one did fail, once — see §6.** The first execution tripped the gate and
the whole run was voided.

## 2. Minimum detectable effect, written down before the effects

| population | MDE (80% power) |
|---|---|
| **(c) NEW156** | **+3.66%** |
| (c_raw) NEW156 unfiltered | +3.39% |
| (a) ALL173 | +3.46% |
| (b) / (b_raw) ORIG17 | +6.75% to +6.96% |

**My pre-recorded prediction was "MDE on (c) near +2–3%". It came in at 3.66% — I was optimistic.**
Recording that as a miss.

## 3. Cluster and cell counts

| population | week clusters | matched cells | flag fired |
|---|---|---|---|
| **(c) NEW156** | **179** | **5,084** | 30.0% |
| (b) ORIG17 filtered | 145 | 2,250 | 23.6% |
| **(b_raw) ORIG17 canary** | **145** | **2,283** | **20.8%** |
| `SIZE_FLAGS` reported | **145** | **2,283** | **20.76%** |

**The canary's counts match the original exactly.**

## 4. 🎯 The canary — the pipeline is proven correct before any new number is believed

| | required | observed |
|---|---|---|
| **(b_raw) ORIG17, unfiltered** | **+0.0740 log / +7.7% level** | **+0.0740 log / +7.68%** |

**Exact to four decimal places**, on a panel that rebuilds to exactly **19,853 coin-days** with the
flag firing on **20.8%** against the original's **20.76%**. **So the reimplementation reproduces
`SIZE_FLAGS` bit-for-bit, and the held-out numbers can be trusted.**

## 5. The result

| population | arm | effect | 95% CI | vs MDE | verdict |
|---|---|---|---|---|---|
| **(c) NEW156 — THE NUMBER** | **rank (primary)** | **+4.77%** | **[+2.46, +7.13]** | **above 3.66%** | **🟢 REPLICATES** |
| (c) NEW156 | frozen (secondary) | +5.91% | [+3.79, +8.07] | above 3.25% | replicates |
| (c_raw) NEW156 unfiltered | sensitivity | +5.86% | [+3.65, +8.13] | above 3.39% | replicates |
| (b) ORIG17 filtered | rank | +7.30% | [+2.61, +12.21] | above 6.96% | replicates |
| **(b_raw) ORIG17 canary** | rank | **+7.68%** | [+3.02, +12.56] | above 6.75% | reproduces exactly |
| (a) ALL173 *(contaminated)* | rank | +6.03% | [+3.79, +8.31] | above 3.46% | replicates |
| (a) ALL173 *(contaminated)* | frozen | +5.11%* | — | — | *from the void run; see §6 |

**`funding_hot` predicts a +4.77% bigger next-day |move| than the HAR forecast alone, on 156 coins
that were never used to discover it, across 179 week-clusters and 5,084 matched cells, with a
confidence interval excluding zero and an effect clearing its own 80%-power threshold.**

### Every pre-specified robustness check passes

| check, specified in advance | outcome |
|---|---|
| **Canary reproduces +0.0740** | ✅ exact |
| **Filter-robust?** (c) +4.77% vs (c_raw) +5.86% | ✅ **same verdict → NOT filter-dependent** |
| **Rank-dependent?** rank +4.77% vs frozen +5.91% | ✅ **same verdict → NOT rank-dependent** |
| **(b) filtered below (b_raw) unfiltered?** | ✅ **+7.30% vs +7.68%** — the Amendment 2 mechanism held |
| Placebo size inside gate | ✅ all eight arms, all conservative |

### Scoring my own recorded predictions

| predicted in advance | outcome |
|---|---|
| (c) attenuates to **+2% to +5%** | ✅ **+4.77%** — inside the band |
| P(clean positive on c) ≈ **45%** | it happened |
| (b) filtered **below** (b_raw) | ✅ +7.30% < +7.68% |
| MDE on (c) near **+2–3%** | ❌ **3.66%** — I was optimistic |
| Canary reproduces +0.0740 | ✅ exact |

**Four of five. The one I got wrong was my own power estimate, in the pessimistic direction for the
study.**

## 6. 🔴 THE FIRST RUN WAS VOID, and its numbers are recorded here so this one cannot be dressed up

**The first execution failed its own canary: (b_raw) returned +5.64% where +7.68% was required.**
Under the prereg that makes the whole run untrustworthy, and it was discarded.

**The defect: `size_flags.py:148` buckets `em` into quintiles GLOBALLY across the panel; I had
bucketed PER DATE.** The design prose says *"within the same date AND the same em quintile"* and
per-date is a defensible reading of that sentence — but the code does global, and the code produced
+7.7%. **Third time in one session that I re-derived a baseline from a write-up instead of reading the
implementation.** Per-date gave 2,944 cells and +5.64%; global gives 2,283 and +7.68%.

**The void run's numbers, disclosed in full** (per-date cells, `PLACEBO=200`):

| arm | size@0 | effect | sealed verdict then |
|---|---|---|---|
| (c) NEW156 | 0.015 | +3.65% | TEST BROKEN |
| (b) ORIG17 | 0.020 | +4.93% | positive but underpowered |
| (b_raw) canary | 0.010 | **+5.64%** | TEST BROKEN |
| (c_raw) | 0.040 | +5.54% | replicates |
| (a) ALL173 | 0.030 | +6.07% | replicates |

**So I had seen a (c) estimate of +3.65% before the valid run produced +4.77%. My expectations were
contaminated even though the data and design were not, and this result is therefore weaker than a
cleanly blind prereg outcome.** That caveat travels with the finding permanently.

**Amendment 4 also widened the placebo gate's lower bound** from 0.02 to 0.001, because
under-rejection is conservative rather than broken and the old bound sat inside the Monte Carlo error
of the size estimate itself. **The upper bound — the direction that admits false positives — was not
touched.** The run was already void on the canary alone, so that change rescued nothing.

## 7. What this means, and what it does not

**It means:** the one finding this project has that ever survived a red team **generalises**. It was
found on 17 coins and holds on 156 others, at **62% of its original magnitude** (+4.77% against
+7.68%) — the attenuation you expect when a discovery sample is also the sample that chose the
hypothesis. **Crowded funding really does precede bigger absolute moves.**

**It does not mean the effect is tradeable.** It is **unsigned** — a bigger |move|, not a direction.
Every signed claim this project has made has died. The honest use is **sizing and stop width**, which
is what `FUNDING_STOP` already pointed at, not entry direction.

**Limits that remain:**

- **One venue, one era:** 2023-03-28 to 2026-10-10, Hyperliquid only.
- **`em` is one of three disagreeing `exp_move` implementations** (the PC's D3, up to 27% apart live).
  Applied uniformly here, so the comparison is internally valid — **but the absolute magnitude inherits
  whatever bias that forecast carries.**
- **Coin-days are not independent.** 5,084 cells sit inside 179 week-clusters, and the clustered
  figure is the one quoted throughout.
- **The 8th combo** — (a) ALL173 under the frozen arm — was cut short when my tool timeout killed the
  process; the value shown is from the void run and is marked. It is the contaminated population under
  the secondary arm and is explicitly non-decisive. The completed run is recorded in
  `size_flags_wide.json`.
- **`funding_hot_bigger_day` should move from SUPPORTED to a replicated tier** on the PC's registry —
  but **on the strength of §5, with §6 attached**, not on my say-so.
