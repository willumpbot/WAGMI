# M28 SPLIT SEAL - written and hashed BEFORE any replay data was built or read (2026-10-15)

Per the owner's fishing guard ("many conditions = false finds") and the server's spec, the
discovery/confirmation split for the M28 map is fixed NOW, before m28 code exists:

- DISCOVERY population: ORIG17 coins (ARB AVAX BTC DOGE ENA ETH HYPE LINK NEAR PUMP SOL SUI UNI VVV
  WLD XRP ZEC) over ALL dates, PLUS all other coins on days with daykey < 20693 (2026-08-28, the
  panel's midpoint day at build time - recomputed as the actual median daykey of the built panel and
  recorded in the build meta; if the recomputed median differs, the RECORDED value governs and this
  seal is amended BEFORE any confirmatory read, never after).
- CONFIRMATION population: non-ORIG17 coins on days with daykey >= the recorded median. Read ONCE,
  after the discovery phase is written up and its candidate conditions are frozen in an amendment to
  this file (condition list + thresholds + predicted sign, each with its discovery-phase effect size).
- No quantity computed on the confirmation population may be inspected before that freeze. The twin-
  must-match-live gate and the random-entry control run on DISCOVERY data only until the freeze.
- LLM-decision rows (claude ideas, bot agent decisions) are excluded from replay entirely (model may
  remember outcomes) - forward-graded only.
- Owner decisions (plans, calls, watchlist adds, mentions) are LABELS on the map, never selection
  criteria for the split.
