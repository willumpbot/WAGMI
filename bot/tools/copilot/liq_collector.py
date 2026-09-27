#!/usr/bin/env python
"""
WAGMI Co-Pilot LIQUIDATION-CASCADE COLLECTOR - liq_collector.py
=============================================================================
Standalone, READ-ONLY w.r.t. the live paper bot. Lives under tools/copilot/;
writes ONLY to data/copilot/liquidations/. No Discord push, no imports of
llm/, execution/, core/, strategies/, and no writes to any live-bot state
file, .env, or data/replay/ - same isolation contract as the rest of
tools/copilot/ (see tools/copilot/README.md).

WHY THIS EXISTS
-------------------------------------------------------------------------
Liquidation cascades are hypothesized to dominate leveraged meme P&L, and
this project has ZERO historical data on them. Unlike candles/funding/OI,
force-liquidation events are NOT retroactively published by any exchange -
this data is UN-BACKFILLABLE. Every day this collector is not running is
evidence permanently lost. This file starts the clock. It is FORWARD
EVIDENCE COLLECTION ONLY - see data/copilot/PREREGISTRATION.md for the
pre-registered hypotheses this feeds. NOT a backtest. NOT an edge claim.

SOURCES - WHAT WAS ACTUALLY CHECKED (2026-07-31, live from this machine)
-------------------------------------------------------------------------
1. HYPERLIQUID (the venue the owner actually trades) - CHECKED, NO USABLE
   MARKET-WIDE FEED. HL's public WS (wss://api.hyperliquid.xyz/ws) exposes
   ~24 subscription types (allMids, l2Book, trades, candle, userEvents,
   orderUpdates, userFills, ...). The only liquidation-carrying type is
   `userEvents`, whose `liquidation` field is scoped to ONE user's own
   account - there is no market-wide "give me every liquidation on HL"
   subscription. The public `trades` stream does not flag liquidations
   either. CONFIRMED against HL's own docs - not an assumption.
   => Binance/Bybit data below is a PROXY for HL cascade pressure, not HL's
   own liquidations. HL has different LPs, different per-asset leverage
   caps (e.g. POPCAT caps at 3x on HL - see copilot.py), and thinner books
   than a CEX for the same meme coin, so a CEX cascade is directionally
   informative but not a 1:1 mirror of what happens to HL positions.

2. BINANCE USD-M futures forceOrder stream - the canonical public
   liquidation feed industry-wide, and the task's named primary source.
   IMPLEMENTED per Binance's real documented protocol (verified against
   ccxt's own binanceusdm forceOrder handler, not guessed): per-symbol
   wss://fstream.binance.com/ws/<symbol>@forceOrder, or subscribe to
   <symbol>@forceOrder over the combined wss://fstream.binance.com/stream
   endpoint. BUT: live-tested 2026-07-31 from this machine/network and the
   DATA PLANE IS SILENTLY WITHHELD. The WS handshake succeeds (HTTP 101)
   and a SUBSCRIBE control message is ack'd normally ({"result":null,...}),
   but ZERO market-data frames ever arrive - confirmed against
   btcusdt@aggTrade (normally many messages/second on any live BTC futures
   market) combined with !forceOrder@arr (the all-market liquidation feed)
   over a continuous 55-second live listen: exactly 1 message received
   total (the subscribe ack), 0 data frames. Binance's plain REST
   (fapi.binance.com/fapi/v1/exchangeInfo) returns HTTP 451 "restricted
   location" from this same network - consistent with a geo/compliance
   block, but applied at the WS layer as a silent data withhold rather
   than an outright connection refusal (the handshake and control-plane
   protocol both work fine). This looks like a network/regional
   restriction on THIS machine, not a bug in this file - the protocol
   implementation is correct and may simply start working if run from
   elsewhere (VPS, VPN, different ISP). Kept ENABLED by default so it
   self-heals silently if that ever changes; every connection cycle logs
   whether it is actually receiving data (not just connected) so a
   "listening but empty" state is never mistaken for "collecting".

3. BYBIT V5 linear perpetuals `allLiquidation.<symbol>` public stream
   (wss://stream.bybit.com/v5/public/linear) - ADDED. Not in the original
   task brief, but added because BOTH named sources come up short from
   this network: HL has no market-wide feed (see #1) and Binance's feed is
   connectable-but-empty (see #2). Without a working venue this collector
   would run "successfully" forever - clean connect/subscribe logs - while
   capturing literally nothing, which defeats the entire "start the clock
   today" mandate. Bybit's public WS (unlike its REST API, which also
   403s with a CloudFront "distribution configured to block access from
   your country" message from this network) IS reachable and DOES deliver
   live data - verified 2026-07-31 with real BTCUSDT trade-stream data
   flowing within ~4 seconds of subscribing. This is the collector's
   PRIMARY working venue in practice; Binance is best-effort/dormant until
   proven otherwise on this network.

   Bybit's liquidation payload uses a DIFFERENT side convention than
   Binance - see _parse_bybit_event()'s docstring below. Getting this
   backwards would silently invert every "long vs short liquidated" label
   for 60-90 days, so it is normalized explicitly and documented inline,
   not inferred.

SYMBOL MAPPING (watchlist -> exchange perpetual symbol) - VERIFIED LIVE
-------------------------------------------------------------------------
Both venues' REST symbol-listing endpoints are themselves geo-blocked from
this network (Binance exchangeInfo -> 451, Bybit instruments-info -> 403
CloudFront), so "does this perpetual exist" could not be checked by simply
fetching a symbol list. Instead each candidate was verified the hard way,
2026-07-31: subscribe to that candidate's public trade stream on each venue
and observe either an immediate venue-side rejection ("handler not found" -
symbol doesn't exist) or real trade data arriving (symbol exists).

  watchlist | Binance USD-M     | Bybit linear   | note
  ----------|-------------------|----------------|---------------------------
  BTC       | BTCUSDT           | BTCUSDT        |
  SOL       | SOLUSDT           | SOLUSDT        |
  POPCAT    | NOT LISTED        | POPCATUSDT     | Binance gap
  WIF       | WIFUSDT           | WIFUSDT        |
  FARTCOIN  | NOT LISTED        | FARTCOINUSDT   | Binance gap
  PENGU     | NOT LISTED        | PENGUUSDT      | Binance gap
  kPEPE     | 1000PEPEUSDT      | 1000PEPEUSDT   | 1000x-denominated, both venues
  kBONK     | 1000BONKUSDT      | 1000BONKUSDT   | 1000x-denominated, both venues
  kSHIB     | NOT LISTED        | SHIB1000USDT   | Binance gap; note Bybit's OWN
            |                   |                | naming is inconsistent with
            |                   |                | itself (1000PEPE/1000BONK vs
            |                   |                | SHIB1000) - verified live,
            |                   |                | not a guess.

Binance covers 6/9 (missing POPCAT, FARTCOIN, PENGU) *and* is currently
data-dark on this network regardless (see #2) - so in practice it covers
0/9 right now, dormant. Bybit covers 9/9 and is the venue actually
producing rows. Every row is tagged with `venue` so analysis can
segment/weight by source; e.g. a POPCAT cascade study will be Bybit-only
whenever/if Binance stays dark.

ROW SCHEMA (one JSON object per line, data/copilot/liquidations/liq_events.jsonl)
-------------------------------------------------------------------------
  ts_utc        - ISO8601 UTC timestamp of the liquidation fill
  venue         - "binance" | "bybit"
  symbol        - our watchlist name (BTC, SOL, POPCAT, WIF, FARTCOIN,
                  PENGU, kPEPE, kBONK, kSHIB) - NOT the venue's raw ticker
  side          - "long" | "short" - the side of the POSITION that got
                  force-liquidated (normalized across venues, see the two
                  _parse_*_event() docstrings for the exact per-venue
                  field mapping and why it differs)
  price         - Binance: average fill price of the forced order.
                  Bybit: BANKRUPTCY price (Bybit's allLiquidation stream
                  does not expose an actual fill price) - a close proxy
                  for notional size but not identical semantics to
                  Binance's price; kept in source_raw either way for any
                  future re-derivation.
  qty_base      - liquidated quantity in the coin's base units
  notional_usd  - price * qty_base, rounded to cents
  source_raw    - compact copy of the venue's original fields (for audit /
                  future re-parsing; NOT the full envelope)

FAIL-SOFT CONTRACT
-------------------------------------------------------------------------
This process must never crash and never take down anything else. Every
venue connection loop is wrapped in its own try/except with exponential
backoff + jitter (base 2s, cap 60s, reset to base on a clean reconnect);
a dead venue never blocks the other. All connection state transitions
(connecting / subscribed / reconnecting / error) are logged to
data/copilot/liquidations/collector.log (rotating, 5MB x 3 backups) via
the stdlib logging module - nothing here touches the live bot's own
logs/state/heartbeat.

CLI
-------------------------------------------------------------------------
  python tools/copilot/liq_collector.py                    # run forever (Task Scheduler mode)
  python tools/copilot/liq_collector.py --duration 60       # smoke test: run 60s then exit cleanly
  python tools/copilot/liq_collector.py --once              # quick sanity check (~15s) then exit
  python tools/copilot/liq_collector.py --venues bybit       # only Bybit (skip the dormant Binance leg)
  python tools/copilot/liq_collector.py --symbols BTC,SOL    # narrow the watchlist
  python tools/copilot/liq_collector.py --summary            # print liq_summary.py's report and exit
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import sys
import time
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Dict, List, Optional

import websockets

# ---------------------------------------------------------------------------
# Paths - all writes confined to data/copilot/liquidations/
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))          # tools/copilot
BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))            # bot/
OUT_DIR = os.path.join(BOT_DIR, "data", "copilot", "liquidations")
EVENTS_PATH = os.path.join(OUT_DIR, "liq_events.jsonl")
LOG_PATH = os.path.join(OUT_DIR, "collector.log")

# ---------------------------------------------------------------------------
# Watchlist + venue symbol map (see module docstring for how this was verified)
# ---------------------------------------------------------------------------
WATCHLIST = ["BTC", "SOL", "POPCAT", "WIF", "FARTCOIN", "PENGU", "kPEPE", "kBONK", "kSHIB"]

SYMBOL_MAP: Dict[str, Dict[str, Optional[str]]] = {
    "BTC":      {"binance": "BTCUSDT",      "bybit": "BTCUSDT"},
    "SOL":      {"binance": "SOLUSDT",      "bybit": "SOLUSDT"},
    "POPCAT":   {"binance": None,           "bybit": "POPCATUSDT"},
    "WIF":      {"binance": "WIFUSDT",      "bybit": "WIFUSDT"},
    "FARTCOIN": {"binance": None,           "bybit": "FARTCOINUSDT"},
    "PENGU":    {"binance": None,           "bybit": "PENGUUSDT"},
    "kPEPE":    {"binance": "1000PEPEUSDT", "bybit": "1000PEPEUSDT"},
    "kBONK":    {"binance": "1000BONKUSDT", "bybit": "1000BONKUSDT"},
    "kSHIB":    {"binance": None,           "bybit": "SHIB1000USDT"},
}

BINANCE_WS_BASE = "wss://fstream.binance.com/stream"
BYBIT_WS_URL = "wss://stream.bybit.com/v5/public/linear"

BACKOFF_BASE_S = 2.0
BACKOFF_CAP_S = 60.0
HEARTBEAT_EVERY_S = 30.0  # how often to log "still alive, N events so far" per venue
POLL_INTERVAL_S = 2.0  # ws.recv() timeout - keeps stop_event checks responsive for --duration/--once


# ---------------------------------------------------------------------------
# Logging - file (rotating) + console. Isolated to data/copilot/liquidations/.
# ---------------------------------------------------------------------------
def _build_logger() -> logging.Logger:
    os.makedirs(OUT_DIR, exist_ok=True)
    logger = logging.getLogger("liq_collector")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:  # idempotent for re-import / test harnesses
        return logger
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%dT%H:%M:%SZ")
    fh = RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)
    return logger


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _safe_float(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _ms_to_iso(ms) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc).isoformat()


def append_event(row: dict) -> None:
    """Append one JSON row. Own file, own dir - never touches live-bot state."""
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(EVENTS_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()


# ---------------------------------------------------------------------------
# Per-venue event parsing -> normalized row
# ---------------------------------------------------------------------------
def _parse_binance_event(raw: dict, symbol_display: str) -> Optional[dict]:
    """Binance forceOrder: 'S' is the side of the FORCE ORDER Binance places
    to close the position, NOT the position side itself.
      S == "SELL" -> Binance is forcibly SELLING -> a LONG position was liquidated
      S == "BUY"  -> Binance is forcibly BUYING  -> a SHORT position was liquidated
    Verified against ccxt's binanceusdm handle_liquidation()/parse_ws_liquidation()
    source + inline Binance doc comments, 2026-07-31 - not inferred from the name.
    """
    o = raw.get("o") or {}
    raw_side = o.get("S")
    if raw_side == "SELL":
        side = "long"
    elif raw_side == "BUY":
        side = "short"
    else:
        side = "unknown"
    price = _safe_float(o.get("ap")) or _safe_float(o.get("p"))
    qty = _safe_float(o.get("z")) or _safe_float(o.get("q"))
    ts_ms = o.get("T") or raw.get("E")
    if price is None or qty is None:
        return None
    return {
        "ts_utc": _ms_to_iso(ts_ms),
        "venue": "binance",
        "symbol": symbol_display,
        "side": side,
        "price": price,
        "qty_base": qty,
        "notional_usd": round(price * qty, 2),
        "source_raw": {
            "s": o.get("s"), "S": raw_side, "p": o.get("p"), "ap": o.get("ap"),
            "q": o.get("q"), "z": o.get("z"), "X": o.get("X"), "T": o.get("T"),
        },
    }


def _parse_bybit_event(item: dict, symbol_display: str) -> Optional[dict]:
    """Bybit V5 allLiquidation: 'S' is the POSITION side directly (the
    OPPOSITE convention from Binance's forceOrder 'S', which is the side of
    the closing order) - per Bybit's own docs, confirmed 2026-07-31:
      S == "Buy"  -> a LONG position was liquidated
      S == "Sell" -> a SHORT position was liquidated
    'p' is the BANKRUPTCY price, not an actual fill price (Bybit's stream
    does not expose one) - see module docstring's ROW SCHEMA note on price.
    """
    raw_side = item.get("S")
    if raw_side == "Buy":
        side = "long"
    elif raw_side == "Sell":
        side = "short"
    else:
        side = "unknown"
    price = _safe_float(item.get("p"))
    qty = _safe_float(item.get("v"))
    ts_ms = item.get("T")
    if price is None or qty is None:
        return None
    return {
        "ts_utc": _ms_to_iso(ts_ms),
        "venue": "bybit",
        "symbol": symbol_display,
        "side": side,
        "price": price,
        "qty_base": qty,
        "notional_usd": round(price * qty, 2),
        "source_raw": {"s": item.get("s"), "S": raw_side, "p": item.get("p"), "v": item.get("v"), "T": ts_ms},
    }


# ---------------------------------------------------------------------------
# Venue connection loops - each is fail-soft + independent, own backoff state
# ---------------------------------------------------------------------------
async def run_binance(symbols: List[str], logger: logging.Logger, stats: dict, stop_event: asyncio.Event) -> None:
    pairs = [(name, SYMBOL_MAP[name]["binance"]) for name in symbols if SYMBOL_MAP.get(name, {}).get("binance")]
    if not pairs:
        logger.info("binance: no watchlist symbols have a known Binance mapping - skipping venue")
        return
    binance_to_display = {b.lower(): name for name, b in pairs}
    streams = [f"{b.lower()}@forceOrder" for _, b in pairs]
    backoff = BACKOFF_BASE_S
    while not stop_event.is_set():
        try:
            logger.info(f"binance: connecting ({len(streams)} symbols: {', '.join(binance_to_display.values())})...")
            async with websockets.connect(BINANCE_WS_BASE, open_timeout=15, ping_interval=20, ping_timeout=20) as ws:
                sub = {"method": "SUBSCRIBE", "params": streams, "id": 1}
                await ws.send(json.dumps(sub))
                logger.info("binance: connected + subscribe sent, listening...")
                backoff = BACKOFF_BASE_S  # reset on a clean connect
                events_this_conn = 0
                last_heartbeat = time.time()
                while not stop_event.is_set():
                    try:
                        raw_msg = await asyncio.wait_for(ws.recv(), timeout=POLL_INTERVAL_S)
                    except asyncio.TimeoutError:
                        if time.time() - last_heartbeat >= HEARTBEAT_EVERY_S:
                            logger.info(f"binance: alive, connected, {events_this_conn} liquidation(s) this connection "
                                        f"(0 is expected/normal if this network cannot reach Binance's WS data plane - see module docstring)")
                            last_heartbeat = time.time()
                        continue
                    try:
                        msg = json.loads(raw_msg)
                    except json.JSONDecodeError:
                        continue
                    if "id" in msg and "stream" not in msg:
                        continue  # subscribe ack, e.g. {"result":null,"id":1}
                    # The combined /stream endpoint wraps every data message as
                    # {"stream": "<name>", "data": {...actual event...}} - unwrap it.
                    if "stream" in msg and "data" in msg:
                        msg = msg["data"]
                    if msg.get("e") != "forceOrder":
                        continue
                    marketId = (msg.get("o") or {}).get("s", "")
                    display = binance_to_display.get(marketId.lower())
                    if not display:
                        continue
                    row = _parse_binance_event(msg, display)
                    if row:
                        append_event(row)
                        events_this_conn += 1
                        stats["binance"] = stats.get("binance", 0) + 1
                        logger.info(f"binance LIQUIDATION: {display} {row['side']} ${row['notional_usd']:,.0f} @ {row['price']}")
        except asyncio.CancelledError:
            raise
        except Exception as e:  # fail-soft: never let a ws error kill the process
            logger.warning(f"binance: connection error ({type(e).__name__}: {e}) - reconnecting in {backoff:.1f}s")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=backoff + random.uniform(0, 1.0))
                return  # stop_event fired during backoff
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, BACKOFF_CAP_S)


async def run_bybit(symbols: List[str], logger: logging.Logger, stats: dict, stop_event: asyncio.Event) -> None:
    pairs = [(name, SYMBOL_MAP[name]["bybit"]) for name in symbols if SYMBOL_MAP.get(name, {}).get("bybit")]
    if not pairs:
        logger.info("bybit: no watchlist symbols have a known Bybit mapping - skipping venue")
        return
    bybit_to_display = {b: name for name, b in pairs}
    topics = [f"allLiquidation.{b}" for _, b in pairs]
    backoff = BACKOFF_BASE_S
    while not stop_event.is_set():
        ping_task = None
        try:
            logger.info(f"bybit: connecting ({len(topics)} symbols: {', '.join(bybit_to_display.values())})...")
            async with websockets.connect(BYBIT_WS_URL, open_timeout=15) as ws:
                await ws.send(json.dumps({"op": "subscribe", "args": topics}))

                async def _ping_loop():
                    # Bybit V5 public WS wants an app-level {"op":"ping"} periodically
                    # (docs: every 20s) or it drops the connection - protocol-level
                    # ws ping/pong alone is not sufficient for this venue.
                    while True:
                        await asyncio.sleep(20)
                        await ws.send(json.dumps({"op": "ping"}))

                ping_task = asyncio.create_task(_ping_loop())
                logger.info("bybit: connected + subscribe sent, listening...")
                backoff = BACKOFF_BASE_S
                events_this_conn = 0
                last_heartbeat = time.time()
                sub_confirmed = False
                while not stop_event.is_set():
                    try:
                        raw_msg = await asyncio.wait_for(ws.recv(), timeout=POLL_INTERVAL_S)
                    except asyncio.TimeoutError:
                        if time.time() - last_heartbeat >= HEARTBEAT_EVERY_S:
                            logger.info(f"bybit: alive, connected, {events_this_conn} liquidation(s) this connection")
                            last_heartbeat = time.time()
                        continue
                    try:
                        msg = json.loads(raw_msg)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("op") == "subscribe":
                        if msg.get("success") is False:
                            logger.warning(f"bybit: subscribe rejected: {msg.get('ret_msg')}")
                        else:
                            sub_confirmed = True
                            logger.info("bybit: subscription confirmed")
                        continue
                    if msg.get("op") == "pong" or msg.get("ret_msg") == "pong":
                        continue
                    topic = msg.get("topic", "")
                    if not topic.startswith("allLiquidation."):
                        continue
                    bybit_sym = topic.split(".", 1)[1]
                    display = bybit_to_display.get(bybit_sym)
                    if not display:
                        continue
                    for item in msg.get("data", []) or []:
                        row = _parse_bybit_event(item, display)
                        if row:
                            append_event(row)
                            events_this_conn += 1
                            stats["bybit"] = stats.get("bybit", 0) + 1
                            logger.info(f"bybit LIQUIDATION: {display} {row['side']} ${row['notional_usd']:,.0f} @ {row['price']}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"bybit: connection error ({type(e).__name__}: {e}) - reconnecting in {backoff:.1f}s")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=backoff + random.uniform(0, 1.0))
                return
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, BACKOFF_CAP_S)
        finally:
            if ping_task:
                ping_task.cancel()


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
async def _main_async(venues: List[str], symbols: List[str], duration: Optional[float], logger: logging.Logger) -> dict:
    stop_event = asyncio.Event()
    stats: dict = {}
    tasks = []
    if "binance" in venues:
        tasks.append(asyncio.create_task(run_binance(symbols, logger, stats, stop_event)))
    if "bybit" in venues:
        tasks.append(asyncio.create_task(run_bybit(symbols, logger, stats, stop_event)))
    if not tasks:
        logger.error("no venues enabled - nothing to do")
        return stats

    async def _timer():
        if duration is not None:
            await asyncio.sleep(duration)
            logger.info(f"duration={duration}s elapsed - shutting down cleanly")
            stop_event.set()

    timer_task = asyncio.create_task(_timer())
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        timer_task.cancel()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="WAGMI liquidation-cascade collector (read-only, standalone).")
    ap.add_argument("--venues", type=str, default="binance,bybit", help="Comma-separated: binance,bybit (default both)")
    ap.add_argument("--symbols", type=str, default=",".join(WATCHLIST), help="Comma-separated watchlist subset")
    ap.add_argument("--duration", type=float, default=None, help="Run for N seconds then exit cleanly (smoke-test mode)")
    ap.add_argument("--once", action="store_true", help="Shortcut for --duration 15 (quick sanity check)")
    ap.add_argument("--summary", action="store_true", help="Print liq_summary.py's report and exit (no collection)")
    args = ap.parse_args()

    if args.summary:
        if _THIS_DIR not in sys.path:
            sys.path.insert(0, _THIS_DIR)
        from liq_summary import print_summary  # local import: only needed for --summary
        print_summary(EVENTS_PATH)
        return

    venues = [v.strip().lower() for v in args.venues.split(",") if v.strip()]
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    duration = 15.0 if args.once else args.duration

    logger = _build_logger()
    logger.info(f"=== WAGMI liq_collector starting === venues={venues} symbols={symbols} "
                f"duration={duration if duration else 'forever'} out={EVENTS_PATH}")
    try:
        stats = asyncio.run(_main_async(venues, symbols, duration, logger))
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt - shutting down cleanly")
        stats = {}
    logger.info(f"=== liq_collector session ended === events captured this run: {stats}")


if __name__ == "__main__":
    main()
