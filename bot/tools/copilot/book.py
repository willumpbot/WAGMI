#!/usr/bin/env python
"""
WAGMI Co-Pilot - PORTFOLIO RISK VIEW - book.py
=============================================================================
The biggest uncaptured risk for a 3-15x leveraged meme trader is CORRELATED
exposure: per-coin guardrails (copilot.py's liquidation brief, pretrade.py's
fee card) each look at ONE position in isolation. Three "different" longs
that are 70-90% correlated to each other aren't three independent bets -
they're closer to one bet, sized three times over. This module is the
BOOK-LEVEL view that makes that visible.

READ-ONLY / STANDALONE, same constraints as copilot.py/pretrade.py: only
imports copilot.py's and pretrade.py's public fetch/liquidation/trade-card
functions (no duplicated math), plus the already-collected longtail OHLC
CSVs for co-movement history. Never imports live-bot packages (llm/,
execution/, core/, strategies/), never writes to data/replay/, .env, or any
live-bot state file, never pushes to Discord.

WHAT THIS IS NOT: a prediction of what BTC or any coin will do. Every number
below is ARITHMETIC (fee/liq math already in copilot.py) or a MEASUREMENT of
historical co-movement (correlation/beta) used for RISK SIZING, exactly the
same "measure, don't predict" posture as the rest of the co-pilot. See the
HONESTY footer at the bottom of every book.

CLI:
    python tools/copilot/cli.py book "SOL long 5x 1200; POPCAT long 3x 400; BTC long 10x 2000"
    python tools/copilot/cli.py book "SOL long 5x 1200" --equity 8000
    python tools/copilot/cli.py book "..." --shocks 5,10,15,25 --history-days 120

    (This file can also be run directly: python tools/copilot/book.py "...")

SPEC FORMAT: semicolon-separated positions, each in pretrade.py's own
"SYMBOL SIDE LEVERAGEx MARGIN_USD" grammar (reuses parse_trade_spec() - no
second parser). e.g. "SOL long 5x 1200; POPCAT long 3x 400; BTC long 10x 2000".

WHAT EACH SECTION MEASURES
---------------------------
1. PER-POSITION lines - notional (pure spec arithmetic: margin x leverage,
   always shown even if live data fails), liq price + distance and funding
   $/day (both reused straight from pretrade.py's build_trade_card(), which
   itself reuses copilot.py's compute_liquidation() - no re-derivation).
2. BOOK AGGREGATES - total notional/margin (spec-level, always available),
   EFFECTIVE ACCOUNT LEVERAGE = total notional / --equity (default $5,000),
   and net funding $/day signed across the book (PAY positive, EARN negative).
3. CORRELATION-ADJUSTED EXPOSURE - a pairwise correlation matrix of daily
   returns (longtail CSVs in data/longtail/ohlc/ where available, falling
   back to a live HL fetch via copilot.py's own fetch_ohlc() for symbols the
   longtail set doesn't cover, e.g. BTC/SOL/POPCAT), then a SIGNED-by-side
   average pairwise correlation (a long+long pair uses the raw correlation;
   a long+short pair flips its sign, since an inverse position in a
   correlated asset partially HEDGES rather than compounds the book's risk)
   collapsed into "N positions are effectively ~X independent positions of
   risk" via N_eff = N / (1 + (N-1)*avg_signed_corr). This is a standard
   diversification-ratio heuristic for RISK SIZING, not a forecast of any
   coin's return. Symbols with insufficient history are named and excluded.
4. BTC SHOCK SCENARIOS - for each --shocks magnitude (default -5/-10/-15%),
   each position is moved by shock% x its own historical BETA-to-BTC (beta=1
   for BTC itself; beta defaults to 1.0 with a note if there isn't enough
   overlapping history to measure it), producing a book P&L, a list of which
   positions cross their OWN already-computed liq_price at that shock, and
   the book's estimated remaining margin. This is the single most useful
   number in the file: "if BTC drops 15% overnight, here's your book."
5. VERDICT - one honest plain-language line (effective leverage + the
   worst-shock liquidation set + the diversification read) plus a footer
   that repeats, explicitly, that this is arithmetic/correlation-based risk
   measurement, NOT a prediction.

LIMITATIONS (said once, plainly, here rather than buried in a footnote):
  - Assumes each position was opened at TODAY's price (no entry price is in
    the spec grammar) - the same assumption pretrade.py's card already makes
    for its own liquidation math; this module does not add a new one.
  - Beta/correlation are estimated from daily-close returns over
    --history-days (default 150, i.e. within the 90-180d window this feature
    was scoped to) - a backward-looking measurement, not a forward guarantee
    that co-movement holds during an actual shock. QUANTIFIED (corr_stress_test.py,
    2026-07-31): avg alt correlation rises ~0.51 calm -> ~0.73 in high-vol stress
    (bootstrap-significant z=2.40, era-stable, 98%+ of pairs), collapsing a
    3-position book's ~1.5 independent bets to ~1.2 - so this is a measurably
    optimistic floor. (Note: the naive "worst BTC day" definition is NOT robust -
    a single -14% day drives it; the high-realized-vol definition is the stable one.)
  - Scenario liquidation ignores cross-margin interaction between positions
    (each position's margin is treated in isolation, same isolated-margin
    approximation compute_liquidation() already uses) and funding accrual.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from copilot import (  # noqa: E402
    BOT_DIR,
    _get_hl_client,
    fetch_ohlc,
)
from pretrade import (  # noqa: E402
    TradeCard,
    build_trade_card,
    parse_trade_spec,
)

LONGTAIL_OHLC_DIR = os.path.join(BOT_DIR, "data", "longtail", "ohlc")

BOOK_DEFAULT_EQUITY_USD = 5000.0     # owner's real approx account size
BOOK_DEFAULT_HISTORY_DAYS = 150      # within the 90-180d scope for correlation/beta
BOOK_DEFAULT_SHOCKS_PCT = (-5.0, -10.0, -15.0)  # BTC downside shock scenarios
MIN_RETURN_ROWS = 10                 # below this, correlation/beta is too noisy to show

HONESTY_FOOTER = (
    "Arithmetic + correlation-based risk view, NOT a prediction of what BTC or any coin "
    "will do. Correlation/beta are backward-looking co-movement measurements for SIZING, "
    "not an edge. And they UNDERSTATE stress risk: on this universe's own history, avg "
    "alt-pairwise correlation rises from ~0.51 in calm conditions to ~0.73 in high-volatility "
    "stress (bootstrap-significant, era-stable, holds for 98%+ of coin pairs) - so a "
    "3-position same-side book's ~1.5 'independent bets' collapses to ~1.2 exactly when it "
    "matters. Treat the calm-window number above as an optimistic floor and size for the "
    "stressed one."
)


# ---------------------------------------------------------------------------
# Spec parsing - reuses pretrade.py's own per-position grammar, just splits
# the book string on ";" first.
# ---------------------------------------------------------------------------

def parse_book_spec(raw: str) -> List[Tuple[str, str, float, float]]:
    """Parses 'SYM SIDE LEVx MARGIN; SYM SIDE LEVx MARGIN; ...' into a list of
    (symbol, side, leverage, margin_usd) tuples, one per ";"-separated chunk,
    via pretrade.parse_trade_spec() (no second parser). Raises ValueError
    with a clear message identifying which chunk failed - callers should
    catch this and print usage, not let it traceback into the CLI user."""
    if not raw or not raw.strip():
        raise ValueError(
            'empty book spec; expected "SYMBOL SIDE LEVERAGEx MARGIN_USD; SYMBOL SIDE LEVERAGEx MARGIN_USD; ...", '
            'e.g. "SOL long 5x 1200; POPCAT long 3x 400"'
        )
    chunks = [c.strip() for c in raw.split(";") if c.strip()]
    if not chunks:
        raise ValueError(f"no positions found in book spec {raw!r} (nothing between the ';' separators)")
    positions: List[Tuple[str, str, float, float]] = []
    for chunk in chunks:
        try:
            positions.append(parse_trade_spec(chunk))
        except ValueError as e:
            raise ValueError(f"bad position {chunk!r}: {e}")
    return positions


# ---------------------------------------------------------------------------
# Return-history loading - longtail CSV first (already-collected co-movement
# data, legitimate reuse for RISK sizing), live HL fetch fallback for symbols
# the longtail set doesn't cover (majors like BTC/SOL, or POPCAT).
# ---------------------------------------------------------------------------

def _load_longtail_returns(symbol: str, days: int) -> Optional[pd.Series]:
    path = os.path.join(LONGTAIL_OHLC_DIR, f"{symbol}_1d.csv")
    if not os.path.isfile(path):
        return None
    try:
        df = pd.read_csv(path)
        if "c" not in df.columns:
            return None
        if "dt_utc_iso" in df.columns:
            dates = pd.to_datetime(df["dt_utc_iso"], errors="coerce", utc=True).dt.date
        elif "open_time_ms" in df.columns:
            dates = pd.to_datetime(df["open_time_ms"], unit="ms", errors="coerce", utc=True).dt.date
        else:
            return None
        df = df.assign(_date=dates).dropna(subset=["_date", "c"]).sort_values("_date")
        if days:
            df = df.tail(days + 1)  # +1 row so pct_change yields `days` return rows
        ret = df.set_index("_date")["c"].astype(float).pct_change().dropna() * 100.0
        return ret if len(ret) >= MIN_RETURN_ROWS else None
    except Exception:
        return None


def _load_live_returns(client, symbol: str, days: int) -> Optional[pd.Series]:
    df = fetch_ohlc(client, symbol, "1d", days + 5)  # +5 buffer for gaps
    if df is None or len(df) < MIN_RETURN_ROWS + 1:
        return None
    df = df.assign(_date=df["t"].dt.date)
    ret = df.set_index("_date")["c"].astype(float).pct_change().dropna() * 100.0
    if days:
        ret = ret.tail(days)  # honor --history-days the SAME way the longtail path does
    return ret if len(ret) >= MIN_RETURN_ROWS else None


def load_symbol_returns(client, symbol: str, days: int) -> Tuple[Optional[pd.Series], str]:
    """Returns (daily-return-series-or-None, source-note). Tries the longtail
    CSV first, falls back to a live HL fetch (copilot.py's own fetch_ohlc()
    - no duplicated fetch logic) for symbols the longtail set doesn't cover."""
    s = _load_longtail_returns(symbol, days)
    if s is not None:
        return s, "longtail CSV"
    s = _load_live_returns(client, symbol, days)
    if s is not None:
        return s, "live HL fetch"
    return None, "insufficient history"


