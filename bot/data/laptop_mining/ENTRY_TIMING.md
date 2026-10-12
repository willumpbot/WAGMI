# 🔴 RETRACTED, 2026-10-12. The "entry momentum" was measured at the CLOSE, not the entry — the feature contained the trade's own outcome.

**`trade_ledger.timestamp` is the CLOSE time, not the open.** I assumed it was the entry and
computed each trade's trailing 24-hour momentum ending there. For a trade held three hours, that
window therefore **contained the trade's own price action**: a position that went the bot's way
showed "positive entry momentum" *because of the move it had just captured.* The feature was partly
the outcome.

**Proof, from the server's own sidecar** (`entry_mom.jsonl` carries true fill times from
`position_journal` OPEN events, joined on `position_id`, n=50):

| interpretation of `timestamp` | median offset from the true fill | within 5 min |
|---|---|---|
| open | +1.49 h | **2%** |
| **close (so open = timestamp − hold)** | **+0.07 h** | **62%** |

**Recomputed at the true fill time:**

| momentum measured at | outcome | slope | CI95 | verdict |
|---|---|---|---|---|
| close (the error) | win 0/1 | +0.0438 | [+0.024, +0.066] | significant |
| **fill (correct)** | **win 0/1** | **+0.0098** | **[−0.012, +0.032]** | **NULL** |
| close (the error) | net PnL | +2.37 | [+1.10, +4.30] | significant |
| fill (correct) | net PnL | +1.43 | [+0.32, +3.14] | significant, 40% smaller |

**The headline is dead.** "75 counter-trend trades won 17% against 42%" rested on the **win-rate**
slope, which I chose precisely because win/loss is size-independent and therefore the load-bearing
statistic. **At the true fill time that slope is null.**

**The net-PnL slope survives but I am not reporting it as a finding.** It is size-dependent — the
exact confound §3 of the original was built to rule out — and the size-free version it was validated
against is now null. A surviving effect whose own robustness check has failed is not a finding.

**What this does NOT invalidate:** `PREREG_ENTRY_TIMING_2026-10-11` and the server's `entry_mom`
sidecar both use **true fill times** from `position_journal`, so the sealed forward test measures
the right quantity. **Its stated in-sample motivation is withdrawn, but the test itself stands** —
and it is now the only thing that can settle the question.

**How this got past me:** I verified the sidecar's arithmetic against my own panel (55 of 55 to
4 decimals) and took that as validating the study. It validated the *formula*, not the *timestamp I
fed it*. The two are different checks and I only did one.

---

_Original write-up follows, retained unedited so the error is legible rather than erased._

# My prediction was wrong, and the opposite showed up: the bot's **counter-trend entries win 17% against 42%.** 75 of 294 trades, −$11.35/trade equal-weighted. Strong candidate, **not** a SUPPORT verdict yet.

_2026-10-11. `entry_timing.py` plus confound checks. 294 closed trades, 2026-06-01 → 10-11
(131 days, 59 trading days), against the 169-coin 1h panel._

---

## 1. What I predicted, and that it failed

Two panels agree that the recent short-horizon winner gives a little back (`INTRADAY_DISP.md`, 16/16
negative; the 42-coin 1h panel, −3.0 bps at z −4.8 clearing Bonferroni). I predicted, **in writing
before running**, that the bot would pay that tax: entries taken *with* recent momentum should do
**worse**.

**They do better, and the CI excludes zero.** The pre-specified direction was wrong.

I am leading with that because the test was built to be able to embarrass the hypothesis that
motivated it, and it did. The reversal result **does not transfer** to the bot's holding periods —
median hold is **3.0 hours**, and in the crossover grid a 24h lookback at a 3–4h horizon is weakly
*positive*, not negative. The two results do not conflict; I read the grid wrong.

## 2. The association that turned up instead

Signed momentum at entry = trailing return × (+1 long, −1 short). Positive = trading **with** the
prevailing move.

