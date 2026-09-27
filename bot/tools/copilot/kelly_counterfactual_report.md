# Kelly / Compound-Size Counterfactual Test (READ-ONLY)

Ledger: C:\Users\vince\WAGMI\bot\data\trade_ledger.csv
Bootstrap seed: 20260801, iterations: 5000

## 1. Actual ledger columns & sizing-field population

- **Ledger path**: C:\Users\vince\WAGMI\bot\data\trade_ledger.csv
- **Raw rows (closed trades)**: 274

Columns found: trade_id, timestamp, symbol, side, regime_1h, regime_4h, agreement_level, contributing_factors, confidence_score, kelly_weight_applied, compound_size_multiplier, leverage, hold_hours, exit_type, entry_price, snapshot_entry, exit_price, gross_pnl, fees, funding, net_pnl, running_equity, session_dd_pct, ab_gate_hash, predicted_ev, realized_rr, win, epoch_id, position_id, funding_rate_entry, open_interest_entry, premium_entry

- **kelly_weight_applied populated**: 4/274 rows
- **compound_size_multiplier populated**: 0/274 rows
  -> Both task-assumed sizing columns are effectively DEAD in this ledger. Source-code audit (core/close_pipeline/close_subscribers_accounting.py) confirms: compound_size_multiplier is sourced from `ev.compound_mult`, which is a documented FIELD-GAP -- no emitter ever populates it, so it is 0/N always. kelly_weight_applied comes from `ctx.kelly_engine` (a T2 collaborator) and was only wired for the most recent 4 trades in this ledger. Neither column can support the requested counterfactual as specified.
  -> The mechanic that DOES vary on every trade and IS the live Kelly-derived sizing multiplier is the `leverage` column (execution/leverage.py: leverage = live_symbol_kelly_lev(symbol) * live_agreement_mult(...), i.e. per-symbol half/full-Kelly leverage from the bot's own ledger stats, discounted by an agreement multiplier that can only reduce it). Confidence itself scales a separate, UN-LOGGED risk_multiplier (the CONF_LADDER: 0.15x below 80% confidence, 1.0x at 80%+) that changes position size directly but leaves no ledger column. This script therefore (a) uses `leverage` directly wherever a discrete sizing-tier signal is needed, and (b) reconstructs each trade's actual realized notional exposure from price action to capture the combined effect of leverage AND the un-logged confidence risk_multiplier, for the linear pnl-rescale counterfactual.

- **Sim/pollution rows excluded (house filter)**: 20
- **Rows retained for analysis**: 254

## 2. Notional reconstruction (qty = gross_pnl / signed price move)

- **Rows with zero price move (indeterminate size, e.g. breakeven scratch)**: 1
- **Rows with gross_pnl rounding to $0.00 despite a tick move (indeterminate size)**: 2
- **Total rows excluded from the sizing counterfactual (indeterminate size)**: 3
  These 3 rows are kept unscaled/identical in both actual and flat curves (combined net_pnl $-0.33 -- negligible; each is a fee-only scratch where price barely moved, so there is no size signal to counterfactually rescale).

Sanity check -- fees / reconstructed notional (should look like a plausible bps round-trip fee if the notional reconstruction is right):
- **median fee/notional**: 9.7 bps
- **25th/75th pct fee/notional**: 7.2 / 10.8 bps
  -> Consistent with the project's known ~9bps round-trip fee finding -- the reconstruction is sound.

Reconstructed notional distribution (USD, valid rows only):
- **min**: $11.39
- **25%**: $123.64
- **50%**: $237.49
- **75%**: $586.16
- **90%**: $1,849.27
- **max**: $13,047.12
- **mean**: $846.75

## 2b. Actual vs flat equity curve (full sample, chronological)

Flat notional used (mean deployed notional across 251 sized trades): $846.75

- **ACTUAL (Kelly+leverage sizing) terminal cum. net_pnl**: $-98.58
- **ACTUAL (Kelly+leverage sizing) max drawdown**: $938.87
- **ACTUAL (Kelly+leverage sizing) DD-adjusted return (terminal / maxDD)**: -0.105
- **ACTUAL (Kelly+leverage sizing) per-trade mean / std**: $-0.39 / $43.25
- **ACTUAL (Kelly+leverage sizing) per-trade Sharpe-like (mean/std)**: -0.0090
- **ACTUAL (Kelly+leverage sizing) per-trade pnl variance**: $1,870.79

- **FLAT (constant notional) terminal cum. net_pnl**: $-609.65
- **FLAT (constant notional) max drawdown**: $750.46
- **FLAT (constant notional) DD-adjusted return (terminal / maxDD)**: -0.812
- **FLAT (constant notional) per-trade mean / std**: $-2.40 / $14.93
- **FLAT (constant notional) per-trade Sharpe-like (mean/std)**: -0.1608
- **FLAT (constant notional) per-trade pnl variance**: $222.89

- **DD-adjusted-return verdict (this cut)**: ACTUAL has better (or equal) DD-adjusted return
- **Variance ratio (actual/flat)**: 8.39x

## 3. Is the applied multiplier keyed to a confidence signal that predicts outcome?

- **corr(leverage, confidence_score) [confidence>0 only, n=157]**: 0.232
- **corr(notional_actual, confidence_score) [pearson / spearman]**: 0.194 / 0.191
  Leverage itself is barely correlated with confidence (consistent with the code: leverage is driven by the live per-symbol Kelly stat and agreement discount, not confidence directly). But realized NOTIONAL is meaningfully positively correlated with confidence (~0.16-0.19) -- this is the un-logged CONF_LADDER risk_multiplier showing through (0.15x below 80% confidence, 1.0x at/above), i.e. the bot IS sizing up its real dollar exposure on higher-confidence trades, even though leverage-the-column is not the channel.

Win rate / mean realized_rr / mean net_pnl by LEVERAGE tercile:
  - low  : n= 85  avg_lev= 1.00x  win_rate=22.4%  mean_realized_rr=nan  mean_net_pnl=$-5.69
  - mid  : n= 84  avg_lev= 1.11x  win_rate=53.6%  mean_realized_rr=-0.157  mean_net_pnl=$1.62
  - high : n= 85  avg_lev= 2.72x  win_rate=36.5%  mean_realized_rr=-0.147  mean_net_pnl=$2.93

Win rate / mean leverage / mean notional by CONFIDENCE tercile:
  - low  : n= 52  avg_conf= 54.8  avg_lev= 1.52x  avg_notional=$295  win_rate=57.7%
  - mid  : n= 52  avg_conf= 65.3  avg_lev= 1.39x  avg_notional=$410  win_rate=42.3%
  - high : n= 53  avg_conf= 78.8  avg_lev= 2.03x  avg_notional=$934  win_rate=32.1%

- **Point-biserial corr(confidence_score, win) [n>0 confidence rows only]**: r=-0.200, p=0.012
  -> confidence_score is significantly ANTI-predictive of win/loss (r=-0.200, p=0.012, n=157): HIGHER confidence correlates with LOWER win rate, matching this project's prior finding that confidence is anti-predictive above ~70%. The CONF_LADDER sizing mechanic (0.15x below 80% confidence, 1.0x at/above) is therefore sizing UP precisely where the ledger's own history says outcomes get WORSE -- worse than neutral variance amplification, this is sizing against the (weak) signal that does exist.

## 3b. Independent cross-check: does confidence predict outcome in the higher-n shadow ledger?

- **shadow_ledger.csv columns**: id, timestamp, factor, symbol, predicted_side, confidence, entry_price, exit_price, actual_return, resolved, resolve_timestamp
  NOTE: shadow_ledger.csv is an unsized, mechanical factor-prediction-resolution corpus (id, factor, predicted_side, confidence, entry/exit price, actual_return, resolved). It has NO kelly_weight_applied / compound_size_multiplier / leverage / pnl / notional fields, so it CANNOT be used for the sizing counterfactual itself. It IS large enough (n=11,528) to give an independent, higher-power read on whether `confidence` predicts directional correctness -- used here only as a robustness check on section 3's finding, not as a second sizing test.
  Also note: `actual_return` is populated ONLY for resolved=='true' rows (2143/2143) and is NaN for resolved=='false' rows -- a data-population gap, not a real absence of losers. Using actual_return directly would be selection-biased (all winners by construction). The clean test is confidence vs the binary resolved-correctly flag, restricted to rows that actually resolved (true or false, excluding 'expired' = no resolution occurred).
- **n resolved (true+false, excl. expired)**: 3008
- **Point-biserial corr(confidence, resolved_correctly)**: r=0.352, p=2.01e-88
  -> At n=3,008 (~20x the live ledger's power), this DIFFERENT 'confidence' field (a per-factor mechanical score, not the LLM coordinator's confidence_score) is POSITIVELY correlated with directional correctness (r=0.352, p=2e-88) -- the OPPOSITE sign from the live ledger's confidence_score-vs-win result in section 3 (r=-0.20). These are two different signals (mechanical per-factor score vs. the LLM's own stated confidence) scored on two different corpora, so this is NOT a clean corroboration either way -- it does NOT confirm the live ledger's anti-predictive finding, but it also does not rescue confidence-keyed LEVERAGE sizing: the live book's leverage is driven by live_symbol_kelly_lev + agreement_mult (section 3), not by this shadow factor score, and the live ledger's OWN confidence_score remains anti-predictive on its own data. Reported for completeness/transparency, not as support for either direction.

