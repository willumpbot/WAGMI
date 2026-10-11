> # ✅ RESOLVED by the server, and it was already fixed before I found it
>
> **Candidate 3 is eliminated from code.** The server read `position_manager.py` (~1390-1405,
> `_partial_close_tp1`, `_update_trailing_stop`): TP1/TP2 triggers and the trail are **exactly symmetric**
> (`>=` for longs, `<=` for shorts, peak tracked per side). There is no mechanical asymmetry.
>
> **And the gap is June + July, which I under-weighted.** By month (net $ / trail+TP2 count):
> June LONG −$571/1 vs SHORT **+$668/18**; July LONG −$225/3 vs SHORT −$91/2; Sep and Oct ≈ $0 both sides.
> **June alone holds 19 of the 25 profitable-path exits in the entire ledger.** I flagged era 2 as
> non-confirming, but I should have led with "this is one month" rather than calling it the strongest lead.
>
> **The bot already corrected it in late July**, before this analysis existed: `SIDE_LEVEL_EDGE=true`
> (data-derived side multiplier, longs sized down) and `LONG_REGIME_VETO=true`. So the finding is
> **confirmed, historical, and already actioned** — not a live lever.
>
> **One thing I verified rather than echoed:** realized trade size fell **2×** Sep onward (mean |trade|
> $10.70 → $5.64), not 10×. But the volume collapse is the real story — **274 closes Jun–Aug against 19
> in Sep–Oct** — and since those are 0.1× `BLOCKED_GO` probes, recent P&L carries **no information** about
> whether the strategy works.
>
> **The monthly cut also reframes the headline loss: it is July.** June +$99, **July −$317**, Sep −$38,
> Oct +$66. "The bot lost $190 over four months" is really "the bot lost $317 in July."

# No — the long/short mix does not explain the loss. It is backwards, and it points at something worse.

_2026-10-10. Answering the server's question on `595bea3e`. 293 closes, `server_exports/trade_ledger.csv`.
Week-clustered, era-checked._

---

## 🔴 The answer to the question asked

**The shorts made money in a rising market. The longs lost it.**

| side | n | total $ | mean $ | win% | avg WIN | avg LOSS | payoff |
|---|---|---|---|---|---|---|---|
| **LONG** | 117 | **−795.24** | −6.80 | 37% | **+$0.90** | −$11.27 | **0.08** |
| **SHORT** | 176 | **+605.40** | +3.44 | 36% | **+$22.00** | −$6.91 | **3.19** |

**Win rates are identical (37% vs 36%).** The entire gap is payoff size, and the asymmetry is extreme:
**the best long trade in the whole ledger is +$6.29.** Across 43 winning longs, not one cleared seven
dollars. The short side's best three are **+$188, +$252, +$505**.

**And market drift cannot explain the loss, because the trades are too short.** The median hold is
**3.0 hours**. At 20.3% over 3,144 hours that is **0.019% of drift per trade** against a stop sitting
**1.78%** away — **1.1% of one stop, 0.011R**. Scaled over 176 shorts it is about **$20**, roughly
**10%** of the $190 loss. The four-month drift is a fact about the window, not a force on a 3-hour trade.

## Statistics, honestly

| | value |
|---|---|
| pooled LONG−SHORT mean difference | **−$10.24** |
| **equal-weighted by week (12 weeks)** | **−$15.93** |
| week-clustered 95% CI | **[−$23.18, −$1.85]** — excludes zero |
| weeks where LONG is worse | **9 of 12** |

The equal-weighted figure is **larger** than the pooled one, so heavy weeks were *diluting* this effect,
not manufacturing it. That is the rarer direction and it strengthens the result.

## 🔴 The mechanism: the long side has almost no access to the bot's profit engine

| exit path | LONG | SHORT |
|---|---|---|
| **TRAILING_STOP** | 4 of 117 (3.4%) — **+$10 total** | 16 of 176 (9.1%) — **+$702** |
| **TP2** | **0 of 117 (0.0%)** | 5 of 176 (2.8%) — **+$449** |
| SL | 52 (44.4%) −$268 | 70 (39.8%) −$329 |
| LLM_EXIT_AGENT | 47 (40.2%) **−$494** | 58 (33.0%) −$227 |

**Every dollar this bot has ever made came from short trades reaching the trail or TP2** — $1,151 of the
$1,161 those paths produced. Longs reach them at **3.4%** against **11.9%**, and the four longs that *did*
trail produced **+$10 between them**.

**This is not a size effect** — mean leverage is 1.56 long against 1.73 short. **And it is not geometry:**
`TP1_SCREEN.md` measured stop and target distances as near-identical by side (LONG 1.81% / 8.12%,
SHORT 1.78% / 8.01%).

So: **symmetric targets, a market that rose 20%, and the long side reached its first target 3.5× less
often.** That combination should not happen, and I cannot explain it from the ledger alone.

