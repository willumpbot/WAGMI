"""Live Quant Analyst scheduler.

Runs every N minutes per symbol:
  1. Fetch live OHLCV (daily / 4h / 1h)
  2. Compute indicators (EMA20/50, RSI14, ATR, support/resistance)
  3. Generate chart PNGs (re-uses chart_thread.py logic)
  4. Run agent committee via Claude CLI (Regime + Trade + Critic + Risk)
  5. Save everything to web/public/thesis/{symbol}/

Usage:
    python tools/live_analyst.py                    # one pass over all 4 symbols
    python tools/live_analyst.py --loop             # run forever every 10min
    python tools/live_analyst.py --loop --interval 300   # every 5min
    python tools/live_analyst.py --symbols BTC ETH  # specific symbols only
    python tools/live_analyst.py --no-agents        # skip LLM, just charts + heuristics
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import ccxt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from llm.claude_cli_client import call_agent, available as cli_available

# Where the scheduler writes outputs — served by both API and frontend
OUT_ROOT = ROOT.parent / "web" / "public" / "thesis"
OUT_ROOT.mkdir(parents=True, exist_ok=True)

DEFAULT_SYMBOLS = ["BTC", "ETH", "SOL", "HYPE"]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("live_analyst")


# =================== data + indicators ===================

def get_exchange():
    ex = ccxt.hyperliquid()
    ex.load_markets()
    return ex


def fetch_ohlcv(ex, symbol: str, tf: str, limit: int):
    sym = f"{symbol}/USDC:USDC"
    c = ex.fetch_ohlcv(sym, tf, limit=limit)
    if not c:
        return None
    return {
        "t": [x[0] for x in c],
        "o": np.array([x[1] for x in c]),
        "h": np.array([x[2] for x in c]),
        "l": np.array([x[3] for x in c]),
        "c": np.array([x[4] for x in c]),
        "v": np.array([x[5] for x in c]),
    }


def ema(arr: np.ndarray, n: int) -> np.ndarray:
    alpha = 2 / (n + 1)
    out = [arr[0]]
    for v in arr[1:]:
        out.append(alpha * v + (1 - alpha) * out[-1])
    return np.array(out)


def rsi14(closes: np.ndarray) -> float:
    if len(closes) < 15:
        return 50.0
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    g = float(np.mean(gains[-14:]))
    l = float(np.mean(losses[-14:]))
    return 100 - 100 / (1 + g / max(l, 1e-9))


def atr14(h, l, c) -> float:
    if len(c) < 15:
        return 0.0
    tr = np.maximum(h[1:] - l[1:], np.abs(h[1:] - c[:-1]))
    tr = np.maximum(tr, np.abs(l[1:] - c[:-1]))
    return float(np.mean(tr[-14:]))


def compute_levels(symbol: str, ex) -> Dict[str, Any]:
    """Multi-timeframe indicator + level bundle for one symbol."""
    logger.info(f"[{symbol}] fetching OHLCV...")
    d1 = fetch_ohlcv(ex, symbol, "1d", 60)
    h4 = fetch_ohlcv(ex, symbol, "4h", 100)
    h1 = fetch_ohlcv(ex, symbol, "1h", 96)
    m5 = fetch_ohlcv(ex, symbol, "5m", 100)
    if not all([d1, h4, h1, m5]):
        return {}

    ticker = ex.fetch_ticker(f"{symbol}/USDC:USDC")
    price = float(ticker["last"])

    # Daily
    e20_d = ema(d1["c"], 20)
    e50_d = ema(d1["c"], min(50, len(d1["c"]) // 2))
    slope_d = (float(e20_d[-1]) - float(e20_d[-10])) / float(e20_d[-10]) * 100

    # 1h
    e20_1 = ema(h1["c"], 20)
    e50_1 = ema(h1["c"], 50)

    # 4h
    e20_4 = ema(h4["c"], 20)
    e50_4 = ema(h4["c"], 50)

    return {
        "symbol": symbol,
        "ts": datetime.now(timezone.utc).isoformat(),
        "price": price,
        "daily": {
            "ema20": float(e20_d[-1]), "ema50": float(e50_d[-1]),
            "slope_pct": slope_d, "rsi14": rsi14(d1["c"]),
            "atr14": atr14(d1["h"], d1["l"], d1["c"]),
            "hi60d": float(np.max(d1["h"])), "lo60d": float(np.min(d1["l"])),
            "trend": ("UP" if e20_d[-1] > e50_d[-1] and slope_d > 0.2
                      else ("DOWN" if e20_d[-1] < e50_d[-1] and slope_d < -0.2
                            else "FLAT")),
        },
        "h4": {
            "ema20": float(e20_4[-1]), "ema50": float(e50_4[-1]),
            "rsi14": rsi14(h4["c"]),
            "atr14": atr14(h4["h"], h4["l"], h4["c"]),
            "hi20": float(np.max(h4["h"][-20:])), "lo20": float(np.min(h4["l"][-20:])),
        },
        "h1": {
            "ema20": float(e20_1[-1]), "ema50": float(e50_1[-1]),
            "rsi14": rsi14(h1["c"]),
            "atr14": atr14(h1["h"], h1["l"], h1["c"]),
            "hi20": float(np.max(h1["h"][-20:])), "lo20": float(np.min(h1["l"][-20:])),
            "vol_ratio": float(np.mean(h1["v"][-3:]) / max(np.mean(h1["v"][-20:]), 1e-9)),
        },
        "m5": {
            "rsi14": rsi14(m5["c"]),
            "atr14": atr14(m5["h"], m5["l"], m5["c"]),
        },
    }


def levels_to_summary(L: Dict[str, Any]) -> str:
    """Compress indicator bundle into ~300 token prompt for the LLM agents."""
    if not L:
        return "NO DATA"
    s = L["symbol"]
    p = L["price"]
    d = L["daily"]; h4 = L["h4"]; h1 = L["h1"]; m5 = L["m5"]
    return (
        f"{s} live ${p:,.2f} ({L['ts']})\n"
        f"Daily: trend {d['trend']} (slope {d['slope_pct']:+.2f}%/10d) RSI {d['rsi14']:.0f} "
        f"EMA20 ${d['ema20']:,.0f} EMA50 ${d['ema50']:,.0f} ATR {d['atr14']/p*100:.2f}% "
        f"60d range ${d['lo60d']:,.0f}-${d['hi60d']:,.0f}\n"
        f"4h:    RSI {h4['rsi14']:.0f} EMA20 ${h4['ema20']:,.0f} EMA50 ${h4['ema50']:,.0f} "
        f"ATR {h4['atr14']/p*100:.2f}% range ${h4['lo20']:,.0f}-${h4['hi20']:,.0f}\n"
        f"1h:    RSI {h1['rsi14']:.0f} EMA20 ${h1['ema20']:,.0f} EMA50 ${h1['ema50']:,.0f} "
        f"ATR {h1['atr14']/p*100:.2f}% range ${h1['lo20']:,.0f}-${h1['hi20']:,.0f} vol {h1['vol_ratio']:.2f}x\n"
        f"5m:    RSI {m5['rsi14']:.0f} ATR {m5['atr14']/p*100:.2f}%"
    )


# =================== agent committee ===================

REGIME_PROMPT_SYSTEM = (
    "You are the WAGMI Regime Agent. Classify market regime from the data. "
    "Write a 2-3 sentence analysis. Be specific about the regime label "
    "(trending_bull/trending_bear/range/high_volatility/low_liquidity/unknown), "
    "directional bias, and volatility band. Keep it under 200 words."
)

TRADE_PROMPT_SYSTEM = (
    "You are the WAGMI Trade Agent. Given regime + market data, form an actionable "
    "thesis: go_long, go_short, or wait. Name the entry zone, stop, and target(s). "
    "Cite specific confluence factors. Keep it under 250 words, prose is fine."
)

CRITIC_PROMPT_SYSTEM = (
    "You are the WAGMI Critic Agent. Stress-test the thesis. If you want to veto, "
    "explain why and propose a counter-thesis. If pass, name the main risk anyway. "
    "Under 200 words."
)

RISK_PROMPT_SYSTEM = (
    "You are the WAGMI Risk Agent. Given thesis + equity + positions, propose "
    "sizing (size_multiplier 0-2x, leverage 1-10x, max loss %). Cite risk flags. "
    "Under 150 words."
)


# Project knowledge, split by epistemic strength.
# STRUCTURAL = physics of price action + statistical invariants — trust heavily.
# HISTORICAL = backward-looking base rates — trust directionally, expect drift.
# LIVE = real-time predictive model outputs — trust when fresh, verify when stale.

_KB_STRUCTURAL = """
STRUCTURAL TRUTHS (physics of markets + Bonferroni-cleared statistical invariants):
- Reversal probability by R-multiple (n=121, Bonferroni-cleared):
    0.5R -> 25% reversal, 1.0R -> 15.6%, 1.5R -> 6.7%, 2R -> 20%, 5R -> 32%
    => the zone where reversal drops below 10% is 1.5R. Don't BE earlier.
