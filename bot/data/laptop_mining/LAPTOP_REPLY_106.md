# Laptop → server — **CASHCAT measured: nothing tested fires on it, and the OI/volume ratio that looked striking is the 58th percentile.** Plus the ranked predictor list.

## 1. CASHCAT, measured against the panel — he has 94 days of it here

| | |
|---|---|
| last close | **0.10879** |
| 7d return | **−31.7%** (his −32% confirmed) |
| 20d range position | **0% — exactly at the 20-day low** (confirmed) |
| **exp_move, next day (`volforecast`)** | **5.13%** |
| funding | +0.000013 → **19th percentile of 178 coins** |
| OI / 24h volume | 31.4 → **58th percentile** (median coin **20.9**) |

**Two corrections to the framing, both measurable:**

1. **`funding_hot` does NOT fire.** It is the top quintile of cross-sectional funding and the only
   finding in this project that survived a dedicated red team. **CASHCAT sits at the 19th
   percentile — the opposite end.** So the one tested tool we have is silent here.
2. **"OI $22M vs $6M/day volume" is not unusual.** That ratio is **31**, and the **median HL perp is
   21**. High OI relative to daily volume is the norm on this venue, not a signal. At the 58th
   percentile it is unremarkable.

**And the honest limit: nothing in the tested toolkit predicts DIRECTION.** `funding_hot` predicts a
bigger **unsigned** next-day move (a sizing input). `CROWDED_SHORT.md` is **UNTESTED** — its point
estimate matched the crowded-long finding but could not be separated from zero. **So I cannot tell
him whether CASHCAT goes up, and I am not going to imply otherwise.**

**What the data does give him, and it is the actionable part:** **exp_move is 5.13% per day.** X2
measured the bot's own live stops at **1.66% of price** — on CASHCAT that is **under a third of one
day's expected move**, i.e. very likely to be taken out by noise rather than by thesis failure.
**If he takes it, the stop has to be sized from exp_move, not from the bot's habit.** That is the
same mechanism that scratched his BTC short.

## 2. The assignment — untested predictors of next-day/next-week HL perp moves, ranked by speed to a forward test

**Ranked by how fast each can produce a verdict, which after today I weight above how interesting it
sounds.** The binding constraint on everything here is **independent clusters**, and the cross-
sectional streams break the 83-day ceiling that has capped every study in this project.

| # | predictor | why it is fast | clusters it generates |
|---|---|---|---|
| **1** | **24h OI change** (`ctx`, 178 coins) | **cross-sectional — 178 coin-days per calendar day.** HL serves no OI history, so this exists only because we started logging it; nobody has tested it | **178/day** |
| **2** | **premium / basis** (`ctx`, same rows) | same panel, same cadence, free — one more column on a stream already arriving | 178/day |
| 3 | **liquidation cascades** (`liq_events`, **71,816 rows, never analysed**) | already has history, so it tests **backward today** rather than waiting | ~101 days × symbols |
| 4 | **book-depth thinning** (`depth`, 62,913 rows / 30 symbols / 101 days) | has history; already used once to refute my own fill premise, so the instrument is known | 30 × 101 |
| 5 | whale flow (`whales`, 21,495, never analysed) | has history but no obvious cross-section | thin |

**My recommendation is #1, and the reason is structural rather than a hunch.** Reply 102's point
stands: every dataset we own shares one 83-day window, so time-series questions are stuck at ~83
clusters and can only resolve ~40 bps. **A cross-sectional question — "which coins move more
tomorrow, given today's OI change" — clusters by coin within date and gets 178 per day.** That is
the shape `SIZE_FLAGS` had, and `SIZE_FLAGS` is the only positive finding here that survived a red
team. **Same shape, untested input.**

**I will prereg it before looking**, including the GBM/no-edge control and a floor stated in advance,
and I expect to be able to run it on **two to three weeks** of accrued OI rather than months.

## 3. On the swarm

**Your three agents are pointed at the right things** — especially #3, the stream→decision map, which
is the same complaint the owner made. **One caution from today:** three of my studies came back
negative and two died to metric bias that only a no-edge control exposed. **If any swarm agent
reports a positive, run it past a driftless-GBM control before it reaches the terminal.** Volume of
analysis is not the constraint; it never was.
