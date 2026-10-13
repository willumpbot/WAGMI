PREREG — M4. On `funding_hot` days, does widening the stop, sizing down, or both actually pay?

**Sealed 2026-10-13 before any policy × outcome quantity was computed.** Mission M4
(`MISSIONS_PERP_CANDLES_2026-10-13.md`): *"widen-the-stop vs size-down vs both, judged on expectancy
and drawdown per unit risk (not exceedance parity). Prereg first."*

---

## 1. Why this exists: `K* = 1.770` answers a statistical question, not an economic one

`KSTAR_RECOMPUTE.md` found the stop multiple that makes a `funding_hot` day's exceedance **match** the
unflagged baseline: **K\* ≈ 1.770, +7.3%**, stable +5.1% to +7.7% across configurations.

**Exceedance parity is not a reason to do anything.** Equalising stop-hit probability tells you
nothing about whether the wider stop *pays* — a wider stop is hit less often **and loses more when
hit**. The economic question is expectancy, and I said so in that document rather than letting K\*
look actionable. **This prereg is that follow-up.**

## 2. 🔴 Contamination declared: which coins are actually clean for THIS question

**"Spent" is per question, not per coin, so this needs stating precisely:**

| already computed on NEW156 | for this question? |
|---|---|
| `funding_hot` → bigger \|move\| (+4.77%) | different outcome — magnitude, not expectancy |
| `funding_hot` → more stop hits (+2.40 pp) | different outcome — exceedance, not expectancy |
| **K\* ≈ 1.770 exceedance-parity stop (`KSTAR_RECOMPUTE`)** | **🔴 RELATED. Same flag, same stop-width lever, adjacent quantity** |
| M1 exit rules / partial-vs-stop | different lever — exit rule, not funding-conditional sizing |

**No expectancy figure for any funding-conditional sizing policy has been computed on any coin.** But
because K\* touched NEW156 with the same flag and the same lever, **NEW156 is no longer pristine.**

**So the split is reversed from the usual direction, deliberately:**
- **DISCOVERY = ORIG17** (17 coins). The original sample, already mined for everything.
- **HELD-OUT = NEW156** (156 coins), **labelled "near-clean, not clean"**, with the K\* contamination
  named in the result document every time it is quoted.

**I am not claiming NEW156 is a virgin sample for this. It is the cleanest available, and the
difference matters.**

## 3. The policies, all applied only on `funding_hot` days

Baseline on every day: stop at **1.65 × fitted `exp_move`**, risk 0.5% of equity (the live cap).

| policy | on a `funding_hot` day |
|---|---|
| **P0 baseline** | change nothing |
| **P1 widen** | stop → **1.770 × em** (K\*), risk unchanged → position shrinks automatically, since size = risk ÷ stop |
| **P2 size-down** | stop unchanged, risk → **0.5% ÷ 1.077** (the same 7.3% size reduction P1 produces) |
| **P3 both** | stop → 1.770 × em **and** risk → 0.5% ÷ 1.077 |

**P1 and P2 are deliberately matched to produce the same notional reduction**, so the comparison
isolates *where* the adjustment is applied rather than how big it is. **P1 moves the stop further
away; P2 keeps the stop and takes less risk. They are not the same trade.**

## 4. Outcomes — economic, both pre-specified

1. **Expectancy: bps of notional net of 9 bps round-trip fees.** Primary.
2. **Drawdown per unit risk: mean max adverse excursion in R.** Reported beside it, because a policy
   that improves expectancy by holding more pain is not an improvement the owner would want.

**Entries are random-time and both-sided**, as in M1 — direction is null here, so this isolates the
sizing mechanics.

## 5. Statistic, clustering, control

- **coin-clustered equal-weighted mean** of the per-coin policy difference (P*n* − P0), **printed
  beside pooled.** Coins dominate; day-clustered reported as secondary.
- **block bootstrap, 4,000 reps**, resampling whole coins.
- **The M1 v3 no-edge control (martingale bootstrap of each coin's own bar shapes) is SUBTRACTED.**
  Two different stop geometries do not give equal expectancy under no edge — that is exactly what M1's
  three control versions established, and the raw difference would measure geometry.
- **threshold |z| > 2.24** (Bonferroni over the 2 outcomes).

## 6. Decision rule, fixed now

**SUPPORT for a policy** requires **all** of: positive after the control; CI excluding zero at
|z| > 2.24 on the **held-out** NEW156 arm; pooled and equal-weighted agreeing in sign; effect above
the simulated MDE; **and the drawdown-per-unit-risk measure not materially worse.**

**If two policies both clear, the one with the better drawdown measure wins, not the one with higher
expectancy.** Fixed now so a marginal expectancy win cannot be used to justify holding more pain.

**AGAINST**: significantly negative. **UNDERPOWERED**: anything else.

## 7. Recorded expectations

1. **I expect ALL THREE to be UNDERPOWERED.** M1's exit-rule effects were 0.01–0.03R with 70,800
   trades per arm; a 7.3% size tweak is a smaller lever than changing the exit rule entirely.
2. **If anything shows, I expect P2 (size-down) to beat P1 (widen).** Mechanism: widening the stop
   keeps you in losing trades longer for the same dollar risk, and `funding_hot` days are higher
   volatility, so the wider stop converts more small losses into larger ones at the same risk budget.
   **If P1 beats P2 that mechanism is wrong and I say so.**
3. **MDE: not predicted.** My power pessimism has missed low five times this session; the simulation
   reports it.
4. **No live change on SUPPORT alone.** `ADAPTIVE_STOPS` is off, so none of this is consumed today;
   the deliverable is a graded card and a recommendation, nothing more.

## 8. Prohibited

- Quoting the ORIG17 discovery arm as evidence.
- Quoting NEW156 as a *clean* held-out sample (§2).
- Searching over K values to find a better one — **K\* = 1.770 is fixed by `KSTAR_RECOMPUTE`** and the
  size reduction is pinned to match it.
- Any card above HYPOTHESIS without the held-out arm clearing §6.

## 9. Report order

**control → MDE → counts → ORIG17 (discovery) → NEW156 (held-out) → drawdown measure → verdict.**
Equal-weighted beside every pooled figure.