- State-machine invariant: 80% of trades die IDLE->OPEN->CLOSED (never reach TRAILING).
    Of the 20% that DO reach TRAILING, historical WR is 100%. Structural edge is
    getting trades to TRAILING, not picking winners.
- Bonferroni-cleared alpha ICs (survived strictest multi-comparison correction):
    btc_4h_return_signed  IC +0.519  (universal across 8 symbol*side cells)
    rsi_div_1h_6h_aligned IC +0.456
    chop_score_proxy      IC -0.384  (inverse: high chop = low edge)
    conviction_count      z-score 3.615 (p=0.0003)
- Conviction stacking super-additivity (n=145, Cochran-Armitage p=0.0003):
    0 aligned=0%WR  1=20%  2=38%  4=61% WR, PF 4.12 at 4-aligned.
    Each additional aligned signal contributes > its marginal.
- Stop-hunting structural fact: 52% of SL-hits within 30-min window are hunts
    (price returns to original direction). 1.5x ATR beyond the obvious stop
    level saves 35% of losses.
- Overconfidence curve: model outputs >= 95% confidence HISTORICALLY lose
    money (n=1,381, -$18.4k). This is a model-calibration truth, not a
    trading rule. Treat extreme confidence as suspicious.
"""

_KB_HISTORICAL = """
HISTORICAL STATISTICS (base rates — may drift, use as context not commandment):
- Confidence bin WR table (n=5,787 trades):
    65-70 bin: WR 37.7% (+$24,782 cumulative)  <- positive despite low WR (good R:R)
    70-75:    20.6% (+$10,199)                  <- unusual: low WR, positive PnL
    85-90:    74.7% (+$68,874)                  <- HIGHEST WR
    90-100:   22.7% (-$18,364)                  <- OVERCONFIDENCE TRAP
