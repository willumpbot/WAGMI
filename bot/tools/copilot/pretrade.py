#!/usr/bin/env python
"""
WAGMI Co-Pilot - Theme A: Fee & Carry - pretrade.py
=============================================================================
PRE-TRADE CARD: the account's PROVEN edge is a cost cut, not a signal. The
owner's own ledger arithmetic showed fees are the dominant leak (~9bps
round-trip taker cost = a real chunk of the risk budget on a $5k account) and
funding accrues silently on multi-day holds. This module makes that leak
visible AT THE MOMENT OF THE TRADE, before it's placed.

READ-ONLY / STANDALONE, same constraints as copilot.py: only imports
copilot.py's public fetch/indicator/liquidation functions (no duplication of
that math) and, for the CLI's --discord path, tools/discord_notify.py. Never
touches live/.env/data/replay or any live-bot package.

HONESTY (per owner mandate - see copilot.py's THEME A note in its docstring):
  - Fees and funding here are ARITHMETIC (rate x notional), never a
    prediction. This card never tells you whether to take the trade.
  - The "maker fee saved" number is POTENTIAL ONLY - a resting maker order
    can simply miss the fill; it is not a guaranteed alternative to the
    taker cost.
  - Slippage is a rough PER-SYMBOL ESTIMATE (SLIPPAGE_BPS_ESTIMATE below),
    not measured from live order-book depth - it exists to keep the
    "R-needed-to-scratch" number honest on thin books, not to be precise.
  - Funding is presented as CARRY/cost context only, never as a directional
    signal - a funding-fade edge was tested and came back null (see
    EDGE INSTRUMENTS 2026-07-27 in project memory); this module must not
    imply funding predicts price direction.

CLI (wired into copilot.py, not run standalone in normal use):
    python tools/copilot/copilot.py --trade "POPCAT long 3x 800"
    python tools/copilot/copilot.py --trade "SOL long 10x 1500" --discord

    (This file can also be run directly for quick iteration:
     python tools/copilot/pretrade.py "BTC long 15x 2000")

TRADE SPEC FORMAT: "SYMBOL SIDE LEVERAGEx MARGIN_USD"
    e.g. "POPCAT long 3x 800" -> $800 is the MARGIN/collateral you're putting
    up, NOT the notional. Notional = margin x leverage (here, $2,400). This
    matches how the owner actually sizes trades (equity-at-risk first).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from copilot import (  # noqa: E402
    DEFAULT_SIDE,
    FUNDING_PAYMENTS_PER_DAY,
    RISK_PLAN_DEFAULT_ACCOUNT_USD,
    RISK_PLAN_DEFAULT_RISK_PCT,
    DipRead,
    LiquidationRead,
    RiskPlan,
    _norm_symbol,
    build_dip_read,
    compute_liquidation,
    compute_risk_plan,
    fetch_hl_max_leverage,
    format_risk_plan,
)

BOT_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))

# ---------------------------------------------------------------------------
# CONFIG - HL's real (base-tier) taker/maker fee schedule. Owner trades base
# tier (no VIP volume discount known/assumed) - these are HL's published
# non-VIP perp rates, expressed per SIDE (an open + a close = 2 sides = RT).
# ---------------------------------------------------------------------------
TAKER_FEE_BPS_PER_SIDE = 4.5   # ~4.5bps/side -> ~9bps round-trip (the leak)
MAKER_FEE_BPS_PER_SIDE = 1.5   # resting/maker order - POTENTIAL only, see module docstring

# Rough, UNMEASURED per-symbol one-way slippage estimate for a market/taker
# fill - exists only to keep "R-needed-to-scratch" honest on thin books, not
# a precise order-book-depth measurement (this tool has no L2 feed). Majors
# get a low estimate; anything not listed falls back to the thin-book default.
SLIPPAGE_BPS_ESTIMATE = {
    "BTC": 0.3,
    "ETH": 0.3,
    "SOL": 0.5,
}
DEFAULT_SLIPPAGE_BPS_ONE_WAY = 5.0  # thin/alt coins (e.g. POPCAT) - conservative default

FUNDING_DWARF_HORIZON_DAYS = 5.0  # if paying funding overtakes the RT fee within this many days, flag it


@dataclass
class TradeCard:
    ok: bool = True
    data_note: Optional[str] = None

    symbol: str = ""
    side: str = DEFAULT_SIDE
    leverage: float = 1.0
    margin_usd: float = 0.0
    notional_usd: float = 0.0
    entry_price: float = 0.0

    # Fees
    taker_fee_rt_usd: float = 0.0
    taker_fee_rt_bps: float = 0.0
    fee_pct_of_margin: float = 0.0
    maker_fee_rt_usd: float = 0.0
    maker_savings_usd: float = 0.0

    # R-needed-to-scratch
    slippage_bps_one_way: float = 0.0
    r_to_scratch_pct: float = 0.0

    # Funding
    funding_available: bool = False
    funding_rate_hourly: Optional[float] = None
    funding_rate_daily_pct: Optional[float] = None
    funding_direction: str = "n/a"   # PAY / EARN / FLAT / n/a
    funding_daily_usd: Optional[float] = None
    funding_extreme: bool = False
    funding_dwarfs_fee_days: Optional[float] = None

    # Liquidation / leverage safety (reused, not recomputed)
    liq: Optional[LiquidationRead] = None
    venue_cap_leverage: Optional[float] = None
    over_venue_cap: bool = False
    at_venue_cap: bool = False

    # RISK PLAN - the automatable half (reused from copilot.py, not recomputed)
    risk_plan: Optional[RiskPlan] = None

    # Bottom line
    total_cost_open_hold1day_usd: float = 0.0

    warnings: List[str] = field(default_factory=list)


def parse_trade_spec(raw: str):
    """Parses 'SYMBOL SIDE LEVERAGEx MARGIN_USD' (e.g. 'POPCAT long 3x 800').
    Returns (symbol, side, leverage, margin_usd). Raises ValueError with a
    clear message on any malformed input - callers should catch and print
    usage, not let this traceback into a CLI user's face."""
    if not raw or not raw.strip():
        raise ValueError('empty --trade spec; expected "SYMBOL SIDE LEVERAGEx MARGIN_USD", e.g. "POPCAT long 3x 800"')
    tokens = raw.strip().split()
    if len(tokens) != 4:
        raise ValueError(
            f'--trade must have exactly 4 parts: "SYMBOL SIDE LEVERAGEx MARGIN_USD", '
            f'e.g. "POPCAT long 3x 800" - got {raw!r} ({len(tokens)} parts)'
        )
    symbol = _norm_symbol(tokens[0])  # HL k-meme casing (kPEPE stays kPEPE, not KPEPE) - see copilot._norm_symbol
    side = tokens[1].strip().upper()
    if side in ("BUY",):
        side = "LONG"
    if side in ("SELL",):
        side = "SHORT"
    if side not in ("LONG", "SHORT"):
        raise ValueError(f'side must be long/short (or buy/sell), got {tokens[1]!r}')
    lev_tok = tokens[2].strip().lower().rstrip("x")
    try:
        leverage = float(lev_tok)
    except ValueError:
        raise ValueError(f'leverage must be a number like "3x" or "3", got {tokens[2]!r}')
    if leverage <= 0:
        raise ValueError(f'leverage must be > 0, got {leverage}')
    margin_tok = tokens[3].strip().replace("$", "").replace(",", "")
    try:
        margin_usd = float(margin_tok)
    except ValueError:
        raise ValueError(f'margin must be a dollar number, got {tokens[3]!r}')
    if margin_usd <= 0:
        raise ValueError(f'margin must be > 0, got {margin_usd}')
    return symbol, side, leverage, margin_usd


