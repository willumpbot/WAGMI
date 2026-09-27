#!/usr/bin/env python
"""
WAGMI Co-Pilot - OWNER-CALL system - owner_call.py
=============================================================================
THE single highest-leverage co-pilot instrument. The owner logs his OWN
discretionary entry - his direction, his read, e.g. `call KITTY long
"reclaimed range low, holders ripping"` - and gets back TWO things:

  1. A rich, ENTRY-TIME-SAFE snapshot, logged forward to
     data/copilot/owner_call_ledger.jsonl, so that in ~30-90 days HIS OWN
     discretionary edge can be tested against UNSEEN forward returns
     (resolve_owner_calls below). The scorecard (SIGNAL_SCORECARD.md) is blunt:
     the co-pilot has NO mechanical directional edge, and the data says the
     owner's discretionary judgment beats every mechanical entry rule tested -
     so the ONE thing worth manufacturing forward evidence on is HIS calls.
     This ledger accrues one data point PER TRADE HE TAKES, not one per 60
     calendar days like passive discovery, so it is the fastest path past the
     overfit ceiling.

  2. A RISK-AMPLIFIER brief (printed to stdout - phone-readable) that makes
     the trade survivable WITHOUT ever second-guessing his direction. This is
     the ONLY thing the co-pilot is honestly good at (per the scorecard):
     liquidation-safe leverage, liq price + how often the coin moves that far,
     a disaster stop, size for a small target risk %, the fee-scratch floor,
     and a correlation/concentration pointer. It NEVER tells him whether to
     take the trade or which way - that is his read.

HONESTY (matches SIGNAL_SCORECARD.md, no overclaim): the co-pilot claims NO
knowledge of direction. It logs his read verbatim and makes the position not
blow up. Entry direction and timing are HIS.

=============================================================================
ROUTING - be honest about the instrument type
=============================================================================
HL-LISTED perps (BTC/ETH/SOL/HYPE/XRP/POPCAT/WIF/FARTCOIN/PENGU/kPEPE/kBONK/
kSHIB and anything with an HL perp - detected LIVE via HL's `meta` universe,
not a hardcoded list): full leverage/liquidation machinery. Reuses copilot.py's
build_dip_read / compute_liquidation / compute_risk_plan (the validated,
horizon-aware, recalibrated risk numbers the scorecard says to trust) - no
reinvented risk claims.

DEX-SPOT memes NOT on HL (e.g. $KITTY and small Solana coins): NO leverage, NO
liquidation - and the brief SAYS SO. Snapshot comes from the micro-cap data
layer (data/microcap/wash_signal.jsonl, liquidity_snapshots.jsonl, and
flow_signal.jsonl IF a parallel build has added it - degrades gracefully to
null if absent). The "risk amplifier" for spot is position-size guidance for a
target $ risk + an organic_score/wash health caveat + a liquidity-vs-size
slippage caveat. Symbols are matched to a mint via universe.json /
universe_testable.json (Solana symbols collide - if ambiguous, the highest-
liquidity match is used and the ambiguity is flagged; the chosen mint is
recorded in the row so resolution is unambiguous).

READ-ONLY / STANDALONE, same contract as every tools/copilot/*.py module:
never imports live-bot packages (llm/, execution/, core/, strategies/), never
touches live/.env/data/replay. Writes exactly ONE new file it owns:
data/copilot/owner_call_ledger.jsonl (append-only) and its resolved twin
owner_call_ledger_resolved.jsonl. No Discord push.

ROW SCHEMA (data/copilot/owner_call_ledger.jsonl, one JSON object per line):
    ts_utc, epoch          when the call was logged (wall clock; NOT the
                            resolution anchor - see settled_close_date)
    symbol, side           his read: "LONG"/"SHORT"
    reason                 his FULL reason, up to ~500 chars (NOT truncated as
                            harshly as the auto call-logger's 140)
    source                 always "owner_manual"
    instrument_type        "HL_PERP" or "DEX_SPOT"
    ev_schema              forward-evidence schema version (see EV_SCHEMA_VERSION)
    leverage               his stated leverage, or null (spot: always null)
    mint                   DEX-spot: the resolved Solana mint (null for HL)
    mint_ambiguous         DEX-spot: true if >1 candidate mint existed for the
                            symbol (highest-liquidity one was chosen)
    settled_close          close of the last FULLY CLOSED daily candle at call
                            time (entry-time-safe anchor for resolution)
    settled_close_date     "YYYY-MM-DD", that candle's open date (the calendar
                            anchor resolve_owner_calls uses; NOT ts_utc)
    price                  live/display price at call time (human continuity
                            only - resolver uses settled_close, never this)
    -- HL_PERP extra fields --
    action, action_reason_short, trend, adx, bb_pos, rsi, atr_pct,
    funding_hourly, safe_max_lev, liq_price, liq_distance_pct, risk_label,
    size_notional_usd, disaster_stop_price, beta_to_btc
    -- DEX_SPOT extra fields --
    organic_score, organic_score_label, holder_count, liquidity_usd,
    volume_h24, daily_vol_pct, size_notional_usd, size_pct_of_liquidity,
    flow_holder_growth_24h, flow_organic_buyer_influx_24h, flow_liq_change_24h,
    flow_txns_buy_sell_ratio_24h, flow_vol_accel_1h_vs_24h  (flow_* null until
    the parallel flow_signal.jsonl build lands)

FAIL-NEUTRAL: log_owner_call() swallows every exception (one-line stderr
warning) and returns a bool - logging must never be the reason a brief breaks.
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import os
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from copilot import (  # noqa: E402
    DEFAULT_SIDE,
    MAX_HOLD_DAYS_RANGE,
    RealizedVol,
    _fetch_hl_universe,
    _funding_direction_note,
    _get_hl_client,
    _norm_symbol,
    build_dip_read,
    compute_liquidation,
    compute_risk_plan,
    fetch_hl_max_leverage,
)

BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))
DATA_DIR = os.path.join(BOT_DIR, "data", "copilot")
LEDGER_PATH = os.path.join(DATA_DIR, "owner_call_ledger.jsonl")
RESOLVED_PATH = os.path.join(DATA_DIR, "owner_call_ledger_resolved.jsonl")

MICROCAP_DIR = os.path.join(BOT_DIR, "data", "microcap")
WASH_PATH = os.path.join(MICROCAP_DIR, "wash_signal.jsonl")
LIQ_SNAP_PATH = os.path.join(MICROCAP_DIR, "liquidity_snapshots.jsonl")
FLOW_PATH = os.path.join(MICROCAP_DIR, "flow_signal.jsonl")
UNIVERSE_PATH = os.path.join(MICROCAP_DIR, "universe.json")
UNIVERSE_TESTABLE_PATH = os.path.join(MICROCAP_DIR, "universe_testable.json")
OHLCV_DIR = os.path.join(MICROCAP_DIR, "ohlcv")

# Jupiter organic_score (0-100) at/above this = "genuinely traded" (not wash/
# dead). Matches the collector's testable-universe gate. Used by resolve_mint's
# health tier and the spot health readout so a wash clone of a famous symbol
# never wins mint resolution over the canonical, genuinely-traded coin.
MICROCAP_HEALTHY_ORGANIC_FLOOR = 40.0

# ev-schema for the owner-call forward-evidence instrument. Independent of the
# auto call-logger's version; starts at 2 to match its post-anchor-fix
# settled-close contract (settled_close/settled_close_date carried on every row).
EV_SCHEMA_VERSION = 2

CALL_LOG_ENV = "COPILOT_OWNER_CALL_LOG"
_DISABLED_VALUES = {"false", "0", "no", "off"}

MAX_REASON_LEN = 500

# Risk sizing defaults. The owner's account is small (~$5k) and the ceiling on
# fraction-of-equity risked per trade is 0.5% (MAX_RISK_PCT_CEILING = 0.005) -
# so the owner-call sizes for 0.5% by default, NOT the 1.0% the generic RISK
# PLAN uses. Never size above the ceiling by default.
MAX_RISK_PCT_CEILING = 0.005          # 0.5% of equity - hard ceiling
DEFAULT_RISK_PCT = 0.5                 # percent (0.5% of equity)
DEFAULT_EQUITY_USD = 5000.0

# Round-trip taker fee (matches pretrade.py's ~9bps). Used only for the honest
# "price must move ~X% just to clear fees" floor on HL calls - never a signal.
ROUND_TRIP_FEE_BPS = 9.0
# Rough one-way slippage estimate (bps) for the fee floor - same spirit as
# pretrade.SLIPPAGE_BPS_ESTIMATE (unmeasured heuristic, majors low / alts high).
_SLIPPAGE_BPS = {"BTC": 0.3, "ETH": 0.3, "SOL": 0.5, "HYPE": 1.0}
_DEFAULT_SLIPPAGE_BPS_ONE_WAY = 5.0

# Spot sizing: with no leverage/liq, a spot meme's "stop" is a mental one. Size
# for the target $ risk against a 2x-daily-vol adverse move (the same 2xATR
# spirit copilot's RISK PLAN uses), then cap by a slippage caveat vs pool depth.
SPOT_STOP_VOL_MULT = 2.0
# Slippage is estimated from CONSTANT-PRODUCT (xy=k) AMM math, NOT a raw
# "% of pool" heuristic (the old 2%-of-pool rule badly understated cost - a 2%
# order slips ~4%). DexScreener liquidity_usd ~= both sides ~= 2 * quote reserve
# Y, and for xy=k a buy of $S has avg-execution slippage vs spot ~= S/Y =
# 2*S/liquidity_usd (one-way); a round trip is ~2x that. So the honest one-way
# slippage estimate is 2*size/liquidity. Flag on the SLIPPAGE %, not the pool %.
# (A live Jupiter /quote would be exact incl. routing/fees; this xy=k figure is
# the honest slippage-naive floor - real cost is >= this, never less.)
SLIPPAGE_NOTABLE_PCT = 1.0     # one-way est >=1% -> scale in
SLIPPAGE_SEVERE_PCT = 3.0      # one-way est >=3% -> you're moving the market


def estimate_amm_slippage_pct(size_usd: Optional[float], liquidity_usd: Optional[float]) -> Optional[float]:
    """Constant-product one-way avg-execution slippage vs spot, in PERCENT.
    ~= 2 * size / liquidity_usd (see SLIPPAGE constants above). None if inputs
    missing/non-positive. Slippage-naive floor: real cost (routing + LP fee +
    MEV) is >= this, never less."""
    if not size_usd or not liquidity_usd or size_usd <= 0 or liquidity_usd <= 0:
        return None
    return (2.0 * size_usd / liquidity_usd) * 100.0

HORIZONS_DAYS: Tuple[int, ...] = (1, 7, 30)   # owner-call forward horizons
VERDICT_MIN_N = 20                     # no edge verdict printed below this many resolved calls

HONESTY_FOOTER = (
    "The co-pilot does NOT know your direction is right - that's your read, and the data says "
    "your discretion beats every mechanical entry rule tested. Everything above is risk/not-blow-up "
    "math (arithmetic + measured volatility), never a prediction. Your calls are logged (see line above) "
    "to build forward proof of YOUR edge."
)


# ---------------------------------------------------------------------------
# small jsonl / json helpers (standalone; no live-bot deps)
# ---------------------------------------------------------------------------

def _is_enabled() -> bool:
    return os.environ.get(CALL_LOG_ENV, "true").strip().lower() not in _DISABLED_VALUES


def _short_reason(reason: Optional[str], max_len: int = MAX_REASON_LEN) -> str:
    if not reason:
        return ""
    flat = " ".join(str(reason).split())
    if len(flat) <= max_len:
        return flat
    return flat[: max_len - 3].rstrip(",;:- ") + "..."


def _load_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _iter_jsonl(path: str):
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _load_jsonl(path: str) -> List[dict]:
    return list(_iter_jsonl(path))


def _latest_row_for_mint(path: str, mint: str) -> Optional[dict]:
    """Last (most recent) row in a micro-cap jsonl whose mint matches. Linear
    reverse scan - fine at this tool's scale. Never raises."""
    best = None
    for row in _iter_jsonl(path):
        if row.get("mint") == mint:
            best = row  # rows are appended in time order; keep the last match
    return best


