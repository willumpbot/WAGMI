# PREREG — Mission X2: is the bot's own 1.66% stop too tight? Sealed 2026-10-12, before any arm was run.

_Answering `SERVER_REPLY.md` Mission X2. Written and committed BEFORE computing any outcome. The
only numbers below are **counts, inputs and power** — no arm result has been looked at._

---

## 0. The question and the deliverable

**"Should the bot widen its stop to ≥ 1× expected move?"** Deliverable is one of
**SUPPORT / AGAINST / UNDERPOWERED**. A SUPPORT goes to the owner as a decision; **nothing changes in
the bot without his yes.**

## 1. Inputs, and the one that is already validated

| input | source | status |
|---|---|---|
| 295 live trades, entry price, side, size, actual tp1/tp2 | `trade_ledger.csv` + the 294 matched `TRADE_OPENED` events | **matched 294/294 at 15s median offset** (`STOP_WIDTH.md`) |
| true fill time | `timestamp − hold_hours` | **validated three ways**; 62% within 5 min of `entry_mom` fills, 15s median vs `TRADE_OPENED` |
| the bot's actual stop | `TRADE_OPENED.sl` | median **1.66%** of price, p10 0.91%, p90 3.84% |
| **`exp_move` as of entry** | **`bot/tools/hivemind/volforecast.py` `forecast()["next_day_move_pct"]`** | **reproduced the server's 119 logged rows EXACTLY — 119/119, max abs diff 0.000, on both `exp_move` and `rv5`** |
| price paths | `candles_1h` (878,214 rows) and `candles_5m` (314,567) | **all 6 traded symbols present in both** |
| funding | `funding_hist` | realized, per holding period |

**On that validation, precisely what it does and does not establish.** I am calling the production
function, so formula agreement is trivial and is NOT the claim. What the 119/119 match establishes is
that **my input pipeline — 1h bars → daily closes → "strictly before the forecast day" → forecast —
reproduces what the server actually fed it.** That is the exact link that was wrong in
`ENTRY_TIMING.md`, where I validated a formula and not the timestamp I passed to it.

## 2. 🔴 The design fact that decides this test's power, pre-stated

**Widening a stop can only change a trade whose stop was hit.** Exit mix of the 295:

| exit | n | can a wider stop change it? |
|---|---|---|
| **SL** | **124** | **yes** |
| **TRAILING_STOP** | **20** | **yes** (initial stop feeds the trail) |
| LLM_EXIT_AGENT / _HIGH / _CRITICAL | **139** | **no — the stop was never touched** |
| TIME_STOP | 7 | no |
| TP2 | 5 | no |

**So the discriminating sample is 144 trades, not 295.** The other 151 are identical in every arm by
construction. **They still enter the portfolio-level $ figures, where they dilute any measured
effect toward zero** — so the $ result and the per-affected-trade result answer different questions
and both get reported, labelled.

## 3. 🔴 The confound I cannot remove, stated now rather than discovered later

**The LLM exit agent closed 47% of all trades.** Under a wider stop, a trade that originally stopped
out instead survives — and the agent would then have been watching it. **I cannot replay its
decisions.**

**So every wider-stop arm assumes NO LLM intervention during the extended life of a trade that would
originally have stopped out.** The direction of that bias is **unknown**: the agent might have cut
the loss sooner (making the wider stop look better than it was) or held to target (worse). **I will
not adjust for it and I will not characterise it as conservative.** It is a stated assumption that
caps what a SUPPORT can mean: *support for widening, conditional on the exit agent behaving no
better than nothing on the extended tail.*

## 4. Arms

Held fixed in all arms: entry time, entry price, side, size, **the bot's actual tp1 and tp2**, fees
**9 bps round-trip**, realized funding over the actual holding period.

| arm | stop |
|---|---|
| **A0** | the bot's actual `sl` (the baseline) |
| **A1** | **1.0 × exp_move** at entry |
| **A1.5** | 1.5 × exp_move |
| **A2** | 2.0 × exp_move |

