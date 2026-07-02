# RQ18 — GOLDEN-ERA ARCHAEOLOGY (2026-07-02)

Lane: reconstruct the conditions of the two claimed profitable stretches and decide if there is a replicable recipe.
Script: `bot/tools/research/rq18_golden_era.py` (read-only over `bot/data` + `historical/`; price truth = HL candleSnapshot 1h, aggregated to 4h for regime; candle cache `rq18_candles.json`).
Inputs: `bot/data/trades.csv` (92 closes), `bot/data/trade_ledger.csv` (hold/exit join), `historical/old-bot-pre-2026-04-23/trades.csv` (228 closes, Mar 25–May 11).

## VERDICT (one paragraph)

**There is only ONE golden era, not two — and its money is regime beta, not trade-level alpha.** The "+$1,756 metadata-poor era" and "June 1–6" are the same five days: the no-metadata bucket (n=22) makes +$1,773 from its 5 trades inside Jun 1–6 and −$17 from its other 17. June 1–6 was a violent bear leg (BTC −14.8%, ETH −21.8%, SOL −23.5% in 5 days; realized vol 3–8%/day vs ~1%/day the prior week); the bot was short 11/13 times at 1.5–2.5x and made +$1,537 — **less than a passive 2x short of ETH (+$2,183) or SOL (+$2,349) and about equal to passive 2x BTC (+$1,477) on the same $5k**. A zero-edge system with the same trade magnitudes produces ≥+$1,537 about 10% of the time (sign-flip MC, 200k trials); remove the top 3 trades and the era is −$229. The one candidate live-detectable condition — 4h trending_bear (ADX>25, −DI>+DI, close<EMA50) — **fails the era split**: SHORT in trending_bear is 8/10, +$1,788 in Jun 1–6 but 5/19, −$158 after Jun 7. The replicable recipe, stated honestly as an n=2 hypothesis: *when a multi-day high-vol bear leg is underway, be short with asymmetric exits and stop trading when it ends* — both profitable stretches in the bot's entire history (Jun 1–6 +$1,537; old-bot May 7–8, 7 consecutive shorts, +$1,019) are exactly this, and everything outside them sums to deeply negative.

---

## 0. Record correction (the "two eras" premise is wrong in our own docs)

- RESEARCH_AGENDA Q18 says "pre-May trades (rows 1-21, +$1,756)". **False.** The old-bot archive (Mar 25–May 11, n=228) totals **−$3,714.99** (Mar −$68 n=7, Apr −$2,119 n=198, May −$1,529 n=23); its rows 1–21 sum to **−$69.51**.
- The real +$1,756.61 is the `unknown_no_metadata` bucket of the CURRENT ledger (BT_SIGNAL_SOURCES): n=22, of which **5 trades inside Jun 1–6 = +$1,772.97** and 17 trades after Jun 7 = **−$16.88**.
- So "early big-short era" ⊂ "June 1–6". One era. DATA_CENSUS row for `historical/old-bot-pre-2026-04-23/` ("the +$1,756 era") is mislabeled the same way.

## 1. What the market did (HL candles, ground truth)

| Day (2026) | BTC ret / rv | ETH ret / rv | SOL ret / rv |
|---|---|---|---|
| May 30–31 | −0.3..+0.6% / 0.7–0.8 | ±0.7% / 0.7–1.2 | ±0.8% / 1.2–1.5 |
| Jun 1 | −3.05 / 2.0 | 0.00 / 2.4 | −1.42 / 3.1 |
| Jun 2 | −6.55 / 3.1 | −7.37 / 3.4 | −8.73 / 4.5 |
| Jun 3 | −3.92 / 3.6 | −2.52 / 5.5 | −3.49 / 5.1 |
| Jun 4 | −0.41 / 4.4 | −2.32 / 4.5 | −3.84 / 6.1 |
| Jun 5 | −4.42 / 6.1 | −10.60 / 7.1 | −7.61 / 7.9 |
| Jun 6 | −0.28 / 2.3 | −0.85 / 5.0 | −2.25 / 5.5 |
| **Jun 7** | **+4.02** / 3.3 | **+7.68** / 4.0 | **+6.92** / 5.0 |

(rv = realized vol, %/day from 1h log-returns.) Cumulative Jun 1→Jun 6 close: BTC −14.8%, ETH −21.8%, SOL −23.5%. Then Jun 7 was a V-reversal (+4–8%) and Jun 7–16 chopped back up (BTC +7.9%, ETH +14.3%, SOL +18.2%). The golden era is exactly one directional leg, and it ended in one day.

## 2. What the bot did differently (n=13 vs n=79)

| | Jun 1–6 | Jun 7+ |
|---|---|---|
| n / WR / net | 13 / 61.5% / **+$1,536.56** | 79 / 20.3% / **−$796.10** |
| Trade rate | 2.61/day | 3.20/day |
| Sides | SHORT 11 (+$1,601), LONG 2 (−$64) | SHORT 52 (−$163), LONG 27 (−$633) |
| Leverage on the big wins | 1.5–2.5x | up to 15x appears |
| Median hold | 2.75h | 2.98h |
| Winner holds / exits | 1.9–8.8h → TP2 / trailing (378, 1010, 377) | — |
| Loser holds / exits | 0.7–1.7h → SL (−2 to −188) | — |
| Entry hours UTC | spread (01–21h), no cluster | spread, no cluster |
| Symbols | ETH +$823, BTC +$390, SOL +$379, HYPE −$56 | all negative; HYPE −$518 worst |