| | against 24h momentum | with 24h momentum |
|---|---|---|
| trades | **75** | 219 |
| **win rate** | **17%** | **42%** |
| mean net PnL | **−$11.38** | +$3.00 |
| mean realized RR | **−0.378** | −0.035 |
| median hold | 3.0h | 3.0h |

**Hold time is identical, so this is not a duration artifact.**

## 3. 🟢 It survived every confound I could put to it

**Is it just position size?** `net_pnl` scales with size; **win/loss does not.**

| outcome | n | slope on 24h signed momentum | CI95 | z |
|---|---|---|---|---|
| net PnL | 294 | +2.37 | [+1.11, +4.36] | +2.85 |
| realized RR | 80 | +0.026 | [+0.002, +0.052] | +1.99 |
| **win (0/1)** | 294 | **+0.044** | **[+0.024, +0.067]** | **+3.99** |

**The win-rate slope is z = +3.99 and is size-independent by construction.** Bonferroni over the
three lookbacks tested is |z| > 2.39; it clears comfortably. *(Realized RR, at z 1.99 on n=80, does
not clear — it is supporting, not load-bearing.)*

**Did the bot already know?** `corr(confidence_score, signed momentum) = +0.10`, and the effect holds
in **both** halves — high confidence +0.92 (CI excludes 0), low confidence +4.58 (CI excludes 0).
**The bot's own confidence score does not capture this.**

**And the check my own standard demands — the equal-weighted block mean, not just clustered CIs:**

| | with − against, net PnL |
|---|---|
| pooled | +$14.38 |
| **equal-weighted over the 27 days having both** | **+$11.35** |
| block-mean CI95 | **[+$2.92, +$23.02]** — excludes zero |

**The number being acted on survives the clustering standard, not only its confidence interval.**
That is the specific check that overturned six conclusions on 2026-10-08, and this one passes it.

## 4. ⚠️ Why this is still not a SUPPORT verdict

**It is observational, and the bot chose these trades.** I did not randomise entries; I measured
the ones it took. Three live concerns:

1. **The alternative to a counter-trend entry is not "the same trade, better timed."** It may be no
   trade at all, in conditions I cannot reconstruct. So I **cannot** claim a filter would have
   recovered 75 × $11.35.
2. **The exit mix differs, and that is the likely mechanism:** counter-trend entries hit **SL 57%**
   of the time versus **37%**. Entering against the prevailing move puts the stop in the path of
   that move. **This may be a stop-placement finding as much as an entry finding** — and those imply
   different fixes.
3. **75 trades in one regime.** 27 days carry the comparison. One quarter is not a cycle.

## 5. What I am asking for, and what I am not

**Not asking for a bot change.** No trading change without a SUPPORT verdict and the owner's yes,
and this is one in-sample observational test.

**What it justifies now:** `PREREG_ENTRY_TIMING_2026-10-11.md` is **sealed** so the forward test is
clean — the server logs signed 24h momentum at every entry from here, and the prospective win-rate
gap gets tested once, at a pre-stated n, against a pre-stated bar. Nothing is adjusted in the
meantime.

**And one thing worth the server's attention regardless of the verdict:** the counter-trend bucket
is only **25% of entries but carries a −0.378 mean RR**. Whether the right fix is a filter or a
wider stop is exactly what the forward test should separate, which is why the prereg specifies both.

## Limits
- **Observational, in-sample, bot-selected.** §4 is the whole caveat and it is not small.
- **131 days, one market regime.** The window is June–October 2026.
- **`realized_rr` is populated on only 80 of 294 rows**, so the size-free continuous outcome is
  thinner than the binary one. The win-rate result is the one that carries weight.
- **Entry momentum is computed from 1h closes**, not the fill price path, so a fill inside the hour
  is approximated by that hour's close.
- **3 lookbacks × 3 outcomes were examined.** The headline (24h, win rate) clears Bonferroni over
  the lookbacks; I have not corrected across outcomes, and say so rather than claiming otherwise.
