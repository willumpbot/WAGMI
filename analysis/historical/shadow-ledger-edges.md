# Shadow Ledger Edge Audit
*Generated: 2026-05-30 | Source: historical/old-bot-pre-2026-04-23/shadow_ledger.csv*
*Note: Time-of-day patterns excluded per Nunu — found to be conditional noise, not a real edge.*

---

## Dataset Overview

| Metric | Value |
|---|---|
| Total shadow ledger rows | 6,121 |
| Resolved with numeric return | 1,330 |
| Date range (resolved only) | 2026-04-02 → 2026-04-21 (19-day window) |
| Unique (factor, symbol, side) combos | 13 |
| Factors tracked | regime_trend, bollinger_squeeze, multi_tier_quality |

**Caveat:** The resolved data covers only April 2–21, 2026 — a 19-day window. The hardcoded SHADOW_EDGES in `ensemble.py` were derived from 3,802 entries on April 15. Our resolved subset (1,330) is the portion of that window that had actual outcomes.

---

## Current SHADOW_EDGES in ensemble.py — Audit Result

Each hardcoded edge verified against the shadow ledger data:

| Setup | Code Says | Shadow Ledger n | Shadow Ledger WR | Shadow Ledger Avg Return | Verdict |
|---|---|---|---|---|---|
| ETH BUY + regime_trend | 100% WR, 135 samples → floor 0.90 | 135 | **100.0%** | +0.0078 | ✅ CONFIRMED. Rock solid. |
| HYPE BUY + bollinger_squeeze | 61.2% WR, 196 samples → floor 0.80 | 196 | **61.2%** | +0.0050 | ✅ CONFIRMED. Exact match. |
| SOL SELL + multi_tier_quality | 72.1% WR, 68 samples → floor 0.80 | 68 | **72.1%** | +0.0037 | ✅ CONFIRMED. Exact match. |
| SOL SELL + bollinger_squeeze | 72.1% WR, 68 samples → floor 0.80 | 68 | **72.1%** | +0.0037 | ✅ CONFIRMED. Exact match. |
| BTC BUY + regime_trend | 55.1% WR, 78 samples → floor 0.65 | 117 | **65.0%** | +0.0036 | ✅ IMPROVED — more data, better WR. Could upgrade floor from 0.65 → 0.72. |
| HYPE BUY + regime_trend | 80.0% WR, 40 samples → floor 0.72 | 63 | **87.3%** | +0.0030 | ✅ IMPROVED — n grew from 40 to 63, WR improved. Recommend floor 0.80. |

**All 6 current SHADOW_EDGES are confirmed valid. None have degraded.**

Two of the six (BTC BUY regime_trend, HYPE BUY regime_trend) now have more data and stronger numbers than when they were originally calibrated — worth upgrading their floors.

---

## Current SHADOW_BLOCKS — Audit Result

Desktop-claude has already removed all SHADOW_BLOCKS in the new architecture (blocks → informational). This audit is for historical reference:

| Setup | Code Rationale | Shadow Ledger n | Shadow Ledger WR | Shadow Ledger Return | Notes |
|---|---|---|---|---|---|
| SOL SELL + regime_trend | 0% WR / 149 samples | 149 | **0.0%** | total=-2.1921 | ✅ Block was correct — 0% WR, massive negative return sum |
| HYPE BUY + multi_tier_quality | 36.8% WR / 95 samples | 95 | **36.8%** | avg=-0.0026 | ✅ Block was correct — both low WR and negative avg return |
| ETH SELL + regime_trend | 23.1% WR / 65 samples | 65 | **23.1%** | avg=-0.0028 | ✅ Block was correct |
| SOL BUY + regime_trend | "75% WR trap: loses big" | 181 | **82.3%** | avg=+0.0116, total=+2.1081 | ⚠️ DATA CONTRADICTS BLOCK — see below |

### The SOL BUY regime_trend Mystery

The code comment says: *"75% WR trap: wins small, loses big (-0.48 sum)"*

Our shadow ledger shows: **82.3% WR, n=181, avg return +0.0116, total return +2.1081** — entirely positive.

Possible explanations:
1. The April 15 derivation used a different metric (net PnL after fees vs raw % return)
2. Market regime in early April 2026 was specifically favorable for SOL BUY, making this look better than it really is
3. The block was based on older data that got overwritten when newer data came in

**Given that desktop-claude already removed all SHADOW_BLOCKS from the new bot, this is moot for current architecture.** The LLM will now evaluate SOL BUY regime_trend on its own merits with this data as context.

