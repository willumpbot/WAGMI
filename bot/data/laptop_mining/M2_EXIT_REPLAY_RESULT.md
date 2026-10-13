# M2 / ARM A — **UNDERPOWERED**, on two independent gates. And the signs disagree *again*.

**`PREREG_PARTIAL_EXIT` (`d78bbb05`), arm A (LIVE).** Replay of `partial_1R_trail` vs `stop_only` on
the bot's **295 real trades**, paired on the same path, bps net of 9 bps fees. Read in the sealed
order.

**Recorded expectation was "arm A: UNDERPOWERED, with a small positive point estimate." That is
exactly what happened.**

---

## 1. Declared interpretation, made before any number

The sealed text said *"K = 1.65 only — the bot's own live stop distance"*, and **that is ambiguous in
a way that matters.** In `FUNDING_STOP`, K multiplies `exp_move`; but **`ADAPTIVE_STOPS` is false, so
em-based stops are not live at all**, and the bot's actual stop is ~1.66% of price. `1.65 × em` would
be 5–8% — three to five times wider. **The two quantities share a number by coincidence.**

**So R is each trade's OWN stop distance `|entry − sl|`** (recovered from `TRADE_OPENED`, since
`stop_initial` is blank on most ledger rows). Measured mean **1R = 204 bps**, consistent with the
~1.66% figure plus per-trade variation. **Declared in the script header before the run.**

## 2. Counts

**295 trades · 59 day-clusters · 6 coins · mean 1R 204 bps.** No trades skipped.

**🔴 Six coins.** The prereg asked for day clustering with coin reported alongside — **but
coin-clustering on 6 units is not reportable**, so the day is the only usable cluster here. That is a
limit of the bot's universe, not a choice.

## 3. The two rules

| rule | pooled | **eq-weighted day** | win rate | stopped |
|---|---|---|---|---|
| `stop_only` | **+44.7 bps** | **−23.8 bps** | 0.32 | 0.60 |
| `partial_1R_trail` | **+19.2 bps** | **−8.8 bps** | **0.53** | **0.44** |

**🔴 Both rules are positive pooled and NEGATIVE day-weighted.** That is the era imbalance already
documented in `PROFITS_ONLY_MINING.md`: **274 of 295 trades sit in Jun–Jul**, packed into few days,
while the Sep–Oct trades are spread thinly across many. **Pooling therefore reports Jun–Jul and
day-weighting is effectively a Sep–Oct statistic.** Neither is wrong; they answer different questions,
and at a 13:1 era imbalance this sample cannot separate policy from era.

**What is mechanically coherent:** the partial rule raises the win rate from **0.32 to 0.53** and cuts
stop-outs from **0.60 to 0.44**. That is exactly what banking half at +1R should do. **It is not
evidence of profitability** — a higher win rate with smaller wins is the defining trade-off of the
rule, not a benefit.

## 4. ARM A — the verdict

| | |
|---|---|
| pooled difference | **−25.5 bps** |
| **equal-weighted day difference (GOVERNS)** | **+14.9 bps** |
| day-block CI (4,000 reps, 59 clusters) | **[−39.1, +66.0]** |
| z | **0.55** |
| signs agree? | **NO** |

**VERDICT: UNDERPOWERED — and it fails on two independent sealed criteria, not one:**

1. **Criterion 2 (pooled and equal-weighted must agree in sign): FAILS.** Pooled −25.5 against
   equal-weighted +14.9.
2. **Criterion 1 (CI excluding zero at |z| > 2.24): FAILS.** z = 0.55, CI spanning −39 to +66.
3. **The §5 MDE gate also fires independently:** the CI half-width is ~52 bps, so the detectable
   effect is far above the **25 bps** pre-committed ceiling. **At that MDE a ~10 bps candidate effect
   cannot be resolved even in principle** — which is precisely why the ceiling was written down in
   advance.

## 5. 🔴 The sign flip is the headline, and it is not new

**Pooled and equal-weighted disagree in sign. Again.** This is now the most frequently recurring
defect in the project — the same shape as M2's original death, `fattail2`, the fetch re-queue,
skipgate, the gate audit, `profits_only`, and the caller-form result earlier today where
equal-weighting callers turned **+2.7 pp into −9.1 pp**.

**Every single time, the cause has been the same:** a few units (days, callers, coins, eras) carry
most of the mass, pooling follows them, and the equal-weighted figure answers the question actually
asked. **It is worth stating as a standing rule rather than a recurring surprise: in this project, a
pooled figure quoted without its equal-weighted twin should be treated as unreported.**

## 6. Scoring my recorded predictions

| predicted in advance | outcome |
|---|---|
| **"Arm A: UNDERPOWERED"** | ✅ |
| **"with a small positive point estimate"** | ✅ governing figure +14.9 bps |
| **"~300 trades cannot resolve 10 bps"** | ✅ MDE far above the 25 bps ceiling |
| **"the partial will look BETTER on the bot's entries than on random ones"** (mechanism: the bot enters on signals with momentum, so a partial monetises an early favourable move) | **unresolved.** +14.9 bps governing vs M1's +5 to +11 is directionally consistent, **but at z 0.55 that is not evidence and I am not claiming it** |

**The mechanism is neither confirmed nor refuted. Arm B is the only thing that can settle it.**

## 7. What this does and does not say

**Does NOT say** the partial rule fails on real trades. **It says 295 trades across 59 days and 6
coins cannot resolve a 10 bps effect**, and that the era imbalance makes even the sign ambiguous.

**Does say firmly:** nothing changes in the bot. The prereg already ruled that out
(§6.4 — "no trading change on SUPPORT alone"), and arm A did not even reach SUPPORT.

**Arm B remains sealed and is the real test.** It gates at **≥30 forward days** (~5,340 coin-days) or
**2026-12-01**. It has ~900× arm A's coin-day count and is the only arm with a chance of resolving a
10 bps effect. **No run before the gate.**

## Limits
- 59 day-clusters, 6 coins, 13:1 era imbalance (274 of 295 trades in Jun–Jul).
- R is each trade's own stop; horizon truncated to 72h for both rules (the bot's real cap was 96h).
- 1h bars, justified by today's 5m referee (0.2–0.6% ordering disagreement, <1.1 bps bias).
- Fills assumed exactly at stop/target; same-bar ties resolved to the stop.
- Owner-plan executions (6 fills) are too few to report separately and are excluded from arm A.
