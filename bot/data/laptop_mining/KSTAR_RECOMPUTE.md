# `K*` recomputed — the published **+2.9%** understates it by about half. Consistent answer: **+7.3%, K\* ≈ 1.77**

_2026-10-12. **Descriptive, NOT preregistered. No verdict is claimed and none should be quoted as a
test result.** This supersedes the `K* = 1.698` figure in `FUNDING_STOP.md` for two independent
reasons._

---

## 1. Why it needed redoing

**Reason one — the wrong forecast.** `funding_stop.py:41-42` hardcodes `Y1B=(0.0,0.35,0.35,0.30)`,
`Y1S=1.0` — no intercept, no smearing — where the bot's `exp_move` uses the fitted
`[-0.3921,0.0521,0.2143,0.5201]` with smearing `1.7389`. **The published `K*` is a multiple of a
different quantity than the stop it was advising on.**

**Reason two, and the larger one — the wrong framework.** The published `K*` is a **marginal**
calculation (all hot rows vs all unflagged rows). The significance test that justified it is
**matched** within date × em-quintile. **Mixing them understates the effect, because `funding_hot`
days cluster in particular `em` quintiles and the matching is what removes that confound:**

| `em` | population | op | marginal | matched |
|---|---|---|---|---|
| naive | NEW156 | `ge` | +0.97 pp | **+2.37 pp** |
| naive | NEW156 | `gt` | **−0.30 pp** | **+3.48 pp** 🔴 signs disagree |
| naive | ORIG17 | `gt` | **−0.08 pp** | **+2.67 pp** 🔴 signs disagree |
| fitted | NEW156 | `gt` | +1.38 pp | **+2.40 pp** |
| fitted | ORIG17 | `gt` | +2.24 pp | **+2.67 pp** |

**The marginal figure is roughly half the matched one everywhere, and for the live `gt` operator under
the naive `em` it has the opposite sign.** Where they disagree the matched figure is the defensible
one — that is the entire reason the study matched in the first place.

## 2. The published number reproduces exactly in its own configuration

**Marginal, naive `em`, ORIG17, `ge` → `K* = 1.698` (+2.9%).** Identical to `FUNDING_STOP.md`. **That
is a third independent confirmation of the unfitted-HAR diagnosis**, alongside the +2.64/t 3.31 and
+2.68/t 3.04 reproductions.

## 3. `K*` computed consistently — widen the hot-day stop until the MATCHED gap closes

Solves: *mean over cells of* `P(move > K*·em | hot) − P(move > 1.65·em | unflagged)` *= 0*,
week-clustered.

| `em` | population | op | matched gap at 1.65 | **K\*** | vs 1.65 | |
|---|---|---|---|---|---|---|
| naive | ORIG17 | `ge` | +2.72 pp | 1.777 | **+7.7%** | the published config, done right |
| **fitted** | **NEW156** | **`gt`** | **+2.40 pp** | **1.770** | **+7.3%** | **← live config, HELD-OUT. The number.** |
| fitted | ORIG17 | `gt` | +2.67 pp | 1.753 | +6.3% | live config, in-sample |
| fitted | NEW156 | `ge` | +1.69 pp | 1.734 | +5.1% | fitted `em`, study operator |

**Every configuration lands between +5.1% and +7.7%.** Compare the marginal version, which ranged
**−0.9% to +6.0%** and changed sign — **the consistent calculation is not only larger, it is stable
across exactly the `em` and operator choices that made the marginal one unusable.**

## 4. What I would and would not do with this

**Would:** treat **K\* ≈ 1.77 (+7.3%)** as the candidate widening for `funding_hot` days, derived on
**156 held-out coins**, under the **live flag**, against the **fitted forecast**, in the **same
framework that established the effect**.

**Would not:**

- **Quote it as a test result.** It is descriptive, computed after seeing the replication, on a
  quantity nobody preregistered. **It is a calibration, not a finding.**
- **Wire it in.** `ADAPTIVE_STOPS=false`, so nothing live consumes `exp_move` today. **Sequence it
  after the `risk_voice` 0.8 haircut and the `basemap._closed` fix**, both of which move `em` and would
  move `K*` with it.
- **Treat the stability as validation.** +5.1% to +7.7% across four configurations is reassuring about
  the *arithmetic*, not evidence about the *world*. A proper answer needs its own prereg with an
  economic objective — exceedance parity is a statistical target, and what actually matters is
  expectancy after the wider stop's larger losses.

## 5. The transferable point

**A decision number and the test that justifies it must come from the same framework.** `FUNDING_STOP`
established its effect with matching and then set its recommendation marginally, and the gap between
those two choices is a factor of two in the advice. **Nobody did anything careless — the significance
test and the calibration were written in different places and never compared.** That is precisely the
class of defect the server's D-checks exist for, and it suggests one worth adding: **does a claim's
decision number come from the same estimator as its evidence?**
