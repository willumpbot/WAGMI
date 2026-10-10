# The real ledger: the trailing exit is the bot's most profitable path. It runs on 6.8% of trades.

_2026-10-10. 293 real closes from `server_exports/trade_ledger.csv`, 2026-06-01 → 10-10.
First analysis in this project on **actual fills** rather than simulation.
Answers the owner's own question, and reverses my simulated answer._

---

## 🔴 The answer

**The owner was right about the mechanism, and my simulation was wrong about it in both directions.**

| exit path | n | share | net $ | win% | mean $ |
|---|---|---|---|---|---|
| SL | 122 | 41.6% | −596.58 | 40% | −4.89 |
| **LLM_EXIT_AGENT** | 105 | 35.8% | **−721.17** | 22% | −6.87 |
| LLM_EXIT_HIGH | 33 | 11.3% | −123.48 | 12% | −3.74 |
| **TRAILING_STOP** | 20 | 6.8% | **+712.65** | 100% | **+35.63** |
| TIME_STOP | 7 | 2.4% | +90.17 | 71% | +12.88 |
| **TP2** | 5 | 1.7% | **+448.58** | 100% | **+89.72** |
| LLM_EXIT_CRITICAL | 1 | 0.3% | 0.00 | 100% | 0.00 |
| **total** | **293** | | **−189.84** | | |

**Trailing and TP2 are 8.5% of closes and +$1,161. The two LLM exit paths are 47% of closes and
−$845.** The bot is net −$190 because the leak slightly exceeds the engine.

So the lever is **not** "make the trail better". It is:
1. **let more trades reach TP1**, which is the only way the trail can arm at all, and
2. **stop the exit agent closing positions early** — it is the single largest line item in the ledger.

---

## Why my simulation got this wrong, twice

**First I simulated the wrong mechanic.** `README_DATA_RESPONSE.md` documents the live trail:
arms **only after TP1**, books a 50% partial, moves the stop to a cushioned breakeven, then trails
`ATR × 1.5 × style` — **fixed at entry**, tightening 0.67 → 0.33 as it runs TP1 → TP2, with a
profit-lock floor. I swept arm-at +0.25/0.5/1.0R with a constant R-distance trail on 1h bars. Not
the same animal.

**Then I nearly drew a confident conclusion from a biased column.** `realized_rr` is present on only
**79 of 293 rows**, and the missingness tracks the outcome almost perfectly:

| exit type | rows | has `realized_rr` | win% |
|---|---|---|---|
| **LLM_EXIT_HIGH** (loses) | 33 | **32 — 97%** | 12% |
| LLM_EXIT_AGENT | 105 | 11 — 10% | 22% |
| SL | 122 | 34 — 28% | 40% |
| **TRAILING_STOP** (wins) | 20 | **1 — 5%** | **100%** |
| **TP2** (wins) | 5 | **0 — 0%** | **100%** |
| TIME_STOP | 7 | 0 — 0% | 71% |

On that subset I measured **−0.134R, t = −2.84, CI [−0.227, −0.042]** and it looked like a clean,
significant finding about the bot's performance. **It is a selection artifact:** the R column is
recorded on 97% of the worst exit type and 5% of the best one. Had I written that up it would have
been the tenth reversal.

### 🔧 Server action: this is a logging bug worth fixing
**`realized_rr` is missing on 73% of closes, and non-randomly.** Any R-based analysis — mine or
yours — is biased until it is populated. Worst gaps: `TRAILING_STOP` 19 of 20 missing, `TP2` 5 of 5,
`TIME_STOP` 7 of 7. The winners are the rows that don't log R.

---

## What I can and cannot claim about the trail

**Can:** when the trail engages, those trades are the most profitable group in the ledger —
+$712.65 over 20 closes, mean +$35.63, roughly 3.75× the whole bot's net loss in the other direction.

**Cannot:** that this is the *trail's* doing. Two reasons, both structural:

1. **The 100% win rate is tautological.** The trail arms only after TP1 and a 50% partial is already
   banked, so a `TRAILING_STOP` close *cannot* be a loss. The win rate is a property of the state
   machine, not of the exit.
2. **There is no comparison group.** `TP1`-only exits: **0 rows.** The bot never takes TP1 and stops
   — it always trails afterwards. So "trail vs bank TP1 and leave" has no empirical counterfactual in
   this data. It would need a paper arm or a `state_path` replay.

That second point is the one I would spend the next effort on, and the data to do it already exists:
`trades.csv` carries `state_path` (e.g. `IDLE→OPEN→TP1_HIT→TRAILING→CLOSED`) and
`position_journal.jsonl` has per-position entry and closing legs. A replay that books the TP1 partial
and closes the remainder at the TP1 price gives the counterfactual directly.

---

## Trader rules — one number each

1. **Your trailing exit works. It just almost never runs — 6.8% of closes.** Those 20 trades made
   **+$713** while the whole bot lost $190.
2. **The exit agent is the leak: 105 closes, 22% win rate, −$721.** That is the largest single line
   item in the ledger and it is bigger than the stop losses.
3. **Only 8.5% of trades ever reach TP1.** Everything good in this ledger happens after TP1, so
   "how do more trades get there" is a more valuable question than any exit tuning.

## Limits
- **Pre-2026-07-24 USD is leverage-inflated** (the de-leveraging fix). Mean leverage is 1.6 before and
  1.9 after, so the distortion is not wildly asymmetric across exit types — read **share and sign**
  as solid and the absolute dollars as indicative. The honest 45-row window alone has
  `TRAILING_STOP` n=1, which is why I used all 293 for composition.
- **Selection remains.** Trades that reach TP1 may be better trades, not better-exited trades. The
  `state_path` replay above is what separates those.
- 293 closes over 4 months, one bot, one regime. No funding or slippage decomposition attempted here.
- **Not red-teamed.** Given that the first version of this analysis was a selection artifact I caught
  only on the third check, treat the composition table as solid and every causal reading as
  provisional.