- Time-of-day WR (4 symbols, Apr 2026):
    UTC 00-03: 24%   04-07: 15% (DEAD)   08-11: 43%
    UTC 12-15: 36%   16-19: 29%          20-23: 55% (BEST)
  NOTE: These are period-specific. Current market may differ.
  Use as prior, not gospel.
"""

_KB_REASONING_RULES = """
HOW TO REASON (our edge framework):
1. Start from STRUCTURAL truths (reversal curve, state-machine, Bonferroni ICs).
2. Layer in LIVE predictive model outputs when present.
3. Cross-check against HISTORICAL base rates but weight them less.
4. The real edge is STRUCTURAL (letting winners reach TRAILING) + ALPHA STACK
   (Bonferroni-cleared signals aligned) rather than chasing high-WR buckets.
5. Overconfidence is the enemy. Favor conviction-count >= 2 with structural
   confluence over any single high-WR cell.
6. When in doubt: wait for conviction to stack (4-aligned = 61% WR PF 4.12) or
   skip entirely. No-trade is often the best trade.
"""


def _kb_static() -> str:
    return f"{_KB_STRUCTURAL}\n{_KB_HISTORICAL}\n{_KB_REASONING_RULES}"


# Back-compat alias
_KB_STATIC = _kb_static()


def _graduated_rules_for(symbol: str) -> str:
    """Load WAGMI's graduated-rules.json and format any active rules matching this symbol."""
    try:
        rules_path = ROOT / "data" / "llm" / "graduated_rules.json"
        if not rules_path.exists():
            return ""
        data = json.loads(rules_path.read_text(encoding="utf-8"))
        rules = data.get("rules", []) if isinstance(data, dict) else []
        applicable = []
        for r in rules:
            if not r.get("active"):
                continue
            conds = r.get("conditions", {}) or {}
            sym_match = conds.get("symbol") in (None, "", symbol, "ALL")
            if sym_match:
                applicable.append(r)
        if not applicable:
            return ""
        lines = ["\nWAGMI GRADUATED RULES (our codified edges, apply when conditions match):"]
        for r in applicable[:10]:  # cap to 10 most important
            conds = r.get("conditions", {}) or {}
            cond_str = " & ".join(f"{k}={v}" for k, v in conds.items())
            lines.append(
                f"- {r.get('hypothesis_statement','')} "
                f"[{r.get('action')}/{r.get('adjustment','?')}] "
                f"when {cond_str} (conf {r.get('confidence',0):.0%}, n={r.get('total_evidence','?')})"
            )
        return "\n".join(lines)
    except Exception as e:
        logger.debug(f"graduated_rules load failed: {e}")
        return ""


