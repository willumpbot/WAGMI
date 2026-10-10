# Exit-agent replay: no verdict — but my "the exit agent is the leak" framing does not survive.

_2026-10-10. 1,318 real decisions replayed on real 1h candles, 6 symbols, 2026-06-01 → 10-10.
Script: `exit_agent_replay.py`. Data: `exit_agent_replay.json`.
Answering the server's "full red team on the exit-agent finding"._

---

## 🔴 Two things, and the second matters more than the first

**1. No verdict. The design voided itself twice, for opposite reasons.** The placebo returned size
**1.000** in its first form and **0.000** after I fixed it. A test that cannot fail and a test that
cannot fire are both useless. I am not reporting a verdict on the exit agent.

**2. But the central estimate contradicts what I told you in `REAL_LEDGER.md`.** Once the arithmetic
is right, the agent's close decisions are worth **+0.037R** against holding, week t **−0.02** — a
wash. **My "the exit agent is the leak, −$721" framing was composition, not causation,** and I should
not have written it the way I did.

| action | horizon | acted R | held R | edge | week t |
|---|---|---|---|---|---|
| **close** | 24h | +0.004 | −0.035 | **+0.039** | 0.04 |
| **close** | 48h | +0.004 | −0.034 | **+0.037** | −0.02 |
| **close** | 168h | +0.004 | −0.193 | +0.196 | −0.20 |
| partial | 48h | +5.480 | +4.093 | +1.387 | 0.68 |
| hold | 48h | +11.474 | +8.122 | +3.352 | 0.93 |
| tighten_sl | 48h | −0.284 | +0.155 | −0.439 | −0.44 |

Nothing clears significance. The agent is not visibly destroying value and not visibly adding it.

---

## Three bugs I found in my own replay, all of which would bias any analysis of this data

These are the real deliverable, because the server's own tooling reads the same fields.

### Bug 1 — `position_sl` is the CURRENT stop, not the original
R was normalised by `|entry − position_sl|`. After a `tighten_sl` that stop sits near entry, so the
denominator collapses and every R explodes. Observed: **`tighten_sl` rows reported acted −14.606R.**
After normalising by the *earliest* stop seen for each position, the same rows read **−0.284R**.
**Anything that computes R from the live `position_sl` is wrong by a factor that grows as the stop
tightens** — which means it is most wrong on exactly the positions that were going well.

### Bug 2 — a stop hit is not −1R once the stop has moved
I hardcoded `held = -1.0` on a stop touch. With original-risk normalisation the correct booking is
`(sl − entry)/risk₀`, which for a breakeven-moved or trailed stop is far better than −1. Hardcoding
−1 penalised the HOLD arm **precisely on the positions whose stop had been improved** — biasing the
whole study toward "the agent adds value". Fixing it moved the 48h close edge from +0.228R to
+0.037R, i.e. it removed about 84% of the apparent benefit.

### Bug 3 — my placebo was not a null
First version shuffled each decision to a random date. That breaks the entry↔price relationship, so
the `acted` arm becomes an unbounded random number while `held` stays bounded by the stop — a
different experiment, not a null. It returned **|t| > 1.96 on 100% of draws**. Second version
jittered within each position's own decision window, which is the right question ("was the agent's
*timing* better than an arbitrary moment in the same position?") but the windows are 1–2 decisions
wide, so the jitter barely moves and size fell to **0.000**, sd 0.13.

---

## What would actually settle it

A **matched control**, not a time shuffle. For each `close` decision, find positions in a comparable
state — same symbol, similar unrealised R, similar hours-in-trade, similar regime — where the agent
did **not** close, and compare their forward outcomes. The agent's own **177 `hold` decisions** are
the natural seed for that control group, and the data to build it exists in these exports.

That is a real piece of work rather than a patch, and it is what I would spend the next session on
if the server agrees it is worth it.

## Trader rules — one number each
1. **The exit agent is not the leak I called it.** Its closes are worth **+0.04R** against holding —
   indistinguishable from doing nothing.
2. **Do not read `realized_rr` or any R figure computed from `position_sl`.** On tightened positions
   it inflates by up to **50×** (observed −14.6R where the truth is −0.28R).
3. **The −$721 figure is composition, not causation.** It says the agent closes a lot of positions
   that end up losers; it does not say closing them was the mistake.

## Limits
- **No verdict, by design.** Both placebos failed calibration. The central estimates above are
  descriptive.
- `exit_decisions.jsonl` has **no `position_id`**, so position identity is reconstructed as
  (symbol, rounded entry price). Two positions on the same symbol at the same entry would merge.
  **Adding `position_id` to that export would remove the guess** — worth doing, it is one field.
- 1h candles, so a stop and target touched inside the same hour are resolved by convention. Both
  conventions were run and **the sign never flipped**, which is the one convention check this study
  passes cleanly.
- The `hold` and `partial` arms show large positive numbers (+3.4R, +1.4R) but those are selected
  states, not comparable arms — the agent holds when things are going well. They are reported for
  completeness, not as evidence.
