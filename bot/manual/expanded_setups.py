"""
Expanded Setup Definitions for the Sniper Filter

Generated: 2026-03-24
Source: SYMBOL_RESEARCH.md analysis of 965 backtest trades + 1000 counterfactual records

These setups have been identified as positive-EV through cross-tabulation of
symbol x side x confidence band from backtest data. Each setup includes the
minimum conditions required for the edge to exist.

IMPORTANT: These are RESEARCH RESULTS, not yet validated out-of-sample.
Paper trade each setup for 30+ trades before committing real capital.

Usage:
    from manual.expanded_setups import EXPANDED_SETUPS, CURRENT_SETUPS, AVOID_LIST
"""

# =============================================================================
# CURRENT SETUPS (already in sniper filter, confirmed edge)
# =============================================================================
CURRENT_SETUPS = [
    {
        "name": "HYPE_BUY_SNIPER",
        "symbol": "HYPE",
        "side": "BUY",
        "min_confidence": 85,
        "max_confidence": 100,
        "min_agree": 3,
        "regimes": None,  # Currently no regime gate -- SEE NOTE BELOW
        "expected_wr": 0.88,
        "expected_pf": 12.07,
        "sample_size": 201,  # counterfactual
        "ev_per_trade_pct": 4.75,
        "size_multiplier": 1.0,  # Full size
        "max_leverage": 16,
        "grade": "A+",
        "notes": (
            "WARNING: 88% WR is from counterfactual data during a HYPE rally. "
            "Backtest shows only 57% WR for HYPE LONG overall. "
            "Consider adding regime gate: only take in trend/trending_bull. "
            "Without regime gate, this setup is likely overfit to bullish conditions."
        ),
    },
    {
        "name": "SOL_SELL_SNIPER",
        "symbol": "SOL",
        "side": "SELL",
        "min_confidence": 65,
        "max_confidence": 100,
        "min_agree": 3,
        "regimes": None,
        "expected_wr": 0.62,
        "expected_pf": 2.12,
        "sample_size": 225,  # counterfactual
        "ev_per_trade_pct": 0.99,
        "size_multiplier": 1.0,
        "max_leverage": 6,
        "grade": "B",
        "notes": "Solid edge. Consider upgrading to conf >= 80 for full size (PF jumps to 3.41).",
    },
]