## 🔧 For the server — three candidate causes, in the order I would check them

1. **Long entries are systematically late.** If longs are entered into exhaustion while shorts are entered
   into continuation, this is a signal-timing problem and it would show as a worse immediate excursion
   on longs. `ic_dropped_resolved.jsonl` carries `r1h` / `r4h` / `up12` / `dn12` by proposed side —
   that is the file that would answer it, and it needs no new logging.
2. **The exit agent may be specifically bad on longs.** It closes 40.2% of longs for **−$494** (the single
   biggest line item in the ledger) against 33.0% of shorts for −$227. My replay found it **neutral
   overall (+0.037R)** — but that was **pooled across sides**, which would hide exactly this. **A
   side-cut of that replay is the next thing I will run.**
3. **A sign or direction asymmetry in long target/trail handling.** A long that can never record a
   winner above $6.29 across 43 winners looks mechanical rather than statistical. Worth one direct read
   of the long path in `_update_trailing_stop` and the TP1 partial logic.

## Trader rules — one number each
1. **The rising market did not cause the loss.** It explains about **10%**. At a 3-hour median hold,
   four-month drift is worth **0.011R** per trade.
2. **The loss is the long side: −$795 against +$605 short.** Same win rate, 40× worse payoff ratio.
3. **The best long trade ever recorded is +$6.29.** Longs reach the profitable exits 3.4% of the time
   and made $10 doing it.

## Limits — read these before acting
- **"Skip the longs" is NOT a tested rule.** The +$605 counterfactual assumes everything else unchanged,
  which is false: fewer positions changes sizing, the confidence floor, and the exit agent's load. I am
  reporting what happened, not a strategy.
- **Era 1 dominates** (LONG −$648, SHORT +$670). In era 2 **both** sides lost (−$147 / −$131), so this is
  substantially a June phenomenon and era 2 does not confirm it. The clustered CI pools eras.
- **Not independent of the TP1 screen.** The "shorts reach TP1 more" pattern I killed as fragile and this
  are the **same phenomenon**, so this is one observation, not two — but measured in dollars over 293
  trades rather than 25 events, which is why it survives where that did not.
- Pre-2026-07-24 USD is leverage-inflated; read share and sign as solid, absolute dollars as indicative.
- One bot, one four-month window, 43 long winners. **Not red-teamed.**

---

# Update: candidate 2 is **not supported.** The exit agent is not specifically bad on longs.

_Same day. `exit_agent_by_side.py` re-runs the verified replay split by side — same tie rule, same three
bug fixes, so the arithmetic is identical to the pooled run._

| action | side | n | edge (pooled) | edge (equal-weighted by week) | week t | MDE(80%) |
|---|---|---|---|---|---|---|
| close | **LONG** | 267 | **−0.134R** | **+0.389R** | 2.45 | 0.321 |
| close | **SHORT** | 558 | **+0.119R** | −0.092R | −0.39 | 0.224 |

**LONG close edge −0.134R vs SHORT +0.119R. Difference −0.253R, t = −1.81 — not significant,** and the
80%-power MDE for that difference is **0.391R**, so a side gap smaller than that was never detectable here.
**The pooled "+0.037R wash" was not hiding a side split.**

**And the long arm's own estimate is not stable enough to quote in either direction.** Pooled **−0.134R**
and equal-weighted-by-week **+0.389R** have **opposite signs**. When those two disagree on sign, the
number is a property of which weeks carried the volume, not of the agent. The `t = 2.45` on the clustered
figure would read as "the agent adds value on longs" — it is below the MDE and contradicts its own pooled
mean, so it is not a finding.

**Net: candidate 2 is both unsupported and underpowered.** It is not the explanation, and this test could
not have found a moderate version of it.

**That leaves candidates 1 and 3**, which are now the whole question:
- **late long entries** — answerable from `ic_dropped_resolved.jsonl`'s `r1h`/`r4h`/`up12`/`dn12` by side,
- **a mechanical asymmetry in the long trail/TP1 path** — a direct code read on the server's side.

The `hold` and `partial` arms are reported in the script output but are **selected states** (the agent
holds when things go well), and the SHORT hold arm returns **+26R**, which is that selection, not an
effect. They are not evidence about anything.

---

# Update 2: candidate 1 is **UNTESTED, not refuted.** The test I built for it was positive by construction.

_`ic_dropped_resolved.jsonl`, 998 dropped signals — attractive because nothing the bot did to a position
can contaminate them._

**What it appeared to show:** scoring each proposal by its own favourable minus adverse 12-bar excursion,
**LONG proposals +47.1 bps against SHORT −44.4 bps, a +91.5 bps gap, naive t = 8.27**, comfortably past an
MDE of 30.2 bps. Written up naively that reads "the long *signals* were actually the better ones."

**It is drift, and the design guarantees the sign.** Two checks killed it:

