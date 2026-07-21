"""Phase 0.4-B close pipeline: TradeClosed frozen event, durable
close_outbox, and the tiered CloseBus dispatcher.

BUILT + UNIT-TESTED IN ISOLATION ONLY (see spec04.md section (3), Phase B).
Nothing in this package is imported/called by any live code path yet --
the god-block in multi_strategy_main.py remains the sole authoritative
close path until Phase D (caller migration) / Phase E (flip). Importing
this package must never change any live behavior.

Modules:
  trade_closed.py  -- the frozen TradeClosed event + LegKind enum.
  close_outbox.py  -- append-only durable delivery log (data/close_outbox.jsonl).
  close_bus.py      -- tiered dispatcher (CloseBus, DeliveryReport, AppliedStore).
"""

from __future__ import annotations

from core.close_pipeline.trade_closed import LegKind, TradeClosed

__all__ = ["TradeClosed", "LegKind"]
