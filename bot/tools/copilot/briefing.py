#!/usr/bin/env python
"""
WAGMI Co-Pilot - MORNING BRIEFING - briefing.py
=============================================================================
ONE composed, scannable daily digest that pulls the co-pilot's already-honest
components into a single message. This is a COMPOSITION layer only - it adds
no new signal, no new math, and no new claim. Every number below is computed
by an existing, already-adversarially-reviewed function elsewhere in
tools/copilot/; this file's only job is picking the highest-signal line out
of each and laying them out so the owner can read the whole thing in ~10
seconds instead of running 4 separate commands.

READ-ONLY / STANDALONE, same constraints as every other tools/copilot/*.py
module: never imports live-bot packages (llm/, execution/, core/,
strategies/), never touches live/.env/data/replay. The only state this file
can touch is an OUTGOING Discord push, and only when --send is passed
explicitly (see SAFETY below) - it never writes to any tools/copilot/*.json
state file (moving_state.json, alert_state.json, call_ledger.jsonl are all
untouched; whats_moving's history is read for OI-delta context but never
persisted back).

REUSE, NOT REIMPLEMENTATION - every section below is existing logic, imported:
  1. HEADER / WEATHER   -> weather.compute_market_weather() (context-only,
                            OOS-refuted as a sizing/direction gate - see that
                            module's docstring). Only the compact regime/
                            breadth20/BTC-vs-EMA fields are printed here, not
                            weather.py's full multi-line CONTEXT paragraph -
                            that verbosity is exactly what this file exists
                            to distill away.
  2. WATCHLIST READS    -> copilot.build_dip_read() (ADD/HOLD/WAIT + why),
                            copilot.compute_liquidation(..., hold_days=5.0)
                            for the horizon-aware multi-day safe leverage +
                            single-day ceiling (see copilot.py's "HORIZON-
                            AWARE LEVERAGE" note - this is the fix that makes
                            a "safe" band actually mean ~4% liq risk at a
                            3-5d hold instead of the old ~25-40%).
                            copilot_alerts.action_bucket() classifies each
                            read into ADD / WAIT_KNIFE / HOLD / WAIT_CHOP /
                            NODATA (the SAME bucket logic the proactive
                            alerter uses) so sorting "actionable first" reuses
                            an existing, already-reviewed classification
                            instead of a second one invented here.
  3. BOOK RISK          -> book.py's own spec parser / correlation /
                            BTC-shock-scenario functions, condensed to the
                            2-3 highest-signal numbers (effective leverage,
                            ~N independent bets, worst-shock liquidation row).
  4. RADAR              -> whats_moving.run_scan() (top-N attention movers;
                            the ~50% next-day hit-rate honesty is already
                            baked into that module and repeated here, not
                            re-derived).
  5. OVERNIGHT LIQS     -> liq_summary.load_events() over
                            data/copilot/liquidations/liq_events.jsonl (the
                            un-backfillable forward-evidence collector -
                            see liq_collector.py's module docstring).

SAFETY - NEVER FIRE A REAL DISCORD PUSH BY ACCIDENT
-----------------------------------------------------------------------------
--send is the ONLY thing that pushes to Discord. Without it, this script
always computes + prints the digest to stdout and does nothing else -
--dry-run is accepted for symmetry with the other cli.py subcommands
(alerts/movers) but is a no-op: the no-push behavior is already the default,
not something --dry-run switches on. (A past test run of a different tool
here once pinged the owner by accident - this file is built so that mistake
requires typing --send, not forgetting a flag.)

CLI:
    python tools/copilot/briefing.py --equity 5000
    python tools/copilot/briefing.py --symbols BTC,SOL,POPCAT
    python tools/copilot/briefing.py --book "SOL long 5x 1200; POPCAT long 3x 400"
    python tools/copilot/briefing.py --send            # REAL Discord push
    python tools/copilot/cli.py brief --equity 5000     # via the unified CLI
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from copilot import (  # noqa: E402
    BOT_DIR,
    DEFAULT_SIDE,
    MAX_HOLD_DAYS_RANGE,
    _get_hl_client,
    build_dip_read,
    compute_liquidation,
    fetch_hl_max_leverage,
)
from copilot_alerts import action_bucket  # noqa: E402 - reuse the SAME ADD/WAIT_KNIFE/HOLD/WAIT_CHOP/NODATA bucket the proactive alerter uses, no second classification
from weather import compute_market_weather, session_vol_context  # noqa: E402

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
# Same 9-coin watchlist as liq_collector.WATCHLIST / run_copilot_daily.ps1
# (kept as a plain literal here, not imported from liq_collector.py, so this
# read-only digest never pulls in that module's `websockets` dependency just
# for a constant list).
DEFAULT_SYMBOLS = ["BTC", "SOL", "POPCAT", "WIF", "FARTCOIN", "PENGU", "kPEPE", "kBONK", "kSHIB"]

BRIEFING_DEFAULT_EQUITY_USD = 5000.0   # owner's real approx account size (book.py uses the same default)
MOVERS_TOP_N = 5                        # "top 3-5 movers" per the brief spec
LIQ_LOOKBACK_HOURS = 24.0

# This brief explicitly commits to the 3-5 day RISK PLAN hold window (see
# copilot.py "HORIZON-AWARE LEVERAGE") - use the conservative/upper end (5d),
# the SAME convention copilot.py's own format_range_block/compute_risk_plan
# use for their horizon-aware probes.
HOLD_DAYS = MAX_HOLD_DAYS_RANGE[1]

_BUCKET_PRIORITY = {"ADD": 0, "WAIT_KNIFE": 1, "HOLD": 2, "WAIT_CHOP": 3, "NODATA": 4}

MORNING_BRIEFING_FOOTER = (
    "Discipline + attention aid, NOT a proven alpha edge: the ADD/WAIT read is a mild measured "
    "timing tilt (not a buy signal), weather + radar are context/attention only (no directional "
    "edge), and book risk is arithmetic/correlation measurement, not a forecast. The entry "
    "decision is yours."
)


# ---------------------------------------------------------------------------
# Section 1: HEADER / WEATHER - compact one-liner (not weather.py's full
# multi-paragraph CONTEXT block; that's exactly the verbosity this digest
# exists to distill).
# ---------------------------------------------------------------------------

def build_weather_line(mw) -> str:
    if not mw.ok:
        return f"WEATHER: unavailable ({mw.data_note})."
    regime_disp = mw.regime.replace("_", " ")
    breadth_bit = f"breadth20={mw.breadth_pct:.0f}%" if mw.breadth_pct is not None else "breadth n/a"
    if mw.btc_above_ema50 is None:
        btc_bit = "BTC-EMA n/a"
    else:
        btc_bit = "BTC>50dEMA" if mw.btc_above_ema50 else "BTC<50dEMA"
    return (
        f"WEATHER: {regime_disp} ({breadth_bit}, {btc_bit}) - "
        f"volatility context only, NOT a sizing/direction call."
    )


# ---------------------------------------------------------------------------
# Section 2: WATCHLIST READS - one (or two, for actionable coins) lines per
# symbol, sorted actionable-first.
# ---------------------------------------------------------------------------

def _short_reason(text: Optional[str], max_len: int = 115) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(" ", 1)[0] + "..."


def build_watchlist_rows(client, symbols: List[str], side: str = DEFAULT_SIDE) -> List[str]:
    scored: List[tuple] = []
    for sym in symbols:
        dip = build_dip_read(client, sym)
        bucket = action_bucket(dip)
        if not dip.ok:
            scored.append((_BUCKET_PRIORITY.get(bucket, 5), f"{sym:<9} NO DATA - {dip.data_note}"))
            continue

        hl_max_lev = fetch_hl_max_leverage(client, sym)
        # leverage=1.0 probe: safe_max_leverage / single_day_safe_max_leverage
        # are independent of the probe leverage - see compute_liquidation's
        # own docstring. Same reuse pattern as copilot.py's horizon_probe in
        # format_range_block / compute_risk_plan.
        liq = compute_liquidation(dip.price, side, 1.0, dip.vol, hl_max_lev, sym, hold_days=HOLD_DAYS)

        if liq.horizon_used is not None and liq.single_day_safe_max_leverage is not None:
            lev_bit = (
                f"safe lev {liq.horizon_used:.0f}d <= {liq.safe_max_leverage:.1f}x "
                f"(1d ceiling {liq.single_day_safe_max_leverage:.1f}x)"
            )
        else:
            lev_bit = f"safe lev (1d only, thin history) <= {liq.safe_max_leverage:.1f}x"

        action_disp = {"WAIT_KNIFE": "WAIT (knife)", "WAIT_CHOP": "WAIT (chop)"}.get(bucket, dip.action)
        line = f"{sym:<9} {action_disp:<14} @ ${dip.price:,.4f} | {lev_bit}"
        if bucket in ("ADD", "WAIT_KNIFE"):
            line += f"\n          {_short_reason(dip.action_reason)}"
        scored.append((_BUCKET_PRIORITY.get(bucket, 5), line))

    scored.sort(key=lambda t: t[0])  # stable sort: actionable buckets first, original order preserved within a bucket
    return [line for _, line in scored]


# ---------------------------------------------------------------------------
# Section 3: BOOK RISK (optional) - condensed from book.py's own functions.
# ---------------------------------------------------------------------------

def build_book_section(client, book_spec: str, equity: float) -> List[str]:
    from book import (  # local import: only needed when --book is passed
        BOOK_DEFAULT_HISTORY_DAYS,
        BOOK_DEFAULT_SHOCKS_PCT,
        build_return_frame,
        compute_effective_positions,
        compute_scenarios,
        parse_book_spec,
    )
    from pretrade import build_trade_card  # local import: same reason

    try:
        specs = parse_book_spec(book_spec)
    except ValueError as e:
        return [f"BOOK RISK: invalid --book spec: {e}"]

    cards = [build_trade_card(client, sym, side, lev, margin) for (sym, side, lev, margin) in specs]
    total_notional = sum(margin * lev for (_sym, _side, lev, margin) in specs)
    eff_leverage = (total_notional / equity) if equity > 0 else float("nan")

    universe = sorted(set([c.symbol for c in cards] + ["BTC"]))
    frame, _notes = build_return_frame(client, universe, BOOK_DEFAULT_HISTORY_DAYS)

    positions_for_corr = [(c.symbol, c.side) for c in cards if c.ok]
    n_eff: Optional[float] = None
    if len(positions_for_corr) > 1:
        _avg_signed, n_eff, _missing = compute_effective_positions(frame, positions_for_corr)
    elif positions_for_corr:
        n_eff = 1.0

    lines = [
        f"BOOK RISK ({len(cards)} position(s)): effective leverage {eff_leverage:.2f}x on ${equity:,.0f} equity"
        + (f", ~{n_eff:.1f} independent bet(s)" if n_eff is not None else "")
    ]

    scenarios = compute_scenarios(cards, frame, list(BOOK_DEFAULT_SHOCKS_PCT))
    if scenarios:
        worst = max(scenarios, key=lambda s: abs(s.shock_pct))
        liq_bit = ", ".join(worst.liquidated) if worst.liquidated else "nothing"
        lines.append(
            f"  Worst shock ({worst.shock_pct:+.0f}% BTC): liquidates {liq_bit} | "
            f"est. margin remaining ${worst.margin_remaining_usd:,.0f} of ${worst.margin_intended_usd:,.0f}"
        )
    lines.append("  (arithmetic/correlation risk view, not a prediction - see `cli.py book` for the full breakdown)")
    return lines


# ---------------------------------------------------------------------------
# Section 4: RADAR - top movers, attention only.
# ---------------------------------------------------------------------------

def build_radar_section(client, watch_symbols: List[str], top_n: int = MOVERS_TOP_N) -> List[str]:
    from whats_moving import CANDLE_STAGE_POOL, load_state, run_scan  # local import

    # Read-only use of whats_moving's own state (OI-delta history context) -
    # deliberately never saved back here (no save_state call): this digest
    # must not mutate movers.py's own dedup/history state.
    state = load_state()
    history = state.get("history", {})

    ranked, _rejects, _total = run_scan(client, top_n, CANDLE_STAGE_POOL, history)
    lines = ["RADAR (attention only, ~50% next-day hit-rate OOS - NOT a directional signal):"]
    if not ranked:
        lines.append("  no movers cleared the liquidity floor this run.")
        return lines

    for i, row in enumerate(ranked[:top_n], 1):
        sym = row["symbol"]
        pct = row.get("pct_24h")
        pct_s = f"{pct:+.1f}%/24h" if pct is not None else "24h n/a"
        flags = row.get("flags") or []
        flag_bit = f"  [{', '.join(flags)}]" if flags else ""
        owner_bit = "  [OWNER COIN]" if sym in watch_symbols else ""
        lines.append(f"  {i}. {sym:<10} {pct_s:>10} (score {row['score']:.0f}){flag_bit}{owner_bit}")
    return lines


# ---------------------------------------------------------------------------
# Section 5: OVERNIGHT LIQUIDATIONS - from the un-backfillable collector.
# ---------------------------------------------------------------------------

def build_liquidations_section(watch_symbols: List[str], lookback_hours: float = LIQ_LOOKBACK_HOURS) -> List[str]:
    from liq_summary import DEFAULT_PATH, load_events  # local import

    rows = load_events(DEFAULT_PATH)
    if not rows:
        return ["OVERNIGHT LIQUIDATIONS: quiet (collector has captured no events yet)."]

    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    recent = []
    for r in rows:
        ts = r.get("ts_utc")
        try:
            t = datetime.fromisoformat(ts) if ts else None
        except ValueError:
            t = None
        if t is None:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t >= cutoff:
            recent.append(r)

    if not recent:
        return [f"OVERNIGHT LIQUIDATIONS: quiet (no events in the last {lookback_hours:.0f}h)."]

    total_notional = sum(r.get("notional_usd") or 0.0 for r in recent)
    biggest = max(recent, key=lambda r: r.get("notional_usd") or 0.0)
    watch_hit = sorted({r.get("symbol") for r in recent if r.get("symbol") in watch_symbols})
    watch_bit = ", ".join(watch_hit) if watch_hit else "none"
    return [
        f"OVERNIGHT LIQUIDATIONS ({lookback_hours:.0f}h): {len(recent)} event(s), ${total_notional:,.0f} notional | "
        f"biggest: {biggest.get('symbol')} {biggest.get('side')} ${biggest.get('notional_usd', 0):,.0f} "
        f"({biggest.get('venue')}) | watchlist coins hit: {watch_bit}"
    ]


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def format_briefing(client, symbols: List[str], equity: float, book_spec: Optional[str] = None) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"WAGMI MORNING BRIEFING - {ts}", ""]

    mw = compute_market_weather(client)
    lines.append(build_weather_line(mw))
    lines.append(session_vol_context(datetime.now(timezone.utc).hour))
    lines.append("")

    lines.append("WATCHLIST:")
    lines.extend(build_watchlist_rows(client, symbols))
    lines.append("")

    if book_spec:
        lines.extend(build_book_section(client, book_spec, equity))
        lines.append("")

    lines.extend(build_radar_section(client, symbols))
    lines.append("")

    lines.extend(build_liquidations_section(symbols))
    lines.append("")

    lines.append(MORNING_BRIEFING_FOOTER)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _normalize_symbol(s: str) -> str:
    """Uppercases a symbol EXCEPT HL's lowercase-k 1000x-denominated meme
    convention (kPEPE, kBONK, kSHIB - NOT ccxt's KPEPE; confirmed live -
    HLNative's candle fetch 500s on the all-caps form). market_collector.py
    and liq_collector.py hardcode this exact casing already; this just makes
    --symbols robust to however the owner types it (kpepe/KPEPE/kPEPE all
    normalize to the one HL actually accepts)."""
    s = s.strip()
    if len(s) > 1 and s[0].lower() == "k" and s[1:].isalpha():
        return "k" + s[1:].upper()
    return s.upper()


def _parse_symbols(raw: str) -> List[str]:
    syms = [_normalize_symbol(s) for s in raw.split(",") if s.strip()]
    return syms or list(DEFAULT_SYMBOLS)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="WAGMI Morning Briefing - one composed, scannable daily digest over the co-pilot's "
                    "existing components (read-only w.r.t. the live bot; NEVER pushes to Discord unless --send)."
    )
    ap.add_argument("--symbols", type=str, default=",".join(DEFAULT_SYMBOLS), help="Comma-separated watchlist (default: the 9-coin owner watchlist)")
    ap.add_argument("--equity", type=float, default=BRIEFING_DEFAULT_EQUITY_USD, help=f"Account equity in USD (default {BRIEFING_DEFAULT_EQUITY_USD:.0f})")
    ap.add_argument("--book", type=str, default=None, help='Optional held-book spec (book.py grammar): "SYM SIDE LEVx MARGIN; SYM SIDE LEVx MARGIN; ..." - adds a BOOK RISK section')
    ap.add_argument("--dry-run", action="store_true", help="No-op flag, kept for symmetry with `cli.py alerts`/`cli.py movers` - print-only is already the default without --send")
    ap.add_argument("--send", action="store_true", help="Push the digest to Discord via WAGMI_DISCORD_WEBHOOK. Without this flag: compute + print to stdout only, NEVER push.")
    args = ap.parse_args()

    symbols = _parse_symbols(args.symbols)
    client = _get_hl_client()

    digest = format_briefing(client, symbols, args.equity, args.book)
    print(digest)

    if args.send:
        tools_dir = os.path.join(BOT_DIR, "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        from discord_notify import send_discord  # local import: only needed on a real send
        ok = send_discord(digest, title="WAGMI Morning Briefing")
        print(f"\n[SEND] Discord push {'sent' if ok else 'FAILED'}")
    else:
        print("\n[DRY RUN] no Discord push sent (pass --send to push for real).")


if __name__ == "__main__":
    main()
