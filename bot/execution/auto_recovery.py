"""
Auto-recovery system for the WAGMI trading bot.

Handles:
1. Position state persistence — save/load full position manager state to JSON
2. Startup reconciliation — match persisted state with exchange, detect mismatches
3. Stale signal detection — skip cached signals if bot was down > 5 minutes
4. Graceful degradation — retry exchange API on startup, warn on unexpected positions

Flow on startup:
  1. Load persisted position state from disk (preserves SL/TP/trailing values)
  2. Fetch live positions from exchange
  3. Reconcile: merge persisted state with exchange truth
  4. Log downtime duration and skip stale signals
"""

import json
import logging
import os
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("bot.execution.auto_recovery")

# ── Constants ──────────────────────────────────────────────
_STATE_FILE = os.path.join("data", "position_state.json")
_HEARTBEAT_FILE = os.path.join("data", "heartbeat.json")
_STALE_SIGNAL_THRESHOLD_S = 300  # 5 minutes
_EXCHANGE_RETRY_INTERVAL_S = 30
_EXCHANGE_MAX_RETRIES = 5


# ── Heartbeat: track when bot was last alive ───────────────

def save_heartbeat(filepath: str = _HEARTBEAT_FILE) -> None:
    """Write current timestamp to heartbeat file. Call every tick."""
    try:
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        data = {
            "last_alive": datetime.now(timezone.utc).isoformat(),
            "pid": os.getpid(),
        }
        with open(filepath, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.debug(f"[HEARTBEAT] Failed to write: {e}")


def get_downtime_seconds(filepath: str = _HEARTBEAT_FILE) -> float:
    """Return how many seconds the bot has been down since last heartbeat.

    Returns 0.0 if no heartbeat file exists (first run).
    """
    try:
        if not os.path.exists(filepath):
            return 0.0
        with open(filepath) as f:
            data = json.load(f)
        last_alive_str = data.get("last_alive", "")
        if not last_alive_str:
            return 0.0
        last_alive = datetime.fromisoformat(last_alive_str)
        if last_alive.tzinfo is None:
            last_alive = last_alive.replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - last_alive
        return max(0.0, delta.total_seconds())
    except Exception as e:
        logger.debug(f"[HEARTBEAT] Failed to read: {e}")
        return 0.0


def should_skip_stale_signals(filepath: str = _HEARTBEAT_FILE) -> Tuple[bool, float]:
    """Check if cached signals should be skipped due to extended downtime.

    Returns (should_skip, downtime_seconds).
    """
    downtime = get_downtime_seconds(filepath)
    skip = downtime > _STALE_SIGNAL_THRESHOLD_S
    if skip:
        logger.warning(
            f"[RECOVERY] Bot was down for {downtime:.0f}s ({downtime/60:.1f}m). "
            f"Skipping stale cached signals."
        )
    elif downtime > 0:
        logger.info(
            f"[RECOVERY] Bot was down for {downtime:.0f}s ({downtime/60:.1f}m). "
            f"Within tolerance, signals OK."
        )
    return skip, downtime


# ── Position State Persistence ─────────────────────────────

def _position_to_dict(pos) -> Dict[str, Any]:
    """Serialize a Position object to a JSON-safe dict."""
    d = {
        "symbol": pos.symbol,
        "side": pos.side,
        "entry": pos.entry,
        "qty": pos.qty,
        "sl": pos.sl,
        "tp1": pos.tp1,
        "tp2": pos.tp2,
        "leverage": pos.leverage,
        "mode": pos.mode,
        "strategy": pos.strategy,
        "confidence": pos.confidence,
        "atr": pos.atr,
        "tp1_close_pct": pos.tp1_close_pct,
        "state": pos.state,
        "state_path": list(pos.state_path),
        "original_qty": pos.original_qty,
        "original_sl": pos.original_sl,
        "trailing_distance": pos.trailing_distance,
        "peak_price": pos.peak_price,
        "highest_price": pos.highest_price,
        "lowest_price": pos.lowest_price,
        "open_time": pos.open_time.isoformat() if pos.open_time else None,
        "close_time": pos.close_time.isoformat() if pos.close_time else None,
        "realized_pnl": pos.realized_pnl,
        "fees_paid": pos.fees_paid,
        "funding_costs": pos.funding_costs,
        "outcome": pos.outcome,
        "wallet_id": pos.wallet_id,
        "notes": pos.notes,
        "setup_type": pos.setup_type,
    }
    return d


def _dict_to_position(d: Dict[str, Any]):
    """Deserialize a dict back into a Position object."""
    from execution.position_manager import Position
    from execution.position_state import OPEN, CLOSED

    open_time = d.get("open_time")
    if open_time and isinstance(open_time, str):
        open_time = datetime.fromisoformat(open_time)
        if open_time.tzinfo is None:
            open_time = open_time.replace(tzinfo=timezone.utc)
    else:
        open_time = datetime.now(timezone.utc)

    close_time = d.get("close_time")
    if close_time and isinstance(close_time, str):
        close_time = datetime.fromisoformat(close_time)
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)
    else:
        close_time = None

    pos = Position(
        symbol=d["symbol"],
        side=d["side"],
        entry=d["entry"],
        qty=d["qty"],
        sl=d["sl"],
        tp1=d["tp1"],
        tp2=d["tp2"],
        leverage=d.get("leverage", 1.0),
        mode=d.get("mode", "spot"),
        strategy=d.get("strategy", ""),
        confidence=d.get("confidence", 0.0),
        atr=d.get("atr", 0.0),
        tp1_close_pct=d.get("tp1_close_pct", 0.5),
        state=d.get("state", OPEN),
        state_path=d.get("state_path", [OPEN]),
        original_qty=d.get("original_qty", d["qty"]),
        original_sl=d.get("original_sl", d["sl"]),
        trailing_distance=d.get("trailing_distance", 0.0),
        peak_price=d.get("peak_price", d["entry"]),
        highest_price=d.get("highest_price", d["entry"]),
        lowest_price=d.get("lowest_price", d["entry"]),
        open_time=open_time,
        close_time=close_time,
        realized_pnl=d.get("realized_pnl", 0.0),
        fees_paid=d.get("fees_paid", 0.0),
        funding_costs=d.get("funding_costs", 0.0),
        outcome=d.get("outcome", ""),
        wallet_id=d.get("wallet_id", ""),
        notes=d.get("notes", ""),
        setup_type=d.get("setup_type", ""),
    )
    return pos


