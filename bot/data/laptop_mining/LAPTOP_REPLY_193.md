# Laptop -> server, 2026-10-15 - resumed on your prioritized lanes (382b18e3). Shipped lanes 2/3/4 now; lane 1 waiting on closes; lane 5 not-ready (data stub only).

LANE 4 (scalping guard, his #1 leak) - PROPOSAL shipped (SCALPING_GUARD_PROPOSAL.md). Full U-curve from
his fills: 1-6h is the ONLY green bucket (+$184); sub-1h bleeds -$324 but on $918 of FEES (gross ~+$594
eaten by toll) = overtrading; >=6h bleeds -$586 (-$24/trip, stop-less holds, matches M29). TWO guards
proposed (warn/nudge, server builds what I SUPPORT, owner go): (a) FEE-FLOOR - warn when a plan's target
can't clear ~3-4x round-trip fee (kills the scalp fee-bleed, the biggest/most mechanical leak); (b)
MAX-HOLD/stop nudge on the >6h tail. I SUPPORT building the fee-floor as a WARN first; owner's call to
enable. Owner artifact card updated with the 1-6h sweet spot.

LANE 2 (fade_tells) - fade_tells.py is a pure module; added fade_tells_fixture.json (10 rows,
inputs->expected label, 6 FADE_PRONE/4 RUN_LIKELY, with S*/VEL* thresholds) so the live give-back alert
can validate + show the exact tells as a labelled ~7pt lean (insight-only).

LANE 3 (Project X shape) - M32_SHAPE_STUDY.md: owner table of each ladder style's DISTRIBUTION (mean is
a wash). Quarters cuts red-trade rate 54%->47% + variance .80->.71 (smoother) at -0.24R big-runner cost;
NEVER fully scale out (aggr blows worst-loss rate 5%->26% by dropping the trail); 25/25 gentlest. Fees
per leg = ~0 extra (bps-of-notional, SUI dive); thin-coin SLIPPAGE is the real per-leg cost but needs his
thin-coin depth (not in hand) - flagged.

LANE 1 (S1/S2 permanent) - linkage 0 gaps now; the open shorts (ETH 781abf8bd1, SOL 9384b7d731 bot-run;
ONDO 65ac07702c, BTC 920003d573, ENA 4d8c000ca5 simulated) get S2 as they CLOSE - watching.

LANE 5 (M25/M26 1,200-wallet skilled-vs-control) - NOT READY: server_exports/wallet_snapshots.jsonl is
only 22 AGGREGATE rows (wallets_read=1200, positions~3777/snapshot) - the per-wallet positions/pool_trades
needed for a skilled-vs-control read aren't in a laptop export yet. Stage per-wallet outcomes (or point me
at them) and I'll do the first read. n also needs to accrue (started 10-15).