# ---------------------------------------------------------------------------
# ROUTING - is this symbol an HL perp?
# ---------------------------------------------------------------------------

def is_hl_listed(client, symbol: str) -> bool:
    """True iff `symbol` is in HL's live `meta` universe (i.e. has a perp).
    Fail-soft: if the meta fetch failed, returns False (treated as spot) - the
    spot path degrades gracefully, so a transient HL outage never crashes."""
    universe = _fetch_hl_universe(client)
    if not universe:
        return False
    return symbol in universe


# ---------------------------------------------------------------------------
# MINT RESOLUTION for DEX-spot symbols (Solana symbols collide)
# ---------------------------------------------------------------------------

@dataclass
class MintMatch:
    mint: Optional[str] = None
    liquidity_usd: Optional[float] = None
    organic_score: Optional[float] = None
    ohlcv_day_path: Optional[str] = None
    ambiguous: bool = False
    n_candidates: int = 0
    note: str = ""


def _collect_mint_candidates(symbol: str) -> Dict[str, dict]:
    """Gather every known mint for `symbol` (case-insensitive) across the
    screened universe files AND the live micro-cap collectors, merging the
    liquidity/organic/ohlcv facts we know about each. Returns {mint: {...}}."""
    sym_u = symbol.upper()
    cands: Dict[str, dict] = {}

    def _touch(mint: str) -> dict:
        return cands.setdefault(mint, {"liquidity_usd": None, "organic_score": None, "ohlcv_day_path": None})

    testable = _load_json(UNIVERSE_TESTABLE_PATH) or {}
    for c in (testable.get("coins") or []):
        if str(c.get("symbol", "")).upper() == sym_u and c.get("mint"):
            e = _touch(c["mint"])
            if c.get("liquidity_usd") is not None:
                e["liquidity_usd"] = c["liquidity_usd"]
            if c.get("organic_score") is not None:
                e["organic_score"] = c["organic_score"]
            if c.get("ohlcv_day_path"):
                e["ohlcv_day_path"] = os.path.join(MICROCAP_DIR, c["ohlcv_day_path"])

    universe = _load_json(UNIVERSE_PATH) or {}
    for key in ("tier_a_named", "tier_b_systematic", "tier_b_established"):
        for c in (universe.get(key) or []):
            if str(c.get("symbol", "")).upper() == sym_u and c.get("mint"):
                e = _touch(c["mint"])
                if e["liquidity_usd"] is None and c.get("liquidity_usd") is not None:
                    e["liquidity_usd"] = c["liquidity_usd"]

    # live collectors also carry mints (and may track a mint the universe files
    # haven't refreshed into yet) - fold their latest liquidity/organic in too.
    for path, field_lookup in ((LIQ_SNAP_PATH, "liquidity_usd"), (WASH_PATH, "organic_score")):
        seen_latest: Dict[str, dict] = {}
        for row in _iter_jsonl(path):
            if str(row.get("symbol", "")).upper() == sym_u and row.get("mint"):
                seen_latest[row["mint"]] = row
        for mint, row in seen_latest.items():
            e = _touch(mint)
            if field_lookup == "liquidity_usd" and e["liquidity_usd"] is None and row.get("liquidity_usd") is not None:
                e["liquidity_usd"] = row.get("liquidity_usd")
            if field_lookup == "organic_score" and e["organic_score"] is None and row.get("organic_score") is not None:
                e["organic_score"] = row.get("organic_score")
    return cands


