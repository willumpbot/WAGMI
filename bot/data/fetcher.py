"""
CCXT-primary multi-exchange data fetcher with CoinGecko fallback.

Exchange priority per symbol (tried in order):
  BTC:      Kraken -> Bybit -> CoinGecko
  SOL:      Kraken -> Bybit -> CoinGecko
  PEPE:     Hyperliquid (as KPEPE) -> Kraken -> Bybit -> CoinGecko
  HYPE:     Hyperliquid -> CoinGecko
  FARTCOIN: Hyperliquid -> Bybit -> CoinGecko

CCXT provides real OHLCV candles with open/high/low/close/volume.
CoinGecko is automatic fallback if CCXT exchanges are unavailable.
"""

import time
import random
import logging
import threading
import requests
import pandas as pd
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple

logger = logging.getLogger("bot.data")

# ─── CCXT config ──────────────────────────────────────────────────

# Default candle limits per timeframe
CCXT_LIMITS = {
    "5m": 300,    # ~25 hours
    "15m": 200,   # ~50 hours
    "30m": 200,   # ~100 hours
    "1h": 500,    # ~20 days
    "4h": 200,    # ~33 days
    "6h": 120,    # ~30 days
    "1d": 90,     # ~90 days
}

# Timeframe -> milliseconds (for `since` calculation)
TIMEFRAME_MS = {
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "6h": 6 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}

# ─── CoinGecko config (fallback) ─────────────────────────────────

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

COINGECKO_TIMEFRAME_MAP = {
    "5m":    {"days": 1,  "freq": "5min"},
    "15m":   {"days": 1,  "freq": "15min"},
    "30m":   {"days": 1,  "freq": "30min"},
    "1h":    {"days": 30, "freq": "1h"},
    "4h":    {"days": 90, "freq": "4h"},
    "6h":    {"days": 90, "freq": "6h"},
    "16h":   {"days": 90, "freq": "16h"},
    "1d":    {"days": 90, "freq": "1D"},
    "daily": {"days": 30, "freq": "1h"},
}


