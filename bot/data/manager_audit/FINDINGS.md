# Shadow-manager audit (2026-10-07)

**Headline: no shadow trade-level manager has shown skill.** Across 290 closed trades (net -$205, 63% losers), every shadow veto lands on trades that lose less often than the 63% base rate. The positive "$ if enforced" figures each come from 2–3 large losers. Best one-sided p = 0.33.

## What worked
- **Exit agent (live):** +$574 vs holding, 69% hit rate (n=29). Caveat: 28 of 29 are loser-cuts.
- **Trend-adjusted floor (live block):** -0.30% per blocked setup, CI excludes 0. The only block with clear value.
- **Old Overseer's recurring slice-level "avoid" calls:** 8 of 11 themes right, flagged in June, before the human audits found the same things.
  - Avoiding consolidation alone: +$474. Avoiding longs: +$247.
  - Wrong big calls: "block ETH/SOL shorts" would have given up $499; "focus on HYPE longs" lost $459.
  - 63% of its recommendations were too vague to test. 0 of 410 were applied.

## What was noise
- **Critic shadow veto:** n=42, 45% hit, +$11.
- **Quant reduce-size:** n=48, +$26. **Quant adjust-conf:** n=106, no skill.
- **volume_chop:** fires on nearly every scan. **R21d:** p=0.39.
- **R3 solo-divert:** harmful, -$14.
- **Confidence floor:** trimmed mean ≈ 0.
- **SIDE-FALLBACK clamp:** n=11, 82% hit. Insufficient but promising.

## Design rule for the new manager layer
Managers should emit **falsifiable slice rules** (side × regime × symbol), not per-trade opinions. A rule acts only after n≥13 forward trades in which its slice beats the other trades. Being negative in a losing book doesn't count.

## Data gaps
- `position_id` is filled on only 46 of 290 ledger rows.
- Quant and Critic shadow lines have no symbol or cycle id.
- `missed_trades_resolved.jsonl` is corrupt: 726 of 1,407 rows have impossible 1h prices.
- Test fixtures write into the live logs and counterfactuals.

Per-manager stats and the trade IDs behind each join are in `scorecard.json`.