def _find_ohlcv_day_path(symbol: str, mint: str) -> Optional[str]:
    """Locate the daily OHLCV CSV for (symbol, mint). Files are named
    `{symbol}_{mint[:8]}_day.csv`. Falls back to a mint-prefix glob."""
    direct = os.path.join(OHLCV_DIR, f"{symbol}_{mint[:8]}_day.csv")
    if os.path.isfile(direct):
        return direct
    hits = glob.glob(os.path.join(OHLCV_DIR, f"*_{mint[:8]}_day.csv"))
    return hits[0] if hits else None


def resolve_mint(symbol: str) -> MintMatch:
    """Pick the mint for a DEX-spot symbol. HEALTH tier wins first (a genuinely-
    traded coin beats a wash/dead clone even if the clone shows higher - and
    likely fake - liquidity), then liquidity, then organic score. Ambiguity
    (>1 candidate) is flagged; if a higher-'liquidity' but wash/dead mint was
    deprioritized, the note says so. Records the chosen mint + its ohlcv day
    path (looked up if the universe files didn't carry one)."""
    cands = _collect_mint_candidates(symbol)
    if not cands:
        return MintMatch(note=f"no known mint for {symbol} in universe/microcap data")

    # Health tier: 2 = healthy (organic_score >= floor), 1 = unmeasured (None -
    # not confirmed dead, don't punish), 0 = confirmed low/wash/dead (incl 0).
    # This stops a wash clone of a famous coin (e.g. a 0-organic BONK with big
    # fake liquidity) from beating the canonical, genuinely-traded mint.
    def _health_tier(os_val) -> int:
        if os_val is None:
            return 1
        return 2 if os_val >= MICROCAP_HEALTHY_ORGANIC_FLOOR else 0

    def _key(item):
        _m, d = item
        return (_health_tier(d.get("organic_score")),
                d.get("liquidity_usd") if d.get("liquidity_usd") is not None else -1.0,
                d.get("organic_score") if d.get("organic_score") is not None else -1.0)

    ranked = sorted(cands.items(), key=_key, reverse=True)
    mint, d = ranked[0]
    ohlcv = d.get("ohlcv_day_path") or _find_ohlcv_day_path(symbol, mint)
    ambiguous = len(cands) > 1
    note = ""
    if ambiguous:
        # Was a higher-raw-liquidity candidate skipped because it's wash/dead?
        most_liquid = max(cands.values(),
                          key=lambda x: x.get("liquidity_usd") if x.get("liquidity_usd") is not None else -1.0)
        skipped_wash = (most_liquid is not d
                        and _health_tier(most_liquid.get("organic_score")) < _health_tier(d.get("organic_score")))
        chosen_desc = (f"chose the genuinely-traded one (organic {d.get('organic_score')}, "
                       f"${(d.get('liquidity_usd') or 0):,.0f}); a higher-'liquidity' but wash/dead mint was skipped"
                       if skipped_wash else
                       f"chose the healthiest/most-liquid one (organic {d.get('organic_score')}, "
                       f"${(d.get('liquidity_usd') or 0):,.0f})")
        note = (
            f"{len(cands)} mints share the symbol {symbol}; {chosen_desc}. "
            f"Confirm this is the coin you mean."
        )
    return MintMatch(
        mint=mint, liquidity_usd=d.get("liquidity_usd"), organic_score=d.get("organic_score"),
        ohlcv_day_path=ohlcv, ambiguous=ambiguous, n_candidates=len(cands), note=note,
    )


# ---------------------------------------------------------------------------
# Micro-cap OHLCV -> settled candle + realized daily vol (entry-time-safe)
# ---------------------------------------------------------------------------

