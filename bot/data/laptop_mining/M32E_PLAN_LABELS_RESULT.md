# Project X part 6 - the owner's plans on the fade map (DESCRIPTIVE, n=7, NO verdict). Closes the label loop. Takeaway: the fade-lean is a population TILT, not a per-trade oracle - on 7 trades it tracked the outcome 1/7, which at n=7 means nothing, and 6/7 ended "neither" (no clean run or fade in 48h). Don't read the lean as a per-trade call.

_2026-10-15. m32e_plan_labels.py. Only 7 owner/ai plans fall within candle coverage (the rest are the
2025-09..2026-02 wallet era, no candles -> part 5 territory). All 7 reached +0.5R. claude_idea plans
flagged (not owner-direction labels)._

## His 7 in-coverage trades, fade-lean vs outcome
| coin | src | peakR | velocity | fade-lean | outcome |
|---|---|---|---|---|---|
| SOL | owner | 0.80 | fast | RUN_LIKELY | neither |
| BTC | claude_idea | 0.73 | slow | RUN_LIKELY | neither |
| BTC | claude_idea | 0.89 | slow | RUN_LIKELY | neither |
| BTC | claude_idea | 0.85 | slow | RUN_LIKELY | neither |
| ETH | claude_idea | 0.84 | fast | RUN_LIKELY | FADED |
| HYPE | claude_idea | 1.56 | fast | RUN_LIKELY | RAN (lean right) |
| CASHCAT | owner | 2.43 | slow | FADE_PRONE | RAN |

## Read (honest)
n=7 is far too few to judge the lean - this is a label pass for completeness, not a test. The lean
tracked the outcome on 1/7, and most trades (6/7, incl. all three BTC) ended "neither" (no +1.5R run and
no fade to <=0 within 48h). This is CONSISTENT with the sealed finding that the fade tell is a modest
~7-point probability tilt: it is NOT expected to call individual trades, and should never be used as a
per-trade yes/no. CASHCAT (FADE_PRONE but RAN to +2.4R) is the kind of single-trade exception a weak
tilt always throws. Use the lean only as a gentle nudge on the give-back alert (which is how
fade_tells.py ships: insight-only), never as a per-trade gate.

## Rule (one line)
The fade-lean is a weak tilt across many trades, not a crystal ball for one - on your last 7 it was
right once, which tells you nothing except "don't bet a single trade on it." (n=7)