def compute_live_factors(symbol: str, levels: Dict[str, Any]) -> Dict[str, Any]:
    """Compute Bonferroni-cleared factor alignment from current market data.
    Returns a structured dict (for storage + API). The string prompt form is
    built from this same dict by _live_factor_status_prompt."""
    if not levels:
        return {}
    h4 = levels.get("h4", {}) or {}
    h1 = levels.get("h1", {}) or {}

    h4_rsi = h4.get("rsi14", 50)
    h4_ema20 = h4.get("ema20", 0)
    price = levels.get("price", 0)

    if h4_rsi > 55 and price > h4_ema20:
        btc_4h_direction = "bullish"
    elif h4_rsi < 45 and price < h4_ema20:
        btc_4h_direction = "bearish"
    else:
        btc_4h_direction = "neutral"

    h1_atr = h1.get("atr14", 0)
    h1_range = h1.get("hi20", 0) - h1.get("lo20", 0)
    chop_est = round(h1_atr / max(h1_range, 1e-9), 2) if h1_range else 0.0
    chop_ok = chop_est < 0.6

    h1_rsi = h1.get("rsi14", 50)
    rsi_aligned = (h1_rsi > 50) == (h4_rsi > 50)
    rsi_bullish_stack = rsi_aligned and h1_rsi > 50

    count = 0
    if btc_4h_direction == "bullish":
        count += 1
    if chop_ok:
        count += 1
    if rsi_bullish_stack:
        count += 1
    # Fourth factor: daily trend up (we already have this as structural)
    if levels.get("daily", {}).get("trend") == "UP":
        count += 1

    # Historical WR for conviction count (from Conviction Stacking study)
    wr_by_count = {0: 0, 1: 20, 2: 38, 3: 50, 4: 61}
    return {
        "btc_4h_direction": btc_4h_direction,           # bullish/bearish/neutral
        "btc_4h_aligned_long": btc_4h_direction == "bullish",
        "chop_score": chop_est,
        "chop_ok": chop_ok,
        "rsi_aligned": rsi_aligned,
        "rsi_bullish_stack": rsi_bullish_stack,
        "daily_trend_up": levels.get("daily", {}).get("trend") == "UP",
        "conviction_count": count,
        "conviction_max": 4,
        "conviction_wr_est": wr_by_count.get(count, 50),
    }


def _live_factor_status(symbol: str, levels: Dict[str, Any]) -> str:
    """Format the live factor status as a prompt block."""
    f = compute_live_factors(symbol, levels)
    if not f:
        return ""
    return (
        "\nLIVE FACTOR STATUS (Bonferroni-cleared, evaluated right now):\n"
        f"  btc_4h_return_signed: {f['btc_4h_direction']}   (for long entries: bullish=aligned)\n"
        f"  chop_score_proxy:    {f['chop_score']:.2f}    "
        f"({'OK (< 0.60)' if f['chop_ok'] else 'HIGH (avoid)'})\n"
        f"  rsi_div_aligned:     {'YES' if f['rsi_aligned'] else 'NO'} (1h vs 4h RSI regime match)\n"
        f"  conviction_count:    {f['conviction_count']}/{f['conviction_max']} aligned signals "
        f"(hist WR {f['conviction_wr_est']}%; KB: 0=0%WR 1=20% 2=38% 4=61%PF4.12)"
    )


