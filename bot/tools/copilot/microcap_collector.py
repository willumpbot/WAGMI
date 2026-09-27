#!/usr/bin/env python
"""
WAGMI Co-Pilot MICRO-CAP / SOLANA CAT-COIN COLLECTOR - microcap_collector.py
=============================================================================
Standalone, READ-ONLY w.r.t. the live paper bot. Lives under tools/copilot/;
writes ONLY to data/microcap/ (a brand-new directory - never touches
data/copilot/, data/replay/, .env, or any live-bot state file). No Discord
push. No imports of llm/, execution/, core/, strategies/ - same isolation
contract as liq_collector.py / the rest of tools/copilot/ (see README.md).

WHY THIS EXISTS
-------------------------------------------------------------------------
Companion collector to tools/copilot/MICROCAP_DATA_RECON.md, which confirmed
(live, from this machine, 2026-08-06) that a usable, free, no-key data stack
exists to test the owner's thesis that real edge lives in the thin,
less-efficient Solana cat-coin / micro-cap tail that Hyperliquid mid-cap data
can't reach (owner trades $KITTY, $POPCAT + other Solana memes):
  - GeckoTerminal (api.geckoterminal.com/api/v2): free real OHLCV candles
    (day/hour/minute), no key, 30 req/min, hard-capped at a rolling 180-day
    window on the free tier.
  - DexScreener (api.dexscreener.com): free live liquidity/volume/mcap/age
    snapshots, no key, ~60 req/min. NO historical candles - snapshot only.
  - Jupiter Token API v2 (lite-api.jup.ag): free organic-vs-total volume
    split per token - a real wash-trading measurement tool, not just a
    warning. POPCAT's own 24h organic-BUY ratio came back 10.0% in recon -
    an ESTABLISHED, real, liquid coin. Read that as the realistic baseline,
    not a disqualifying red flag; the value here is a RELATIVE/rank signal
    and a sudden-drop alarm, not a hard ">50% required" filter.

THE SURVIVORSHIP FIX - the single most important thing this file does
-------------------------------------------------------------------------
Per the recon report (S4a): GeckoTerminal does NOT purge dead pools from its
own index once a pool address is known (verified live on an already-$0
pool). So the bias is entirely in DISCOVERY, not retention. A universe
assembled by searching for coins "that look interesting today" is
survivor-poisoned - the ~98%+ of pump.fun launches that died on the bonding
curve are invisible to a retrospective search. The fix: run discovery
FORWARD, continuously, logging every newly-seen Solana pair the moment it's
seen (dead or alive later, we'll still have it on file). This file's
`--discover` mode starts that clock TODAY. The Tier-B "systematic universe"
screen (see build_universe()) draws EXCLUSIVELY from this forward discovery
log - never from a fresh retrospective search - so the survivorship fix is
structural, not just a caveat in a docstring.

ISOLATION CONTRACT
-------------------------------------------------------------------------
- Writes ONLY under data/microcap/ (this file creates the directory).
- Imports: stdlib + `requests` only. No llm/, execution/, core/, strategies/.
- No Discord webhook, no .env reads/writes, no data/replay/ writes.
- Never touches the live bot's positions, trades.csv, decisions.jsonl, or
  heartbeat. Fully standalone - can run, crash, or be killed without any
  effect on the paper bot.

RATE LIMITS - respected per-host, confirmed against recon's live findings
-------------------------------------------------------------------------
  GeckoTerminal : 30 req/min documented + reproduced live (429 after a rapid
                  burst) -> throttled to a minimum 2.2s gap between calls
                  (~27/min, safety margin under the cap) with exponential
                  backoff + Retry-After respect on any 429.
  DexScreener   : 60 req/min documented -> throttled to a minimum 1.1s gap.
  Jupiter v2    : no disclosed limit in recon (no 429 hit in light testing)
                  -> still throttled to a conservative 1.0s gap; same
                  backoff-on-429 contract applied defensively.
Every host's limiter is independent (a slow GT page doesn't block DexScreener
calls) and every HTTP call funnels through `_get_json()`, so there is exactly
one place rate-limiting and backoff live - no per-endpoint copy-paste.

FIELD SHAPES - verified LIVE 2026-08-06 from this machine (not guessed):
-------------------------------------------------------------------------
  GT pool object (new_pools / dexes/{id}/pools / search/pools):
    attributes.address, attributes.name ("SYM / SOL"), attributes.
    pool_created_at (ISO8601), attributes.reserve_in_usd, attributes.
    fdv_usd, attributes.market_cap_usd, attributes.volume_usd.h24,
    relationships.base_token.data.id ("solana_<mint>"),
    relationships.dex.data.id (e.g. "pump-fun", "raydium").
  GT ohlcv: data.attributes.ohlcv_list = [[ts_unix, o, h, l, c, vol_usd], ...]
    ordered NEWEST-FIRST (verified: element 0 has the latest timestamp).
  DexScreener /tokens/v1/solana/{mint}: array of pair objects with
    pairAddress, dexId, baseToken.{address,name,symbol}, priceUsd,
    liquidity.usd, volume.{m5,h1,h6,h24}, txns.{...}, fdv, marketCap,
    pairCreatedAt (epoch MS).
  Jupiter /tokens/v2/search or /recent: id (mint), name, symbol, holderCount,
    mcap, fdv, usdPrice, liquidity, stats{5m,1h,6h,24h}.{buyVolume,
    sellVolume,buyOrganicVolume,sellOrganicVolume,numBuys,numSells,
    numTraders,numOrganicBuyers}. NOT every field present on every token
    (freshly-launched tokens can be missing mcap/liquidity/stats24h) -
    every read here is defensive (.get with None fallback).

NAMED-COIN RESOLUTION (Tier A) - symbol collisions are REAL, verified live
-------------------------------------------------------------------------
Searching DexScreener for "KITTY" on Solana returns AT LEAST 8 distinct
pairs/mints using the KITTY symbol (verified live), most with no metadata.
Picking the wrong one silently corrupts every downstream number. This file's
resolution heuristic: search DexScreener, keep only Solana pairs whose
baseToken.symbol matches (case-insensitive), rank by liquidity.usd desc,
THEN cross-check the top candidate against Jupiter's token metadata (name/
twitter/website) as a real-world sanity signal - a coin with a matching
name + live socials (e.g. KITTY -> "Hello Kitty" / x.com/hkittycoin /
hellokitty.website, confirmed live) is a much stronger match than a bare
mint with no metadata. The resolution is still logged as a heuristic, not a
certainty - `universe.json`'s tier_a entries carry `resolution_method` and
`alternate_candidates_considered` so a human can override if the coin
resolved. POPCAT's mint is pinned directly (confirmed in the recon report:
7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr) - no search needed.

CLI
-------------------------------------------------------------------------
  python tools/copilot/microcap_collector.py --smoke
      Small live test of every stage (discover 1 page/source, resolve
      named coins, pull a few OHLCV candles, one snapshot+wash pass). This
      is the "show me it works" command.

  python tools/copilot/microcap_collector.py --discover
      One forward-discovery poll (GT new_pools + per-dex pools + Jupiter
      recent) -> appends new pairs to discovery_log.jsonl. Run this often
      (the whole survivorship fix depends on cadence, not one-off runs).

  python tools/copilot/microcap_collector.py --universe
      (Re)build universe.json: Tier A (named coins, always included) +
      Tier B systematic (screen applied to discovery_log.jsonl candidates
      ONLY - never a fresh search, see survivorship note above).

  python tools/copilot/microcap_collector.py --screen-established
      (Re)build ONLY universe.json's tier_b_established section: the
      CURRENT liquid-but-thin cat/meme universe (GT trending_pools + top
      pools on raydium/pumpswap/moonshot + DexScreener keyword search across
      cat/kitty/inu/pepe/bonk/wif/dog/meow/paw/moon), screened to
      $50k-$5M liquidity / >=14d old / Solana-only / no stables-wrapped.
      This is the fix for Tier B systematic producing 0 coins: the forward
      discovery log only ever catches $0-liquidity newborns, which can never
      be the owner's actual (established, thin) trading universe. Merge-safe
      with --universe in both directions - each preserves the other's
      section across its own rewrite. Tuning: --established-min-liquidity-usd
      --established-max-liquidity-usd --established-min-age-days.

  python tools/copilot/microcap_collector.py --history
      Pull/refresh day+hour OHLCV (GeckoTerminal) for every coin currently
      in universe.json. Idempotent - only fetches/appends candles newer
      than what's already on disk; a fresh CSV backfills to the 180d cap.

  python tools/copilot/microcap_collector.py --snapshot
      One liquidity/volume/mcap snapshot (DexScreener) + one organic-volume
      wash-signal read (Jupiter) per universe coin.

  python tools/copilot/microcap_collector.py --testable
      (Re)build universe_testable.json: universe.json's coins narrowed to
      those with sufficient mint-keyed OHLCV already on disk (default >=20
      day candles) and a current liquidity read above the screen floor -
      no network calls, pure on-disk/on-file rollup. Wash-heaviness
      (buy_organic_ratio_24h) is recorded and FLAGGED, never used to
      exclude - see build_testable_universe() docstring and INTEGRITY_NOTES
      #3 (POPCAT's own organic baseline is ~10%). This is the file an
      analysis/backtest script should actually load, not universe.json
      itself (which is the candidate list, not a data-availability check).

  python tools/copilot/microcap_collector.py --once
      Run discover -> universe -> history -> snapshot once, in that order,
      then exit. (If none of --discover/--universe/--history/--snapshot are
      given alongside --once, all four run; pass a subset to restrict.)

  python tools/copilot/microcap_collector.py --daemon
      Loop forever: discover + snapshot every --interval-min (default 20),
      history refresh every --history-every-n-cycles (default 6, i.e. ~2h
      at the default interval). Ctrl-C to stop. NOT registered as a
      scheduled task by this file - see run_microcap_collector.ps1 for the
      supervisor wrapper (build-only, not registered, per instructions).

  Universe-screen tuning (Tier B only - Tier A named coins always included
  regardless of these):
    --min-liquidity-usd 30000   --max-liquidity-usd 5000000
    --min-age-hours 24          --max-age-days (unset = no cap; GT itself
                                 caps history retrieval at 180d regardless)

See data/microcap/INTEGRITY_NOTES.md (written/refreshed by this file on
every run) for the full, loud statement of survivorship/wash/slippage/
history-cap caveats. Read it before treating anything derived from this
data as a backtest result rather than an honest forward-test foundation.
"""
from __future__ import annotations

import argparse
import csv
import gc
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, List, Optional, Tuple

import requests

# ---------------------------------------------------------------------------
# Paths - all writes confined to data/microcap/ (brand-new dir, per mandate)
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))            # tools/copilot
BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))              # bot/
OUT_DIR = os.path.join(BOT_DIR, "data", "microcap")
OHLCV_DIR = os.path.join(OUT_DIR, "ohlcv")
DISCOVERY_LOG_PATH = os.path.join(OUT_DIR, "discovery_log.jsonl")
UNIVERSE_PATH = os.path.join(OUT_DIR, "universe.json")
WASH_LOG_PATH = os.path.join(OUT_DIR, "wash_signal.jsonl")
LIQ_SNAPSHOT_PATH = os.path.join(OUT_DIR, "liquidity_snapshots.jsonl")
FLOW_SIGNAL_PATH = os.path.join(OUT_DIR, "flow_signal.jsonl")
INTEGRITY_NOTES_PATH = os.path.join(OUT_DIR, "INTEGRITY_NOTES.md")
LOG_PATH = os.path.join(OUT_DIR, "collector.log")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
GT_BASE = "https://api.geckoterminal.com/api/v2"
DS_BASE = "https://api.dexscreener.com"
JUP_BASE = "https://lite-api.jup.ag"
UA = {"User-Agent": "wagmi-microcap-collector/1.0 (read-only research collector)"}
TIMEOUT = 15

# Solana DEX ids enumerated in recon S1/S3 - covers bonding-curve-stage
# (pump-fun, boop-fun) through graduated AMM pools (raydium, pumpswap,
# moonshot, bags-fm).
DEX_IDS = ["pump-fun", "pumpswap", "raydium", "moonshot", "bags-fm", "boop-fun"]

# Owner's named coins (Tier A - ALWAYS in universe regardless of the Tier B
# screen). POPCAT's mint is pinned per the recon report's live confirmation;
# everything else resolves at runtime via _resolve_named_coin() with the
# symbol-collision guard described in the module docstring.
NAMED_COINS: Dict[str, Optional[str]] = {
    "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
    "KITTY": None,  # resolved live - multiple Solana symbol collisions exist
}

# Symbols to exclude from the Tier B systematic screen even if they show up
# in discovery (stables / wrapped-native, per task spec item 2).
STABLE_WRAPPED_BLACKLIST = {
    "SOL", "WSOL", "USDC", "USDT", "USDH", "UXD", "PYUSD", "USDS", "DAI",
    "WBTC", "WETH", "CBBTC", "SUSD", "USDE",
}

# Per-host minimum gap between requests (seconds). GeckoTerminal's 30/min is
# the tightest confirmed-live limit (recon: 429 after a rapid burst) - 2.2s
# keeps us at ~27/min, a real safety margin, not a hair's-width one.
MIN_INTERVAL_S = {
    "geckoterminal": 2.2,
    "dexscreener": 1.1,
    "jupiter": 1.0,
}
BACKOFF_BASE_S = 3.0
BACKOFF_CAP_S = 90.0
MAX_RETRIES = 4

