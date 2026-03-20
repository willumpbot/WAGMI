import pandas as pd
import numpy as np
import aiohttp
from config import RISK_K, VS_CURRENCY

API = "https://api.coingecko.com/api/v3/coins/{id}/market_chart"


async def fetch_df(session, coin_id: str, days: int = 60):
    params = {"vs_currency": VS_CURRENCY, "days": days}
    async with session.get(API.format(id=coin_id), params=params, timeout=20) as r:
        if r.status != 200:
            return None
        js = await r.json()
        if "prices" not in js or "total_volumes" not in js:
            return None
        df = pd.DataFrame(js["prices"], columns=["ts", "close"])
        df["volume"] = [v[1] for v in js["total_volumes"]]
        df["ts"] = pd.to_datetime(df["ts"], unit="ms")
        return df


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


async def compute_regime(session) -> str:
    df = await fetch_df(session, "bitcoin", days=60)
    di = compute_indicators(df)
    if di is None:
        return "Neutral"
    last = di.iloc[-1]
    if last["SMA20"] > last["SMA50"]:
        return "Risk-ON"
    if last["SMA20"] < last["SMA50"] * 0.98:
        return "Risk-OFF"
    return "Neutral"


async def build_signals_snapshot(session, coins: dict, regime: str) -> dict:
    out = {}
    for sym, info in coins.items():
        df = await fetch_df(session, info["id"], days=60)
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