def build_knowledge_block(symbol: str, levels: Optional[Dict[str, Any]] = None) -> str:
    """Compose the KB prompt for a specific symbol, including:
    - static structural truths + historical base rates + reasoning rules
    - graduated rules matching this symbol
    - LIVE factor status (Bonferroni alignment right now)
    """
    out = _KB_STATIC
    if levels:
        out += _live_factor_status(symbol, levels)
    out += _graduated_rules_for(symbol)
    return out


# Back-compat: some call sites expect KNOWLEDGE_BLOCK constant
KNOWLEDGE_BLOCK = _KB_STATIC


def agent_regime(summary: str, levels: Dict[str, Any], skip: bool) -> Dict[str, Any]:
    """Returns {narrative: prose, regime: heuristic_label, confidence: int, ...}.
    Prose comes from LLM; structured fields from heuristic on levels."""
    fields = _derive_regime_fields(levels)
    if skip or not cli_available():
        return {"ok": True, "agent": "regime", "narrative": _heuristic_regime_prose(levels), **fields}
    kb = build_knowledge_block(levels.get("symbol", ""), levels)
    prompt = (
        f"{kb}\n\n"
        f"Market snapshot:\n{summary}\n\n"
        "Analyze the regime. Name the regime label, directional bias, and volatility band. "
        "Reference the knowledge base when relevant. 2-3 sentences."
    )
    r = call_agent(prompt, REGIME_PROMPT_SYSTEM, model="sonnet", max_budget_usd=0.10, timeout=60)
    narrative = (r.text or "").strip() if r.ok else _heuristic_regime_prose(levels)
    return {"ok": r.ok, "agent": "regime", "narrative": narrative,
            "latency_s": r.latency_s if r.ok else 0, **fields}


def agent_trade(summary: str, levels: Dict[str, Any], regime_out: Dict[str, Any], skip: bool) -> Dict[str, Any]:
    fields = _derive_trade_fields(levels, regime_out)
    if skip or not cli_available():
        return {"ok": True, "agent": "trade", "narrative": _heuristic_trade_prose(levels, regime_out), **fields}
    kb = build_knowledge_block(levels.get("symbol", ""), levels)
    prompt = (
        f"{kb}\n\n"
        f"Regime verdict: {regime_out.get('regime_label','?')} bias={regime_out.get('bias','?')}\n\n"
        f"Market snapshot:\n{summary}\n\n"
        "Form a thesis: go_long / go_short / wait. Name entry zone, stop, target(s). "
        "Cite the specific confluence. Reference the knowledge base base-rates. "
        "2-4 sentences."
    )
    r = call_agent(prompt, TRADE_PROMPT_SYSTEM, model="sonnet", max_budget_usd=0.10, timeout=90)
    narrative = (r.text or "").strip() if r.ok else _heuristic_trade_prose(levels, regime_out)
    return {"ok": r.ok, "agent": "trade", "narrative": narrative,
            "latency_s": r.latency_s if r.ok else 0, **fields}


def agent_critic(summary: str, levels: Dict[str, Any], trade_out: Dict[str, Any], skip: bool) -> Dict[str, Any]:
    fields = _derive_critic_fields(levels, trade_out)
    if skip or not cli_available():
        return {"ok": True, "agent": "critic", "narrative": _heuristic_critic_prose(levels, trade_out), **fields}
    kb = build_knowledge_block(levels.get("symbol", ""), levels)
    prompt = (
        f"{kb}\n\n"
        f"Trade thesis action={trade_out.get('action','?')}: {trade_out.get('narrative','')[:250]}\n\n"
        f"Market snapshot:\n{summary}\n\n"
        "Stress-test this thesis. Name the #1 risk or counter-thesis. "
        "Pass/reduce/veto? 2-3 sentences."
    )
    r = call_agent(prompt, CRITIC_PROMPT_SYSTEM, model="sonnet", max_budget_usd=0.10, timeout=60)
    narrative = (r.text or "").strip() if r.ok else _heuristic_critic_prose(levels, trade_out)
    return {"ok": r.ok, "agent": "critic", "narrative": narrative,
            "latency_s": r.latency_s if r.ok else 0, **fields}


