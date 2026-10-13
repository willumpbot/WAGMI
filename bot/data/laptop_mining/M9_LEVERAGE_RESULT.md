# M9 phase 1 — **Your instinct is right that the cap is timid, and wrong that it costs you anything.**

_2026-10-13. `m9_leverage.py`. **EXPLORATORY**, no card above HYPOTHESIS, no live change.
26 coins, 600 random-time both-sided entries each, 1h bars, stop at one expected move, 72h horizon._

**Owner:** *"I probably would've gone closer to the safe max limit, however I don't know ... that's
where the data and information gap really comes in."*

---

## 1. The answer in three lines

1. **The terminal's safe-leverage table is 4.6× to 6.7× more conservative than your stop requires.**
   At **120% of "safe"**, the chance a wick liquidates you before your stop fills is **0.000 to
   0.002**. So yes — the cap is timid.
2. **And raising leverage would gain you nothing**, because with dollar risk fixed by the stop,
   **leverage does not change your P&L at all.** It only frees margin you are not using.
3. **The thing actually limiting your position size is the 0.5% risk cap and the stop distance —
   not leverage.** If you want bigger positions, that is the dial, and it is the one you just turned
   *down* by enabling the clamp.

## 2. Why leverage cannot change returns here

**Size is `risk ÷ stop_distance`.** Fix the dollar risk and fix the stop, and the position is
**identical at 3× and at 9.5×**. The only things that move are:

- **margin locked** = notional ÷ L
- **liquidation distance** = 1/L − maintenance margin

**Anyone answering "3× or 5.9×?" in terms of expected profit has the wrong model**, and that includes
the intuition that a lower multiplier is leaving money on the table. It isn't leaving money anywhere;
it is leaving *margin* idle.

## 3. The timidity, measured

| coin | terminal "safe" L | stop-based hard ceiling | ratio | P(liq before stop) @120% |
|---|---|---|---|---|
| BTC | 9.5× | **43.4×** | 4.6× | 0.000 |
| ETH | 7.8× | 35.8× | 4.6× | 0.002 |
| SOL | 7.4× | **34.2×** | 4.6× | 0.000 |
| HYPE | 4.8× | **25.1×** | 5.3× | 0.002 |
| XRP | 6.2× | 35.0× | 5.6× | 0.000 |
| NEAR | 3.4× | 22.7× | 6.7× | 0.002 |

**The table protects against a p99 one-day adverse move (6.7% BTC → 19.4% NEAR).** But a stop at one
expected move (1.8% → 3.9%) **fills long before that move completes**, so the table is guarding a
scenario the stop already handles. **The ceiling that matters is where liquidation would sit inside
the stop** — and that is 22× to 43×, not 3× to 9×.

## 4. 🔴 But the margin it frees is margin you are not using

On **$5,000 at 0.5% risk per trade**:

| coin | stop | position notional | margin @3× | margin @safe L |
|---|---|---|---|---|
| BTC | 1.80% | **$1,385** | **$462** (9.2% of account) | $146 (2.9%) |
| SOL | 2.43% | $1,030 | $343 (6.9%) | $138 (2.8%) |
| HYPE | 3.48% | $718 | $239 (4.8%) | $151 (3.0%) |
| NEAR | 3.91% | $639 | $213 (4.3%) | $189 (3.8%) |

**At 3× you can already hold roughly ten concurrent positions.** The bot runs one or two. **Going to
9.5× turns "ten" into "thirty-four" — capacity that is already idle.**

**So the honest reading of today's 3× on SOL/HYPE is not timidity. It is irrelevance.** The 0.5% risk
cap and a ~2.4% stop make the position $1,030 whatever the multiplier says.

## 5. What this does NOT say — three things that could overturn it

1. **🔴 Maintenance margin is modelled FLAT at 0.5%. Hyperliquid's is TIERED and rises with position
   size.** That bites hardest exactly where you would push leverage, so **the 22–43× ceilings are
   optimistic** and phase 2 must put the real schedule in before anyone acts on them.
2. **It assumes the stop always fills at the stop price.** A gap, an outage, or a liquidity hole
   breaks that — **and that is precisely the scenario the p99 table exists for.** My 1h bars cannot
   see an intra-hour gap, so I have measured wick risk, not gap risk. **The p99/1.5 rule may be
   defensible for a reason my simulation structurally cannot test.**
3. **Random entries, 72h, one venue, 2026-03-17 → 10-13.** Nothing here says whether to take a trade;
   only what leverage does once you have.

## 6. What I would change, and what I would not

**Would not:** raise the leverage cap. It would buy idle margin and spend real tail risk, against a
model of maintenance margin I have already flagged as optimistic.

**Would:** stop treating leverage as a decision worth agonising over at this account size. **The two
dials that actually move outcomes are the risk per trade and the stop distance.**

**The genuinely open question your instinct points at is different and better: are positions too
SMALL?** At 0.5% risk, a $5k account risks **$25 a trade**. That is a question about risk appetite and
drawdown tolerance, not leverage — **and unlike the leverage question, it would really change
returns.** It also runs straight into the cap you enabled today, so it is a decision for you and the
desktop, not something I should quietly assume.

## 7. Phase 2, queued
- HL **tiered** maintenance margin and funding accrual over the hold (§5.1).
- Condition the whole table on `exp_move` decile and `funding_hot`, so "is /1.5 too timid" gets a
  regime-by-regime answer rather than an average.
- Liquidation-before-stop on **5m** bars for the 72 coins that have them, to narrow the gap-risk blind
  spot in §5.2.
- Positioning: limit vs market, scaling in thirds, distance from liquidation clusters.

## Bug found and fixed before any number was read
The first run reported **P(liq before stop) ≈ 0.40, identical at 50% and 120% of safe leverage** —
impossible, since closer liquidation must raise it. Cause: both "never reached" states used the same
sentinel (10⁶), so `liq_bar <= stop_bar` was TRUE whenever **neither** happened, scoring every quiet
trade as a liquidation. **The flatness across leverage is what exposed it.** Same family as treating
an absent log line as a zero.
