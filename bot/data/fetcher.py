"""
CoinGecko-primary data fetcher.
Constructs OHLCV candles from CoinGecko market_chart price data.

CoinGecko granularity by lookback:
  days=1   -> ~5-min intervals  (used for 5m/15m/30m candles)
  days=7   -> ~hourly intervals (used for 1h candles)
  days=30  -> ~hourly intervals (used for 1h/4h/6h candles)
  days=90  -> ~hourly intervals (used for 6h/16h/daily candles)
  days=365 -> ~daily intervals  (used for daily/weekly candles)

OHLCV is approximated by resampling close-price data points:
  open  = first close in interval
  high  = max close in interval
  low   = min close in interval
  close = last close in interval
  volume = sum of volumes in interval
"""

import time
import random
import logging
import threading
import requests
import pandas as pd
from datetime import datetime, timezone
from typing import Optional, Dict

logger = logging.getLogger("bot.data")

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

# Mapping from desired timeframe to CoinGecko lookback and resample frequency
TIMEFRAME_MAP = {
    "5m":  {"days": 1,  "freq": "5min"},
    "15m": {"days": 1,  "freq": "15min"},
    "30m": {"days": 1,  "freq": "30min"},
    "1h":  {"days": 30, "freq": "1h"},
    "4h":  {"days": 90, "freq": "4h"},
    "6h":  {"days": 90, "freq": "6h"},
    "16h": {"days": 90, "freq": "16h"},
    "1d":  {"days": 90, "freq": "1D"},
    "daily": {"days": 30, "freq": "1h"},  # alias: returns hourly data for zone strategies
}