def save_position_state(pos_mgr, filepath: str = _STATE_FILE) -> bool:
    """Persist all position manager state to JSON.

    Called after every state change (open, close, trailing update).
    Returns True on success.
    """
    try:
        positions_data = {}
        for symbol, pos in pos_mgr.positions.items():
            positions_data[symbol] = _position_to_dict(pos)

        state = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "position_count": len(positions_data),
            "positions": positions_data,
        }

        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

        # Write atomically: write to temp file then rename
        tmp_path = filepath + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(state, f, indent=2)
        # On Windows, remove target first if it exists
        if os.path.exists(filepath):
            os.remove(filepath)
        os.rename(tmp_path, filepath)

        logger.debug(
            f"[RECOVERY] Saved {len(positions_data)} position(s) to {filepath}"
        )
        return True
    except Exception as e:
        logger.warning(f"[RECOVERY] Failed to save position state: {e}")
        return False


def load_position_state(
    pos_mgr, filepath: str = _STATE_FILE
) -> int:
    """Load position state from JSON into pos_mgr.

    Only loads positions that are not already in pos_mgr.
    Returns number of positions loaded.
    """
    try:
        if not os.path.exists(filepath):
            logger.info("[RECOVERY] No position state file found (first run?)")
            return 0

        with open(filepath) as f:
            state = json.load(f)

        saved_at = state.get("saved_at", "unknown")
        positions_data = state.get("positions", {})
        loaded = 0

        for symbol, pos_data in positions_data.items():
            # Skip if already in pos_mgr
            existing = pos_mgr.positions.get(symbol)
            if existing and existing.state != "CLOSED":
                logger.debug(f"[RECOVERY] {symbol} already in pos_mgr, skipping load")
                continue

            # Skip closed positions
            if pos_data.get("state") == "CLOSED":
                continue

            try:
                pos = _dict_to_position(pos_data)
                pos_mgr.positions[symbol] = pos
                loaded += 1
                logger.info(
                    f"[RECOVERY] Loaded {symbol} {pos.side} from state file: "
                    f"state={pos.state} SL={pos.sl} TP1={pos.tp1} TP2={pos.tp2} "
                    f"trailing_dist={pos.trailing_distance:.4f}"
                )
            except Exception as e:
                logger.warning(f"[RECOVERY] Failed to load {symbol}: {e}")

        if loaded > 0:
            logger.info(
                f"[RECOVERY] Loaded {loaded} position(s) from state file "
                f"(saved at {saved_at})"
            )
        else:
            logger.info("[RECOVERY] No active positions to load from state file")

        return loaded

    except Exception as e:
        logger.warning(f"[RECOVERY] Failed to load position state: {e}")
        return 0


# ── Exchange Connection with Retry ─────────────────────────

def wait_for_exchange(
    exchanges: Dict[str, object],
    max_retries: int = _EXCHANGE_MAX_RETRIES,
    retry_interval_s: float = _EXCHANGE_RETRY_INTERVAL_S,
) -> bool:
    """Wait for exchange API to become reachable on startup.

    Returns True if exchange is reachable, False after max retries.
    """
    exchange = exchanges.get("hyperliquid")
    if exchange is None:
        logger.warning("[RECOVERY] No Hyperliquid exchange configured")
        return False

    for attempt in range(1, max_retries + 1):
        try:
            exchange.fetch_positions()
            logger.info(f"[RECOVERY] Exchange reachable (attempt {attempt})")
            return True
        except Exception as e:
            if attempt < max_retries:
                logger.warning(
                    f"[RECOVERY] Exchange unreachable (attempt {attempt}/{max_retries}): {e}. "
                    f"Retrying in {retry_interval_s}s..."
                )
                time.sleep(retry_interval_s)
            else:
                logger.error(
                    f"[RECOVERY] Exchange unreachable after {max_retries} attempts: {e}. "
                    f"Continuing with persisted state only."
                )
                return False


