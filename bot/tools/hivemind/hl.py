"""Shared Hyperliquid info-API client for the hivemind: per-process cache + polite retry on 429."""
import json
import time
import urllib.error
import urllib.request

_CACHE = {}
_LAST = [0.0]
MIN_GAP_S = 0.25


def post(body, ttl=60, timeout=30):
    key = json.dumps(body, sort_keys=True)
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    data = key.encode()
    for attempt in range(5):
        wait = MIN_GAP_S - (time.time() - _LAST[0])
        if wait > 0:
            time.sleep(wait)
        _LAST[0] = time.time()
        req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=data,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read())
            _CACHE[key] = (time.time(), out)
            return out
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 4:
                raise
            time.sleep(1.5 * (attempt + 1))


def candles(coin, interval, start_ms, end_ms=None, ttl=60):
    end_ms = end_ms or int(time.time() * 1000)
    end_ms = end_ms - end_ms % 60000          # round so identical requests in one run share the cache
    return post({"type": "candleSnapshot", "req": {"coin": coin, "interval": interval,
                                                   "startTime": int(start_ms), "endTime": int(end_ms)}}, ttl=ttl)