def _read_ohlcv_daily(path: Optional[str]) -> List[Tuple[str, float]]:
    """Returns [(open_date 'YYYY-MM-DD', close), ...] sorted ascending, from a
    micro-cap daily CSV (timestamp_unix, timestamp_iso, o,h,l,c, volume_usd).
    Empty list on any problem - callers degrade gracefully."""
    if not path or not os.path.isfile(path):
        return []
    out: List[Tuple[str, float]] = []
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    ts = int(float(row["timestamp_unix"]))
                    close = float(row["close"])
                except (KeyError, TypeError, ValueError):
                    continue
                d = datetime.fromtimestamp(ts, tz=timezone.utc).date().strftime("%Y-%m-%d")
                out.append((d, close))
    except OSError:
        return []
    out.sort(key=lambda x: x[0])
    return out


def _settled_from_ohlcv(rows: List[Tuple[str, float]]) -> Tuple[Optional[float], Optional[str]]:
    """Last FULLY-CLOSED daily candle (drop today's still-forming bar)."""
    if not rows:
        return None, None
    today = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")
    idx = len(rows) - 1
    if rows[idx][0] >= today and idx >= 1:
        idx -= 1
    return rows[idx][1], rows[idx][0]


def _daily_vol_pct_from_ohlcv(rows: List[Tuple[str, float]], lookback: int = 45) -> Optional[float]:
    closes = [c for _d, c in rows[-(lookback + 1):] if c and c > 0]
    if len(closes) < 8:
        return None
    rets = [(closes[i] / closes[i - 1] - 1.0) * 100.0 for i in range(1, len(closes))]
    if len(rets) < 2:
        return None
    return float(statistics.pstdev(rets))


# ---------------------------------------------------------------------------
# MICRO-CAP SNAPSHOT FRESHNESS (staleness disclosure).
# The wash/liquidity/flow snapshots are written FORWARD by the micro-cap
# collector (a separate process / Task Scheduler job). If that collector
# stalls (crash, network, machine off), `_latest_row_for_mint` still returns
# the last row it wrote - which could be HOURS or DAYS old. Presenting a stale
# organic_score / price / liquidity / "RIGHT NOW" flow as if it were current
# is a REAL harm on a fast meme, so eye/call MUST disclose the snapshot age.
# ---------------------------------------------------------------------------

# Micro-cap snapshots older than this get a prominent freshness caveat. The
# collector normally writes every few minutes, so >2h means it likely stalled.
SNAPSHOT_STALE_WARN_HOURS = 2.0


def _parse_snapshot_ts(ts: Optional[str]) -> Optional[datetime]:
    """Parse a micro-cap snapshot ts_utc (full ISO, may carry a tz offset).
    Returns a tz-aware UTC datetime, or None. Never raises."""
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError, TypeError):
        return None


def _snapshot_age_hours(rows: List[Optional[dict]], now: Optional[datetime] = None
                        ) -> Tuple[Optional[datetime], Optional[float]]:
    """Newest ts_utc across the given snapshot rows + its age in hours (both
    None if no row carries a parseable ts_utc)."""
    now = now or datetime.now(timezone.utc)
    newest: Optional[datetime] = None
    for r in rows:
        if not r:
            continue
        dt = _parse_snapshot_ts(r.get("ts_utc"))
        if dt is not None and (newest is None or dt > newest):
            newest = dt
    if newest is None:
        return None, None
    return newest, (now - newest).total_seconds() / 3600.0


def _fmt_age(age_h: float) -> str:
    if age_h < 1.0:
        return f"{age_h * 60.0:.0f}min"
    if age_h < 48.0:
        return f"{age_h:.1f}h"
    return f"{age_h / 24.0:.1f}d"


def _freshness_line(age_h: Optional[float]) -> str:
    """One human line disclosing the micro-cap snapshot age. A prominent STALE
    caveat once past SNAPSHOT_STALE_WARN_HOURS; a quiet 'current' note otherwise."""
    if age_h is None:
        return ("Data freshness: snapshot has NO timestamp - age UNKNOWN; treat the health/price/flow "
                "below as unverified and re-check on-chain before trading.")
    if age_h <= SNAPSHOT_STALE_WARN_HOURS:
        return f"Data freshness: micro-cap snapshot ~{_fmt_age(age_h)} old (current)."
    return (f">>> STALE DATA: micro-cap snapshot is ~{_fmt_age(age_h)} old (collector likely stalled) - the "
            f"organic/price/liquidity/flow below may NOT reflect right now. Re-check before trading a fast meme. <<<")


# ---------------------------------------------------------------------------
# OwnerCall result object + builders
# ---------------------------------------------------------------------------

@dataclass
class OwnerCall:
    ok: bool = True
    note: Optional[str] = None
    symbol: str = ""
    side: str = DEFAULT_SIDE
    reason: str = ""
    instrument_type: str = ""     # HL_PERP / DEX_SPOT
    leverage: Optional[float] = None
    equity: float = DEFAULT_EQUITY_USD
    risk_pct: float = DEFAULT_RISK_PCT

    brief_lines: List[str] = field(default_factory=list)
    row: Dict[str, Any] = field(default_factory=dict)


def _base_row(oc: "OwnerCall", now: datetime) -> Dict[str, Any]:
    return {
        "ts_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "epoch": int(now.timestamp()),
        "symbol": oc.symbol,
        "side": oc.side,
        "reason": _short_reason(oc.reason),
        "source": "owner_manual",
        "instrument_type": oc.instrument_type,
        "ev_schema": EV_SCHEMA_VERSION,
        "leverage": oc.leverage,
    }


def _fee_floor_pct(symbol: str) -> float:
    slip_one_way = _SLIPPAGE_BPS.get(symbol, _DEFAULT_SLIPPAGE_BPS_ONE_WAY)
    return (ROUND_TRIP_FEE_BPS + slip_one_way * 2.0) / 100.0  # bps -> percent