---

## NEW EDGES — Not in Current SHADOW_EDGES

Two setups have n ≥ 40, WR ≥ 60%, and positive returns but are NOT in the hardcoded SHADOW_EDGES:

| Setup | n | WR | Avg Return | Total Return | Recommendation |
|---|---|---|---|---|---|
| **SOL BUY + multi_tier_quality** | 90 | **100.0%** | +0.0077 | +0.6920 | 🔥 ADD as SHADOW_EDGE (floor 0.90) — stronger than existing entries |
| **SOL BUY + bollinger_squeeze** | 100 | **90.0%** | +0.0067 | +0.6681 | 🔥 ADD as SHADOW_EDGE (floor 0.85) — very strong |

### Caveat on New Edges

Both new edges cover the April 2–21 window only. A 19-day window of 90–100% WR is extremely high and raises the question of whether this was a specific SOL bull phase rather than a durable edge. Desktop-claude should verify these against the live bot's data before hardcoding.

**Recommended approach for new bot:** Give the LLM the signal as context (`SOL BUY + multi_tier_quality: historically 100% WR on 90 samples, April data`), let the LLM weight it against current regime rather than hardcoding a floor. This is the LLM-first philosophy.

---

## Full Combo Table (All Resolved Data)

| Factor | Symbol | Side | n | WR | Avg Return | Total Return | Status |
|---|---|---|---|---|---|---|---|
| regime_trend | ETH | BUY | 135 | 100.0% | +0.0078 | +1.0489 | ✅ SHADOW_EDGE (0.90) |
| multi_tier_quality | SOL | BUY | 90 | 100.0% | +0.0077 | +0.6920 | 🆕 NEW EDGE — not hardcoded |
| bollinger_squeeze | SOL | BUY | 100 | 90.0% | +0.0067 | +0.6681 | 🆕 NEW EDGE — not hardcoded |
| regime_trend | HYPE | BUY | 63 | 87.3% | +0.0030 | +0.1919 | ✅ SHADOW_EDGE (0.72) — improved |
| regime_trend | SOL | BUY | 181 | 82.3% | +0.0116 | +2.1081 | ⚠️ Was BLOCKED, data positive |
| bollinger_squeeze | HYPE | BUY | 196 | 61.2% | +0.0050 | +0.9772 | ✅ SHADOW_EDGE (0.80) |
| regime_trend | BTC | BUY | 117 | 65.0% | +0.0036 | +0.4245 | ✅ SHADOW_EDGE (0.65) — improved |
| multi_tier_quality | SOL | SELL | 68 | 72.1% | +0.0037 | +0.2524 | ✅ SHADOW_EDGE (0.80) |
| bollinger_squeeze | SOL | SELL | 68 | 72.1% | +0.0037 | +0.2524 | ✅ SHADOW_EDGE (0.80) |
| multi_tier_quality | HYPE | BUY | 95 | 36.8% | -0.0026 | -0.2510 | ❌ Confirmed loser (was BLOCK) |
| regime_trend | ETH | SELL | 65 | 23.1% | -0.0028 | -0.1837 | ❌ Confirmed loser (was BLOCK) |
| regime_trend | HYPE | SELL | 3 | 0.0% | -0.0076 | -0.0229 | ❌ Too small sample |
| regime_trend | SOL | SELL | 149 | 0.0% | -0.0147 | -2.1921 | ❌ Catastrophic (was BLOCK) |

---

## Asks for Desktop-Claude

1. **Confirm new edges are in LLM context:** SOL BUY + multi_tier_quality (100% WR, 90 samples) and SOL BUY + bollinger_squeeze (90% WR, 100 samples) are not in the current SHADOW_EDGES. The LLM should know about these.

2. **Consider upgrading two existing edges:**
   - BTC BUY + regime_trend: n grew from 78→117, WR improved from 55%→65%. Floor 0.65 could be 0.72.
   - HYPE BUY + regime_trend: n grew from 40→63, WR improved from 80%→87.3%. Floor 0.72 could be 0.80.

3. **SOL BUY regime_trend needs investigation:** Data says +2.1 total return / 82.3% WR but it was hardcoded as a block. With blocks removed, the LLM will evaluate it on its own — just be aware the historical data is ambiguous here.

---

*Layer 1 complete. All analysis in analysis/historical/. Awaiting go-ahead for Layer 2 (agent replay, uses CLI quota).*
