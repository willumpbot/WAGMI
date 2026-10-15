"""OWNER_PLAN_ANY_COIN: the paper bot executes the owner's plans on ANY Hyperliquid perp, not only its own 6.

Default OFF (= today's behaviour exactly: a plan on a coin outside trading_config.DEFAULT_SYMBOLS is rejected
"bot only manages ..."). ON: core/owner_plan_exec.drain accepts such a plan and opens it through the SAME path a
core-coin owner plan takes (limit-touch / market-drift entry rules, plan_levels, PositionManager.open_position,
owner exit modes, OWNER_RUNNER_STYLE half/trail with atr_at_fill, plan time limit, owner_fills.jsonl rows,
position_state persistence + restart restore). The bot's OWN strategy scan is untouched: it iterates
DEFAULT_SYMBOLS only, so it never evaluates, opens or rotates into these coins.

What a coin needs that the bot only had for its 6, and where it comes from here (Hyperliquid public info API,
no wallet, one-shot HTTP with short timeouts so a blip never stalls the tick):
  price / mark updates  -> ONE `allMids` call per tick covers every extra coin (cached MIDS_TTL_S)
  szDecimals / maxLev   -> `metaAndAssetCtxs` (cached META_TTL_S); registered into execution.precision
                           (price decimals = min(6 - szDecimals, 5 significant figures), qty = szDecimals)
  funding               -> the same `metaAndAssetCtxs` call (ctx "funding", the value ccxt reports as fundingRate)
  paper fill simulation -> the coin's ccxt pair is registered in order_executor.SYMBOL_TO_PAIR so the paper
                           OrderExecutor fills it exactly like a core coin (min-notional floor, 20% margin cap, fees)
  1h ATR (pos.atr)      -> `candleSnapshot` 1h, same TR/14 formula as owner_plan_exec._atr_1h
  daily atr_at_fill     -> owner_plan_exec.atr_at_fill already reads HL daily candles for any coin (hl_name mapping)
  update_price / exits  -> manage(): the core coins get update_price inside _process_symbol (a DEFAULT_SYMBOLS
                           loop); extra coins get it here, every tick, with the same close-order + owner-diversion
                           steps as the core close loop, plus the queued exit-engine / exit-agent / hold-limit
                           events (_pending_exit_events) for those coins, which _process_symbol would never drain.

EXIT MODE for extra coins: bot_manages degrades to profits_only. The bot's discretionary exits (MFE exit, funding
avoidance, liquidation-tighten, 5m early-exit momentum) live in _process_symbol and need the candles / funding the
bot only fetches for its 6; the exit engine / exit agent would see regime "unknown" and no candles. Rather than run
a half-blind "bot_manages", the owner's stop / target / partials / runner rule govern (requested mode is kept in
entry_reasons["exit_mode_requested"]). OWNER_PLAN_EXIT_MODE_FORCE=bot_manages degrades the same way for them.

Sizing: the plan's risk_usd exactly as for a core owner plan, then execution.risk_cap.apply_risk_cap (the 0.5%
MAX_RISK_PCT_CEILING; scales DOWN only, and only when RISK_CAP_HARD_CLAMP is on, shadow-logged otherwise).
Leverage above the coin's Hyperliquid maxLeverage is rejected (the exchange would refuse it).

Books: owner positions never reach equity / circuit breaker / ledgers / learning (record_owner_close diverts every
leg, keyed off strategy=="owner_plan", like core owner positions). get_total_unrealized_pnl already skips owner
positions. Like core owner plans, an open one still occupies a max_open_positions slot (get_open_count).
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("bot.core.owner_any_coin")

HL_INFO_URL = "https://api.hyperliquid.xyz/info"
MIDS_TTL_S = 5.0          # one allMids per tick (ticks are >= ~60s; drain + manage share the same call)
MIDS_MAX_AGE_S = 180.0    # never act on a mid older than this (HL down -> skip the tick, like a core NO DATA)
META_TTL_S = 600.0
ATR_TTL_S = 900.0

_LOCK = threading.RLock()
_MIDS: Dict[str, Any] = {"ts": 0.0, "tried": 0.0, "px": {}}
_META: Dict[str, Any] = {"ts": 0.0, "tried": 0.0, "coins": {}}
_ATR: Dict[str, Tuple[float, float]] = {}
# bot symbol (upper) -> registered info {"name": HL coin name, "szDecimals", "maxLeverage", "price_dp"}
_REG: Dict[str, Dict[str, Any]] = {}
# fill-price guard: an off-scale reading must be confirmed by the next tick before it is acted on
_PENDING_JUMP: Dict[str, float] = {}

_CLOSE_ACTIONS = ("SL", "TP1", "TP2", "TRAILING_STOP", "EARLY_EXIT",
                  "EMERGENCY", "LIQUIDATION_AVOID", "LIQUIDATION_PROXIMITY",
                  "FUNDING_AVOIDANCE", "ROTATE_PROFIT", "ROTATE_LOSS_AVOIDANCE",
                  "TIME_STOP", "TP1_FULL", "TELEGRAM_CLOSE")   # == multi_strategy_main close loop _close_actions


def enabled() -> bool:
    return os.getenv("OWNER_PLAN_ANY_COIN", "false").strip().lower() in ("1", "true", "yes", "on")


def core_symbols() -> set:
    try:
        from trading_config import DEFAULT_SYMBOLS
        return set(DEFAULT_SYMBOLS.keys())
    except Exception:
        return {"BTC", "ETH", "SOL", "HYPE", "XRP", "NEAR"}


def is_extra(symbol: str) -> bool:
    """True only for a coin this module registered (never for a core coin; always False with the flag never on)."""
    return str(symbol or "").upper() in _REG


def hl_name(symbol: str) -> str:
    """Hyperliquid's own coin name for a bot symbol (e.g. KPEPE -> kPEPE). Unregistered/core: unchanged."""
    info = _REG.get(str(symbol or "").upper())
    return info["name"] if info else symbol


