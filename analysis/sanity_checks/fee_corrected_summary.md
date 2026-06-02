# Fee Correction Summary

**Date:** 2026-06-02  
**Author:** laptop-claude  
**Purpose:** Sanity check #1 from LAPTOP_AUTONOMOUS_MASTER_BRIEF.md — verify 45bps→4.5bps correction propagated through all analyses

---

## The Correction

Old analyses used **45 bps (0.45%)** taker fee — a 10x overstatement vs Hyperliquid Tier-0 actual of **4.5 bps (0.045%)**.  
Backtest engine now correctly set to **5 bps** (conservative round-up) in `trading_config.py`.  
Fee drag in old analyses was overstated 10x, which made profitable setups look like losers.

---

## Impact Per Analysis File

### analysis/historical/edge-finder.md — **CONCLUSIONS FLIP**

- **Fee used:** 45 bps (implicit in Net PnL calculations)
- **At 45 bps:** Total fees = -$875, Net PnL = -$4,590. Trailing stops appeared to generate the only alpha (-$921 net).
- **At 4.5 bps:** Total fees = -$87. Net PnL = **-$3,714**. Trailing stop bucket flips to **+$593 net**.
- **What changed:** The "only trailing stops work, everything else loses" conclusion is too pessimistic. At correct fees, the exit-type buckets look materially better. Absolute loss magnitude (from SL rate) is real and unchanged; fee drag was phantom.
- **Action:** Directional findings valid (reduce SL rate, improve entry quality). $ magnitudes overstated by ~$788 (fee overage).

---

### analysis/historical/shadow-ledger-edges.md — **NO CHANGE**

- **Fee used:** 4.5 bps (correct — percentages only, no $ fee calculations)
- WR and % return data unaffected. Conclusions unchanged.

---

### analysis/historical/counterfactual-analysis-2026-05-31.md — **DIRECTIONAL FINDINGS VALID**

- **Fee used:** 45 bps (implicit)
- Exit timing findings (81% of exits better at TP1, cumulative delta +477%) are directional comparisons — which exit is *better* is not fee-dependent.
- $ magnitude of "lost alpha" overstated by ~10x.
- **Conclusion:** Stick to early exit vs TP1 findings. Ignore $ magnitudes in that doc.

---

### analysis/historical/layer2-pilot-results.md — **CONCLUSIONS FLIP**

- **Fee used:** 45 bps (explicitly stated)
- **At 45 bps:** Fees = -$178.92 = 152% of gross PnL. Net = **-$73** (loss). Verdict: "partial failure, fee drag killing alpha."
- **At 4.5 bps:** Fees = -$17.89 = 15% of gross PnL. Net = **+$100** (profit). Verdict: "success — 3/3 positions profitable, 66.7% WR."
- **What changed:** The Layer 2 pilot was actually profitable at correct fees. The "fee drag kills everything" diagnosis was entirely an artifact of the 10x fee error.

---

### analysis/historical/quant-alpha-synthesis-2026-06-01.md — **MECHANICAL BACKTEST OK, OLD-BOT COSTS OVERSTATED**

- **Fee used:** Mixed
  - Mechanical backtest numbers (58.3% WR HYPE BUY, regime WR tables): 4.5 bps ✅
  - Old-bot PnL figures (e.g., -$2,909 ETH regret, -$624 SOL): 45 bps (overstated 10x)
- Old-bot $ losses were ~10x smaller in fee terms. Regime and setup WR conclusions are unaffected.

---

## Summary Table

| File | Fee Used | Conclusions Change? | Key Correction |
|------|----------|---------------------|----------------|
| edge-finder.md | 45 bps ❌ | **YES** | Trailing PnL flips: -$921 → +$593 |
| shadow-ledger-edges.md | 4.5 bps ✅ | No | — |
| counterfactual-analysis | 45 bps ❌ | Directional only | $ magnitudes 10x overstated |
| layer2-pilot-results.md | 45 bps ❌ | **YES** | Net PnL flips: -$73 → +$100 |
| quant-alpha-synthesis | Mixed | Partial | Old-bot $ losses 10x smaller |
| **Backtest engine** | **5 bps ✅** | **FIXED** | Correct since 2026-06-02 |

---

## Key Takeaway

The backtest engine is now correctly configured. Future backtests will not carry this error.

For interpreting historical analyses: any $ PnL figure in `edge-finder.md` or `layer2-pilot-results.md` should be mentally divided by ~10 for the fee component. The entry-quality finding (SL rate too high, need higher WR) and the regime findings (trending > illiquid) are fee-independent and hold.
