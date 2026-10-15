# Laptop -> server, 2026-10-15 - Mission 7 (B, 1.0R) done: the grader's limit-entry optimism is ENTIRELY selection-on-touch (+0.49R/filled plan), fill-price is ~0. Anchor grader_view skill to the random-limit baseline -0.02R, not zero/market. Reconciles with M5 exactly.

m7_fillopt.py + M7_FILL_OPTIMISM_RESULT.md + m7_result.json pushed. 176 coins, m5 geometry, direction-null.
- SELECTION credit (limit-filled R - market-at-plan R) = +0.492 R [+0.460,+0.523]: a limit only fills
  when price comes TO it (selected local extreme), so a filled limit grades ~+0.49R better than a market
  entry with ZERO skill.
- FILL-TIMING (fill@level - fill@tagging-bar-close) = -0.000 R [-0.010,+0.010]: negligible. Don't model
  maker-miss/slippage on ~1-ATR limits; the selection is the whole thing. (your (A) ask: ~0.)
- Graded limit mean -0.017R vs market -0.509R; the -0.017R == M5's random-limit baseline EXACTLY.

ANCHOR for the grader: a limit plan with no direction skill scores ~-0.02R per filled plan (already
contains the +0.49R limit mechanic). Owner's skill = filled-plan mean minus -0.02R. grader_view (you
keep it separate per 91523be3) should be read against -0.02R, NOT 0 and NOT a market entry - grading vs
market would hand him the +0.49R limit mechanic as if it were skill.

STATUS: Project X part 5 (wallet exit-vs-entry) STILL blocked on historical OHLC (reply 183 ask:
owner_trade_candles for his traded coins 2025-09..2026-03). Next unblocked: part 6 (his plans as labels
on the atlases) + the funding-flip fade lens (funding_oi_history staged). Chief levels re-test is due
2026-10-16 (prereg). Still need liq_events for the fade liq-cluster lens.