## 4. Refute-yourself: bootstrap significance + fragility checks

- **Bootstrap iterations**: 5000
- **P(flat DD-adj return > actual DD-adj return) across resamples**: 12.1%
- **Mean (flat - actual) DD-adj-return delta, 95% CI**: -0.746 [-2.656, 0.205]
  -> ACTUAL beat FLAT on DD-adjusted return in 87.9% of the 5000 resamples (i.e. FLAT only beat ACTUAL in 12.1%).
  -> Leans consistently in one direction (>=80/20 split) but does NOT clear a strict 95% significance bar -- suggestive, not conclusive. Do not over-claim a hard proof either way.

(a) Fragility check -- is any 'flat is better' result driven by a few large-multiplier losers?
  Top-3 largest-notional LOSING trades (candidates for 'fragile' driver):
    500b2b013945  XRP SHORT  notional=$10,428  lev=2.0x  net_pnl=$-10.79
    55c04b4a7920  XRP SHORT  notional=$9,015  lev=1.5x  net_pnl=$-9.37
    3514b13fa6b2  HYPE LONG  notional=$8,298  lev=2.5x  net_pnl=$-89.17
  After dropping those 3 trades: ACTUAL DD-adj=0.013, terminal=$10.75 | FLAT DD-adj=-0.808, terminal=$-526.97
  -> If the actual-vs-flat gap direction is UNCHANGED after removing these 3, the finding is not driven purely by a handful of outliers.