# ── Hyperliquid public info API (one shot, short timeout: never stalls the tick) ──────────────

def _post(body: Dict[str, Any], timeout: float = 5.0):
    import urllib.request
    req = urllib.request.Request(HL_INFO_URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def fetch_mids() -> Dict[str, float]:
    """{UPPER coin: mid}. One allMids call per MIDS_TTL_S; on failure the last good snapshot (if fresh enough)."""
    now = time.time()
    with _LOCK:
        if now - _MIDS["tried"] < MIDS_TTL_S:
            return _MIDS["px"] if now - _MIDS["ts"] <= MIDS_MAX_AGE_S else {}
        _MIDS["tried"] = now
    try:
        raw = _post({"type": "allMids"})
        px = {}
        for k, v in (raw or {}).items():
            if str(k).startswith("@"):
                continue  # spot pairs
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if f > 0:
                px[str(k).upper()] = f
        with _LOCK:
            _MIDS.update(ts=now, px=px)
        return px
    except Exception as e:
        logger.warning(f"[OWNER-ANY-COIN] allMids failed: {e}")
        with _LOCK:
            return _MIDS["px"] if now - _MIDS["ts"] <= MIDS_MAX_AGE_S else {}


def fetch_meta() -> Dict[str, Dict[str, Any]]:
    """{UPPER coin: {name, szDecimals, maxLeverage, funding, delisted}} from metaAndAssetCtxs (cached)."""
    now = time.time()
    with _LOCK:
        if now - _META["tried"] < (META_TTL_S if _META["coins"] else 30.0):   # failed fetch: retry after 30s
            return _META["coins"]
        _META["tried"] = now
    try:
        meta, ctxs = _post({"type": "metaAndAssetCtxs"})
        coins = {}
        for i, u in enumerate(meta.get("universe") or []):
            ctx = ctxs[i] if i < len(ctxs) else {}
            try:
                fr = float(ctx.get("funding")) if ctx.get("funding") is not None else None
            except (TypeError, ValueError):
                fr = None
            coins[str(u.get("name", "")).upper()] = {
                "name": u.get("name"), "szDecimals": int(u.get("szDecimals") or 0),
                "maxLeverage": float(u.get("maxLeverage") or 0) or None, "funding": fr,
                "delisted": bool(u.get("isDelisted")),
            }
        with _LOCK:
            _META.update(ts=now, coins=coins)
        return coins
    except Exception as e:
        logger.warning(f"[OWNER-ANY-COIN] metaAndAssetCtxs failed: {e}")
        with _LOCK:
            return _META["coins"]


def _price_decimals(sz_decimals: int, price: Optional[float]) -> int:
    """Hyperliquid perp price rule: <= 6 - szDecimals decimals AND <= 5 significant figures."""
    dp = max(0, 6 - int(sz_decimals))
    if price and price > 0:
        dp = min(dp, max(0, 5 - (int(math.floor(math.log10(price))) + 1)))
    return dp


def register(symbol: str, info: Dict[str, Any], price: Optional[float] = None) -> Dict[str, Any]:
    """Make the bot's per-coin plumbing know this coin: precision table + paper executor pair. Never overrides an
    entry the bot already has (e.g. SUI/DOGE are in config/symbol_precision.json)."""
    sym = str(symbol).upper()
    with _LOCK:
        reg = _REG.get(sym)
        if reg is None or (reg.get("price_dp") is None and price):
            sz = int(info.get("szDecimals") or 0)
            dp = _price_decimals(sz, price)
            own_spec = bool(reg and reg.get("own_spec"))
            reg = {"name": info.get("name") or sym, "szDecimals": sz, "maxLeverage": info.get("maxLeverage"),
                   "price_dp": dp if price else None, "own_spec": own_spec,
                   "own_pair": bool((_REG.get(sym) or {}).get("own_pair"))}
            _REG[sym] = reg
            try:
                from execution.precision import register_symbol_spec
                # only ever (re)writes a spec THIS module inserted; the bot's own table entries are never touched
                if register_symbol_spec(sym, {"price": dp, "qty": sz, "min_qty": 10.0 ** -sz,
                                              "tick_size": 10.0 ** -dp, "max_leverage": info.get("maxLeverage") or 3},
                                        overwrite=own_spec):
                    reg["own_spec"] = True
            except Exception:
                logger.warning(f"[OWNER-ANY-COIN] {sym} precision registration failed", exc_info=True)
            try:
                from execution import order_executor as _oe
                if sym not in _oe.SYMBOL_TO_PAIR:
                    _oe.SYMBOL_TO_PAIR[sym] = f"{sym}/USDC:USDC"
                    reg["own_pair"] = True
            except Exception:
                logger.warning(f"[OWNER-ANY-COIN] {sym} executor pair registration failed", exc_info=True)
        return reg


def plan_check(coin: str, pl: Dict[str, Any]) -> Tuple[str, str]:
    """For a plan on a non-core coin with the flag on: ("ok", "") / ("wait", why) / ("rejected", why)."""
    sym = str(coin or "").upper()
    if not sym:
        return "rejected", "plan has no coin"
    meta = fetch_meta()
    if not meta:
        return "wait", "waiting: Hyperliquid metadata unavailable"
    info = meta.get(sym)
    if info is None:
        return "rejected", f"{coin} is not a Hyperliquid perp"
    if info.get("delisted"):
        return "rejected", f"{coin} is delisted on Hyperliquid"
    try:
        lev = max(1.0, float(pl.get("leverage") or 1))
    except (TypeError, ValueError):
        lev = 1.0
    mx = info.get("maxLeverage")
    if mx and lev > mx:
        return "rejected", f"leverage {lev:g}x is above {coin}'s Hyperliquid max {mx:g}x"
    register(sym, info)
    return "ok", ""


def price_for(bot, symbol: str) -> Optional[float]:
    """Current mid for a registered extra coin (one shared allMids call). Also finalises its price precision."""
    sym = str(symbol).upper()
    info = _REG.get(sym)
    px = fetch_mids().get(str(info["name"] if info else sym).upper())
    if px and info is not None and info.get("price_dp") is None:
        register(sym, dict(info, name=info["name"]), price=px)
    return px


def funding_for(symbol: str) -> Optional[float]:
    info = fetch_meta().get(str(hl_name(symbol)).upper())
    return info.get("funding") if info else None


def exit_mode_for(requested: str) -> Tuple[str, Optional[str]]:
    """bot_manages -> profits_only for extra coins (see module doc). Returns (mode, note)."""
    if requested == "bot_manages":
        return "profits_only", ("bot_manages degraded to profits_only: the bot's discretionary exits need the "
                                "candles/funding it only fetches for its own coins")
    return requested, None


def resolve_exit_mode(mode: str) -> str:
    """owner_exit_mode hook for positions marked any_coin (covers OWNER_PLAN_EXIT_MODE_FORCE=bot_manages too)."""
    return exit_mode_for(mode)[0]


def cap_qty(bot, symbol: str, qty: float, entry: float, stop: float) -> float:
    """The bot's per-trade risk cap (execution.risk_cap) on the owner plan's qty. Never increases qty."""
    try:
        from execution.risk_cap import apply_risk_cap
        equity = float(bot.risk_mgr.equity or 0.0)
    except Exception:
        logger.warning(f"[OWNER-ANY-COIN] {symbol} risk cap: equity unavailable - qty unchanged")
        return qty
    return apply_risk_cap(qty, entry, stop, equity, context=f"[OWNER-ANY-COIN][{symbol}] owner plan")


def atr_1h(symbol: str) -> float:
    """1h ATR(14) from Hyperliquid candles (same formula as owner_plan_exec._atr_1h). 0.0 when unavailable."""
    sym = str(symbol).upper()
    now = time.time()
    hit = _ATR.get(sym)
    if hit and now - hit[1] < ATR_TTL_S:
        return hit[0]
    try:
        end = int(now * 1000)
        bars = sorted(_post({"type": "candleSnapshot", "req": {"coin": hl_name(sym), "interval": "1h",
                                                                  "startTime": end - 40 * 3600 * 1000, "endTime": end}})
                      or [], key=lambda b: b["t"])
        h = [float(b["h"]) for b in bars]
        lo = [float(b["l"]) for b in bars]
        c = [float(b["c"]) for b in bars]
        if len(c) < 15:
            return 0.0
        trs = [max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])) for i in range(1, len(c))]
        v = sum(trs[-14:]) / 14
        v = v if v > 0 else 0.0
        _ATR[sym] = (v, now)
        return v
    except Exception as e:
        logger.debug(f"[OWNER-ANY-COIN] {sym} 1h ATR failed: {e}")
        return 0.0