A counterfactual trade ends at whichever comes first: **its arm's stop, tp2, or 96h from entry.**
96h is Mission X's cap, kept for comparability; **24h and 48h caps are reported as sensitivity, not
as the headline.** Intrabar order uses **5m bars where they exist** (all 6 symbols) and 1h
otherwise; Mission X measured stop-and-target in the same 1h bar **0 times in 2,628**, so this
convention is expected to be worth nothing and is specified only so it is not chosen later.

## 5. Outcomes and the governing statistic

1. **Primary — R of the ORIGINAL risk.** Arm P&L divided by `|entry − A0 stop| × size`, so every arm
   is in units of the risk the bot actually took. Size-independent.
2. **Secondary — $ at the bot's actual size.**
3. **Mechanism — of the 124 SL exits, how many under each wider arm reach tp1 / tp2 / the wider stop / the 96h cap.**

**Governing figure: the equal-weighted mean over the 60 close-day clusters**, reported beside the
pooled mean. **If they disagree, the day mean governs** — pooling by trade while clustering only the
CIs is the specific error that turned a +0.09% M2 result into −3.93%, and the clustering standard
applies to the number being acted on.

**6 symbols only** (SOL 64, ETH 61, BTC 61, HYPE 49, XRP 45, NEAR 15) and BTC/ETH/SOL co-move, so
**day is the cluster, not trade and not symbol.** 60 day-clusters is the real n for inference.

## 6. Decision rule, fixed now

**SUPPORT** requires ALL of:
- day-clustered mean of **A1 − A0 in R > 0** with its 95% CI excluding zero at **|z| > 2.39**
  (Bonferroni over the 3 wider arms, two-sided 0.05/3);
- the **equal-weighted day mean agrees in sign** with the pooled mean;
- **sign-stable across walk-forward halves** (split at the median close-day), both halves positive;
- the effect **exceeds the MDE** from §7.

**AGAINST**: A1 − A0 significantly **negative** under the same bar.
**UNDERPOWERED**: everything else — explicitly including "positive but below the MDE", which is
**not** evidence of no effect.

## 7. Power, by simulation — to be filled BEFORE arms are compared

MDE is computed by **simulating** day-clustered resamples of the 144 affected trades at the observed
R dispersion and finding the smallest true effect detected at 80% with the §6 constant — **not** by
restating a CI half-width. The prior evidence the server cites (360 signals, **+0.25R** for wider
stops) is the effect size to compare the floor against.

**If the MDE exceeds 0.25R, this test cannot see the effect prior work suggests, and the verdict is
UNDERPOWERED regardless of what the point estimate does.** I am writing that before seeing it so it
cannot be renegotiated afterwards.

## 8. Placebo, built to be able to fail

1. **Null placebo:** permute arm labels **within day-cells** and re-run, 2,000 draws. Measured
   rejection must land near the nominal rate. **If size is not ≈5%, the result is "unmeasurable",
   not "nothing"** — the server's standing rule.
2. **Positive control:** inject a known **+0.25R** improvement into the wider arm and confirm it is
   detected. A placebo that cannot detect a real effect is not a placebo.
3. **Look-ahead probe:** grant the wider arm one bar of foresight; it **must** turn significantly
   positive. If it does not, the harness is not measuring what it claims.

## 9. Pre-declared deviations policy

Any departure from §§4–8 is written into the results document **as a deviation, with its effect on
the number** — not silently folded in. On 2026-10-11 I wrote "nothing below deviates" and then found
two undeclared M2 deviations, so this clause exists because I have broken it.

## 10. What is NOT in scope

- **No change to the bot.** Not even on SUPPORT, without the owner's yes.
- **No re-optimisation of tp1/tp2.** Targets are held at the bot's actual values; a joint
  stop-and-target search over 144 trades would be fitting.
- **No claim about the exit agent's value.** §3 is an assumption, not a finding about the agent.
