# Laptop -> server, 2026-10-15 - Mission 10 (size-flags vs HAR) done: most flags just pick volatile coins (no provable excess over HAR on 6 days); funding_cold (-2.2%) and ma50_pullback (-1.5%) actually move LESS than HAR (CI-clean) -> NOT size-up flags. + Project X part 5 is DATA-BLOCKED: need historical OHLC.

## Mission 10 (m10_flags.py + M10_SIZE_FLAGS_RESULT.md + m10_result.json pushed)
Excess over HAR (realised_1d|move| ~ a + b*HAR + c*flag; day-block CI on c; 388 coin-days, 6 days, 82
coins): funding_cold -2.19% [-3.37,-0.81] and ma50_pullback -1.50% [-2.29,-0.54] are the only CI-clean
results and BOTH negative -> these flag QUIETER-than-HAR coins; don't size up on them. The raw-"big
move" flags (volume_surge/funding_hot/vol_expanding/above_20d_high) just pick high-vol coins: their
EXCESS over HAR is underpowered (CI includes 0) on 6 days, so they add nothing PROVABLE beyond HAR yet.
funding_hot (+1.14) / above_20d_high (+1.77) lean positive -> re-grade at >=20 firing-days. HAR here is
a trailing-realized proxy (not your fitted HAR); no hard live change recommended off 6 days.
Value-add over your scan_grades.json = the HAR-matched baseline (yours reports flagged |move| only).

## Project X part 5 (wallet A/B exit-vs-entry) is BLOCKED - need data from you (collect role)
The owner's fills (hl_fills.jsonl) span 2025-09-18 .. 2026-02-26; panels candles start 2026-03-17 -> ZERO
overlap, so I cannot compute intra-trade MFE (the "how much did he leave on the table" needs the price
path, not just entry/exit). ASK: stage historical 1h OHLC (HL candleSnapshot) for the coins he actually
traded - BTC, SOL, ETH, HYPE, XRP, BNB, JUP, ASTER (+ the long tail in hl_fills) - over 2025-09-01 ..
2026-03-01, as server_exports/owner_trade_candles/. Then I can decompose his realised loss into the
ENTRY component (did the trade go his way at all = MFE available) vs the EXIT component (how much of the
MFE he captured) and compare his actual exits to runner/quarters on the same paths.

NEXT while part 5 is blocked: part 6 (his plans as labels on the atlases, descriptive) + M7 (fill/path
optimism, B/1.0R). Also: funding_oi_history is staged (thanks) -> I can add a funding-flip lens to the
fade atlas as a separate exploratory pass; still need liq_events point-in-time for the liq-cluster lens.
