# "Never close before TP1 unless the stop is near": **AGAINST** — on the only data that can test it, the rule loses money.

_2026-10-10. Answering the server's mission-B / exit-agent question using `server_exports/llm_exits_resolved.jsonl`
(29 server-resolved counterfactuals). Second independent method on the same question; agrees with `EXIT_AGENT_REPLAY.md`._

---

## 🔴 Verdict: AGAINST the rule. But read the power line before the dollar figure.

**Power first.** n = 29, sd of delta $98.69, so the **80%-power MDE is $51.31 per close.** The observed mean is
**−$19.81 — below the detection floor**, t = −1.08, 95% CI **[−$55.73, +$16.11]**. **The aggregate is not
statistically distinguishable from zero.** Any verdict here rests on the decomposition, not the mean.

| if held to the mechanical exit | n | realized | if held | delta |
|---|---|---|---|---|
| would have hit **SL** | 23 | −583.47 | **−1,649.08** | **−1,065.61** |
| would have hit **TP2** | 6 | −32.77 | **+458.39** | **+491.15** |
| **net** | **29** | −616.23 | −1,190.70 | **−574.46** |

**79% of these positions would have hit their stop if held.** The agent cut them, and cutting saved **$1,066**.
The 6 that would have run to TP2 cost **$491** by being cut. Net: holding them all would have cost **$574 more**.

So the rule "don't close before TP1" would, on exactly the trades where it bites, have **lost money** — and the
reason the t-stat is weak is that the 6 wrong cuts are individually large (max **$884** left on the table).
That is a variance story, not a sign story: the sign is stable, the magnitude is not.

## ⚠️ The export that answers this is a biased sample — flagging it before it bites either of us

`llm_exits_resolved.jsonl` is **not a sample of agent closes.** It is the loser cuts:

| | n | mean P&L | win rate |
|---|---|---|---|
| resolved (in the export) | 29 | **−$21.25** | **3%** |
| unresolved (the other LLM closes) | 110 | −$2.08 | 24% |

**t = −2.04.** The export is 10× worse per trade than the closes it omits, and the server's own `category`
field says so outright: **28 of 29 are `loser_cut`, 1 is `winner_cut`.** 23 of 29 sit pre-Jul-15.

That is fine for the question *actually* asked — "were the agent's worst closes right?" — and it is the right
subpopulation for a rule that only fires on open losers. It is **not** usable for "is the exit agent good?",
and a verdict computed from it without this caveat would be the `realized_rr` selection artifact a second time.

## Two independent methods now agree

| method | n | estimate | significant? |
|---|---|---|---|
| my 1h-candle replay (`EXIT_AGENT_REPLAY.md`) | 1,318 decisions | **+0.037R** for closing | no (week t −0.02) |
| server-resolved counterfactuals (this doc) | 29 loser-cuts | **+$574** for closing | no (t −1.08) |

Different data, different resolution, different failure modes — **same direction and same non-significance.**
The exit agent's closes are not the leak, and restricting them is not an improvement I can find.

## Trader rules — one number each
1. **Do not add the "never close before TP1" rule.** On the 29 closes where it would have applied, holding
   costs **$574 more**, and **79%** of them would have hit the stop.
2. **The cost of the rule is concentrated, not spread.** Six closes account for the entire upside of holding;
   one of them alone left **$884** on the table. If the rule is ever revisited, it should be conditioned on
   whatever separates those six — not applied to all open losers.
3. **The agent is ~neutral, measured twice.** +0.037R on 1,318 decisions, +$574 on 29 — neither significant.

## Limits
- **n = 29, below its own detection floor.** The sign is consistent; the size is not established.
- **Biased subpopulation, by construction** (see above). Conclusions apply to open losers only.
- **23 of 29 are pre-Jul-15**, so this inherits the era confound documented in `REAL_LEDGER.md`.
- Server-side resolution; I did not recompute the SL/TP1/TP2 hits from candles. `match_time_diff_s` is up to
  ~5 min on some rows, which is a real but small source of error at these stop distances.
