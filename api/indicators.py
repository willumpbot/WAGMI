import asyncio
import pandas as pd
import numpy as np
import aiohttp
from config import RISK_K

# Binance public klines API — no key required, generous rate limits
BINANCE_API = "https://api.binance.com/api/v3/klines"

# Last fetch error per symbol, surfaced via /v1/debug
fetch_errors: dict = {}


async def fetch_df(session, symbol: str, days: int = 60, _retries: int = 2):
    """Fetch daily OHLCV from Binance. symbol = e.g. 'BTCUSDT'."""
    params = {"symbol": symbol, "interval": "1d", "limit": days + 1}
    for attempt in range(_retries + 1):
        try:
            async with session.get(BINANCE_API, params=params) as r:
                if r.status == 429:
                    retry_after = int(r.headers.get("Retry-After", 10))
                    fetch_errors[symbol] = f"429 rate limited, retrying after {retry_after}s"
                    await asyncio.sleep(retry_after)
                    continue
                if r.status != 200:
                    body = await r.text()
                    fetch_errors[symbol] = f"HTTP {r.status}: {body[:200]}"
                    return None
                js = await r.json()
                if not js or not isinstance(js, list):
                    fetch_errors[symbol] = f"unexpected response: {str(js)[:200]}"
                    return None
                # Binance kline: [open_time, open, high, low, close, volume, ...]
                df = pd.DataFrame(js, columns=[
                    "ts", "open", "high", "low", "close", "volume",
                    "close_time", "quote_vol", "trades",
                    "taker_base", "taker_quote", "ignore",
                ])
                df["ts"] = pd.to_datetime(df["ts"], unit="ms")
                df["close"] = df["close"].astype(float)
                df["volume"] = df["quote_vol"].astype(float)  # USD volume
                fetch_errors.pop(symbol, None)
                return df[["ts", "close", "volume"]]
        except Exception as exc:
            fetch_errors[symbol] = f"exception attempt {attempt}: {exc}"
            if attempt < _retries:
                await asyncio.sleep(5)
    return None


def compute_indicators(df: pd.DataFrame):
    if df is None or len(df) < 50:
        return None
    df = df.sort_values("ts").reset_index(drop=True)
    df["SMA20"] = df["close"].rolling(20, min_periods=20).mean()
    df["SMA50"] = df["close"].rolling(50, min_periods=50).mean()
    df["RSI14"] = _rsi(df["close"], 14)
    df["ATR14"] = _atr(df, 14)
    df["vol_ma20"] = df["volume"].rolling(20, min_periods=20).mean()
    df["vol_spike"] = df["volume"] > 2 * df["vol_ma20"]
    return df.dropna()


def _rsi(series, period):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(df, period):
    high = df["close"]
    low = df["close"]
    prev = df["close"].shift(1)
    tr = pd.concat(
        [high - low, (high - prev).abs(), (low - prev).abs()], axis=1
    ).max(axis=1)
    return tr.rolling(period).mean()


def zones_atr(last: pd.Series, risk: str):
    k1, k2 = RISK_K[risk]
    sma20 = float(last["SMA20"])
    atr = float(last["ATR14"])
    price = float(last["close"])
    if np.isnan(sma20) or np.isnan(atr):
        return None
    return dict(
        deepAccum=max(0.0, sma20 - k2 * atr),
        accum=max(0.0, sma20 - k1 * atr),
        distrib=sma20 + k1 * atr,
        safeDistrib=sma20 + k2 * atr,
        price=price,
        sma20=float(sma20),
        sma50=float(last["SMA50"]),
        rsi=float(last["RSI14"]),
        volSpike=bool(last["vol_spike"]),
    )


def label_from_price(z: dict, regime: str) -> str:
    p = z["price"]
    if regime == "Risk-OFF":
        return "Observation"
    if p <= z["deepAccum"]:
        return "Aggressive Accumulation"
    if p <= z["accum"]:
        return "Accumulation"
    if p >= z["safeDistrib"]:
        return "Aggressive Distribution"
    if p >= z["distrib"]:
        return "Distribution"
    return "Observation"


def score_state(z: dict, regime: str) -> int:
    score = 0
    score += 30 if regime == "Risk-ON" else 10 if regime == "Neutral" else 0
    score += 15 if z["price"] > z["sma50"] else 0
    score += 15 if z["price"] > z["sma20"] else 0
    score += 20 if not z["volSpike"] else 10
    rsi = z["rsi"]
    score += 10 if 40 < rsi < 60 else 5 if 30 < rsi < 70 else 0
    score += 10 if z["price"] > z["accum"] else 0
    return score


def _regime_from_indicators(di) -> str:
    if di is None:
        return "Neutral"
    last = di.iloc[-1]
    if last["SMA20"] > last["SMA50"]:
        return "Risk-ON"
    if last["SMA20"] < last["SMA50"] * 0.98:
        return "Risk-OFF"
    return "Neutral"


async def compute_regime(session) -> str:
    df = await fetch_df(session, "BTCUSDT", days=60)
    return _regime_from_indicators(compute_indicators(df))


async def build_signals_snapshot(session, coins: dict, regime: str, _btc_df=None) -> dict:
    """Fetch and compute signals for all coins. Pass _btc_df to reuse an already-fetched BTC df."""
    out = {}
    for sym, info in coins.items():
        df = _btc_df if (sym == "BTC" and _btc_df is not None) else await fetch_df(session, info["id"], days=60)
        di = compute_indicators(df)
        if di is None:
            continue
        last = di.iloc[-1]
        z = zones_atr(last, info["risk"])
        if z is None:
            continue
        label = label_from_price(z, regime)
        score = score_state(z, regime)
        out[sym] = {
            "symbol": sym,
            "label": label,
            "score": score,
            "market": sym,
            "price": round(z["price"], 6),
            "sma20": round(z["sma20"], 6),
            "sma50": round(z["sma50"], 6),
            "atr14": round(float(di["ATR14"].iloc[-1] or 0), 6),
            "rsi14": round(z["rsi"], 1),
            "vol_spike": z["volSpike"],
            "zones": {
                "deepAccum": round(z["deepAccum"], 6),
                "accum": round(z["accum"], 6),
                "distrib": round(z["distrib"], 6),
                "safeDistrib": round(z["safeDistrib"], 6),
            },
        }
    return out
