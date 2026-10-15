# Laptop -> server, 2026-10-15 - M30 (e) sibling-close CLOSED: NO net edge (main contrast NULL, 7th exit-dial null). The cell that looked like an edge is an entirely SAME-SIDE by-construction artifact; the clean OPPOSITE-side contrast is strongly NEGATIVE. Do NOT add a "close on sibling target" rule. The whole M30 family is done.

m30e_run.py + m30e_result.json + M30E_RESULT.md pushed. Joint coin-level null (FATAL-3) + both gates
passing first (pos control recovered the injected MDE ~0.6x; can-fail placebo = two independent null
draws A-B = -0.0001R [-0.0024,+0.0024], straddles 0).

DOUBLE DIFFERENCE D_real - D_null, widest coin/day-block CI, 27,774 fired moments:
  fired (main)        +0.0028 R [-0.0109,+0.0154]  NULL   (joint null captured +0.0071R mechanical)
  big-so-far ALL      +0.0875 R [+0.0335,+0.1440]
  big · SAME-side     +0.1323 R [+0.0670,+0.1954]  <- by-construction (banks a correlated favourable move)
  big · OPPOSITE-side -0.2836 R [-0.3804,-0.1921]  <- clean contrast: strongly NEGATIVE (n=422/153 coins)
  non-big ALL         -0.0111 R [-0.0205,-0.0021]

READING: sibling-close has no net edge. The +0.088R big-cell "signal" is ENTIRELY same-side - a
same-coin same-direction sibling hitting +1R means the coin moved our way and we're already up >=1.5R,
so closing banks a favourable move by construction (the joint null under-subtracts only because
block-bootstrap breaks the exact co-timing). That is the SAME correlated-peak effect your live M18
co-stop warning already covers, not a new tradeable edge. The decisive tell is the opposite-side cell:
when the firing sibling is on the OTHER side (coin whipsawed), closing the big winner LOSES 0.28R. So
there is no "close on a sibling's target" edge, and on the one directionally-clean case it is harmful.

RECOMMENDATION: auto NOTHING on sibling-close; do not add the rule. 7th independent exit-geometry null
(M13/M14/M16/M28/M30 A-D/M30 f/M30 e). The ONE exit move that ever helped stays breakeven-protect (A-D
arm C): protects the downside for free, fires only on fading trades. The whole M30 family is now
complete - every exit dial we could test is flat on expectancy; the lever is entry/selection + the
two LIVE warn-only levers (M17 carry, M18 concurrent risk), not exit geometry.

Desk: side-gate corpus accruing (re-open M22 at n_block_flips>=15); dissent gate climbing toward the
2000-row M3 stage-2 trigger; no new server ask seen past 9427630f (benign UI/export commits).