def entry_marks(symbol: str, requested_mode: str, note: Optional[str]) -> Dict[str, Any]:
    out = {"any_coin": True, "hl_coin": hl_name(symbol)}
    if note:
        out["exit_mode_requested"] = requested_mode
        out["exit_mode_note"] = note
    return out


# ── per-tick management of open extra-coin owner positions ───────────────────────────────────

def _owner_extra_symbols(pm) -> list:
    from core.owner_plan_exec import is_owner_position
    core = core_symbols()
    return [s for s, p in list(pm.positions.items()) if s not in core and is_owner_position(p)]


def _guarded_price(bot, sym: str, px: float) -> Optional[float]:
    """multi_strategy_main's fill-price guardrail (validate_fill_price vs the last known price), except that an
    off-scale reading CONFIRMED by the next tick is accepted: a thin coin that gaps >10% must not freeze its stop."""
    last = (getattr(bot, "_last_prices", {}) or {}).get(sym)
    if last is None:
        return px
    try:
        from execution.precision import validate_fill_price
        err = validate_fill_price(sym, px, last)
    except Exception:
        err = None
    if not err:
        _PENDING_JUMP.pop(sym, None)
        return px
    prev = _PENDING_JUMP.get(sym)
    if prev and abs(px - prev) / prev <= 0.10:
        _PENDING_JUMP.pop(sym, None)
        logger.warning(f"[OWNER-ANY-COIN] {sym} off-scale move confirmed on a 2nd tick ({last:g} -> {px:g}) - accepted")
        return px
    _PENDING_JUMP[sym] = px
    logger.warning(f"[OWNER-ANY-COIN] {sym} PRICE HELD: {err} (needs a 2nd confirming tick)")
    return None