GT_OHLCV_LIMIT = 1000          # GT's own per-request cap
GT_HISTORY_CAP_DAYS = 180      # free-tier hard cap, confirmed live in recon

DEFAULT_MIN_LIQUIDITY_USD = 30_000.0
DEFAULT_MAX_LIQUIDITY_USD = 5_000_000.0
DEFAULT_MIN_AGE_HOURS = 24.0

# --- Tier B ESTABLISHED screen (--screen-established) -----------------------
# Unlike Tier B systematic above (drawn EXCLUSIVELY from the forward
# discovery log to avoid survivorship bias on brand-new pump.fun-stage
# launches - see module docstring), this screen targets coins that are
# ALREADY established and liquid right now (the owner's actual arena: $KITTY,
# $POPCAT and peers). Survivorship bias does not apply the same way here: a
# coin that has been alive and liquid for >=14 days is, by construction,
# still findable by a current search - it isn't a bonding-curve newborn that
# could have died and vanished before discovery. A retrospective/current
# search is therefore the CORRECT method for this tier, not a shortcut that
# reintroduces the bias the Tier B systematic design avoids.
ESTABLISHED_SEARCH_TERMS = ["cat", "kitty", "inu", "pepe", "bonk", "wif", "dog", "meow", "paw", "moon"]
# Graduated AMM venues only (excludes pump-fun/boop-fun bonding-curve stage -
# those are the $0-liquidity newborns the Tier B systematic screen already
# targets via forward discovery; established coins live on real AMMs).
ESTABLISHED_DEX_IDS = ["raydium", "pumpswap", "moonshot"]
DEFAULT_ESTABLISHED_MIN_LIQUIDITY_USD = 50_000.0
DEFAULT_ESTABLISHED_MAX_LIQUIDITY_USD = 5_000_000.0
DEFAULT_ESTABLISHED_MIN_AGE_DAYS = 14.0
ESTABLISHED_MAX_COINS = 60  # target ~30-60; cap by liquidity desc if search surfaces more


# ---------------------------------------------------------------------------
# Logging - isolated to data/microcap/, mirrors liq_collector.py's setup
# ---------------------------------------------------------------------------
def _build_logger() -> logging.Logger:
    os.makedirs(OUT_DIR, exist_ok=True)
    logger = logging.getLogger("microcap_collector")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%SZ")
    fh = RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


LOG = _build_logger()


# ---------------------------------------------------------------------------
# Rate-limited, retrying HTTP layer - the ONE place every call funnels
# through, so limiting/backoff logic isn't duplicated per endpoint.
# ---------------------------------------------------------------------------
_last_call_ts: Dict[str, float] = {}


def _throttle(host: str) -> None:
    min_gap = MIN_INTERVAL_S.get(host, 1.0)
    last = _last_call_ts.get(host, 0.0)
    elapsed = time.time() - last
    if elapsed < min_gap:
        time.sleep(min_gap - elapsed)
    _last_call_ts[host] = time.time()


def _get_json(host: str, url: str, params: Optional[dict] = None) -> Tuple[Optional[int], Any]:
    """Rate-limited GET -> (status_code, parsed_json_or_None). Never raises -
    fail-soft is the contract for a standalone collector (one bad response
    must not kill a multi-hour --daemon run)."""
    backoff = BACKOFF_BASE_S
    for attempt in range(1, MAX_RETRIES + 1):
        _throttle(host)
        try:
            r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
        except requests.RequestException as e:
            LOG.warning(f"{host}: request error ({type(e).__name__}: {e}) attempt {attempt}/{MAX_RETRIES}")
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_CAP_S)
            continue
        if r.status_code == 429:
            # NOTE: GeckoTerminal's own 429 response was confirmed LIVE to send
            # `Retry-After: 0` (verified 2026-08-06, not a hypothetical) - a
            # literal 0 would defeat backoff entirely and cause a 429-retry
            # storm. Never trust the header below our own exponential floor.
            retry_after = r.headers.get("Retry-After")
            hinted = float(retry_after) if retry_after and retry_after.replace(".", "", 1).isdigit() else 0.0
            wait = max(hinted, backoff)
            LOG.warning(f"{host}: 429 rate-limited, backing off {wait:.1f}s (attempt {attempt}/{MAX_RETRIES})")
            time.sleep(wait)
            backoff = min(backoff * 2, BACKOFF_CAP_S)
            continue
        if r.status_code >= 500:
            LOG.warning(f"{host}: {r.status_code} server error, retrying in {backoff:.1f}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, BACKOFF_CAP_S)
            continue
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, None
    LOG.error(f"{host}: giving up after {MAX_RETRIES} attempts: {url}")
    return None, None


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ms_to_iso(ms) -> Optional[str]:
    try:
        return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _append_jsonl(path: str, row: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()


def _read_jsonl(path: str) -> List[dict]:
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


# ---------------------------------------------------------------------------
# GeckoTerminal
# ---------------------------------------------------------------------------
def gt_search_pools(query: str) -> List[dict]:
    status, j = _get_json("geckoterminal", f"{GT_BASE}/search/pools", {"query": query, "network": "solana"})
    if status != 200 or not j:
        return []
    return j.get("data", []) or []


def gt_new_pools(page: int = 1) -> List[dict]:
    status, j = _get_json("geckoterminal", f"{GT_BASE}/networks/solana/new_pools", {"page": page})
    if status != 200 or not j:
        return []
    return j.get("data", []) or []


def gt_dex_pools(dex_id: str, page: int = 1) -> List[dict]:
    status, j = _get_json("geckoterminal", f"{GT_BASE}/networks/solana/dexes/{dex_id}/pools", {"page": page})
    if status != 200 or not j:
        return []
    return j.get("data", []) or []


def gt_trending_pools(page: int = 1) -> List[dict]:
    """GT's current trending-pools listing for Solana. Used by the Tier B
    ESTABLISHED screen (current-state search), never by the survivorship-safe
    forward discovery log (--discover uses new_pools/dexes-pools only)."""
    status, j = _get_json("geckoterminal", f"{GT_BASE}/networks/solana/trending_pools", {"page": page})
    if status != 200 or not j:
        return []
    return j.get("data", []) or []


def gt_ohlcv(pool_address: str, timeframe: str, aggregate: int = 1,
             before_timestamp: Optional[int] = None, limit: int = GT_OHLCV_LIMIT) -> Tuple[Optional[int], List[list]]:
    params = {"aggregate": aggregate, "limit": limit}
    if before_timestamp is not None:
        params["before_timestamp"] = before_timestamp
    status, j = _get_json("geckoterminal", f"{GT_BASE}/networks/solana/pools/{pool_address}/ohlcv/{timeframe}", params)
    if status == 200 and j:
        try:
            return status, j["data"]["attributes"]["ohlcv_list"]
        except (KeyError, TypeError):
            return status, []
    return status, []


def _gt_pool_to_discovery_row(d: dict, source: str) -> Optional[dict]:
    """Normalize a GT pool object (new_pools / dexes-pools / search/pools) to
    a discovery-log row. See module docstring's FIELD SHAPES section."""
    try:
        attrs = d.get("attributes", {}) or {}
        address = attrs.get("address")
        if not address:
            return None
        name = attrs.get("name", "") or ""
        symbol = name.split("/")[0].strip() if "/" in name else name.strip()
        rel = d.get("relationships", {}) or {}
        base_id = ((rel.get("base_token") or {}).get("data") or {}).get("id", "") or ""
        mint = base_id.split("_", 1)[1] if "_" in base_id else None
        dex_id = ((rel.get("dex") or {}).get("data") or {}).get("id")
        liq = attrs.get("reserve_in_usd")
        return {
            "pair_address": address,
            "mint": mint,
            "symbol": symbol,
            "name": name,
            "dex_id": dex_id,
            "network": "solana",
            "pool_created_at": attrs.get("pool_created_at"),
            "first_seen_ts": _iso_now(),
            "liquidity_usd_at_discovery": float(liq) if liq not in (None, "") else None,
            "fdv_usd_at_discovery": _safe_float(attrs.get("fdv_usd")),
            "source": source,
        }
    except Exception as e:
        LOG.warning(f"discovery: failed to parse GT pool row ({type(e).__name__}: {e})")
        return None


def _safe_float(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# DexScreener
# ---------------------------------------------------------------------------
def ds_search(query: str) -> List[dict]:
    status, j = _get_json("dexscreener", f"{DS_BASE}/latest/dex/search", {"q": query})
    if status != 200 or not j:
        return []
    return j.get("pairs", []) or []


def ds_token_pairs(mint: str) -> List[dict]:
    status, j = _get_json("dexscreener", f"{DS_BASE}/tokens/v1/solana/{mint}")
    if status != 200 or not j or not isinstance(j, list):
        return []
    return j


def _jupiter_recent_to_discovery_row(t: dict) -> Optional[dict]:
    mint = t.get("id")
    if not mint:
        return None
    return {
        "pair_address": None,  # Jupiter's recent feed is mint-level, not pool-level
        "mint": mint,
        "symbol": t.get("symbol"),
        "name": t.get("name"),
        "dex_id": t.get("launchpad"),
        "network": "solana",
        "pool_created_at": None,
        "first_seen_ts": _iso_now(),
        "liquidity_usd_at_discovery": _safe_float(t.get("liquidity")),
        "fdv_usd_at_discovery": _safe_float(t.get("fdv")),
        "source": "jupiter_recent",
    }


# ---------------------------------------------------------------------------
# Jupiter Token API v2
# ---------------------------------------------------------------------------
def jup_search(query: str) -> List[dict]:
    status, j = _get_json("jupiter", f"{JUP_BASE}/tokens/v2/search", {"query": query})
    if status != 200 or not j or not isinstance(j, list):
        return []
    return j


def jup_recent() -> List[dict]:
    status, j = _get_json("jupiter", f"{JUP_BASE}/tokens/v2/recent")
    if status != 200 or not j or not isinstance(j, list):
        return []
    return j


# ---------------------------------------------------------------------------
# 1. FORWARD-DISCOVERY - the survivorship-bias mitigant
# ---------------------------------------------------------------------------
def run_discovery(smoke: bool = False) -> int:
    """Poll GT new_pools + per-dex pools + Jupiter recent; append newly-seen
    Solana pairs to discovery_log.jsonl, deduped by pair address (falling
    back to mint for Jupiter's mint-only rows, which lack a pool address).
    Returns the number of NEW rows appended this run."""
    existing = _read_jsonl(DISCOVERY_LOG_PATH)
    seen_keys = {(r.get("pair_address") or r.get("mint")) for r in existing if r.get("pair_address") or r.get("mint")}
    LOG.info(f"discovery: {len(existing)} pairs already on file, {len(seen_keys)} unique keys")

    new_rows: List[dict] = []

    LOG.info("discovery: polling GT new_pools...")
    for d in gt_new_pools(page=1):
        row = _gt_pool_to_discovery_row(d, "gt_new_pools")
        if row and (row["pair_address"] not in seen_keys):
            new_rows.append(row)
            seen_keys.add(row["pair_address"])

    dex_ids = DEX_IDS[:1] if smoke else DEX_IDS
    for dex_id in dex_ids:
        LOG.info(f"discovery: polling GT dexes/{dex_id}/pools...")
        for d in gt_dex_pools(dex_id, page=1):
            row = _gt_pool_to_discovery_row(d, f"gt_dex_{dex_id}")
            if row and (row["pair_address"] not in seen_keys):
                new_rows.append(row)
                seen_keys.add(row["pair_address"])

    LOG.info("discovery: polling Jupiter tokens/v2/recent...")
    for t in jup_recent():
        row = _jupiter_recent_to_discovery_row(t)
        key = row["pair_address"] or row["mint"] if row else None
        if row and key and key not in seen_keys:
            new_rows.append(row)
            seen_keys.add(key)

    for row in new_rows:
        _append_jsonl(DISCOVERY_LOG_PATH, row)

    LOG.info(f"discovery: {len(new_rows)} NEW pairs appended this run "
             f"(total on file now: {len(existing) + len(new_rows)})")
    return len(new_rows)


# ---------------------------------------------------------------------------
# 2. UNIVERSE SCREEN
# ---------------------------------------------------------------------------
def _resolve_named_coin(symbol: str, pinned_mint: Optional[str]) -> dict:
    """Resolve a Tier A named coin to a real Solana pair. Pinned mints (e.g.
    POPCAT, confirmed in the recon report) skip search entirely. Otherwise:
    search DexScreener, keep Solana pairs with a matching symbol, rank by
    liquidity, cross-check the top candidate's mint against Jupiter metadata
    (name/socials) as a real-world sanity signal. Symbol collisions on
    Solana are common and confirmed live (KITTY: 8+ distinct Solana pairs
    share the symbol) - this is a heuristic, not a certainty; the result
    carries `resolution_method` + `alternate_candidates_considered` so a
    human can override."""
    if pinned_mint:
        pairs = ds_token_pairs(pinned_mint)
        top = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0.0) if pairs else None
        return {
            "symbol": symbol,
            "mint": pinned_mint,
            "pool_address": top.get("pairAddress") if top else None,
            "resolution_method": "pinned (confirmed in MICROCAP_DATA_RECON.md)",
            "liquidity_usd": (top.get("liquidity") or {}).get("usd") if top else None,
            "mcap_usd": top.get("marketCap") if top else None,
            "pair_created_at": _ms_to_iso(top.get("pairCreatedAt")) if top else None,
            "dex_id": top.get("dexId") if top else None,
            "alternate_candidates_considered": 0,
        }

    candidates = [p for p in ds_search(symbol)
                  if p.get("chainId") == "solana"
                  and (p.get("baseToken") or {}).get("symbol", "").upper() == symbol.upper()]
    if not candidates:
        LOG.warning(f"resolve: no Solana DexScreener match for named coin {symbol!r}")
        return {"symbol": symbol, "mint": None, "pool_address": None,
                "resolution_method": "UNRESOLVED - no DexScreener match", "alternate_candidates_considered": 0}

    candidates.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0.0, reverse=True)
    top = candidates[0]
    mint = (top.get("baseToken") or {}).get("address")

    # Cross-check against Jupiter metadata (name/socials) - a real signal,
    # not a rubber stamp. Freshly-launched or thin coins may have no
    # metadata at all; that's logged, not silently upgraded to "verified".
    cross_check = "no Jupiter metadata found"
    jup_hits = jup_search(mint) if mint else []
    if jup_hits:
        jt = jup_hits[0]
        has_socials = bool(jt.get("twitter") or jt.get("website"))
        cross_check = (f"Jupiter name={jt.get('name')!r} holderCount={jt.get('holderCount')} "
                       f"socials={'yes' if has_socials else 'no'}")

    return {
        "symbol": symbol,
        "mint": mint,
        "pool_address": top.get("pairAddress"),
        "resolution_method": f"heuristic: highest-liquidity Solana DexScreener match "
                              f"among {len(candidates)} symbol candidates; cross-check: {cross_check}. "
                              f"MANUAL VERIFICATION RECOMMENDED - symbol collisions on Solana are real "
                              f"(see MICROCAP_DATA_RECON.md).",
        "liquidity_usd": (top.get("liquidity") or {}).get("usd"),
        "mcap_usd": top.get("marketCap"),
        "pair_created_at": _ms_to_iso(top.get("pairCreatedAt")),
        "dex_id": top.get("dexId"),
        "alternate_candidates_considered": len(candidates) - 1,
    }


def _passes_screen(mint: str, symbol: Optional[str], pool_created_at_iso: Optional[str],
                    min_liq: float, max_liq: float, min_age_hours: float,
                    max_age_days: Optional[float]) -> Tuple[bool, dict, str]:
    """Live-check one Tier B discovery-log candidate against the screen
    thresholds via a single DexScreener call. Returns (passes, snapshot,
    reason)."""
    if symbol and symbol.upper() in STABLE_WRAPPED_BLACKLIST:
        return False, {}, "excluded: stable/wrapped symbol"
    pairs = ds_token_pairs(mint)
    if not pairs:
        return False, {}, "excluded: no live DexScreener pair found (likely dead/delisted/unindexed)"
    top = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0.0)
    liq = (top.get("liquidity") or {}).get("usd") or 0.0
    created_ms = top.get("pairCreatedAt")
    age_hours = None
    if created_ms:
        age_hours = (time.time() * 1000 - created_ms) / 3_600_000.0
    if liq < min_liq:
        return False, top, f"excluded: liquidity ${liq:,.0f} < min ${min_liq:,.0f}"
    if liq > max_liq:
        return False, top, f"excluded: liquidity ${liq:,.0f} > max ${max_liq:,.0f}"
    if age_hours is not None and age_hours < min_age_hours:
        return False, top, f"excluded: age {age_hours:.1f}h < min {min_age_hours}h"
    if max_age_days is not None and age_hours is not None and age_hours > max_age_days * 24:
        return False, top, f"excluded: age {age_hours/24:.1f}d > max {max_age_days}d"
    return True, top, "included"


