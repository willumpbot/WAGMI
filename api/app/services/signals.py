"""
Async market signal engine for NunuIRL Platform.

Fetches CoinGecko market data, computes indicators (SMA20/50, RSI14, ATR proxy, vol_spike),
calculates ATR-based zones, assigns safe action labels (no BUY/SELL wording), and maintains
a global state that updates every 60 seconds.

Safe labels: Observation | Accumulation | Aggressive Accumulation | Distribution | Aggressive Distribution
"""

import asyncio
import random
import statistics
from datetime import datetime, timezone
from typing import Dict, Optional, Any
import pandas as pd
import httpx

VS_CURRENCY = "usd"
RETRY_DELAY = 10
POLL_SECONDS = 60

# Coins with CoinGecko IDs and risk tiers for zone multipliers
# Slimmed to just BTC and SOL for now per request.
# To add a new asset, include its CoinGecko ID and choose a risk tier.
# Example placeholder for pumpfun (uncomment when correct CoinGecko ID is confirmed):
# "PUMPFUN": {"id": "<coingecko-id-here>", "risk": "high"},
COINS = {
    "BTC": {"id": "bitcoin", "risk": "low"},
    "SOL": {"id": "solana", "risk": "medium"},
    "PUMP": {"id": "pump", "risk": "high"},
}

# ATR-based zone multipliers (k1, k2) for risk tiers
RISK_MULTIPLIERS = {
    "low": (1.0, 1.8),
    "medium": (1.3, 2.2),
    "high": (1.6, 2.8),
}

# Global state: last_updated (ISO), signals (dict per symbol), errors (last 10)
state: Dict[str, Any] = {
    "last_updated": None,
    "regime": "Neutral",  # Neutral | Risk-ON | Risk-OFF (future: compute from BTC/SOL)
    "signals": {},
    "errors": [],
}

def atr14_proxy(df: pd.DataFrame) -> float:
    """ATR(14) proxy in absolute $ terms using rolling std of returns times last price."""
    if len(df) < 15:
        return 0.0
    try:
        pct_std = df["close"].pct_change().rolling(14).std()
        last_price = float(df["close"].iloc[-1])
        return float((pct_std.iloc[-1] or 0.0) * last_price)
    except Exception:
        return 0.0

def label_and_score(z: Dict[str, float], sma20: float, sma50: float, rsi: Optional[float], atr_abs: float):
    """Return (label, score 0-100, atr_pct) using proximity to bands, trend, RSI band, and volatility penalty."""
    c = z["current"]

    # Support both legacy keys (deepAccum/accum/distrib/safeDistrib) and new names
    deep_buy = z.get("deep_buy", z.get("deepAccum", 0.0))
    regular_buy = z.get("regular_buy", z.get("accum", 0.0))
    regular_sell = z.get("regular_sell", z.get("distrib", 0.0))
    safe_sell = z.get("safe_sell", z.get("safeDistrib", 0.0))

    deep_d = abs((c - deep_buy) / max(1e-9, deep_buy))
    regb_d = abs((c - regular_buy) / max(1e-9, regular_buy))
    regs_d = abs((c - regular_sell) / max(1e-9, regular_sell))
    safes_d = abs((c - safe_sell) / max(1e-9, safe_sell))

    # Trend and RSI band score
    trend = 1 if sma20 > sma50 else 0
    rsi_val = rsi if rsi is not None else 50.0
    rsi_ok = 1 if 40 <= rsi_val <= 70 else 0

    # Volatility penalty (higher ATR% => lower score)
    atr_pct = (atr_abs / max(1e-9, c)) * 100.0
    vol_pen = max(0.0, min(1.0, atr_pct / 10.0))  # 0–1 over ~0–10%

    # Labeling by zones
    if c <= deep_buy:
        label = "Deep Accumulation"
    elif c <= regular_buy:
        label = "Accumulation"
    elif c >= safe_sell:
        label = "Safe Distribution"
    elif c >= regular_sell:
        label = "Distribution"
    else:
        label = "Neutral"

    # Score blend 0–100
    proximity = 1.0 - min(deep_d, regb_d, regs_d, safes_d)
    proximity = max(0.0, min(1.0, proximity))
    score = int(100 * (0.45 * proximity + 0.25 * trend + 0.20 * rsi_ok + 0.10 * (1.0 - vol_pen)))
    return label, score, atr_pct

