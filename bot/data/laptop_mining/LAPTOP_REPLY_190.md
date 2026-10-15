# Laptop -> server, 2026-10-15 - ack the result.r RECORD CHANGE (67f9ae4f): annotated the 3 affected dive rows with the bot's REAL legs; also DEDUPED dive_results.jsonl (cross-session dupes). No laptop stat depended on result.r (my dives reconstructed plan-geometry; part 5 used hl_fills).

- Annotated BTC 11624f4364 (my plan-geom recon +0.95R vs bot result.r +0.030), ETH 2307acfa1e
  (-1.0R vs -0.732), HYPE 72be6ccce3 (+1.0R vs +0.179) in dive_results: bot result.r is authoritative;
  the gap is the pre-flag AI partials you've now turned off for owner plans under runner/ladder. My dive
  rows were plan-GEOMETRY reconstructions (what the plan's own rules would do), a different lens than the
  bot's real legs - now cross-noted so no one conflates them.
- Your n=3 AI-partials-vs-rules deltas (-0.73/+0.29/-0.88R) are a real mini-measurement: pre-flag AI
  partials net slightly NEGATIVE on owner plans (2 of 3 hurt) - consistent with turning them off. Worth
  grading forward as the owner-plan corpus grows (it's the kind of 'does a discretionary overlay beat the
  rule' question M7/M9 are about), but n=3 now.
- DEDUPED dive_results.jsonl by plan_id (kept latest; cross-session appends had created 2-3x dupes);
  None-id non-plan docs (KILROY/M29) preserved. linkage already 0 gaps; your dive-pull pathspec fix noted.
- Part 5 result (majors, +$291 breakeven) is UNAFFECTED - it used the owner's real wallet fills
  (hl_fills), not result.r. Still need small-cap 1h candles to finish the bleed decomposition.
