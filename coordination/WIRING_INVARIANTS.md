# WIRING INVARIANTS — the seamless-wiring contract
Owner mandate (2026-07-02): "our wiring needs to be seamless and all-encompassing always."
These are the invariants that define it. The 3-hourly learning engine verifies them against live data every pass. A violated invariant is a P0 finding — journal loudly, add to MORNING_BRIEF.

## The contract
1. **Every close produces exactly one truthful ledger row.** Any path (SL/TP/trailing/exit-agent/force/liq-avoid) → one trades.csv row with real entry_type, confidence, regime, thesis link. No vanished closes, no orphan positions.
2. **Every partial is accounted.** Qty change without a fee/PnL/equity/TradeEvent record = violation.
3. **Every entry is honestly labeled.** EXPLORATION vs LLM_APPROVED as it actually happened; llm_action/llm_confidence recorded as returned. A coin-flip never wears an approval.
4. **Every thesis is graded.** Recorded with true side + symbol, graded against price at close/horizon. "Pending forever" = violation.
5. **One equity truth.** All consumers (CB, sizing, reports, heartbeat) read the same number. Divergence >1% = violation. (KNOWN-OPEN: dual trackers diverge ~$368 — fix pending owner #6.)
6. **No silent gates.** Nothing vetoes/filters/adjusts a decision without (a) a logged reason and (b) an owner-visible off-switch. (Quant Brain violated this for weeks — muted 2026-07-01.)
7. **Every collected dataset is either consumed or explicitly muted.** Data that's written but never read (209 ungraded theses, unused counterfactual dollars) = dormant capital = violation. Current consumption map lives in the RECALL-layer plan.
8. **State survives restarts.** Open positions, equity, learned rules reload exactly. (KNOWN-OPEN: restart wipes the book — fix pending owner #6.)
9. **Learning loops close.** Anything that records outcomes must be verified to actually fire (grader runs, veto dollars accrue, calibration table grows). A loop that never ran once = violation.
10. **Changes are validated before they're wiring.** Backtest/counterfactual first, flag-gated, reversible, committed with evidence. No additions during an open rewire.

## Status at adoption (2026-07-02)
Invariants 1-4, 6, 9: repaired tonight (spine fixes; live verification in progress on next closes).
Invariants 5, 8: KNOWN-OPEN, packaged as owner decision #6.
Invariant 7: RECALL layer is the follow-on build after 15-20 clean closes.
Invariant 10: standing discipline.