def build_hl_owner_call(client, oc: "OwnerCall", now: datetime) -> "OwnerCall":
    """HL-perp path: full leverage/liq risk amplifier reusing copilot.py."""
    dip = build_dip_read(client, oc.symbol)
    if not dip.ok:
        oc.ok = False
        oc.note = dip.data_note or f"no HL data for {oc.symbol}"
        return oc

    hl_max = fetch_hl_max_leverage(client, oc.symbol)
    side = oc.side
    lev = oc.leverage

    # risk plan (horizon-aware safe leverage, 2xATR stop, size for target risk)
    liq_at_lev = compute_liquidation(dip.price, side, lev if lev else 1.0, dip.vol, hl_max, oc.symbol)
    plan = compute_risk_plan(dip, liq_at_lev, side, risk_pct=oc.risk_pct, account_usd=oc.equity)
    safe_max = plan.safe_max_leverage if plan.safe_max_leverage is not None else liq_at_lev.safe_max_leverage

    # if he gave no leverage, recommend the horizon-safe max as the working lever
    working_lev = lev if lev else safe_max
    liq = compute_liquidation(dip.price, side, working_lev, dip.vol, hl_max, oc.symbol, hold_days=MAX_HOLD_DAYS_RANGE[1])

    # correlation / concentration pointer (reuse book.py, no duplicated math)
    beta = None
    try:
        from book import build_return_frame, compute_beta_to_btc  # local import
        frame, _notes = build_return_frame(client, sorted({oc.symbol, "BTC"}), 150)
        beta = compute_beta_to_btc(frame, oc.symbol)
    except Exception as e:  # noqa: BLE001
        print(f"[owner_call] beta-to-BTC unavailable for {oc.symbol}: {e}", file=sys.stderr)

    fee_floor = _fee_floor_pct(oc.symbol)
    notional_ctx = oc.equity * (working_lev or 1.0)

    L = oc.brief_lines
    L.append(f"OWNER CALL: {oc.symbol} {side} - HL PERP (leverage + liquidation apply)")
    L.append(f"  Your read: \"{_short_reason(oc.reason)}\"")
    L.append(f"  Price ${dip.price:.6f} | {dip.trend_1d.upper()} (ADX {dip.adx_1d:.0f} {dip.trend_strength}) "
             f"| RSI {dip.rsi_1d:.0f} | ATR {(dip.atr_pct_1d or 0)*100:.1f}%/day" if dip.adx_1d is not None and dip.rsi_1d is not None
             else f"  Price ${dip.price:.6f} | {dip.trend_1d.upper()}")
    L.append("")
    L.append("RISK AMPLIFIER (survive-the-trade math - your direction is NOT questioned):")

    lev_show = f"{working_lev:.1f}x" + ("" if lev else " (recommended - you gave no leverage)")
    if plan.horizon_used is not None and plan.single_day_safe_max_leverage is not None:
        L.append(
            f"  Safe leverage: multi-day (~{plan.horizon_used:.0f}d hold) safe <= {safe_max:.1f}x "
            f"(OOS ~4% liq risk); single-day ceiling {plan.single_day_safe_max_leverage:.1f}x. "
            f"Using {lev_show}."
        )
    else:
        L.append(f"  Safe leverage: <= {safe_max:.1f}x for {oc.symbol} right now. Using {lev_show}.")
    if lev and safe_max and lev > safe_max + 1e-9:
        L.append(f"  >>> WARNING: your {lev:.1f}x is ABOVE the safe max {safe_max:.1f}x [{liq.risk_label}] - cut it. <<<")
    L.append(
        f"  Liquidation @ {working_lev:.1f}x {side}: ${liq.liq_price:.6f} ({liq.distance_pct*100:.1f}% away) "
        f"- {oc.symbol} has moved that far in a day {liq.drop_freq_note}."
    )
    if plan.ok and plan.size_notional_usd is not None and plan.disaster_stop_price is not None:
        L.append(
            f"  Size for {oc.risk_pct:.2f}% risk (${plan.risk_usd:,.2f} on ${oc.equity:,.0f}): "
            f"~${plan.size_notional_usd:,.0f} notional, disaster stop ${plan.disaster_stop_price:.6f} "
            f"(2xATR, {(plan.disaster_stop_pct or 0)*100:.1f}% away)."
        )
    L.append(f"  Hard stop (before HL liquidates): ${liq.hard_stop_price:.6f} ({liq.hard_stop_pct*100:.1f}% away).")
    L.append(
        f"  Fee floor: price must move ~{fee_floor:.2f}% just to clear the ~9bps round-trip fee "
        f"(+ est. slippage) before any profit."
    )
    if beta is not None:
        L.append(
            f"  Concentration: {oc.symbol} beta-to-BTC ~{beta:.2f} (moves ~{beta:.1f}x BTC). "
            f"If you already hold correlated longs, run `cli.py book` to see combined liq risk."
        )
    L.append("  " + _funding_direction_note(dip, side, notional_ctx))
    if plan.leverage_veto:
        which = "FALLING KNIFE" if plan.leverage_veto_reason == "knife" else "CHOP"
        L.append(f"  >>> {which} regime: the risk here is a -10% path that liquidates a lever, not your direction "
                 f"- stay spot or <=2x if you take it. <<<")

    r = _base_row(oc, now)
    r.update({
        "price": dip.price,
        "settled_close": dip.settled_close,
        "settled_close_date": dip.settled_close_date,
        "mint": None,
        "action": dip.action,
        "action_reason_short": _short_reason(dip.action_reason, 140),
        "trend": dip.trend_1d,
        "adx": dip.adx_1d,
        "bb_pos": dip.bb_pos_1d,
        "rsi": dip.rsi_1d,
        "atr_pct": dip.atr_pct_1d,
        "funding_hourly": dip.funding_rate,
        "safe_max_lev": safe_max,
        "liq_price": liq.liq_price,
        "liq_distance_pct": liq.distance_pct,
        "risk_label": liq.risk_label,
        "size_notional_usd": plan.size_notional_usd if plan.ok else None,
        "disaster_stop_price": plan.disaster_stop_price if plan.ok else None,
        "beta_to_btc": beta,
    })
    oc.row = r
    return oc


