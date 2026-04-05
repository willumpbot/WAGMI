"""
Simulated LLM Agents for Backtest (No API Required).

Applies the same decision logic as the 9-agent LLM pipeline but as
deterministic Python code. This lets us backtest the LLM-first
architecture without spending API credits.

Each agent is a function that takes signal + context and returns
a decision. The pipeline chains them: Regime → Trade → Risk → Critic.

Enable: --sim-agents flag on backtest, or SIM_AGENTS_ENABLED=true env var.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

logger = logging.getLogger("bot.backtest.simulated_agents")


@dataclass
class SimDecision:
    """Decision from the simulated agent pipeline."""
    action: str  # "go" or "skip"
    confidence: float = 0.0  # 0.0-1.0
    size_mult: float = 1.0  # 0.0-2.0 sizing multiplier
    regime: str = "unknown"
    reason: str = ""
    skip_reasons: List[str] = field(default_factory=list)
    boost_reasons: List[str] = field(default_factory=list)


def _env_bool(key: str, default: bool) -> bool:
    return os.getenv(key, str(default)).lower() in ("1", "true", "yes")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


# ─── Simulated Regime Agent ─────────────────────────────────────

def sim_regime_agent(signal, df_1h=None) -> str:
    """Classify market regime from technical indicators.

    Uses ADX, ATR percentile, and volume to determine regime.
    Matches the Regime Agent prompt's classification rubric.
    """
    regime = (signal.metadata or {}).get("regime", "unknown")

    # If regime already classified by strategy, use it
    if regime and regime != "unknown":
        return regime

    if df_1h is None or len(df_1h) < 20:
        return "unknown"

    try:
        close = df_1h["close"]
        high = df_1h["high"]
        low = df_1h["low"]

        # Simple ATR
        tr = (high - low).tail(14)
        atr = tr.mean()
        atr_pct = atr / close.iloc[-1] if close.iloc[-1] > 0 else 0

        # Trend direction from EMA
        ema_20 = close.ewm(span=20).mean()
        ema_50 = close.ewm(span=50).mean()
        trend_up = ema_20.iloc[-1] > ema_50.iloc[-1]
        trend_strength = abs(ema_20.iloc[-1] - ema_50.iloc[-1]) / close.iloc[-1]

        # Volume
        vol = df_1h.get("volume")
        vol_ratio = 1.0
        if vol is not None and len(vol) > 20:
            vol_ratio = vol.iloc[-1] / vol.tail(20).mean() if vol.tail(20).mean() > 0 else 1.0

        # Classify
        if atr_pct > 0.03:  # >3% ATR = high vol
            return "high_volatility"
        elif trend_strength > 0.005 and atr_pct > 0.01:
            return "trending_bull" if trend_up else "trending_bear"
        elif trend_strength > 0.002:
            return "trend"
        elif atr_pct < 0.005:
            return "consolidation"
        else:
            return "range"
    except Exception:
        return "unknown"


# ─── Simulated Trade Agent ──────────────────────────────────────

def sim_trade_agent(signal, regime: str, df_1h=None) -> SimDecision:
    """Apply the Trade Agent's decision logic informed by 1,410-signal analysis.

    KEY FINDINGS FROM FULL DATA:
    - bollinger_squeeze is the ONLY profitable strategy (57% WR, +0.15%/trade)
    - confidence_scorer is a slight loser (47% WR, generates 60% of all signals)
    - Confidence numbers are NOT predictive (80%+ is WORSE than <60%)
    - high_volatility regime has genuine edge (55% WR, n=258)
    - Golden setups: ETH_SELL_BB 70%, BTC_BUY_BB 69%, SOL_BUY_BB 67%
    """
    skip_reasons = []
    boost_reasons = []
    conf = 0.50  # Start at base

    meta = signal.metadata or {}
    num_agree = meta.get("num_agree", 1)
    symbol = signal.symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "")

    # ── Gate 1: Regime Check ──
    bad_regimes = {"panic", "low_liquidity"}
    if regime in bad_regimes:
        if num_agree < 3:
            skip_reasons.append(f"regime={regime} with only {num_agree}-agree")
            return SimDecision(
                action="skip", confidence=0.0,
                regime=regime, reason="; ".join(skip_reasons),
                skip_reasons=skip_reasons,
            )

    # trending_bear: historically worst regime. Allow only strong signals
    if regime == "trending_bear":
        if num_agree < 2 or signal.confidence < 80:
            skip_reasons.append(f"trending_bear with weak signal (agree={num_agree}, conf={signal.confidence:.0f})")
            return SimDecision(
                action="skip", confidence=0.0,
                regime=regime, reason="; ".join(skip_reasons),
                skip_reasons=skip_reasons,
            )

    # ── Gate 1.5: STRATEGY QUALITY (from 1,410-signal analysis) ──
    # bollinger_squeeze is the ONLY profitable strategy (57% WR)
    # confidence_scorer is 47% WR (slight loser). Others worse.
    strategy = signal.strategy or ""
    strategies_agree = meta.get("strategies_agree", [strategy])
    has_bb = "bollinger_squeeze" in strategies_agree
    primary_is_bb = strategy == "bollinger_squeeze"

    if has_bb:
        conf += 0.10
        boost_reasons.append("bollinger_squeeze signal (57% WR, only profitable strategy)")
    else:
        # No BB involved — this is a non-BB signal.
        # From 1,410 signals: non-BB strategies have NEGATIVE expected value.
        # 2-agree without BB is two losing strategies agreeing — still loses.
        conf -= 0.15
        skip_reasons.append("no bollinger_squeeze (only profitable strategy missing)")

    # GOLDEN SETUP DETECTION
    setup_key = f"{symbol}_{signal.side}_{strategy}"
    golden_setups = {
        "ETH_SELL_bollinger_squeeze": (0.15, "ETH_SELL_BB 70% WR"),
        "BTC_BUY_bollinger_squeeze": (0.12, "BTC_BUY_BB 69% WR"),
        "SOL_BUY_bollinger_squeeze": (0.10, "SOL_BUY_BB 67% WR"),
        "BTC_SELL_bollinger_squeeze": (0.08, "BTC_SELL_BB 61% WR"),
        "ETH_BUY_bollinger_squeeze": (0.06, "ETH_BUY_BB 59% WR"),
    }
    dead_setups = {
        "HYPE_SELL_bollinger_squeeze": "35% WR, worst setup",
        "HYPE_BUY_confidence_scorer": "38% WR",
        "HYPE_SELL_regime_trend": "20% WR",
    }

    if setup_key in golden_setups:
        boost, reason = golden_setups[setup_key]
        conf += boost
        boost_reasons.append(f"GOLDEN: {reason}")
    elif setup_key in dead_setups:
        skip_reasons.append(f"DEAD SETUP: {setup_key} ({dead_setups[setup_key]})")
        return SimDecision(
            action="skip", confidence=0.0,
            regime=regime, reason="; ".join(skip_reasons),
            skip_reasons=skip_reasons,
        )

    # Dead strategies (from 1,410-signal data)
    if strategy in ("mean_reversion", "regime_trend") and not has_bb:
        skip_reasons.append(f"{strategy} solo (43% WR, losing strategy)")
        return SimDecision(
            action="skip", confidence=0.0,
            regime=regime, reason="; ".join(skip_reasons),
            skip_reasons=skip_reasons,
        )

    # ── Gate 2: Directional Alignment (basic check) ──
    # Can't form independent thesis without more data, skip this gate

    # ── Gate 3: Timeframe Confluence ──
    regime_4h = meta.get("regime_4h", "unknown")
    regime_1h = meta.get("regime_1h", regime)
    if regime_4h != "unknown" and regime_1h != regime_4h:
        # Check if compatible
        compatible = {
            ("consolidation", "trending_bull"),
            ("trending_bull", "consolidation"),
            ("consolidation", "trend"),
            ("trend", "consolidation"),
        }
        if (regime_1h, regime_4h) not in compatible:
            conf -= 0.10
            skip_reasons.append(f"HTF conflict: 1h={regime_1h} vs 4h={regime_4h}")

    # ── Gate 4: Strategy Consensus ──
    if num_agree >= 3:
        conf += 0.15
        boost_reasons.append(f"3+-agree ({num_agree})")
    elif num_agree >= 2:
        conf += 0.05
        boost_reasons.append(f"2-agree")
    elif num_agree == 1:
        conf -= 0.10
        skip_reasons.append(f"solo signal")

    # ── Gate 5: Market Quality ──
    if df_1h is not None and len(df_1h) >= 20:
        try:
            close = df_1h["close"]
            # RSI
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain.iloc[-1] / loss.iloc[-1] if loss.iloc[-1] > 0 else 100
            rsi = 100 - (100 / (1 + rs))

            if rsi > 75:
                conf -= 0.10
                skip_reasons.append(f"RSI overbought ({rsi:.0f})")
            elif rsi < 25:
                conf -= 0.10
                skip_reasons.append(f"RSI oversold ({rsi:.0f})")

            # Volume
            vol = df_1h.get("volume")
            if vol is not None and len(vol) > 20:
                vol_ratio = vol.iloc[-1] / vol.tail(20).mean() if vol.tail(20).mean() > 0 else 1.0
                if vol_ratio > 2.0:
                    # Surging volume — check direction
                    price_up = close.iloc[-1] > close.iloc[-2]
                    signal_long = signal.side == "BUY"
                    if price_up != signal_long:
                        conf -= 0.10
                        skip_reasons.append(f"volume surging against direction")
                    else:
                        conf += 0.05
                        boost_reasons.append("volume confirmation")
        except Exception:
            pass

    # ── Gate 6: Signal Quality ──
    chop = meta.get("chop_score", meta.get("chop_score_smoothed", 0))
    if chop > 0.65:
        conf -= 0.10
        skip_reasons.append(f"choppy market ({chop:.2f})")

    ev = meta.get("ev_per_dollar")
    if ev is not None and ev < 0:
        skip_reasons.append(f"negative EV ({ev:.3f})")
        return SimDecision(
            action="skip", confidence=0.0,
            regime=regime, reason="; ".join(skip_reasons),
            skip_reasons=skip_reasons,
        )

    win_prob = meta.get("win_prob_deflated", meta.get("win_prob"))
    if win_prob is not None and win_prob < 0.40:
        conf -= 0.10
        skip_reasons.append(f"low win prob ({win_prob:.2f})")

    rr = signal.risk_reward_tp1
    if rr < 1.0:
        skip_reasons.append(f"R:R too low ({rr:.2f})")
        return SimDecision(
            action="skip", confidence=0.0,
            regime=regime, reason="; ".join(skip_reasons),
            skip_reasons=skip_reasons,
        )

    # ── Gate 7: Symbol Edge (from 60d backtest outcome analysis) ──
    # BTC: 60% WR, +$477 — strong edge, especially SHORT
    # ETH: 31% WR, -$97 — net loser, ETH LONG especially bad
    # SOL/HYPE: insufficient closed trades in backtest
    if symbol == "BTC":
        conf += 0.05
        boost_reasons.append("BTC edge (60% WR)")
        # BTC SHORT is the crown jewel: 13/17 winners were BTC SHORT
        if signal.side == "SELL":
            conf += 0.05
            boost_reasons.append("BTC SHORT dominant winner pattern")
    elif symbol == "ETH":
        # ETH LONG is -$54 across 4 trades. ETH SHORT marginal.
        if signal.side == "BUY":
            if num_agree < 2 or signal.confidence < 80:
                skip_reasons.append("ETH LONG requires 2-agree + 80% conf (historically -$54)")
                return SimDecision(
                    action="skip", confidence=0.0,
                    regime=regime, reason="; ".join(skip_reasons),
                    skip_reasons=skip_reasons,
                )
            conf -= 0.05  # Penalize even passing ETH LONGs
        elif signal.side == "SELL":
            if num_agree < 2:
                skip_reasons.append("ETH SHORT solo is marginal")
                return SimDecision(
                    action="skip", confidence=0.0,
                    regime=regime, reason="; ".join(skip_reasons),
                    skip_reasons=skip_reasons,
                )

    # ── Final Decision ──
    conf = max(0.0, min(0.95, conf))

    if conf < 0.35:
        return SimDecision(
            action="skip", confidence=conf,
            regime=regime,
            reason="; ".join(skip_reasons) if skip_reasons else "low confidence",
            skip_reasons=skip_reasons,
        )

    return SimDecision(
        action="go", confidence=conf,
        regime=regime,
        reason="; ".join(boost_reasons) if boost_reasons else "passed all gates",
        skip_reasons=skip_reasons,
        boost_reasons=boost_reasons,
    )


# ─── Simulated Risk Agent ──────────────────────────────────────

def sim_risk_agent(signal, decision: SimDecision, equity: float) -> SimDecision:
    """Apply Risk Agent sizing logic.

    Adjusts size_mult based on conviction, regime, and portfolio state.
    """
    if decision.action == "skip":
        return decision

    meta = signal.metadata or {}
    num_agree = meta.get("num_agree", 1)
    regime = decision.regime

    sz = 1.0

    # Consensus sizing — INVERTED from traditional wisdom!
    # Data: Solo BB (62% WR) > 2-agree+BB (52% WR) > 2-agree_noBB (45% WR)
    # BB works BEST alone. Adding other strategies dilutes its edge.
    strategies_agree = meta.get("strategies_agree", [])
    has_bb = "bollinger_squeeze" in strategies_agree

    if has_bb and num_agree == 1:
        sz = 1.3  # Solo BB is the BEST pattern (62% WR)
    elif has_bb and num_agree >= 2:
        sz = 1.0  # BB + confirmation: still good but diluted
    elif num_agree >= 3:
        sz = 0.8  # 3-agree without BB: decent but not BB-quality
    elif num_agree >= 2:
        sz = 0.6  # 2-agree without BB: marginal
    elif num_agree == 1:
        sz = 0.3  # Solo non-BB: near coinflip

    # Regime adjustment
    regime_mult = {
        "trend": 1.0, "trending_bull": 1.0, "trending_bear": 0.6,
        "consolidation": 0.9, "range": 0.8,
        "high_volatility": 0.7, "panic": 0.4,
        "unknown": 0.7,
    }.get(regime, 0.7)
    sz *= regime_mult

    # Confidence adjustment
    conf = decision.confidence
    if conf >= 0.75:
        sz *= 1.2
    elif conf >= 0.60:
        sz *= 1.0
    elif conf >= 0.45:
        sz *= 0.7
    else:
        sz *= 0.5

    # Clamp
    sz = max(0.3, min(2.0, sz))

    decision.size_mult = round(sz, 2)
    return decision


# ─── Simulated Critic Agent ────────────────────────────────────

def sim_critic_agent(signal, decision: SimDecision, df_1h=None) -> SimDecision:
    """Apply Critic Agent's counter-thesis logic.

    Checks for known losing patterns and vetoes if found.
    """
    if decision.action == "skip":
        return decision

    meta = signal.metadata or {}
    red_flags = 0
    veto_reasons = []

    # Flag 1: Solo signal in bad regime
    num_agree = meta.get("num_agree", 1)
    if num_agree <= 1 and decision.regime in ("trending_bear", "range", "high_volatility"):
        red_flags += 1
        veto_reasons.append("solo in adverse regime")

    # Flag 2: ETH longs (historically poor)
    symbol = signal.symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "")
    if symbol == "ETH" and signal.side == "BUY" and decision.regime != "trending_bull":
        red_flags += 1
        veto_reasons.append("ETH LONG in non-bull regime")

    # Flag 3: Low R:R
    rr = signal.risk_reward_tp1
    if rr < 1.3:
        red_flags += 1
        veto_reasons.append(f"R:R {rr:.2f} < 1.3")

    # Flag 4: Very low confidence
    if signal.confidence < 60:
        red_flags += 1
        veto_reasons.append(f"conf {signal.confidence:.0f}% < 60")

    # Flag 4b: Extreme confidence (anti-predictive from live data)
    # 90-100% confidence = 22.7% WR historically
    if signal.confidence >= 98:
        red_flags += 1
        veto_reasons.append(f"extreme conf {signal.confidence:.0f}% (anti-predictive)")

    # Flag 5: Chop market
    chop = meta.get("chop_score", meta.get("chop_score_smoothed", 0))
    if chop > 0.55:
        red_flags += 1
        veto_reasons.append(f"choppy ({chop:.2f})")

    # Flag 6: Fee drag
    fee_drag = meta.get("fee_drag_pct", 0)
    if fee_drag > 20:
        red_flags += 1
        veto_reasons.append(f"fee drag {fee_drag:.0f}%")

    # Veto if 3+ red flags
    if red_flags >= 3:
        decision.action = "skip"
        decision.reason = f"CRITIC VETO ({red_flags} flags): " + "; ".join(veto_reasons)
        decision.skip_reasons.extend(veto_reasons)
        return decision

    # Reduce size if 2 flags
    if red_flags >= 2:
        decision.size_mult = round(decision.size_mult * 0.6, 2)
        decision.reason += f" | CRITIC WARNING ({red_flags} flags): " + "; ".join(veto_reasons)

    return decision


# ─── Full Pipeline ──────────────────────────────────────────────

# Track last signal outcome per symbol for sequential momentum
_last_signal_won: dict = {}


def run_simulated_pipeline(
    signal,
    equity: float = 500.0,
    df_1h=None,
) -> SimDecision:
    """Run the full simulated agent pipeline on a signal.

    Regime → Trade → Risk → Critic

    Returns SimDecision with action (go/skip) and size_mult.
    """
    # Step 1: Regime classification
    regime = sim_regime_agent(signal, df_1h)

    # Step 2: Trade decision (7-gate filter)
    decision = sim_trade_agent(signal, regime, df_1h)

    # Step 3: Risk sizing
    decision = sim_risk_agent(signal, decision, equity)

    # Step 4: Critic review
    decision = sim_critic_agent(signal, decision, df_1h)

    # Step 5: Sequential momentum adjustment
    # Data: After WIN → 69% WR next signal. After LOSS → 33% WR.
    # This is a 35-point spread — massive edge.
    symbol = signal.symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "")
    last_won = _last_signal_won.get(symbol)
    if last_won is True:
        decision.size_mult = round(decision.size_mult * 1.2, 2)  # Size up after win
        decision.boost_reasons.append("after-win momentum (69% WR)")
    elif last_won is False:
        decision.size_mult = round(decision.size_mult * 0.5, 2)  # Half size after loss
        decision.skip_reasons.append("after-loss caution (33% WR)")

    return decision


def should_execute_signal(
    signal,
    equity: float = 500.0,
    df_1h=None,
) -> tuple:
    """Quick check: should this signal be executed?

    Returns (should_trade: bool, size_mult: float, reason: str)
    """
    decision = run_simulated_pipeline(signal, equity, df_1h)

    if decision.action == "skip":
        return False, 0.0, decision.reason

    return True, decision.size_mult, decision.reason


# Module-level flag
_SIM_AGENTS_ENABLED = _env_bool("SIM_AGENTS_ENABLED", False)


def is_sim_agents_enabled() -> bool:
    return _SIM_AGENTS_ENABLED


def record_signal_outcome(symbol: str, won: bool):
    """Record whether a signal's trade was profitable, for sequential momentum."""
    sym = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "")
    _last_signal_won[sym] = won


def reset_signal_state():
    """Reset sequential state (call at start of backtest)."""
    _last_signal_won.clear()
