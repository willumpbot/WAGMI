PREREG — does "take 50% at +1R and trail the rest" beat holding to the stop, on populations M1 never touched?

**Sealed 2026-10-13, before any quantity was computed on either held-out arm.** Follows M1
(`M1_EXIT_LIBRARY.md`, commit `9cd7c4d5`), whose sweep is the **discovery** and is declared as such
below so this document cannot be read as its own evidence.

---

## 1. 🔴 Declaring the discovery, including what disqualifies the obvious held-out arm

**M1 tested 14 exit rules × 5 stop widths = 70 combinations** on 177 coins and 70,800 random-time
entries. The `partial_1R_*` family (50% off at +1R, remainder trailed) led at **all five** K values:

| K | diff vs no-edge control | z |
|---|---|---|
| 1.0 | +4.6 to +5.3 bps | 1.95 – 2.30 |
| 1.5 | +5.6 to +6.1 | 1.78 – 1.89 |
| 2.5 | +9.7 | 2.19 – 2.27 |
| 3.0 | +10.9 to +11.2 | 2.32 |

**Best single cell across the whole sweep was z 3.19 against a Bonferroni threshold of ~3.2 for 70
tests — at the line, not past it.** The family's claim rests on *consistency across five K* rather
than any one cell.

**🔴 And `NEW156` CANNOT serve as the held-out arm.** M1 reported ORIG17 and NEW156 separately, so I
have already seen NEW156's values for exactly these rules (+5.6 to +10.0). **It is spent.** Saying
otherwise would be the "re-cut of the discovery sample" that this project's entire replication
programme exists to stop — and it is how M2 survived six readings before the equal-weighted block
mean killed it.

**So the held-out arms must be populations M1 never used at all.**

## 2. The two held-out arms, both pre-specified now

| arm | population | why it is genuinely unseen | available |
|---|---|---|---|
| **(A) LIVE** | the bot's **real** entries (`trade_events` / ledger) + the owner's plan executions (`owner_fills` / `plans.json`) | M1 entered at **random times**. The bot's entries are selected by its own pipeline — a different population, not a resample | **now** |
| **(B) FORWARD** | random-time entries drawn **only from 1h bars after 2026-10-13** | bars that did not exist when M1 ran. `candles_1h` accumulates (2026-03-17 is a permanent floor), so this arm grows by ~178 coin-days per day | **accrues** |

**A fresh random sample on the same coins and period is NOT an arm.** That is a different draw from a
population I have already mined, so it measures sampling noise, not the world. Stating that so I
cannot quietly substitute it later.

## 3. The test

| | |
|---|---|
| **rules compared** | `partial_1R_har` (50% at +1R, trail 1.0 × `exp_move`) **vs** `stop_only`, both at the same K |
| **why these two** | M1 showed the trail *flavour* is worth <0.7 bps, so the family collapses to one representative. `stop_only` is the "let it ride to the stop" baseline — the actual alternative |
| **K** | **1.65 only.** The bot's own live stop distance. Testing five K again would re-import the multiplicity this prereg exists to escape |
| **outcome** | per-trade net return, **bps of notional, 9 bps round-trip fees**, partial legs paying their own fee |
| **statistic** | paired difference per entry (same path, both rules), **equal-weighted mean over COIN-days**, printed beside pooled |
| **clustering** | arm A: **day** (and coin, reported). Arm B: **coin**, since coins dominate as in M1 |
| **CI** | block bootstrap, 4,000 reps, resampling whole clusters |
| **no-edge control** | the M1 v3 martingale bootstrap of each coin's own bar shapes, **subtracted**, because the raw difference between two exit geometries is not zero under no edge |
| **threshold** | CI excluding zero at **\|z\| > 2.24** (Bonferroni over the 2 arms) |

## 4. Decision rule, fixed now

**SUPPORT** requires **all** of:

1. arm **(A) LIVE** positive with CI excluding zero at |z| > 2.24;
2. **pooled and equal-weighted agree in sign** on arm A;
3. the effect **exceeds the simulated MDE** of §5;
4. it **survives the no-edge subtraction** (positive after the control, not merely positive);
5. arm **(B) FORWARD** positive, when it has the n of §5.

**AGAINST**: significantly negative on arm A. **UNDERPOWERED**: anything else, explicitly including
positive-but-below-MDE.

**If A and B disagree in sign, that is the result** — reported as population-dependence, with neither
promoted. A rule that helps random entries but not the bot's own entries is a fact about the bot's
entries, and worth knowing.

## 5. Power — stated before reading, and I expect it to be fatal on arm A

**Arm A is small.** The bot has on the order of **300 closed trades** and the owner a handful of plan
executions. **M1's effect is 0.01–0.03R, roughly +5 to +11 bps.** On ~300 paired trades with per-trade
noise in the tens of bps, the detectable effect is tens of bps.

**Pre-commitment: if the simulated MDE on arm A exceeds 25 bps, the verdict is UNDERPOWERED
regardless of the point estimate.** I am naming 25 because M1's candidate effect is ~10 bps, so an MDE
above 25 cannot resolve it even in principle.

**Arm B runs when it holds ≥ 30 forward days** (~5,340 coin-days), or on **2026-12-01**, whichever is
first. **No run before then** — and if I run it earlier for any reason, that run is the one that counts.

**MDE on arm B is not predicted.** My power pessimism has now missed low **four times in one session**
(both replications, chat quality 14→8 pp, caller form >15→8 pp), so the simulation reports it and I
make no forecast.

## 6. Recorded expectations

1. **Arm A: UNDERPOWERED, with a small positive point estimate.** ~300 trades cannot resolve 10 bps.
2. **Arm B: genuinely uncertain, ~50/50.** M1's consistency across five K is real structure, but 70
   combinations were searched and the best cell sat *at* the Bonferroni line.
3. **I expect the partial to look BETTER on the bot's entries than on random ones**, because the bot
   enters on signals with some momentum persistence and a partial monetises an early favourable move.
   **If arm A comes in NEGATIVE while M1 was positive, that mechanism is wrong and I say so.**
4. **No trading change on SUPPORT alone.** The deliverable is a graded claim card, not a config edit.
   `ADAPTIVE_STOPS` is off and the exit path is the server's; any change is theirs and the owner's.

## 7. Prohibited

- Quoting **NEW156** as a held-out result for these rules. It is spent (§1).
- Re-running across multiple K to find a better cell.
- Substituting a fresh random sample on the mined period for arm B.
- Reporting a **signed direction** of any kind. The outcome is an exit-mechanics quantity.
- Letting anything here exceed **HYPOTHESIS** on a card before arm B reports.

## 8. Report order, enforced

**no-edge control → MDE → cluster counts → arm A → arm B (when due) → verdict.** The equal-weighted
figure sits beside every pooled one. No number is read before the one above it.