The mechanical signature of the era: **with-trend shorts at modest leverage, losers cut in ~1h, winners run 5–9h to TP2/trailing** (avg win $167 vs avg loss $8 in the no-meta bucket). The only losers in-era were the 2 counter-trend HYPE LONGs and 1 pre-confirmation ETH short (Jun 1, ADX still 21) and 1 BTC short stopped in a bounce. Entry hour: no session edge in either era (contradicts nothing in RQ11).

## 3. Detectable-live condition — and its era-split failure

At entry time (4h candles closed before entry only — genuinely live-computable): `trending_bear` = ADX(14)>25 AND −DI>+DI AND close<EMA50.

- Jun 1–6: **10/13 entries in trending_bear** — all 9 winning shorts were; ADX rose 35→41→44→60→72 through the leg.
- Full-ledger split (n=92, XRP n=2 excluded):

| side × regime | n | WR | net |
|---|---|---|---|
| SHORT + trending_bear, **Jun 1–6** | 10 | **80%** | **+$1,788** |
| SHORT + trending_bear, **Jun 7+** | 19 | **26%** | **−$158** |
| SHORT, no TB (all) | 33 | 21% | −$192 |
| LONG + trending_bear (all) | 10 | 20% | −$300 |
| LONG, no TB (all) | 16–18 | 11–12% | −$395 |

So: trending_bear was present at the golden entries (detectable ✓) but is **not sufficient** — after Jun 7 the same flag fired 29/77 times (ADX lags; it kept reading "bear" during the reversal chop) and shorts under it were 26% WR. The condition that actually made the money — "the leg continues for 3 more days" — is only visible in hindsight. Per THE_STANDARD, a condition you can only see in hindsight is not a signal. Untested residual hypothesis (n too small to validate): golden entries had *rising* ADX and fresh lows ("young leg"), Jun 7+ TB signals were stale-trend chop; nobody should build on this without a proper leg-freshness backtest.

## 4. Adversarial: is it luck?

- **WR test**: 8/13 wins, P(≥8 | p=0.5) = **0.29**. Nothing.
- **Dollar test**: sign-flip Monte Carlo on the 13 |PnL| magnitudes: P(net ≥ +$1,537) = **0.104** (20,710/200,000). A zero-edge coin with our exit geometry hits the golden era 1 time in 10.
- **Fragility**: remove best trade (ETH +1,010) → +$526; best two → +$148; best three → **−$229**. The era is 3 trades.
- **Window test**: 3/80 contiguous 13-trade windows in the ledger reach +$1,537 — all overlapping Jun 1–6.
- **Beta test**: passive 2x short held Jun 1→6 on the same $5k: BTC +$1,477, ETH +$2,183, SOL +$2,349. The bot **underperformed naive exposure** to the coins it traded most profitably. Zero evidence of timing alpha above direction.
- **Base rate**: across both ledgers (320 closes) lifetime net is ≈ −$2,975. A system that loses overall will still print a +30%-equity week every time a −20% market leg coincides with its short bias. Old bot confirms the pattern: its single best stretch is also 7 consecutive shorts in a bear leg (May 7–8, +$1,019, 7/7) inside a −$3,715 lifetime.

Conclusion of the adversarial pass: **cannot reject luck at the trade level; can reject "hidden alpha" vs passive exposure.** What is NOT luck (p≪.01 territory) is the loss side: LONGs are 4/28 lifetime (−$694) and Jun 7+ trading in no-regime lost −$796 over 79 trades — the bot reliably *gives back* golden-era money in chop.

## 5. The recipe (as falsifiable hypothesis, n=2 legs)

1. **Regime, not signal**: profit exists only inside multi-day, high-rv bear legs (2 of 2 in history). Entry trigger candidates (rv > 2× prior-week average AND 4h trending_bear with rising ADX) are live-detectable but validated on n=2 legs — hypothesis, not knowledge.
2. **Direction with the leg only**: in-era counter-trend trades lost (HYPE longs 0/2); lifetime LONGs 14% WR. LLM-approved longs 0/13 (BT_SIGNAL_SOURCES) is the same fact.
3. **Asymmetric exits**: ~1h stop on losers, 5–9h TP2/trailing on winners — this geometry is what converted the leg into +$1,537 while 5 in-era losers cost only −$395.
4. **Stop when the leg dies**: the entire lifetime negative comes from trading through chop at ≥3/day. Jun 7 (a +4–8% reversal day against open shorts' logic) was live-detectable as leg-death; the bot instead traded 79 more times.

**Falsifiers**: (a) the next 4h-trending-bear episode with n≥13 with-trend shorts nets ≤$0 (the naked-TB version is already falsified by Jun 7+: 26% WR, −$158); (b) a leg-freshness-qualified backtest over the 36.5k counterfactuals shows no WR lift for young-leg vs stale-leg TB shorts; (c) any future bear leg ≥10%/5d where the recipe's paper P&L underperforms passive 2x short — which would confirm the beta interpretation and kill the "recipe" framing entirely.

**Week-1-artifact test**: applied — the "edge" did not survive week 2 (Jun 7+ TB shorts −$158). Recorded as a killed hypothesis in its naked form; only the regime-gated version (with leg-freshness + leg-death exit) remains open, pending backtest per feedback_backtest_before_adding.

## Files
- Script: `bot/tools/research/rq18_golden_era.py` (+ `rq18_candles.json` cache)
- Corrections owed: RESEARCH_AGENDA Q18 line ("pre-May rows 1-21") and DATA_CENSUS row 147 label — both attribute +$1,756 to the wrong ledger.