def build_universe(min_liq: float, max_liq: float, min_age_hours: float,
                    max_age_days: Optional[float], smoke: bool = False) -> dict:
    """Tier A (named coins - ALWAYS included, screen does not apply) +
    Tier B (systematic universe - screened EXCLUSIVELY from
    discovery_log.jsonl candidates, never a fresh retrospective search;
    this is the structural survivorship fix, see module docstring)."""
    LOG.info("universe: resolving Tier A named coins...")
    tier_a = []
    for symbol, pinned in NAMED_COINS.items():
        entry = _resolve_named_coin(symbol, pinned)
        tier_a.append(entry)
        LOG.info(f"universe: Tier A {symbol} -> mint={entry.get('mint')} "
                 f"pool={entry.get('pool_address')} liq=${entry.get('liquidity_usd')}")

    # Merge-safety: this function fully rewrites universe.json, but must not
    # clobber a tier_b_established section built separately by
    # --screen-established (possibly by a concurrently-running --daemon
    # cycle using this same rebuild path) - carry it forward if present.
    preserved_established = {}
    if os.path.exists(UNIVERSE_PATH):
        try:
            with open(UNIVERSE_PATH, "r", encoding="utf-8") as f:
                prior = json.load(f)
            for k in ("tier_b_established", "tier_b_established_excluded_sample",
                      "screen_established_params", "tier_b_established_generated_at"):
                if k in prior:
                    preserved_established[k] = prior[k]
        except (OSError, json.JSONDecodeError):
            LOG.warning("universe: couldn't read prior universe.json to preserve tier_b_established "
                        "(missing/corrupt) - proceeding without it")

    discovery_rows = _read_jsonl(DISCOVERY_LOG_PATH)
    LOG.info(f"universe: screening Tier B from {len(discovery_rows)} discovery-log candidates "
             f"(NOT a fresh search - see survivorship note in module docstring)")
    seen_mints = set()
    tier_b = []
    excluded_sample = []
    candidates = discovery_rows[:20] if smoke else discovery_rows
    for row in candidates:
        mint = row.get("mint")
        if not mint or mint in seen_mints:
            continue
        seen_mints.add(mint)
        passes, snap, reason = _passes_screen(mint, row.get("symbol"), row.get("pool_created_at"),
                                               min_liq, max_liq, min_age_hours, max_age_days)
        if passes:
            tier_b.append({
                "symbol": (snap.get("baseToken") or {}).get("symbol") or row.get("symbol"),
                "mint": mint,
                "pool_address": snap.get("pairAddress") or row.get("pair_address"),
                "dex_id": snap.get("dexId") or row.get("dex_id"),
                "liquidity_usd": (snap.get("liquidity") or {}).get("usd"),
                "volume_24h_usd": (snap.get("volume") or {}).get("h24"),
                "pair_created_at": _ms_to_iso(snap.get("pairCreatedAt")) or row.get("pool_created_at"),
                "discovered_at": row.get("first_seen_ts"),
                "discovery_source": row.get("source"),
            })
        elif len(excluded_sample) < 25:
            excluded_sample.append({"symbol": row.get("symbol"), "mint": mint, "reason": reason})

    universe = {
        "generated_at": _iso_now(),
        "screen_params": {
            "chain": "solana",
            "min_liquidity_usd": min_liq,
            "max_liquidity_usd": max_liq,
            "min_age_hours": min_age_hours,
            "max_age_days": max_age_days,
            "excludes_stables_wrapped": sorted(STABLE_WRAPPED_BLACKLIST),
            "tier_b_candidate_pool": "discovery_log.jsonl ONLY (forward-discovered pairs) - "
                                     "never a fresh retrospective search, see INTEGRITY_NOTES.md",
        },
        "tier_a_named": tier_a,
        "tier_b_systematic": tier_b,
        "tier_b_excluded_sample": excluded_sample,
        "counts": {
            "tier_a": len(tier_a),
            "tier_b_passed": len(tier_b),
            "discovery_log_candidates_considered": len(candidates),
        },
        "note": ("Tier B is empty (or small) when discovery_log.jsonl is new/small - this is "
                 "EXPECTED and CORRECT, not a bug: the systematic universe only grows as forward "
                 "discovery runs accumulate history. Do not backfill Tier B via a retrospective "
                 "search; that would reintroduce survivorship bias. Run --discover regularly.")
                if len(discovery_rows) < 10 else None,
    }
    universe.update(preserved_established)
    if "tier_b_established" in preserved_established:
        universe["counts"]["tier_b_established"] = len(preserved_established["tier_b_established"])
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(UNIVERSE_PATH, "w", encoding="utf-8") as f:
        json.dump(universe, f, indent=2)
    LOG.info(f"universe: wrote {UNIVERSE_PATH} - Tier A={len(tier_a)} Tier B={len(tier_b)} "
             f"Tier B established={len(preserved_established.get('tier_b_established', []))} (preserved) "
             f"(from {len(candidates)} discovery candidates considered)")
    return universe


