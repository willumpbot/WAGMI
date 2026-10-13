# M4 — widen the stop vs size down on `funding_hot` days. **UNDERPOWERED — and the drawdown verdict FLIPS SIGN depending on the denominator, which turns out to be unavoidable.**

_2026-10-13. `m4_funding_sizing.py`. Prereg sealed **`1a00b1cf`**, amended **`7c699867`** before any
policy × outcome quantity was computed. Ran **once** as amended. 177 coins, 67,739 entries,
`funding_hot` coin-days only._

**Held-out arm is labelled NEW156 by inheritance; the actual count here is 160 non-ORIG17 coins.**
**It is NEAR-CLEAN, NOT CLEAN** — `KSTAR_RECOMPUTE` touched these coins with the same flag and the
same stop-width lever.

---

## 1. The answer, in the mission's own terms

**The mission asked which is better: widen the stop to K\*, size down, or both — judged on expectancy
and drawdown.** The answer:

1. **On expectancy: UNDERPOWERED.** `P1 − P2 = +0.0015% of equity per trade`, CI
   `[−0.0000, +0.0031]`, **z 1.91 against a 1.96 threshold, and below the 0.0022 MDE.** No verdict.
2. **On drawdown: there is no answer, and §4 proves there cannot be one.** The sign flips with the
   choice of denominator, and both denominators are confounded — in opposite directions.
3. **🔴 And the economically useful finding: the whole question is worth about 8 cents a trade on a
   $5,000 account.** `+0.0015%` of equity is **$0.075 per trade** — smaller than the round-trip fee.
   **This lever is not where the money is**, which is the same shape as M9's answer about leverage.

## 2. Checks that had to pass before any arm could be read

| check | result | |
|---|---|---|
| **determinism (amendment A1c)** | `P2/P0 = 0.93220` vs `1.65/1.770 = 0.93220` | **exact** |
| **no-edge control** | −0.0097 to −0.0112% of equity, all four policies | ≈ −(fee), correct sign and scale |
| **flag rate** | fired on **29.0%** of coin-days, not 20% | expected: `>=` on tie-heavy funding (reply 121) |
| **counts** | 177 coins, ORIG17 17 / held-out 160, 67,739 entries | |

**The determinism check is the one I care about most.** The amendment predicted, from algebra alone
and before running, that P2 must equal P0 × 0.93220 exactly. It does, to five decimals. **That is the
instrument confirming the thing I corrected the prereg for** — and had the sealed bps-of-notional unit
survived, this arm would have read exactly `0.0000` with a tight CI and looked like a precise null.

## 3. Results

### Expectancy, % of equity per trade, control subtracted

| | ORIG17 (discovery) | **held-out 160 (near-clean)** |
|---|---|---|
| P0 baseline | +0.0112 (z 0.87) | −0.0043 (z −1.07) |
| P1 widen | +0.0112 (z 0.84) | −0.0025 (z −0.67) |
| P2 size-down | +0.0104 (z 0.83) | −0.0040 (z −1.08) |
| P3 both | +0.0105 (z 0.85) | −0.0023 (z −0.68) |
| **D = P1 − P2 (primary)** | +0.0008 (z 0.47) | **+0.0015, CI [−0.0000,+0.0031], z 1.91** |
| D = P3 − P2 | +0.0001 (z 0.04) | +0.0017, **z 2.04** |

**Pooled and equal-weighted agree in sign on every row** (pooled values in the JSON; the largest
divergence is 0.0011 pp). **That is a cleaner agreement than M2 arm A managed**, and it is the one
part of this result I would call solid.

### 🔴 P3 crossed the threshold and must NOT be promoted

`D = P3 − P2` reads **z 2.04**, clearing 1.96, while the sealed primary reads 1.91 and does not.
**P3 is P1 scaled by a further 0.9322 and inherits P1's geometry — the amendment declared in advance
that it carries no independent information.** Its own MDE is 0.0023 against an effect of 0.0017, so it
fails the MDE test regardless.

**This is exactly the result multiplicity correction exists for, and it is worth being explicit that I
would have "found" something had I sealed P3 as primary.** The prereg fixed the primary before the
numbers existed, which is the only reason this is a footnote and not a finding.

## 4. 🔴 The structural finding: "widen vs size down" has no normalisation-free answer

This is the part worth keeping. The drawdown result **reverses** depending on the denominator:

| drawdown, held-out arm | P1 widen | P2 size-down | winner |
|---|---|---|---|
| **% of equity** | 0.3794 | **0.3667** | **P2**, by +0.0127, z 46.3 |
| **per unit risk (in R)** | **0.7588** | 0.7868 | **P1**, by −0.0280 |