# -------- heuristic derivers (structured fields, always deterministic) --------

def _derive_regime_fields(L: Dict[str, Any]) -> Dict[str, Any]:
    if not L:
        return {"regime_label": "unknown", "confidence": 0, "bias": "neutral", "vol_band": "medium"}
    d, h1 = L["daily"], L["h1"]
    atr_pct = d["atr14"] / L["price"] * 100
    if d["trend"] == "UP" and d["slope_pct"] > 0.5:
        label, bias, conf = "trending_bull", "bullish", 70
    elif d["trend"] == "DOWN" and d["slope_pct"] < -0.5:
        label, bias, conf = "trending_bear", "bearish", 70
    elif abs(d["slope_pct"]) < 0.3:
        label, bias, conf = "range", "neutral", 60
    else:
        label, bias, conf = "unknown", "neutral", 40
    if atr_pct > 5:
        vol = "high"
    elif atr_pct > 2.5:
        vol = "medium"
    else:
        vol = "low"
    return {"regime_label": label, "confidence": conf, "bias": bias, "vol_band": vol,
            "daily_slope_pct": round(d["slope_pct"], 2), "daily_rsi": round(d["rsi14"], 0),
            "h1_rsi": round(h1["rsi14"], 0), "vol_ratio_1h": round(h1["vol_ratio"], 2)}


def _derive_trade_fields(L: Dict[str, Any], regime_out: Dict[str, Any]) -> Dict[str, Any]:
    if not L:
        return {"action": "wait", "confidence": 0}
    p = L["price"]
    h1, h4 = L["h1"], L["h4"]
    # Support/resistance from 1h
    resistance = h1["hi20"]
    support = h1["lo20"]
    atr = h1["atr14"]
    bias = regime_out.get("bias", "neutral")
    rsi5 = L["m5"]["rsi14"]

    # Decision logic
    if bias == "bullish":
        if rsi5 > 75:
            action, conf = "wait", 55  # overbought, wait pullback
            entry_low, entry_high = h1["ema20"] * 0.998, h1["ema20"] * 1.002
            stop = support - atr * 0.3
            t1, t2 = resistance, L["daily"]["hi60d"]
        elif p < h1["ema20"]:
            action, conf = "go_long", 65
            entry_low, entry_high = p * 0.998, p * 1.002
            stop = support - atr * 0.3
            t1, t2 = resistance, L["daily"]["hi60d"]
        else:
            action, conf = "wait", 60
            entry_low, entry_high = h1["ema20"] * 0.998, h1["ema20"] * 1.002
            stop = support - atr * 0.3
            t1, t2 = resistance, L["daily"]["hi60d"]
    elif bias == "bearish":
        if rsi5 < 25:
            action, conf = "wait", 55
            entry_low, entry_high = h1["ema20"] * 0.998, h1["ema20"] * 1.002
            stop = resistance + atr * 0.3
            t1, t2 = support, L["daily"]["lo60d"]
        elif p > h1["ema20"]:
            action, conf = "go_short", 65
            entry_low, entry_high = p * 0.998, p * 1.002
            stop = resistance + atr * 0.3
            t1, t2 = support, L["daily"]["lo60d"]
        else:
            action, conf = "wait", 60
            entry_low, entry_high = h1["ema20"] * 0.998, h1["ema20"] * 1.002
            stop = resistance + atr * 0.3
            t1, t2 = support, L["daily"]["lo60d"]
    else:
        action, conf = "wait", 40
        entry_low, entry_high = p * 0.997, p * 1.003
        stop = support - atr * 0.3
        t1, t2 = resistance, L["daily"]["hi60d"]

    # R:R
    rr1 = abs(t1 - (entry_high + entry_low) / 2) / max(abs(stop - (entry_high + entry_low) / 2), 1e-9)
    rr2 = abs(t2 - (entry_high + entry_low) / 2) / max(abs(stop - (entry_high + entry_low) / 2), 1e-9)

    return {
        "action": action, "confidence": conf,
        "entry_low": round(entry_low, 2), "entry_high": round(entry_high, 2),
        "stop": round(stop, 2), "target1": round(t1, 2), "target2": round(t2, 2),
        "rr_t1": round(rr1, 2), "rr_t2": round(rr2, 2),
        "invalidation": round(L["daily"]["ema50"], 2),
    }


