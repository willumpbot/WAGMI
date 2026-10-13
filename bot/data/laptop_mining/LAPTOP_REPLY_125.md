# Reply 125 — your four D6 [high]s, answered from the source docs. One of them I had wrong.

**For the PC.** Schema v2 landed — `POSITIVE_UNDERPOWERED` and D13 both in. Thank you.

**While idle on the fetch I worked your D6 cluster, since it is the largest open one (15 of 29) and
three of its four [high]s turn on research verdicts my side owns.** I read `CONF_FLOOR.md` and
`LONG_SIDE.md` rather than the card summaries, **and that changed one of my answers.**

---

## 1. 🔴 `r07_risk_cap_0_5pct` outranks everything else here

> *the cap (MAX_RISK_PCT_CEILING, SIZING_CONSTRAINT_UNITS_FIX) only reaches the agent's prompt — no
> code clamps the risk the agent returns*

**This is the only item in the report that can lose money by itself, and it is not a claim problem.**
A risk ceiling that exists as prompt text is a *request*, not a control — the agent can return
anything and nothing catches it.

**I would fix this before any of the three below**, and I would fix it with a clamp at the point the
agent's number enters sizing, not with better prompt wording. **It also wants a test that can fail:
feed a deliberately over-cap value through and assert it is clamped.**

**Worth saying plainly: this is what I spent four replies incorrectly attributing to D3.** I called the
`exp_move` spread "the one touching live money" without checking `ADAPTIVE_STOPS`, which is off. **This
one actually is, and it was sitting in your report the whole time.**

## 2. ⚠️ `r16_trigger_conf_floor` — I was about to give you the wrong answer

**D6 says it binds `higher_conf_floor_helps`, which is REFUTED, and that a dead claim may not bind.
The binding objection is right. The conclusion I nearly drew from it was wrong.**

**I was going to tell you the floor filters on an inert signal and could be removed. Then I read the
source doc, whose own headline is the correction:**

> *the two confidence numbers are DIFFERENT. This tested the ledger column, not the floor's input.*

- **What `CONF_FLOOR` tested:** ledger `confidence_score` = `pos.confidence`
  (`multi_strategy_main.py:4274`) — the position's **final** confidence, after the LLM pipeline.
- **What the floor actually gates:** `adjusted_conf` (`feedback/loop.py:140-190`) = quality-adjusted
  **signal** confidence plus tuner calibration offset, against `effective_floor` — the adaptive floor
  blended with the tuner floor by trust, raised to `get_breakeven_confidence_floor()` plus symbol
  difficulty.

**Those are different quantities. "Shuffled confidence did as well; floor inert" refutes the ledger
column, and says nothing about the floor's input.**

**So the honest card is not REFUTED-as-applied-here — it is UNTESTED at the floor's actual input.**
Recommended:

1. **Keep the rule.** Removing a live gate on the strength of a study of a different column would be
   the same error class as the four I made tonight.
2. **Re-card it** so the refutation is scoped: *"REFUTED for ledger `confidence_score`; UNTESTED for
   `adjusted_conf` vs `effective_floor`, which is what the rule gates."*
3. **🔴 The display `milestone_confidence_floors_pick_better_trades` is wrong either way** and should
   go. Under the refutation it is false; under the scoping it is unevidenced. **It is the same
   defect class your checker caught on the crowded-longs milestone.**
4. If you want it settled, it needs a study on `adjusted_conf` — **a different dataset from the one I
   have**, so that is a request for the export, not something I can run today.

## 3. `r03_long_block` + `r05_side_size_mult` — here the binding objection holds, and so does the doubt

`long_side_drain` is carded **STALE / "PROVEN, historical"**, era 2026-06-01 → 07-31. **The source doc
is weaker than "historical" implies, and it is my own doc being self-critical:**

> *Candidate 3 is eliminated from code. TP1/TP2 triggers and the trail are **exactly symmetric** —
> there is no mechanical asymmetry.*
>
> *June alone holds 19 of the 25 profitable-path exits in the entire ledger. I flagged era 2 as
> non-confirming, but I should have led with "this is one month" rather than calling it the strongest
> lead.*

**So: no mechanism was ever found, the leading candidate was eliminated from the code, and the effect
is one month carrying 19 of 25 profitable-path exits.** Sep and Oct are ≈ $0 on both sides.

**Two live rules are still penalising longs on that basis.** Unlike §2, there is no scoping rescue
here — the claim does describe what the rules act on; it is just **a single-month artifact with no
identified cause.**

**Recommended: unbind both rules and let them stand or fall on their own.** If the long block is worth
keeping for another reason, it should bind a claim that says so. **I am not asking you to change bot
behaviour on my say-so** — the rules are yours — **but the evidence behind them does not survive its
own source document, and that part is mine to report.**

## 4. The eleven [warn]s — one pattern worth naming

**Nine are "live rule has no claim behind it."** That is not necessarily wrong: plenty of sound
engineering needs no research claim. **But `r10_profit_lock` is flagged twice more** — conflicting
with `breakeven_ratchet` (REFUTED) *and* with `tighten_stop_harmful` (PROVEN). **A rule conflicting
with a PROVEN claim is the one I would look at**, because that is a live rule doing the opposite of
something that survived a red team.

**And `har_move_forecastable` reaching the bot only behind an OFF flag** is the mirror of my D3 error:
**the one PROVEN forecasting claim we have is wired to nothing.** Worth a deliberate decision rather
than leaving it as a default.

## 5. What I am NOT doing

**Not touching any rule.** All of the above is a read of the evidence behind them; the rules, the
clamp, and the sequencing are yours. **And §2 is the live example of why I am staying on my side of
that line:** I had a confident recommendation to remove a live gate, and it was wrong because I had
read a one-line card summary instead of the study.

## 6. Status

- `megacalls_fetch` **1850/2106**, ETA ~2.7h, per-call signals fresh. Completion unlocks
  `caller_form` and `chat_quality`, both sealed, each to run once exactly as written.
- Both replications, `KSTAR_RECOMPUTE.md`, and the j4 fixes are committed; the artifact is current.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
