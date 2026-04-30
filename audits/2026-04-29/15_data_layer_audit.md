# Data Layer Audit — 2026-04-29

**Question:** `bot/data/` contains the data pipeline (fetcher, db, migrations, logs, persistence). Is it healthy, is anything dead?

**Headline:** **Data layer is in healthy shape — 9 of 11 Python modules wired, 2 orphan modules (telemetry, csv_logger).** The single `fetcher.py` is the workhorse (43 callers); `db.py` is heavily used (14 callers); `strategy_weights.py` is wired (11 callers). The orphans are similar to the agents/swarm pattern: substantive implementations sitting unused.

---

## Inventory

| Module | LoC | Callers | Status |
|---|---|---|---|
| `fetcher.py` | (large) | **43** | ✅ workhorse |
| `db.py` | 1,084 | **14** | ✅ active |
| `strategy_weights.py` | 327 | **11** | ✅ active (wired in §08) |
| `learning.py` | (mid) | **8** | ✅ active |
| `risk_log.py` | (small) | 3 | ✅ active |
| `ml_log.py` | (small) | 3 | ✅ active |
| `trade_log.py` | 86 | 3 | ✅ active |
| `migrations.py` | 188 | 2 | ✅ active (DB migrations) |
| `price_store.py` | 82 | 1 | ⚠️ thin wiring — verify fragile? |
| **`fetchers/telemetry.py`** | 250 | **0** | ❌ orphan |
| **`storage/csv_logger.py`** | 99 | **0** | ❌ orphan |

---

## ❌ Orphans (2)

### `data/fetchers/telemetry.py` (250 lines)

```python
"""
Telemetry: System-wide counters, rolling averages, and health status.

Tracks execution quality, safety violations, and performance metrics.
Exposed via /telemetry Telegram command with OK/WARN/CRITICAL thresholds.
"""

_THRESHOLDS_UPPER = {
    "avg_snapshot_age":            (8.0, 15.0),      # seconds
    "avg_slippage":                (0.3, 0.8),       # percent
    "avg_spread":                  (0.2, 0.5),       # percent
    "max_snapshot_age":            (15.0, 30.0),
    "max_slippage":                (0.5, 1.5),
    "stale_signals":               (5, 20),
    "execution_anomalies":         (3, 10),
    "circuit_breaker_triggers":    (2, 5),
    "llm_errors":                  (5, 15),
}
```

The docstring says "Exposed via /telemetry Telegram command with OK/WARN/CRITICAL thresholds." Searching:

```
$ grep -rn "/telemetry\|telemetry_command" bot/alerts bot/multi_strategy_main.py
(no matches for the Telegram command)
```

So the module exists, has detailed thresholds, was meant to be exposed via a Telegram `/telemetry` command, but the Telegram side was never built. **Same pattern as dormant agents (§09): 80% complete, last 20% never wired.**

**Recommendation:** wire to a `/v1/telemetry/health` endpoint in `bot/api_server.py` and surface in `/status` page (or as a new `/health` page). The thresholds are valuable. ~2-3 hours.

### `data/storage/csv_logger.py` (99 lines)

```python
"""
CSV Trade Logger with full dual-entry schema.

Logs every trade with all required fields from the execution spec:
- snapshot_entry, live_entry, effective_entry
- snapshot_timestamp, execution_timestamp, snapshot_age_seconds
- slippage_pct, spread_pct, liquidity
- human_copy_tradable, stale, outcome, state_path
- veto/downgrade reasons
"""

_TRADE_LOG = "data/logs/trades_enhanced.csv"
```

A "trades_enhanced.csv" with full dual-entry tracking — snapshot vs live entry prices, slippage/spread/liquidity, etc. **More detailed than the active `trades.csv` schema.**

The bot currently uses `trade_log.py` (86 lines, 3 callers, simpler schema). The enhanced version was clearly built to capture richer trade telemetry, but never replaced the simpler one.

**Trade-off:** the enhanced schema is much better for forensics (the §03 forensics page would benefit), but switching means migrating existing logs. Decide:

- (a) Migrate to enhanced schema — ~3-4 hours including data migration script
- (b) Archive `csv_logger.py` — accept the simpler schema is sufficient
- (c) Run both in parallel — the enhanced one writes alongside the simple one for some period

