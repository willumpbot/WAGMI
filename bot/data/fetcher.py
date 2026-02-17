"""
Multi-exchange data fetcher using CCXT.
Primary: Kraken (BTC, SOL) + Hyperliquid (HYPE) for real OHLCV candles.
Fallback chain: if an exchange is geo-blocked (403), auto-tries the next.
Final fallback: CoinGecko for any coin not available on exchanges.

Why CCXT over CoinGecko:
- Real OHLCV candles (true high/low, not approximated from close)
- 3,000+ calls/min vs 10-30/min (CoinGecko)
- Sub-second latency vs 2-3 seconds
- No API key required for market data
- WebSocket support for future real-time streaming
"""

import os
import time
import random
import logging
import threading
import requests
import pandas as pd
from datetime import datetime, timezone
from typing import Any, Optional, Dict, List

logger = logging.getLogger("bot.data")

# CoinGecko fallback config
_CG_API_KEY = os.getenv("COINGECKO_API_KEY", "")
if _CG_API_KEY:
    COINGECKO_BASE = "https://pro-api.coingecko.com/api/v3"
else:
    COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Mapping from our timeframe labels to CCXT format
CCXT_TIMEFRAME_MAP = {
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1h",
    "4h": "4h",
    "6h": "6h",
    "16h": None,  # not natively supported, build from 4h
    "1d": "1d",
    "daily": "1h",  # strategies want hourly data
}

# How many candles to fetch per timeframe
CANDLE_LIMITS = {
    "5m": 200,
    "15m": 100,
    "30m": 100,
    "1h": 200,
    "4h": 100,
    "6h": 60,
    "16h": 60,
    "1d": 90,
    "daily": 720,  # 30 days of hourly
}

# CoinGecko fallback config
CG_TIMEFRAME_MAP = {
    "5m":  {"days": 1,  "freq": "5min"},
    "15m": {"days": 1,  "freq": "15min"},
    "30m": {"days": 1,  "freq": "30min"},
    "1h":  {"days": 30, "freq": "1h"},
    "4h":  {"days": 90, "freq": "4h"},
    "6h":  {"days": 90, "freq": "6h"},
    "16h": {"days": 90, "freq": "16h"},
    "1d":  {"days": 90, "freq": "1D"},
    "daily": {"days": 30, "freq": "1h"},
}

CACHE_TTL_BY_TF = {
    "5m": 60,
    "15m": 90,
    "30m": 120,
    "1h": 180,
    "4h": 300,
    "6h": 600,
    "16h": 600,
    "1d": 900,
    "daily": 300,
}