def load_universe() -> dict:
    if os.path.exists(UNIVERSE_PATH):
        with open(UNIVERSE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    LOG.info("universe: no universe.json on file yet - bootstrapping Tier A only "
             "(run --universe for a full Tier B screen once discovery_log.jsonl has data)")
    return build_universe(DEFAULT_MIN_LIQUIDITY_USD, DEFAULT_MAX_LIQUIDITY_USD, DEFAULT_MIN_AGE_HOURS, None)


def _universe_coins(universe: dict) -> List[dict]:
    """Flatten Tier A + Tier B systematic + Tier B established into one
    deduped (by mint) list of {symbol, mint, pool_address}."""
    coins = []
    seen_mints = set()
    for tier_key in ("tier_a_named", "tier_b_systematic", "tier_b_established"):
        for e in universe.get(tier_key, []) or []:
            mint = e.get("mint")
            if mint and mint not in seen_mints:
                seen_mints.add(mint)
                coins.append({"symbol": e.get("symbol"), "mint": mint, "pool_address": e.get("pool_address")})
    return coins


# ---------------------------------------------------------------------------
# 2b. TIER B ESTABLISHED SCREEN (--screen-established) - the "real arena" fix
# ---------------------------------------------------------------------------
# PROBLEM this solves: the forward-discovery log (--discover) only catches
# brand-new pump.fun-stage pools ($0 liquidity at first sight), which the
# Tier B systematic screen's own liquidity floor then excludes almost
# entirely (see universe.json's tier_b_excluded_sample - 20/20 samples were
# $0-$1 liquidity newborns). It structurally cannot produce the
# established-but-thin cat/meme coins ($KITTY, $POPCAT and peers,
# ~$50k-$5M liquidity) the owner actually trades. This screen builds that
# universe directly from CURRENT state (GT trending/top pools + DexScreener
# keyword search across the cat/meme naming space) - see the constants block
# above for why current-state search is methodologically correct here
# (unlike for brand-new launches).
def _ds_pair_to_established_candidate(p: dict, source: str) -> Optional[dict]:
    if p.get("chainId") != "solana":
        return None
    base = p.get("baseToken") or {}
    mint = base.get("address")
    symbol = base.get("symbol")
    if not mint or not symbol:
        return None
    return {
        "mint": mint,
        "symbol": symbol,
        "pool_address": p.get("pairAddress"),
        "dex_id": p.get("dexId"),
        "pool_created_at": _ms_to_iso(p.get("pairCreatedAt")),
        "source": source,
    }


def gather_established_candidates(smoke: bool = False) -> List[dict]:
    """Gather (mint, symbol, ...) candidate rows from GT trending/top pools +
    DexScreener keyword search, deduped by mint. This is a discovery pass
    ONLY - every candidate still goes through a live _passes_screen()
    liquidity/age re-check in build_established_universe() before it's
    trusted; nothing here is written to universe.json directly."""
    candidates: Dict[str, dict] = {}

    LOG.info("screen-established: polling GT trending_pools...")
    pages = 1 if smoke else 3
    for page in range(1, pages + 1):
        for d in gt_trending_pools(page=page):
            row = _gt_pool_to_discovery_row(d, "gt_trending_pools")
            if row and row.get("mint") and row["mint"] not in candidates:
                candidates[row["mint"]] = row

    dex_ids = ESTABLISHED_DEX_IDS[:1] if smoke else ESTABLISHED_DEX_IDS
    dex_pages = 1 if smoke else 2
    for dex_id in dex_ids:
        LOG.info(f"screen-established: polling GT dexes/{dex_id}/pools (top pools)...")
        for page in range(1, dex_pages + 1):
            for d in gt_dex_pools(dex_id, page=page):
                row = _gt_pool_to_discovery_row(d, f"gt_top_{dex_id}")
                if row and row.get("mint") and row["mint"] not in candidates:
                    candidates[row["mint"]] = row

    terms = ESTABLISHED_SEARCH_TERMS[:2] if smoke else ESTABLISHED_SEARCH_TERMS
    for term in terms:
        LOG.info(f"screen-established: DexScreener search {term!r}...")
        for p in ds_search(term):
            cand = _ds_pair_to_established_candidate(p, f"dexscreener_search_{term}")
            if cand and cand["mint"] not in candidates:
                candidates[cand["mint"]] = cand

    LOG.info(f"screen-established: {len(candidates)} unique mint candidates gathered from "
             f"GT trending/top pools ({','.join(ESTABLISHED_DEX_IDS)}) + DexScreener search ({','.join(terms)})")
    return list(candidates.values())


def build_established_universe(min_liq: float, max_liq: float, min_age_days: float,
                                exclude_mints: Optional[set] = None, smoke: bool = False,
                                max_coins: int = ESTABLISHED_MAX_COINS) -> Tuple[List[dict], List[dict]]:
    """Live-screen every gathered candidate via _passes_screen() (same
    liquidity/age/blacklist gate the systematic screen uses) and return
    (passed, excluded_sample). Passed entries are capped to max_coins by
    liquidity desc if the search surfaces more than the ~30-60 target."""
    exclude_mints = exclude_mints or set()
    candidates = gather_established_candidates(smoke=smoke)
    min_age_hours = min_age_days * 24.0
    passed: List[dict] = []
    excluded_sample: List[dict] = []
    for cand in candidates:
        mint = cand.get("mint")
        symbol = cand.get("symbol")
        if not mint or mint in exclude_mints:
            continue
        passes, snap, reason = _passes_screen(mint, symbol, cand.get("pool_created_at"),
                                               min_liq, max_liq, min_age_hours, None)
        if passes:
            created_ms = snap.get("pairCreatedAt")
            created_iso = _ms_to_iso(created_ms) or cand.get("pool_created_at")
            age_days = round((time.time() * 1000 - created_ms) / 86_400_000.0, 1) if created_ms else None
            passed.append({
                "symbol": (snap.get("baseToken") or {}).get("symbol") or symbol,
                "mint": mint,
                "pool_address": snap.get("pairAddress") or cand.get("pool_address"),
                "dex_id": snap.get("dexId") or cand.get("dex_id"),
                "liquidity_usd": (snap.get("liquidity") or {}).get("usd"),
                "mcap_usd": snap.get("marketCap"),
                "fdv_usd": snap.get("fdv"),
                "volume_24h_usd": (snap.get("volume") or {}).get("h24"),
                "pair_created_at": created_iso,
                "age_days": age_days,
                "discovery_source": cand.get("source"),
            })
        elif len(excluded_sample) < 40:
            excluded_sample.append({"symbol": symbol, "mint": mint, "reason": reason})

    passed.sort(key=lambda e: e.get("liquidity_usd") or 0.0, reverse=True)
    if len(passed) > max_coins:
        LOG.info(f"screen-established: {len(passed)} passed screen, capping to top {max_coins} by liquidity")
        passed = passed[:max_coins]
    LOG.info(f"screen-established: {len(passed)} coins passed (liquidity ${min_liq:,.0f}-${max_liq:,.0f}, "
             f"min age {min_age_days}d) out of {len(candidates)} unique candidates considered")
    return passed, excluded_sample


def run_screen_established(min_liq: float, max_liq: float, min_age_days: float, smoke: bool = False) -> dict:
    """(Re)build ONLY the tier_b_established section of universe.json,
    preserving tier_a_named/tier_b_systematic/everything else already on
    disk. build_universe() (the Tier B systematic rebuild) is itself
    merge-safe in the other direction - it preserves tier_b_established
    across its own rewrites - so the two screens can be run independently,
    including by a concurrently-running --daemon, without clobbering each
    other."""
    universe = load_universe()
    tier_a_mints = {e.get("mint") for e in universe.get("tier_a_named", []) if e.get("mint")}
    passed, excluded = build_established_universe(min_liq, max_liq, min_age_days,
                                                    exclude_mints=tier_a_mints, smoke=smoke)
    universe["tier_b_established"] = passed
    universe["tier_b_established_excluded_sample"] = excluded
    universe["screen_established_params"] = {
        "chain": "solana",
        "min_liquidity_usd": min_liq,
        "max_liquidity_usd": max_liq,
        "min_age_days": min_age_days,
        "excludes_stables_wrapped": sorted(STABLE_WRAPPED_BLACKLIST),
        "sources": ["gt_trending_pools", f"gt_dexes[{','.join(ESTABLISHED_DEX_IDS)}]/pools",
                    f"dexscreener_search[{','.join(ESTABLISHED_SEARCH_TERMS)}]"],
        "method": "CURRENT-STATE search+screen (not the forward-discovery-log Tier B systematic) "
                  "- correct here because target coins are ALREADY established/liquid, not "
                  "brand-new pump.fun-stage launches; see module docstring + constants block.",
    }
    universe.setdefault("counts", {})["tier_b_established"] = len(passed)
    universe["tier_b_established_generated_at"] = _iso_now()
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(UNIVERSE_PATH, "w", encoding="utf-8") as f:
        json.dump(universe, f, indent=2)
    LOG.info(f"screen-established: wrote {len(passed)} coins to tier_b_established in {UNIVERSE_PATH}")
    return universe


# ---------------------------------------------------------------------------
# 3. HISTORICAL OHLCV PULLER (GeckoTerminal) - idempotent, throttled
# ---------------------------------------------------------------------------
def _ohlcv_csv_path(symbol: str, mint: str, timeframe: str) -> str:
    # Key the filename by MINT, not just symbol. Solana symbol collisions are
    # rampant (the established screen surfaced 10 distinct "PEPE" mints and 3
    # "Bonk", plus many symbols shared across tiers) - a symbol-only filename
    # silently merges different coins' candles into one CSV, exactly the
    # "wrong mint = wrong data, silently" trap MICROCAP_DATA_RECON.md warns
    # about. Symbol is kept as a human-readable prefix; the mint fragment
    # guarantees per-coin uniqueness.
    safe = "".join(c for c in (symbol or "") if c.isalnum() or c in "-_") or "UNKNOWN"
    mint_frag = "".join(c for c in (mint or "") if c.isalnum())[:8] or "NOMINT"
    return os.path.join(OHLCV_DIR, f"{safe}_{mint_frag}_{timeframe}.csv")


def _read_existing_timestamps(path: str) -> set:
    if not os.path.exists(path):
        return set()
    ts = set()
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                ts.add(int(row["timestamp_unix"]))
            except (KeyError, ValueError):
                continue
    return ts


def _write_candles(path: str, candles: List[list]) -> int:
    """Append new candle rows (candles already filtered to new-only),
    sorted ascending by timestamp. Writes header if the file is new."""
    if not candles:
        return 0
    candles = sorted(candles, key=lambda c: c[0])
    is_new = not os.path.exists(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["timestamp_unix", "timestamp_iso", "open", "high", "low", "close", "volume_usd"])
        for c in candles:
            ts, o, h, l, cl, vol = c
            writer.writerow([ts, _ms_to_iso(ts * 1000), o, h, l, cl, vol])
    return len(candles)


def pull_ohlcv_for_coin(symbol: str, mint: str, pool_address: str, timeframe: str,
                         max_days: int = GT_HISTORY_CAP_DAYS, smoke: bool = False) -> int:
    """Idempotent OHLCV pull: if a CSV already exists, only fetch the latest
    page and append candles newer than what's on disk. If new, paginate
    backward (via before_timestamp) until GT's own 180-day cap (HTTP 401) or
    max_days, whichever binds first. Returns candles written."""
    path = _ohlcv_csv_path(symbol, mint, timeframe)
    existing_ts = _read_existing_timestamps(path)
    total_written = 0

    if existing_ts:
        # Incremental: pull the newest page, append only candles STRICTLY
        # newer than the current max on-file timestamp (not merely "not an
        # exact duplicate"). This guarantees the CSV stays globally ascending
        # by construction without a full re-sort/rewrite on every run - an
        # exact-duplicate-only filter is NOT sufficient: verified live during
        # build that a plain "not in existing_ts" check can append
        # chronologically OLDER candles after newer ones (e.g. a fetch whose
        # window reaches further back than what's already on file), breaking
        # monotonic order. Any genuinely older gap should be backfilled by
        # deleting the CSV and letting the fresh-file path below re-paginate
        # cleanly, not patched in via incremental top-up.
        max_existing_ts = max(existing_ts)
        status, candles = gt_ohlcv(pool_address, timeframe, limit=200 if smoke else GT_OHLCV_LIMIT)
        new_candles = [c for c in candles if int(c[0]) > max_existing_ts]
        total_written += _write_candles(path, new_candles)
        LOG.info(f"history: {symbol} {timeframe} incremental -> {len(new_candles)} new candles "
                 f"(status={status}, {len(existing_ts)} already on file)")
        return total_written

    # Fresh file: paginate backward to the history cap, accumulating ALL
    # pages in memory before writing once. Writing page-by-page would be
    # WRONG here: each page covers an OLDER window than the last (we walk
    # backward via before_timestamp), so per-page writes would leave the
    # CSV in descending chronological BLOCKS even though each block is
    # internally sorted - confirmed live as a real bug during verification,
    # not a hypothetical. Total volume here is small (<=20k rows for the
    # deepest hourly backfill), so holding it in memory for one coin is
    # negligible; it's discarded (gc.collect()) before the next coin.
    before_ts = None
    cutoff_ts = time.time() - max_days * 86400
    pages = 1 if smoke else 20  # 20 pages of 1000 hourly candles safely covers 180d even at aggregate=1
    limit = 100 if smoke else GT_OHLCV_LIMIT
    all_candles: Dict[int, list] = {}
    for page_num in range(pages):
        status, candles = gt_ohlcv(pool_address, timeframe, before_timestamp=before_ts, limit=limit)
        if status == 401:
            LOG.info(f"history: {symbol} {timeframe} hit GT's 180-day free-tier cap (HTTP 401) - "
                     f"this is expected for coins older than 180d, see INTEGRITY_NOTES.md")
            break
        if not candles:
            LOG.info(f"history: {symbol} {timeframe} no more candles returned (page {page_num + 1})")
            break
        for c in candles:
            all_candles[int(c[0])] = c
        oldest_ts = min(int(c[0]) for c in candles)
        if oldest_ts <= cutoff_ts or smoke:
            break
        before_ts = oldest_ts  # paginate further back
    new_candles = [c for ts, c in all_candles.items() if ts not in existing_ts]
    total_written += _write_candles(path, new_candles)
    LOG.info(f"history: {symbol} {timeframe} backfill -> {total_written} candles written to {path}")
    return total_written


def run_history(universe: dict, smoke: bool = False, max_days: int = GT_HISTORY_CAP_DAYS) -> int:
    coins = _universe_coins(universe)
    if smoke:
        coins = coins[:3]
    timeframes = ["day"] if smoke else ["day", "hour"]
    total = 0
    for coin in coins:
        if not coin.get("pool_address"):
            LOG.warning(f"history: skipping {coin['symbol']} - no pool_address resolved")
            continue
        for tf in timeframes:
            total += pull_ohlcv_for_coin(coin["symbol"], coin.get("mint"), coin["pool_address"], tf,
                                         max_days=max_days, smoke=smoke)
        gc.collect()  # RAM-lean: drop per-coin candle lists between coins
    LOG.info(f"history: run complete, {total} total candles written across {len(coins)} coin(s)")
    return total


# ---------------------------------------------------------------------------
# 4 & 5. WASH-TRADING SIGNAL (Jupiter) + LIQUIDITY-AT-TIME SNAPSHOTS (DexScreener)
# ---------------------------------------------------------------------------
def _organic_ratio(buy_v: Optional[float], buy_org: Optional[float]) -> Optional[float]:
    if not buy_v:
        return None
    return round((buy_org or 0.0) / buy_v, 4)


def snapshot_wash_signal(symbol: str, mint: str) -> Optional[dict]:
    hits = jup_search(mint)
    if not hits:
        LOG.warning(f"wash: no Jupiter data for {symbol} ({mint})")
        return None
    t = hits[0]
    # organicScore (0-100) + label is Jupiter's ACTUAL manipulation/health
    # composite and the RIGHT wash discriminator. The per-window buy_organic_
    # ratio below is a much narrower "strictly-organic buy VOLUME" fraction that
    # runs ~0.10 even for genuinely-healthy coins (POPCAT scores organicScore
    # 74/"medium" yet buy_organic_ratio 0.10) - it is NOT a wash signal on its
    # own and must not be flagged on. Verified 2026-08-06: across the 15-coin
    # testable set, organicScore cleanly separated 5 dead/manipulated coins
    # (score 0/"low": Ban, WOULD, fih, FCOD, GUN) from 10 genuinely-traded ones,
    # while buy_organic_ratio was uncorrelated with real health.
    row = {"ts_utc": _iso_now(), "symbol": symbol, "mint": mint, "source": "jupiter_v2",
           "holder_count": t.get("holderCount"),
           "organic_score": t.get("organicScore"),
           "organic_score_label": t.get("organicScoreLabel")}
    for window in ("5m", "1h", "6h", "24h"):
        stats = t.get(f"stats{window}") or {}
        buy_v = stats.get("buyVolume")
        buy_org = stats.get("buyOrganicVolume")
        sell_v = stats.get("sellVolume")
        sell_org = stats.get("sellOrganicVolume")
        row[f"buy_volume_{window}"] = buy_v
        row[f"buy_organic_volume_{window}"] = buy_org
        row[f"buy_organic_ratio_{window}"] = _organic_ratio(buy_v, buy_org)
        row[f"sell_volume_{window}"] = sell_v
        row[f"sell_organic_volume_{window}"] = sell_org
        row[f"sell_organic_ratio_{window}"] = _organic_ratio(sell_v, sell_org)
        row[f"num_traders_{window}"] = stats.get("numTraders")
    _append_jsonl(WASH_LOG_PATH, row)
    LOG.info(f"wash: {symbol} organic_score={row.get('organic_score')} "
             f"({row.get('organic_score_label')}) - THE health signal; "
             f"buy_organic_ratio_24h={row.get('buy_organic_ratio_24h')} is NOT (see snapshot_wash_signal note)")
    return row


def snapshot_liquidity(symbol: str, mint: str, pool_address: Optional[str]) -> Optional[dict]:
    pairs = ds_token_pairs(mint)
    if not pairs:
        LOG.warning(f"liquidity: no DexScreener data for {symbol} ({mint})")
        return None
    top = None
    if pool_address:
        top = next((p for p in pairs if p.get("pairAddress", "").lower() == pool_address.lower()), None)
    if top is None:
        top = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0.0)
    row = {
        "ts_utc": _iso_now(), "symbol": symbol, "mint": mint,
        "pair_address": top.get("pairAddress"), "dex_id": top.get("dexId"),
        "price_usd": _safe_float(top.get("priceUsd")),
        "liquidity_usd": (top.get("liquidity") or {}).get("usd"),
        "volume_h24": (top.get("volume") or {}).get("h24"),
        "volume_h6": (top.get("volume") or {}).get("h6"),
        "volume_h1": (top.get("volume") or {}).get("h1"),
        "volume_m5": (top.get("volume") or {}).get("m5"),
        "txns_h24_buys": ((top.get("txns") or {}).get("h24") or {}).get("buys"),
        "txns_h24_sells": ((top.get("txns") or {}).get("h24") or {}).get("sells"),
        "fdv_usd": top.get("fdv"),
        "mcap_usd": top.get("marketCap"),
        "pair_created_at": _ms_to_iso(top.get("pairCreatedAt")),
        "source": "dexscreener",
    }
    _append_jsonl(LIQ_SNAPSHOT_PATH, row)
    LOG.info(f"liquidity: {symbol} liq=${row['liquidity_usd']} vol24h=${row['volume_h24']}")
    return row


