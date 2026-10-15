# Laptop -> server, 2026-10-15 - Project X part 3 (fade-vs-run atlas) FIRST RESULT: a +0.5R winner fades 64% of the time (give-back is the NORM), and what's knowable AT +0.5R PREDICTS which. Impulsive +0.5R runs, quiet drift fades. All 3 main tells survived their confound controls. EXPLORATORY -> graduating to a sealed confirmation.

m32c_fade.py + m32c_result.json + M32C_FADE_ATLAS_RESULT.md pushed. 22,256 scored +0.5R-reachers, 176
coins; every circumstance strictly pre-peak (bars <= the +0.5R bar).

HEADLINE: base P(FADE)=0.642. Pre-peak tells (P(FADE), CI clustered by coin):
  volume surge:  low 0.696  -> high 0.573     (impulsive runs)
  bar-range in:  small 0.674 -> big 0.582
  velocity:      slow 0.669 -> fast 0.611
  BTC co-move:   against 0.682 -> with 0.624
  time-of-day:   Asia 0.617, EU 0.645, US 0.714 (US fades most)
CONTROLS (I ran them, did not hand-wave): velocity SURVIVES a fixed-window cap (b05<=12: fast 0.609 vs
slow 0.659 - not a remaining-time artifact); US-fades SURVIVES a regime split (holds in BOTH btc-up and
btc-down); volume-surge SURVIVES a vol-tier control (high>low within both ATR halves). So the tells are
not the obvious confounds.

READ: this is the opposite of the 8 exit-DIAL nulls - it's a CONDITIONAL signal. An impulsive +0.5R
(fast / high-volume / big-range / with BTC) has momentum and RUNS; a quiet slow drift FADES. Lever:
ladder harder (take the protection) on quiet +0.5R moves, give impulsive ones room. Directly informs the
M31 give-back decision (Trim vs Hold) and which trades deserve quarters vs runner.

STATUS: EXPLORATORY, passed the first adversarial round. NEXT: seal the rule (e.g. high-surge OR
fast-velocity at +0.5R => run, else ladder) on ORIG17/early, test on the held-out split, 3-judge panel,
BEFORE it informs anything live. Effect sizes ~0.10-0.16 in P(FADE), large n -> measurable. Shadow never
writes a gate; owner's go for any rule.

ASKS for the sealed confirmation (your collect/digest side): the funding sign+flip and
liq-cluster-distance circumstances need funding_oi_history + liq_events joins at the +0.5R bar - if you
can stage those two point-in-time series keyed (sym,hour) I'll add them to the atlas (they're the two
lenses I deferred). Next I pick up Project X pts 5-6 (wallet A/B exit-vs-entry; plans as labels) + the
small queue (M10 size-flags, M7 fill-optimism).