def build_spot_owner_call(oc: "OwnerCall", now: datetime) -> "OwnerCall":
    """DEX-spot path: NO leverage/liq. Snapshot from the micro-cap layer +
    position-size guidance + wash-health + liquidity-slippage caveats."""
    mm = resolve_mint(oc.symbol)
    if mm.mint is None:
        oc.ok = False
        oc.note = mm.note
        return oc

    wash = _latest_row_for_mint(WASH_PATH, mm.mint) or {}
    liqsnap = _latest_row_for_mint(LIQ_SNAP_PATH, mm.mint) or {}
    flow = _latest_row_for_mint(FLOW_PATH, mm.mint) or {}  # empty if file absent

    snap_ts, snap_age_h = _snapshot_age_hours([wash, liqsnap, flow], now)

    ohlcv_rows = _read_ohlcv_daily(mm.ohlcv_day_path)
    settled_close, settled_date = _settled_from_ohlcv(ohlcv_rows)
    daily_vol = _daily_vol_pct_from_ohlcv(ohlcv_rows)

    organic = wash.get("organic_score", mm.organic_score)
    organic_label = wash.get("organic_score_label")
    holders = wash.get("holder_count")
    liquidity = liqsnap.get("liquidity_usd", mm.liquidity_usd)
    price = liqsnap.get("price_usd")
    if price is None and ohlcv_rows:
        price = ohlcv_rows[-1][1]
    vol_h24 = liqsnap.get("volume_h24")

    # size for target $ risk against a 2x-daily-vol mental stop (no liq exists)
    risk_usd = oc.equity * oc.risk_pct / 100.0
    size_notional = None
    size_pct_liq = None
    if daily_vol and daily_vol > 1e-9:
        stop_frac = (SPOT_STOP_VOL_MULT * daily_vol) / 100.0
        if stop_frac > 1e-9:
            size_notional = risk_usd / stop_frac
    if size_notional is not None and liquidity and liquidity > 0:
        size_pct_liq = size_notional / liquidity

    L = oc.brief_lines
    L.append(f"OWNER CALL: {oc.symbol} {oc.side} - DEX SPOT (NO leverage, NO liquidation - spot only)")
    L.append(f"  Your read: \"{_short_reason(oc.reason)}\"")
    L.append(f"  Mint: {mm.mint}")
    if mm.ambiguous:
        L.append(f"  >>> AMBIGUOUS: {mm.note} <<<")
    L.append(f"  {_freshness_line(snap_age_h)}")
    px_bit = f"${price:.8f}" if isinstance(price, (int, float)) else "n/a"
    L.append(f"  Price {px_bit} | liquidity ${(liquidity or 0):,.0f} | 24h vol ${(vol_h24 or 0):,.0f}"
             + (f" | daily vol ~{daily_vol:.1f}%" if daily_vol else ""))
    L.append("")
    L.append("RISK AMPLIFIER (spot - size + health, NO leverage/liq to manage):")

    if size_notional is not None:
        L.append(
            f"  Size for {oc.risk_pct:.2f}% risk (${risk_usd:,.2f} on ${oc.equity:,.0f}): ~${size_notional:,.0f} "
            f"against a mental stop ~{SPOT_STOP_VOL_MULT*daily_vol:.1f}% out (2x its {daily_vol:.1f}% daily vol) - "
            f"spot can go to zero, so this stop is YOURS to honor, nothing liquidates you into it."
        )
    else:
        L.append("  Size: unavailable (no daily-vol history) - size small; spot memes can round-trip to ~0.")

    # wash / organic health caveat
    if organic is not None:
        if organic < 40:
            health = ">>> WASH RISK: organic_score {:.0f}/100 (low) - volume looks largely inorganic; treat with suspicion. <<<".format(organic)
        elif organic < 60:
            health = "organic_score {:.0f}/100 (medium) - some real flow, still thin.".format(organic)
        else:
            health = "organic_score {:.0f}/100 (healthier) - relatively organic flow.".format(organic)
        holder_bit = f" holders {holders:,}." if isinstance(holders, (int, float)) else ""
        L.append(f"  Health: {health}{holder_bit}")
    else:
        L.append("  Health: organic_score unavailable for this mint (degraded) - size small.")

    # liquidity vs size slippage caveat - constant-product (xy=k) estimate, not
    # a raw "% of pool" heuristic. slip_pct = one-way avg execution vs spot.
    slip_pct = estimate_amm_slippage_pct(size_notional, liquidity)
    if slip_pct is not None:
        rt = slip_pct * 2.0  # round-trip (in + out)
        basis = (f"~${size_notional:,.0f} into a ${liquidity:,.0f} pool: est ~{slip_pct:.1f}% "
                 f"one-way slippage (~{rt:.1f}% round-trip, constant-product estimate)")
        if slip_pct >= SLIPPAGE_SEVERE_PCT:
            L.append(f"  >>> SLIPPAGE SEVERE: {basis} - you'd move the market on entry AND exit. Cut size or scale in hard. <<<")
        elif slip_pct >= SLIPPAGE_NOTABLE_PCT:
            L.append(f"  >>> SLIPPAGE: {basis} - notable; the round-trip alone eats into any move. Consider scaling in. <<<")
        else:
            L.append(f"  Slippage: {basis} - manageable.")
        L.append(f"    (slippage-naive floor from pool depth; real cost incl. LP fee + routing + MEV is >= this. A max size for ~{SLIPPAGE_NOTABLE_PCT:.0f}% one-way is ~${liquidity*SLIPPAGE_NOTABLE_PCT/200.0:,.0f}.)")
    elif liquidity:
        L.append(f"  Slippage: pool ${liquidity:,.0f} - keep entry small; ~${liquidity*SLIPPAGE_NOTABLE_PCT/200.0:,.0f} is the ~{SLIPPAGE_NOTABLE_PCT:.0f}% one-way slippage size (constant-product estimate).")

    # flow signal (parallel build - degrade gracefully)
    if flow:
        fbits = []
        for k, lbl in (("holder_growth_24h", "holder growth 24h"),
                       ("organic_buyer_influx_24h", "organic buyer influx 24h"),
                       ("liq_change_24h", "liq change 24h"),
                       ("txns_buy_sell_ratio_24h", "buy/sell txn ratio 24h"),
                       ("vol_accel_1h_vs_24h", "vol accel 1h vs 24h")):
            if flow.get(k) is not None:
                fbits.append(f"{lbl} {flow[k]}")
        if fbits:
            L.append("  Flow: " + "; ".join(fbits) + ".")
    else:
        L.append("  Flow: flow_signal not yet available (parallel build) - degraded, snapshot still logged.")

    r = _base_row(oc, now)
    r.update({
        "price": price,
        "settled_close": settled_close,
        "settled_close_date": settled_date,
        "mint": mm.mint,
        "mint_ambiguous": mm.ambiguous,
        "snapshot_ts_utc": snap_ts.strftime("%Y-%m-%dT%H:%M:%SZ") if snap_ts else None,
        "snapshot_age_hours": round(snap_age_h, 3) if snap_age_h is not None else None,
        "snapshot_stale": (snap_age_h is not None and snap_age_h > SNAPSHOT_STALE_WARN_HOURS),
        "organic_score": organic,
        "organic_score_label": organic_label,
        "holder_count": holders,
        "liquidity_usd": liquidity,
        "volume_h24": vol_h24,
        "daily_vol_pct": daily_vol,
        "size_notional_usd": size_notional,
        "size_pct_of_liquidity": size_pct_liq,
        "flow_holder_growth_24h": flow.get("holder_growth_24h"),
        "flow_organic_buyer_influx_24h": flow.get("organic_buyer_influx_24h"),
        "flow_liq_change_24h": flow.get("liq_change_24h"),
        "flow_txns_buy_sell_ratio_24h": flow.get("txns_buy_sell_ratio_24h"),
        "flow_vol_accel_1h_vs_24h": flow.get("vol_accel_1h_vs_24h"),
    })
    oc.row = r
    return oc


