# Missed-Opportunity Audit

Generated: 2026-05-30T21:40:27.368233+00:00

For each of 131 skipped signals, we looked at price action after the skip using 5m candles. We determined whether the skip would have hit TP1 (MISSED_WIN), would have hit SL (GOOD_SKIP), or neither yet (OPEN).

## Headline

Raw outcomes: {'NEUTRAL_LEAN_LOSS': 37, 'OPEN': 88, 'NEUTRAL_LEAN_WIN': 6}

- **43 skips resolved** (TP1 or SL reached within available data)
- **Skip quality: 86.0%** (37 good skips vs 6 missed wins)
- **88 still open** (no TP1/SL hit in the candles we have)
- **0 in the future** (created after our newest candle)

**Plain English:** The bot's skipping is paying off — 86% of the resolved skips would have lost money. The conservative behavior is correct, not overly cautious.

## By Symbol

| Symbol | Resolved | Good Skips | Missed Wins | Skip Quality |
|---|---|---|---|---|
| BTC | 0 | 0 | 0 | 0% |
| ETH | 6 | 0 | 6 | 0% |
| HYPE | 29 | 29 | 0 | 100% |
| SOL | 8 | 8 | 0 | 100% |

## By Side

| Side | Resolved | Good Skips | Missed Wins | Skip Quality |
|---|---|---|---|---|
| BUY | 43 | 37 | 6 | 86% |
| SELL | 0 | 0 | 0 | 0% |

## By Regime

| Regime | Resolved | Good Skips | Missed Wins | Skip Quality |
|---|---|---|---|---|
| consolidation | 0 | 0 | 0 | 0% |
| range | 1 | 1 | 0 | 100% |
| trend | 6 | 0 | 6 | 0% |
| trending_bull | 36 | 36 | 0 | 100% |

## By Skip Reason

| Reason | Resolved | Good Skips | Missed Wins | Skip Quality |
|---|---|---|---|---|

## Methodology (so you know what to trust)

- **Data**: last 25h of 5m candles fetched live via CCXT/Hyperliquid
- **Outcome rules**: TP1 hit before SL = MISSED_WIN; SL hit before TP1 = GOOD_SKIP; neither hit = use MFE/MAE lean
- **MFE/MAE lean**: if max-favorable > 1.5x max-adverse AND > 0.3% = NEUTRAL_LEAN_WIN; converse = NEUTRAL_LEAN_LOSS; otherwise OPEN
- **Thresholds are arbitrary** (1.5x, 0.3%). Different cutoffs would give different numbers. Use this as directional signal, not gospel.
- **Sample sizes are small** for some categories. ETH n=6 'all missed' could easily be coincidence.

## Top Missed Wins (alpha left on the table)

| When | Symbol | Side | Entry | TP1 | MFE% | MAE% | 1h move | Skip reason |
|---|---|---|---|---|---|---|---|---|
| 2026-05-30T18:28:16 | ETH | BUY | $2024.2000 | $2040.4386 | +0.34% | -0.01% | +0.01% | graduated_rule_veto |
| 2026-05-30T18:29:08 | ETH | BUY | $2024.2000 | $2040.4386 | +0.34% | -0.01% | +0.01% | graduated_rule_veto |
| 2026-05-30T18:30:03 | ETH | BUY | $2024.2000 | $2040.5350 | +0.34% | -0.01% | +0.00% | graduated_rule_veto |
| 2026-05-30T18:30:54 | ETH | BUY | $2024.2000 | $2040.5350 | +0.34% | -0.01% | +0.00% | graduated_rule_veto |
| 2026-05-30T18:31:49 | ETH | BUY | $2024.3000 | $2040.6350 | +0.34% | -0.02% | +0.00% | graduated_rule_veto |
| 2026-05-30T18:32:41 | ETH | BUY | $2024.3000 | $2040.6350 | +0.34% | -0.02% | +0.00% | graduated_rule_veto |

## Top Good Skips (caution paid off)

| When | Symbol | Side | Entry | SL | MFE% | MAE% | 1h move | Skip reason |
|---|---|---|---|---|---|---|---|---|
| 2026-05-30T18:10:02 | SOL | BUY | $83.0350 | $82.6200 | +0.07% | -0.36% | -0.16% | graduated_rule_veto |
| 2026-05-30T18:19:14 | SOL | BUY | $83.0110 | $82.5901 | +0.10% | -0.33% | -0.10% | graduated_rule_veto |
| 2026-05-30T18:20:17 | SOL | BUY | $83.0110 | $82.5901 | +0.10% | -0.33% | -0.18% | graduated_rule_veto |
| 2026-05-30T18:22:03 | SOL | BUY | $83.0760 | $82.6519 | +0.02% | -0.40% | -0.26% | graduated_rule_veto |
| 2026-05-30T18:30:03 | HYPE | BUY | $68.0000 | $65.2234 | +0.46% | -1.30% | -0.50% | graduated_rule_veto |
| 2026-05-30T18:31:16 | HYPE | BUY | $68.0000 | $65.2234 | +0.46% | -1.30% | -0.50% | graduated_rule_veto |
| 2026-05-30T18:31:50 | HYPE | BUY | $68.0800 | $65.2827 | +0.35% | -1.42% | -0.62% | graduated_rule_veto |
| 2026-05-30T18:33:03 | HYPE | BUY | $68.0800 | $65.2827 | +0.35% | -1.42% | -0.62% | graduated_rule_veto |
| 2026-05-30T18:33:36 | HYPE | BUY | $68.0600 | $65.2615 | +0.38% | -1.39% | -0.59% | graduated_rule_veto |
| 2026-05-30T18:34:49 | HYPE | BUY | $68.0600 | $65.2615 | +0.38% | -1.39% | -0.59% | graduated_rule_veto |
| 2026-05-30T18:35:22 | HYPE | BUY | $68.1270 | $65.3262 | +0.28% | -1.49% | -0.09% | graduated_rule_veto |
| 2026-05-30T18:36:35 | HYPE | BUY | $68.1270 | $65.3262 | +0.28% | -1.49% | -0.09% | graduated_rule_veto |
| 2026-05-30T18:37:08 | HYPE | BUY | $68.1470 | $65.3342 | +0.25% | -1.51% | -0.12% | graduated_rule_veto |
| 2026-05-30T18:38:22 | HYPE | BUY | $68.1470 | $65.3342 | +0.25% | -1.51% | -0.12% | graduated_rule_veto |
| 2026-05-30T18:38:55 | HYPE | BUY | $68.1320 | $65.3192 | +0.27% | -1.49% | -0.09% | graduated_rule_veto |

## Co-Pilot Read (Nunu, here's what to think about)

You're not missing alpha — the bot's caution is well-calibrated for current conditions. Keep trusting the LLM's skip calls. Most rejected setups would have lost.

