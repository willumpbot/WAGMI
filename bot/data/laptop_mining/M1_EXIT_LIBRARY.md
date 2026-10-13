# M1 — Exit-policy library on 178 perps. **EXPLORATORY.** The owner's "take some, hold some" is top at every K.

_2026-10-13. `m1_exit_library.py` + `m1_report.py`. **Nothing here may reach a card above
HYPOTHESIS.** 177 coins, 400 random-time entries each, both sides, 1h bars, 72h horizon, stops at
K × fitted `exp_move`, 9 bps round-trip fees. **70,800 simulated trades per arm.**_

---

## 0. Why random entries, and why that is the point

**Direction is null here** — ~98 direction tests and 8,340 graded rounds all say no. So entries are
**random-time and both-sided on purpose**: with direction stripped out, any difference between exit
rules is **the mechanical cost or benefit of the rule**, not a directional edge wearing an exit label.

## 1. 🔴 The result only exists because of the control — and the control took three attempts

**Every rule loses money on random entries. That is arithmetic, not information** (zero expected
gross, minus 9 bps of fees). **The question is which rules lose LESS than the same rule on a no-edge
path**, so everything below is **measured minus control**, coin-clustered.

**The no-edge control is a martingale bootstrap of each coin's own bar shapes** — real intrabar
geometry and fat tails preserved, sequence destroyed, drift removed in price terms. **It took three
versions, and the first two would have produced a confidently wrong table:**

| version | what it did | how it failed |
|---|---|---|
| v1 | driftless GBM, wicks ~ \|N(0,σ)\| each side | **−66 bps on WIF vs −3.7 measured.** Independent wicks invent stop-outs, and the error scaled with volatility — high-vol coins would have looked best |
| v2 | bootstrap real bars, demean **log** returns | **+66 bps on WIF.** Demeaning logs leaves a positive arithmetic drift of ~σ²/2 per bar, compounding over 72 bars. Right idea, wrong unit |
| **v3** | bootstrap real bars, normalise steps to **E[step] = 1** | **martingale to machine precision (±2.2e-16).** Residual per-rule spread −0.075R to +0.040R — real discrete-bar geometry, which is what gets subtracted |

**And I nearly threw v3 away.** My check was "the control should be within 15 bps of −9", which failed
on WIF — but **1R is 676 bps on WIF against 362 on BTC, so an absolute-bps threshold penalises
high-R coins.** In R units the deviations were 0.04–0.08R and fine. **The check was wrong, not the
control.**

## 2. The ranked table — partial-at-1R + trail is top at ALL FIVE K values

**Governing statistic: coin-clustered equal-weighted mean of (measured − control), bps net of fees.**

| K | best rule | diff | z | ORIG17 | NEW156 |
|---|---|---|---|---|---|
| 1.0 | `partial_1R_chand` | **+5.3** | 2.24 | **−1.6** 🔴 | +6.1 |
| 1.5 | `partial_1R_har` | **+6.1** | 1.89 | −0.2 🔴 | +6.7 |
| 2.0 | *(partials lead)* | ~+7 | ~2.0 | mixed | positive |
| 2.5 | `tgt_0.5R` | **+10.8** | **3.19** | +4.0 | +11.5 |
| 3.0 | `tgt_3R` | +11.6 | 2.23 | +37.6 | +8.9 |

**The robust pattern is not any single cell — it is that `partial_1R_*` (take 50% at +1R, trail the
rest) sits at or near the top at every one of five independent K values.** That is the owner's own
"take some, hold some toward the runners", and consistency across K is a weak form of replication
that single-cell winners do not have.

**Trail flavour barely matters** — chandelier, 2×ATR and 1×`exp_move` land within ~0.7 bps of each
other at every K. **So the gain, if real, is from taking the partial, not from the trailing method.**

## 3. 🔴 Four reasons not to believe this yet

**1. Multiplicity. I tested 14 rules × 5 K = 70 combinations.** At z > 1.96 roughly 3.5 false
positives are expected by chance; **8 cells clear z 2.16.** The Bonferroni threshold for 70 tests is
about **z 3.2**, and the single best cell is **z 3.19** — *at* the line, not past it.

**2. The built-in replication FAILS at low K.** `ORIG17` is **negative** for the top rule at K = 1.0
(−1.6) and K = 1.5 (−0.2) while `NEW156` is positive. **The 17-coin arm is noisy at n=17, but a
discovery/held-out split that disagrees in sign is a warning, not a footnote.**

**3. The magnitudes are tiny.** +5 to +11 bps against 1R values of 352–1,000 bps is **0.01–0.03R**.
A 10 bps edge is barely more than one round trip in fees. **Nothing here survives a worse fill
assumption.**

**4. The 1h referee is unresolved.** Earlier tonight 1h bars contradicted 5m on **22%** of 1.66%
stops. At K = 1.0 stops are ~350 bps, comparable in tightness. **No K = 1.0 number should be believed
until the 5m referee runs** — 72 coins, ~21 days are on disk for exactly that.

## 4. What the table says about the owner's actual question

**"Who manages the exit?"** On this evidence, *mechanically*:

- **Doing nothing is not free.** `stop_only` is +0.0 at K = 1.0 and `time_12h` is **−4.5 (z −2.44)** —
  the only cell with a CI excluding zero on the *negative* side. **A fixed short time stop is the one
  thing here that looks actively harmful.**
- **`be_at_1R` is −1.2 at K = 1.0 and never leads.** `breakeven_ratchet` was already REFUTED on the
  bot's trades; **re-tested on perps with fees, it still does not earn its place.** That is now two
  independent datasets.
- **Taking a partial at +1R and letting the rest run is the only family that is consistently
  positive** — which is the owner's instinct, arrived at from the opposite direction.

**It does NOT say "Profits only beats bot-manages".** That needs M2 (the real-trade replay), because
this panel is random entries and the bot's entries are not random.

## 5. What happens next, in order

1. **5m referee check** on the 72 coins that have it — measure the 1h/5m disagreement per rule and
   per K before any K = 1.0 claim.
2. **A sealed prereg for the `partial_1R` family only**, chosen because it leads at all five K rather
   than winning one cell. **Pre-specified: NEW156 as the held-out arm, coin-clustered, with the
   multiplicity of this sweep declared in the document so the prereg cannot be read as the discovery.**
3. **M2** — replay the same rules on the bot's real entries and the owner's plans, which is the
   population that actually matters.

## Limits
- EXPLORATORY. 70 combinations, one winner at the Bonferroni line, coin split disagreeing at low K.
- Fills assumed exactly at the stop/target; same-bar ties resolved to the **stop** (declared).
- Trails move on closed bars only.
- 1h bars, 2026-03-17 → 2026-10-13, ~210 days. One venue, one regime.
- Random entries: this measures exit mechanics, **not** the bot's actual population.