# =============================================================================
# NEW SETUPS (research-identified, need paper trading validation)
# =============================================================================
EXPANDED_SETUPS = [
    # -------------------------------------------------------------------
    # SETUP 1: BTC SHORT at very high confidence (>=90)
    # Evidence: 43 backtest trades, 67.4% WR, PF 1.98, +$103 avg
    # The 70-80% confidence zone is a DEATH TRAP (PF 0.31-0.79)
    # Only the >=90 tier is profitable — the filter is NON-NEGOTIABLE
    # -------------------------------------------------------------------
    {
        "name": "BTC_SHORT_HIGH_CONF",
        "symbol": "BTC",
        "side": "SELL",
        "min_confidence": 90,
        "max_confidence": 100,
        "min_agree": 3,
        "regimes": None,  # Works across regimes when confidence is this high
        "expected_wr": 0.674,
        "expected_pf": 1.98,
        "sample_size": 43,
        "ev_per_trade_pct": 2.5,  # Estimated from avg pnl / position size
        "size_multiplier": 0.6,  # 60% of HYPE BUY size (lower edge)
        "max_leverage": 8,
        "grade": "B+",
        "notes": (
            "NEVER relax below 90% confidence. "
            "BTC SHORT at 70-80% conf has PF 0.31-0.79 = massive losses. "
            "The 90% threshold is the ONLY thing making this profitable. "
            "Expect ~0.5-1 signals per day."
        ),
        "validation_status": "NEEDS_PAPER_TRADING",
        "min_paper_trades_required": 30,
    },
    # -------------------------------------------------------------------
    # SETUP 2: SOL SELL at high confidence (>=80) — upgrade of existing
    # Evidence: 32 backtest trades, 75% WR, PF 3.41, +$59 avg
    # This is the existing SOL SELL with a tighter confidence gate
    # At conf >= 80, profit factor nearly DOUBLES (3.41 vs 1.73)
    # -------------------------------------------------------------------
    {
        "name": "SOL_SELL_HIGH_CONF",
        "symbol": "SOL",
        "side": "SELL",
        "min_confidence": 80,
        "max_confidence": 100,
        "min_agree": 3,
        "regimes": None,
        "expected_wr": 0.75,
        "expected_pf": 3.41,
        "sample_size": 32,
        "ev_per_trade_pct": 1.8,
        "size_multiplier": 1.0,  # Full size at this confidence
        "max_leverage": 10,
        "grade": "A+",
        "notes": (
            "Upgrade path for existing SOL SELL. "
            "Keep SOL SELL at conf 65-79 at 50% size. "
            "Boost to full size when conf >= 80."
        ),
        "validation_status": "HIGH_CONFIDENCE",  # Subset of proven setup
        "min_paper_trades_required": 15,
    },
    # -------------------------------------------------------------------
    # SETUP 3: BTC LONG in the 70-80% confidence band
    # Evidence: 49 trades, 69.4% WR, PF 1.85, +$73 avg
    # CRITICAL: Must cap at conf < 85. High-conf BTC LONG fails badly.
    # BTC LONG at 85-90: N=4, PF=0.40 (disaster)
    # BTC LONG at 90+: N=4, PF=0.60 (still bad)
    # The sweet spot is MODERATE confidence (70-80)
    # -------------------------------------------------------------------
    {
        "name": "BTC_LONG_MODERATE_CONF",
        "symbol": "BTC",
        "side": "BUY",
        "min_confidence": 70,
        "max_confidence": 80,  # HARD CAP — do not raise
        "min_agree": 2,
        "regimes": ["trend", "trending_bull", "consolidation"],
        "expected_wr": 0.694,
        "expected_pf": 1.85,
        "sample_size": 49,
        "ev_per_trade_pct": 1.5,
        "size_multiplier": 0.4,  # 40% of HYPE BUY size (cautious)
        "max_leverage": 5,
        "grade": "B+",
        "notes": (
            "COUNTERINTUITIVE: BTC LONG gets WORSE above 85% confidence. "
            "This suggests the system buys tops when overly bullish. "
            "The 70-80% sweet spot = moderate conviction in trending regimes. "
            "USE MAX_CONFIDENCE CAP. Expect ~0.5-1 signals per day."
        ),
        "validation_status": "NEEDS_PAPER_TRADING",
        "min_paper_trades_required": 30,
    },
]

# =============================================================================
# MONITORING LIST (marginally positive, need more data)
# =============================================================================
MONITORING_SETUPS = [
    {
        "name": "SOL_LONG_70_75",
        "symbol": "SOL",
        "side": "BUY",
        "min_confidence": 70,
        "max_confidence": 75,
        "min_agree": 2,
        "regimes": ["trend", "trending_bull"],
        "expected_wr": 0.638,
        "expected_pf": 1.56,
        "sample_size": 47,
        "notes": (
            "Marginally positive. PF 1.56 is decent but WR drops fast outside this band. "
            "SOL LONG at 65-70 has 14% WR (disaster). "
            "SOL LONG at 90+ has 25% WR (also disaster). "
            "Only the narrow 70-75 band works. Needs 30 more trades to confirm."
        ),
        "validation_status": "INSUFFICIENT_DATA",
        "min_paper_trades_required": 50,
    },
    {
        "name": "BTC_SHORT_65_70",
        "symbol": "BTC",
        "side": "SELL",
        "min_confidence": 65,
        "max_confidence": 70,
        "min_agree": 2,
        "regimes": None,
        "expected_wr": 0.643,
        "expected_pf": 1.56,
        "sample_size": 28,
        "notes": (
            "Interesting: BTC SHORT at LOW confidence (65-70) has decent edge. "
            "But the 70-80 band is terrible (PF 0.31-0.79). "
            "This could be a statistical artifact. Monitor but don't trade."
        ),
        "validation_status": "SUSPICIOUS_PATTERN",
        "min_paper_trades_required": 50,
    },
]

