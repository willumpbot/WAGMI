"""Premium Alert Filter.

Decides whether a signal is worth sending to the user's phone as a
manually-actionable trading alert, and what tier it belongs to.

Built 2026-04-16 to replace the noisy "every ensemble signal goes to
Telegram" default that was sending ~170 alerts/day, most of them low
quality. The new filter enforces a shadow-ledger-verified quality bar
so the user only gets alerts for setups with proven edge.

Tiers:
    EXECUTE   — Take action now. High-conviction, all conditions met.
                Target: 1-3 per day. These are the alerts you ACT on.
    WATCH     — Setup is forming. Get ready, don't act yet.
                Target: 3-8 per day. These are "get your finger on the
                trigger, one condition away from execute."
    NONE      — Do not send. Quality below user-attention threshold.

Thresholds (conservative by design — prefer silence over noise):
    EXECUTE requires one of:
      - Shadow-verified premium edge (>=80% floor, 100+ samples) AND
        confidence >= 75% AND 2+ strategies agree
      - Shadow-verified standard edge (60-80% floor) AND
        confidence >= 82% AND 3+ strategies agree AND favorable regime
    WATCH requires:
      - Shadow-verified edge (any tier) AND confidence >= 65%
      - OR explicit anticipatory pre-stage

Author: autonomous session 2026-04-15/16, built from the shadow ledger
(3,835 resolved entries) analysis that produced _SHADOW_EDGES and
_SHADOW_BLOCKS in ensemble.py.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Tuple

logger = logging.getLogger("bot.alerts.premium_filter")


class AlertTier(Enum):
    """Which tier of alert (if any) to send for a signal."""
    NONE = "none"       # do not send
    WATCH = "watch"     # advance notice — user should get ready
    EXECUTE = "execute" # action now — user should consider taking


# ─── Shadow-ledger-verified edges ────────────────────────────────────
# Sourced from bot/data/shadow_ledger.csv analysis on 2026-04-15.
# See AUTONOMOUS_SESSION_2026_04_15.md for full derivation.
#
# Structure: (symbol, side, strategy) -> {wr, n, grade}
# grade: "premium" = 100+ samples with strong edge, can EXECUTE alone
#        "standard" = 40-100 samples with edge, needs more confirmation
# EMPTIED 2026-07-14 (living-values de-hardcode): these tables were rebuilt
# 2026-04-16 from the PRE-FEE-FIX shadow_ledger — the same poison that was declared
# invalid and emptied in comprehensive_snapshot.py / ensemble.py on 2026-06-05. This
# copy survived the purge and still asserted "ETH BUY regime_trend = 100% WR, can
# EXECUTE alone" and BLOCKED ("ETH","SELL","regime_trend") — i.e. it suppressed
# ETH_SELL, the actual best live edge (+$14.90/tr). No fictional edges/blocks; let live
# data + graduated_rules (n>=13) decide. Revert: restore from git if ever needed.
_SHADOW_EDGES: Dict[Tuple[str, str, str], Dict[str, object]] = {}

_SHADOW_BLOCKS: frozenset = frozenset()

# Regimes that historically kill each setup. Sourced from
# project_autonomous_session_2026_04_15 Finding 7 + per-regime analysis.
# (symbol, side) -> set of regime strings to avoid.
#
# Note: two regime classifiers exist — trade_profile outputs "illiquid",
# quant_regime.py outputs "low_liquidity". We accept both as aliases for
# the same underlying condition. Regime strings are normalized to lower
# case at lookup time.
_ADVERSE_REGIMES: Dict[Tuple[str, str], frozenset] = {
    # HYPE in illiquid: 8.3% WR on 12 HYPE LONGs (Finding 7)
    # HYPE in ranging:  14.3% WR on 7 HYPE LONGs (Finding 7)
    # HYPE in trending: 33.3% WR on 6 HYPE LONGs (marginal — not adding to block yet)
    ("HYPE", "BUY"): frozenset({"illiquid", "low_liquidity", "ranging", "range"}),
}

# Regime aliases — normalize different classifier outputs.
_REGIME_ALIASES: Dict[str, str] = {
    "low_liquidity": "illiquid",
    "low-liquidity": "illiquid",
    "lowliquidity": "illiquid",
    "low_vol": "low_volatility",
    "hi_vol": "high_volatility",
    "trending": "trend",  # trade_profile uses "trending", some use "trend"
}


def _normalize_regime(regime: str) -> str:
    """Lowercase and apply aliases to regime string."""
    r = (regime or "").lower().strip()
    return _REGIME_ALIASES.get(r, r)


# ─── Dedup for WATCH alerts ──────────────────────────────────────────
# In-memory rate limit on WATCH alerts. Key: (symbol, side, strategy).
# Stores last alert timestamp. Prevents anticipatory engine from
# spamming the same setup every scan cycle.
_WATCH_ALERT_COOLDOWN_S = 1800  # 30 minutes between same-setup WATCHes
_last_watch_alert: Dict[Tuple[str, str, str], float] = {}


def is_watch_deduped(symbol: str, side: str, strategy: str) -> bool:
    """Return True if a WATCH alert for this setup was sent within cooldown.

    Call BEFORE sending a WATCH. If returns True, skip the alert.
    Call mark_watch_sent() after successful send.
    """
    key = ((symbol or "").upper(), (side or "").upper(), (strategy or "").lower())
    last = _last_watch_alert.get(key, 0)
    return (time.time() - last) < _WATCH_ALERT_COOLDOWN_S


def mark_watch_sent(symbol: str, side: str, strategy: str) -> None:
    """Record that a WATCH alert was sent for this setup."""
    key = ((symbol or "").upper(), (side or "").upper(), (strategy or "").lower())
    _last_watch_alert[key] = time.time()


@dataclass
class AlertDecision:
    """Decision made by the filter on a given signal."""
    tier: AlertTier
    reason: str
    shadow_wr: Optional[float] = None
    shadow_n: Optional[int] = None
    shadow_grade: Optional[str] = None
    size_suggestion_notional: Optional[float] = None
    max_loss_usd: Optional[float] = None
    key_conditions_met: list = field(default_factory=list)
    key_conditions_missing: list = field(default_factory=list)

    @property
    def should_send(self) -> bool:
        return self.tier != AlertTier.NONE


# ─── Sizing recommendations ──────────────────────────────────────────
# Recommended position size based on max-loss-per-trade constraint.
# Inputs: equity, leverage, stop_pct (sl distance as % of entry), max_loss_pct
# Output: notional position size in USD
def _suggest_size(
    equity: float,
    leverage: float,
    stop_pct: float,
    max_loss_usd: float = 10.0,
) -> float:
    """Size a position so that SL hit = max_loss_usd loss.

    Given: risk = notional * leverage_factor * stop_pct, but for isolated
    margin the loss at SL = margin * stop_pct * leverage.

    Simpler model: loss_at_sl = notional * stop_pct
        notional = max_loss_usd / stop_pct
    """
    if stop_pct <= 0:
        return 0.0
    notional = max_loss_usd / stop_pct
    # Cap at 40% of equity to avoid over-concentration
    max_notional = equity * 0.40
    return min(notional, max_notional)


# ─── Main decision function ──────────────────────────────────────────
def evaluate_for_alert(
    symbol: str,
    side: str,  # "BUY" or "SELL" or "LONG" or "SHORT"
    strategy: str,  # primary driver strategy name
    confidence: float,  # 0-100
    num_agree: int,
    regime: str,
    entry: float,
    sl: float,
    tp1: float,
    tp2: float,
    leverage: float,
    strategies_agree: Optional[list] = None,
    equity: float = 500.0,
    ev_per_dollar: float = 0.0,
    anticipatory_prestage: bool = False,
    max_loss_usd: float = 10.0,
) -> AlertDecision:
    """Decide whether this signal deserves a user-facing alert.

    This is the only function most callers need. Returns an AlertDecision
    whose `tier` determines send behavior (EXECUTE / WATCH / NONE).
    """
    # Normalize side to BUY/SELL for shadow lookup
    _side_up = (side or "").upper()
    if _side_up in ("LONG",):
        side_bs = "BUY"
    elif _side_up in ("SHORT",):
        side_bs = "SELL"
    else:
        side_bs = _side_up  # "BUY" or "SELL"

    symbol_up = (symbol or "").upper().split("/")[0]  # strip "/USDT:USDT"
    strategy_l = (strategy or "").lower()

    key = (symbol_up, side_bs, strategy_l)

    # 1. Hard block: setup is a known money loser. Never alert.
    if key in _SHADOW_BLOCKS:
        return AlertDecision(
            tier=AlertTier.NONE,
            reason=f"shadow-blocked: {key} is a verified money loser",
        )

    # 2. Adverse regime check (with alias normalization)
    adverse_regimes = _ADVERSE_REGIMES.get((symbol_up, side_bs), frozenset())
    regime_n = _normalize_regime(regime)
    if regime_n in adverse_regimes:
        return AlertDecision(
            tier=AlertTier.NONE,
            reason=f"adverse regime: {symbol_up} {side_bs} historically weak in '{regime_n}'",
        )

    # 3. Look up shadow edge
    edge = _SHADOW_EDGES.get(key)
    conditions_met = []
    conditions_missing = []

    if edge is None:
        # No shadow data for this exact combo. Only alert if it's
        # an anticipatory pre-stage (that's a different quality signal).
        if anticipatory_prestage:
            return AlertDecision(
                tier=AlertTier.WATCH,
                reason="anticipatory pre-stage (no shadow data)",
                key_conditions_met=["anticipatory_engine_fired"],
            )
        return AlertDecision(
            tier=AlertTier.NONE,
            reason=f"no shadow edge data for {key}",
        )

    shadow_wr = float(edge["wr"])
    shadow_n = int(edge["n"])
    shadow_grade = str(edge["grade"])

    # Compute stop distance and size suggestion
    stop_pct = abs(entry - sl) / entry if entry > 0 else 0
    size_notional = _suggest_size(equity, leverage, stop_pct, max_loss_usd)

    # 4. Tier decision
    # EXECUTE conditions
    if shadow_grade == "premium":
        if confidence >= 75 and num_agree >= 2:
            conditions_met = [
                f"premium-edge setup ({shadow_wr*100:.0f}% WR on {shadow_n})",
                f"confidence {confidence:.0f}% >= 75",
                f"{num_agree} strategies agree",
            ]
            return AlertDecision(
                tier=AlertTier.EXECUTE,
                reason="premium-edge setup with strong consensus",
                shadow_wr=shadow_wr, shadow_n=shadow_n, shadow_grade=shadow_grade,
                size_suggestion_notional=size_notional,
                max_loss_usd=max_loss_usd,
                key_conditions_met=conditions_met,
            )
        else:
            # Premium edge but confidence or agreement too low → WATCH
            if confidence < 75:
                conditions_missing.append(f"confidence {confidence:.0f}% < 75 needed")
            if num_agree < 2:
                conditions_missing.append(f"only {num_agree} strategy agreeing, need 2+")
            conditions_met.append(f"premium-edge setup ({shadow_wr*100:.0f}% WR on {shadow_n})")
            return AlertDecision(
                tier=AlertTier.WATCH,
                reason="premium-edge forming; wait for confirmation",
                shadow_wr=shadow_wr, shadow_n=shadow_n, shadow_grade=shadow_grade,
                size_suggestion_notional=size_notional,
                max_loss_usd=max_loss_usd,
                key_conditions_met=conditions_met,
                key_conditions_missing=conditions_missing,
            )

    elif shadow_grade == "standard":
        if confidence >= 82 and num_agree >= 3:
            conditions_met = [
                f"standard-edge setup ({shadow_wr*100:.0f}% WR on {shadow_n})",
                f"high confidence {confidence:.0f}% >= 82",
                f"{num_agree} strategies agree (>= 3)",
            ]
            return AlertDecision(
                tier=AlertTier.EXECUTE,
                reason="standard-edge with high confidence + multi-strategy",
                shadow_wr=shadow_wr, shadow_n=shadow_n, shadow_grade=shadow_grade,
                size_suggestion_notional=size_notional,
                max_loss_usd=max_loss_usd,
                key_conditions_met=conditions_met,
            )
        elif confidence >= 70:
            # Standard edge, decent confidence → WATCH
            if confidence < 82:
                conditions_missing.append(f"confidence {confidence:.0f}% < 82 needed")
            if num_agree < 3:
                conditions_missing.append(f"only {num_agree} strategies agreeing, need 3+")
            conditions_met.append(f"standard-edge setup ({shadow_wr*100:.0f}% WR on {shadow_n})")
            return AlertDecision(
                tier=AlertTier.WATCH,
                reason="standard-edge forming; needs more confirmation",
                shadow_wr=shadow_wr, shadow_n=shadow_n, shadow_grade=shadow_grade,
                size_suggestion_notional=size_notional,
                max_loss_usd=max_loss_usd,
                key_conditions_met=conditions_met,
                key_conditions_missing=conditions_missing,
            )
        else:
            return AlertDecision(
                tier=AlertTier.NONE,
                reason=f"standard-edge but confidence too low ({confidence:.0f}%)",
            )

    # Unknown grade — treat conservatively
    return AlertDecision(
        tier=AlertTier.NONE,
        reason=f"unknown shadow grade: {shadow_grade}",
    )
