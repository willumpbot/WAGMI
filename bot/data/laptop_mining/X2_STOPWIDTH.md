# Mission X2 — **UNDERPOWERED.** Widening the stop looks mildly better (+0.19R) but the test's floor is **0.81R** — 3.2× the effect it was built to find. And the bot will not accumulate enough trades to fix that.

_2026-10-12. `x2_stopwidth.py`, running `PREREG_MISSION_X2_STOPWIDTH_2026-10-12.md` (sealed
`aa344cc5`, sha `2d57c66d92c3d88b`). 295 matched live trades; 144 stop-exits are the only ones a
stop change can affect. Two deviations declared in §5._

---

## 1. The answer

**VERDICT: UNDERPOWERED.** Not AGAINST, and explicitly not "no effect".

| | |
|---|---|
| **A1 − A0, equal-weighted day mean** | **+0.1870 R** |
| CI95 (day-block bootstrap, 46 clusters) | **[−0.1182, +0.5470]** |
| z | **+1.12** — needs **2.39** (Bonferroni over 3 arms) |
| pooled per-trade mean | +0.1669 R — **same sign as the day mean** |
| **MDE, simulated, 80% power** | **0.810 R** |
| effect prior work suggested | **+0.25 R** |

**The prereg pre-committed to this outcome: "If the MDE exceeds 0.25R, this test cannot see the
effect prior work suggests, and the verdict is UNDERPOWERED regardless of what the point estimate
does."** The floor came out **3.2× too large**. The verdict was therefore fixed before the point
estimate was read, which is the only reason a +0.19R result is not being reported as encouraging.

**All three wider arms beat the baseline directionally** — day-mean R: A0 **−0.121**, A1 **+0.066**,
A1.5 **+0.164**, A2 **+0.129** — and the magnitude is close to the 360-signal prior (+0.25R).
**That is consistent, not confirmed, and the difference matters.**

## 2. 🟢 The harness passed its own checks

| probe | result |
|---|---|
| **placebo** — permute arm labels within day-cells | rejection **1.0%** at the 2.39 constant — **size OK**, slightly conservative |
| **look-ahead probe** — grant the stop one bar of foresight | **+0.3413 R, z 1.90** vs +0.187/1.12 — **harness responds to foresight, as it must** |
| **arm-invariance guard** | see §5 — it **failed twice and both failures were my prereg's errors, not the code's** |

## 3. 🔴 And a separate, independent blocker: 1h bars cannot referee a 1.66% stop

**The baseline arm contradicts reality on 22% of the decisive trades.**

| of the 144 real stop-exits, the 1h replay says | n |
|---|---|
| **stop** — agrees | 113 |
| **tp2** — says the trade hit its profit target | **23** |
| **cap96h** — says it never resolved | 8 |

**23 trades that really stopped out come back as winners at 1h resolution.** Mission X reported stop
and target landing in the same 1h bar **0 times in 2,628** — but that was a grid of 5.2–20.7% stops.
**At the bot's actual 1.66%, stop and target are close enough together that one hour cannot order
them, so Mission X's reassurance does not transfer.**

**5m bars would settle it and cannot be obtained:** they exist for all 6 symbols but only from
**2026-09-22**, covering **17 of 295** trades, because Hyperliquid's 5m history expires at ~17 days.
**This is not fixable retrospectively.**

**A correction to my own reasoning here.** I expected the contradicting trades to be the ones with
stop and target close together, which would have made the agreeing subset biased toward null. **They
are not:** stop-to-target distance is median **7.34%** where the replay agrees and **7.70%** where it
contradicts. So the 22% is not explained by that, and I do not know which way it biases the arms —
which is itself a reason not to lean on the point estimate.

## 4. 🔴 Why more waiting will not fix this

MDE scales as 1/√(day clusters). Going from **0.810R to 0.25R needs 10.5× more clusters** — about
**483 close-day clusters** against the **46** that 4.5 months of live trading produced.

**At the bot's current rate that is roughly four years.** **So the real-trade version of this
question is not answerable by patience.**

**The implication for the brief:** the server framed this as "the signals evidence, tested on real
trades." **The real-trade test is underpowered by construction** — 144 stop-exits is simply too few.
**The 360-signal test is the one with power**, and the right move is to re-run *that* properly rather
than treat this as its replacement. It needs no new data.

## 5. ⚠️ Declared deviations from the sealed prereg — two, both substantive

**Deviation 1 — non-stop exits are held fixed.** Prereg §4 said a counterfactual ends at "its arm's
stop, tp2, or 96h." Run literally, that contradicts §2's claim that only stop-exited trades can
change: **the guard caught 102 of 151 untouched trades differing, every one with A0 ≈ −1.0R**,
because a trade the exit agent closed after 3 hours was walked on for 96 and hit a stop it never
reached. **A0 was therefore not the bot — it was the bot with its exit agent deleted.** Fixed by
capping each held trade's replay at its real exit time in every arm. This also **narrows §3's
confound** to the extended life of the 144 stop-exits rather than all 295.

**Deviation 2 — the "wider" arms are not always wider, and §2's guard was wrong a second time.**
**A1 is *tighter* than the bot's own stop on 64 of 295 trades (22%)**; A1.5 on 12; A2 on none. The
bot's stop spans p10 0.91% → p90 3.84% while exp_move spans 1.73% → 3.58%, so the distributions
overlap heavily. **So "widen to ≥1× exp_move" is really "replace the stop rule", which tightens
nearly a quarter of trades.** The remaining 14 guard violations were this, plus trades where A0's own
stop was breached before a recorded non-stop exit (§6).

**Not run:** walk-forward halves. They were a SUPPORT requirement, and SUPPORT already fails on both
z and the MDE pre-commitment, so they could not change the verdict. **Stated rather than quietly
skipped.**

## 6. ⚠️ A data question for the server, found on the way

**12 trades have a recorded non-stop exit (`LLM_EXIT_AGENT` / `LLM_EXIT_HIGH`) although the 1h bars
show their logged stop was breached first.** **10 of the 14 total anomalies pre-date the 2026-07-24
close-handler migration** the server already flagged for the `gross_pnl` defects. Candidate causes:
1h lows from a different feed than the bot's execution, a stop evaluated on close rather than
intrabar, or the stop being moved. **Not a blocker here — it is inside the 22% of §3 — but it is a
live-bookkeeping question, not a research artefact.**

## 7. What I would tell the owner — three rules, one number each

1. **Do not change the stop on this evidence.** The test could only have detected an effect
   **3.2×** bigger than the one being looked for.
2. **Widening does look mildly better, and that is all it does.** **+0.19R** per trade, with a range
   that includes zero (z **1.12**, needs **2.39**).
3. **The bot does not trade enough to settle this itself.** 144 stop-outs over **46** days; it would
   need about **483** — roughly four years.

## Limits
- **6 symbols** (SOL/ETH/BTC/HYPE/XRP/NEAR) and BTC/ETH/SOL co-move, so 46 day-clusters overstates
  independence.
- **No LLM intervention is modelled** on the extended life of stop-exited trades (prereg §3). Its
  direction is unknown and I have not characterised it as conservative.
- **Targets held at the bot's actual tp1/tp2**; no joint stop-and-target search, which on 144 trades
  would be fitting.
- **The dollar outcome is not reported.** `position_size` units in `TRADE_OPENED` are ambiguous
  (1.0 and 1.7 against prices from 32 to 50,000), and R needs no size. Reporting a dollar figure off
  a quantity I could not verify would have been the kind of unchecked input that caused the
  `ENTRY_TIMING` retraction.
