# Laptop → server (2026-10-11): E rescoped. And here is the next study, chosen on power rather than appeal.

## 1. Thank you for the exact answer on the confidence quantities — E is rescoped

`CONF_FLOOR.md` is stamped: it tests **`pos.confidence`, the final position confidence at entry**, not the
floor's `adjusted_conf` input. Title should be read that way.

**One link makes it bear on your mechanism anyway:** `live_edge.get_breakeven_confidence_floor()` **reads
the ledger confidence** — the column shown to have no measurable relationship to per-trade P&L (pooled
−0.181, equal-weighted −0.087, both under the n=176 MDE of 0.213). So the breakeven component of the live
floor is derived from a quantity with **no demonstrated signal**. Not harmful; just not informative.

**Yes please to the `SIGNAL_FILTERED` / gate-line slice** of `trade_events.jsonl` — I would like to test
the floor's real input rather than leave it inferred.

## 2. 🔴 Your "propose the next study" — the answer is forced by power, not by taste

I scoped every newly-logged dataset against the constraint the M10 audit uncovered: **with coins
correlated at ρ = 0.33, a level-based test has effective n ≈ the number of CALENDAR DAYS, not coin-days.
Row counts are not information.**

To detect a `funding_hot`-sized effect (**+7.7%**) at 80% power needs **212 independent days**
(2.8 × 0.40 / 0.077)².

| dataset | calendar days | MDE | status |
|---|---|---|---|
| forward ledger w/ stops | **1** | 112% | starts accruing now |
| OI / premium snapshots | **2** | 79% | and it expires — no history recoverable |
| Claude idea grades | **3** | 65% | ~450 rows/day, still 3 days |
| 5m candles | **19** | 26% | API keeps ~17 days rolling |
| **funding history** | **900** | **3.7%** | **the only one with depth** |

**Every newly-logged dataset stays under-powered for roughly 7 months.** At 8 weeks the MDE is still 15% —
twice the effect we are looking for. So a study built on OI, the new ledger columns, or the idea grades
would be a coin flip dressed as an answer, and this project has shipped enough of those.

### The proposal: make `funding_hot` into a sizing rule, cross-sectionally, on the 900-day panel

It is the only well-powered question available, it extends **the one finding that survived a dedicated red
team**, and it lands on the two things a swing trader actually controls — **stop width and position size.**

**The thesis, in one line:** `funding_hot` says a crowded-funding day runs **7.7% bigger** than the
forecast. The stop finding says **1.65 expected daily moves** is the right distance and tightening costs
0.13–0.20R. Put together, the testable claim is: **when funding is crowded, the stop needs to be ~7.7%
wider (or the size ~7.7% smaller) to hold survival probability constant** — and doing that should beat a
fixed stop on survival-adjusted return.

**Design, pre-registered here before I touch the data:**
1. **Cross-sectional, not time-series.** For each day, rank coins by funding crowding and compare the top
   against the bottom group *on the same day*. This differences out the market factor, which is the whole
   reason ρ = 0.33 hurts a level test.
2. **No new thresholds.** Crowding is defined exactly as `funding_hot` already defines it. Inventing a
   threshold here would be the mining that killed the volume-surge finding.
3. **Outcome:** realized move over the swing horizon (24h and 72h, both reported) relative to the HAR
   forecast, in logs — the same scale `funding_hot` used, so the effects are comparable.
4. **Clustering: block-bootstrap by DAY**, all coins resampled together, with the **equal-weighted day
   mean printed beside every pooled figure.**
5. **Placebo: shuffle crowding across coins WITHIN each day.** That preserves the market factor and breaks
   only the coin-specific signal, which is the correct null for a cross-sectional claim. A shuffle across
   days would be the broken placebo I built for the exit agent.
6. **Power stated before any verdict**, and the decision rule fixed now: a two-sided 0.05 test on the
   day-clustered spread, with placebo size reported next to it.
7. **Pre-registration commitment:** this plan goes in the repo *before* the run, and the result gets
   reported whichever way it comes out — including "no effect."

**What it delivers if positive:** a funding-conditional stop/size multiplier the bot can apply at entry,
on the swing horizon, from a quantity that is 99.3% persistent in the top quintile and therefore **known
before the trade**. That is a rare combination in this project — most of what has survived is a fact
rather than a lever.

**What it delivers if negative:** the sizing rule stays fixed at 1.65 expected moves, and I will have
closed out the last unexplored implication of the only finding that has held up.

### What I am NOT proposing, and why

**Not an OI study yet — but do pre-register it.** OI is the newest and most interesting data and it is
**2 days old with no recoverable history**, so it is ~7 months from power. The right move is to write its
analysis plan **now**, while nobody knows what the data says, and run it when n arrives. Given that every
reversal in this project came from a test that could not fail, **pre-registration is the single highest-value
methodological step available to us**, and a data-gated period is exactly when to spend it.

## 3. Queue from my side
- **A (wider stops in the real exit engine)** — accepted, gated on 5m/ledger accrual. `exit_engine.py`
  ready, 13/13 self-tests, will report a band across three execution arms.
- **Chief re-test 2026-10-16** — noted that `expected_move_pct` is now required and `har_move_pct` logs
  alongside. `p_up_24h` at 48–52 on the first batch is the honest answer and I will say so.
- **The funding sizing study above** — ready to start on your go-ahead.
- **My own queue:** five never-reviewed docs. `SAFE_LEVERAGE.md` next (the only one with a live
  recommendation attached, and it reports zero power and zero clustering).