def build_trade_card(
    client, symbol: str, side: str, leverage: float, margin_usd: float,
    risk_pct: float = RISK_PLAN_DEFAULT_RISK_PCT,
    risk_account: float = RISK_PLAN_DEFAULT_ACCOUNT_USD,
) -> TradeCard:
    dip = build_dip_read(client, symbol)
    if not dip.ok:
        return TradeCard(ok=False, symbol=symbol, side=side, leverage=leverage, margin_usd=margin_usd, data_note=dip.data_note)

    side_u = side.strip().upper()
    is_long = side_u in ("LONG", "BUY")
    notional = margin_usd * leverage

    hl_max_lev = fetch_hl_max_leverage(client, symbol)
    liq = compute_liquidation(dip.price, side_u, leverage, dip.vol, hl_max_lev, symbol)

    card = TradeCard(
        ok=True, symbol=symbol, side=side_u, leverage=leverage, margin_usd=margin_usd,
        notional_usd=notional, entry_price=dip.price, liq=liq, venue_cap_leverage=hl_max_lev,
    )

    # ---- Fees (arithmetic, both sides = round trip) ----
    taker_rt_bps = TAKER_FEE_BPS_PER_SIDE * 2.0
    maker_rt_bps = MAKER_FEE_BPS_PER_SIDE * 2.0
    card.taker_fee_rt_bps = taker_rt_bps
    card.taker_fee_rt_usd = notional * taker_rt_bps / 10000.0
    card.maker_fee_rt_usd = notional * maker_rt_bps / 10000.0
    card.maker_savings_usd = card.taker_fee_rt_usd - card.maker_fee_rt_usd
    card.fee_pct_of_margin = (card.taker_fee_rt_usd / margin_usd * 100.0) if margin_usd > 0 else float("nan")

    # ---- R-needed-to-scratch: fees + a rough RT slippage estimate, as a %
    # price move. Fee/slippage cost scales with NOTIONAL and so does the P&L
    # from a price move, so leverage cancels out of this % - it is the same
    # required move regardless of how much margin backs the same notional. ----
    slip_one_way = SLIPPAGE_BPS_ESTIMATE.get(symbol, DEFAULT_SLIPPAGE_BPS_ONE_WAY)
    card.slippage_bps_one_way = slip_one_way
    slip_rt_bps = slip_one_way * 2.0
    card.r_to_scratch_pct = (taker_rt_bps + slip_rt_bps) / 100.0  # bps -> percent

    # ---- Funding: carry cost/credit, never a signal ----
    if dip.funding_rate is not None:
        card.funding_available = True
        rate = dip.funding_rate
        card.funding_rate_hourly = rate
        daily_rate = rate * FUNDING_PAYMENTS_PER_DAY
        card.funding_rate_daily_pct = daily_rate * 100.0
        eff = rate if is_long else -rate
        if eff > 1e-12:
            card.funding_direction = "PAY"
        elif eff < -1e-12:
            card.funding_direction = "EARN"
        else:
            card.funding_direction = "FLAT"
        card.funding_daily_usd = abs(daily_rate) * notional
        card.funding_extreme = dip.funding_extreme
        if card.funding_direction == "PAY" and card.funding_daily_usd > 1e-9:
            days_to_dwarf = card.taker_fee_rt_usd / card.funding_daily_usd
            if days_to_dwarf <= FUNDING_DWARF_HORIZON_DAYS:
                card.funding_dwarfs_fee_days = days_to_dwarf

    # ---- Liquidation / leverage safety (reused from copilot.py, not redone) ----
    if hl_max_lev is not None:
        card.at_venue_cap = leverage >= hl_max_lev - 1e-9
        card.over_venue_cap = leverage > hl_max_lev + 1e-9

    # ---- Warnings roll-up ----
    card.warnings.extend(liq.warnings)
    if card.over_venue_cap:
        card.warnings.append(
            f"{leverage:.1f}x is ABOVE {symbol}'s Hyperliquid venue cap ({hl_max_lev:.0f}x) - "
            f"HL will not let you open this; it will clamp or reject the order."
        )
    elif card.at_venue_cap:
        card.warnings.append(
            f"{leverage:.1f}x IS Hyperliquid's max allowed leverage for {symbol} - there is zero "
            f"headroom; any adverse move eats margin faster than a lower-leverage position would."
        )
    if liq.risk_label != "SAFE":
        card.warnings.append(f"Leverage is {liq.risk_label} for {symbol}'s current volatility (safe max ~{liq.safe_max_leverage:.1f}x).")
    if card.funding_dwarfs_fee_days is not None:
        card.warnings.append(
            f"Funding will exceed the one-time round-trip fee after ~{card.funding_dwarfs_fee_days:.1f} days held - "
            f"factor hold length into the cost, not just the entry fee."
        )

    # ---- RISK PLAN - the automatable half (reuses dip.atr_1d + liq, no re-derivation) ----
    card.risk_plan = compute_risk_plan(dip, liq, side_u, risk_pct, risk_account)

    # ---- Bottom line: cost to open + hold 1 day ----
    funding_1day_signed = 0.0
    if card.funding_daily_usd is not None:
        funding_1day_signed = card.funding_daily_usd if card.funding_direction == "PAY" else -card.funding_daily_usd if card.funding_direction == "EARN" else 0.0
    card.total_cost_open_hold1day_usd = card.taker_fee_rt_usd + funding_1day_signed

    return card