# =============================================================================
# HARD AVOID LIST (confirmed negative EV at all confidence levels)
# =============================================================================
AVOID_LIST = [
    {
        "name": "HYPE_SELL",
        "symbol": "HYPE",
        "side": "SELL",
        "reason": (
            "0% WR in counterfactual (173 records), "
            "PF < 1.0 at EVERY confidence band in backtest (239 trades), "
            "even 90%+ confidence has 42% WR and PF 0.57. "
            "The system is systematically wrong on HYPE shorts."
        ),
    },
    {
        "name": "BTC_SHORT_70_80",
        "symbol": "BTC",
        "side": "SELL",
        "min_confidence": 70,
        "max_confidence": 80,
        "reason": (
            "The single largest dollar loser in the backtest. "
            "N=98, PF=0.31-0.79, total loss = -$9,003 over 90 days. "
            "NEVER relax the BTC SHORT confidence floor below 90."
        ),
    },
    {
        "name": "SOL_LONG_HIGH_CONF",
        "symbol": "SOL",
        "side": "BUY",
        "min_confidence": 85,
        "max_confidence": 100,
        "reason": (
            "SOL LONG at 85-90%: PF=0.82, N=6. "
            "SOL LONG at 90+: PF=0.37, WR=25%, N=8. "
            "High confidence SOL longs are consistently wrong."
        ),
    },
    {
        "name": "BTC_LONG_HIGH_CONF",
        "symbol": "BTC",
        "side": "BUY",
        "min_confidence": 85,
        "max_confidence": 100,
        "reason": (
            "BTC LONG at 85-90%: PF=0.40, N=4. "
            "BTC LONG at 90+: PF=0.60, N=4. "
            "Small sample but consistent: high-conf BTC longs buy tops."
        ),
    },
]


def get_all_tradeable_setups():
    """Return all setups that are ready to trade (current + validated expanded)."""
    ready = list(CURRENT_SETUPS)
    for setup in EXPANDED_SETUPS:
        if setup.get("validation_status") == "HIGH_CONFIDENCE":
            ready.append(setup)
    return ready


def get_setups_needing_validation():
    """Return setups that need paper trading validation before going live."""
    return [
        s for s in EXPANDED_SETUPS
        if s.get("validation_status") in ("NEEDS_PAPER_TRADING",)
    ] + MONITORING_SETUPS


def is_avoided(symbol: str, side: str, confidence: float) -> bool:
    """Check if a symbol/side/confidence combo is on the avoid list."""
    for avoid in AVOID_LIST:
        if avoid["symbol"] == symbol and avoid["side"] == side:
            min_c = avoid.get("min_confidence", 0)
            max_c = avoid.get("max_confidence", 100)
            if min_c <= confidence <= max_c:
                return True
    return False


def match_setup(symbol: str, side: str, confidence: float, num_agree: int = 1):
    """Find the best matching setup for a signal, or None if no match."""
    # Check avoid list first
    if is_avoided(symbol, side, confidence):
        return None

    best = None
    best_pf = 0

    all_setups = CURRENT_SETUPS + EXPANDED_SETUPS
    for setup in all_setups:
        if (setup["symbol"] == symbol
                and setup["side"] == side
                and setup["min_confidence"] <= confidence <= setup.get("max_confidence", 100)
                and num_agree >= setup["min_agree"]
                and setup.get("expected_pf", 0) > best_pf):
            best = setup
            best_pf = setup["expected_pf"]

    return best