def build_owner_call(
    symbol: str, side: str, reason: str,
    leverage: Optional[float] = None, equity: float = DEFAULT_EQUITY_USD,
    risk_pct: float = DEFAULT_RISK_PCT, client=None, now: Optional[datetime] = None,
) -> OwnerCall:
    """Build the risk-amplifier brief + entry-time-safe row for one owner call.
    Routes HL vs DEX-spot automatically. Does NOT write anything - that's
    log_owner_call / run_call."""
    now = now or datetime.now(timezone.utc)
    sym = _norm_symbol(symbol)
    side_u = (side or DEFAULT_SIDE).strip().upper()
    if side_u in ("BUY",):
        side_u = "LONG"
    if side_u in ("SELL",):
        side_u = "SHORT"
    risk_pct = min(risk_pct, MAX_RISK_PCT_CEILING * 100.0)  # honor the 0.5% ceiling
    oc = OwnerCall(symbol=sym, side=side_u, reason=reason or "", leverage=leverage,
                   equity=equity, risk_pct=risk_pct)
    client = client or _get_hl_client()
    if is_hl_listed(client, sym):
        oc.instrument_type = "HL_PERP"
        return build_hl_owner_call(client, oc, now)
    oc.instrument_type = "DEX_SPOT"
    oc.leverage = None  # spot never has leverage
    return build_spot_owner_call(oc, now)


# ---------------------------------------------------------------------------
# Ledger write (fail-neutral) + light exact-dup guard
# ---------------------------------------------------------------------------

def _row_id(row: dict) -> str:
    key = f"{row.get('ts_utc','')}|{row.get('symbol','')}|{row.get('mint') or ''}|{row.get('side','')}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _is_exact_dup(row: dict) -> bool:
    """Skip only a TRUE accidental re-run: same symbol+side+mint+reason on the
    same settled-close date. Genuine re-entries (different reason/day) are kept
    - owner calls are intentional and must NOT be day-deduped like auto-calls."""
    for prev in _iter_jsonl(LEDGER_PATH):
        if (prev.get("symbol") == row.get("symbol")
                and prev.get("side") == row.get("side")
                and (prev.get("mint") or None) == (row.get("mint") or None)
                and prev.get("reason") == row.get("reason")
                and prev.get("settled_close_date") == row.get("settled_close_date")):
            return True
    return False


def log_owner_call(row: dict) -> bool:
    """Append one owner-call row. FAIL-NEUTRAL: never raises. Returns True iff
    a row was actually written (False on: disabled via env, no usable row, or
    an exact-duplicate guard)."""
    try:
        if not _is_enabled():
            return False
        if not row or not row.get("symbol"):
            return False
        if _is_exact_dup(row):
            return False
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(LEDGER_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        return True
    except Exception as e:  # noqa: BLE001 - deliberate: logging must never break the brief
        print(f"[owner_call] WARNING: failed to log owner call: {e}", file=sys.stderr)
        return False


def format_owner_call(oc: OwnerCall, logged: bool, dry_run: bool) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"=== WAGMI OWNER CALL - {ts} ==="]
    if not oc.ok:
        lines.append(f"NO DATA: {oc.note}")
        lines.append("")
        lines.append(HONESTY_FOOTER)
        return "\n".join(lines)
    lines.extend(oc.brief_lines)
    lines.append("")
    if dry_run:
        lines.append("(DRY RUN - not logged to owner_call_ledger.jsonl)")
    elif logged:
        lines.append("Logged to data/copilot/owner_call_ledger.jsonl for forward-evidence resolution.")
    else:
        lines.append("(Not logged - duplicate of an existing call, or logging disabled.)")
    lines.append("")
    lines.append(HONESTY_FOOTER)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# RESOLVER - stamp forward 1d/7d/30d outcomes onto owner-call rows
# ---------------------------------------------------------------------------

def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _hl_daily_closes(client, symbol: str, start_ms: int, end_ms: int) -> Dict[str, float]:
    try:
        candles = client.candles(symbol, "1d", start_ms, end_ms)
    except Exception as e:  # noqa: BLE001
        print(f"[owner_call] {symbol} HL candle fetch failed: {e}", file=sys.stderr)
        return {}
    out: Dict[str, float] = {}
    for c in candles or []:
        try:
            d = datetime.fromtimestamp(int(c["t"]) / 1000.0, tz=timezone.utc).date().strftime("%Y-%m-%d")
            out[d] = float(c["c"])
        except (KeyError, TypeError, ValueError, OSError, OverflowError):
            continue
    return out


