# PREREG — Mission E2: does the exit engine's stop-tightening help or hurt? **Sealed before any outcome was replayed.**

_Answering the owner's own observation: **"our thesis was pretty right, but we seemed to get stopped
out before it could truly show?"** His BTC short (plan `11624f4364`) had its stop moved
85,600 → 83,776.1 (breakeven) after ~6h and scratched at +$1.92; price never came within 1,300 of
85,600 afterwards and is now ~82,508, so his own stop would still be alive at ~+0.7R toward target._

---

## 0. 🔴 The owner-plan A/B is n=2 and is NOT the test

The server pointed at `plans.json`'s `bot_result` (owner's levels) vs `exec_result` (what the bot
did) as a paired A/B. **There are 5 plans and 2 with both columns populated.** That is two
anecdotes. **The owner's specific question cannot be answered on owner plans, and I am not going to
dress up n=2.**

**The general question is answerable on the bot's own tightening**, which is the same mechanism on a
usable sample.

## 1. What I have looked at — predictor side only, no outcomes

| | |
|---|---|
| `exit_decisions.jsonl` | 1,336 rows: close 831, partial 198, hold 189, **tighten_sl 118** |
| **applied tighten_sl** | **86**, all with a parseable before→after |
| genuinely tightened | **80** (6 loosened, 0 unchanged) |
| **median stop distance before → after** | **1.53% → 0.87% of entry** |
| moved >0.1% of entry closer | **72** |
| extreme cases | HYPE 6.06% → **0.02%**; several ~5% → ~0.2% |
| **distinct days** | **34** · symbols BTC 26, ETH 20, SOL 15, HYPE 11, XRP 10, NEAR 4 |

**An instrument note that cost me a wrong conclusion ten minutes ago:** these rows are logged
**after** application, so `position_sl` and `new_sl` both hold the **new** value. The true
before→after lives only in the `details` string (`"SL 1985.65 -> 1985.29"`). Comparing the two
numeric fields says "83 of 86 were no-ops", which is false. **Parse `details`.**

## 2. The test — paired, which is what makes 34 clusters usable

For each applied tighten, replay forward **from the tighten timestamp** under two stops, everything
else identical:

| arm | stop |
|---|---|
| **KEEP** | the stop as it was *before* the tighten |
| **TIGHTEN** | the stop the engine actually set |

Each arm ends at **its own stop, the position's `position_tp2`, or 96h**, whichever comes first.
Bars: `candles_5m` where available, else `candles_1h` — **all 6 symbols are present in both.**

| | |
|---|---|
| **outcome** | P&L from the tighten moment, in **R of the ORIGINAL risk** `\|entry − old_sl\|`, so it is size-free |
| **primary contrast** | **TIGHTEN − KEEP**, equal-weighted over the **34 tighten-days**, printed beside the pooled per-event mean |
| **CI** | day-block bootstrap, 4,000 reps |
| **bar** | two-sided 0.05, **\|z\| > 1.96** — one contrast, one outcome, so no Bonferroni inflation |

## 3. 🔴 The placebo that decides whether any result means anything

**Tightening a stop changes the outcome distribution on a random walk, deterministically.** A closer
stop fires more often; that is arithmetic, not skill. **So the GBM no-edge control is the primary
validity check here, not an afterthought** — this is the exact omission that put a wrong gloss on
X2's +0.19R.

1. **Driftless-GBM control.** Replace each path with a driftless GBM at that symbol's realised
   hourly vol, keep both stops identical, 300 worlds. **If the measured TIGHTEN − KEEP sits inside
   the no-edge spread, there is no finding** regardless of its sign or z.
2. **Day-label shuffle**, 2,000 draws — size must be ≈5%.

## 4. Decision rule

**SUPPORT for "owner plans keep the owner's stop; the exit engine may only alert"** requires ALL of:

1. TIGHTEN − KEEP **< 0** (tightening hurts), CI excluding zero at **|z| > 1.96**;
2. pooled and equal-weighted **agree in sign**;
3. **sign-stable** across halves split at the median tighten-day;
4. effect **exceeds the MDE** of §5;
5. **falls outside the GBM no-edge spread.**

**AGAINST**: tightening significantly *helps*. **UNDERPOWERED**: anything else.

## 5. Power

MDE by simulation on the paired per-day differences. **Pre-commitment: the prior evidence puts
"don't tighten" at −0.13 to −0.20R. If the MDE exceeds 0.20R, the verdict is UNDERPOWERED regardless
of the point estimate.**

**A paired design on 34 clusters may actually clear this** — the same position under two stops
removes most of the between-position variance — which is why this is worth running where the
owner-plan version is not.

## 6. The confound, declared

**Neither arm models further LLM intervention.** In the KEEP arm the engine would have gone on
watching and might have closed the position some other way. **So KEEP is "the position left alone
with its original stop", not "what the bot would have done"** — the same assumption X2 declared, and
the direction of its bias is unknown.

## 7. Recorded expectation

**I expect TIGHTEN − KEEP to be negative, and I expect it to clear the bar.** The prior evidence is
consistent (breakeven ratchet refuted in July; "don't tighten" at −0.13 to −0.20R), the mechanism is
blunt (median stop distance nearly halved, some to 0.02% of entry), and the paired design is
efficient. **If it comes back null I will report that rather than hunt for a subset that works.**

## 8. Out of scope

- **No change to the exit engine without the owner's yes**, even on SUPPORT.
- **No claim about the LLM's close/partial actions** — only `tighten_sl`.
- **Deviations** declared in the results document with their effect on the number.
