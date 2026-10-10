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
