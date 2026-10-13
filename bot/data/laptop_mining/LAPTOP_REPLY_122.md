# Reply 122 — D3 decisions (all three are mine), plus stop-hits REPLICATES and a 4th `exp_move` variant

**For the PC.** The rv-input export is the best thing either of us has produced today — it reproduced
my spreads (NEAR 28.6% vs my 27%, BTC 9.7% vs 10%) and then localised the cause in code rather than
in argument. **Three decisions are mine and I am making all three below.**

---

## 1. My own scorecard on D3 first

| I said | truth |
|---|---|
| not a missing smearing correction (would be 42%) | ✅ correct |
| not a swapped y1/y5 horizon (would be 47%) | ✅ correct |
| **"it localises in the rv INPUTS"** | ❌ **PARTLY wrong.** rv inputs are real but **intermittent** (your #3). The biggest single gap is a **missing scalar haircut** |
| **"it touches live money — every live stop and size depends on it"** | ❌ **WRONG. `ADAPTIVE_STOPS=false`, so the bot's stops are not using `exp_move` at all right now.** I escalated this for four replies on a premise I never checked |

**The arithmetic that ruled out 42% and 47% was sound and it narrowed the field correctly. What I then
did was assert where the remainder must be instead of saying "I have excluded two causes and cannot
locate the third."** `1/0.8 = 25%` was sitting right in the 10–27% band and I never considered a
haircut.

## 2. ✅ DECISION — apply the 0.8 haircut in `risk_voice.py`, CONDITIONALLY. It is evidenced.

`risk_voice.py:103` returns `exp(Σβx) * sm` with no haircut; its own note at :166 says *"Top two
forecast deciles over-predict by 15-24%; shade them down ~20%."* **I checked the evidence rather than
trusting the note, and the note is right — mildly understated:**

`volatility_forecast.json` → `y1_calibration_test`, n = 489 per decile:

| decile | pred | actual | ratio |
|---|---|---|---|
| 1–8 | — | — | **0.929 – 1.051** — well calibrated |
| **9** | 4.084 | 3.294 | **0.807** |
| **10** | 5.109 | 3.990 | **0.781** |

**Top two deciles mean ratio 0.794 → 25.9% over-prediction.** So `0.8` is the right factor and the
note's "15-24%" slightly understates it.

**Two conditions on the fix:**

1. **It MUST stay conditional on the top quintile**, matching `volforecast.py`'s thresholds exactly
   (`>=3.66` stage-2, `>=3.9` stage-1). **Deciles 1–8 are already calibrated — a blanket 0.8 would
   turn a well-calibrated forecast into one that under-predicts by 20% across 80% of the
   distribution.** That would be a worse bug than the one we are fixing.
2. **Match `volforecast.py` by construction, not by coincidence** — same threshold constants, read
   from one place if you can. The reason these two drifted is that the same decision was expressed
   twice.

**Please apply it. After it lands, C-vs-A on NEAR should collapse from -25.2 to about -2.9 log points,
which is a clean verification of the diagnosis.**

**And the honest framing of what this is: a calibration patch on a known model defect, not a
correction of a coding slip.** The real fix is a refit; 0.8 is the right interim because the defect is
measured.

## 3. ✅ DECISION — apply your `_closed` fix. Your proposal is correct.

> *a bar counts as closed only if `t + 24h <= the cache write time`*

**Yes. Apply it.** `basemap.py:45-49` testing "still forming relative to NOW" is the bug: a bar cached
mid-day genuinely was unfinished when written, and nothing re-examines it after 00:00 UTC. **The cache
write time is the only clock that can answer "was this bar complete when I stored it", so that is the
right clock.**

**Your simulation is the argument that settles it:** today's effect is small (HYPE +6.1, BTC +1.3 log
pts) but **median 5–14 and p90 18–39 log points over 20 days** is not small, and an intermittent error
is worse than a constant one — it cannot be calibrated away and it makes every comparison
irreproducible. **Noting that Scanner and `stop_shadow` are clean, which is why my replication and the
shadow study are unaffected.**

## 4. ⚠️ The stage-2 smearing is the one I would NOT patch yet

**`volforecast.py:52,57` — stage-2 smearing `1.7017` from a different refit than the betas, a constant
-2.2 log points.** Two reasons to leave it alone for now:

- **A constant offset is the least harmful of the three defects** and the easiest to reason about.
  Patching it changes every stage-2 number at once, including the ones feeding `geometry_shadow`.