def compute_regime(signals: Dict[str, Any]) -> str:
    """Derive a simple aggregate regime from majority label bucket."""
    counts = {
        "Deep Accumulation": 0,
        "Accumulation": 0,
        "Neutral": 0,
        "Distribution": 0,
        "Safe Distribution": 0,
    }
    for s in signals.values():
        lbl = s.get("label", "Neutral")
        counts[lbl] = counts.get(lbl, 0) + 1
    for k in ["Deep Accumulation", "Accumulation", "Neutral", "Distribution", "Safe Distribution"]:
        if counts.get(k, 0) > 0:
            return k
    return "Neutral"


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute SMA20, SMA50, ATR14 proxy, RSI14, vol_spike."""
    if len(df) < 50:
        return df
    
    # SMA
    df["SMA20"] = df["close"].rolling(20).mean()
    df["SMA50"] = df["close"].rolling(50).mean()
    
    # ATR proxy: use simple range from high/low if available, else stddev of close
    # Since CoinGecko market_chart only has close, use rolling stddev as ATR proxy
    df["ATR14"] = df["close"].rolling(14).std()
    
    # RSI14
    delta = df["close"].diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    down = down.replace(0, 1e-9)  # prevent div by zero
    roll_up = up.rolling(14).mean()
    roll_down = down.rolling(14).mean().replace(0, 1e-9)
    rs = roll_up / roll_down
    df["RSI14"] = 100 - (100 / (1 + rs))
    
    # Volume spike: volume > 2x 20-period SMA
    vma20 = df["volume"].rolling(20).mean()
    df["vol_spike"] = df["volume"] > 2 * vma20
    
    return df


def compute_zones(df: pd.DataFrame, risk: str) -> Optional[Dict[str, float]]:
    """
    Calculate ATR-based zones:
    - deepAccum = SMA20 - k2*ATR
    - accum = SMA20 - k1*ATR
    - distrib = SMA20 + k1*ATR
    - safeDistrib = SMA20 + k2*ATR
    """
    if len(df) < 50 or df["SMA20"].isna().iloc[-1] or df["ATR14"].isna().iloc[-1]:
        return None
    
    sma20 = float(df["SMA20"].iloc[-1])
    atr14 = float(df["ATR14"].iloc[-1])
    k1, k2 = RISK_MULTIPLIERS[risk]
    
    zones = {
        "deepAccum": max(0.0, sma20 - k2 * atr14),
        "accum": max(0.0, sma20 - k1 * atr14),
        "distrib": sma20 + k1 * atr14,
        "safeDistrib": sma20 + k2 * atr14,
        "current": float(df["close"].iloc[-1]),
        "sma20": sma20,
        "sma50": float(df["SMA50"].iloc[-1]) if not df["SMA50"].isna().iloc[-1] else sma20,
        "atr14": atr14,
    }
    # Provide alias keys expected by downstream helpers (deep_buy, regular_buy, regular_sell, safe_sell)
    zones["deep_buy"] = zones["deepAccum"]
    zones["regular_buy"] = zones["accum"]
    zones["regular_sell"] = zones["distrib"]
    zones["safe_sell"] = zones["safeDistrib"]
    return zones


def label_from_zones(zones: Dict[str, float], regime: str) -> str:
    """
    Assign safe label based on price vs zones:
    - Aggressive Accumulation: price <= deepAccum
    - Accumulation: price <= accum
    - Aggressive Distribution: price >= safeDistrib
    - Distribution: price >= distrib
    - Observation: else
    """
    price = zones["current"]
    if price <= zones["deepAccum"]:
        return "Aggressive Accumulation"
    elif price <= zones["accum"]:
        return "Accumulation"
    elif price >= zones["safeDistrib"]:
        return "Aggressive Distribution"
    elif price >= zones["distrib"]:
        return "Distribution"
    else:
        return "Observation"


def compute_score(zones: Dict[str, float], df: pd.DataFrame, regime: str) -> int:
    """
    Compute confidence score (0-100):
    - regime alignment: 30 pts (neutral=15, risk-on with accum=30, etc.)
    - trend alignment: 30 pts (SMA20 > SMA50 + price near zones)
    - liquidity/vol: 20 pts (vol_spike + ATR relative to price)
    - RSI mean-reversion quality: 10 pts
    - vol pattern: 10 pts (consistent vol or spike)
    """
    score = 0
    
    # Regime (simplified: neutral=15, else 30 if aligned)
    # Future: compute regime from BTC/SOL; for now, always neutral
    score += 15
    
    # Trend alignment: SMA20 > SMA50 and price near zones
    if zones["sma20"] > zones["sma50"]:
        score += 15
    if abs(zones["current"] - zones["sma20"]) / zones["sma20"] < 0.05:
        score += 15
    
    # Liquidity/vol
    if not df["vol_spike"].isna().iloc[-1] and df["vol_spike"].iloc[-1]:
        score += 10
    if zones["atr14"] / zones["current"] > 0.02:  # ATR > 2% of price
        score += 10
    
    # RSI mean-reversion quality
    if not df["RSI14"].isna().iloc[-1]:
        rsi = float(df["RSI14"].iloc[-1])
        if rsi < 30 or rsi > 70:
            score += 10
    
    # Vol pattern: if recent volume > avg
    recent_vol = df["volume"].iloc[-5:].mean()
    avg_vol = df["volume"].mean()
    if recent_vol > avg_vol:
        score += 10
    
    return min(100, score)


async def fetch_market_data(
    client: httpx.AsyncClient, coin_id: str, days: int = 60, retries: int = 2
) -> Optional[pd.DataFrame]:
    """Fetch CoinGecko market_chart for a coin and return DataFrame with close, volume, timestamp."""
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
    params = {"vs_currency": VS_CURRENCY, "days": days}
    
    for attempt in range(retries + 1):
        try:
            r = await client.get(url, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            
            if "prices" not in data or "total_volumes" not in data:
                return None
            
            df = pd.DataFrame(data["prices"], columns=["timestamp", "close"])
            df["volume"] = [v[1] for v in data["total_volumes"]]
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            return df
        
        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(RETRY_DELAY * (attempt + 1))
            else:
                error_msg = f"{coin_id}: {str(e)}"
                state["errors"] = (state["errors"] + [error_msg])[-10:]
                return None


async def refresh_signals():
    """Fetch market data for all coins, compute indicators, zones, labels, scores, and regime."""
    async with httpx.AsyncClient() as client:
        results: Dict[str, Any] = {}

        for symbol, info in COINS.items():
            df = await fetch_market_data(client, info["id"])
            if df is None or len(df) < 50:
                continue

            df = calculate_indicators(df)
            zones = compute_zones(df, info["risk"])
            if not zones:
                continue

            rsi = float(df["RSI14"].iloc[-1]) if "RSI14" in df.columns and not df["RSI14"].isna().iloc[-1] else None
            vol_spike = bool(df["vol_spike"].iloc[-1]) if "vol_spike" in df.columns and not df["vol_spike"].isna().iloc[-1] else False
            atr_abs = atr14_proxy(df)
            label, score, atr_pct = label_and_score(zones, zones["sma20"], zones["sma50"], rsi, atr_abs)

            results[symbol] = {
                "symbol": symbol,
                "label": label,
                "score": score,  # 0–100
                "price": zones["current"],
                "sma20": zones["sma20"],
                "sma50": zones["sma50"],
                "atr14": atr_abs,          # absolute $ proxy
                "atr_pct": atr_pct,        # % of price
                "rsi14": rsi,
                "vol_spike": vol_spike,
                "zones": {
                    "deepAccum": zones["deep_buy"],
                    "accum": zones["regular_buy"],
                    "distrib": zones["regular_sell"],
                    "safeDistrib": zones["safe_sell"],
                },
            }

            # Rate-limit friendly: small random delay between requests
            await asyncio.sleep(0.25 * random.uniform(0.8, 1.2))

        state["signals"] = results
        state["regime"] = compute_regime(results)
        state["last_updated"] = datetime.now(timezone.utc).isoformat()


async def loop_runner():
    """Background task that refreshes signals every POLL_SECONDS."""
    while True:
        try:
            await refresh_signals()
        except Exception as e:
            error_msg = f"loop: {str(e)}"
            state["errors"] = (state["errors"] + [error_msg])[-10:]
        
        await asyncio.sleep(POLL_SECONDS)
