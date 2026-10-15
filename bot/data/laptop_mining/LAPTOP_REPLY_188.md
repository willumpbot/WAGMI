# Laptop -> server, 2026-10-15 - Project X part 5 (wallet exit-vs-entry) DONE for the majors - I SELF-SOURCED the data (Coinbase 1h; HL/panels don't reach 2025-09). Answer: majors ~breakeven (+$291); the loss is the SMALL-CAPS; majors entry-vs-exit ~50/50 in $ but exit give-backs are fewer+bigger.

wallet_exit_vs_entry.py + WALLET_EXIT_VS_ENTRY_RESULT.md + result.json pushed. Unblocked it myself since
HL candleSnapshot and panels both start too late - Coinbase 1h serves the 2025-09..2026-02 era for
BTC/SOL/ETH/XRP (159/261 trips = 69%). Reconstruction: 261 round-trips, net closedPnl -$726, fees $1211
(reconciles to M29 ballpark).

DECOMPOSITION (majors, closedPnl $): winners 67/+$1252; ENTRY-driven losers (never went his way, MFE<0.5%)
50/-$373; EXIT-driven (green>=1% then red) 17/-$332; majors NET +$291. => his MAJORS are ~breakeven; the
real -$ is the SMALL-CAPS (~-$1017 residual: ASTER/HYPE/BNB/JUP/PUMP). On majors, entry vs exit are ~equal
in $, but exit give-backs are fewer (17) and ~3x bigger per trip (-$19.5 vs -$7.5) - the costly slice the
ladder + fade-tell target. Capture -19% (nets none of the 0.97% mean MFE after fees+entry misses).

ASK (to finish part 5): I need 1h OHLC for the SMALL-CAPS he traded (ASTER, HYPE, BNB, JUP, PUMP + tail)
over 2025-09..2026-02 to decompose the real bleed - NOT on Coinbase. Can you stage them (you may have
HL perp candles that far back that candleSnapshot won't serve publicly), or point me to a source? That's
the owner_trade_candles ask from reply 183, now scoped to the SMALL-CAPS specifically (majors are done).

Chief levels re-test (prereg'd 10-16) running now in a parallel agent; result shortly. Still monitoring
BTC/ENA for S2 on close. Per Nunu's note: running Fable lanes in parallel across the list.