def build_return_frame(client, symbols: List[str], days: int) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """symbols should include every held symbol PLUS 'BTC' (added by the
    caller if not already held) since the scenario table needs BTC's own
    return series to compute every other symbol's beta-to-BTC."""
    series: Dict[str, pd.Series] = {}
    notes: Dict[str, str] = {}
    for sym in symbols:
        s, note = load_symbol_returns(client, sym, days)
        notes[sym] = note
        if s is not None:
            series[sym] = s
    frame = pd.DataFrame(series) if series else pd.DataFrame()
    return frame, notes


def compute_beta_to_btc(frame: pd.DataFrame, symbol: str, btc_col: str = "BTC") -> Optional[float]:
    if symbol == btc_col:
        return 1.0
    if symbol not in frame.columns or btc_col not in frame.columns:
        return None
    sub = frame[[symbol, btc_col]].dropna()
    if len(sub) < MIN_RETURN_ROWS:
        return None
    var = sub[btc_col].var()
    if not var or var <= 1e-12:
        return None
    return float(sub[symbol].cov(sub[btc_col]) / var)


def compute_effective_positions(
    frame: pd.DataFrame, positions: List[Tuple[str, str]]
) -> Tuple[Optional[float], Optional[float], List[str]]:
    """positions: list of (symbol, side). Returns (avg_signed_corr, n_eff,
    missing_symbols). Signs a pair's correlation by side (long*long=+1,
    short*short=+1, long*short=-1) - an inverse position in a correlated
    asset partially HEDGES the book rather than compounding it, so it pulls
    N_eff UP toward the raw position count (capped at N - you can't have more
    independent bets than positions). Iterates over POSITIONS, not unique
    symbols, so multiple tranches of the same coin (e.g. two SOL longs) are
    handled: a symbol with itself is correlation 1.0 (fully stacked)."""
    syms = [p[0] for p in positions]
    sides = [1.0 if p[1].upper() in ("LONG", "BUY") else -1.0 for p in positions]
    present_idx = [i for i, s in enumerate(syms) if s in frame.columns]
    missing = list(dict.fromkeys(s for s in syms if s not in frame.columns))
    n = len(present_idx)
    if n <= 1:
        return None, (1.0 if n == 1 else None), missing
    # Build the correlation matrix over UNIQUE present symbols (duplicate column
    # labels would make corr.loc[a, a] return a DataFrame, not a scalar).
    unique_present = list(dict.fromkeys(syms[i] for i in present_idx))
    corr = frame[unique_present].corr(min_periods=MIN_RETURN_ROWS)
    pairs = []
    for ii in range(len(present_idx)):
        for jj in range(ii + 1, len(present_idx)):
            i, j = present_idx[ii], present_idx[jj]
            a, b = syms[i], syms[j]
            c = 1.0 if a == b else corr.loc[a, b]  # same coin = fully correlated
            if pd.notna(c):
                pairs.append(float(c) * sides[i] * sides[j])
    if not pairs:
        return None, None, missing
    avg_signed = float(np.mean(pairs))
    n_eff = float(np.clip(n / (1.0 + (n - 1) * avg_signed), 1.0, n))
    return avg_signed, n_eff, missing


