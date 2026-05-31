"""
Comprehensive snapshot builder for the LLM agent neural network.
Assembles EVERY piece of data the system knows into a structured context
that agents can reason about.

Design goals:
  - COMPLETE: every indicator, state, and feedback loop the system tracks
  - COMPACT: ~500-800 tokens total (agents have ~4000 token budgets)
  - LAYERED: market / signals / positions / system / memory / time
  - ZERO-SAFE: missing data produces empty dicts, never crashes

Called by the coordinator before running the agent pipeline.
Replaces the ad-hoc snapshot assembly scattered across _build_*_input methods.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.llm.agents.comprehensive_snapshot")


# ---------------------------------------------------------------------------
# Technical indicator helpers (numpy-free, list-based for speed)
# ---------------------------------------------------------------------------

def _ema(values: List[float], span: int) -> float:
    """Exponential moving average of the last `span` values. Returns last value."""
    if not values or len(values) < 2:
        return values[-1] if values else 0.0
    k = 2.0 / (span + 1)
    ema_val = values[0]
    for v in values[1:]:
        ema_val = v * k + ema_val * (1 - k)
    return ema_val


def _rsi(closes: List[float], period: int = 14) -> float:
    """RSI from close prices. Returns 0-100 scale."""
    if len(closes) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        delta = closes[-period - 1 + i] - closes[-period - 1 + i - 1]
        if delta > 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss < 1e-12:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - 100.0 / (1.0 + rs), 1)


def _atr(highs: List[float], lows: List[float], closes: List[float],
         period: int = 14) -> float:
    """Average True Range from OHLC lists. Returns absolute value."""
    if len(closes) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(closes)):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0.0
    return sum(trs[-period:]) / period


def _adx(highs: List[float], lows: List[float], closes: List[float],
         period: int = 14) -> float:
    """Simplified ADX. Returns 0-100 scale."""
    n = len(closes)
    if n < period + 2:
        return 25.0  # neutral default
    plus_dms, minus_dms, trs = [], [], []
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        plus_dms.append(max(up, 0.0) if up > down else 0.0)
        minus_dms.append(max(down, 0.0) if down > up else 0.0)
        tr = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                 abs(lows[i] - closes[i - 1]))
        trs.append(tr)
    # Smoothed sums over last `period` bars
    sm_tr = sum(trs[-period:])
    if sm_tr < 1e-12:
        return 0.0
    sm_plus = sum(plus_dms[-period:])
    sm_minus = sum(minus_dms[-period:])
    plus_di = 100 * sm_plus / sm_tr
    minus_di = 100 * sm_minus / sm_tr
    denom = plus_di + minus_di
    if denom < 1e-12:
        return 0.0
    dx = 100 * abs(plus_di - minus_di) / denom
    return round(dx, 1)


def _macd_hist(closes: List[float]) -> float:
    """MACD histogram (12/26/9). Positive = bullish momentum."""
    if len(closes) < 26:
        return 0.0
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = ema12 - ema26
    # Approximate signal line from last 9 MACD values
    # (simplified: just return the current MACD as histogram proxy)
    return round(macd_line, 6)


def _bb_position(closes: List[float], period: int = 20) -> Dict[str, float]:
    """Bollinger Band width (%) and price position (-1 to +1 scale).
    -1 = at lower band, 0 = at middle, +1 = at upper band."""
    if len(closes) < period:
        return {}
    window = closes[-period:]
    sma = sum(window) / period
    if sma < 1e-12:
        return {}
    variance = sum((x - sma) ** 2 for x in window) / period
    std = variance ** 0.5
    if std < 1e-12:
        return {"w": 0.0, "pos": 0.0}
    upper = sma + 2 * std
    lower = sma - 2 * std
    width = (upper - lower) / sma * 100
    band_range = upper - lower
    price_pos = (closes[-1] - lower) / band_range * 2 - 1  # -1 to +1
    return {"w": round(width, 2), "pos": round(price_pos, 2)}


def _extract_ohlcv(data: Dict[str, Any], timeframe: str = "1h"):
    """Extract OHLCV lists from the multi-timeframe data dict.

    Supports common data shapes:
      - data[timeframe] = list of [ts, o, h, l, c, v] candles
      - data[timeframe] = {"open": [...], "high": [...], ...}
      - data = list of candles (single timeframe)
    Returns (opens, highs, lows, closes, volumes) or Nones.
    """
    raw = data.get(timeframe, data.get(timeframe.replace("m", "min"), None))
    if raw is None and timeframe == "1h":
        # Fallback: try the first key that looks like a timeframe
        for k in data:
            if isinstance(data[k], (list, dict)) and k not in ("symbol",):
                raw = data[k]
                break
    if raw is None:
        return None, None, None, None, None

    if isinstance(raw, list) and raw and isinstance(raw[0], (list, tuple)):
        # List of candles: [ts, o, h, l, c, v]
        opens = [float(c[1]) for c in raw]
        highs = [float(c[2]) for c in raw]
        lows = [float(c[3]) for c in raw]
        closes = [float(c[4]) for c in raw]
        volumes = [float(c[5]) for c in raw if len(c) > 5]
        return opens, highs, lows, closes, volumes

    if isinstance(raw, dict):
        closes = raw.get("close", raw.get("closes", []))
        if closes:
            return (
                raw.get("open", raw.get("opens", [])),
                raw.get("high", raw.get("highs", [])),
                raw.get("low", raw.get("lows", [])),
                [float(c) for c in closes],
                raw.get("volume", raw.get("volumes", [])),
            )

    return None, None, None, None, None


# ---------------------------------------------------------------------------
# Layer builders
# ---------------------------------------------------------------------------

def _build_market_layer(
    symbol: str,
    data: Dict[str, Any],
    current_price: float,
    all_prices: Optional[Dict[str, float]],
    funding_rates: Optional[Dict[str, float]],
    open_interest: Optional[Dict[str, float]],
    liquidation_levels: Optional[Dict],
) -> Dict[str, Any]:
    """Layer 1: Market data + computed technicals.

    Token budget: ~200 tokens. Uses short keys throughout.
    """
    mkt: Dict[str, Any] = {
        "sym": symbol,
        "px": round(current_price, _price_decimals(current_price)),
    }

    # Compute technicals from the best available timeframe
    for tf in ("1h", "5m", "15m", "4h"):
        opens, highs, lows, closes, volumes = _extract_ohlcv(data, tf)
        if closes and len(closes) >= 20:
            mkt["tf"] = tf
            mkt["rsi"] = _rsi(closes)
            mkt["adx"] = _adx(highs, lows, closes)
            mkt["macd_h"] = _macd_hist(closes)
            bb = _bb_position(closes)
            if bb:
                mkt["bb_w"] = bb["w"]
                mkt["bb_pos"] = bb["pos"]
            atr_val = _atr(highs, lows, closes)
            if atr_val > 0 and current_price > 0:
                mkt["atr_pct"] = round(atr_val / current_price * 100, 3)
            # EMAs as distance from price (%)
            for span in (9, 20, 50):
                if len(closes) >= span:
                    ema_val = _ema(closes, span)
                    if ema_val > 0:
                        dist = (current_price - ema_val) / ema_val * 100
                        mkt[f"ema{span}_d"] = round(dist, 2)
            # 1h and 24h price change
            if len(closes) >= 2:
                mkt["chg_1h"] = round(
                    (closes[-1] - closes[-2]) / closes[-2] * 100, 2
                ) if tf == "1h" and closes[-2] > 0 else None
            if len(closes) >= 24 and tf == "1h":
                mkt["chg_24h"] = round(
                    (closes[-1] - closes[-24]) / closes[-24] * 100, 2
                ) if closes[-24] > 0 else None
            # Volume ratio (current vs 20-bar avg)
            if volumes and len(volumes) >= 20:
                avg_vol = sum(volumes[-20:]) / 20
                if avg_vol > 0:
                    mkt["vol_r"] = round(volumes[-1] / avg_vol, 2)
            break  # use first available timeframe

    # Funding rate
    if funding_rates:
        fr = funding_rates.get(symbol)
        if fr is not None and abs(fr) >= 0.0001:
            mkt["fr"] = round(fr, 5)

    # Open interest change
    if open_interest:
        oi = open_interest.get(symbol)
        if oi is not None and abs(oi) >= 0.1:
            mkt["oi_chg"] = round(oi, 1)

    # Cross-asset: BTC price for correlation context
    if all_prices:
        btc = all_prices.get("BTC", all_prices.get("BTC/USDT"))
        if btc and symbol not in ("BTC", "BTC/USDT"):
            mkt["btc_px"] = round(btc, 0)

    # Liquidation clusters
    if liquidation_levels:
        ll = liquidation_levels.get(symbol)
        if ll:
            mkt["liq"] = ll

    # Strip None values
    return {k: v for k, v in mkt.items() if v is not None}


# Shadow edges — mirrors bot/strategies/ensemble.py _SHADOW_EDGES.
# Wired into the snapshot 2026-05-30 so agents see "this is a known alpha setup" when applicable.
# Each entry: (symbol, side, strategy) -> dict with wr%, n, hypothesis_text.
_AGENT_SHADOW_EDGES = {
    ("ETH",  "BUY",  "regime_trend"):       {"wr": 100, "n": 135, "hypothesis": "100% WR validated edge on ETH BUY via regime_trend (3,802-trade audit)"},
    ("HYPE", "BUY",  "bollinger_squeeze"):  {"wr": 61,  "n": 196, "hypothesis": "61.2% WR validated edge on HYPE BUY via bollinger_squeeze"},
    ("SOL",  "SELL", "multi_tier_quality"): {"wr": 72,  "n": 68,  "hypothesis": "72.1% WR validated edge on SOL SELL via multi_tier_quality"},
    ("SOL",  "SELL", "bollinger_squeeze"):  {"wr": 72,  "n": 68,  "hypothesis": "72.1% WR validated edge on SOL SELL via bollinger_squeeze"},
    ("BTC",  "BUY",  "regime_trend"):       {"wr": 65,  "n": 117, "hypothesis": "65% WR validated edge on BTC BUY via regime_trend (upgraded 2026-05-30)"},
    ("HYPE", "BUY",  "regime_trend"):       {"wr": 87,  "n": 63,  "hypothesis": "87.3% WR validated edge on HYPE BUY via regime_trend (upgraded 2026-05-30)"},
    ("SOL",  "BUY",  "multi_tier_quality"): {"wr": 100, "n": 90,  "hypothesis": "100% WR / 90 samples — new edge discovered 2026-05-30 (April 19-day window, may be SOL bull-phase artifact)"},
    ("SOL",  "BUY",  "bollinger_squeeze"):  {"wr": 90,  "n": 100, "hypothesis": "90% WR / 100 samples — new edge discovered 2026-05-30 (caveat: 19-day window)"},
}


def _build_signal_layer(
    strategy_signals: Optional[Dict[str, Any]],
    ensemble_result: Any,
    gate_decisions: Optional[List[Dict]],
    multiplier_chain: Optional[List[Dict]],
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """Layer 2: Strategy signals, gate decisions, multiplier chain, shadow-edge matches.

    Token budget: ~150 tokens (plus ~50 if shadow edges match).
    """
    sig: Dict[str, Any] = {}

    # Per-strategy signals
    if strategy_signals:
        strats = {}
        for name, info in strategy_signals.items():
            if isinstance(info, dict):
                entry = {}
                if info.get("side"):
                    entry["s"] = info["side"]
                if info.get("confidence"):
                    entry["c"] = round(float(info["confidence"]), 2)
                if info.get("fired"):
                    entry["fired"] = True
                if entry:
                    strats[name[:12]] = entry
            elif info is not None:
                strats[name[:12]] = str(info)[:30]
        if strats:
            sig["strats"] = strats

    # Ensemble verdict
    if ensemble_result:
        ens = {}
        if isinstance(ensemble_result, dict):
            for k in ("side", "confidence", "action", "votes", "veto"):
                if k in ensemble_result:
                    ens[k[:4]] = ensemble_result[k]
        elif hasattr(ensemble_result, "side"):
            ens["side"] = getattr(ensemble_result, "side", None)
            ens["conf"] = getattr(ensemble_result, "confidence", None)
        if ens:
            sig["ens"] = ens

    # Gate decisions: only blocked gates to save tokens
    if gate_decisions:
        blocked = []
        for g in gate_decisions:
            if isinstance(g, dict) and not g.get("passed", True):
                blocked.append({
                    "g": g.get("name", g.get("gate", "?"))[:15],
                    "v": g.get("value"),
                    "th": g.get("threshold"),
                })
        if blocked:
            sig["blocked"] = blocked
        sig["gates_pass"] = sum(
            1 for g in gate_decisions if isinstance(g, dict) and g.get("passed", True)
        )
        sig["gates_total"] = len(gate_decisions)

    # Multiplier chain: show each step
    if multiplier_chain:
        running = 1.0
        chain = []
        for m in multiplier_chain:
            if isinstance(m, dict):
                val = float(m.get("value", 1.0))
                running *= val
                if abs(val - 1.0) >= 0.01:  # only non-unity multipliers
                    chain.append({
                        "n": m.get("name", "?")[:12],
                        "v": round(val, 3),
                    })
        if chain:
            sig["mults"] = chain
            sig["final_mult"] = round(running, 3)

    # SHADOW EDGES: surface any (symbol, side, strategy) matches so the LLM sees
    # "this is a validated alpha setup" instead of having to remember from prompt context.
    # Wired 2026-05-30 per Nunu's directive: agents must see all evidence available.
    if symbol and strategy_signals:
        matches = []
        for strat_name, info in strategy_signals.items():
            if not isinstance(info, dict): continue
            side = info.get("side")
            fired = info.get("fired", False)
            if not (side and fired): continue
            key = (symbol.upper(), side.upper(), strat_name)
            if key in _AGENT_SHADOW_EDGES:
                edge = _AGENT_SHADOW_EDGES[key]
                matches.append({
                    "setup": f"{symbol} {side} via {strat_name}",
                    "wr": edge["wr"],
                    "n": edge["n"],
                    "note": edge["hypothesis"][:120],
                })
        if matches:
            sig["validated_edges"] = matches
            sig["edge_count"] = len(matches)
        else:
            sig["validated_edges"] = []

    return sig


def _build_position_layer(
    positions: Optional[Dict[str, Any]],
    current_price: float,
) -> Dict[str, Any]:
    """Layer 3: Open position state.

    Token budget: ~100 tokens per position.
    """
    if not positions:
        return {}

    pos_out: Dict[str, Any] = {}

    items = positions.items() if isinstance(positions, dict) else []
    if isinstance(positions, list):
        items = [(p.get("symbol", "?"), p) for p in positions]

    for sym, p in items:
        if isinstance(p, dict):
            entry = {}
            side = p.get("side", "")
            entry_px = float(p.get("entry", p.get("entry_price", 0)))
            if side:
                entry["s"] = side
            if entry_px > 0:
                entry["entry"] = round(entry_px, _price_decimals(entry_px))
                # Unrealized PnL %
                if current_price > 0 and entry_px > 0:
                    if side.upper() in ("LONG", "BUY"):
                        pnl_pct = (current_price - entry_px) / entry_px * 100
                    else:
                        pnl_pct = (entry_px - current_price) / entry_px * 100
                    entry["upnl_pct"] = round(pnl_pct, 2)

            # State machine phase
            state = p.get("state", "")
            if state:
                entry["st"] = state

            # MFE / MAE
            highest = float(p.get("highest_price", p.get("peak_price", 0)))
            lowest = float(p.get("lowest_price", 0))
            if highest > 0 and entry_px > 0:
                mfe = abs(highest - entry_px) / entry_px * 100
                entry["mfe"] = round(mfe, 2)
            if lowest > 0 and entry_px > 0:
                mae = abs(entry_px - lowest) / entry_px * 100
                entry["mae"] = round(mae, 2)

            # Time in trade
            opened_at = p.get("opened_at", p.get("open_time"))
            if opened_at:
                try:
                    if isinstance(opened_at, str):
                        from datetime import datetime as _dt
                        opened_at = _dt.fromisoformat(opened_at.replace("Z", "+00:00"))
                    if hasattr(opened_at, "timestamp"):
                        elapsed_min = (time.time() - opened_at.timestamp()) / 60
                        entry["mins"] = int(elapsed_min)
                except Exception:
                    pass

            # Trailing distance
            trail = float(p.get("trailing_distance", 0))
            if trail > 0 and entry_px > 0:
                entry["trail_pct"] = round(trail / entry_px * 100, 3)

            # Leverage
            lev = p.get("leverage")
            if lev and float(lev) > 1:
                entry["lev"] = round(float(lev), 1)

            # Funding paid
            funding = float(p.get("funding_costs", p.get("funding_paid", 0)))
            if abs(funding) > 0.001:
                entry["fund_cost"] = round(funding, 3)

            if entry:
                pos_out[sym] = entry
        elif hasattr(p, "side"):
            # Position object
            pos_out[sym] = {
                "s": getattr(p, "side", ""),
                "entry": getattr(p, "entry", 0),
                "st": getattr(p, "state", ""),
            }

    return pos_out


def _build_system_layer(
    strategy_weights: Optional[Dict[str, float]],
    kelly_fractions: Optional[Dict[str, float]],
    adaptive_risk_mult: float,
    tuner_state: Optional[Dict],
    ic_values: Optional[Dict[str, float]],
    confidence_floor: float,
    recent_trades: Optional[List[Dict]],
    rejection_counts: Optional[Dict[str, int]],
    pass_rate: float,
    equity: float,
    daily_pnl: float,
    consecutive_losses: int,
    drawdown_pct: float,
) -> Dict[str, Any]:
    """Layer 4: Feedback loops, performance, risk state.

    Token budget: ~150 tokens.
    """
    sys: Dict[str, Any] = {}

    # Equity & PnL
    if equity > 0:
        sys["eq"] = round(equity, 1)
    if abs(daily_pnl) >= 0.01:
        sys["d_pnl"] = round(daily_pnl, 2)
    if consecutive_losses > 0:
        sys["c_loss"] = consecutive_losses
    if abs(drawdown_pct) >= 0.1:
        sys["dd_pct"] = round(drawdown_pct, 1)

    # Strategy weights (only non-default)
    if strategy_weights:
        sw = {k[:12]: round(v, 2) for k, v in strategy_weights.items()
              if abs(v - 1.0) >= 0.05}
        if sw:
            sys["sw"] = sw

    # Kelly fractions
    if kelly_fractions:
        kf = {k[:8]: round(v, 3) for k, v in kelly_fractions.items() if v > 0}
        if kf:
            sys["kelly"] = kf

    # Adaptive risk multiplier
    if abs(adaptive_risk_mult - 1.0) >= 0.05:
        sys["risk_m"] = round(adaptive_risk_mult, 2)

    # Tuner state (calibration offset, IC)
    if tuner_state:
        cal = tuner_state.get("calibration_offset")
        if cal and abs(float(cal)) >= 0.01:
            sys["cal_off"] = round(float(cal), 3)

    # IC values (information coefficient per strategy)
    if ic_values:
        ic = {k[:12]: round(v, 3) for k, v in ic_values.items() if abs(v) >= 0.01}
        if ic:
            sys["ic"] = ic

    if confidence_floor != 65.0:
        sys["conf_floor"] = confidence_floor

    # Pass rate
    if pass_rate > 0:
        sys["pass_rate"] = round(pass_rate, 3)

    # Rejection counts (only meaningful ones)
    if rejection_counts:
        rej = {k[:12]: v for k, v in rejection_counts.items() if v > 0}
        if rej:
            sys["rej"] = rej

    # Recent trades summary (compact)
    if recent_trades:
        wins = sum(1 for t in recent_trades if float(t.get("pnl", 0)) > 0)
        total = len(recent_trades)
        total_pnl = sum(float(t.get("pnl", 0)) for t in recent_trades)
        sys["recent"] = {
            "n": total,
            "wr": round(wins / total, 2) if total > 0 else 0,
            "pnl": round(total_pnl, 2),
        }
        # Last 5 outcomes string (e.g. "WWLWL")
        outcomes = ""
        for t in recent_trades[-5:]:
            outcomes += "W" if float(t.get("pnl", 0)) > 0 else "L"
        if outcomes:
            sys["recent"]["seq"] = outcomes

    return sys


# Cache the most recent skip-stats read so we don't hit disk every snapshot.
# Refreshes if file mtime changes.
_skip_stats_cache = {"mtime": 0, "stats": {}, "symbol_stats": {}}


def _load_recent_skip_stats(symbol: Optional[str] = None) -> Dict[str, Any]:
    """Read counterfactual_pending.jsonl and surface skip patterns.

    Wired 2026-05-30 per Nunu directive: agents should see how often we've been
    skipping similar setups so they can corroborate or contradict their own
    inclination to skip.
    """
    import os, json as _json
    path = os.path.join("data", "llm", "counterfactual_pending.jsonl")
    if not os.path.exists(path):
        return {}
    try:
        mtime = os.path.getmtime(path)
        if mtime == _skip_stats_cache["mtime"] and _skip_stats_cache["stats"]:
            cached = dict(_skip_stats_cache["stats"])
            if symbol:
                cached["this_symbol"] = _skip_stats_cache["symbol_stats"].get(symbol.upper(), {})
            return cached
        # Recompute
        from collections import Counter
        rows = []
        with open(path) as f:
            for line in f:
                try: rows.append(_json.loads(line))
                except Exception: pass
        total = len(rows)
        sym_count = Counter(r.get("symbol", "?") for r in rows)
        side_count = Counter(r.get("side", "?") for r in rows)
        reason_count = Counter(r.get("skip_reason", "?")[:40] for r in rows)
        symbol_stats = {}
        for sym in ("BTC", "ETH", "SOL", "HYPE"):
            sym_rows = [r for r in rows if r.get("symbol") == sym]
            buys = sum(1 for r in sym_rows if r.get("side") == "BUY")
            sells = sum(1 for r in sym_rows if r.get("side") == "SELL")
            symbol_stats[sym] = {"total": len(sym_rows), "buy": buys, "sell": sells}
        stats = {
            "total_skips_today": total,
            "by_symbol_count": dict(sym_count),
            "by_side_count": dict(side_count),
            "top_skip_reasons": dict(reason_count.most_common(3)),
        }
        _skip_stats_cache["mtime"] = mtime
        _skip_stats_cache["stats"] = stats
        _skip_stats_cache["symbol_stats"] = symbol_stats
        if symbol:
            stats = dict(stats)
            stats["this_symbol"] = symbol_stats.get(symbol.upper(), {})
        return stats
    except Exception:
        return {}


def _build_memory_layer(
    lessons: Optional[List[str]],
    hypotheses: Optional[List[str]],
    trade_dna: Optional[Dict],
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """Layer 5: Memory — lessons, hypotheses, trade DNA, live skip patterns.

    Token budget: ~100 tokens (plus ~30 if skip stats present).
    """
    mem: Dict[str, Any] = {}

    if lessons:
        # Keep only last 3, truncated
        mem["lessons"] = [l[:80] for l in lessons[-3:]]

    if hypotheses:
        # Active hypotheses, truncated
        mem["hyp"] = [h[:60] for h in hypotheses[:3]]

    # LIVE SKIP PATTERNS: surface how much we've been skipping similar setups.
    # If a setup has been skipped 30+ times today, that's evidence the LLM should
    # weigh — either we're correctly being cautious, or we're missing alpha.
    skip_stats = _load_recent_skip_stats(symbol)
    if skip_stats:
        mem["live_skip_evidence"] = {
            "total_skips_today": skip_stats.get("total_skips_today", 0),
            "this_symbol_skips": skip_stats.get("this_symbol", {}).get("total", 0),
            "top_reasons": skip_stats.get("top_skip_reasons", {}),
        }

    if trade_dna:
        # Compact DNA summary
        dna = {}
        if isinstance(trade_dna, dict):
            for k in ("best_setup", "worst_setup", "edge_regime", "avoid_regime"):
                if k in trade_dna:
                    dna[k] = str(trade_dna[k])[:40]
            # Win rate by setup type
            wr_map = trade_dna.get("setup_win_rates", trade_dna.get("effectiveness"))
            if wr_map and isinstance(wr_map, dict):
                dna["wr"] = {k[:10]: round(v, 2) if isinstance(v, float) else v
                             for k, v in list(wr_map.items())[:5]}
        if dna:
            mem["dna"] = dna

    return mem


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _price_decimals(price: float) -> int:
    """Choose rounding precision based on price magnitude."""
    if price >= 10000:
        return 1
    if price >= 100:
        return 2
    if price >= 1:
        return 3
    if price >= 0.01:
        return 5
    return 8


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_comprehensive_snapshot(
    # Market data
    symbol: str,
    data: Dict[str, Any],
    current_price: float,
    all_prices: Optional[Dict[str, float]] = None,

    # Funding / OI
    funding_rates: Optional[Dict[str, float]] = None,
    open_interest: Optional[Dict[str, float]] = None,

    # Signal pipeline state
    strategy_signals: Optional[Dict[str, Any]] = None,
    ensemble_result: Any = None,
    gate_decisions: Optional[List[Dict]] = None,
    multiplier_chain: Optional[List[Dict]] = None,

    # Position state
    positions: Optional[Dict[str, Any]] = None,

    # Feedback loop states
    strategy_weights: Optional[Dict[str, float]] = None,
    kelly_fractions: Optional[Dict[str, float]] = None,
    adaptive_risk_mult: float = 1.0,
    tuner_state: Optional[Dict] = None,
    ic_values: Optional[Dict[str, float]] = None,
    confidence_floor: float = 65.0,

    # System performance
    recent_trades: Optional[List[Dict]] = None,
    rejection_counts: Optional[Dict[str, int]] = None,
    pass_rate: float = 0.0,
    equity: float = 500.0,
    daily_pnl: float = 0.0,
    consecutive_losses: int = 0,
    drawdown_pct: float = 0.0,

    # Memory
    lessons: Optional[List[str]] = None,
    hypotheses: Optional[List[str]] = None,
    trade_dna: Optional[Dict] = None,

    # Time context
    current_utc_hour: Optional[int] = None,
    day_of_week: Optional[str] = None,
    session: Optional[str] = None,

    # Liquidation levels
    liquidation_levels: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Build the complete snapshot for the agent neural network.

    Returns a dict with 6 layers:
      market   — technicals, funding, OI, cross-asset
      signals  — per-strategy, ensemble, gates, multipliers
      positions — open positions with MFE/MAE, state, timing
      system   — equity, PnL, feedback loops, rejections
      memory   — lessons, hypotheses, trade DNA
      time     — UTC hour, day, session

    Total size target: 500-800 JSON tokens.
    """
    now = datetime.now(timezone.utc)
    if current_utc_hour is None:
        current_utc_hour = now.hour
    if day_of_week is None:
        day_of_week = now.strftime("%A")
    if session is None:
        h = current_utc_hour
        if 0 <= h < 8:
            session = "asia"
        elif 8 <= h < 13:
            session = "london"
        elif 13 <= h < 21:
            session = "us"
        else:
            session = "quiet"

    snapshot: Dict[str, Any] = {}

    # -- LAYER 1: MARKET --
    try:
        snapshot["market"] = _build_market_layer(
            symbol, data, current_price, all_prices,
            funding_rates, open_interest, liquidation_levels,
        )
    except Exception as e:
        logger.warning(f"[SNAPSHOT] Market layer error: {e}")
        snapshot["market"] = {"sym": symbol, "px": current_price}

    # -- LAYER 2: SIGNALS --
    try:
        snapshot["signals"] = _build_signal_layer(
            strategy_signals, ensemble_result, gate_decisions, multiplier_chain,
            symbol=symbol,  # passes through so shadow edge matching can run
        )
    except Exception as e:
        logger.warning(f"[SNAPSHOT] Signal layer error: {e}")
        snapshot["signals"] = {}

    # -- LAYER 3: POSITIONS --
    try:
        snapshot["positions"] = _build_position_layer(positions, current_price)
    except Exception as e:
        logger.warning(f"[SNAPSHOT] Position layer error: {e}")
        snapshot["positions"] = {}

    # -- LAYER 4: SYSTEM STATE --
    try:
        snapshot["system"] = _build_system_layer(
            strategy_weights, kelly_fractions, adaptive_risk_mult,
            tuner_state, ic_values, confidence_floor,
            recent_trades, rejection_counts, pass_rate,
            equity, daily_pnl, consecutive_losses, drawdown_pct,
        )
    except Exception as e:
        logger.warning(f"[SNAPSHOT] System layer error: {e}")
        snapshot["system"] = {"eq": equity}

    # -- LAYER 5: MEMORY --
    try:
        snapshot["memory"] = _build_memory_layer(lessons, hypotheses, trade_dna, symbol=symbol)
    except Exception as e:
        logger.warning(f"[SNAPSHOT] Memory layer error: {e}")
        snapshot["memory"] = {}

    # -- LAYER 6: TIME CONTEXT --
    snapshot["time"] = {
        "utc_h": current_utc_hour,
        "day": day_of_week[:3],
        "sess": session,
    }

    return snapshot


def snapshot_to_compact_json(snapshot: Dict[str, Any]) -> str:
    """Serialize snapshot to minimal JSON for agent prompts."""
    import json
    return json.dumps(snapshot, separators=(",", ":"), default=str)


def extract_layer(snapshot: Dict[str, Any], *layers: str) -> Dict[str, Any]:
    """Extract specific layers from the snapshot for per-agent input.

    Usage:
        regime_input = extract_layer(snap, "market", "time")
        risk_input = extract_layer(snap, "market", "positions", "system")
    """
    return {k: snapshot.get(k, {}) for k in layers if k in snapshot}
