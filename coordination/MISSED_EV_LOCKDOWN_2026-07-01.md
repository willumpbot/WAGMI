# Missed-EV Lockdown — Robustness Test of the "LLM Regime-Skips Leave Huge EV" Claim — 2026-07-01

**Source:** `bot/data/llm/counterfactual_resolved.jsonl` snapshot 2026-07-01 ~21:55 UTC — 39,082 resolved records (file grew from the 36,541 in the prior audit), 2026-05-30 → 2026-07-01.
**Claim under test** (from `EV_AND_MISSED.md`): LLM-agent regime-skips (`[MA] regime=...`) had 94–100% would-win rates and +6–12% avg moves → "#1 lever is loosening the agent's regime caution."

## VERDICT: **ARTIFACT.** One window, one direction. Do NOT loosen the agent's regime caution based on that audit.

The killer number: **W1 (May30–Jun05) skipped SELLs: n=1,348, 75% would-win, +5.68% avg. Every other week×side cell: win% 0–19%, avg −1.33% to +0.25%.** 80% of ALL positive missed PnL across 3,821 regime-skip records comes from Week-1 skipped SHORTS — i.e., the bot skipped shorts during the early-June crash (BTC 82K→60K). That crash already happened.

## (a) Split by calendar week — does the edge persist?
[MA] regime-skips, all regimes pooled:

| week | n | would-win% | avg hypPnL |
|---|---|---|---|
| **W1 May30–Jun05** | 1,749 | **59%** | **+3.54%** |
| W2 Jun06–12 | 1,072 | 16% | −0.26% |
| W3 Jun13–19 | 614 | 11% | −0.59% |
| W4 Jun20–26 | 235 | 6% | −0.53% |
| W5 Jun27–Jul01 | 151 | 14% | −0.06% |

**No. It exists in exactly one week and is negative-to-flat in all four subsequent weeks.** Post-W1 pooled: n=2,072, ~12% win, ~−0.4% avg — the regime-skips have been *correctly* skipping losers for the last 3.5 weeks.

Per regime family (the prior audit's headline rows):
- `high_volatility`: **699 of 711 records (98%) are W1** (W1: 54% win +3.07%; W2: 0% win −3.16%). The category barely exists outside the crash week.
- `trending_bear`: 159/182 in W1 (94% win +4.55%); W3: 13% win.
- `consolidation`: W1 62% win +4.21% → W2–W5: 7–17% win, −0.96% to +0.20%.
- `range`: W1 55% win +3.74% → W2–W5: 2–15% win, −0.54% to +0.14%.

The prior audit's "94–100% win" rows were per-exact-reason-string slices of W1.

## (b) Split by direction of skipped signal — symmetric or one-sided?
| week | skipped LONGS (BUY) | skipped SHORTS (SELL) |
|---|---|---|
| **W1** | n=401, **2% win, −3.67%** | n=1,348, **75% win, +5.68%** |
| W2 | n=513, 19% win, +0.25% | n=559, 13% win, −0.74% |
| W3 | n=165, 6% win, −1.33% | n=449, 13% win, −0.33% |
| W4 | n=140, 1% win, −0.47% | n=95, 12% win, −0.63% |
| W5 | n=116, 18% win, +0.24% | n=35, 0% win, −1.07% |

**Entirely one-sided.** The "missed EV" = skipped SHORTS during a melt-DOWN (mirror image of "skipped longs during a melt-up"). In the same week the agent also skipped 401 longs that would have lost −3.67% avg — the regime-skip gate was simultaneously saving money on the other side. After W1, skipped shorts are net losers in every week.

## (c) Control group — confidence-floor skips per window
| week | n | win% | avg hypPnL |
|---|---|---|---|
| W1 | 412 | 2% | −0.53% |
| W2 | 0 | — | — |
| W3 | 1,310 | 8% | −0.44% |
| W4 | 10,025 | 12% | −0.23% |
| W5 | 16,486 | 3% | −0.53% |

Control behaves as expected: **net-negative in every window, both sides** (worst cell: W3 BUY −1.14%; best cell: W4 SELL −0.10%, still negative). The data is sane; the instrument works. The regime-skip anomaly is real *in the data* — it just isn't a repeatable edge.

## Additional caveats that further weaken the original claim
- **Autocorrelation/bursts:** the 3,821 regime-skip records collapse into only **672 unique symbol-hours** (max burst: 123 records for SOL in the single hour 2026-06-03 05:00). Effective independent sample in W1 is a few hundred episodes of the same one-way move, not 1,749 observations.
- **HYPE poisons even the pooled view:** by symbol, HYPE regime-skips are 16% win / −1.23% pooled — skipping HYPE was right even in W1's bear market.
- The counterfactual resolution window (med 42 bars) means W1 "+6–12%" figures ride the full crash leg — unattainable with real TP/trailing logic.

## What survives, if anything
Only a conditional, already-known statement: *in a confirmed strong trend (ADX>~50 trending_bear), continuation signals in trend direction should not be regime-skipped.* That is the same lesson as the thesis-grading pass (best theses = high-ADX continuation shorts). It is a **regime-conditional rule, not a general "the agent is too cautious" rule**. Post-W1, the agent's regime-skips have been correct ~88% of the time.

## Action implication
1. Keep confidence floors as-is (still doing their job, every window).
2. Do NOT loosen `[MA]` regime-skips globally — since Jun 6 they have net-SAVED money.
3. If anything, encode the narrow version: allow trend-direction continuation entries when regime=trending_bear/bull with high ADX confidence — and validate that on fresh forward data first (per the backtest-before-adding rule).
4. Update/annotate `EV_AND_MISSED.md` — its headline table should not be acted on as written.