def manage(bot, trace_id: str = "") -> int:
    """Price-update + close-route every open owner position on a coin outside DEFAULT_SYMBOLS. Never raises.

    Runs whatever the flags (a position opened while OWNER_PLAN_ANY_COIN was on must not be stranded with no price
    feed after the flag goes off - core owner positions keep being managed the same way). A no-op without network
    when no such position exists (always, unless the flag was on at some point). Returns events processed.
    """
    try:
        pm = bot.pos_mgr
        syms = _owner_extra_symbols(pm)
        if not syms:
            return 0
        from core import owner_plan_exec as ope
        mids = fetch_mids()
        n = 0
        for sym in syms:
            try:
                n += _manage_one(bot, pm, ope, sym, mids, trace_id)
            except Exception as e:
                logger.warning(f"[{trace_id}][OWNER-ANY-COIN] {sym} manage error: {e}", exc_info=True)
        return n
    except Exception as e:
        logger.warning(f"[{trace_id}][OWNER-ANY-COIN] manage error: {e}", exc_info=True)
        return 0


def _manage_one(bot, pm, ope, sym: str, mids: Dict[str, float], trace_id: str) -> int:
    pos = pm.positions.get(sym)
    if pos is None:
        return 0
    # (re-)register after a restart: precision + executor pair must exist before any rounding / close order
    if sym not in _REG:
        info = fetch_meta().get(str((pos.entry_reasons or {}).get("hl_coin") or sym).upper())
        if info is not None:
            register(sym, info)
    if sym not in _REG:
        # no Hyperliquid metadata yet (HL unreachable right after a restart): without the coin's precision and
        # executor pair nothing can be rounded or closed correctly -> touch nothing (pending closes stay queued)
        logger.warning(f"[{trace_id}][OWNER-ANY-COIN] {sym}: waiting for Hyperliquid metadata - not managed this tick")
        return 0
    name = str(hl_name(sym)).upper()
    events = []
    if pos.state != "CLOSED":
        px = mids.get(name)
        if px:
            if _REG.get(sym, {}).get("price_dp") is None and sym in _REG:
                register(sym, _REG[sym], price=px)
            px = _guarded_price(bot, sym, px)
        if px:
            bot._last_prices[sym] = px
            fr = funding_for(sym)
            if fr:
                try:
                    bot._last_funding_rates[sym] = fr
                except Exception:
                    pass
                pm.accrue_funding(sym, fr)
            events = list(pm.update_price(sym, px))
    # queued closes for this coin (exit engine partials, exit agent, hold limit / OWNER_PLAN_MAX_HOLD):
    # _process_symbol only drains its own DEFAULT_SYMBOLS, so they are drained here (pop-under-lock, consumed once)
    pending = getattr(bot, "_pending_exit_events", None)
    if pending:
        lock = getattr(bot, "_pending_exit_lock", None) or threading.Lock()
        with lock:
            mine = [e for e in bot._pending_exit_events if e.symbol == sym]
            if mine:
                bot._pending_exit_events = [e for e in bot._pending_exit_events if e.symbol != sym]
        events.extend(mine)
    for event in events:
        captured = pm.positions.get(sym)
        if event.action in _CLOSE_ACTIONS and event.qty > 0 and not event.metadata.get("_exchange_submitted"):
            res = bot.order_executor.close_position(symbol=event.symbol, side="SELL" if event.side == "LONG" else "BUY",
                                                    qty=event.qty, price=event.price, reason=event.action)
            if not getattr(res, "filled", False):
                logger.critical(f"[{trace_id}][{sym}] CLOSE ORDER FAILED for {event.action} (owner any-coin) - "
                                f"skipping record. Error: {getattr(res, 'error', '')}")
                continue
        if ope.is_owner_event(event):
            try:
                ope.record_owner_close(event, captured, pm)
            except Exception as e:
                logger.warning(f"[{trace_id}][{sym}] owner-plan fill record failed: {e}")
        else:  # never expected: the bot does not trade these coins
            logger.error(f"[{trace_id}][{sym}] non-owner event {event.action} on an any-coin symbol - not booked")
    # cleanup, like _process_symbol: drop this coin's CLOSED position once nothing is pending for it
    p = pm.positions.get(sym)
    still_pending = any(e.symbol == sym for e in (getattr(bot, "_pending_exit_events", None) or []))
    if p is not None and p.state == "CLOSED" and not still_pending:
        del pm.positions[sym]
        for d in ("_last_prices", "_last_funding_rates"):
            try:
                getattr(bot, d).pop(sym, None)
            except Exception:
                pass
        _PENDING_JUMP.pop(sym, None)
    return len(events)


def _reset_for_tests() -> None:
    with _LOCK:
        _MIDS.update(ts=0.0, tried=0.0, px={})
        _META.update(ts=0.0, tried=0.0, coins={})
        _ATR.clear()
        _PENDING_JUMP.clear()
        for sym, reg in list(_REG.items()):
            try:
                if reg.get("own_spec"):
                    from execution.precision import unregister_symbol_spec
                    unregister_symbol_spec(sym)
                if reg.get("own_pair"):
                    from execution import order_executor as _oe
                    _oe.SYMBOL_TO_PAIR.pop(sym, None)
            except Exception:
                pass
            _REG.pop(sym, None)
