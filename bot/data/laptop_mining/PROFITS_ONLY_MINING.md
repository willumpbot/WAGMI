# Profits-only across all 295 trades — **nothing real.** Pooled says +0.13%, day-weighted says −0.27%, and both sit inside the no-edge spread. **Sixth appearance of the same weighting flip.**

_2026-10-13. `profits_only.py`. Descriptive mining job, **not preregistered**, per the owner:
"there's not really a point in changing the others, but looking under them under data mining could be
useful just like everything else we are data mining."_

---

## 1. The three policies, all 295 matched trades

| policy | pooled | **equal-weighted day** | mean R |
|---|---|---|---|
| **(a) actual** | −0.253% | **−0.277%** | −0.097 |
| **(b) profits_only** | −0.123% | **−0.546%** | −0.059 |
| **(c) hands_off** | −0.155% | **−0.660%** | −0.071 |

**Differences versus actual:**

| | pooled | **equal-weighted day** | |
|---|---|---|---|
| profits_only − actual | **+0.130%** | **−0.269%** | 🔴 **signs disagree** |
| hands_off − actual | +0.098% | **−0.383%** | 🔴 **signs disagree** |

## 2. 🔴 Why neither number is a finding — two independent reasons

**(a) Both sit inside the no-edge spread.** The GBM control was run and read *first*, as asked:

| wide-minus-tight, no edge | median | 95% spread |
|---|---|---|
| % of notional | −0.032% | **[−0.339%, +0.300%]** |
| R | +0.088% | [−0.153, +0.300] |

**Measured +0.130% and −0.269% are both inside [−0.339, +0.300].** Nothing to report either way.

**Worth noting the control's own lesson: the two units disagree on the direction of the bias** —
negative in % of notional, positive in R. That is a third independent argument for % of notional as
the canonical unit (reply 114), because a unit whose *bias* flips sign cannot be used to judge a
stop-width treatment.

**(b) The weighting flip is an era artefact, and it is the sixth instance.**

| era | profits_only − actual | n |
|---|---|---|
| **Jun–Jul** | **+0.23%** | **274** |
| **Sep–Oct** | **−1.18%** | **21** |

**274 of 295 trades are Jun–Jul, packed into few days; the 21 Sep–Oct trades are spread thinly
across many.** So pooling follows Jun–Jul and day-weighting is effectively a Sep–Oct statistic.
**Neither is wrong; they are answering different questions**, and with a 13:1 era imbalance the
honest answer is that this sample cannot separate policy from era.

**This is the same shape as M2, `fattail2`'s death rate, the fetch re-queue, skipgate, and the gate
audit.** It is now the single most reliable failure mode in this project.

## 3. The cross-sections, for completeness — all noise at these n

| by | profits_only − actual |
|---|---|
| side | LONG **+0.30%** (n 119) · SHORT +0.01% (n 176) |
| coin | ETH **+1.28%** (61) · BTC +0.08% (61) · XRP +0.08% (45) · HYPE +0.07% (49) · SOL **−0.51%** (64) · NEAR **−1.25%** (15) |

**ETH +1.28% against NEAR −1.25% on 61 and 15 trades is coin-level noise**, not a per-coin policy
effect. Reporting it because it was asked for, and flagging that I would not act on any row of it.

## 4. 🟢 One methodological point in this design's favour, and one instrument result

**The geometry bias here runs AGAINST the policy being tested.** E2 compared a *tightened* stop
against the original and measured in R of the original risk — the tightened arm's loss is capped by
construction, so the bias favoured the thing under test, and +0.41R at z 4.69 turned out to be the
denominator. **Here the tightened arm is the status quo**, and `profits_only`/`hands_off` hold the
wider original stop and eat full-size losses. **The control confirms it: −0.032% median, i.e. a
no-edge world makes the wider stop look slightly worse.** So a win for profits_only would have been
a win against the bias. **It did not win.**

**1h/5m referee check: 16 agree, 1 disagree of 17.** Far better than the 22% contradiction X2 hit —
because these walks run entry-to-exit against a *wide* original stop, not a 1.66% stop where an hour
cannot order the touches. **5m still only reaches back to 2026-09-22**, so 278 of 295 trades are
refereed on 1h and that limit stands.

## 5. What I would tell the owner

1. **Looking under the other trades was worth doing and found nothing.** Profits-only across all 295
   is **+0.13% pooled, −0.27% day-weighted** — and a coin-flip market produces anything in
   **±0.3%**.
2. **His own trade remains the only clean instance.** +$26 under profits-only versus **+$1.92**
   actual is a real, documented case; 295 bot trades do not generalise it.
3. **The blocker is unchanged and is not analysis.** 274 of the 295 are from one era that ended in
   July. **More owner plans with both columns logged is still the only thing that settles this.**

## Limits
- **Not preregistered.** Descriptive mining, as instructed. No verdict is claimed and none should be
  quoted from it.
- 60 day-clusters, with a **13:1 era imbalance** that the day mean cannot neutralise.
- **Partial legs reconstructed for only 46 of 295 trades** from `exit_decisions.jsonl`; the rest of
  policy (b) is therefore identical to (c) for those trades.
- Hold cap fixed at **96h** for bot trades (no per-trade `max_hold_h` exists outside owner plans).
- No funding; fees at a flat 9 bps round trip.