def format_trade_card(card: TradeCard) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    if not card.ok:
        return f"PRE-TRADE CARD: {card.symbol} - NO DATA: {card.data_note}"

    lines = []
    lines.append(
        f"=== PRE-TRADE CARD: {card.symbol} {card.side} {card.leverage:.1f}x - "
        f"${card.margin_usd:,.0f} margin (${card.notional_usd:,.0f} notional) - {ts} ==="
    )
    lines.append(f"Entry (last): ${card.entry_price:.4f}")
    lines.append("")

    # ---- FEES ----
    lines.append(
        f"FEE (taker, round trip @ {card.taker_fee_rt_bps:.1f}bps): ${card.taker_fee_rt_usd:.2f} "
        f"= {card.taker_fee_rt_bps/100.0:.2f}% of notional = {card.fee_pct_of_margin:.2f}% of your ${card.margin_usd:,.0f} margin"
    )
    lines.append(
        f"  Maker alternative (both legs resting, ~{MAKER_FEE_BPS_PER_SIDE*2:.1f}bps RT): ${card.maker_fee_rt_usd:.2f} "
        f"-> POTENTIAL saving of ${card.maker_savings_usd:.2f} (a resting order can simply miss the fill - not guaranteed)"
    )
    lines.append("")

    # ---- R-NEEDED-TO-SCRATCH ----
    lines.append(
        f"R-NEEDED-TO-SCRATCH: price must move ~{card.r_to_scratch_pct:.2f}% just to cover round-trip fees "
        f"({card.taker_fee_rt_bps/100.0:.2f}%) + est. slippage ({card.slippage_bps_one_way:.1f}bps one-way, "
        f"{card.slippage_bps_one_way*2/100.0:.2f}% RT - unmeasured heuristic, not order-book depth) - before any profit."
    )
    lines.append("")

    # ---- FUNDING ----
    if not card.funding_available:
        lines.append(f"FUNDING: no data available for {card.symbol}.")
    else:
        extreme_bit = "  >>> EXTREME - crowded positioning, squeeze/unwind risk. <<<" if card.funding_extreme else ""
        verb = {"PAY": "PAYS", "EARN": "EARNS", "FLAT": "~flat -"}.get(card.funding_direction, "n/a")
        lines.append(
            f"FUNDING (carry, not a signal): {card.funding_rate_hourly*100:+.4f}%/hr "
            f"(~{card.funding_rate_daily_pct:+.3f}%/day) - {card.side} {verb} ~${card.funding_daily_usd:,.2f}/day "
            f"on ${card.notional_usd:,.0f} notional.{extreme_bit}"
        )
        if card.funding_dwarfs_fee_days is not None:
            lines.append(
                f"  Multi-day flag: at this rate, funding paid exceeds the one-time RT fee after "
                f"~{card.funding_dwarfs_fee_days:.1f} days - don't just look at the entry fee on a longer hold."
            )
    lines.append("")

    # ---- LIQUIDATION / SAFE-LEVERAGE ----
    liq = card.liq
    cap_bit = f"venue cap {card.venue_cap_leverage:.0f}x" if card.venue_cap_leverage is not None else "venue cap unknown (fallback mm used)"
    cap_flag = " *** AT/OVER VENUE CAP ***" if (card.at_venue_cap or card.over_venue_cap) else ""
    lines.append(
        f"LIQUIDATION: ${liq.liq_price:.4f} ({liq.distance_pct*100:.1f}% away) | {cap_bit}{cap_flag} | "
        f"safe-max (vol-derived) ~{liq.safe_max_leverage:.1f}x | [{liq.risk_label}]"
    )
    lines.append(f"  {liq.risk_reason}")
    lines.append("")

    # ---- RISK PLAN - the automatable half ----
    if card.risk_plan is not None:
        lines.extend(format_risk_plan(card.risk_plan))
        lines.append("")

    # ---- WARNINGS ----
    if card.warnings:
        lines.append("WARNINGS:")
        for w in card.warnings:
            lines.append(f"  - {w}")
        lines.append("")

    # ---- BOTTOM LINE ----
    fund_bit = ""
    if card.funding_available and card.funding_direction != "FLAT":
        verb_lower = "paying" if card.funding_direction == "PAY" else "earning"
        fund_bit = f" (fee ${card.taker_fee_rt_usd:.2f} + funding ${card.funding_daily_usd:.2f}/day {verb_lower})"
    if card.total_cost_open_hold1day_usd >= 0:
        cost_bit = f"costs ~${card.total_cost_open_hold1day_usd:.2f} total{fund_bit}"
    else:
        cost_bit = (
            f"costs ${card.taker_fee_rt_usd:.2f} in fees, but funding earned nets it to roughly a "
            f"${abs(card.total_cost_open_hold1day_usd):.2f} CREDIT{fund_bit} - don't count on that lasting; "
            f"funding direction can flip"
        )
    lines.append(
        f"BOTTOM LINE: opening + holding 1 day {cost_bit}. "
        f"You need roughly +{card.r_to_scratch_pct:.2f}% just to cover fees/slippage before any profit - "
        f"this is arithmetic, not a prediction of whether the trade works."
    )

    return "\n".join(lines)


def main() -> None:
    """Standalone convenience entrypoint for quick iteration - the supported
    path is `python tools/copilot/copilot.py --trade "..."`."""
    if len(sys.argv) < 2:
        print('Usage: python tools/copilot/pretrade.py "SYMBOL SIDE LEVERAGEx MARGIN_USD"')
        sys.exit(1)
    raw = " ".join(sys.argv[1:])
    from copilot import _get_hl_client  # noqa: E402 (local: avoid import cost when only used as a library)
    try:
        symbol, side, leverage, margin_usd = parse_trade_spec(raw)
    except ValueError as e:
        print(f"error: {e}")
        sys.exit(1)
    client = _get_hl_client()
    card = build_trade_card(client, symbol, side, leverage, margin_usd)
    print(format_trade_card(card))


if __name__ == "__main__":
    main()
