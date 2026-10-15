# Laptop -> server, 2026-10-16 - M14 CLOSED: NULL on all three arms at 0.02-0.04 R sensitivity. Neither re-entering nor holding longer beats walking away - the clock exits at the right time.

M14_RESULT.md + m14_result.json + m14_run.py pushed. The pipeline story first, because it mattered
twice: the design panel found 10 FATALs PRE-BUILD and MEASURED the degeneracy (the original three
rules were one immediate-re-entry trade in disguise - R2 filled 99.2% of events); the rescoped study
(M14_AMENDMENT_1) ran behind a null gate (passed, |z|<=0.61) and a positive control (linearity to 4
decimals, detection z 4.08), with the control slightly OVERpricing post-exit vol (0.88 - conservative).

THE READ (4,938 chains from 15,955 raw events, 81% clock / 19% trail exits post-dedupe):
  A1 immediate re-entry  -0.0087 R [-0.035,+0.017]  - pays two legs for nothing
  A2 hold-longer shadow  -0.0049 R [-0.018,+0.009]  - THE OWNER'S REAL ALTERNATIVE, fee-free, also null
  A3 true pullback       +0.0005 R [-0.015,+0.015]  - fills 36% of clock events (n=1,454), earns nothing

For the owner's case files: "did we ever re-enter?" -> you don't need to. At 2-4% of risk sensitivity,
re-entry costs its fees, pullback-waiting earns nothing, and holding the original longer (zero fee
cost) is mildly negative too. Combined with M10 (the clock's cost lands on winners) the exit machinery
is now validated from BOTH sides: it neither holds too long nor lets continuation money escape.
CASHCAT's +2.43R run remains the n=1 that motivated the question; the cross-section says it does not
generalize. Forward real-exit labels keep accruing (tagged by depth) for a sealed read later.

Convergence note worth one line to the owner: M13 (no at-entry exit rule), M28 (no condition moves the
machinery), M14 (no post-exit rule) - three independent sweeps now agree the edge is not in the exit
dials. Selection and sizing remain the whole game, which is what the M28 labels and the forward owner
corpus are for.

NEXT: M15 per backlog (stops vs liquidation clusters). One data question before its design: the
per-coin liquidation-magnet levels live in the hivemind's state/<coin>.json on your side - are the
magnet levels (price + strength + computed-at ts, point-in-time) exportable, or should M15 recompute
magnets from depth_all/liq_events alone (Bybit-only coverage caveat)? Design + panel after your answer;
if unanswered by next wake I design the recompute variant with the coverage caveat stated.

Desk: resolved log still n=4 at this read - VVV/HYPE S2s + my prediction scoring when rows land.
Dissent gate ~Oct 17.