Probably (a) post-bot-restart. The slippage/spread fields would directly feed the §11 telemetry surface and §05 status page.

---

## Empty Subdir Stub: `data/fetchers/`

The directory exists with only `telemetry.py` and `__init__.py`. The naming `fetchers/` (plural) suggests the intent was per-exchange fetchers (e.g., `fetchers/hyperliquid.py`, `fetchers/binance.py`, `fetchers/kraken.py`).

The actual implementation is a single `data/fetcher.py` (singular, 43 callers) using CCXT's per-exchange routing internally.

So either:
- (a) The plural directory was created in anticipation of multi-exchange split, never populated.
- (b) The single fetcher works fine; the directory is misleading.

**Recommendation:** if cross-exchange aggregation is a goal (BLUEPRINT §6.5 mentions "cross-exchange leading indicators"), keep the directory and start populating. Otherwise rename `data/fetchers/` → `data/health/` (since telemetry is the only resident anyway). Low priority.

---

## `price_store.py` — Single-Caller Fragility

Only 1 caller. 82 lines. If that one call site disappears, the module becomes orphan. Worth either:

- Confirming the single caller is stable / documented
- Inlining if the abstraction isn't earning its keep

Not urgent, just worth noting. ~15 minutes to read and decide.

---

## What `db.py` Does (1,084 lines)

`db.py` is the second-largest data module after `fetcher.py`. 14 callers. Without reading it fully, the line count + caller count suggests it's the main persistence layer — probably SQLite.

Per `data-pipeline.md` rule (CLAUDE.md): "SQLite migrations must be backwards-compatible." `migrations.py` (188 lines, 2 callers) implements this.

**Recommendation:** spot-check `migrations.py` — verify it has versioning + rollback semantics. If absent, that's a future-failure waiting to happen. ~30 min spot-check.

---

## Trade Log vs CSV Log vs Trades.csv

The data layer has multiple trade-logging surfaces:

- `trade_log.py` (86 lines, 3 callers) — active, simple schema
- `csv_logger.py` (99 lines, 0 callers) — orphan, enhanced schema
- `bot/trades.csv` — the active output file (currently 1 line / header per §07.3.1)

Plus:
- `risk_log.py` (3 callers) — separate risk event log
- `ml_log.py` (3 callers) — ML-specific logging

The trade-logging surface is fragmented. **Worth consolidating** — one canonical writer that emits both structured rows (CSV/JSONL) and events (for risk_log/ml_log subscribers).

This isn't a bug, just complexity that's accumulated. ~3 hours to consolidate.

---

## Health Verdict per Module

✅ Wired and active: 9 modules
❌ Orphan (substantive but unwired): 2 modules
⚠️ Single-caller fragile: 1 module (`price_store.py`)

**Better signal than agents (§09: 57% dead) or tools (§11: 93% script-only).** Worse than skills (§13: 100% wired) but generally healthy.

---

## Combined Recommendations

1. **Wire `fetchers/telemetry.py`** (~2-3h) — high signal, directly surfaces in `/status`
2. **Decide on `csv_logger.py`** (~3-4h if migrating, ~5min if archiving) — the enhanced schema is genuinely better but switching has migration cost
3. **Rename or populate `data/fetchers/`** (~15min decision) — directory naming clarity
4. **Spot-check `migrations.py` for backwards-compat** (~30min) — risk insurance
5. **Consolidate trade-logging surface** (~3h, eventual) — reduces cognitive load
6. **Verify `price_store.py` single caller** (~15min) — fragility check

Total: **~6-8 hours** for the high-value items (1, 2, 4). Items 3 and 6 are housekeeping.

---

## What This Audit Confirms

The data layer mirrors the execution layer's pattern: **load-bearing modules are correctly wired, but supplementary modules accumulate as orphans**. Both layers contrast favorably with the agents/learning/tools layers where dead-code surface dominates.

The healthy pattern: small core (fetcher, db, migrations) + several active extensions (trade_log, strategy_weights, learning) + a few unwired aspirations (telemetry, csv_logger). Pruning the aspirations or wiring them is straightforward.

The data-pipeline rule in CLAUDE.md (`bot/data/**` requires backwards-compatible SQLite migrations) is well-targeted — if `migrations.py` enforces this, the layer is genuinely safe to evolve.