def run_snapshot(universe: dict, smoke: bool = False) -> Tuple[int, int]:
    coins = _universe_coins(universe)
    if smoke:
        coins = coins[:3]
    liq_count = wash_count = 0
    for coin in coins:
        if snapshot_liquidity(coin["symbol"], coin["mint"], coin.get("pool_address")):
            liq_count += 1
        if snapshot_wash_signal(coin["symbol"], coin["mint"]):
            wash_count += 1
        gc.collect()
    LOG.info(f"snapshot: run complete, {liq_count} liquidity rows + {wash_count} wash rows "
             f"across {len(coins)} coin(s)")
    return liq_count, wash_count


# ---------------------------------------------------------------------------
# 5b. TESTABLE-UNIVERSE ROLLUP (--testable) - the analyzable set
# ---------------------------------------------------------------------------
# Purpose: universe.json is the CANDIDATE list (screened for liquidity/age at
# discovery/build time); it says nothing about whether a coin actually has
# usable data ON DISK right now. universe_testable.json is the narrower,
# verified-clean set a backtest/analysis script should actually load: mint-
# keyed OHLCV present with enough candles, a CURRENT (not stale) liquidity
# read above the screen floor, and an explicit wash-heaviness flag (per
# INTEGRITY_NOTES.md #3, this is a FLAG not an exclusion - POPCAT's own 24h
# organic-buy baseline is ~10%, well under a naive 20% cutoff, so excluding
# on this would drop the owner's own primary named coin).
DEFAULT_TESTABLE_MIN_DAY_CANDLES = 20
# Flag on Jupiter's organic_score (0-100 health composite), NOT the narrow
# buy_organic_ratio (which is ~0.10 even for healthy coins - see
# snapshot_wash_signal). Verified 2026-08-06: score 0/"low" cleanly isolated
# the 5 dead/manipulated coins; >=40 kept every genuinely-traded one.
DEFAULT_TESTABLE_MIN_ORGANIC_SCORE = 40.0
UNIVERSE_TESTABLE_PATH = os.path.join(OUT_DIR, "universe_testable.json")


def _latest_by_mint(rows: List[dict]) -> Dict[str, dict]:
    """Reduce a JSONL log's rows to the latest row per mint (by ts_utc,
    string-sortable ISO8601)."""
    latest: Dict[str, dict] = {}
    for row in rows:
        mint = row.get("mint")
        if not mint:
            continue
        prior = latest.get(mint)
        if prior is None or (row.get("ts_utc") or "") >= (prior.get("ts_utc") or ""):
            latest[mint] = row
    return latest


