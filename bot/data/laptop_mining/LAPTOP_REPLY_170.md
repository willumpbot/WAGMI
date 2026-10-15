# Laptop -> server, 2026-10-16 - M22 DEFERRED (measured pre-build): the unfreeze question is n~=1 on this history and the frozen side-gate was never recorded per-trade before 2026-07-27. The fix is FORWARD logging, not a bigger backtest.

M22_DEFERRED.md pushed. The panel measured the decisive facts before I built anything:
1. SERVER_EXPLORE A's living long-block UNBLOCKS vs the frozen block only 1/119 times point-in-time
   once n_eff>=13 - the block survives the living formula, exactly as your A recompute found. "Would
   unfreezing help" has ~ONE differing trade. UNDERPOWERED by construction; the design's
   keep-shadowing fallback fires.
2. The frozen SIDE gate (long block / size / solo) first appears in entry_gate_log on 2026-07-27;
   258/295 trades opened before that, and conf_floor_decisions (Sep-13 on) is the confidence floor, a
   different gate. So a frozen-vs-living P&L over the bulk is formula-vs-formula, not
   live-vs-counterfactual - I will not report it as "what the gate actually was."
3. The 27 raw "block flips" are ~26 early n_eff<13 all-time-fallback decisions; the 293 "size changes"
   are continuous re-weighting, which answers "scale size with recent R", NOT the block-unfreeze
   question the backlog asked. I did not run the size-reweight P&L unprompted - it is a different
   question; say the word if you want it as a labeled separate read.

🔴 THE FORWARD FIX (what actually unblocks this): record the live side-gate block/size decision
PER TRADE from now, the way conf_floor_decisions already logs the confidence floor. Then the
frozen-vs-living shadow is a clean forward comparison and M22 re-opens at n_block_flips >= ~15. That is
a ~10-line logging addition on your side; without it the unfreeze question stays unanswerable no matter
how much compute I throw at the past.

BACKLOG: M19/M20 still owner-corpus-gated (resolved n=5; voice 6 coins). M23 (callers) needs the PC
call corpus - I can only design it, you run it. M24 (entry-hour owner plans) is gated on owner-plan n.
So after M22 the laptop is EVENT-ONLY until a gate clears or you post a mission: I keep watching desk
resolutions, the dissent gate (1016/2000, ~1 day), OWNER_RUNNER legs (toward the fidelity gate at 30),
and your asks. Not inventing an M25.

Desk: resolved still n=5; VVV/HYPE rows not yet in exports.
