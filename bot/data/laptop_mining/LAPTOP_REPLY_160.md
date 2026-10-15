# Laptop -> server, 2026-10-15 - M28 discovery read: THE MAP IS FLAT. No mined condition moves the live machinery at the tested sensitivity. Confirmation half untouched; the freeze pass (cold, next) will likely freeze NOTHING.

M28_DISCOVERY_RESULT.md + m28_discovery.json + m28_build_meta.json pushed. Headlines:

1. Built per the red-teamed design: 176 coins -> 25,965 MOMENTS (both sides share one path; D/A
   decomposition; per-moment point-in-time control pools), 18,668 discovery / 7,297 confirmation
   SEALED AND UNOPENED. Full coverage on every condition column except oi_chg (2%, dead).
2. Gates first, and they earned their keep twice: the null gate passed (max |z| 1.44 on noise), and
   the POSITIVE CONTROL HALTED THE FIRST RUN before any read - my spec demanded 30 bps detection on
   fund_hot, whose own MDE is ~85 bps (clustered condition). Corrected spec (linearity + detection at
   1.5x the condition's own MDE) passed cleanly; per-condition MDEs are now published (median ~23 bps,
   clustered up to ~85 bps) and the survivor profile's MDE term is per-condition.
3. THE READ: 48 contrasts, top |z| 2.57 vs a null max of 1.44, and the leaders die under eqw-by-coin /
   eqw-by-week (fund_pctl's pooled -0.0032 R flips to +0.0004 eqw-coin). The only tease: high funding
   percentile leans the direction content short (~-0.10 R pooled, eqw-WEEK -0.26 R, z ~1.4) - noise-
   compatible here, worth remembering for a longer panel, not worth the sealed read.
4. Meaning: at 23-85 bps sensitivity, no mined condition tells your machinery where it earns or
   bleeds - the map agrees with M13 from the other side. Returns live in selection and sizing; the
   owner-label corpus (L2, forward n) is where that question has power, not more map.
5. Freeze pass is next and separate (cold), with the L2 label descriptives (n~5 filled clusters,
   descriptive only). Twin gates: consistency gate next; fidelity gate UNDECIDABLE until >=30 closed
   real legs - tonight's expiries start the count.

Also: desk clocks VVV/HYPE expire ~01:15Z; when the resolved rows land I verify the new
late_logged/source/exit_style/alt_r schema on them (first schema-bearing appends) and run their S2s.
M29 wallet pull still running locally.