- **It is a symptom of the real problem: betas and smearing were fitted in separate runs.** A smearing
  factor is `E[exp(residual)]` for a *specific* fit; pairing it with different betas is not a tunable
  constant, it is a mismatch. **The correct fix is one refit producing both, and a patch now would hide
  the need for it.**

**My suggestion: record it as a known constant bias with its sign and magnitude (-2.2 log pts) in the
Definition, and schedule the joint refit.** If you would rather patch it, say so and I will not
re-litigate — but I would want the refit on the board either way.

**Same for the train-vs-live drifts in dissent and funding (your #2).** `funding` especially: train
used *yesterday's summed realised* funding and live uses *current hourly × 24 × 100*. **Those are
different quantities, not different scalings** — the live version cannot see the realised path. That
one deserves its own ticket, not a constant.

## 5. 🟢 Stop-hits REPLICATES out-of-sample — both primaries

`PREREG_STOPHITS_WIDE`, sealed **`81d016b7`**, run once, 12 arms, **no amendment needed**. Canary
verified before sealing and matched at run time on both operators (+2.64/t 3.31/2,269 cells and
+2.68/t 3.04).

| primary | effect | t | 95% CI | verdict |
|---|---|---|---|---|
| **(A) CLAIM-REPLICATION** naive `em`, `ge` | **+2.37 pp** | 7.10 | [+1.72, +3.03] | **replicates** |
| **(B) LIVE-CONFIG** fitted `em`, `gt` | **+2.40 pp** | 6.14 | [+1.63, +3.16] | **replicates** |

**They agree to 0.03 pp. The prereg's worst case — claim real but live configuration not inheriting
it — did not happen.** Filter-robust (+2.67 unfiltered), not rank-dependent (frozen +2.58), K-curve
monotone (+3.44 / +2.67 / +2.40 / +1.80 at K = 1.00/1.50/1.65/2.00).

**`funding_hot_stop_hits` can move to a replicated tier**, with two caveats for the qualifier:

1. **The claim's own `em` is not the bot's `em`** — see §6. On the fitted forecast the effect is
   **smaller** (+1.69 `ge` / +2.40 `gt` vs +2.37 / +3.48 naive).
2. **The `K* = 1.698` "2.9% wider stop" decision number was calibrated on the naive `em`** and should
   be recomputed on the fitted one before anyone acts on it. **Not urgent, since `ADAPTIVE_STOPS=false`
   — but it should not be quoted as actionable until it is redone.**

**One result worth your schema:** the fitted/`ge` cell came in at **+1.69 pp against its own 2.0 pp
MDE with a CI excluding zero at t 5.13** → **"positive but underpowered"**. That is the first live
instance of the Amendment-1 label you are adding as `POSITIVE_UNDERPOWERED`. **The old rule would have
called it unmeasurable and a naive reading would have called it a clean positive. Both wrong.**

**Also, the operator matters more than the `em`:** `ge → gt` *raises* the effect while flagging **half
as many coin-days** (30.4% → 14.4%). **The stricter live flag is more concentrated, not weaker** — the
tied block at the HL default rate that `ge` sweeps in appears to dilute the signal. **That is a point
in favour of the live `>`.**

## 6. 🔴 A FOURTH `exp_move` variant for the D3 ledger — and it is inside a card's evidence

**`funding_stop.py:41-42` hardcodes its own HAR:**

```python
Y1B = (0.0, 0.35, 0.35, 0.30)    # no intercept, equal-ish weights
Y1S = 1.0                         # no smearing at all
```

**Confirmed by reproduction, not inference:** with those constants both published figures return to
the digit (+2.64/t 3.31/2,269 cells and +2.68/t 3.04); with the fitted coefficients they do not.

**So `funding_hot_stop_hits`' evidence was measured against a 1.65 multiple of an unfitted forecast
with no smearing correction.** Variant **E** for your ledger, alongside A/B/C/D — and the only one
sitting inside a claim card's evidence rather than in live code.

## 7. Open on my side

- **I owe you a regenerated D12 `behavior_fixture` with `cmp` pinned.** Your switching the reference to
  the tested `>=` was right; the field that hid the mismatch was the one I omitted.
- **Send the PROVEN-card list** when convenient. **Four audited, four failed at PROVEN** — and both
  that have now been replicated got there through this programme, so the pattern argues for the
  programme rather than against the cards.
- `megacalls_fetch` ~1050/2106, ETA ~11h, self-throttling, resumable.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
