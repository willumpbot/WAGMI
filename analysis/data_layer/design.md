# Data Layer Design

**Date:** 2026-06-02  
**Author:** laptop-claude  
**Status:** Active implementation — OI history shipped

---

## Audit: What the Bot Currently Fetches

| Data Source | Fetched? | Where | Update Frequency | Agents That Use It |
|-------------|----------|-------|------------------|--------------------|
| OHLCV 5m | ✅ | `fetcher.fetch_multi_timeframe` | Per tick | All strategies |
| OHLCV 1h | ✅ | `fetcher.fetch_multi_timeframe` | Per tick | RegimeTrend, MultiTierQuality |
| OHLCV 4h | ✅ | `fetcher.fetch_multi_timeframe` | Per tick | RegimeTrend |
| OHLCV 6h | ✅ | `fetcher.fetch_multi_timeframe` | Per tick | RegimeTrend |
| OHLCV 1d | ✅ | `fetcher.fetch_multi_timeframe` | Per tick | MonteCarlo |
| Funding rate | ✅ | `fetcher.fetch_funding_rate` | Every 60 ticks | Regime agent (via `_meta`) |
| OI current snapshot | ✅ | `fetcher.fetch_open_interest` | Every 60 ticks | Quant agent (via `_meta`) |
| OI history (rolling) | ❌ → ✅ | `multi_strategy_main.py` | Every 60 ticks | Quant agent, trade agent |
| Liquidation events | ❌ | Not fetched | — | None |
| Orderbook depth | ❌ | Not fetched | — | None |
| Mark price / basis | ❌ | Not fetched | — | None |
| BTC 1h (lead-lag) | ✅ | `fetcher.fetch_multi_timeframe` | Per tick (non-BTC) | Ensemble |

---

## OI History — Shipped

**Problem:** Agents receive only two OI snapshots: `open_interest` (current) and `open_interest_prev` (last tick). 
This gives a one-period delta but no trend context. Is OI expanding for 30 minutes (strong trend) or just a single-tick blip?

**Solution (in `multi_strategy_main.py`):**
- `_oi_history: Dict[str, deque]` — rolling deque of `{"ts": epoch, "oi": float}` dicts per symbol
- Capacity: 12 entries × 60-tick sampling interval ≈ 12 hours of history at 5m ticks
- On each OI fetch: append to deque, inject summarized history into `_meta["oi_history"]`
- Format: list of `{"ts": int, "oi": float}` sorted oldest→newest (agents can compute slope, momentum)

**What agents can do with it:**
- Compute OI 1h change, 4h change, 12h change
- Detect OI divergence (price rising, OI falling = weak trend)
- Detect OI expansion into a move (confirms directional conviction)
- Trade/Regime agents: add "oi_expanding" vs "oi_contracting" to regime context

---

## Liquidation Events — Planned (Medium Priority)

**Why it matters:** Liquidation cascades are the main driver of wick-to-stop scenarios. Knowing the liquidation level density around price would let the risk agent widen stops preemptively and let the trade agent skip entering just above a liquidation cluster.

**How to fetch:** Hyperliquid REST endpoint `/info` with `{"type": "liquidations"}` — no auth needed. Returns recent liquidations as `{symbol, side, price, size, time}`.

**Implementation plan:**
1. Add `HyperliquidFetcher.fetch_liquidations(symbol, lookback_minutes=60)` in `bot/data/fetchers/`
2. Call in `multi_strategy_main.py` alongside OI fetch (every 60 ticks)
3. Summarize: `{"recent_count": int, "recent_notional": float, "last_cascade_minutes_ago": int}`
4. Inject into `_meta["liquidations"]` for trade/risk agents

**Estimated effort:** 2h

---

## Orderbook Depth — Low Priority

**Why it matters:** Slippage estimate and support/resistance. Large bid walls below price = support. Large ask walls above = resistance.

**Risk:** Orderbook snapshots are stale by the time the next tick fires. Net benefit over ATR-based SR is marginal without streaming.

**Recommendation:** Defer until streaming websocket is implemented. Static REST snapshots add latency for marginal gain.

---

## Mark Price / Basis — Low Priority

**Why it matters:** Basis (mark vs index) > 0.5% = market is overheated. Negative basis = fear/deleveraging.

**Implementation:** Single field from `fetcher.fetch_mark_price()` — CCXT supports it. 3-line change.

**Recommendation:** Implement as part of funding rate enrichment (both are anti-trend signals).

---

## Implementation Priority

| Item | Effort | Impact | Status |
|------|--------|--------|--------|
| OI history (12h rolling) | 30 min | High — trend confirmation for quant/trade agents | ✅ Done |
| Mark price / basis | 1h | Medium — adds overheating signal | Pending |
| Liquidation events | 2h | High — reduces stop-hunt exposure | Planned |
| Orderbook depth | 4h | Low — marginal without streaming | Deferred |