# ---------------------------------------------------------------------------
# BTC shock scenarios - pure arithmetic reuse of each card's already-computed
# compute_liquidation() result; only the beta-implied shocked price is new.
# ---------------------------------------------------------------------------

@dataclass
class ScenarioResult:
    shock_pct: float
    book_pnl_usd: float
    liquidated: List[str]
    margin_remaining_usd: float
    margin_intended_usd: float
    beta_notes: List[str]


def compute_scenarios(cards: List[TradeCard], frame: pd.DataFrame, shocks_pct: List[float]) -> List[ScenarioResult]:
    results = []
    for shock in shocks_pct:
        book_pnl = 0.0
        liquidated: List[str] = []
        margin_remaining = 0.0
        margin_intended = 0.0
        beta_notes: List[str] = []
        for c in cards:
            margin_intended += c.margin_usd
            if not c.ok or c.liq is None:
                continue
            beta = compute_beta_to_btc(frame, c.symbol)
            beta_used = beta if beta is not None else 1.0
            if beta is None:
                beta_notes.append(f"{c.symbol} beta unknown - assumed 1:1 with BTC")
            move = (shock / 100.0) * beta_used
            new_price = c.entry_price * (1.0 + move)
            is_long = c.side in ("LONG", "BUY")
            pnl = c.notional_usd * move if is_long else -c.notional_usd * move
            is_liq = (new_price <= c.liq.liq_price) if is_long else (new_price >= c.liq.liq_price)
            # Isolated margin: once liquidated you lose the posted margin and no
            # more - cap the P&L there so the book total can't claim a loss
            # larger than the capital actually at risk (which contradicts the
            # "margin remaining $0" printed on the same line).
            if is_liq:
                pnl = -c.margin_usd
            remaining = 0.0 if is_liq else max(c.margin_usd + pnl, 0.0)
            book_pnl += pnl
            margin_remaining += remaining
            if is_liq:
                liquidated.append(c.symbol)
        results.append(ScenarioResult(
            shock_pct=shock, book_pnl_usd=book_pnl, liquidated=liquidated,
            margin_remaining_usd=margin_remaining, margin_intended_usd=margin_intended,
            beta_notes=beta_notes,
        ))
    return results


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