*(R figures are the reported % of equity divided by each policy's own risk — 0.500% and 0.4661%. A
transformation of the output above, not a second run.)*

**Both denominators are confounded, in opposite directions:**
- **In % of equity**, P2 looks better partly because **it simply risks fewer dollars** (0.4661% vs
  0.500%). Some of its advantage is "bet less", not "bet better".
- **In R**, P1 looks better partly because **R *is* the stop, and P1's is wider** — the same price
  excursion is a smaller number of R. That is the artifact the amendment caught.

**And the two cannot be fixed at once. `notional = risk ÷ stop`, so matching notional AND dollar risk
forces the same stop — i.e. the same policy.** Any comparison of "widen" against "size down" at equal
notional is therefore *necessarily* unmatched on dollar risk, and vice versa.

**So the mission's question does not have an empirical answer. It has a preference answer:** widening
the stop holds your dollar risk at 0.5% and shrinks the position; sizing down shrinks the dollar risk
and keeps the stop. **Which you prefer is a statement about whether 0.5% per trade is the quantity you
want held constant — and that is the owner's call, not a number.** Both arms agree on the flip
(ORIG17 −0.0270 R, held-out −0.0280 R), so this is a property of the construction, not noise.

## 5. Recorded expectations, scored

| sealed expectation | outcome |
|---|---|
| **7.1 — all three UNDERPOWERED** | **HELD** for the one estimated contrast (withdrawn for P2/P3 by amendment A1e, since a deterministic quantity cannot be underpowered) |
| **7.2 — if anything shows, P2 beats P1** | **🔴 MISSED.** The point estimate runs the other way: P1 − P2 is **positive** (+0.0015), not negative |
| 7.3 — MDE not predicted | n/a; measured 0.0022% of equity |

**My stated mechanism is not supported, and the prereg obliged me to say so plainly:** I argued a wider
stop "keeps you in losing trades longer for the same dollar risk, so it converts small losses into
larger ones on high-volatility days." **The expectancy sign is the opposite of that prediction** (not
significantly, but opposite), while the **drawdown** result in % of equity *is* consistent with the
mechanism. So the honest reading is that my mechanism describes the **path pain** correctly and the
**expectancy** not at all — and that I had merged the two into one claim.

**This is my power pessimism missing low a sixth time**, in a direction I should note: I predicted
UNDERPOWERED and got z 1.91, which is underpowered by 0.05 of a z. The call was right and the margin
was far thinner than "all three underpowered" implied.

## 6. What I would and would not take to the owner

**Would not:** any recommendation to change stop width or size on `funding_hot` days. The primary
contrast does not clear, the drawdown comparison has no clean denominator, and `ADAPTIVE_STOPS` is off
so nothing consumes this today anyway.

**Would:** the magnitude. **At $5,000 and 0.5% risk, the gap between the best and worst of these four
policies is about $0.08 per trade.** Combined with M9 — where leverage turned out not to move P&L at
all — the pattern across two independent studies is that **the geometry dials are economically
irrelevant at this account size, and the dials that matter are risk-per-trade and whether to be in the
trade.** That is worth saying as a conclusion, not as four more tables.

## Limits
- One venue, `funding_hot` coin-days only, 2026-03-17 → 10-13, 1h bars.
- Random-time both-sided entries: **direction is null by construction**, so this measures sizing
  mechanics and says nothing about entry quality.
- Target fixed at 3.30 × `em` for every policy (amendment A1d) so a policy moves only the stop; a
  policy set that also moved the target would answer a different question.
- Same-bar stop/target ambiguity counted as the **stop** throughout (conservative).
- Drawdown is **not** control-subtracted — a martingale has adverse excursions too, so the absolute dd
  levels (~0.37%) are not "edge", only the differences between policies are comparable.
- K\* = 1.770 fixed from `KSTAR_RECOMPUTE`; no search over K, per sealed §8.

## VOID RUN 1 — and it exposed a worse defect than the bug
`HIST` pointed at `hist/`; the directory is `history/`. All 178 funding files were missed, every coin
was skipped — **and the script still printed `VERDICT: UNDERPOWERED` and scored expectation 7.2 as
`MISSED`, from zero rows.** `(nan > 0) == (nan > 0)` is `True`, and `nan < 0` is `False`, so an empty
panel walked straight through the verdict block and produced confident-looking output.

**A harness that renders a verdict out of no data is the absence-is-not-evidence failure living inside
the instrument** — the same family as my six `j4` false alarms, where the detector was the thing that
broke. Fixed structurally, not by correcting the path: the script now **halts** if fewer than 50 coins
carry funding, or if the arms come back with fewer than 20 held-out / 3 discovery coins. **The verdict
block is now unreachable on an empty panel by construction.**