def _derive_critic_fields(L: Dict[str, Any], trade_out: Dict[str, Any]) -> Dict[str, Any]:
    """Flag risk conditions."""
    if not L:
        return {"vote": "veto", "risk_flags": ["no_data"]}
    p = L["price"]
    flags = []
    rsi5 = L["m5"]["rsi14"]
    rsi1 = L["h1"]["rsi14"]
    vol_1h = L["h1"]["vol_ratio"]
    atr_pct_1h = L["h1"]["atr14"] / p * 100

    if vol_1h < 0.5:
        flags.append("thin_volume")
    if rsi5 > 78:
        flags.append("rsi5m_overbought")
    elif rsi5 < 22:
        flags.append("rsi5m_oversold")
    if rsi1 > 75:
        flags.append("rsi1h_overbought")
    elif rsi1 < 25:
        flags.append("rsi1h_oversold")
    if atr_pct_1h < 0.3:
        flags.append("compressed_vol")
    if trade_out.get("action") in ("go_long", "go_short") and (rsi5 > 78 or rsi5 < 22):
        vote = "reduce"
    elif vol_1h < 0.3 and trade_out.get("action") != "wait":
        vote = "veto"
    else:
        vote = "pass"
    return {"vote": vote, "risk_flags": flags}


# -------- heuristic prose (fallback narratives) --------

def _heuristic_regime_prose(L: Dict[str, Any]) -> str:
    if not L:
        return "No data available."
    d = L["daily"]
    return (f"Daily trend {d['trend']} with slope {d['slope_pct']:+.2f}%/10d and RSI {d['rsi14']:.0f}. "
            f"Price {(L['price']-d['ema20'])/d['ema20']*100:+.2f}% vs daily EMA20 "
            f"(${d['ema20']:,.0f}). ATR {d['atr14']/L['price']*100:.2f}% — "
            f"{'extended' if abs((L['price']-d['ema20'])/d['ema20']*100) > 5 else 'healthy'} momentum.")


def _heuristic_trade_prose(L: Dict[str, Any], regime_out: Dict[str, Any]) -> str:
    if not L:
        return "No trade thesis — data unavailable."
    bias = regime_out.get("bias", "neutral")
    rsi5 = L["m5"]["rsi14"]
    h1 = L["h1"]
    if bias == "bullish":
        if rsi5 > 75:
            return (f"Bullish structure but 5m RSI {rsi5:.0f} overbought. Wait for pullback to "
                    f"${h1['ema20']:,.0f} (1h EMA20), stop at ${h1['lo20']:,.0f}.")
        return (f"Bullish bias intact. Long entry near ${h1['ema20']:,.0f} (1h EMA20) with stop "
                f"below ${h1['lo20']:,.0f} (1h support). Target ${h1['hi20']:,.0f} then "
                f"${L['daily']['hi60d']:,.0f}.")
    if bias == "bearish":
        return (f"Bearish bias. Short opportunity on bounce to ${h1['ema20']:,.0f}, stop above "
                f"${h1['hi20']:,.0f}. Target ${h1['lo20']:,.0f} then ${L['daily']['lo60d']:,.0f}.")
    return (f"Range/unclear regime. No directional edge. Wait for breakout of "
            f"${h1['lo20']:,.0f}-${h1['hi20']:,.0f}.")


def _heuristic_critic_prose(L: Dict[str, Any], trade_out: Dict[str, Any]) -> str:
    if not L:
        return "No data to critique."
    action = trade_out.get("action", "wait")
    flags = _derive_critic_fields(L, trade_out).get("risk_flags", [])
    if action == "wait":
        return "Pass — no trade proposed. Waiting is the right call when confluence is absent."
    risk_lines = ", ".join(flags) if flags else "none major"
    return f"Primary risks: {risk_lines}. Size down if any conviction factor missing."