class DataFetcher:
    """
    CCXT-primary market data fetcher with CoinGecko fallback.
    Uses real OHLCV from exchanges (Kraken, Hyperliquid, Bybit).
    Falls back to CoinGecko if CCXT is unavailable.
    """

    def __init__(self, max_retries: int = 3, retry_delay: float = 5.0, cache_ttl: int = 45):
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, tuple] = {}
        self._lock = threading.Lock()

        # Exchange fallback chains per symbol (Hyperliquid primary for all)
        self._symbol_exchanges = {
            "BTC": [("hyperliquid", "BTC/USDC:USDC"), ("kraken", "BTC/USDT"), ("bybit", "BTC/USDT")],
            "ETH": [("hyperliquid", "ETH/USDC:USDC"), ("kraken", "ETH/USDT"), ("bybit", "ETH/USDT")],
            "SOL": [("hyperliquid", "SOL/USDC:USDC"), ("kraken", "SOL/USDT"), ("bybit", "SOL/USDT")],
            "HYPE": [("hyperliquid", "HYPE/USDC:USDC")],
            "XRP": [("hyperliquid", "XRP/USDC:USDC"), ("bybit", "XRP/USDT")],
            "AVAX": [("hyperliquid", "AVAX/USDC:USDC"), ("bybit", "AVAX/USDT")],
            "LINK": [("hyperliquid", "LINK/USDC:USDC"), ("bybit", "LINK/USDT")],
            "SUI": [("hyperliquid", "SUI/USDC:USDC"), ("bybit", "SUI/USDT")],
            "NEAR": [("hyperliquid", "NEAR/USDC:USDC"), ("bybit", "NEAR/USDT")],
            "ARB": [("hyperliquid", "ARB/USDC:USDC"), ("bybit", "ARB/USDT")],
            "DOGE": [("hyperliquid", "DOGE/USDC:USDC"), ("bybit", "DOGE/USDT")],
            "WIF": [("hyperliquid", "WIF/USDC:USDC"), ("bybit", "WIF/USDT")],
            "PEPE": [("hyperliquid", "KPEPE/USDC:USDC"), ("kraken", "PEPE/USDT"), ("bybit", "PEPE/USDT")],
            "TIA": [("hyperliquid", "TIA/USDC:USDC"), ("bybit", "TIA/USDT")],
            "SEI": [("hyperliquid", "SEI/USDC:USDC"), ("bybit", "SEI/USDT")],
            "JUP": [("hyperliquid", "JUP/USDC:USDC"), ("bybit", "JUP/USDT")],
            "ONDO": [("hyperliquid", "ONDO/USDC:USDC"), ("bybit", "ONDO/USDT")],
            "FARTCOIN": [("hyperliquid", "FARTCOIN/USDC:USDC"), ("bybit", "FARTCOIN/USDT")],
        }

        # CCXT exchange instances
        self._exchanges: Dict[str, object] = {}
        self._ccxt_available = False
        self._init_ccxt()

        # CoinGecko session (fallback)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "NunuIRL-Bot/1.0"})
        self._last_cg_request_ts = 0.0
        self._min_cg_request_gap = 1.5

        # Stats
        self._ccxt_requests = 0
        self._cg_requests = 0
        self._ccxt_failures = 0
        self._ccxt_first_success: Dict[str, bool] = {}  # log first success per symbol

    # ─── CCXT initialization ─────────────────────────────────────

    def _init_ccxt(self):
        """Initialize CCXT exchange instances."""
        try:
            import ccxt
            self._ccxt_module = ccxt

            exchange_configs = {
                "kraken": {"enableRateLimit": True, "timeout": 15000},
                "bybit": {"enableRateLimit": True, "timeout": 15000},
                "hyperliquid": {"enableRateLimit": True, "timeout": 15000},
            }

            needed = set()
            for chain in self._symbol_exchanges.values():
                for ex_name, _ in chain:
                    needed.add(ex_name)

            for name in needed:
                try:
                    cls = getattr(ccxt, name)
                    self._exchanges[name] = cls(exchange_configs.get(name, {}))
                except Exception as e:
                    logger.warning(f"CCXT failed to init {name}: {e}")

            if self._exchanges:
                self._ccxt_available = True
                logger.info(f"CCXT initialized: {sorted(self._exchanges.keys())}")
            else:
                logger.warning("No CCXT exchanges available, using CoinGecko only")

        except ImportError:
            logger.warning("ccxt not installed (pip install ccxt), using CoinGecko only")
            self._ccxt_module = None

    # ─── Cache ────────────────────────────────────────────────────

    def _get_cached(self, key: str) -> Optional[pd.DataFrame]:
        if key in self._cache:
            ts, df = self._cache[key]
            if time.time() - ts < self.cache_ttl:
                return df.copy()
        return None

    def _set_cache(self, key: str, df: pd.DataFrame):
        self._cache[key] = (time.time(), df.copy())

    # ─── CCXT fetching ────────────────────────────────────────────

    def _resolve_ccxt_params(
        self, exchange, timeframe: str
    ) -> Tuple[str, int, Optional[str]]:
        """Determine fetch parameters for a given exchange + timeframe.
        Returns (fetch_tf, limit, aggregate_to)."""
        supported = getattr(exchange, "timeframes", {}) or {}

        if timeframe == "daily":
            # Zone strategies expect hourly-granularity data
            return "1h", 720, None
        elif timeframe == "16h":
            # No exchange supports 16h natively; aggregate from 1h
            return "1h", 500, "16h"
        elif timeframe == "6h" and "6h" not in supported:
            # Kraken doesn't have 6h; aggregate from 1h
            return "1h", 720, "6h"
        else:
            return timeframe, CCXT_LIMITS.get(timeframe, 200), None

    def _fetch_ccxt_ohlcv(
        self, symbol_name: str, timeframe: str
    ) -> Optional[pd.DataFrame]:
        """Fetch OHLCV via CCXT, trying each exchange in the fallback chain."""
        if not self._ccxt_available:
            return None

        chain = self._symbol_exchanges.get(symbol_name, [])
        if not chain:
            return None

        for ex_name, pair in chain:
            exchange = self._exchanges.get(ex_name)
            if exchange is None:
                continue

            try:
                fetch_tf, limit, aggregate_to = self._resolve_ccxt_params(
                    exchange, timeframe
                )

                # Calculate `since` — always pass it (required for Hyperliquid)
                tf_ms = TIMEFRAME_MS.get(fetch_tf, 60 * 60_000)
                since_ms = int((time.time() * 1000) - (limit * tf_ms * 1.1))

                self._ccxt_requests += 1
                candles = exchange.fetch_ohlcv(
                    pair, fetch_tf, since=since_ms, limit=limit
                )

                if not candles or len(candles) < 5:
                    continue

                df = pd.DataFrame(
                    candles,
                    columns=["timestamp", "open", "high", "low", "close", "volume"],
                )
                df["time"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                df = df.drop(columns=["timestamp"]).sort_values("time")
                df = df.reset_index(drop=True)

                # Aggregate if needed (e.g. 1h -> 6h)
                if aggregate_to:
                    df = self._aggregate_ohlcv(df, aggregate_to)

                if df.empty or len(df) < 5:
                    continue

                # Log candle count for every successful fetch
                logger.info(
                    f"[DATA] {symbol_name} fetched {len(df)} candles for {timeframe} "
                    f"via CCXT {ex_name}"
                )

                return df

            except Exception as e:
                self._ccxt_failures += 1
                logger.warning(
                    f"[{symbol_name}] CCXT {ex_name} {timeframe}: {e}"
                )
                continue

        return None

    def _fetch_ccxt_ticker(self, symbol_name: str) -> Optional[float]:
        """Get latest price via CCXT ticker."""
        if not self._ccxt_available:
            return None

        chain = self._symbol_exchanges.get(symbol_name, [])
        for ex_name, pair in chain:
            exchange = self._exchanges.get(ex_name)
            if exchange is None:
                continue
            try:
                self._ccxt_requests += 1
                ticker = exchange.fetch_ticker(pair)
                price = ticker.get("last") or ticker.get("close")
                if price and price > 0:
                    return float(price)
            except Exception as e:
                self._ccxt_failures += 1
                logger.debug(f"[{symbol_name}] CCXT ticker {ex_name}: {e}")
                continue
        return None

    def _aggregate_ohlcv(
        self, df: pd.DataFrame, target_tf: str
    ) -> pd.DataFrame:
        """Aggregate OHLCV data to a larger timeframe (e.g. 1h -> 6h)."""
        if df.empty:
            return df
        freq_map = {"6h": "6h", "16h": "16h", "4h": "4h", "1d": "1D"}
        freq = freq_map.get(target_tf, target_tf)

        df_idx = df.set_index("time")
        agg = (
            df_idx.resample(freq)
            .agg(
                {"open": "first", "high": "max", "low": "min",
                 "close": "last", "volume": "sum"}
            )
            .dropna()
            .reset_index()
        )
        return agg

    # ─── CoinGecko fallback ──────────────────────────────────────

    def _cg_rate_limit(self):
        """Enforce minimum gap between CoinGecko requests."""
        with self._lock:
            now = time.time()
            gap = now - self._last_cg_request_ts
            if gap < self._min_cg_request_gap:
                time.sleep(self._min_cg_request_gap - gap + random.uniform(0, 0.3))
            self._last_cg_request_ts = time.time()

    def _fetch_cg_market_chart(
        self, coin_id: str, days: int
    ) -> Optional[pd.DataFrame]:
        """Fetch raw price+volume data from CoinGecko."""
        cache_key = f"cg_raw:{coin_id}:{days}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart"
        params = {"vs_currency": "usd", "days": days}

        for attempt in range(self.max_retries):
            self._cg_rate_limit()
            self._cg_requests += 1
            try:
                resp = self._session.get(url, params=params, timeout=15)
                if resp.status_code == 429:
                    wait = min(int(resp.headers.get("Retry-After", 60)), 120)
                    logger.warning(
                        f"[{coin_id}] CoinGecko rate limited, waiting {wait}s"
                    )
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if "prices" not in data or "total_volumes" not in data:
                    return None

                prices = data["prices"]
                volumes = data["total_volumes"]

                df = pd.DataFrame(prices, columns=["timestamp", "close"])
                df["volume"] = [v[1] for v in volumes[: len(df)]]
                df["time"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
                df = df.drop(columns=["timestamp"]).set_index("time").sort_index()

                self._set_cache(cache_key, df.reset_index())
                return df.reset_index()

            except Exception as e:
                logger.warning(
                    f"[{coin_id}] CoinGecko attempt {attempt+1}/{self.max_retries}: {e}"
                )
                if attempt < self.max_retries - 1:
                    time.sleep(
                        self.retry_delay * (attempt + 1) + random.uniform(0, 1)
                    )

        return None

    def _resample_cg_to_ohlcv(
        self, df_raw: pd.DataFrame, freq: str
    ) -> pd.DataFrame:
        """Resample CoinGecko close+volume data into OHLCV candles."""
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
        return ohlcv

    def _fetch_cg_ohlcv(self, coin_id: str, timeframe: str) -> pd.DataFrame:
        """Fetch OHLCV from CoinGecko for a single timeframe."""
        tf_config = COINGECKO_TIMEFRAME_MAP.get(timeframe)
        if tf_config is None:
            return pd.DataFrame()

        raw = self._fetch_cg_market_chart(coin_id, tf_config["days"])
        if raw is None or raw.empty:
            return pd.DataFrame()

        if timeframe == "daily":
            return raw.copy()

        return self._resample_cg_to_ohlcv(raw, tf_config["freq"])

    # ─── Public API ──────────────────────────────────────────────

    def fetch_ohlcv(
        self, symbol_name: str, coin_id: str, timeframe: str
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data. Tries CCXT first, falls back to CoinGecko.

        Args:
            symbol_name: Symbol name for CCXT lookup (e.g. "BTC", "HYPE")
            coin_id: CoinGecko coin ID for fallback (e.g. "bitcoin", "hyperliquid")
            timeframe: "5m", "15m", "30m", "1h", "4h", "6h", "16h", "1d", "daily"
        """
        cache_key = f"ohlcv:{symbol_name}:{timeframe}"
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        # Try CCXT first
        df = self._fetch_ccxt_ohlcv(symbol_name, timeframe)
        if df is not None and not df.empty:
            self._set_cache(cache_key, df)
            return df

        # Fall back to CoinGecko
        logger.info(f"[{symbol_name}] CCXT unavailable for {timeframe}, falling back to CoinGecko")
        df = self._fetch_cg_ohlcv(coin_id, timeframe)
        if not df.empty:
            logger.info(f"[DATA] {symbol_name} fetched {len(df)} candles for {timeframe} via CoinGecko")
            self._set_cache(cache_key, df)
        return df

    def fetch_multi_timeframe(
        self, symbol_name: str, coin_id: str, timeframes: list
    ) -> Dict[str, pd.DataFrame]:
        """
        Fetch OHLCV for multiple timeframes. CCXT primary, CoinGecko fallback.

        Args:
            symbol_name: Symbol name for CCXT (e.g. "BTC")
            coin_id: CoinGecko coin ID for fallback (e.g. "bitcoin")
            timeframes: List of timeframes (e.g. ["1h", "6h", "daily"])
        """
        result = {}
        cg_fallback_tfs = []

        # Try CCXT for each timeframe
        for tf in timeframes:
            cache_key = f"ohlcv:{symbol_name}:{tf}"
            cached = self._get_cached(cache_key)
            if cached is not None:
                result[tf] = cached
                continue

            df = self._fetch_ccxt_ohlcv(symbol_name, tf)
            if df is not None and not df.empty:
                self._set_cache(cache_key, df)
                result[tf] = df
            else:
                cg_fallback_tfs.append(tf)

        # CoinGecko fallback for timeframes CCXT couldn't serve
        if cg_fallback_tfs:
            logger.info(
                f"[{symbol_name}] CoinGecko fallback for: {cg_fallback_tfs}"
            )
            # Group by CoinGecko lookback days to minimize API requests
            by_days: Dict[int, list] = {}
            for tf in cg_fallback_tfs:
                tf_config = COINGECKO_TIMEFRAME_MAP.get(tf)
                if tf_config is None:
                    result[tf] = pd.DataFrame()
                    continue
                days = tf_config["days"]
                if days not in by_days:
                    by_days[days] = []
                by_days[days].append((tf, tf_config["freq"]))

            for days, tf_list in by_days.items():
                raw = self._fetch_cg_market_chart(coin_id, days)
                if raw is None or raw.empty:
                    for tf, _ in tf_list:
                        result[tf] = pd.DataFrame()
                    continue

                for tf, freq in tf_list:
                    if tf == "daily":
                        df = raw.copy()
                    else:
                        df = self._resample_cg_to_ohlcv(raw, freq)
                    cache_key = f"ohlcv:{symbol_name}:{tf}"
                    if not df.empty:
                        self._set_cache(cache_key, df)
                    result[tf] = df

        return result

    def latest_price(
        self, symbol_name: str, coin_id: str
    ) -> Optional[float]:
        """Get the latest price. CCXT ticker first, CoinGecko fallback."""
        cache_key = f"price:{symbol_name}"
        cached = self._get_cached(cache_key)
        if cached is not None and not cached.empty:
            return float(cached["close"].iloc[-1])

        # Try CCXT ticker
        price = self._fetch_ccxt_ticker(symbol_name)
        if price is not None:
            df = pd.DataFrame([{"close": price}])
            self._set_cache(cache_key, df)
            return price

        # CoinGecko fallback
        raw = self._fetch_cg_market_chart(coin_id, days=1)
        if raw is not None and not raw.empty:
            return float(raw["close"].iloc[-1])

        return None

    def clear_cache(self):
        """Clear the data cache."""
        self._cache.clear()

    def get_stats(self) -> Dict[str, int]:
        """Return fetcher statistics."""
        return {
            "total_requests": self._ccxt_requests + self._cg_requests,
            "ccxt_requests": self._ccxt_requests,
            "cg_requests": self._cg_requests,
            "ccxt_failures": self._ccxt_failures,
            "cache_hits": len(self._cache),
        }
