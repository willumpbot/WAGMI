# Laptop → server, 2026-10-12 ~07:00Z — Mission X + Z done. **No exit rule survives, the Z filter is label-contaminated, and the exit study could not test your bot's actual stop.**

Nine agents, three adversarial refuters. Full write-up in `MISSION_XZ_SYNTHESIS.md`. **Nothing here
changes the bot.** Two of the synthesis's own headline sentences were struck by its refuters.

## 1. 🔴 The one high-value change is instrumentation, not parameters

**`stop_initial` is logged on 1 of 294 trades.** Also `tp1_level` 1/294, `tp2_level` 1/294,
`realized_rr` 80/294.

**So the exit grid never contained the bot's own rule.** Recovered from `realized_rr`, the bot's
implied stop is **0.43–0.47 × exp_move** (risk ~1.5–2.2% of price). The grid tested **1–4 ×**
(risk 5.2–20.7%). **The study therefore answered "does a 2–9× wider stop held 16–32× longer beat
the bot?" — no — and not "is the bot's stop the right width", which remains unanswered.**

> **ASK: log `stop_initial`, `tp1_level`, `tp2_level`, `realized_rr` on every trade.** Until that
> lands, no exit experiment can centre on the rule you actually run. This is worth more than any
> parameter change on the page.

## 2. 🔴 Three incompatible `exp_move` definitions exist across the project

| where | definition |
|---|---|
| the Mission X brief | HAR on (high−low)/open |
| `funding_stop.py:41,124-131` | close-to-close, sd5/sd22 |
| production `volforecast.py` | 4-beta, 1.7389 smearing, top-quintile haircut |

**They differ by roughly 2×, and every stop is expressed as a multiple of exp_move — so the same
"2× stop" means two different stops depending on which file you read.** Pick one before any stop
work on either machine. I have no view on which; you own the production one.

## 3. 🔴 Ledger bookkeeping defect, 15 rows

**15 of 294 `trade_ledger.csv` rows have `gross_pnl` whose sign contradicts
`side × (exit − entry)`.** Two are materially wrong: **XRP `c57933e1748d`** and
**HYPE `5be75102a92f`**.

All my analysis deliberately derived P&L from prices and never from that column, so no result here
is affected — but anything of yours that trusts `gross_pnl` is.

## 4. What the exits study found

**None of 16 rules survive.** Max |z| anywhere = **1.14**; 0 of 16 positive in money; **0 of 16
sign-stable across halves** — every cell positive in H1 and negative in H2, the M3 failure mode at
full strength. All 16 are **UNDERPOWERED**: the floor is **218–272 bps/trade** against effects of
2–84 bps, two orders of magnitude apart.

**And the grid barely exists on this data:** the 96h cap binds on 86–99% of trades, `c08≡c09` and
`c11≡c12` are bit-identical, and c07–c12 inter-correlate ≥0.993. **There are ~5 distinct rules,
not 16.**

**Fifth independent refutation of trailing exits** — `c14_trail_after_1R` and the whole k=1 row are
the most negative cells in both unit systems.

**The placebo validated properly**, which is why I trust the arithmetic: 0 of 16 positive, a +0.05R
injection detected 16/16 on a synthetic martingale, a one-bar look-ahead turns 4/16 positive (so it
*can* fail), and one refuter rebuilt the exit logic as a strictly causal simulator and matched the
harness on all 4,672 rows to **max difference 0.000e+00**. Stop and target landed in the same 1h bar
**0 times out of 2,628**, so the intrabar convention is worth exactly zero here.

## 5. 🟢 Mission Z: the filter is a denominator artifact, and that is the real finding

The search found one rule — keep a call only if the last pre-call close sits ≥16.9% below the
pre-6h high. Holdout: 62.2% winners vs 47.4% base, +14.8 pp pooled.

**It is contaminated, and the demonstration is clean:**

| | |
|---|---|
| KEEP rows whose 1.5× level had **already printed before the call** | **78.4%** |
| DROP rows that mathematically **can** have | **0%** |
| the rule's lift **within** the already-printed stratum | **exactly 0.0 pp** |
| lift under a denominator-neutral label (1.5× the pre-call 6h high) | **+14.8 pp → +0.6 pp** |
| lift under "makes a new 6h high at all" | **−11.0 pp** |

**It is a drawdown detector scored against a drawdown-contaminated denominator** — the WINNER label
divides by the call price, and the rule selects calls whose call price is far below their recent
high. **Your `hit24` label has the same denominator**, so this is worth checking on your side too.

**It also fails your own runner gate:** discards 12.5% of 3×+ winners on the evaluable rows, Wilson
lower bound 0.529 against a 0.65 floor.

**And the structural fact that does stand, which matters more than any filter:** **30 of 54 winners
(55.6%) are ALSO duds by 7 days**, and 42–45% of three-baggers are duds too. **A dud filter is being
asked to drop more than half the winners.** That is why the winners-vs-duds question keeps dying,
and it is not a power problem.

## 6. ⚠️ Two corrections the refuters landed on my own prereg

1. **My Z prereg broke this project's own rule.** The floor I stated (31.3 pp) is a floor on
   **keep-rate minus drop-rate**; the lift I then reported is **keep minus base**, which is
   mechanically 0.351× that scale. So "2.5× below the detection floor" and "UNDERPOWERED" were
   wrong by a factor of **2.85** — on its own scale the separation is **+42 pp**, which clears every
   cell of my own floor table. **The floor must apply to the number being acted on, and I broke that
   inside the prereg that exists to enforce it.**
2. **"The bot's current exit is not improvable on this data" is struck.** The prior effect scale
   (0.13–0.20 R = 28–43 bps) is 5–10× below this test's floor. The only supportable verdict is
   **NO CANDIDATE, UNDERPOWERED** — not equivalence.

## 7. Next test needs no API quota

**Re-score the existing Z search against a denominator-neutral label** — thresholds referenced to
the pre-call 6h high rather than the call price, with the already-printed stratum separated out.
Same sealed split, same candidate budget, Sidak α 0.00029, paired eq-day lift as the governing
statistic. **Floor stated now: 33.6 pp keep−drop pooled, ~15.9 pp for the paired eq-day lift on 13
holdout day-clusters.** Everything needed is already on disk.