def format_book(
    cards: List[TradeCard], frame: pd.DataFrame, equity: float,
    shocks_pct: List[float], history_days: int,
) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"WAGMI PORTFOLIO RISK VIEW (book) - {ts}", ""]

    valid = [c for c in cards if c.ok]
    failed = [c for c in cards if not c.ok]

    # ---- 1. Per-position lines ----
    lines.append(f"POSITIONS ({len(cards)}):")
    for c in cards:
        notional = c.margin_usd * c.leverage
        if not c.ok:
            lines.append(
                f"  {c.symbol} {c.side} {c.leverage:.1f}x ${c.margin_usd:,.0f} margin "
                f"(${notional:,.0f} notional) - NO DATA: {c.data_note}"
            )
            continue
        liq = c.liq
        if c.funding_available and c.funding_direction != "FLAT":
            verb = "pays" if c.funding_direction == "PAY" else "earns"
            fund_bit = f"funding {verb} ~${c.funding_daily_usd:,.2f}/day"
        elif c.funding_available:
            fund_bit = "funding ~flat"
        else:
            fund_bit = "funding n/a"
        lines.append(
            f"  {c.symbol} {c.side} {c.leverage:.1f}x ${c.margin_usd:,.0f} margin "
            f"(${notional:,.0f} notional) | liq ${liq.liq_price:.4f} ({liq.distance_pct*100:.1f}% away) "
            f"[{liq.risk_label}] | {fund_bit}"
        )
    lines.append("")

    # ---- 2. Book aggregates ----
    total_notional = sum(c.margin_usd * c.leverage for c in cards)
    total_margin = sum(c.margin_usd for c in cards)
    eff_leverage = (total_notional / equity) if equity > 0 else float("nan")
    net_funding = sum(
        (c.funding_daily_usd if c.funding_direction == "PAY" else -c.funding_daily_usd if c.funding_direction == "EARN" else 0.0)
        for c in valid if c.funding_available
    )
    lines.append("BOOK AGGREGATES:")
    lines.append(
        f"  Total notional: ${total_notional:,.0f}  |  Total margin used: ${total_margin:,.0f}  |  "
        f"Account equity: ${equity:,.0f}"
    )
    lines.append(f"  EFFECTIVE ACCOUNT LEVERAGE: {eff_leverage:.2f}x  (total notional / equity)")
    net_dir = "net PAYS" if net_funding > 1e-9 else ("net EARNS" if net_funding < -1e-9 else "~flat")
    lines.append(f"  Net funding: {net_dir} ~${abs(net_funding):,.2f}/day across the book")
    if failed:
        lines.append(
            f"  ({len(failed)} position(s) excluded from live-data aggregates (funding/liq) - "
            f"no price data: {', '.join(c.symbol for c in failed)})"
        )
    lines.append("")

    # ---- 3. Correlation-adjusted exposure ----
    lines.append(
        f"CORRELATION-ADJUSTED EXPOSURE (co-movement of daily returns, ~{history_days}d lookback - "
        f"RISK SIZING measurement, NOT a prediction):"
    )
    positions_for_corr = [(c.symbol, c.side) for c in valid]
    avg_signed, n_eff = None, None
    if len(positions_for_corr) <= 1:
        lines.append("  Single position (or none) - no correlated exposure to measure.")
        n_eff = float(len(positions_for_corr))
    else:
        pres_syms = [c.symbol for c in valid if c.symbol in frame.columns]
        missing = list(dict.fromkeys(c.symbol for c in valid if c.symbol not in frame.columns))
        unique_present = list(dict.fromkeys(pres_syms))  # dedupe: matrix is per-symbol
        if len(pres_syms) >= 2:
            avg_signed, n_eff, _ = compute_effective_positions(frame, positions_for_corr)
            if len(unique_present) >= 2:
                corr = frame[unique_present].corr(min_periods=MIN_RETURN_ROWS)
                lines.append("  Pairwise correlation of daily returns:")
                header = "        " + "".join(f"{s:>10}" for s in unique_present)
                lines.append(f"    {header}")
                for a in unique_present:
                    row = "".join(
                        f"{corr.loc[a, b]:10.2f}" if pd.notna(corr.loc[a, b]) else f"{'n/a':>10}"
                        for b in unique_present
                    )
                    lines.append(f"    {a:>7}{row}")
                if len(unique_present) < len(pres_syms):
                    lines.append("    (same-symbol tranches are treated as fully correlated with each other.)")
            else:
                lines.append("  All positions here are the same symbol - fully correlated (one directional bet).")
            if avg_signed is not None and n_eff is not None:
                lines.append(
                    f"  Avg side-signed pairwise correlation: {avg_signed:+.2f} -> your {len(pres_syms)} "
                    f"position(s) here are effectively ~{n_eff:.1f} independent position(s) of risk "
                    f"(N/(1+(N-1)*avg_corr); a positive value here means the correlated ones stack risk "
                    f"instead of diversifying it)."
                )
        else:
            lines.append("  Not enough overlapping-history symbols to build a correlation matrix.")
        if missing:
            lines.append(f"  No usable history for: {', '.join(missing)} - excluded from the matrix above.")
    lines.append("")

    # ---- 4. BTC shock scenarios ----
    lines.append("BTC SHOCK SCENARIOS (each position moved by shock% x its own beta-to-BTC; arithmetic stress test, NOT a forecast):")
    # Pass ALL cards (not just `valid`) so the scenario's margin denominator
    # matches "Total margin used" above - failed positions add to margin posted
    # but contribute $0 remaining (we can't model them), which is the honest read.
    scenarios = compute_scenarios(cards, frame, shocks_pct)
    seen_beta_notes = set()
    for sc in scenarios:
        liq_bit = ", ".join(sc.liquidated) if sc.liquidated else "none"
        lines.append(
            f"  BTC {sc.shock_pct:+.0f}%: book P&L ${sc.book_pnl_usd:+,.0f}  |  liquidated: {liq_bit}  |  "
            f"est. margin remaining: ${sc.margin_remaining_usd:,.0f} of ${sc.margin_intended_usd:,.0f}"
        )
        for n in sc.beta_notes:
            if n not in seen_beta_notes:
                seen_beta_notes.add(n)
    if seen_beta_notes:
        lines.append(f"  ({'; '.join(sorted(seen_beta_notes))})")
    if failed:
        lines.append(f"  (positions with no data excluded from scenarios: {', '.join(c.symbol for c in failed)})")
    lines.append("")

    # ---- 5. Verdict ----
    lines.append("VERDICT:")
    bits = [f"Effective leverage {eff_leverage:.1f}x on ${equity:,.0f} equity."]
    worst = scenarios[-1] if scenarios else None
    if worst is not None:
        if worst.liquidated:
            bits.append(f"A {worst.shock_pct:+.0f}% BTC day liquidates {', '.join(worst.liquidated)}.")
        else:
            bits.append(f"No position liquidates even at the {worst.shock_pct:+.0f}% BTC scenario shown.")
    if n_eff is not None and len(positions_for_corr) > 1:
        conc = "more concentrated than" if n_eff < len(positions_for_corr) - 1e-9 else "about as concentrated as"
        bits.append(
            f"Your {len(positions_for_corr)} positions are ~{n_eff:.1f} independent bets - "
            f"you're {conc} the position count alone suggests."
        )
    lines.append("  " + " ".join(bits))
    lines.append("")
    lines.append(HONESTY_FOOTER)

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_shocks(raw: str) -> List[float]:
    try:
        vals = [float(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(f"--shocks must be comma-separated numbers, got {raw!r}")
    if not vals:
        raise argparse.ArgumentTypeError(f"--shocks must have at least one value, got {raw!r}")
    return vals


def main() -> None:
    ap = argparse.ArgumentParser(
        description="WAGMI Portfolio Risk View - correlated-exposure + BTC-shock scenario book (read-only)"
    )
    ap.add_argument(
        "spec", type=str,
        help='Semicolon-separated positions: "SYMBOL SIDE LEVERAGEx MARGIN_USD; SYMBOL SIDE LEVERAGEx MARGIN_USD; ..."',
    )
    ap.add_argument("--equity", type=float, default=BOOK_DEFAULT_EQUITY_USD, help=f"Account equity in USD (default {BOOK_DEFAULT_EQUITY_USD:.0f})")
    ap.add_argument("--history-days", type=int, default=BOOK_DEFAULT_HISTORY_DAYS, help=f"Lookback window (days) for correlation/beta (default {BOOK_DEFAULT_HISTORY_DAYS})")
    ap.add_argument("--shocks", type=str, default=",".join(str(s) for s in BOOK_DEFAULT_SHOCKS_PCT), help="Comma-separated BTC shock %% scenarios (default -5,-10,-15)")
    args = ap.parse_args()

    try:
        specs = parse_book_spec(args.spec)
    except ValueError as e:
        print(f"[book] {e}", file=sys.stderr)
        sys.exit(2)

    try:
        shocks = _parse_shocks(args.shocks)
    except argparse.ArgumentTypeError as e:
        print(f"[book] {e}", file=sys.stderr)
        sys.exit(2)

    client = _get_hl_client()
    cards = [build_trade_card(client, sym, side, lev, margin) for (sym, side, lev, margin) in specs]

    universe = sorted(set([c.symbol for c in cards] + ["BTC"]))
    frame, _notes = build_return_frame(client, universe, args.history_days)

    print(format_book(cards, frame, args.equity, shocks, args.history_days))


if __name__ == "__main__":
    main()
