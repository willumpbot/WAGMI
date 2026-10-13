# PREREG — does `funding_hot → more stop hits` hold OUT-OF-SAMPLE, and does it hold for the LIVE configuration?

**Sealed 2026-10-12 22:35, before any held-out quantity was computed.** Approved by the server
(replies 118/119 and their 08:40Z note: *"Agreed: held-out stop-hits prereg sealed after FUNDING_WIDE
reports, in its own document."*) **`PREREG_FUNDING_WIDE` (`ecf331b4`) is closed and is not touched by
this.**

---

## 1. Why this is two questions, not one

`funding_hot_stop_hits` is the **best-evidenced claim in this project** — placebo calibrated at 0.058,
effect **2.68× its own 80%-power MDE**, 17/17 leave-one-out survivals, and the live flag aligned to a
tested definition. It carded PROVEN; on my audit (reply 118) the PC downgraded it to SUPPORTED for one
reason: **never tested out of sample.**

**While establishing this prereg's canary I found two things that split the question in half.**

### 🔴 Finding A — `funding_stop.py` uses its own hand-rolled HAR, not the fitted forecast

`funding_stop.py:41-42`:

```python
Y1B = (0.0, 0.35, 0.35, 0.30)    # no intercept, equal-ish weights
Y1S = 1.0                         # no smearing correction
```

**`size_flags.py` loads the FITTED coefficients** from `volatility_forecast.json`:
`[-0.3921, 0.0521, 0.2143, 0.5201]` with smearing **1.7389**.

**These are different quantities, so the claim's "1.65 × em stop" is 1.65 × a DIFFERENT em than the
one the bot sets stops from.** Verified by reproduction:

| `em` used | baseline exceedance | `ge` effect | `gt` effect |
|---|---|---|---|
| **naive (funding_stop's own)** | **22.00%** | **+2.64 pp, t 3.31, 2,269 cells** | **+2.68 pp, t 3.04** |
| fitted (what the bot uses) | 17.18% | +2.27 pp, t 3.25 | +2.77 pp, t 3.50 |

**The naive-em row reproduces `FUNDING_STOP.md` to the digit** — +2.64/t 3.31/2,269 cells and
+2.68/t 3.04 — which is how the diagnosis was confirmed rather than assumed. **This is a fourth
`exp_move` variant, and it sits inside the evidence for a card that feeds the terminal.** It belongs
in the PC's D3 ledger.

### 🔴 Finding B — the operator (reply 121)

`funding_stop.py` flags `val >= quantile(0.80)`; the **live** scanner flags `value > cut`. Funding is
tie-heavy (the HL default `1.250e-05` is **18.2%** of non-null rows), so the two differ on **5.8%** of
coin-days: fire rates **26.33%** vs **18.92%** on this panel.

**Together these mean the published claim and the live configuration are different measurements.** So
this prereg answers both, separately and in advance.

## 2. The two primaries — named, and each answering one question

| | question | population | `em` | operator | arm |
|---|---|---|---|---|---|
| **(A) CLAIM-REPLICATION** | *Does the published claim hold on coins it never saw?* | **(c) NEW156** filtered | **naive** | **`ge`** | rank |
| **(B) LIVE-CONFIG** | *Does the condition the bot actually fires on, judged against the stop the bot actually sets, predict more stop hits on coins it never saw?* | **(c) NEW156** filtered | **fitted** | **`gt`** | rank |

**Both are reported unconditionally. Neither is promoted over the other.** They answer different
questions and I am not permitted to pick the winner afterwards:

- **(A) is the scientific replication** of the claim as published.
- **(B) is the decision-relevant number** — the one that would justify changing a live stop.
- **If (A) replicates and (B) does not, the claim is real but the live configuration does not inherit
  it**, and the honest action is to fix the configuration, not to quote (A) on the terminal.

**The full 2×2 of `em` × operator is reported for (c)** so the disagreement is legible rather than
hidden by whichever cell I chose.

## 3. Canary — already verified, which is the point

| arm | required | status |
|---|---|---|
| **(b_raw) ORIG17, unfiltered, naive em, `ge`** | **+2.64 pp, t 3.31, 2,269 cells, 145 weeks, fires 26.33%** | **✅ reproduced exactly before sealing** |
| **(b_raw) ORIG17, unfiltered, naive em, `gt`** | **+2.68 pp, t 3.04, fires 18.92%** | **✅ reproduced exactly before sealing** |

**`PREREG_FUNDING_WIDE`'s canary was a hope and it failed, voiding that run. This one is a verified
fact before the seal.** If the canary does not reproduce at run time, something changed between now
and then and **the whole run is void** — same rule as before.

## 4. Fixed design — read from the CODE, not from any write-up

**That rule is here because breaking it voided the last run and produced three other errors today.**
Everything below was read from `funding_stop.py` directly:

- **Outcome:** `move > K × em`, **strict `>`**, K = **1.65** (`K_VERDICT`). Effect in **percentage
  points** of exceedance probability.
- **`K_SET` = (1.00, 1.50, 1.65, 2.00)** reported for curve shape; **the verdict rests on 1.65 alone.**
- **`START = "2024-01-01"`** for every arm, matching the claim. A 2023 extension is a different study.
- **Cells:** `pd.qcut(em, 5)` **GLOBAL across the panel** × day. **Not per date** — that error voided
  the last run.
- **Flag:** top quintile per date, cross-sectional, `len(dropna) >= 5`, operator per arm.
- **Statistic:** mean within-cell difference, **equal-weighted week-cluster mean**, week-clustered SE.
- **Volume filter** per `PREREG_FUNDING_WIDE` Amendment 2 on all filtered arms; `(b_raw)`/`(c_raw)`
  unfiltered.
- **Verdict matrix** per Amendment 1: (CI excludes zero) × (effect ≥ MDE80) → replicates / positive
  but underpowered / does not replicate / unmeasurable.
- **Placebo gate** per Amendment 4: `SIZE_OK = (0.001, 0.09)`, **only the upper bound fatal**;
  conservative sizes labelled. **`PLACEBO = 400`**, MDE interpolated at 80% power.

## 5. Populations

| | coins | role |
|---|---|---|
| **(c) NEW156** filtered | 156 | **held out — both primaries** |
| (b) ORIG17 filtered | 17 | discovery sample, fitted em |
| **(b_raw) ORIG17 unfiltered, naive em** | 17 | **canary** |
| (c_raw) NEW156 unfiltered | 156 | volume-filter sensitivity |
| (a) ALL173 | 173 | completeness; **contaminated**, never quoted as a replication |

## 6. Recorded expectations — before the run

1. **Canary reproduces +2.64/t 3.31 (`ge`) and +2.68/t 3.04 (`gt`).** Verified; a failure means
   something changed and the run is void.
2. **P(A) — the published claim replicates on (c): ~60%.** Higher than the 45% I gave
   `funding_hot_bigger_day` because this claim is **powered on its discovery sample** (effect 2.68× its
   MDE) rather than sitting under its MDE.
3. **P(B) — the live configuration replicates on (c): ~55%.** Slightly lower, because (B) stacks two
   changes the claim was never tested under (fitted `em` AND the `gt` operator), and the `gt` arm
   flags ~30% fewer coin-days, costing power.
4. **I expect attenuation**, as in the last replication: roughly **+1.2 to +2.2 pp** on (c), against
   +2.64 in-sample. If (c) exceeds its in-sample effect I will say that was unexpected.
5. **MDE on (c): I will not guess a number.** I predicted 2–3% last time and got 3.66%; my MDE
   intuition is demonstrably unreliable, so the power table reports it and I make no claim first.

## 7. Stopping rule

- **Runs ONCE.** No re-cuts, no added arms, no changed K, no moved `START`, no swapped operator or
  `em` after the fact.
- **The only permitted amendment is a defect that would make the run invalid**, written down with its
  reason before any result is read — exactly as Amendment 4 was handled.
- **Prohibited:** quoting (a) ALL173 as a replication; quoting whichever of (A)/(B) looks better as
  "the" result; reporting a signed direction; using `caller_hash` or `starred`.

## 8. Report order, enforced by the code

**size at δ=0 → MDE → week/cell counts → canary → then (A) and (B) together → then the supporting
arms.** The equal-weighted week mean sits beside any pooled figure. No number is read before the one
above it.