| check | result |
|---|---|
| time covered by the file | **1.9 days** (2026-10-08 → 10-10), **1 ISO week** |
| up12 / dn12 ratio, **LONG** proposals | **1.73** |
| up12 / dn12 ratio, **SHORT** proposals | **1.82** |
| up12 / dn12 ratio, **all 998 rows** | **1.80** |

Up-excursions exceed down-excursions by ~1.8× **equally in both groups** — the market rose across the
whole window. Scoring a LONG by (up − dn) and a SHORT by (dn − up) during a rising window **cannot return
anything but a positive gap for the longs.** The short group's ratio is even marginally *higher*, so if
anything those proposals sat in slightly more upward conditions.

**And the clustering was degenerate.** One ISO week means the "week-clustered 95% CI" came back as
**[+91.5, +91.5]** — a point, not an interval. There was never any clustering protection to fail.

This is the rule from the project's own research standard doing its job: *ask whether the result could ever
have come out negative.* This one could not. It is the eleventh time that question has caught something,
and the first time it caught it **before** the writeup rather than after.

**What would actually test candidate 1:** the same `ic_dropped` resolution over **many weeks**, so drift
varies across blocks and a side effect can separate from it. 1.9 days of it cannot. The alternative is a
drift-neutral score — for each proposal compare its excursion to the *same symbol's* move over the same
window — which removes the common market term instead of hoping it averages out.

## Where the long-side question now stands

| candidate | status |
|---|---|
| 1. late / worse long entries | **untested** — needs multi-week `ic_dropped`, or a drift-neutral score |
| 2. exit agent specifically bad on longs | **unsupported and underpowered** (diff −0.253R, t = −1.81, MDE 0.391R) |
| 3. mechanical asymmetry in the long trail / TP1 path | **open — server-side code read** |

The observation itself is untouched: **longs −$795, shorts +$605, identical win rates, best long trade ever
+$6.29, and longs reach the profitable exits at 3.4% against 11.9%.** What is not yet established is why.

---

# Update 3: I fragility-tested this myself. It survives — but the magnitude is two trades.

_2026-10-11. The test I should have run before publishing: the TP1 `side` result died to exactly this
check, and this one should have faced it at the same time._

## It is not a HYPE artifact

| test | diff | week-clustered CI | |
|---|---|---|---|
| as published | −$10.24 | [−23.01, −1.79] | — |
| drop the worst trade (−$264.05) | −$8.04 | [−19.47, −0.64] | **survives** |
| drop the worst 3 | −$7.84 | [−19.51, −0.21] | **survives** |
| drop the worst 5 | −$7.44 | [−19.50, +0.52] | **dies** |
| **drop all 19 HYPE LONGs** | **−$6.90** | **[−17.09, −0.14]** | **survives** |

**Removing every HYPE LONG — the largest single contributor — leaves the effect significant.** The
"drop worst 5" failure is weaker evidence than it looks: two of those five are **SHORTS**
(ETH −$93.84, BTC −$56.49), so that drop removes losses from both arms and is as much a sample-size
effect as a concentration one.

## But the size of the loss is a handful of trades, and that belongs in the headline

| | share of the −$801.94 long-side loss |
|---|---|
| worst **1** long trade | **33%** |
| worst **2** | **44%** |
| worst **5** | **65%** |

**`HYPE` LONG alone is −$459.02 across 19 trades — 57% of the entire long-side loss** — and that is
essentially **two trades**: −$264.05 on 2026-06-17 and −$89.17 on 2026-06-08. It is the worst
symbol-side line in the ledger by a factor of four (next: ETH LONG −$119.25).

**So the honest statement is two-part: the direction is robust, the magnitude is not.** "Longs lose and
shorts win" survives every fragility test that isolates it. "Longs lost $795" is really "longs lost
$795, of which $356 was two bad June trades."

## A hypothesis of mine that was wrong, checked and discarded

The server's `floor_decisions_log.jsonl.gz` revealed a **`HYPE BUY` bypass** that overrode the
confidence floor on the claim that *"HYPE BUY has 88.6% WR in counterfactual data"* — a claim the log
itself later records as **refuted live at 23% WR, n=35**. It fired **661 times**. Live HYPE LONG is
**26.3% WR, −$459**, so the 88.6% figure was badly wrong.

**I expected that to explain the HYPE LONG losses. It does not.** The bypass was active only
**2026-06-19 → 06-29**, and inside that window HYPE LONG took **2 trades for −$10.81**. The damage
(−$448 across 17 trades) sits **outside** it, mostly 2026-06-02 → 06-17, before the bypass existed.

**The bypass is already closed** — it moved to shadow mode from 2026-07-04, and the shadow lines carry
the refutation. Nothing to act on. Recording it because the 88.6%-vs-23% gap is a clean example of a
counterfactual win-rate claim that live data destroyed, and the bot was briefly sized on it.