class DataFetcher:
    """
    Multi-exchange data fetcher using CCXT for real OHLCV candles.
    Falls back to CoinGecko if CCXT is unavailable.
    """

    def __init__(self, max_retries: int = 3, retry_delay: float = 2.0, cache_ttl: int = 120):
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, tuple] = {}
        self._lock = threading.Lock()
        self._total_requests = 0
        self._cache_hits = 0
        self._ccxt_available = False
        self._exchanges: Dict[str, Any] = {}
        self._blocked_exchanges: set = set()  # exchanges that returned 403 geo-block

        # Exchange fallback chains per symbol (tried in order)
        self._symbol_exchanges = {
            "BTC": [("kraken", "BTC/USDT"), ("bybit", "BTC/USDT")],
            "SOL": [("kraken", "SOL/USDT"), ("bybit", "SOL/USDT")],
            "HYPE": [("hyperliquid", "HYPE/USDC:USDC")],
            "FARTCOIN": [("hyperliquid", "FARTCOIN/USDC:USDC"), ("bybit", "FARTCOIN/USDT")],
            "PEPE": [("kraken", "PEPE/USDT"), ("bybit", "PEPE/USDT")],
        }

        # Try to initialize CCXT exchanges
        try:
            import ccxt
            self._ccxt = ccxt

            # Kraken - US-based (San Francisco), no geo-blocking, no auth for market data
            self._exchanges["kraken"] = ccxt.kraken({
                "enableRateLimit": True,
            })

            # Hyperliquid - DEX, no auth needed for market data
            self._exchanges["hyperliquid"] = ccxt.hyperliquid({
                "enableRateLimit": True,
            })

            # Bybit - backup (blocked in some countries)
            try:
                self._exchanges["bybit"] = ccxt.bybit({
                    "enableRateLimit": True,
                })
            except Exception:
                pass

            self._ccxt_available = True
            logger.info(f"CCXT initialized: {list(self._exchanges.keys())}")
        except ImportError:
            logger.warning("CCXT not installed — falling back to CoinGecko. Run: pip install ccxt")
        except Exception as e:
            logger.warning(f"CCXT init failed: {e} — falling back to CoinGecko")

        # CoinGecko fallback session
        self._cg_session = requests.Session()
        headers = {"User-Agent": "NunuIRL-Bot/1.0"}
        if _CG_API_KEY:
            headers["x-cg-demo-api-key"] = _CG_API_KEY
        self._cg_session.headers.update(headers)
        self._cg_last_request_ts = 0.0
        self._cg_min_gap = 2.5
        self._cg_consecutive_429s = 0

    # ─── Cache ───────────────────────────────────────────────────────

    def _get_cached(self, key: str, ttl: Optional[int] = None) -> Optional[pd.DataFrame]:
        effective_ttl = ttl if ttl is not None else self.cache_ttl
        if key in self._cache:
            ts, df = self._cache[key]
            if time.time() - ts < effective_ttl:
                self._cache_hits += 1
                return df.copy()
        return None

    def _set_cache(self, key: str, df: pd.DataFrame):
        self._cache[key] = (time.time(), df.copy())
        # Evict stale entries periodically to prevent memory leak
        if len(self._cache) > 100:
            self._evict_stale_cache()

    def _evict_stale_cache(self):
        """Remove expired cache entries."""
        now = time.time()
        max_ttl = max(CACHE_TTL_BY_TF.values()) * 2  # 2x the longest TTL
        stale = [k for k, (ts, _) in self._cache.items() if now - ts > max_ttl]
        for k in stale:
            del self._cache[k]

    # ─── CCXT fetching ───────────────────────────────────────────────

    def _get_exchange_for_symbol(self, symbol_name: str) -> tuple:
        """Return (exchange_obj, ccxt_symbol) for a given symbol name.
        Uses fallback chain, skipping geo-blocked exchanges."""
        candidates = self._symbol_exchanges.get(symbol_name, [])
        for exch_name, ccxt_sym in candidates:
            if exch_name in self._blocked_exchanges:
                continue
            exch = self._exchanges.get(exch_name)
            if exch:
                return exch, ccxt_sym
        return None, None

    def _mark_exchange_blocked(self, exchange_obj, error_msg: str):
        """Mark an exchange as geo-blocked so we skip it on future calls."""
        error_lower = str(error_msg).lower()
        if "403" in error_lower or "block" in error_lower or "country" in error_lower:
            for name, exch in self._exchanges.items():
                if exch is exchange_obj:
                    self._blocked_exchanges.add(name)
                    logger.warning(f"Exchange '{name}' geo-blocked, will use fallback")
                    break

    def _fetch_ccxt_ohlcv(self, symbol_name: str, timeframe: str) -> Optional[pd.DataFrame]:
        """Fetch OHLCV candles from exchange via CCXT.
        Tries each exchange in the fallback chain, skipping blocked ones."""
        ccxt_tf = CCXT_TIMEFRAME_MAP.get(timeframe)
        limit = CANDLE_LIMITS.get(timeframe, 100)

        # Handle 16h by fetching 4h and resampling
        if timeframe == "16h":
            df_4h = self._fetch_ccxt_ohlcv(symbol_name, "4h")
            if df_4h is not None and not df_4h.empty:
                return self._resample_ohlcv(df_4h, "16h")
            return None

        # Handle 6h — not all exchanges support it, so build from 1h
        if timeframe == "6h":
            # Try native 6h first
            exchange, ccxt_symbol = self._get_exchange_for_symbol(symbol_name)
            if exchange:
                try:
                    self._total_requests += 1
                    since = self._compute_since(exchange, limit, 360)
                    candles = exchange.fetch_ohlcv(ccxt_symbol, "6h", since=since, limit=limit)
                    if candles:
                        return self._candles_to_df(candles)
                except Exception as e:
                    self._mark_exchange_blocked(exchange, str(e))
            # Fallback: build 6h from 1h
            df_1h = self._fetch_ccxt_ohlcv(symbol_name, "1h")
            if df_1h is not None and not df_1h.empty:
                return self._resample_ohlcv(df_1h, "6h")
            return None

        if ccxt_tf is None:
            return None

        # Try each exchange in the fallback chain
        candidates = self._symbol_exchanges.get(symbol_name, [])
        for exch_name, ccxt_symbol in candidates:
            if exch_name in self._blocked_exchanges:
                continue
            exchange = self._exchanges.get(exch_name)
            if not exchange:
                continue

            since = self._compute_since(exchange, limit, self._tf_to_minutes(ccxt_tf))

            for attempt in range(self.max_retries):
                try:
                    self._total_requests += 1
                    candles = exchange.fetch_ohlcv(ccxt_symbol, ccxt_tf, since=since, limit=limit)
                    if not candles:
                        break  # try next exchange
                    return self._candles_to_df(candles)
                except Exception as e:
                    error_str = str(e)
                    # If geo-blocked, mark and try next exchange immediately
                    if "403" in error_str:
                        self._mark_exchange_blocked(exchange, error_str)
                        break  # skip retries, try next exchange
                    logger.warning(f"[{symbol_name}] {exch_name} {timeframe} attempt {attempt+1}/{self.max_retries}: {e}")
                    if attempt < self.max_retries - 1:
                        time.sleep(self.retry_delay * (attempt + 1))

        return None

    def _compute_since(self, exchange, limit: int, tf_minutes: int) -> Optional[int]:
        """Compute 'since' param. Required for Hyperliquid, optional for others."""
        if "hyperliquid" in str(type(exchange)).lower():
            return int((time.time() - limit * tf_minutes * 60) * 1000)
        return None

    def _candles_to_df(self, candles: list) -> pd.DataFrame:
        """Convert raw CCXT candle list to DataFrame."""
        df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.drop(columns=["timestamp"]).set_index("time").sort_index().reset_index()
        return df

    def _tf_to_minutes(self, tf: str) -> int:
        """Convert CCXT timeframe string to minutes."""
        units = {"m": 1, "h": 60, "d": 1440, "w": 10080}
        num = int(tf[:-1])
        unit = tf[-1]
        return num * units.get(unit, 1)

    def _resample_ohlcv(self, df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
        """Resample real OHLCV data to a larger timeframe."""
        if df is None or df.empty:
            return pd.DataFrame()

        freq_map = {"16h": "16h", "6h": "6h", "1d": "1D"}
        freq = freq_map.get(target_tf, target_tf)

        work = df.copy()
        if "time" in work.columns:
            work = work.set_index("time")

        resampled = work.resample(freq).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna().reset_index()
        return resampled

    # ─── CoinGecko fallback ──────────────────────────────────────────

    def _cg_rate_limit(self):
        with self._lock:
            now = time.time()
            gap = now - self._cg_last_request_ts
            if gap < self._cg_min_gap:
                time.sleep(self._cg_min_gap - gap + random.uniform(0, 0.3))
            self._cg_last_request_ts = time.time()

    def _fetch_cg_market_chart(self, coin_id: str, days: int) -> Optional[pd.DataFrame]:
        """CoinGecko fallback: fetch close+volume and approximate OHLCV."""
        cache_key = f"cg_raw:{coin_id}:{days}"
        cached = self._get_cached(cache_key, ttl=300)
        if cached is not None:
            return cached

        url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart"
        params = {"vs_currency": "usd", "days": days}

        for attempt in range(self.max_retries):
            self._cg_rate_limit()
            self._total_requests += 1
            try:
                resp = self._cg_session.get(url, params=params, timeout=15)
                if resp.status_code == 429:
                    self._cg_consecutive_429s += 1
                    wait = min(int(resp.headers.get("Retry-After", 10)), 30) + (self._cg_consecutive_429s * 5)
                    logger.warning(f"[{coin_id}] CoinGecko rate limited, waiting {wait}s")
                    time.sleep(wait)
                    self._cg_min_gap = min(self._cg_min_gap + 1.0, 8.0)
                    continue
                self._cg_consecutive_429s = 0
                resp.raise_for_status()
                data = resp.json()
                if "prices" not in data:
                    return None

                df = pd.DataFrame(data["prices"], columns=["timestamp", "close"])
                if "total_volumes" in data:
                    df["volume"] = [v[1] for v in data["total_volumes"][:len(df)]]
                else:
                    df["volume"] = 0.0
                df["time"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                df = df.drop(columns=["timestamp"]).set_index("time").sort_index().reset_index()
                # Approximate OHLCV from close prices
                df["open"] = df["close"]
                df["high"] = df["close"]
                df["low"] = df["close"]

                self._set_cache(cache_key, df)
                return df

            except Exception as e:
                logger.warning(f"[{coin_id}] CoinGecko attempt {attempt+1}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
        return None

    def _fetch_cg_ohlcv(self, coin_id: str, timeframe: str) -> Optional[pd.DataFrame]:
        """CoinGecko fallback for a specific timeframe."""
        tf_config = CG_TIMEFRAME_MAP.get(timeframe)
        if tf_config is None:
            return None

        raw = self._fetch_cg_market_chart(coin_id, tf_config["days"])
        if raw is None or raw.empty:
            return None

        if timeframe == "daily":
            return raw.copy()

        # Resample
        work = raw.copy().set_index("time")
        resampled = work["close"].resample(tf_config["freq"]).agg(
            open="first", high="max", low="min", close="last"
        )
        resampled["volume"] = work["volume"].resample(tf_config["freq"]).sum()
        resampled = resampled.dropna().reset_index()
        return resampled

    # ─── Public API ──────────────────────────────────────────────────

    def fetch_ohlcv(self, symbol_name: str, coin_id: str, timeframe: str) -> pd.DataFrame:
        """
        Fetch OHLCV data. Tries CCXT first, falls back to CoinGecko.

        Args:
            symbol_name: Symbol name (e.g. "BTC", "HYPE")
            coin_id: CoinGecko coin ID for fallback (e.g. "bitcoin")
            timeframe: One of "5m", "15m", "1h", "4h", "6h", "16h", "1d", "daily"
        """
        cache_key = f"ohlcv:{symbol_name}:{timeframe}"
        ttl = CACHE_TTL_BY_TF.get(timeframe, self.cache_ttl)
        cached = self._get_cached(cache_key, ttl)
        if cached is not None:
            return cached

        df = None

        # Try CCXT first
        if self._ccxt_available:
            df = self._fetch_ccxt_ohlcv(symbol_name, timeframe)
            if df is not None and not df.empty:
                self._set_cache(cache_key, df)
                return df

        # Fallback to CoinGecko
        df = self._fetch_cg_ohlcv(coin_id, timeframe)
        if df is not None and not df.empty:
            self._set_cache(cache_key, df)
            return df

        return pd.DataFrame()

    def latest_price(self, symbol_name: str, coin_id: str) -> Optional[float]:
        """Get latest price. Tries CCXT ticker first, then candle data, then CoinGecko."""
        cache_key = f"price:{symbol_name}"
        cached = self._get_cached(cache_key, ttl=30)
        if cached is not None and not cached.empty:
            return float(cached["close"].iloc[-1])

        # Try CCXT ticker via fallback chain (fastest)
        if self._ccxt_available:
            candidates = self._symbol_exchanges.get(symbol_name, [])
            for exch_name, ccxt_symbol in candidates:
                if exch_name in self._blocked_exchanges:
                    continue
                exchange = self._exchanges.get(exch_name)
                if not exchange:
                    continue
                try:
                    self._total_requests += 1
                    ticker = exchange.fetch_ticker(ccxt_symbol)
                    if ticker and ticker.get("last"):
                        df = pd.DataFrame([{"close": ticker["last"]}])
                        self._set_cache(cache_key, df)
                        return float(ticker["last"])
                except Exception as e:
                    self._mark_exchange_blocked(exchange, str(e))
                    logger.debug(f"[{symbol_name}] {exch_name} ticker failed: {e}")

        # Fallback: get from most recent candle data
        df = self.fetch_ohlcv(symbol_name, coin_id, "5m")
        if df is not None and not df.empty:
            return float(df["close"].iloc[-1])

        return None

    def fetch_multi_timeframe(
        self, symbol_name: str, coin_id: str, timeframes: list
    ) -> Dict[str, pd.DataFrame]:
        """Fetch OHLCV data for multiple timeframes."""
        result = {}
        for tf in timeframes:
            result[tf] = self.fetch_ohlcv(symbol_name, coin_id, tf)
        return result

    def get_stats(self) -> Dict[str, Any]:
        """Return fetcher stats for diagnostics."""
        return {
            "total_requests": self._total_requests,
            "cache_hits": self._cache_hits,
            "cache_entries": len(self._cache),
            "ccxt_available": self._ccxt_available,
            "exchanges": list(self._exchanges.keys()) if self._ccxt_available else [],
            "request_gap": f"{self._cg_min_gap:.1f}s" if not self._ccxt_available else "ccxt",
        }

    def clear_cache(self):
        """Clear the data cache."""
        self._cache.clear()
