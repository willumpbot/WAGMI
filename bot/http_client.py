"""
Shared HTTP client with connection pooling, retries, and rate limiting.

Provides a centralized requests.Session for all outbound HTTP calls
(exchange APIs, CoinGecko, Telegram, Discord webhooks) with:
- Connection pooling (keep-alive)
- Automatic retries with exponential backoff
- Global rate limiting to avoid 429s
- Timeout defaults
- User-Agent identification
"""

import logging
import os
import threading
import time
from typing import Optional, Dict, Any

logger = logging.getLogger("bot.http_client")

try:
    import requests
    from requests.adapters import HTTPAdapter
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False
    requests = None

try:
    from urllib3.util.retry import Retry
    _HAS_RETRY = True
except ImportError:
    _HAS_RETRY = False


_DEFAULT_TIMEOUT = (10, 30)  # (connect, read) seconds
_DEFAULT_RETRIES = 3
_USER_AGENT = "nunuIRL-TradingBot/1.0"

# Global rate limiter: max N requests per second across all endpoints
_RATE_LIMIT_RPS = float(os.getenv("HTTP_RATE_LIMIT_RPS", "10"))
_rate_lock = threading.Lock()
_last_request_times: list = []


class RateLimitedSession:
    """HTTP session with connection pooling, retries, and rate limiting."""

    def __init__(
        self,
        retries: int = _DEFAULT_RETRIES,
        backoff_factor: float = 0.5,
        timeout: tuple = _DEFAULT_TIMEOUT,
        rate_limit_rps: float = _RATE_LIMIT_RPS,
    ):
        if not _HAS_REQUESTS:
            raise ImportError("requests library required: pip install requests")

        self.timeout = timeout
        self.rate_limit_rps = rate_limit_rps
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": _USER_AGENT,
        })

        # Mount retry adapter for http and https
        if _HAS_RETRY:
            retry_strategy = Retry(
                total=retries,
                backoff_factor=backoff_factor,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET", "POST", "PUT", "DELETE"],
            )
            adapter = HTTPAdapter(
                max_retries=retry_strategy,
                pool_connections=10,
                pool_maxsize=20,
            )
        else:
            adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)

        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        # Stats
        self._request_count = 0
        self._error_count = 0

    def _wait_for_rate_limit(self):
        """Enforce global rate limit."""
        if self.rate_limit_rps <= 0:
            return
        min_interval = 1.0 / self.rate_limit_rps
        with _rate_lock:
            now = time.monotonic()
            # Clean old timestamps
            cutoff = now - 1.0
            while _last_request_times and _last_request_times[0] < cutoff:
                _last_request_times.pop(0)
            if len(_last_request_times) >= self.rate_limit_rps:
                sleep_time = _last_request_times[0] + 1.0 - now
                if sleep_time > 0:
                    time.sleep(sleep_time)
            _last_request_times.append(time.monotonic())

    def get(self, url: str, **kwargs) -> "requests.Response":
        """GET request with rate limiting and default timeout."""
        self._wait_for_rate_limit()
        kwargs.setdefault("timeout", self.timeout)
        self._request_count += 1
        try:
            return self._session.get(url, **kwargs)
        except Exception as e:
            self._error_count += 1
            raise

    def post(self, url: str, **kwargs) -> "requests.Response":
        """POST request with rate limiting and default timeout."""
        self._wait_for_rate_limit()
        kwargs.setdefault("timeout", self.timeout)
        self._request_count += 1
        try:
            return self._session.post(url, **kwargs)
        except Exception as e:
            self._error_count += 1
            raise

    def put(self, url: str, **kwargs) -> "requests.Response":
        """PUT request with rate limiting and default timeout."""
        self._wait_for_rate_limit()
        kwargs.setdefault("timeout", self.timeout)
        self._request_count += 1
        try:
            return self._session.put(url, **kwargs)
        except Exception as e:
            self._error_count += 1
            raise

    def delete(self, url: str, **kwargs) -> "requests.Response":
        """DELETE request with rate limiting and default timeout."""
        self._wait_for_rate_limit()
        kwargs.setdefault("timeout", self.timeout)
        self._request_count += 1
        try:
            return self._session.delete(url, **kwargs)
        except Exception as e:
            self._error_count += 1
            raise

    def get_stats(self) -> Dict[str, Any]:
        """Get client statistics."""
        return {
            "requests": self._request_count,
            "errors": self._error_count,
            "error_rate": self._error_count / max(self._request_count, 1),
        }

    def close(self):
        """Close the session."""
        self._session.close()


# Singleton
_instance: Optional[RateLimitedSession] = None


def get_http_client() -> RateLimitedSession:
    """Get the shared HTTP client singleton."""
    global _instance
    if _instance is None:
        _instance = RateLimitedSession()
    return _instance