class DataFetcher:
    """
    CoinGecko-primary market data fetcher.
    Fetches price+volume data and constructs OHLCV candles at desired timeframes.
    Includes caching, rate limiting, and retry logic.
    """

    def __init__(self, max_retries: int = 3, retry_delay: float = 5.0, cache_ttl: int = 45):
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.cache_ttl = cache_ttl
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "NunuIRL-Bot/1.0"})
        self._cache: Dict[str, tuple] = {}  # key -> (timestamp, dataframe)
        self._lock = threading.Lock()
        self._last_request_ts = 0.0
        self._min_request_gap = 2.5  # seconds between CoinGecko requests (rate limit)
        self._consecutive_429s = 0

    def _rate_limit(self):
        """Enforce minimum gap between API requests."""
        with self._lock:
            now = time.time()
            gap = now - self._last_request_ts
            if gap < self._min_request_gap:
                time.sleep(self._min_request_gap - gap + random.uniform(0, 0.3))
            self._last_request_ts = time.time()

    def _get_cached(self, key: str) -> Optional[pd.DataFrame]:
        if key in self._cache:
            ts, df = self._cache[key]
            if time.time() - ts < self.cache_ttl:
                return df.copy()
        return None

    def _set_cache(self, key: str, df: pd.DataFrame):
        self._cache[key] = (time.time(), df.copy())

    def _fetch_market_chart(self, coin_id: str, days: int, vs_currency: str = "usd") -> Optional[pd.DataFrame]:
        """Fetch raw price+volume data from CoinGecko market_chart endpoint."""
        cache_key = f"raw:{coin_id}:{days}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart"
        params = {"vs_currency": vs_currency, "days": days}

        for attempt in range(self.max_retries):
            self._rate_limit()
            try:
                resp = self._session.get(url, params=params, timeout=15)
                if resp.status_code == 429:
                    self._consecutive_429s += 1
                    wait = min(int(resp.headers.get("Retry-After", 10)), 30)
                    # Back off more on repeated 429s
                    wait = wait + (self._consecutive_429s * 5)
                    logger.warning(f"[{coin_id}] CoinGecko rate limited, waiting {wait}s (429 #{self._consecutive_429s})")
                    time.sleep(wait)
                    # Increase gap between future requests
                    self._min_request_gap = min(self._min_request_gap + 1.0, 8.0)
                    continue
                self._consecutive_429s = 0
                resp.raise_for_status()
                data = resp.json()
                if "prices" not in data or "total_volumes" not in data:
                    return None

                prices = data["prices"]
                volumes = data["total_volumes"]

                df = pd.DataFrame(prices, columns=["timestamp", "close"])
                df["volume"] = [v[1] for v in volumes[:len(df)]]
                df["time"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                df = df.drop(columns=["timestamp"]).set_index("time").sort_index()

                self._set_cache(cache_key, df.reset_index())
                return df.reset_index()

            except Exception as e:
                logger.warning(f"[{coin_id}] CoinGecko attempt {attempt+1}/{self.max_retries} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1) + random.uniform(0, 1))

        return None

    def _resample_to_ohlcv(self, df_raw: pd.DataFrame, freq: str) -> pd.DataFrame:
        """
        Resample raw close+volume data into OHLCV candles.
        Approximates open/high/low from close prices within each interval.
        """
        if df_raw is None or df_raw.empty:
            return pd.DataFrame()

        df = df_raw.copy()
        if "time" in df.columns:
            df = df.set_index("time")

        ohlcv = df["close"].resample(freq).agg(
            open="first", high="max", low="min", close="last"
        )
        ohlcv["volume"] = df["volume"].resample(freq).sum()
        ohlcv = ohlcv.dropna().reset_index()
        ohlcv = ohlcv.rename(columns={"time": "time"})
        return ohlcv

    def fetch_ohlcv(self, coin_id: str, timeframe: str, vs_currency: str = "usd") -> pd.DataFrame:
        """
        Fetch OHLCV data for a coin at a specific timeframe.

        Args:
            coin_id: CoinGecko coin ID (e.g. "bitcoin", "hyperliquid")
            timeframe: One of "5m", "15m", "30m", "1h", "4h", "6h", "16h", "1d"
            vs_currency: Quote currency (default "usd")

        Returns:
            DataFrame with columns: [time, open, high, low, close, volume]
        """
        cache_key = f"ohlcv:{coin_id}:{timeframe}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        tf_config = TIMEFRAME_MAP.get(timeframe)
        if tf_config is None:
            logger.warning(f"Unknown timeframe: {timeframe}")
            return pd.DataFrame()

        raw = self._fetch_market_chart(coin_id, tf_config["days"], vs_currency)
        if raw is None or raw.empty:
            return pd.DataFrame()

        # Special case: "daily" returns raw hourly data for zone strategies
        if timeframe == "daily":
            result = raw.copy()
            if "time" not in result.columns and result.index.name == "time":
                result = result.reset_index()
            self._set_cache(cache_key, result)
            return result

        ohlcv = self._resample_to_ohlcv(raw, tf_config["freq"])
        if not ohlcv.empty:
            self._set_cache(cache_key, ohlcv)
        return ohlcv

    def latest_price(self, coin_id: str, vs_currency: str = "usd") -> Optional[float]:
        """Get the latest price for a coin."""
        cache_key = f"price:{coin_id}"
        cached = self._get_cached(cache_key)
        if cached is not None and not cached.empty:
            return float(cached["close"].iloc[-1])

        raw = self._fetch_market_chart(coin_id, days=1, vs_currency=vs_currency)
        if raw is None or raw.empty:
            return None
        return float(raw["close"].iloc[-1])

    def fetch_multi_timeframe(
        self, coin_id: str, timeframes: list, vs_currency: str = "usd"
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch OHLCV data for multiple timeframes at once.
        Optimizes by grouping requests that share the same CoinGecko lookback.
        """
        result = {}

        # Group timeframes by their required CoinGecko lookback days
        by_days = {}
        for tf in timeframes:
            tf_config = TIMEFRAME_MAP.get(tf)
            if tf_config is None:
                continue
            days = tf_config["days"]
            if days not in by_days:
                by_days[days] = []
            by_days[days].append((tf, tf_config["freq"]))

        # Fetch each unique lookback once, then resample to all needed timeframes
        for days, tf_list in by_days.items():
            raw = self._fetch_market_chart(coin_id, days, vs_currency)
            if raw is None or raw.empty:
                for tf, _ in tf_list:
                    result[tf] = pd.DataFrame()
                continue

            for tf, freq in tf_list:
                if tf == "daily":
                    result[tf] = raw.copy()
                else:
                    result[tf] = self._resample_to_ohlcv(raw, freq)

        return result

    def clear_cache(self):
        """Clear the data cache."""
        self._cache.clear()