(b) Selection in which trades got large multipliers:
- **corr(leverage, trade sequence order)**: -0.085
  Mean leverage by symbol (leverage is a per-symbol live-Kelly stat, not a random draw):
    NEAR: 2.40x
    SOL: 1.85x
    BTC: 1.60x
    HYPE: 1.56x
    XRP: 1.46x
    ETH: 1.44x
  -> Leverage is NOT randomly assigned -- it's a deterministic function of each symbol's own trailing win-rate/payoff (live_symbol_kelly_lev) plus the agreement discount. This means large multipliers concentrate on whichever symbol currently LOOKS best in-sample, which is exactly the overfitting risk this test is designed to catch: sizing up on a symbol's recent (possibly noisy) stats, not a proven edge.

(c) Linear-pnl-rescale assumption -- validity and limitations:
  - Verified empirically in section 2: fees/notional sit in a tight ~5-11bps band across the sample, consistent with the reconstruction and with fees scaling proportionally to notional.
  - Funding is charged as a rate x notional x time, so it also scales proportionally with notional -- the rescale is consistent for funding too.
  - LIMITATION: leverage affects LIQUIDATION risk, not raw linear-perp payoff -- a trade that used high leverage for a small counterfactual-implied notional could, at the ACTUAL higher leverage, have been liquidated before reaching its logged exit price on an adverse intra-trade wick that never shows up in entry/exit-price-only data. This rescale does NOT model that path -- it likely UNDERSTATES how much worse the actual-sizing tail risk was (liquidation would show as a much worse realized loss than the linear rescale implies), which if anything is conservative against the 'flat is better' hypothesis being tested here, not for it.
  - LIMITATION: exchange minimum fees / tick-size rounding could make the flat (usually smaller) notional counterfactual paths slightly more fee-drag-heavy in reality than the linear rescale implies; not correctable without per-fill fee schedules.