# (heuristic field-derivers and prose fallbacks are defined above, next to the agents they serve)


# =================== output writer ===================

def write_thesis(symbol: str, levels: Dict[str, Any], committee: Dict[str, Any]) -> Path:
    """Save full thesis bundle to web/public/thesis/{symbol}/."""
    out = OUT_ROOT / symbol.lower()
    out.mkdir(exist_ok=True)

    thesis = {
        "symbol": symbol,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "price": levels.get("price"),
        "levels": levels,
        "factors": compute_live_factors(symbol, levels),
        "committee": committee,
    }
    (out / "thesis.json").write_text(json.dumps(thesis, indent=2, default=str))
    try:
        from tools.thesis_tracker import log_thesis
        log_thesis(thesis)
    except Exception:
        pass
    return out


def generate_charts(symbol: str, out_dir: Path):
    """Invoke chart_thread.py to render the 5 PNGs into out_dir."""
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "chart_thread.py"),
             symbol, "--mode", "thread", "--out", str(out_dir)],
            capture_output=True, text=True, timeout=90,
        )
        if result.returncode != 0:
            logger.warning(f"[{symbol}] chart gen exit {result.returncode}: {result.stderr[:200]}")
    except Exception as e:
        logger.warning(f"[{symbol}] chart gen failed: {e}")


# =================== main pass ===================

def run_once(symbols: List[str], skip_agents: bool = False) -> None:
    ex = get_exchange()
    for s in symbols:
        t0 = time.time()
        logger.info(f"[{s}] === pass start ===")
        try:
            levels = compute_levels(s, ex)
            if not levels:
                logger.warning(f"[{s}] no data, skipping")
                continue

            summary = levels_to_summary(levels)
            logger.info(f"[{s}] summary built ({len(summary)} chars)")

            regime_out = agent_regime(summary, levels, skip=skip_agents)
            logger.info(f"[{s}] regime: {regime_out.get('regime_label', '?')} conf={regime_out.get('confidence', 0)}")

            trade_out = agent_trade(summary, levels, regime_out, skip=skip_agents)
            logger.info(f"[{s}] trade: {trade_out.get('action', '?')} conf={trade_out.get('confidence', 0)}")

            critic_out = agent_critic(summary, levels, trade_out, skip=skip_agents)
            logger.info(f"[{s}] critic: {critic_out.get('vote', '?')}")

            committee = {
                "regime": regime_out,
                "trade": trade_out,
                "critic": critic_out,
                "mode": "cli" if (cli_available() and not skip_agents) else "heuristic",
            }

            out_dir = write_thesis(s, levels, committee)
            generate_charts(s, out_dir)

            logger.info(f"[{s}] === pass done in {time.time()-t0:.1f}s ===")
        except Exception as e:
            logger.exception(f"[{s}] pass failed: {e}")


def main():
    ap = argparse.ArgumentParser(description="Live Quant Analyst scheduler")
    ap.add_argument("--symbols", nargs="+", default=DEFAULT_SYMBOLS,
                    help="Symbols to analyze (e.g. BTC ETH SOL HYPE)")
    ap.add_argument("--loop", action="store_true", help="Run forever every --interval seconds")
    ap.add_argument("--interval", type=int, default=600, help="Loop interval seconds (default 600 = 10min)")
    ap.add_argument("--no-agents", action="store_true", help="Skip LLM, use heuristics only")
    args = ap.parse_args()

    symbols = [s.upper() for s in args.symbols]
    logger.info(f"Starting analyst — symbols={symbols} loop={args.loop} "
                f"interval={args.interval}s agents={'off' if args.no_agents else 'on'} "
                f"cli_available={cli_available()}")

    if args.loop:
        while True:
            run_once(symbols, skip_agents=args.no_agents)
            logger.info(f"Sleeping {args.interval}s...")
            time.sleep(args.interval)
    else:
        run_once(symbols, skip_agents=args.no_agents)


if __name__ == "__main__":
    main()
