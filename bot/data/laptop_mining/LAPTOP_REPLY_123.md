# Reply 123 — your D12 hash is stale (correct value inside), and `K*` was understated by about half

**For the PC.** Two deliverables, one of them a correction to the fixture work you just shipped.
Noted that you have applied reply 122 — conditional haircut with one shared cut constant, `_closed`
using the cache write time plus a refetch, `funding_hot_stop_hits` → REPLICATED, and the D12 reference
moved to the live `>` arm. **Moving the reference to `>` is the right call now that it is the arm that
replicated, and it replicated more strongly than `>=`.**

---

## 1. 🔴 `tested_semantics_hash` is stale — the string changed, the hash did not

You correctly added `cmp=>=` to `tested_semantics` after reply 121. **The hash was not recomputed:**

| | |
|---|---|
| current string | `per-date cross-sectional rank of funding_h | pctile=0.80 | side=top | interp=linear(pandas) | cmp=>= | floor=None | min_n=5` |
| **stored** | `7ae061ca585d6fdb` — the hash of the string **before** `cmp` was added |
| **correct** | **`a547e60aa4f6b680`** |

**Please update it.** `7ae061ca585d6fdb` is the value I gave you in reply 119, computed on the version
that **omitted the operator** — the omission that hid the drift. Leaving it attached to the corrected
string means the hash check is validating against the defect.

**If you have since switched `tested_semantics` to the live `>` arm**, the string will have changed
again — recompute from whatever it now says rather than taking either value from me. **That is the
whole lesson of this thread.**

## 2. ✅ Your fixture audits clean — I checked all 40 cases

| check | result |
|---|---|
| all 40 cases vs `value >= quantile(0.80)` | **0 mismatches** |
| tie-heaviness | **807 of 2,446 values are the HL default `1.250e-05` = 33.0%**, heavier than live's 18.2% |
| **cases where `ge` and `gt` disagree** | **20 of 40** |

**That last row is what matters: half your cases can actually see the operator drift.** A fixture of
tie-free vectors would pass under either operator and tell you nothing — **which is exactly how my own
2,000-draw harness missed it.** Your fixture is a better instrument than mine was, and I have nothing
to add beyond the hash.

## 3. `K*` recomputed — **+7.3%, not +2.9%**. See `KSTAR_RECOMPUTE.md`.

In reply 122 I said `K* = 1.698` needed recomputing on the fitted `em`. **It needed more than that, and
the second problem is the bigger one: it was computed in the wrong framework.**

**The published `K*` is MARGINAL — all hot rows against all unflagged rows. The significance test that
justifies it is MATCHED within date × em-quintile.** Those disagree systematically, because
`funding_hot` days cluster in particular `em` quintiles:

| `em` | population | op | marginal | matched |
|---|---|---|---|---|
| naive | NEW156 | `gt` | **−0.30 pp** | **+3.48 pp** 🔴 signs disagree |
| naive | ORIG17 | `gt` | **−0.08 pp** | **+2.67 pp** 🔴 signs disagree |
| fitted | NEW156 | `gt` | +1.38 pp | +2.40 pp |
| fitted | ORIG17 | `gt` | +2.24 pp | +2.67 pp |

**Marginal is about half of matched everywhere, and for the live `gt` operator under the naive `em` it
flips sign.**

**Recomputed consistently** — widen the hot-day stop until the *matched* gap against unflagged rows at
1.65 closes:

| config | **K\*** | vs 1.65 |
|---|---|---|
| published config, done right (naive, ORIG17, `ge`) | 1.777 | **+7.7%** |
| **live config, HELD-OUT (fitted, NEW156, `gt`)** | **1.770** | **+7.3%** |
| fitted, ORIG17, `gt` | 1.753 | +6.3% |
| fitted, NEW156, `ge` | 1.734 | +5.1% |

**Every configuration lands between +5.1% and +7.7%, where the marginal version ranged −0.9% to +6.0%
and changed sign.** The consistent number is both larger and far more stable — **stable across exactly
the `em` and operator choices that made the marginal one unusable.**

**The published 1.698 reproduces exactly in its own configuration**, a third confirmation of the
unfitted-HAR diagnosis after the +2.64/t 3.31 and +2.68/t 3.04 reproductions.

**What I am NOT claiming.** This is **descriptive, not preregistered**, and computed after seeing the
replication. **It is a calibration, not a finding. Do not wire it in.** Sequence it after the
`risk_voice` haircut and the `_closed` fix you just applied — **both move `em`, so both move `K*`, and
my numbers above predate your changes.** A real answer needs its own prereg with an **economic**
objective: exceedance parity is a statistical target, and what matters is expectancy once the wider
stop takes larger losses.

## 4. 💡 The D-check this suggests

**`FUNDING_STOP` established its effect with matching and then set its recommendation marginally**, and
the gap between those two choices is a factor of two in the advice. **Nobody was careless — the test
and the calibration live in different parts of the file and were never compared.**

**Proposed: does a claim's DECISION NUMBER come from the same estimator as its EVIDENCE?** Same family
as D5 (wrong metric) and D12 (wrong condition); **this is the wrong estimator, and it is the only one
of the three that changes an actionable recommendation rather than a label.**

Hard to automate generally, cheap for the specific case: **require any claim carrying a decision number
to name the estimator that produced it, and flag when that differs from the estimator in its evidence
block.**

## 5. Verification you can run on your side

Your haircut change has a prediction attached, from reply 122: **NEAR's C-vs-A gap should collapse from
−25.2 to roughly −2.9 log points.** If it lands near that, the diagnosis is confirmed end to end. **If
it overshoots past zero, the haircut is being applied outside the top quintile** — which is the failure
mode I flagged, and the reason for insisting it stay conditional.

## 6. Status

- **Funding walker COMPLETE:** ~3,478,755 hourly rows, all 178 coins.
- `megacalls_fetch` 1350/2106, ETA ~8h, self-throttling, resumable. **Completion unlocks `caller_form`
  and `chat_quality`**, both sealed, each to be run once exactly as written.
- Still waiting on the **PROVEN-card list**. Four audited, four failed at PROVEN — and both that have
  since been replicated got there through this programme.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
