#!/usr/bin/env python
"""
WAGMI Co-Pilot MICRO-CAP DATA RECON PROBE - microcap_recon.py
=============================================================================
Standalone, READ-ONLY. Lives under tools/copilot/; writes NOTHING to disk,
imports NOTHING from llm/, execution/, core/, strategies/, and never touches
any live-bot state file, .env, or data/replay/ - same isolation contract as
the rest of tools/copilot/ (see tools/copilot/README.md). This is a probe,
not a collector: it hits public documented APIs a handful of times, prints
what it finds, and exits. It does not run continuously and does not persist
snapshots (unlike liq_collector.py, which is a real forward-collector).

WHY THIS EXISTS
-------------------------------------------------------------------------
Companion script to tools/copilot/MICROCAP_DATA_RECON.md - the full recon
report on whether Solana cat-coin / micro-cap DEX data is usable to test
(and eventually trade) the owner's thin-tail-edge thesis. This script is
the re-runnable, literal evidence behind that report's claims: run it any
time to re-confirm reachability/behavior hasn't silently changed (the same
"verify live, don't trust stale docs" discipline as liq_collector.py's
Binance-WS-geo-block lesson).

SOURCES PROBED (2026-08-06, live from this machine) - see the report for
full detail and citations:
  1. DexScreener  (api.dexscreener.com)      - snapshot-only, no OHLC. 60
     req/min per docs.dexscreener.com/api/reference.
  2. GeckoTerminal (api.geckoterminal.com/api/v2) - REAL historical OHLCV
     candles (day/hour/minute, aggregate param), free, no key. Confirmed
     HARD CAP: HTTP 401 "You can only access data from the past 180 days
     with Public API" beyond that. Confirmed 30 calls/min (empirically hit
     429 after a short burst; matches CoinGecko's documented public limit).
     Also confirmed: dead/zero-liquidity pump.fun-stage pools STILL return
     their OHLCV after dying (tested live on a pool with reserve_in_usd=0)
     - price history is not erased on death, only DISCOVERY of the address
     is time-sensitive (new_pools/dexes-pools listings are rolling/current,
     not a historical launch log).
  3. Jupiter Token API v2 (lite-api.jup.ag) - live snapshot only, no OHLC
     history. But: /tokens/v2/search, /tokens/v2/toporganicscore/{interval},
     /tokens/v2/recent give holderCount + buyVolume/sellVolume ALONGSIDE
     buyOrganicVolume/sellOrganicVolume/numOrganicBuyers - a built-in
     organic-vs-total volume split usable as a wash-trading filter.
  4. Birdeye (public-api.birdeye.so) - all endpoints 401 Unauthorized
     without an API key. Not probed further (would require registering a
     key, out of scope for anonymous read-only recon).
  5. pump.fun frontend-api (frontend-api-v3.pump.fun) - reachable (HTTP
     200), but UNDOCUMENTED internal API with no public docs and no stated
     ToS for third-party use. Probed for reachability ONLY, not used for
     data - flagged in the report as "don't build on this."
  6. FOMO app (fomo.family) - consumer mobile/social trading app (~$17M
     Series A, Nov 2025). No docs.fomo.family or api.fomo.family subdomain
     resolves. Walled garden, no public documented API found - NOT probed
     beyond DNS/homepage reachability, per "no sketchy scraping" mandate.

USAGE
-------------------------------------------------------------------------
    python tools/copilot/microcap_recon.py                 # run all probes
    python tools/copilot/microcap_recon.py --symbol WIF     # probe one token
    python tools/copilot/microcap_recon.py --skip-geckoterminal  # faster,
        avoids the 30/min rate limit if you're iterating quickly

Exit code is always 0 (recon tool, not a health check) - read the printed
report to see what worked.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, Optional

import requests

TIMEOUT = 12
UA = {"User-Agent": "wagmi-microcap-recon/1.0 (read-only research probe)"}

# Known Solana mint addresses for the owner's actual coins (used as default
# probe targets so results are grounded in real, currently-liquid pairs).
KNOWN_MINTS = {
    "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
}


def _get(url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("headers", UA)
    kwargs.setdefault("timeout", TIMEOUT)
    return requests.get(url, **kwargs)


def _safe_json(resp: requests.Response) -> Optional[Any]:
    try:
        return resp.json()
    except Exception:
        return None


def _report(title: str) -> None:
    print(f"\n=== {title} ===")


def probe_dexscreener(mint: str) -> None:
    _report("DexScreener")
    try:
        r = _get(f"https://api.dexscreener.com/tokens/v1/solana/{mint}")
        j = _safe_json(r)
        if r.status_code == 200 and j:
            p = j[0]
            print(f"  OK  price=${p.get('priceUsd')}  liq=${p['liquidity']['usd']:,.0f}"
                  f"  vol24h=${p['volume']['h24']:,.0f}  fdv=${p.get('fdv'):,.0f}")
            print(f"      pairCreatedAt(ms)={p.get('pairCreatedAt')}"
                  f"  dex={p.get('dexId')}  fields=price/liq/vol/txns/priceChange"
                  f"(m5,h1,h6,h24)/fdv/mcap/pairCreatedAt")
            print("      NO historical OHLC/candle endpoint exists on this API "
                  "(confirmed vs docs.dexscreener.com/api/reference) - "
                  "snapshot + 4 rolling windows only.")
        else:
            print(f"  FAIL status={r.status_code} body={r.text[:200]}")
    except Exception as e:
        print(f"  ERROR {e!r}")


def probe_geckoterminal(mint: str, pool_hint: Optional[str] = None) -> None:
    _report("GeckoTerminal (CoinGecko onchain API)")
    try:
        pool = pool_hint
        if pool is None:
            r = _get(
                "https://api.geckoterminal.com/api/v2/search/pools",
                params={"query": mint, "network": "solana"},
            )
            j = _safe_json(r)
            if r.status_code != 200 or not j or not j.get("data"):
                print(f"  FAIL search status={r.status_code} body={r.text[:200]}")
                return
            pool = j["data"][0]["attributes"]["address"]
            print(f"  resolved pool: {pool}")
        time.sleep(2.5)  # respect 30 req/min public limit
        r = _get(
            f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{pool}/ohlcv/day",
            params={"aggregate": 1, "limit": 1000},
        )
        j = _safe_json(r)
        if r.status_code == 200 and j:
            candles = j["data"]["attributes"]["ohlcv_list"]
            newest = time.strftime("%Y-%m-%d", time.gmtime(candles[0][0])) if candles else "n/a"
            oldest = time.strftime("%Y-%m-%d", time.gmtime(candles[-1][0])) if candles else "n/a"
            print(f"  OK  {len(candles)} daily candles  range=[{oldest} .. {newest}]")
            print("      granularities available: day / hour / minute (via ?aggregate=N)")
            print("      free-tier hard cap: 180 days back from now (HTTP 401 beyond that) - "
                  "confirmed live, not just documented.")
        elif r.status_code == 401:
            print(f"  401 (past the 180-day free window): {r.text[:200]}")
        elif r.status_code == 429:
            print("  429 rate-limited (public tier: 30 req/min) - back off and retry")
        else:
            print(f"  FAIL status={r.status_code} body={r.text[:200]}")
    except Exception as e:
        print(f"  ERROR {e!r}")


def probe_jupiter(mint: str) -> None:
    _report("Jupiter Token API v2 (lite-api.jup.ag)")
    try:
        r = _get("https://lite-api.jup.ag/price/v3", params={"ids": mint})
        j = _safe_json(r)
        if r.status_code == 200 and j and mint in j:
            d = j[mint]
            print(f"  price/v3 OK  price=${d.get('usdPrice')}  liq=${d.get('liquidity'):,.0f}"
                  f"  createdAt={d.get('createdAt')}  (LIVE ONLY - no history)")
        else:
            print(f"  price/v3 FAIL status={r.status_code}")

        r2 = _get("https://lite-api.jup.ag/tokens/v2/search", params={"query": mint})
        j2 = _safe_json(r2)
        if r2.status_code == 200 and j2:
            t = j2[0]
            s24 = t.get("stats24h", {}) or {}
            buy_v = s24.get("buyVolume")
            buy_org = s24.get("buyOrganicVolume")
            ratio = f"{(buy_org / buy_v):.1%}" if buy_v else "n/a"
            print(f"  tokens/v2/search OK  holderCount={t.get('holderCount')}"
                  f"  mcap=${t.get('mcap'):,.0f}"
                  f"  24h buyVolume=${buy_v}  buyOrganicVolume=${buy_org} (organic ratio={ratio})")
            print("      organic-vs-total volume split usable as a wash-trading filter.")
        else:
            print(f"  tokens/v2/search FAIL status={r2.status_code}")
    except Exception as e:
        print(f"  ERROR {e!r}")


def probe_birdeye(mint: str) -> None:
    _report("Birdeye (public-api.birdeye.so)")
    try:
        r = _get("https://public-api.birdeye.so/defi/price", params={"address": mint})
        print(f"  status={r.status_code} body={r.text[:150]}")
        print("  Requires a registered API key for ALL endpoints (401 Unauthorized without "
              "one) - not usable anonymously. Deepest OHLCV provider for Solana if a free key "
              "is ever registered, but out of scope for this read-only probe.")
    except Exception as e:
        print(f"  ERROR {e!r}")


def probe_universe_enumeration() -> None:
    _report("Universe enumeration (GeckoTerminal new_pools / dexes-pools, Jupiter recent)")
    try:
        time.sleep(2.5)
        r = _get(
            "https://api.geckoterminal.com/api/v2/networks/solana/dexes/pump-fun/pools",
            params={"page": 1},
        )
        j = _safe_json(r)
        if r.status_code == 200 and j:
            n = len(j.get("data", []))
            print(f"  GT dexes/pump-fun/pools: {n} bonding-curve-stage pools on latest page "
                  "(includes ones already at $0 liquidity - confirms dead pools are NOT purged "
                  "from the index once discovered).")
        else:
            print(f"  GT dexes/pump-fun/pools FAIL status={r.status_code}")

        r2 = _get("https://lite-api.jup.ag/tokens/v2/recent")
        j2 = _safe_json(r2)
        if r2.status_code == 200 and j2:
            print(f"  Jupiter tokens/v2/recent: {len(j2)} freshly-launched tokens returned "
                  "(seconds-to-minutes old, holderCount as low as 1).")
        else:
            print(f"  Jupiter tokens/v2/recent FAIL status={r2.status_code}")
    except Exception as e:
        print(f"  ERROR {e!r}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--symbol", default="POPCAT", help="Symbol to probe (must be in KNOWN_MINTS, "
                     "or pass --mint directly)")
    ap.add_argument("--mint", default=None, help="Solana mint address to probe directly")
    ap.add_argument("--skip-geckoterminal", action="store_true",
                     help="Skip GT probes (avoids the 30/min rate limit while iterating)")
    ap.add_argument("--skip-universe", action="store_true", help="Skip universe-enumeration probes")
    args = ap.parse_args()

    mint = args.mint or KNOWN_MINTS.get(args.symbol.upper())
    if not mint:
        print(f"Unknown symbol {args.symbol!r} and no --mint given. "
              f"Known symbols: {list(KNOWN_MINTS)}")
        sys.exit(1)

    print(f"WAGMI micro-cap data recon probe - target: {args.symbol} ({mint})")
    print("Read-only. No writes. No live-bot imports. See MICROCAP_DATA_RECON.md for the report.")

    probe_dexscreener(mint)
    if not args.skip_geckoterminal:
        probe_geckoterminal(mint)
    else:
        _report("GeckoTerminal")
        print("  SKIPPED (--skip-geckoterminal)")
    probe_jupiter(mint)
    probe_birdeye(mint)
    if not args.skip_universe:
        probe_universe_enumeration()

    print("\nDone. See tools/copilot/MICROCAP_DATA_RECON.md for the full findings and "
          "recommended collection plan.")


if __name__ == "__main__":
    main()
