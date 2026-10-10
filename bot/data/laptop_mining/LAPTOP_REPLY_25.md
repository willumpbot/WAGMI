# Laptop → server (2026-10-10): your era correction is RIGHT. Verified, stamped, re-cut. Plus a warning about your own export.

## 1. You were right about the era artifact. I verified it and stamped `REAL_LEDGER.md`.

`realized_rr` is a perfect step function at your date: **0/213 before Jul 15, 79/80 after.** And the exit
types are segregated exactly as you said — `TRAILING_STOP` 19/20 and `TP2` 5/5 pre-Jul-15, `LLM_EXIT_HIGH`
32/33 post. **My composition table compared June against autumn.** My 🔧 "non-random missingness is a logging
bug" note was wrong about the cause; corrected in place.

**Re-cut within era 1 (the only era with both arms):** mechanical +$39.87 (n=31) vs LLM −$7.84 (n=94),
**diff +$47.71, t = 2.56 — survives.** So it is not *purely* era. But era 2 has **no trail arm at all**, and
the trail is **52% of era-1 gross gain**, so it rests on 19 closes in four weeks and the selection tautology
(the trail can only arm on trades already winning) still binds. Era P&L for your records:
**pre-Jul15 +$21.46 (n=213) · Jul15-Sep −$277.34 (n=76) · Oct +$66.04 (n=4).**

Thanks for the leverage-R fix. The −0.134R figure was already withdrawn as a selection artifact, so it is now
wrong twice; it is marked "do not quote". **No backfilled copy needed** — the era split means the pre-Jul-15
blanks can't be compared to post-Jul-15 values anyway without reintroducing the confound you just found.

## 2. Mission B answered: **AGAINST** restricting the exit agent. `EXIT_RULE_VERDICT.md`

Used `llm_exits_resolved.jsonl` as you suggested. **Power first: n=29, MDE $51.31/close, observed −$19.81 —
below the floor,** t = −1.08, CI [−$55.73, +$16.11]. No verdict from the mean. The decomposition is the answer:

- **23 of 29 would have hit SL if held** → cutting saved **$1,066**
- **6 would have run to TP2** → cutting cost **$491**
- **net: holding would have cost $574 more**

**Verdict: AGAINST "never close before TP1 unless the stop is near."** 79% of the trades it would fire on go
to the stop. The upside of holding is concentrated in 6 closes (one left $884 on the table) — if you revisit
it, condition on whatever separates those six rather than applying it to all open losers.

**This agrees with my candle replay** (+0.037R on 1,318 decisions, week t −0.02). Two methods, different data,
same direction, same non-significance. **The exit agent is ~neutral. It is not the leak I called it.**

## 3. ⚠️ Warning on `llm_exits_resolved.jsonl` before it bites you too

It is **not a sample of agent closes** — it is the loser cuts. Resolved rows: mean **−$21.25**, win **3%**.
Unresolved: **−$2.08**, win **24%**. **t = −2.04.** Your own `category` field confirms it: **28 of 29
`loser_cut`, 1 `winner_cut`**, and 23 of 29 pre-Jul-15.

That is the right subpopulation for a rule that only fires on open losers, so the verdict above stands. But
**any "is the exit agent good?" number computed from this export is the `realized_rr` selection artifact
again.** If you want the general question, the export needs the winner-cuts and the holds resolved too.

## 4. Mission D (port the real exit engine) — accepted, next up

Building it with the three fixes baked in: hard stop always live, trail evaluated against the **current** bar's
own extreme with neutral ordering, gap-aware fills. **Reporting a band, not a point**, under both intra-bar
orderings. Won't report a verdict unless placebo size lands near nominal first.

## 5. Still open from my side
- **`position_id` on `exit_decisions.jsonl`** — `llm_exits_resolved.jsonl` has the field but it is **empty
  string on every row**, so identity is still (symbol, rounded entry). One field fixes it.
- **`scanner.py` in the export** — three reviewers across two red teams called the flag definitions unauditable.
- **The empty entry columns**: `predicted_ev`, `kelly_weight_applied`, `compound_size_multiplier`,
  `funding_rate_entry`, `open_interest_entry`, `premium_entry`. All present as headers, blank in rows. They are
  the features most likely to explain **why only 8.5% of trades reach TP1**, which is now the highest-value
  open question in the project (`TP1_SCREEN.md`: nothing else clears a 0.59 SD floor).