def resolve_owner_calls(now: Optional[datetime] = None) -> dict:
    """Idempotently stamp fwd_1d/7d/30d_pct (RAW close-to-close % move, gross of
    fees - direction/cost applied at analysis time) onto each mature owner-call
    row. Entry-time-safe: anchored on settled_close_date, exact date lookup, no
    look-ahead. HL rows resolve via HL settled candles; DEX-spot rows via the
    mint's micro-cap daily OHLCV CSV. Writes owner_call_ledger_resolved.jsonl.
    NO edge verdict is computed here - just resolve+store (see VERDICT_MIN_N)."""
    now = now or datetime.now(timezone.utc)
    raw_rows = _load_jsonl(LEDGER_PATH)
    resolved = _load_jsonl(RESOLVED_PATH)
    by_id: Dict[str, dict] = {r.get("id"): r for r in resolved if r.get("id")}

    n_resolved_now = 0
    n_immature = 0
    n_bad_anchor = 0
    n_skipped_no_data = 0
    min_h = min(HORIZONS_DAYS)

    # group HL symbols so we fetch each coin's candles once
    hl_pending: Dict[str, List[dict]] = {}
    spot_pending: List[dict] = []
    for raw in raw_rows:
        anchor = _parse_date(raw.get("settled_close_date"))
        entry = raw.get("settled_close")
        if anchor is None or not isinstance(entry, (int, float)) or entry <= 0:
            n_bad_anchor += 1
            continue
        rid = _row_id(raw)
        existing = by_id.get(rid)
        if existing and all(existing.get(f"fwd_{d}d_pct") is not None for d in HORIZONS_DAYS):
            continue
        if now < anchor + timedelta(days=min_h + 1):
            n_immature += 1
            continue
        if raw.get("instrument_type") == "HL_PERP":
            hl_pending.setdefault(raw.get("symbol", ""), []).append(raw)
        else:
            spot_pending.append(raw)

    def _stamp(raw: dict, closes_by_date: Dict[str, float]) -> bool:
        rid = _row_id(raw)
        anchor = _parse_date(raw.get("settled_close_date"))
        entry = float(raw["settled_close"])
        out = dict(by_id.get(rid) or {})
        out.update(raw)
        out["id"] = rid
        changed = False
        for d in HORIZONS_DAYS:
            key = f"fwd_{d}d_pct"
            if out.get(key) is not None:
                continue
            if now < anchor + timedelta(days=d + 1):
                continue
            target = (anchor + timedelta(days=d)).date().strftime("%Y-%m-%d")
            px = closes_by_date.get(target)
            if px is None:
                continue
            out[key] = round((px / entry - 1.0) * 100.0, 4)
            changed = True
        if changed:
            by_id[rid] = out
        return changed

    # HL rows
    if hl_pending:
        client = _get_hl_client()
        for symbol, rows in hl_pending.items():
            anchors = [_parse_date(r.get("settled_close_date")) for r in rows]
            start_ms = int(min(a for a in anchors if a).timestamp() * 1000)
            end_ms = int(now.timestamp() * 1000) + 2 * 86400 * 1000
            closes = _hl_daily_closes(client, symbol, start_ms, end_ms)
            if not closes:
                # Flag rather than skip silently (mirrors resolve_calls.py's
                # posture): an empty HL fetch leaves these rows PENDING, not
                # resolved - do not let a stalled feed look like "no data yet".
                n_skipped_no_data += len(rows)
                print(f"[owner_call] no HL candle data for {symbol} - skipping "
                      f"{len(rows)} row(s) this run (will retry)", file=sys.stderr)
                continue
            for r in rows:
                if _stamp(r, closes):
                    n_resolved_now += 1

    # DEX-spot rows (mint-keyed micro-cap OHLCV)
    for raw in spot_pending:
        mint = raw.get("mint")
        path = _find_ohlcv_day_path(raw.get("symbol", ""), mint) if mint else None
        rows = _read_ohlcv_daily(path)
        if not rows:
            # Flag rather than skip silently: a missing/empty mint OHLCV file
            # means this owner call can NEVER resolve - surface it instead of
            # silently leaving it pending forever (measurement-integrity).
            n_skipped_no_data += 1
            reason = "no OHLCV file for mint" if path is None else f"empty OHLCV file {os.path.basename(path)}"
            print(f"[owner_call] {raw.get('symbol','?')} (mint={mint}): {reason} - "
                  f"cannot resolve this run (will retry)", file=sys.stderr)
            continue
        closes = {d: c for d, c in rows}
        if _stamp(raw, closes):
            n_resolved_now += 1

    resolved_list = sorted(by_id.values(), key=lambda r: r.get("ts_utc", ""))
    if resolved_list:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = RESOLVED_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for r in resolved_list:
                f.write(json.dumps(r, sort_keys=True) + "\n")
        os.replace(tmp, RESOLVED_PATH)

    n_fully = sum(1 for r in resolved_list if all(r.get(f"fwd_{d}d_pct") is not None for d in HORIZONS_DAYS))
    return {
        "total_raw": len(raw_rows),
        "resolved_now": n_resolved_now,
        "resolved_file_rows": len(resolved_list),
        "fully_resolved": n_fully,
        "immature": n_immature,
        "bad_anchor": n_bad_anchor,
        "skipped_no_data": n_skipped_no_data,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run_call(symbol: str, side: str, reason: str, leverage: Optional[float],
             equity: float, risk_pct: float, dry_run: bool) -> str:
    """Build the brief, log the row (unless dry-run), return the printable text."""
    oc = build_owner_call(symbol, side, reason, leverage=leverage, equity=equity, risk_pct=risk_pct)
    logged = False
    if oc.ok and not dry_run:
        logged = log_owner_call(oc.row)
    return format_owner_call(oc, logged, dry_run)


def _main_resolve(argv: list) -> None:
    ap = argparse.ArgumentParser(prog="owner_call.py resolve",
                                 description="stamp forward 1d/7d/30d outcomes onto mature owner-call rows")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    stats = resolve_owner_calls()
    print(
        f"owner-call resolve: total={stats['total_raw']}, resolved_now={stats['resolved_now']}, "
        f"file_rows={stats['resolved_file_rows']}, fully_resolved={stats['fully_resolved']}, "
        f"immature={stats['immature']}, bad_anchor={stats['bad_anchor']}"
        + (f", skipped_no_data={stats['skipped_no_data']}" if stats.get("skipped_no_data") else "")
        + "."
    )
    if not args.quiet and stats["fully_resolved"] < VERDICT_MIN_N:
        print(f"n={stats['fully_resolved']} fully-resolved calls - NO edge verdict below n>={VERDICT_MIN_N} "
              f"(his calls accrue faster than passive discovery, but still need n). Resolve-and-store only.")


def main() -> None:
    # `resolve` is a plain first-arg mode (NOT an argparse subparser - a
    # subparser would swallow the SYMBOL positional). Everything else is a call.
    raw = sys.argv[1:]
    if raw and raw[0] == "resolve":
        _main_resolve(raw[1:])
        return

    ap = argparse.ArgumentParser(
        prog="owner_call.py",
        description="WAGMI Co-Pilot OWNER-CALL: log YOUR discretionary entry + get a risk-amplifier brief "
                    "(HL perps get leverage/liq; DEX-spot memes get size/health). read-only, forward-evidence. "
                    "Use `owner_call.py resolve` to stamp forward outcomes.",
    )
    ap.add_argument("symbol", nargs="?", help="e.g. KITTY, POPCAT, SOL")
    ap.add_argument("side", nargs="?", help="long / short")
    ap.add_argument("reason", nargs="*", help="your read, e.g. reclaimed range low, holders ripping")
    ap.add_argument("--leverage", type=float, default=None, help="HL perps only: your intended leverage (spot ignores this)")
    ap.add_argument("--equity", type=float, default=DEFAULT_EQUITY_USD, help=f"account equity USD (default {DEFAULT_EQUITY_USD:.0f})")
    ap.add_argument("--risk-pct", type=float, default=DEFAULT_RISK_PCT,
                    help=f"%% of equity risked (default {DEFAULT_RISK_PCT}; ceiling {MAX_RISK_PCT_CEILING*100:.1f}%%)")
    ap.add_argument("--dry-run", action="store_true", help="print the brief but do NOT write the ledger row")
    args = ap.parse_args(raw)

    if not args.symbol or not args.side:
        ap.print_help()
        sys.exit(1)
    reason = " ".join(args.reason) if args.reason else ""
    print(run_call(args.symbol, args.side, reason, args.leverage, args.equity, args.risk_pct, args.dry_run))


if __name__ == "__main__":
    main()
