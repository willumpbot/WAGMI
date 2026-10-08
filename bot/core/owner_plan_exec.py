"""Owner-plan execution: the bot paper-trades the OWNER's saved plans and manages the exit itself.

The owner saves trade plans from the terminal (tools/hivemind/plans.py -> data/hivemind/owner_plans.jsonl).
With OWNER_PLAN_EXEC=true the bot also opens each plan as a PAPER position in its own PositionManager,
tagged strategy="owner_plan", and lets its normal exit machinery (TP1 partial, trailing, exit agent,
time stops, MFE exits) manage it. plans.py grades the plan as written; this module records what the
bot's management made of the same plan, so the two can be compared side by side.

HARD RULE: owner trades never feed the bot's learning or stats. Every close/partial of a tagged position
is diverted (multi_strategy_main close loop -> record_owner_close -> `continue`) into
data/hivemind/owner_fills.jsonl instead of equity / circuit breaker / trades.csv / trade ledger / DB /
weights / Kelly / IC / deep memory / learning. Guards elsewhere key off the TAG (strategy=="owner_plan"),
not the flag, so a tagged position recovered after the flag was switched off is still excluded.

Files (all under data/hivemind/):
  owner_plans.jsonl          read-only here (written by plans.py)
  owner_orders_state.json    this module's state: per-plan status (idempotent across restarts)
  owner_fills.jsonl          append-only: one row per open, partial leg and final close
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.core.owner_plan_exec")

OWNER_STRATEGY = "owner_plan"

try:
    from core.paths import DATA_DIR as _DATA_DIR
except Exception:  # pragma: no cover - import-path fallback
    _DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Module-level so tests can point it at a temp dir.
HM_DIR: Path = Path(os.getenv("OWNER_PLAN_DIR") or (_DATA_DIR / "hivemind"))

_LOCK = threading.RLock()

# Statuses after which a plan is never looked at again by drain().
TERMINAL = {"open", "closed", "filled", "blocked", "rejected", "stale", "expired", "cancelled"}


def enabled() -> bool:
    return os.getenv("OWNER_PLAN_EXEC", "false").strip().lower() in ("1", "true", "yes", "on")


def is_owner_position(pos: Any) -> bool:
    return pos is not None and getattr(pos, "strategy", "") == OWNER_STRATEGY


def is_owner_event(event: Any) -> bool:
    return event is not None and getattr(event, "strategy", "") == OWNER_STRATEGY


def plans_path() -> Path:
    return Path(HM_DIR) / "owner_plans.jsonl"


def state_path() -> Path:
    return Path(HM_DIR) / "owner_orders_state.json"


def fills_path() -> Path:
    return Path(HM_DIR) / "owner_fills.jsonl"


def _f(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


# ── persistence ─────────────────────────────────────────────────────────────

def read_plan_rows() -> List[Dict[str, Any]]:
    try:
        text = plans_path().read_text(encoding="utf-8")
    except OSError:
        return []
    rows = []
    for line in text.splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def load_state() -> Dict[str, Any]:
    try:
        st = json.loads(state_path().read_text(encoding="utf-8"))
        if isinstance(st, dict) and isinstance(st.get("plans"), dict):
            return st
    except (OSError, ValueError):
        pass
    return {"plans": {}}


def save_state(st: Dict[str, Any]) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    st["updated"] = time.time()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, p)


def _append_fill(row: Dict[str, Any]) -> None:
    p = fills_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


# ── geometry ────────────────────────────────────────────────────────────────

def plan_levels(side: str, entry: float, stop: float, target: float) -> Optional[Dict[str, float]]:
    """tp2 = target, tp1 = entry +/- 1R capped at the midpoint to target. None if geometry is invalid."""
    sg = 1 if side == "LONG" else -1
    if entry <= 0 or sg * (entry - stop) <= 0 or sg * (target - entry) <= 0:
        return None
    r = abs(entry - stop)
    mid = (entry + target) / 2.0
    tp1 = min(entry + r, mid) if sg > 0 else max(entry - r, mid)
    return {"sl": stop, "tp1": tp1, "tp2": target, "r": r}


def _side_of(price: float, entry: float) -> int:
    return 0 if price == entry else (1 if price > entry else -1)


# ── the drain (called once per tick from _tick_once) ────────────────────────

def drain(bot, trace_id: str = "", now: Optional[float] = None) -> Dict[str, Any]:
    """Process new owner plans: queue limits, open fills, mark rejects. Returns the state dict.

    `bot` is the MultiStrategyBot (needs pos_mgr, order_executor, _last_prices; optional ops_guard,
    telegram_bot, degradation, _tick_regime_cache, fetcher, _executing_lock/_executing_symbols).
    """
    now = time.time() if now is None else now
    with _LOCK:
        st = load_state()
        plans = st["plans"]
        rows = read_plan_rows()
        cancelled = {str(r.get("id")) for r in rows if r.get("kind") == "cancel"}
        changed = False

        try:
            from trading_config import DEFAULT_SYMBOLS
            managed = set(DEFAULT_SYMBOLS.keys())
        except Exception:
            managed = {"BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR"}

        # Entry halts are transient: plans stay pending and are re-evaluated next tick.
        halted = ""
        try:
            if getattr(getattr(bot, "ops_guard", None), "is_killed", False):
                halted = "kill switch"
            elif getattr(getattr(bot, "telegram_bot", None), "is_paused", False):
                halted = "paused"
            elif getattr(bot, "degradation", None) is not None and bot.degradation.should_halt_entries():
                halted = "exchange degraded"
        except Exception:
            pass

        prices = dict(getattr(bot, "_last_prices", {}) or {})
        market_max_age = _f("OWNER_PLAN_MARKET_MAX_AGE_S", 1800.0)
        market_drift = _f("OWNER_PLAN_MARKET_MAX_DRIFT", 0.005)

        for pl in (r for r in rows if r.get("kind") == "plan"):
            pid = str(pl.get("id") or "")
            if not pid:
                continue
            rec = plans.get(pid)
            if rec and rec.get("status") in TERMINAL:
                continue
            if pl.get("ts") and float(pl.get("ts") or 0) < _f("OWNER_PLAN_MIN_TS", 0.0):
                # Plans saved before the feature was switched on are never executed retroactively.
                continue

            def mark(status, reason, **extra):
                nonlocal changed
                r = dict(plans.get(pid) or {}, status=status, reason=reason, coin=pl.get("coin"),
                         side=pl.get("side"), updated=now, **extra)
                r.setdefault("first_seen", now)
                plans[pid] = r
                changed = True
                logger.info(f"[{trace_id}][OWNER-PLAN] {pid} {pl.get('coin')} {pl.get('side')}: {status} — {reason}")

            if pid in cancelled:
                mark("cancelled", "cancelled by owner before fill")
                continue

            coin = str(pl.get("coin") or "").upper()
            side = str(pl.get("side") or "").upper()
            etype = pl.get("entry_type") or "limit"
            try:
                ts = float(pl.get("ts") or 0)
                entry = float(pl["entry"])
                stop = float(pl["stop"])
                target = float(pl["target"])
                price_at_plan = float(pl.get("price_at_plan") or entry)
                window_h = float(pl.get("entry_window_h") or 24)
            except (KeyError, TypeError, ValueError):
                mark("rejected", "plan has non-numeric levels")
                continue

            if coin not in managed:
                mark("rejected", f"bot only manages {'/'.join(sorted(managed))}; {coin or '?'} is not one")
                continue
            if side not in ("LONG", "SHORT") or plan_levels(side, entry, stop, target) is None:
                mark("rejected", "invalid side / stop / target geometry")
                continue
            if getattr(getattr(bot, "order_executor", None), "mode", "paper") != "paper":
                mark("rejected", "owner-plan execution is paper-only; executor is not in paper mode")
                continue

            price = prices.get(coin)
            fill_reason = ""
            if etype == "market":
                if now - ts > market_max_age:
                    mark("stale", f"market plan was {(now - ts) / 60:.0f} min old when the bot saw it")
                    continue
                if not price:
                    if not rec:
                        mark("queued", "waiting for a live price")
                    continue
                drift = abs(price - price_at_plan) / price_at_plan if price_at_plan > 0 else 1.0
                if drift > market_drift:
                    mark("stale", f"price moved {drift:.2%} from the plan's {price_at_plan:g} (max {market_drift:.1%})")
                    continue
                fill_reason = "market plan opened at current price"
            else:
                if now > ts + window_h * 3600:
                    mark("expired", f"entry {entry:g} not reached within {window_h:g}h")
                    continue
                if not price:
                    if not rec:
                        mark("queued", f"limit {entry:g} waiting for a live price")
                    continue
                ref_side = (rec or {}).get("last_side")
                if ref_side is None:
                    ref_side = _side_of(price_at_plan, entry)
                cur_side = _side_of(price, entry)
                crossed = cur_side == 0 or (ref_side != 0 and cur_side != ref_side) or ref_side == 0
                if not crossed:
                    if not rec or rec.get("status") != "queued" or rec.get("last_side") != cur_side:
                        mark("queued", f"limit {entry:g} waiting (last {price:g})", last_side=cur_side)
                    continue
                fill_reason = f"limit {entry:g} crossed (last {price:g})"

            # ---- ready to fill ----
            if halted:
                if not rec or rec.get("reason") != f"waiting: {halted}":
                    mark("queued", f"waiting: {halted}")
                continue
            pm = bot.pos_mgr
            existing = pm.positions.get(coin)
            if existing is not None and getattr(existing, "state", "CLOSED") != "CLOSED":
                if is_owner_position(existing):
                    mark("blocked", f"another owner plan is already open in {coin}")
                else:
                    mark("blocked", f"bot already in {coin}")
                continue
            # Loss cooldown in PositionManager is transient: wait it out instead of burning the plan.
            try:
                _lc = pm._last_close_time.get(coin)
                if _lc is not None and not pm._last_close_won.get(coin, True):
                    from datetime import datetime, timezone
                    if (datetime.now(timezone.utc) - _lc).total_seconds() / 60.0 < pm._reentry_cooldown_minutes:
                        if not rec or rec.get("reason") != "waiting: bot loss cooldown":
                            mark("queued", "waiting: bot loss cooldown")
                        continue
            except Exception:
                pass

            res = _open(bot, pl, coin, side, price, stop, target, trace_id)
            if res.get("ok"):
                mark("open", fill_reason, fill_price=res["entry"], qty=res["qty"], tp1=res["tp1"],
                     tp2=res["tp2"], sl=res["sl"], risk_usd=res["risk_usd"], position_id=res["position_id"],
                     filled_at=now, fills=[])
                try:
                    _append_fill({"kind": "open", "plan_id": pid, "coin": coin, "side": side, "entry": res["entry"],
                                  "qty": res["qty"], "sl": res["sl"], "tp1": res["tp1"], "tp2": res["tp2"],
                                  "risk_usd": res["risk_usd"], "position_id": res["position_id"], "ts": now,
                                  "pnl_lev": res.get("pnl_lev", 1.0),
                                  "reason": fill_reason})
                except Exception:
                    logger.debug("[OWNER-PLAN] open row write failed", exc_info=True)
            else:
                mark("rejected", res.get("reason", "open failed"))

        if changed:
            try:
                save_state(st)
            except Exception:
                logger.warning("[OWNER-PLAN] state save failed", exc_info=True)
        return st


def _atr_1h(bot, coin: str) -> float:
    try:
        from trading_config import DEFAULT_SYMBOLS
        cfg = DEFAULT_SYMBOLS.get(coin)
        data = bot.fetcher.fetch_multi_timeframe(coin, cfg.coingecko_id if cfg else "", ["1h"])
        df = data.get("1h")
        if df is None or len(df) < 15:
            return 0.0
        import pandas as pd
        prev_c = df["close"].shift(1)
        tr = pd.concat([df["high"] - df["low"], (df["high"] - prev_c).abs(), (df["low"] - prev_c).abs()],
                       axis=1).max(axis=1)
        v = float(tr.rolling(14, min_periods=14).mean().iloc[-1])
        return v if v > 0 else 0.0
    except Exception:
        return 0.0


def _open(bot, pl: Dict[str, Any], coin: str, side: str, price: float, stop: float, target: float,
          trace_id: str) -> Dict[str, Any]:
    pm = bot.pos_mgr
    lv = plan_levels(side, price, stop, target)
    if lv is None:
        return {"ok": False, "reason": f"price {price:g} is already past the stop or target"}
    if lv["r"] / price < 0.001:
        return {"ok": False, "reason": "stop is closer than 0.1% to the fill price"}
    risk_usd = float(pl.get("risk_usd") or 0) or _f("OWNER_PLAN_DEFAULT_RISK_USD", 10.0)
    leverage = max(1.0, float(pl.get("leverage") or 1))
    try:
        pnl_lev = pm._pnl_lev(leverage)
    except Exception:
        pnl_lev = 1.0
    qty = risk_usd / (lv["r"] * (pnl_lev or 1.0))
    order_side = "BUY" if side == "LONG" else "SELL"

    lock = getattr(bot, "_executing_lock", None)
    execs = getattr(bot, "_executing_symbols", None)
    if lock is not None and execs is not None:
        with lock:
            if coin in execs:
                return {"ok": False, "reason": f"bot was mid-execution in {coin}"}
            execs.add(coin)
    try:
        order = bot.order_executor.open_position(symbol=coin, side=order_side, qty=qty, price=price,
                                                 leverage=int(leverage), order_type="market")
        if not getattr(order, "filled", False):
            return {"ok": False, "reason": f"paper order refused: {getattr(order, 'error', '')}"[:200]}
        fill = order.fill_price if getattr(order, "fill_price", 0) > 0 else price
        qty = order.fill_qty if getattr(order, "fill_qty", 0) > 0 else qty
        lv = plan_levels(side, fill, stop, target) or lv
        try:
            from execution.trade_profile import TradeProfile
            prof = TradeProfile(entry_type="MEDIUM", entry_reasons=[OWNER_STRATEGY], primary_driver=OWNER_STRATEGY,
                                confidence=50.0, regime=(getattr(bot, "_tick_regime_cache", {}) or {}).get(coin, "unknown"),
                                volatility_band="medium", timeframe_bias="medium")
        except Exception:
            prof = None
        regime = (getattr(bot, "_tick_regime_cache", {}) or {}).get(coin, "unknown")
        pos = pm.open_position(
            symbol=coin, side=side, entry=fill, qty=qty, sl=lv["sl"], tp1=lv["tp1"], tp2=lv["tp2"],
            atr=_atr_1h(bot, coin), leverage=leverage, mode="leverage" if leverage > 1 else "spot",
            strategy=OWNER_STRATEGY, confidence=50.0,
            entry_reasons={"owner_plan_id": pl.get("id"), "owner_trade": True, "llm_action": "owner",
                           "primary_driver": OWNER_STRATEGY, "regime": regime, "setup": pl.get("setup"),
                           "plan_entry": pl.get("entry"), "plan_stop": stop, "plan_target": target},
            trade_profile=prof,
            notes=f"THESIS: owner plan {side} {coin} tgt {target:g} inval {stop:g} | setup=owner_plan",
            setup_type=OWNER_STRATEGY,
        )
        if pos is None:
            return {"ok": False, "reason": "position manager refused (duplicate / cooldown / stop too tight)"}
        return {"ok": True, "entry": pos.entry, "qty": pos.qty, "sl": pos.sl, "tp1": pos.tp1, "tp2": pos.tp2,
                "risk_usd": round(abs(pos.entry - pos.sl) * pos.qty * (pnl_lev or 1.0), 4),
                "position_id": pos.position_id, "pnl_lev": pnl_lev or 1.0}
    finally:
        if lock is not None and execs is not None:
            with lock:
                execs.discard(coin)


# ── close-side diversion (called from the multi_strategy_main close loop) ───

def record_owner_close(event, pos, pos_mgr=None) -> Dict[str, Any]:
    """Write one owner_fills.jsonl row for a tagged TP1 / partial / final close and update state.

    Never touches equity, ledgers or learning — the caller `continue`s past all of that.
    """
    md = getattr(event, "metadata", None) or {}
    er = (getattr(pos, "entry_reasons", None) or md.get("entry_reasons") or {}) if pos is not None else (md.get("entry_reasons") or {})
    pid = str(er.get("owner_plan_id") or "")
    final = bool(getattr(event, "is_position_close", False))
    entry = float(getattr(pos, "entry", 0) or md.get("entry") or 0)
    orig_sl = float(getattr(pos, "original_sl", 0) or md.get("sl") or 0)
    orig_qty = float(getattr(pos, "original_qty", 0) or 0) or float(getattr(event, "qty", 0) or 0)
    lev = float(getattr(event, "leverage", 1) or 1)
    try:
        pnl_lev = pos_mgr._pnl_lev(lev) if pos_mgr is not None else 1.0
    except Exception:
        pnl_lev = 1.0
    risk_usd = abs(entry - orig_sl) * orig_qty * (pnl_lev or 1.0)
    funding = float(md.get("funding_costs", 0) or 0) if final else float(md.get("funding_share", 0) or 0)
    leg_net = float(getattr(event, "pnl", 0) or 0) - float(getattr(event, "fee", 0) or 0) - funding
    total = float(getattr(pos, "realized_pnl", 0) or 0) if pos is not None else leg_net
    opened = getattr(pos, "open_time", None)
    row = {
        "kind": "final" if final else "partial", "plan_id": pid, "coin": getattr(event, "symbol", ""),
        "side": getattr(event, "side", ""), "entry": entry, "exit": float(getattr(event, "price", 0) or 0),
        "qty": float(getattr(event, "qty", 0) or 0), "pnl": round(leg_net, 6),
        "r": round(leg_net / risk_usd, 4) if risk_usd > 0 else None, "reason": getattr(event, "action", ""),
        "position_id": getattr(event, "position_id", "") or getattr(pos, "position_id", ""),
        "opened_at": opened.isoformat() if hasattr(opened, "isoformat") else opened, "ts": time.time(),
    }
    if final:
        row["total_pnl"] = round(total, 6)
        row["total_r"] = round(total / risk_usd, 4) if risk_usd > 0 else None
        row["outcome"] = getattr(pos, "outcome", "")
        row["state_path"] = getattr(pos, "state_path_str", "")
    with _LOCK:
        try:
            _append_fill(row)
        except Exception:
            logger.warning("[OWNER-PLAN] fill row write failed", exc_info=True)
        if pid:
            try:
                st = load_state()
                rec = st["plans"].get(pid) or {"first_seen": time.time()}
                rec.setdefault("fills", []).append({k: row[k] for k in ("kind", "exit", "qty", "pnl", "r", "reason", "ts")})
                rec["pnl_usd"] = round(total, 4)
                rec["r"] = round(total / risk_usd, 3) if risk_usd > 0 else None
                if final:
                    rec["status"] = "closed"
                    rec["reason"] = f"closed by bot: {row['reason']}"
                    rec["closed_at"] = row["ts"]
                rec["updated"] = row["ts"]
                st["plans"][pid] = rec
                save_state(st)
            except Exception:
                logger.warning("[OWNER-PLAN] state update on close failed", exc_info=True)
    if final:
        try:
            from core.position_journal import journal_booked
            journal_booked(row["position_id"], symbol=row["coin"])
        except Exception:
            pass
    logger.info(f"[OWNER-PLAN] {row['kind']} {row['coin']} {row['reason']} leg={leg_net:+.2f} "
                f"total={total:+.2f} ({row.get('total_r', row['r'])}R) — excluded from bot books")
    return row
