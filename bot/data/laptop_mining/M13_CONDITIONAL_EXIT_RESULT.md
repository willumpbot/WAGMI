# M13 — conditional exit policy: **NO at-entry rule earned its place (p = 0.53), and no single arm beats the live runner default. The style_hint for every plan is: the default.**

_2026-10-15. `m13_build.py` + `m13_fit.py`, design + 2 amendments in `M13_CONDITIONAL_EXIT_DESIGN.md`
(red-teamed by a 3-judge panel BEFORE the first run; 6 FATALs fixed first). EXPLORATORY, HYPOTHESIS cap.
174 coins, 19,566 random both-sided entries (24-bar spacing), 7 arms, stop 1.65 × em (lagged one closed
day), per-entry K=16 martingale control, fees on actual leg notionals, funding carry accrued per leg
hold (median |carry| 4.9 bps per runner hold). Source snapshot in `m13_build_meta.json`. R units govern._

## 0. The pipeline proved it CAN say nothing before it said anything

Null gate (identical pipeline on an independent martingale draw, true gain 0 by construction):
increment **−0.0011 R, CI [−0.0041, +0.0017]**, placebo p = 0.51 → PASSED. Nothing below is machinery
artifact.

## 1. Headline, decomposed as pre-registered

| statistic | R (coin-boot 95%) | bps |
|---|---|---|
| (i) best single arm vs `runner_1.00atr`, chosen in-fold | **+0.0014 [−0.0015, +0.0044]** | ~+0.8 |
| (ii) tree increment over (i) — the conditional claim | +0.0132 [+0.0071, +0.0194] | +7.13 [+3.47, +10.88] |
| total policy vs baseline | +0.0146 [+0.0093, +0.0199]; two-way (coin×week) [+0.0019, +0.0265] | — |

**(i) is the quiet headline: no arm beats the live default.** full@1R, full@2R, 0.75/1.5 ATR trails,
the 72h clock, trail-without-partial — none of the seven is unconditionally better than the engine's
`runner_1.00atr` (CI covers 0). **The owner's style, as the server implemented it, survived a
seven-arm challenge.**

**(ii) looks positive — and the placebo killed it.** Day-shift placebo (feature tables rotated by a
common random offset, entries/outcomes/controls fixed, full pipeline re-run per rep, B = 200):
**null mean +9.31 bps (sd 7.05), observed +7.13, p = 0.527.** The null preserves each coin's
time-invariant feature profile, so shifted features "know" WHICH COIN they are but not what is happening
at entry — and they earn the increment just as well. **What the tree discovers is coin identity, not
at-entry conditions.** Confirmation from the time axis: fit-early→eval-late is **negative**
(−0.0061 R [−0.0121, +0.0002]); late→early +0.0081. Structure that does not transfer forward is not a
rule.

## 2. MDE, stated before the verdict

From the null reps: SE ≈ 7.05 bps → **MDE (2.8σ) ≈ 19.8 bps on the increment — about two full fees.**
A real conditional timing effect smaller than that was invisible to this design. So the verdict is:
**NULL at the tested scale, UNDERPOWERED below ~20 bps** — not "proven absent".

## 3. The owner's pre-stated "obvious relations", scored

- *"runner wins on aligned trend + room + high vol"* — the tree never chose trend, room, atr_em, or
  funding as a split. Its single surviving split was `ret7 ≤ 5.2%` (into-weakness → runner-72h,
  into-strength → full@1R), and both leaves carry the **same** out-of-fold gain (+0.0144 R), i.e. the
  gain is not FROM the rule. Suppressed.
- *"full wins when +1R ≈ the next level"* — `room` was never selected; at this MDE, not detectable.
- The CASHCAT-vs-BTC-shorts split that motivated M13 remains explained at n=3 by outcome, not by any
  at-entry feature this design could see.

## 4. What ships

`m13_style_hint.json` carries **VERDICT: NO RULE SHIPS** and every rule `ships: false` with its
suppression reason. **The case-file `style_hint` for every plan is the default (`runner_1.00atr`),**
which §1(i) independently supports. If the server wants a conditional exit in the planner one day, the
path is a prereg with a ≥20 bps-sensitive design (more entries, longer panel, or real-trade populations
once n allows) — not this table.

## 5. Limits
- Random both-sided entries: exit geometry only; real entries are selected and may carry conditional
  structure this design cannot see (M28's map is the follow-up built for that).
- Fills at the trigger level (optimistic, flatters frequent-exit arms); control shares the convention.
- `oi_chg` coverage 2.2% — effectively untested. `fund_pctl` expanding-window.
- Day-lookup features for the placebo-comparable statistic; entry-level features reported beside
  (+5.35 bps increment [+1.81, +8.89] — same conclusion).
- The coin-level structure the tree does find (+9–15 bps) failed the forward time split; it is NOT
  carded even as coin-routing advice.