# ── Full Startup Recovery Orchestrator ─────────────────────

def startup_recovery(
    pos_mgr,
    exchanges: Dict[str, object],
    last_prices: Dict[str, float],
    risk_mgr=None,
    state_filepath: str = _STATE_FILE,
    heartbeat_filepath: str = _HEARTBEAT_FILE,
) -> Dict[str, Any]:
    """Full startup recovery sequence.

    Orchestrates:
    1. Downtime detection + stale signal check
    2. Load persisted position state from disk
    3. Wait for exchange (with retries)
    4. Reconcile persisted state with exchange positions
    5. Handle mismatches (orphans, phantoms)

    Returns a summary dict with recovery results.
    """
    from execution.reconciliation import reconcile_positions

    result = {
        "downtime_seconds": 0.0,
        "skip_stale_signals": False,
        "positions_loaded_from_disk": 0,
        "positions_reconciled_from_exchange": 0,
        "exchange_reachable": False,
        "phantoms_closed": [],
        "orphans_adopted": [],
        "errors": [],
    }

    logger.info("=" * 60)
    logger.info("AUTO-RECOVERY: Starting startup recovery sequence")
    logger.info("=" * 60)

    # Step 1: Detect downtime
    skip_stale, downtime = should_skip_stale_signals(heartbeat_filepath)
    result["downtime_seconds"] = downtime
    result["skip_stale_signals"] = skip_stale
    if downtime > 0:
        logger.info(f"[RECOVERY] Downtime detected: {downtime:.0f}s ({downtime/60:.1f} minutes)")
    else:
        logger.info("[RECOVERY] No previous heartbeat found (fresh start)")

    # Step 2: Load persisted position state
    loaded = load_position_state(pos_mgr, filepath=state_filepath)
    result["positions_loaded_from_disk"] = loaded

    # Step 3: Wait for exchange
    reachable = wait_for_exchange(exchanges, max_retries=_EXCHANGE_MAX_RETRIES, retry_interval_s=_EXCHANGE_RETRY_INTERVAL_S)
    result["exchange_reachable"] = reachable

    if not reachable:
        logger.warning(
            "[RECOVERY] Exchange not reachable. Running with persisted state only. "
            "Positions may be stale."
        )
        result["errors"].append("exchange_unreachable")
        return result

    # Step 4: Reconcile with exchange
    # The existing reconcile_positions only adds positions the exchange has
    # that pos_mgr doesn't. Since we loaded from disk first, disk positions
    # with matching exchange positions won't be overwritten (good — preserves SL/TP).
    try:
        reconciled = reconcile_positions(
            pos_mgr=pos_mgr,
            exchanges=exchanges,
            last_prices=last_prices,
            risk_mgr=risk_mgr,
        )
        result["positions_reconciled_from_exchange"] = reconciled
    except Exception as e:
        logger.warning(f"[RECOVERY] Reconciliation failed: {e}")
        result["errors"].append(f"reconciliation_failed: {e}")

    # Step 5: Detect phantoms (we think open, exchange says closed)
    exchange = exchanges.get("hyperliquid")
    if exchange:
        try:
            from execution.reconciliation import _PAIR_TO_SYMBOL
            raw_positions = exchange.fetch_positions()
            exchange_open = set()
            for raw in raw_positions or []:
                contracts = abs(float(raw.get("contracts", 0) or 0))
                if contracts <= 0:
                    continue
                pair = raw.get("symbol", "")
                symbol = _PAIR_TO_SYMBOL.get(pair)
                if symbol:
                    exchange_open.add(symbol)

            bot_open = {s for s, p in pos_mgr.positions.items() if p.state != "CLOSED"}
            phantoms = bot_open - exchange_open

            for symbol in phantoms:
                pos = pos_mgr.positions.get(symbol)
                if pos:
                    logger.warning(
                        f"[RECOVERY] PHANTOM: {symbol} tracked as {pos.state} but "
                        f"not on exchange. Marking as CLOSED (reconciliation)."
                    )
                    pos.state = "CLOSED"
                    pos.close_time = datetime.now(timezone.utc)
                    pos.outcome = "reconciliation_phantom"
                    result["phantoms_closed"].append(symbol)

        except Exception as e:
            logger.warning(f"[RECOVERY] Phantom detection failed: {e}")
            result["errors"].append(f"phantom_detection_failed: {e}")

    # Save updated state
    save_position_state(pos_mgr, filepath=state_filepath)

    # Write fresh heartbeat
    save_heartbeat(heartbeat_filepath)

    # Summary
    logger.info("=" * 60)
    logger.info(
        f"AUTO-RECOVERY COMPLETE: "
        f"loaded={result['positions_loaded_from_disk']}, "
        f"reconciled={result['positions_reconciled_from_exchange']}, "
        f"phantoms={len(result['phantoms_closed'])}, "
        f"exchange={'OK' if result['exchange_reachable'] else 'UNREACHABLE'}"
    )
    logger.info("=" * 60)

    return result