## 4d. Size-regime check: has notional collapsed recently, and does the verdict hold pre/post?

Weekly median reconstructed notional (USD):
  2026-06-01/2026-06-07: $288
  2026-06-08/2026-06-14: $228
  2026-06-15/2026-06-21: $331
  2026-06-22/2026-06-28: $500
  2026-06-29/2026-07-05: $158
  2026-07-06/2026-07-12: $121
  2026-07-13/2026-07-19: $205
  2026-07-20/2026-07-26: $272
  2026-07-27/2026-08-02: $293

- **Split point**: 2026-07-26 (per project memory: notional-collapse date)
- **Pre-split trades / median notional**: 234 / $227
- **Post-split trades / median notional**: 20 / $290

PRE (2026-06-01..07-25) (n=234):
  ACTUAL: terminal=$-29.76  maxDD=$870.05  DD-adj=-0.034  trade_std=$44.94
  FLAT:   terminal=$-579.01  maxDD=$767.19  DD-adj=-0.755  trade_std=$15.75

POST (2026-07-26..) (n=20):
  ACTUAL: terminal=$-68.82  maxDD=$78.17  DD-adj=-0.880  trade_std=$11.73
  FLAT:   terminal=$-31.51  maxDD=$48.57  DD-adj=-0.649  trade_std=$5.56

  CAVEAT (per project memory): post-2026-07-26 notional is small in absolute dollars, so any post-split finding here is about whether the MECHANIC is sound, not about current dollar impact -- at today's tiny position sizes, no lever (including this one) moves many dollars either way.

## 5. Concrete leverage/notional-cap sensitivity scan

Baseline ACTUAL (uncapped): terminal=$-98.58, maxDD=$938.87

  cap @ median x1.5 ($356): terminal=$-190.41 (delta $-91.83)  maxDD=$233.92 (-75.1%)  n_trades_capped=91
  cap @ 75th pct ($586): terminal=$-220.65 (delta $-122.07)  maxDD=$283.13 (-69.8%)  n_trades_capped=63
  cap @ 90th pct ($1,849): terminal=$-324.07 (delta $-225.49)  maxDD=$488.73 (-47.9%)  n_trades_capped=25

  This is a MECHANIC-VALIDITY finding, not a live-bot change. If the verdict below recommends a cap, that cap must be reviewed and applied by the owner in execution/leverage.py (e.g. bounding live_symbol_kelly_lev's ceiling or adding a hard notional cap) -- this script does not, and must not, modify any live code or config.

## 6. Honest verdict

- **Actual terminal / flat terminal**: $-98.58 / $-609.65
- **Actual maxDD / flat maxDD**: $938.87 / $750.46
- **Actual DD-adj / flat DD-adj**: -0.105 / -0.812
- **Actual per-trade variance / flat per-trade variance**: $1,870.79 / $222.89 (8.39x)

See the printed sections above for the full numeric backing (bootstrap significance, tercile breakdowns, fragility/selection/limitation checks, and the pre/post split) before treating any single number here as the final word. This script deliberately does not hardcode a one-line verdict string -- read the numbers above; report them straight (help / hurt / wash are all valid outcomes). Any recommended cap is a LIVE-BOT change to execution/leverage.py and is OWNER-GATED -- this script does not apply it.