def build_testable_universe(min_day_candles: int = DEFAULT_TESTABLE_MIN_DAY_CANDLES,
                             min_liquidity_usd: float = DEFAULT_MIN_LIQUIDITY_USD,
                             min_organic_score: float = DEFAULT_TESTABLE_MIN_ORGANIC_SCORE) -> dict:
    """(Re)build universe_testable.json: universe.json's coins (deduped by
    mint, see _universe_coins()), narrowed to those with mint-keyed OHLCV
    already on disk (>= min_day_candles daily candles - no network calls,
    pure on-disk check) AND a current liquidity snapshot above the screen
    floor. wash_heavy is a FLAG (buy_organic_ratio_24h < wash_organic_
    threshold), never an exclusion - see module docstring."""
    universe = load_universe()
    coins = _universe_coins(universe)
    latest_liq = _latest_by_mint(_read_jsonl(LIQ_SNAPSHOT_PATH))
    latest_wash = _latest_by_mint(_read_jsonl(WASH_LOG_PATH))

    testable: List[dict] = []
    skipped: List[dict] = []
    for coin in coins:
        symbol, mint = coin["symbol"], coin["mint"]
        day_path = _ohlcv_csv_path(symbol, mint, "day")
        hour_path = _ohlcv_csv_path(symbol, mint, "hour")
        day_n = len(_read_existing_timestamps(day_path))
        hour_n = len(_read_existing_timestamps(hour_path))
        liq_row = latest_liq.get(mint)
        liq_usd = liq_row.get("liquidity_usd") if liq_row else None
        wash_row = latest_wash.get(mint)
        organic_24h = wash_row.get("buy_organic_ratio_24h") if wash_row else None
        organic_score = wash_row.get("organic_score") if wash_row else None
        organic_label = wash_row.get("organic_score_label") if wash_row else None

        reasons = []
        if day_n < min_day_candles:
            reasons.append(f"insufficient day candles on disk ({day_n} < {min_day_candles})")
        if liq_row is None:
            reasons.append("no liquidity_snapshots.jsonl row on file yet - run --snapshot")
        elif liq_usd is None or liq_usd < min_liquidity_usd:
            reasons.append(f"current liquidity ${liq_usd if liq_usd is not None else 0:,.0f} "
                            f"< screen floor ${min_liquidity_usd:,.0f}")
        if reasons:
            skipped.append({"symbol": symbol, "mint": mint, "reasons": reasons})
            continue

        testable.append({
            "symbol": symbol,
            "mint": mint,
            "pool_address": coin.get("pool_address"),
            "day_candles": day_n,
            "hour_candles": hour_n,
            "liquidity_usd": liq_usd,
            "liquidity_snapshot_ts_utc": liq_row.get("ts_utc"),
            "organic_score": organic_score,
            "organic_score_label": organic_label,
            "buy_organic_ratio_24h": organic_24h,
            # THE wash/health flag: low organic_score = manipulated/dead. The old
            # buy_organic_ratio flag mislabelled 14/15 healthy coins as wash.
            "wash_heavy": bool(organic_score is not None and organic_score < min_organic_score),
            "ohlcv_day_path": os.path.relpath(day_path, OUT_DIR).replace(os.sep, "/"),
            "ohlcv_hour_path": os.path.relpath(hour_path, OUT_DIR).replace(os.sep, "/"),
        })

    testable.sort(key=lambda c: c.get("liquidity_usd") or 0.0, reverse=True)
    result = {
        "generated_at": _iso_now(),
        "params": {
            "min_day_candles": min_day_candles,
            "min_liquidity_usd": min_liquidity_usd,
            "min_organic_score": min_organic_score,
            "wash_note": "wash_heavy is a FLAG, not an exclusion. Flags on Jupiter "
                         "organic_score (0-100 health composite) < min_organic_score. "
                         "The old buy_organic_ratio flag was an artifact (~0.10 even for "
                         "healthy coins) and mislabelled 14/15 real coins as wash - fixed 2026-08-06.",
        },
        "counts": {
            "universe_coins_considered": len(coins),
            "testable": len(testable),
            "skipped": len(skipped),
            "wash_heavy_flagged": sum(1 for c in testable if c["wash_heavy"]),
        },
        "coins": testable,
        "skipped_sample": skipped[:60],
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(UNIVERSE_TESTABLE_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    LOG.info(f"testable: wrote {UNIVERSE_TESTABLE_PATH} - {len(testable)} testable "
             f"({result['counts']['wash_heavy_flagged']} wash-heavy flagged) / "
             f"{len(skipped)} skipped out of {len(coins)} universe coins considered")
    return result


# ---------------------------------------------------------------------------
# 6. INTEGRITY-LIMITS doc - written/refreshed on every run (cheap, no network)
# ---------------------------------------------------------------------------
INTEGRITY_NOTES = """# Micro-Cap / Solana Cat-Coin Data - Integrity Notes

**Read this before treating anything derived from `data/microcap/` as a
tradeable backtest result.** It is not one. It is an honest forward-testing
foundation plus a slippage-naive historical upper bound. Every caveat below
is load-bearing, not boilerplate - see `tools/copilot/MICROCAP_DATA_RECON.md`
for the full live-tested evidence behind each claim.

## 1. Survivorship bias

- GeckoTerminal does **not** purge dead pools from its index once a pool
  address is known (confirmed live: a $0-liquidity, day-old bonding-curve
  pool still returned its full OHLCV history). So the bias is entirely in
  **discovery**, not retention.
- BUT: any universe assembled by *searching* for coins "that look
  interesting today" is survivor-poisoned. The ~98%+ of pump.fun launches
  that die on the bonding curve without graduating are invisible to a
  retrospective, name-based search done after the fact.
- **The fix, and why it matters**: `discovery_log.jsonl` is populated ONLY
  by forward polling (`--discover`), never backfilled by search. The Tier-B
  systematic universe in `universe.json` is screened EXCLUSIVELY from that
  log - never from a fresh search. This means: **the clock starts the day
  this collector is first run, not before.** Historical OHLCV pulled today
  for a coin discovered today is real and retroactively complete (GT indexes
  the full pool life once the address is known) - but the *set of coins*
  Tier B will ever contain is bounded by what forward discovery has actually
  seen. A Tier-B universe built in month 1 will be thin; it grows honestly
  over time. Do not "fix" a thin Tier B by backfilling via search - that
  reintroduces exactly the bias this design avoids.
- Tier A (named coins: POPCAT, KITTY) is hand-pinned/resolved regardless of
  discovery-log state and is not subject to this caveat - but see the
  symbol-collision caveat below.

## 2. Symbol collisions / named-coin resolution

- Searching Solana DexScreener for "KITTY" returns 8+ distinct pairs/mints
  sharing that symbol (confirmed live). Picking the wrong one silently
  corrupts every downstream number for that coin.
- This collector's resolution heuristic (highest DexScreener liquidity among
  symbol-matching Solana pairs, cross-checked against Jupiter metadata for
  a plausible name/socials match) is a **heuristic, not a certainty**.
  `universe.json`'s `tier_a_named` entries carry `resolution_method` and
  `alternate_candidates_considered` - inspect these, especially for any
  newly-added named coin, before trusting the resolved mint.

## 3. Wash trading / organic volume

- Jupiter's organic-vs-total volume split (`wash_signal.jsonl`) is a real,
  live, per-token measurement - not a guess.
- Calibration baseline, confirmed live: **POPCAT's own 24h organic-buy
  ratio was measured at 10.0%** - an established, liquid, multi-year-old
  meme coin. A naive ">50% organic required" filter would exclude nearly
  everything, including the coins the owner already trades.
- **Use this signal relatively** (rank peers, or watch for a *sudden drop*
  from a coin's own baseline as a manipulation alarm), not as an absolute
  pass/fail threshold, until a proper peer-relative calibration is built.

## 4. Slippage / thin-book fills

- None of GeckoTerminal/DexScreener/Jupiter's price data reflects what a
  real market order would actually fill at on a thin pool. A close-price
  OHLCV backtest on a $30k-liquidity pool assumes fills at a price a real
  order of meaningful size would move straight through.
- **Any backtest built on this OHLCV data is a SLIPPAGE-NAIVE UPPER BOUND,
  not an achievable P&L.** Treat a positive backtest result as "worth
  forward-testing with realistic size," never as "this edge is real."
- Cross-referencing `liquidity_snapshots.jsonl` (liquidity *at snapshot
  time*, not at every candle) is a partial mitigant, not a full fix -
  liquidity between snapshots is still unknown, and a real fill-cost check
  would require Jupiter's live `/quote` endpoint at the actual sizes being
  considered (not built here - this collector is data acquisition only).

## 4b. Tier B ESTABLISHED (current-state search) - a deliberate exception

- Tier B systematic (above) is drawn EXCLUSIVELY from the forward discovery
  log to avoid survivorship bias on brand-new launches - but in practice that
  log only ever catches pump.fun-stage pools at $0 liquidity (verified live:
  the log's own excluded_sample was 20/20 zero-liquidity newborns), which the
  liquidity floor then always excludes. It structurally cannot find the
  owner's actual arena: established-but-thin coins like $KITTY/$POPCAT.
- `tier_b_established` (built by `--screen-established`) fixes this by
  searching CURRENT state instead: GT trending_pools + top pools on
  raydium/pumpswap/moonshot + DexScreener keyword search across the
  cat/meme naming space, screened to $50k-$5M liquidity, Solana-only,
  pool age >= 14 days, no stables/wrapped/majors.
- This is methodologically different from Tier B systematic but NOT
  survivor-biased for its own question: a coin alive and liquid for >=14
  days is, by construction, still findable by a current search - it isn't a
  bonding-curve newborn that could have died and vanished before discovery.
  The survivorship concern in section 1 is specific to brand-new launches,
  not to weeks/months-old liquid coins.
- Coverage caveat, stated plainly: this screen only finds coins matching the
  search terms used (cat/kitty/inu/pepe/bonk/wif/dog/meow/paw/moon) plus
  whatever GT's trending/top-pools listings surface independently of name -
  it is not an exhaustive census of every established thin Solana meme coin,
  and a coin using none of those name patterns and not currently trending
  would be missed. Treat `tier_b_established` as a representative sample of
  the target population, not a complete enumeration.

## 5. 180-day history cap

- GeckoTerminal's free tier hard-caps OHLCV history at a rolling 180 days
  (confirmed live: HTTP 401 beyond that). Coins younger than 180 days get
  their **entire life's history** for free; coins older (POPCAT since Dec
  2023) get only the trailing 180-day window. Full multi-year history would
  require CoinGecko's paid Analyst plan.

## 6. Rate limits (respected, not aspirational)

- GeckoTerminal: 30 req/min documented, confirmed live (429 after a rapid
  burst) - this collector throttles to a 2.2s minimum gap (~27/min) with
  exponential backoff + `Retry-After` respect on any 429.
- DexScreener: ~60 req/min documented - throttled to a 1.1s minimum gap.
- Jupiter v2: no disclosed limit - throttled conservatively to 1.0s anyway.

## 7. What this data DOES support honestly

- **Forward testing**: from the moment this collector runs, every
  discovered pair, its liquidity-at-time, its organic-volume signal, and
  its OHLCV are captured going forward with no survivorship bias for the
  population actually observed.
- **A slippage-naive historical upper bound** for coins within the 180-day
  window, useful for hypothesis generation and ranking - not for sizing a
  real trade or claiming an edge.
- **What this data does NOT support**: a trustworthy backtest P&L claim,
  a claim about the total historical micro-cap population (only the
  observed/discovered subset), or a claim about achievable fill prices.

Generated/refreshed automatically by `tools/copilot/microcap_collector.py`
on every run - see that file's module docstring for implementation detail.
"""


def write_integrity_notes() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(INTEGRITY_NOTES_PATH, "w", encoding="utf-8") as f:
        f.write(INTEGRITY_NOTES)


# ---------------------------------------------------------------------------
# 7. EARLY-LIFE FORWARD TRACKING (--track-early-life) - the young-coin instrument
# ---------------------------------------------------------------------------
# WHY THIS EXISTS (the whole point):
#   The completed history harness proved there is NO mechanical edge in GT's
#   ~180-day retroactive window, and that the only place an edge could
#   plausibly live - a coin's first <90 days - is UNREACHABLE by history
#   because GT's rolling window predates every already-established coin (and
#   the survivorship note in section 1 blocks backfilling young coins by
#   search). The ONLY way to ever test the Lens-7 early-detection hypotheses
#   (MICROCAP_CAMPAIGN.md M25-M30) is to capture young coins' trajectories
#   going FORWARD, from discovery onward. That is this instrument.
#
# SURVIVORSHIP-FREE BY DESIGN:
#   - Keyed by MINT, never symbol (Solana has 10+ distinct "PEPE"s - a
#     symbol-keyed store silently merges different coins; uses the existing
#     _ohlcv_csv_path(symbol, mint, tf) mint-keyed path helper).
#   - EVERY discovered young coin is logged and tracked, including ones that
#     later die/rug. A coin that stops returning DexScreener data is MARKED
#     status="dead" with last_seen - NEVER silently dropped. The deaths are
#     the signal (~98%+ of pump.fun launches die - that base rate is exactly
#     what M3/M25 need to measure), so losing them would poison the very
#     thing this instrument exists to observe.
#
# ALIVE/DEAD DETECTION - why DexScreener, not GeckoTerminal:
#   GT does NOT purge dead pools (recon S4a / INTEGRITY_NOTES section 1): it
#   keeps returning OHLCV for a $0-liquidity corpse, so OHLCV presence is NOT
#   an aliveness signal. DexScreener, by contrast, delists dead pairs - its
#   absence IS the death signal. So: DexScreener presence => alive + gives
#   liquidity-at-time (the forward M5/M6 signal); GT OHLCV => the price path,
#   which GT RETAINS even after death, letting us capture the full crash/rug
#   trajectory. A coin is marked dead only after EARLY_LIFE_DEATH_THRESHOLD
#   consecutive polls with no live DexScreener pair (guards against a single
#   transient DS miss falsely killing a live coin).
#
# RATE DISCIPLINE:
#   Capped at track_n coins per cycle (default 8), round-robin via a persisted
#   cursor so no coin is starved and request volume is bounded regardless of
#   how large the watchlist grows. Dead coins are frozen (not re-polled), so
#   as coins die the surviving cohort gets denser coverage. Reuses the ONE
#   rate-limited _get_json() path (GT 2.2s gap, DexScreener 1.1s gap) - adds
#   no new uncapped request source. Per active coin per cycle: 1 DexScreener
#   call (alive-check + liquidity snapshot) + up to 2 GT calls (hour+day OHLCV
#   incremental) => 2*track_n GT calls/cycle worst case (~35s at N=8).
EARLY_LIFE_WATCHLIST_PATH = os.path.join(OUT_DIR, "early_life_watchlist.json")
DEFAULT_EARLY_LIFE_MAX_AGE_DAYS = 14.0     # age-at-discovery cutoff for "young"
DEFAULT_EARLY_LIFE_TRACK_N = 8             # coins tracked per cycle (round-robin), GT-budget-safe
EARLY_LIFE_DEATH_THRESHOLD = 3             # consecutive no-live-DexScreener-pair polls -> mark dead
# Discovery sources that are, by construction, brand-new-launch feeds. A coin
# from one of these with NO pool_created_at (Jupiter's recent feed is
# mint-level and carries none) is still young-by-source and included, with
# age_at_discovery_days=None recorded honestly rather than guessed.
EARLY_LIFE_NEW_LAUNCH_SOURCES = {"jupiter_recent", "gt_new_pools"}


def _load_early_life_watchlist() -> dict:
    if os.path.exists(EARLY_LIFE_WATCHLIST_PATH):
        try:
            with open(EARLY_LIFE_WATCHLIST_PATH, "r", encoding="utf-8") as f:
                wl = json.load(f)
            wl.setdefault("coins", {})
            wl.setdefault("cursor", 0)
            return wl
        except (OSError, json.JSONDecodeError):
            LOG.warning("early-life: watchlist file missing/corrupt - starting fresh")
    return {"generated_at": None, "params": {}, "cursor": 0, "counts": {}, "coins": {}}


def _save_early_life_watchlist(wl: dict) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(EARLY_LIFE_WATCHLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(wl, f, indent=2)


def _age_days_at_discovery(first_seen_ts: Optional[str], pool_created_at: Optional[str]) -> Optional[float]:
    """age = first_seen - pool_created (days). None if either timestamp is
    missing/unparseable (Jupiter's recent feed carries no pool_created_at)."""
    def _parse(ts: Optional[str]):
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None
    fs, pc = _parse(first_seen_ts), _parse(pool_created_at)
    if fs is None or pc is None:
        return None
    return round((fs - pc).total_seconds() / 86400.0, 5)


def build_early_life_watchlist(max_age_days: float = DEFAULT_EARLY_LIFE_MAX_AGE_DAYS) -> dict:
    """Select YOUNG discovered coins from discovery_log.jsonl and persist a
    mint-keyed watchlist. Young = age-at-discovery < max_age_days when a
    pool_created_at exists, OR (age unknown AND discovered via a brand-new-
    launch feed, per EARLY_LIFE_NEW_LAUNCH_SOURCES). Stables/wrapped excluded.

    MERGE-SAFE and SURVIVORSHIP-SAFE: coins already on the watchlist keep all
    their accumulated tracking state (status, cursor position independent),
    and are NEVER removed - not even dead ones. This function only ADDS newly-
    qualifying coins and refreshes the static discovery metadata; it never
    prunes. Deduped by mint, keeping the earliest first_seen and enriching
    pool_address/pool_created_at from whichever discovery row carries them
    (Jupiter rows lack a pool address; a later GT row for the same mint may
    supply one)."""
    rows = _read_jsonl(DISCOVERY_LOG_PATH)
    # Dedupe by mint: earliest first_seen, enrich pair_address/pool_created_at.
    merged: Dict[str, dict] = {}
    for r in rows:
        mint = r.get("mint")
        if not mint:
            continue
        cur = merged.get(mint)
        if cur is None:
            merged[mint] = dict(r)
            continue
        if (r.get("first_seen_ts") or "") < (cur.get("first_seen_ts") or ""):
            cur["first_seen_ts"] = r.get("first_seen_ts")
            cur["source"] = r.get("source")
        for k in ("pair_address", "pool_created_at", "dex_id", "symbol", "name"):
            if not cur.get(k) and r.get(k):
                cur[k] = r.get(k)

    wl = _load_early_life_watchlist()
    coins = wl["coins"]
    selected = skipped_old = skipped_stable = newly_added = 0
    for mint, r in merged.items():
        symbol = r.get("symbol") or ""
        if symbol.upper() in STABLE_WRAPPED_BLACKLIST:
            skipped_stable += 1
            continue
        age = _age_days_at_discovery(r.get("first_seen_ts"), r.get("pool_created_at"))
        young_by_age = age is not None and age < max_age_days
        young_by_source = age is None and (r.get("source") in EARLY_LIFE_NEW_LAUNCH_SOURCES)
        if not (young_by_age or young_by_source):
            skipped_old += 1
            continue
        selected += 1
        if mint in coins:
            # Preserve tracking state; only refresh static discovery metadata
            # (and backfill a pool_address if a later discovery row found one).
            e = coins[mint]
            if not e.get("pair_address") and r.get("pair_address"):
                e["pair_address"] = r.get("pair_address")
                e["dex_id"] = e.get("dex_id") or r.get("dex_id")
            if e.get("age_at_discovery_days") is None and age is not None:
                e["age_at_discovery_days"] = age
            continue
        newly_added += 1
        coins[mint] = {
            "mint": mint,
            "symbol": symbol or None,
            "name": r.get("name"),
            "pair_address": r.get("pair_address"),
            "dex_id": r.get("dex_id"),
            "pool_created_at": r.get("pool_created_at"),
            "age_at_discovery_days": age,
            "young_reason": "age<%.0fd" % max_age_days if young_by_age else "young-by-source(%s)" % r.get("source"),
            "first_seen_ts": r.get("first_seen_ts"),
            "discovery_source": r.get("source"),
            "added_to_watchlist_ts": _iso_now(),
            # Tracking state (accrues forward):
            "status": "active" if r.get("pair_address") else "pending_resolve",
            "track_count": 0,
            "consecutive_empty_polls": 0,
            "first_tracked_ts": None,
            "last_tracked_ts": None,
            "last_data_ts": None,
            "last_seen_ts": None,
            "death_detected_ts": None,
            "last_liquidity_usd": None,
            "day_candles_on_disk": 0,
            "hour_candles_on_disk": 0,
        }

    status_counts: Dict[str, int] = {}
    for e in coins.values():
        status_counts[e.get("status", "unknown")] = status_counts.get(e.get("status", "unknown"), 0) + 1
    wl["generated_at"] = _iso_now()
    wl["params"] = {
        "max_age_days_at_discovery": max_age_days,
        "track_n_per_cycle": DEFAULT_EARLY_LIFE_TRACK_N,
        "death_threshold_polls": EARLY_LIFE_DEATH_THRESHOLD,
        "new_launch_sources": sorted(EARLY_LIFE_NEW_LAUNCH_SOURCES),
        "note": "Survivorship-free forward instrument. Coins are keyed by MINT and NEVER "
                "removed once added (dead coins stay, status=dead - the deaths are the signal). "
                "Young = age-at-discovery < max_age_days_at_discovery, or young-by-source when "
                "no pool_created_at exists (Jupiter recent feed). See section 7 of "
                "microcap_collector.py and MICROCAP_CAMPAIGN.md Lens 7.",
    }
    wl["counts"] = {
        "watchlist_total": len(coins),
        "discovery_unique_mints_considered": len(merged),
        "selected_young_this_build": selected,
        "newly_added_this_build": newly_added,
        "skipped_too_old": skipped_old,
        "skipped_stable_wrapped": skipped_stable,
        "by_status": status_counts,
    }
    _save_early_life_watchlist(wl)
    LOG.info(f"early-life: watchlist built - {len(coins)} young coins total "
             f"(+{newly_added} new this build), by_status={status_counts}, "
             f"threshold age<{max_age_days}d (of {len(merged)} unique discovery mints)")
    return wl


def _track_one_early_life_coin(e: dict, smoke: bool) -> str:
    """Track a single watchlist coin forward: DexScreener alive-check +
    liquidity snapshot, then GT OHLCV (hour+day, mint-keyed) accumulation.
    Mutates `e` in place. Returns an outcome tag for the run summary:
    'data' | 'resolved' | 'no_data' | 'dead'."""
    symbol = e.get("symbol") or "UNKNOWN"
    mint = e.get("mint")
    now = _iso_now()
    e["track_count"] = int(e.get("track_count") or 0) + 1
    if not e.get("first_tracked_ts"):
        e["first_tracked_ts"] = now
    e["last_tracked_ts"] = now

    # 1. DexScreener: aliveness + liquidity-at-time (writes liquidity_snapshots.jsonl).
    #    Its ABSENCE (returns None) is the death signal - GT would keep serving
    #    a dead pool's OHLCV forever, so it cannot detect death (see section 7).
    liq_row = snapshot_liquidity(symbol, mint, e.get("pair_address"))
    if liq_row:
        e["consecutive_empty_polls"] = 0
        e["last_seen_ts"] = now
        e["last_data_ts"] = now
        e["last_liquidity_usd"] = liq_row.get("liquidity_usd")
        # Resolve/refresh a pool_address from the live pair if we didn't have one.
        resolved = False
        if not e.get("pair_address") and liq_row.get("pair_address"):
            e["pair_address"] = liq_row.get("pair_address")
            e["dex_id"] = e.get("dex_id") or liq_row.get("dex_id")
            resolved = True
        if e.get("status") in (None, "pending_resolve", "dead"):
            e["status"] = "active"
        outcome = "resolved" if resolved else "data"
    else:
        e["consecutive_empty_polls"] = int(e.get("consecutive_empty_polls") or 0) + 1
        if e["consecutive_empty_polls"] >= EARLY_LIFE_DEATH_THRESHOLD:
            if e.get("status") != "dead":
                e["status"] = "dead"
                e["death_detected_ts"] = now
                LOG.info(f"early-life: {symbol} ({mint}) MARKED DEAD after "
                         f"{e['consecutive_empty_polls']} polls with no live DexScreener pair "
                         f"(last_seen={e.get('last_seen_ts')}) - the death IS the signal, kept on file")
            outcome = "dead"
        else:
            outcome = "no_data"

    # 2. GT OHLCV path (mint-keyed CSVs) - pulled whenever we have a pool
    #    address, EVEN if DexScreener just went dark, because GT retains dead
    #    pools and this captures the full post-death crash trajectory.
    pool = e.get("pair_address")
    if pool:
        for tf in (["day"] if smoke else ["day", "hour"]):
            try:
                pull_ohlcv_for_coin(symbol, mint, pool, tf, smoke=smoke)
            except Exception as ex:  # fail-soft: one bad pull must not kill the cycle
                LOG.warning(f"early-life: OHLCV pull failed for {symbol} {tf} "
                            f"({type(ex).__name__}: {ex})")
        e["day_candles_on_disk"] = len(_read_existing_timestamps(_ohlcv_csv_path(symbol, mint, "day")))
        e["hour_candles_on_disk"] = len(_read_existing_timestamps(_ohlcv_csv_path(symbol, mint, "hour")))
        gc.collect()  # RAM-lean: drop per-coin candle lists between coins

    # 3. FLOW/HOLDER DERIVATIVES for this young coin - the highest-value
    #    early-detection target (section 8). Only when ALIVE (a fresh liq row
    #    exists this poll): a Jupiter wash snapshot accrues forward holder/
    #    organic history for the coin (so holder_growth can populate over time -
    #    young coins are usually NOT in the universe snapshot, so this is the
    #    only place their holder history is captured), then a flow row is
    #    derived + appended. Both calls funnel through the ONE rate-limited
    #    _get_json() path (Jupiter 1.0s gap, its own host limiter). Fail-soft:
    #    a flow error must never kill the tracking cycle.
    if liq_row:
        try:
            snapshot_wash_signal(symbol, mint)   # accrue holder/organic history
            flow_row = _write_flow_row_for_mint(symbol, mint)
            if flow_row:
                e["last_flow_ts"] = flow_row.get("ts_utc")
                e["last_holder_count"] = flow_row.get("holder_count")
        except Exception as ex:
            LOG.warning(f"early-life: flow enrichment failed for {symbol} ({mint}) "
                        f"({type(ex).__name__}: {ex})")
    return outcome


def run_early_life_tracking(track_n: int = DEFAULT_EARLY_LIFE_TRACK_N,
                             max_age_days: float = DEFAULT_EARLY_LIFE_MAX_AGE_DAYS,
                             smoke: bool = False) -> dict:
    """Additive daemon step + `--track-early-life` one-shot. Refreshes the
    young-coin watchlist from discovery_log.jsonl, then tracks up to track_n
    NON-dead coins forward this cycle, round-robin via a persisted cursor so
    nothing is starved and request volume stays bounded. OFF-BY-DEFAULT-SAFE:
    if the watchlist has no trackable coins it no-ops cleanly and returns a
    zeroed summary (never errors)."""
    wl = build_early_life_watchlist(max_age_days=max_age_days)
    coins = wl["coins"]
    # Round-robin over trackable (non-dead) coins only; dead coins are frozen
    # (kept on file, never re-polled) so budget concentrates on survivors.
    trackable_mints = [m for m, e in coins.items() if e.get("status") != "dead"]
    trackable_mints.sort()  # stable, deterministic order for a reproducible cursor
    n_trackable = len(trackable_mints)
    summary = {"tracked": 0, "with_data": 0, "resolved": 0, "no_data": 0, "dead_marked": 0,
               "watchlist_total": len(coins), "trackable": n_trackable, "smoke": smoke}
    if n_trackable == 0:
        LOG.info("early-life: no trackable coins on watchlist - no-op (this is safe, not an error)")
        wl["last_tracking_summary"] = summary
        _save_early_life_watchlist(wl)
        return summary

    cursor = int(wl.get("cursor") or 0) % n_trackable
    n = min(track_n, n_trackable)
    picked = [trackable_mints[(cursor + i) % n_trackable] for i in range(n)]
    LOG.info(f"early-life: tracking {n} of {n_trackable} trackable coins this cycle "
             f"(cursor={cursor}, round-robin), watchlist total={len(coins)}")
    for mint in picked:
        outcome = _track_one_early_life_coin(coins[mint], smoke=smoke)
        summary["tracked"] += 1
        if outcome == "data":
            summary["with_data"] += 1
        elif outcome == "resolved":
            summary["resolved"] += 1
            summary["with_data"] += 1
        elif outcome == "no_data":
            summary["no_data"] += 1
        elif outcome == "dead":
            summary["dead_marked"] += 1

    wl["cursor"] = (cursor + n) % n_trackable
    wl["last_tracking_ts"] = _iso_now()
    wl["last_tracking_summary"] = summary
    # Refresh by_status after this cycle's mutations.
    status_counts: Dict[str, int] = {}
    for e in coins.values():
        status_counts[e.get("status", "unknown")] = status_counts.get(e.get("status", "unknown"), 0) + 1
    wl.setdefault("counts", {})["by_status"] = status_counts
    _save_early_life_watchlist(wl)
    LOG.info(f"early-life: cycle done - tracked={summary['tracked']} "
             f"with_data={summary['with_data']} resolved={summary['resolved']} "
             f"no_data={summary['no_data']} dead_marked={summary['dead_marked']} "
             f"| next_cursor={wl['cursor']} by_status={status_counts}")
    return summary


# ---------------------------------------------------------------------------
# 8. FORWARD FLOW / HOLDER DERIVATIVES (--flow-signal) - the RIGHT features
# ---------------------------------------------------------------------------
# WHY THIS EXISTS (the whole point):
#   The completed full-moat harness proved micro-cap OHLCV *price history* has
#   NO edge - the inefficiency in thin Solana meme coins lives in FLOW,
#   HOLDERS and ATTENTION, not candles. The raw forward snapshots already
#   capture the LEVELS (wash_signal.jsonl: holder_count, organic_score,
#   per-window organic buy/sell volume; liquidity_snapshots.jsonl:
#   liquidity_usd, price, volume, txns). The early-detection signal, though,
#   is in the DERIVATIVES - rates of change: is the holder base accelerating,
#   is organic buying flooding in, is liquidity being added or pulled, is
#   flow accelerating vs its own daily baseline. This step computes those
#   derivatives per-mint by comparing the CURRENT snapshot to PRIOR snapshot
#   rows for that same mint, and writes them to flow_signal.jsonl (the file
#   the co-pilot call command consumes).
#
# ENTRY-TIME-SAFE BY CONSTRUCTION:
#   - Every delta is computed ONLY against PRIOR rows (strictly older than the
#     current snapshot's timestamp) - never a future row. No leakage.
#   - Per horizon (1h/6h/24h) the prior is matched by NEAREST timestamp within
#     a tolerance band [0.6*H, 1.5*H] of age: the prior must be at least 60% of
#     the horizon old (so a "1h" delta is never computed off a 5-minute-old
#     row and mislabelled) and at most 150% old (not absurdly stale). If no
#     prior row falls in the band, the delta is NULL - never 0, never
#     fabricated. This is why 6h/24h deltas stay null until the collector has
#     accumulated that much forward history for a mint; that is correct, not a
#     bug (see PROVE-IT note / deliverable).
#   - MINT-KEYED always (Solana symbols collide: 10+ distinct "PEPE" mints in
#     this very universe), so deltas can never cross-contaminate coins.
#
# organic_buyer_influx_24h: Jupiter's raw numOrganicBuyers is not persisted in
#   wash_signal.jsonl (only organic buy VOLUME + numTraders are), so this uses
#   the fractional change in buy_organic_volume_24h over the ~24h window as the
#   documented proxy for organic-buyer influx. Null when there is no ~24h prior
#   or the level is missing - never fabricated.
_FLOW_HORIZONS_S = {"1h": 3600.0, "6h": 21600.0, "24h": 86400.0}
_FLOW_TOL_LO = 0.6   # prior must be >= 60% of the horizon old
_FLOW_TOL_HI = 1.5   # prior must be <= 150% of the horizon old


def _parse_iso_dt(ts: Optional[str]):
    """Parse an ISO8601 ts_utc string to an aware datetime, or None."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None


def _dated_rows(rows: List[dict]) -> List[Tuple[Any, dict]]:
    """Attach a parsed datetime to each row that has a valid ts_utc and return
    them sorted ascending by time (oldest first). Rows without a parseable
    ts_utc are dropped (they can't be time-matched)."""
    dated = []
    for r in rows:
        dt = _parse_iso_dt(r.get("ts_utc"))
        if dt is not None:
            dated.append((dt, r))
    dated.sort(key=lambda x: x[0])
    return dated


def _group_dated_by_mint(path: str) -> Dict[str, List[Tuple[Any, dict]]]:
    """Read a mint-keyed JSONL log once and return {mint: [(dt, row), ...]}
    sorted ascending per mint. Used by run_flow_signal to avoid re-reading the
    whole file per coin."""
    groups: Dict[str, List[dict]] = {}
    for r in _read_jsonl(path):
        m = r.get("mint")
        if m:
            groups.setdefault(m, []).append(r)
    return {m: _dated_rows(rs) for m, rs in groups.items()}


def _nearest_prior(dated: List[Tuple[Any, dict]], ref_dt, horizon_s: float) -> Optional[dict]:
    """Return the PRIOR row (strictly older than ref_dt) whose age is nearest
    to horizon_s and falls within the tolerance band [0.6*H, 1.5*H]. None if no
    row qualifies - entry-time-safe (only rows with age > 0 are considered)."""
    if ref_dt is None:
        return None
    lo, hi = _FLOW_TOL_LO * horizon_s, _FLOW_TOL_HI * horizon_s
    best_row = None
    best_diff = None
    for dt, row in dated:
        age = (ref_dt - dt).total_seconds()
        if age <= 0:          # not a prior row -> never used (no leakage)
            continue
        if age < lo or age > hi:
            continue
        diff = abs(age - horizon_s)
        if best_diff is None or diff < best_diff:
            best_diff, best_row = diff, row
    return best_row


def _frac_change(now_val, prior_val) -> Optional[float]:
    """(now - prior)/prior as a fraction. None (not 0) if either value is
    missing or the prior is zero - a fabricated delta is worse than no delta."""
    if now_val is None or prior_val is None:
        return None
    try:
        now_f, prior_f = float(now_val), float(prior_val)
    except (TypeError, ValueError):
        return None
    if prior_f == 0.0:
        return None
    return round((now_f - prior_f) / prior_f, 6)


def compute_flow_row(symbol: str, mint: str,
                     wash_dated: List[Tuple[Any, dict]],
                     liq_dated: List[Tuple[Any, dict]]) -> Optional[dict]:
    """Compute one entry-time-safe flow_signal row for a mint from its wash +
    liquidity snapshot history (both lists sorted ascending, oldest first).
    The CURRENT snapshot is the newest row in each list; deltas compare it to
    the nearest qualifying PRIOR row per horizon. Returns None only when there
    is no current data at all (neither a wash nor a liquidity row).

    CONTRACT - flow_signal.jsonl field names (consumed by the call command):
      ts_utc, symbol, mint, holder_count, organic_score, liquidity_usd,
      price_usd, holder_growth_1h, holder_growth_6h, holder_growth_24h,
      organic_buyer_influx_24h, liq_change_1h, liq_change_6h, liq_change_24h,
      txns_buy_sell_ratio_24h, vol_accel_1h_vs_24h.
    """
    cur_wash = wash_dated[-1][1] if wash_dated else {}
    ref_wash_dt = wash_dated[-1][0] if wash_dated else None
    cur_liq = liq_dated[-1][1] if liq_dated else {}
    ref_liq_dt = liq_dated[-1][0] if liq_dated else None
    if not cur_wash and not cur_liq:
        return None

    # --- current LEVELS (copy-through) ---
    holder_count = cur_wash.get("holder_count")
    organic_score = cur_wash.get("organic_score")
    liquidity_usd = cur_liq.get("liquidity_usd")
    price_usd = cur_liq.get("price_usd")

    row: Dict[str, Any] = {
        "ts_utc": _iso_now(),
        "symbol": symbol,
        "mint": mint,
        "holder_count": holder_count,
        "organic_score": organic_score,
        "liquidity_usd": liquidity_usd,
        "price_usd": price_usd,
    }

    # --- holder growth (fraction) per horizon, from wash history ---
    for label, hz in _FLOW_HORIZONS_S.items():
        prior = _nearest_prior(wash_dated[:-1], ref_wash_dt, hz) if len(wash_dated) > 1 else None
        row[f"holder_growth_{label}"] = _frac_change(holder_count, prior.get("holder_count")) if prior else None

    # --- organic-buyer influx over ~24h (proxy: buy_organic_volume_24h frac change) ---
    prior24_wash = _nearest_prior(wash_dated[:-1], ref_wash_dt, _FLOW_HORIZONS_S["24h"]) if len(wash_dated) > 1 else None
    now_org = cur_wash.get("buy_organic_volume_24h")
    row["organic_buyer_influx_24h"] = (
        _frac_change(now_org, prior24_wash.get("buy_organic_volume_24h")) if prior24_wash else None
    )

    # --- liquidity change (LP add/remove proxy) per horizon, from liq history ---
    for label, hz in _FLOW_HORIZONS_S.items():
        prior = _nearest_prior(liq_dated[:-1], ref_liq_dt, hz) if len(liq_dated) > 1 else None
        row[f"liq_change_{label}"] = _frac_change(liquidity_usd, prior.get("liquidity_usd")) if prior else None

    # --- current-snapshot flow composites (no prior needed) ---
    buys = cur_liq.get("txns_h24_buys")
    sells = cur_liq.get("txns_h24_sells")
    if buys is None and sells is None:
        row["txns_buy_sell_ratio_24h"] = None
    else:
        total = (buys or 0) + (sells or 0)
        row["txns_buy_sell_ratio_24h"] = round((buys or 0) / total, 6) if total > 0 else None

    v1 = cur_liq.get("volume_h1")
    v24 = cur_liq.get("volume_h24")
    if v1 is None or v24 in (None, 0):
        row["vol_accel_1h_vs_24h"] = None
    else:
        try:
            row["vol_accel_1h_vs_24h"] = round(float(v1) * 24.0 / float(v24), 6) if float(v24) != 0 else None
        except (TypeError, ValueError):
            row["vol_accel_1h_vs_24h"] = None

    return row


def latest_flow_features(mint: str) -> Optional[dict]:
    """Return the most recent flow_signal.jsonl row for a mint as a dict, or
    None if the mint has no flow row on file yet. Module-level helper the
    co-pilot call command can import; the command may also read the file
    directly, but this is the supported accessor."""
    latest = None
    latest_ts = ""
    for r in _read_jsonl(FLOW_SIGNAL_PATH):
        if r.get("mint") != mint:
            continue
        ts = r.get("ts_utc") or ""
        if latest is None or ts >= latest_ts:
            latest, latest_ts = r, ts
    return latest


def _write_flow_row_for_mint(symbol: str, mint: str) -> Optional[dict]:
    """Convenience path for the early-life tracker: read this ONE mint's wash +
    liquidity history from disk, compute a flow row, append it. Kept separate
    from run_flow_signal's batch path (which groups the whole file once) so a
    single tracked young coin can be enriched without a full universe pass."""
    wash_dated = _dated_rows([r for r in _read_jsonl(WASH_LOG_PATH) if r.get("mint") == mint])
    liq_dated = _dated_rows([r for r in _read_jsonl(LIQ_SNAPSHOT_PATH) if r.get("mint") == mint])
    row = compute_flow_row(symbol, mint, wash_dated, liq_dated)
    if row:
        _append_jsonl(FLOW_SIGNAL_PATH, row)
    return row


def run_flow_signal(universe: dict) -> int:
    """Compute + append one flow_signal.jsonl row per universe coin, deriving
    entry-time-safe deltas from that mint's prior wash + liquidity snapshots.
    Reads each source log ONCE (grouped by mint) for efficiency. Returns the
    number of flow rows written. Fail-soft per coin - one bad mint never kills
    the pass. Run AFTER the snapshot step so the newest snapshot it derives
    from is fresh."""
    coins = _universe_coins(universe)
    wash_groups = _group_dated_by_mint(WASH_LOG_PATH)
    liq_groups = _group_dated_by_mint(LIQ_SNAPSHOT_PATH)
    written = with_delta = 0
    for coin in coins:
        mint, symbol = coin.get("mint"), coin.get("symbol")
        if not mint:
            continue
        try:
            row = compute_flow_row(symbol, mint,
                                   wash_groups.get(mint, []), liq_groups.get(mint, []))
        except Exception as ex:  # fail-soft: one coin must not kill the pass
            LOG.warning(f"flow: compute failed for {symbol} ({mint}) "
                        f"({type(ex).__name__}: {ex})")
            continue
        if row is None:
            continue
        _append_jsonl(FLOW_SIGNAL_PATH, row)
        written += 1
        if any(row.get(k) is not None for k in
               ("holder_growth_1h", "holder_growth_6h", "holder_growth_24h",
                "liq_change_1h", "liq_change_6h", "liq_change_24h")):
            with_delta += 1
    LOG.info(f"flow: wrote {written} flow_signal rows ({with_delta} with >=1 non-null delta) "
             f"across {len(coins)} universe coin(s)")
    return written


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def _run_pipeline(args: argparse.Namespace) -> None:
    write_integrity_notes()
    # NOTE: "screen_established" is deliberately NOT part of the no-flags
    # default (discover/universe/history/snapshot) - it's a separate, heavier
    # one-off/manual op (current-state search across GT + many DexScreener
    # terms) that must be requested explicitly, same as the existing
    # discover/universe/history/snapshot flags.
    steps = [s for s in ("discover", "universe", "screen_established", "history", "snapshot",
                          "flow_signal", "testable", "track_early_life")
              if getattr(args, s)]
    if not steps:
        steps = ["discover", "universe", "history", "snapshot"]

    if "discover" in steps:
        run_discovery(smoke=args.smoke)
    universe = None
    if "universe" in steps:
        universe = build_universe(args.min_liquidity_usd, args.max_liquidity_usd,
                                   args.min_age_hours, args.max_age_days, smoke=args.smoke)
    if "screen_established" in steps:
        universe = run_screen_established(args.established_min_liquidity_usd, args.established_max_liquidity_usd,
                                           args.established_min_age_days, smoke=args.smoke)
    if "history" in steps or "snapshot" in steps or "flow_signal" in steps:
        if universe is None:
            universe = load_universe()
    if "history" in steps:
        run_history(universe, smoke=args.smoke)
    if "snapshot" in steps:
        run_snapshot(universe, smoke=args.smoke)
    if "flow_signal" in steps:
        # AFTER snapshot so the newest raw snapshot it derives deltas from is fresh.
        run_flow_signal(universe)
    if "testable" in steps:
        build_testable_universe(args.testable_min_day_candles, args.min_liquidity_usd,
                                 args.testable_min_organic_score)
    if "track_early_life" in steps:
        run_early_life_tracking(track_n=args.early_life_track_n,
                                 max_age_days=args.early_life_max_age_days, smoke=args.smoke)


def _run_daemon(args: argparse.Namespace) -> None:
    write_integrity_notes()
    cycle = 0
    LOG.info(f"=== microcap_collector daemon starting === interval={args.interval_min}min "
             f"history_every={args.history_every_n_cycles} cycles")
    try:
        while True:
            cycle += 1
            LOG.info(f"--- daemon cycle {cycle} ---")
            run_discovery(smoke=False)
            universe = build_universe(args.min_liquidity_usd, args.max_liquidity_usd,
                                       args.min_age_hours, args.max_age_days, smoke=False)
            run_snapshot(universe, smoke=False)
            # Forward flow/holder derivatives (section 8) - computed AFTER the
            # snapshot so the newest raw snapshot it derives deltas from is
            # fresh. Fail-soft: a flow error must never take down the daemon's
            # discovery/snapshot core.
            try:
                run_flow_signal(universe)
            except Exception as ex:
                LOG.warning(f"flow: signal step errored (non-fatal, continuing daemon) "
                            f"({type(ex).__name__}: {ex})")
            # Additive forward instrument: track a rate-capped, round-robin
            # slice of the young-coin watchlist each cycle (section 7). Fail-
            # soft - a tracking error must never take down the discovery/
            # snapshot core of the daemon.
            try:
                run_early_life_tracking(track_n=args.early_life_track_n,
                                         max_age_days=args.early_life_max_age_days, smoke=False)
            except Exception as ex:
                LOG.warning(f"early-life: tracking step errored (non-fatal, continuing daemon) "
                            f"({type(ex).__name__}: {ex})")
            if cycle % args.history_every_n_cycles == 0:
                run_history(universe, smoke=False)
            gc.collect()
            LOG.info(f"--- daemon cycle {cycle} complete, sleeping {args.interval_min}min ---")
            time.sleep(args.interval_min * 60)
    except KeyboardInterrupt:
        LOG.info("daemon: KeyboardInterrupt - shutting down cleanly")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--discover", action="store_true", help="Run forward-discovery poll")
    ap.add_argument("--universe", action="store_true", help="(Re)build universe.json")
    ap.add_argument("--screen-established", action="store_true", dest="screen_established",
                     help="Build tier_b_established: the CURRENT liquid-but-thin cat/meme universe "
                          "(GT trending/top pools + DexScreener keyword search) - the owner's actual "
                          "arena, separate from the forward-discovery-log Tier B systematic screen")
    ap.add_argument("--history", action="store_true", help="Pull/refresh OHLCV for universe coins")
    ap.add_argument("--snapshot", action="store_true", help="Liquidity + wash snapshot for universe coins")
    ap.add_argument("--flow-signal", action="store_true", dest="flow_signal",
                     help="Compute + append forward FLOW/HOLDER derivatives (holder_growth_1h/6h/24h, "
                          "organic_buyer_influx_24h, liq_change_1h/6h/24h, txns_buy_sell_ratio_24h, "
                          "vol_accel_1h_vs_24h) per universe coin to flow_signal.jsonl - entry-time-safe "
                          "deltas from each mint's PRIOR wash+liquidity snapshots (null when no prior in "
                          "window; never fabricated). Run AFTER --snapshot so the current snapshot is fresh "
                          "(section 8).")
    ap.add_argument("--testable", action="store_true", help="(Re)build universe_testable.json - the narrower, "
                                                              "on-disk-verified-clean analyzable set (see "
                                                              "build_testable_universe() docstring)")
    ap.add_argument("--track-early-life", action="store_true", dest="track_early_life",
                     help="Track YOUNG discovered coins (age-at-discovery < --early-life-max-age-days) forward: "
                          "refresh the mint-keyed early_life_watchlist.json from discovery_log.jsonl, then pull/"
                          "refresh mint-keyed OHLCV (hour+day) for a rate-capped round-robin slice. Dead coins are "
                          "MARKED (status=dead), never dropped - survivorship-free by design (section 7).")
    ap.add_argument("--early-life-track-n", type=int, default=DEFAULT_EARLY_LIFE_TRACK_N, dest="early_life_track_n",
                     help=f"--track-early-life: max young coins to track per cycle, round-robin "
                          f"(default {DEFAULT_EARLY_LIFE_TRACK_N}; bounds GT request volume regardless of watchlist size)")
    ap.add_argument("--early-life-max-age-days", type=float, default=DEFAULT_EARLY_LIFE_MAX_AGE_DAYS,
                     dest="early_life_max_age_days",
                     help=f"--track-early-life: age-at-discovery cutoff in days for the young-coin watchlist "
                          f"(default {DEFAULT_EARLY_LIFE_MAX_AGE_DAYS})")
    ap.add_argument("--once", action="store_true", help="Run selected step(s) once then exit (default: all four)")
    ap.add_argument("--daemon", action="store_true", help="Loop forever (discover+snapshot every --interval-min, "
                                                            "history every --history-every-n-cycles cycles)")
    ap.add_argument("--smoke", action="store_true", help="Small live test of every stage (few pages/coins/candles)")
    ap.add_argument("--interval-min", type=float, default=20.0, help="Daemon cycle interval in minutes (default 20)")
    ap.add_argument("--history-every-n-cycles", type=int, default=6, help="Daemon: refresh OHLCV every N cycles")
    ap.add_argument("--min-liquidity-usd", type=float, default=DEFAULT_MIN_LIQUIDITY_USD)
    ap.add_argument("--max-liquidity-usd", type=float, default=DEFAULT_MAX_LIQUIDITY_USD)
    ap.add_argument("--min-age-hours", type=float, default=DEFAULT_MIN_AGE_HOURS)
    ap.add_argument("--max-age-days", type=float, default=None, help="Optional Tier-B max age cap (unset = no cap)")
    ap.add_argument("--established-min-liquidity-usd", type=float, default=DEFAULT_ESTABLISHED_MIN_LIQUIDITY_USD,
                     help="Tier B established: min liquidity USD (default 50000)")
    ap.add_argument("--established-max-liquidity-usd", type=float, default=DEFAULT_ESTABLISHED_MAX_LIQUIDITY_USD,
                     help="Tier B established: max liquidity USD (default 5000000)")
    ap.add_argument("--established-min-age-days", type=float, default=DEFAULT_ESTABLISHED_MIN_AGE_DAYS,
                     help="Tier B established: min pool age in days (default 14)")
    ap.add_argument("--testable-min-day-candles", type=int, default=DEFAULT_TESTABLE_MIN_DAY_CANDLES,
                     help="--testable: minimum on-disk day candles required (default 20)")
    ap.add_argument("--testable-min-organic-score", type=float, default=DEFAULT_TESTABLE_MIN_ORGANIC_SCORE,
                     help="--testable: flag (not exclude) coins below this Jupiter organic_score 0-100 (default 40)")
    args = ap.parse_args()

    LOG.info(f"=== WAGMI microcap_collector starting === out_dir={OUT_DIR} "
             f"args={vars(args)}")

    if args.smoke:
        args.min_liquidity_usd = min(args.min_liquidity_usd, 1000.0)  # loosen for a small live test
        _run_pipeline(args)
    elif args.daemon:
        _run_daemon(args)
    else:
        _run_pipeline(args)

    LOG.info("=== microcap_collector run complete ===")


if __name__ == "__main__":
    main()
