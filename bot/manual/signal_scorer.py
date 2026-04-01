"""
Signal Quality Scorer for Manual Sniper System.

Scores each signal 0-100 based on multiple factors that predict
trade success. Higher score = higher conviction = trade with more size.

Factors (from overnight research + counterfactual + edge study):
- Setup match: HYPE BUY (weakening, 52% WR) > BTC BUY > SOL SELL (marginal) >> everything else
- Volatility regime: strongest profitability predictor (HYPE optimal at High Vol ATR% 1.40-1.69%)
- Chop score: lower = cleaner market = better entries
- Dip-buy: 2-5% dip from recent high = 88.5% WR
- Time of day: 18-06 UTC = PF 2.47 vs 06-18 UTC = PF 1.29
- Consensus: 3-agree > 2-agree (2x WR validated)
- RSI zone: 35-65 sweet spot (62-64% WR). <30 = panic. >75 = overbought.
- Win probability: sub-48% = negative EV after fees
- Funding rate: structural edge when confirming direction
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("bot.manual.signal_scorer")


def score_signal(
    symbol: str,
    side: str,
    confidence: float,
    num_agree: int,
    chop: float,
    ev_per_dollar: float,
    regime: str,
    is_dip_buy: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Score a signal 0-100 for trade quality.

    Returns:
        {
            "score": 0-100,
            "grade": "A+" / "A" / "B" / "C" / "F",
            "factors": {factor: score_contribution},
            "recommendation": "FIRE" / "TAKE" / "CAUTIOUS" / "SKIP",
            "size_multiplier": 0.5-1.5x
        }
    """
    meta = metadata or {}
    score = 0
    factors = {}

    # 1. SETUP MATCH (40 points max)
    # This is the strongest predictor — updated from comprehensive edge study 2026-03-27
    setup_key = f"{symbol}_{side}"
    setup_scores = {
        "HYPE_BUY": 30,    # Edge WEAKENING (64%→40%). Downgraded from 40. Requires optimal vol regime.
        "SOL_SELL": 30,     # Edge STRENGTHENING (35%→68%). Upgraded from 15. Best at Normal Vol.
        "BTC_BUY": 10,      # 56% WR, PF 1.40 over 30 days. Not yet proven live.
        "BTC_SELL": 5,       # Confirmed negative EV overall. Only marginal at 90%+ conf.
        "SOL_BUY": 3,       # No validated edge. Discovery only at 70-75% conf band.
    }
    setup_score = setup_scores.get(setup_key, 0)
    # HYPE_SELL = 0 (toxic)
    if setup_key == "HYPE_SELL":
        return {
            "score": 0, "grade": "F", "factors": {"toxic_setup": -100},
            "recommendation": "SKIP", "size_multiplier": 0
        }
    score += setup_score
    factors["setup"] = setup_score

    # 2. CHOP SCORE (20 points max)
    # Lower chop = cleaner market = better entries
    if chop <= 0.15:
        chop_pts = 20
    elif chop <= 0.25:
        chop_pts = 16
    elif chop <= 0.35:
        chop_pts = 10
    elif chop <= 0.45:
        chop_pts = 4
    else:
        chop_pts = 0
    score += chop_pts
    factors["chop"] = chop_pts

    # 3. DIP-BUY BONUS (15 points)
    if is_dip_buy and side == "BUY":
        dip_pts = 15
        score += dip_pts
        factors["dip_buy"] = dip_pts

    # 4. CONSENSUS (10 points max)
    if num_agree >= 3:
        agree_pts = 10
    elif num_agree >= 2:
        agree_pts = 5
    else:
        agree_pts = 0
    score += agree_pts
    factors["consensus"] = agree_pts

    # 5. EV PER DOLLAR (10 points max)
    if ev_per_dollar >= 0.4:
        ev_pts = 10
    elif ev_per_dollar >= 0.2:
        ev_pts = 6
    elif ev_per_dollar >= 0.1:
        ev_pts = 3
    else:
        ev_pts = 0
    score += ev_pts
    factors["ev"] = ev_pts

    # 6. REGIME BONUS (5 points)
    strong_regimes = {"consolidation", "trend", "trending_bull"}
    if regime.lower() in strong_regimes:
        regime_pts = 5
        score += regime_pts
        factors["regime"] = regime_pts

    # 7. RSI ZONE (10 points max, -10 penalty)
    # Data: RSI 35-65 = 62-64% WR (sweet spot). RSI<35 = 50% WR. RSI>70 = reversal risk.
    rsi_val = meta.get("rsi")
    if rsi_val is not None and isinstance(rsi_val, (int, float)):
        if 40 <= rsi_val <= 60:
            rsi_pts = 10  # Dead center sweet spot
        elif 35 <= rsi_val <= 65:
            rsi_pts = 6   # Sweet spot edges
        elif 30 <= rsi_val < 35 or 65 < rsi_val <= 70:
            rsi_pts = 0   # Neutral — approaching danger
        else:
            rsi_pts = -10  # Oversold (<30) or overbought (>70) — WR drops to 50%
        score += rsi_pts
        factors["rsi"] = rsi_pts

    # 8. TIME OF DAY (5 points)
    # Data: 18-06 UTC = PF 2.47 vs 06-18 UTC = PF 1.29
    from datetime import datetime, timezone
    current_hour = datetime.now(timezone.utc).hour
    if current_hour >= 18 or current_hour < 6:
        tod_pts = 5  # Prime hours
        score += tod_pts
        factors["time_of_day"] = tod_pts

    # 9. WIN PROBABILITY (10 points max, -15 penalty)
    # The bot's own win probability estimate — trades 2&3 lost at 42% and 40%.
    win_prob = meta.get("win_prob", meta.get("win_prob_deflated"))
    if win_prob is not None and isinstance(win_prob, (int, float)):
        if win_prob >= 0.60:
            wp_pts = 10  # Strong edge
        elif win_prob >= 0.55:
            wp_pts = 7
        elif win_prob >= 0.50:
            wp_pts = 3   # Marginal
        elif win_prob >= 0.45:
            wp_pts = -5  # Below coin flip
        else:
            wp_pts = -15  # Strongly negative EV
        score += wp_pts
        factors["win_prob"] = wp_pts

    # 10. FUNDING RATE EDGE (10 points max, -10 penalty)
    # When funding confirms our direction, it's a structural tailwind:
    # - SELL + positive funding = shorts earn + longs overcrowded = edge
    # - BUY + negative funding = longs earn + shorts overcrowded = edge
    # When funding opposes, we're paying and fighting crowded positioning.
    funding_rate = meta.get("funding_rate")
    if funding_rate is not None and isinstance(funding_rate, (int, float)):
        abs_fr = abs(funding_rate)
        if abs_fr >= 0.0002:  # Non-trivial funding
            funding_favors = (
                (side == "SELL" and funding_rate > 0) or
                (side == "BUY" and funding_rate < 0)
            )
            funding_against = (
                (side == "BUY" and funding_rate > 0) or
                (side == "SELL" and funding_rate < 0)
            )
            if funding_favors:
                if abs_fr >= 0.0005:  # Extreme funding in our favor
                    fr_pts = 10
                else:
                    fr_pts = 5
            elif funding_against:
                if abs_fr >= 0.0005:  # Extreme funding against us
                    fr_pts = -10
                else:
                    fr_pts = -3
            else:
                fr_pts = 0
            score += fr_pts
            factors["funding"] = fr_pts

    # 11. VOLATILITY REGIME (15 points max, -15 penalty)
    # Comprehensive edge study: vol regime is the strongest profitability predictor.
    # HYPE BUY optimal at High Vol (ATR% 1.40-1.69%): PF=3.51, WR=73.9%.
    # HYPE BUY at Extreme Vol (ATR%>1.90%): PF=0.65 = NEGATIVE EV.
    # SOL SELL optimal at Normal Vol (ATR% 0.80-0.98%): PF=1.75, WR=61.5%.
    # SOL SELL at High+ Vol (ATR%>1.20%): PF<0.72 = negative EV.
    atr_val = meta.get("atr")
    entry_price = meta.get("entry", meta.get("price", 0))
    if atr_val is not None and entry_price and entry_price > 0:
        try:
            atr_pct = (float(atr_val) / float(entry_price)) * 100.0
            vol_pts = 0
            if setup_key == "HYPE_BUY":
                if 1.40 <= atr_pct <= 1.69:
                    vol_pts = 15   # Optimal vol: PF 3.51
                elif 1.15 <= atr_pct < 1.40:
                    vol_pts = 3    # Low vol: PF 1.22
                elif 1.69 < atr_pct <= 1.90:
                    vol_pts = -5   # Very high: PF 1.03, marginal
                elif atr_pct > 1.90:
                    vol_pts = -15  # Extreme: PF 0.65, NEGATIVE EV
            elif setup_key == "SOL_SELL":
                if 0.80 <= atr_pct <= 0.98:
                    vol_pts = 15   # Optimal vol: PF 1.75
                elif atr_pct < 0.80:
                    vol_pts = 8    # Low vol: PF 1.56
                elif 0.98 < atr_pct <= 1.20:
                    vol_pts = -3   # Elevated: transition zone
                elif atr_pct > 1.20:
                    vol_pts = -15  # High+: PF <0.72, negative EV
            elif setup_key == "BTC_BUY":
                if 0.92 <= atr_pct <= 1.03:
                    vol_pts = 15   # Very high vol: PF 3.13
                elif atr_pct < 0.77:
                    vol_pts = -10  # Low/normal: PF <0.80
            score += vol_pts
            factors["vol_regime"] = vol_pts
        except (ValueError, TypeError):
            pass

    # 12. BTC-HYPE CORRELATION (10 points max, -10 penalty)
    # Medium corr (0.5-0.7) = PF 2.05. High corr (>0.7) = PF 0.59 (kills HYPE edge).
    btc_corr = meta.get("btc_correlation", meta.get("btc_hype_corr"))
    if btc_corr is not None and setup_key.startswith("HYPE"):
        try:
            corr_val = float(btc_corr)
            if 0.5 <= corr_val <= 0.7:
                corr_pts = 10  # Sweet spot
            elif 0.3 <= corr_val < 0.5:
                corr_pts = 3   # Low: PF 1.07
            elif corr_val > 0.7:
                corr_pts = -10  # High: PF 0.59, edge dies
            else:
                corr_pts = 0   # Decorrelated: PF 0.99
            score += corr_pts
            factors["btc_corr"] = corr_pts
        except (ValueError, TypeError):
            pass

    # Grade and recommendation
    if score >= 80:
        grade = "A+"
        recommendation = "FIRE"       # Max conviction, full size
        size_mult = 1.3
    elif score >= 65:
        grade = "A"
        recommendation = "TAKE"       # Strong, standard size
        size_mult = 1.0
    elif score >= 45:
        grade = "B"
        recommendation = "CAUTIOUS"   # Decent, half size
        size_mult = 0.7
    elif score >= 25:
        grade = "C"
        recommendation = "CAUTIOUS"   # Marginal, quarter size
        size_mult = 0.5
    else:
        grade = "F"
        recommendation = "SKIP"
        size_mult = 0

    return {
        "score": min(score, 100),
        "grade": grade,
        "factors": factors,
        "recommendation": recommendation,
        "size_multiplier": size_mult,
    }


def format_score_line(score_result: Dict[str, Any]) -> str:
    """One-line score summary for alerts."""
    s = score_result
    return f"Score: {s['score']}/100 ({s['grade']}) | {s['recommendation']} | Size: {s['size_multiplier']:.1f}x"
