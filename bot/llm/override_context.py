"""
Override Context: gathers full situational awareness for LLM-reasoned overrides.

When a mechanical filter blocks a signal, this module builds a complete
picture of everything the LLM needs to make an informed decision:

  1. What blocked it (block type + exact numbers)
  2. Signal quality (confidence, strategies, regime, volume)
  3. Historical edge data for this symbol+side+regime
  4. Current portfolio state (equity, positions, recent performance)
  5. Market context (volatility, trend, cross-market)
  6. Existential stakes (survival mode, recent WR, API budget)

The LLM reads this context and decides: is the block wrong?
"""

import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.llm.override_context")


@dataclass
class OverrideContext:
    """Complete context for an override decision."""

    # ── Signal identity ──
    symbol: str = ""
    side: str = ""
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit_1: float = 0.0
    take_profit_2: float = 0.0

    # ── What blocked it ──
    block_type: str = ""         # "negative_ev", "anti_roundtrip", etc.
    block_reason: str = ""       # Human-readable reason
    block_details: Dict[str, Any] = field(default_factory=dict)
    # e.g., for EV: {"ev": -0.07, "win_prob_used": 0.34, "rr": 2.0, "fee_drag": 0.07}

    # ── Signal quality ──
    confidence: float = 0.0
    num_strategies_agree: int = 0
    strategies_firing: List[str] = field(default_factory=list)
    trend_score_1h: float = 0.0
    trend_score_6h: float = 0.0

    # ── Regime ──
    regime_1h: str = ""
    regime_4h: str = ""
    regime_6h: str = ""
    regime_confidence: float = 0.0

    # ── Market context ──
    volume_ratio: float = 0.0
    chop_score: float = 0.0
    atr_pct: float = 0.0
    btc_momentum_1h: float = 0.0
    btc_momentum_24h: float = 0.0
    funding_rate: float = 0.0

    # ── Historical edge (the critical piece) ──
    edge_setup_key: str = ""     # e.g., "HYPE_BUY"
    edge_wr: float = 0.0         # Historical win rate (0-100)
    edge_pf: float = 0.0         # Profit factor
    edge_n: int = 0              # Sample size
    edge_verdict: str = ""       # "CONFIRMED_EDGE", "PROMISING_NOT_PROVEN", etc.
    edge_best_hours: str = ""    # e.g., "18-06"
    edge_regime_match: bool = False  # Does current regime match edge's best regime?

    # ── Portfolio / existential ──
    current_equity: float = 0.0
    open_positions: int = 0
    open_position_symbols: List[str] = field(default_factory=list)
    daily_pnl: float = 0.0
    recent_wr_20: float = 0.0
    survival_score: int = 100    # From survival_scorer
    consecutive_losses: int = 0

    # ── Override history ──
    recent_overrides_today: int = 0
    recent_override_accuracy: Optional[float] = None

    # ── Timing ──
    hour_utc: int = 0
    session: str = ""            # "asia", "europe", "us"
    timestamp: float = field(default_factory=time.time)

    def to_prompt_dict(self) -> Dict[str, Any]:
        """Convert to a compact dict suitable for LLM prompt injection."""
        d = {
            "signal": {
                "symbol": self.symbol,
                "side": self.side,
                "entry": round(self.entry_price, 4),
                "sl": round(self.stop_loss, 4),
                "tp1": round(self.take_profit_1, 4),
                "tp2": round(self.take_profit_2, 4),
                "confidence": round(self.confidence, 1),
                "n_strategies_agree": self.num_strategies_agree,
                "strategies": self.strategies_firing,
            },
            "block": {
                "type": self.block_type,
                "reason": self.block_reason,
                "details": self.block_details,
            },
            "regime": {
                "1h": self.regime_1h,
                "4h": self.regime_4h,
                "6h": self.regime_6h,
                "confidence": round(self.regime_confidence, 2),
                "trend_score_1h": round(self.trend_score_1h, 2),
                "trend_score_6h": round(self.trend_score_6h, 2),
            },
            "market": {
                "volume_ratio": round(self.volume_ratio, 2),
                "chop_score": round(self.chop_score, 2),
                "atr_pct": round(self.atr_pct, 3),
                "btc_1h_pct": round(self.btc_momentum_1h, 2),
                "btc_24h_pct": round(self.btc_momentum_24h, 2),
                "funding_bps": round(self.funding_rate * 10000, 1),
            },
            "historical_edge": {
                "setup_key": self.edge_setup_key,
                "wr_pct": round(self.edge_wr, 1),
                "pf": round(self.edge_pf, 2),
                "sample_size": self.edge_n,
                "verdict": self.edge_verdict,
                "best_hours_utc": self.edge_best_hours,
                "regime_matches_best": self.edge_regime_match,
            } if self.edge_n > 0 else None,
            "portfolio": {
                "equity": round(self.current_equity, 2),
                "open_positions": self.open_positions,
                "open_symbols": self.open_position_symbols,
                "daily_pnl": round(self.daily_pnl, 2),
                "recent_wr_20": round(self.recent_wr_20, 1),
                "survival_score": self.survival_score,
                "consecutive_losses": self.consecutive_losses,
            },
            "timing": {
                "hour_utc": self.hour_utc,
                "session": self.session,
                "in_edge_best_hours": self._hour_in_best_hours(),
            },
            "override_history": {
                "overrides_today": self.recent_overrides_today,
                "recent_accuracy": self.recent_override_accuracy,
            },
        }
        return d

    def _hour_in_best_hours(self) -> Optional[bool]:
        """Check if current hour falls within the edge's best hours window."""
        if not self.edge_best_hours or "-" not in self.edge_best_hours:
            return None
        try:
            parts = self.edge_best_hours.split("-")
            start = int(parts[0])
            end = int(parts[1])
            if start <= end:
                return start <= self.hour_utc <= end
            else:  # Wraparound (e.g., "18-06")
                return self.hour_utc >= start or self.hour_utc <= end
        except Exception:
            return None


def build_override_context(
    symbol: str,
    side: str,
    block_type: str,
    block_reason: str,
    block_details: Dict[str, Any],
    signal: Any = None,
    market_snapshot: Optional[Dict] = None,
    portfolio_state: Optional[Dict] = None,
) -> OverrideContext:
    """Factory: build a complete OverrideContext from available state.

    This is called at the block site (ensemble.py EV block, anti-roundtrip, etc.)
    Pulls data from whatever's available — missing fields are fine (will default).
    """
    from datetime import datetime, timezone

    ctx = OverrideContext(
        symbol=symbol,
        side=side,
        block_type=block_type,
        block_reason=block_reason,
        block_details=dict(block_details) if block_details else {},
    )

    now = datetime.now(timezone.utc)
    ctx.hour_utc = now.hour
    if 0 <= ctx.hour_utc < 8:
        ctx.session = "asia"
    elif 8 <= ctx.hour_utc < 16:
        ctx.session = "europe"
    else:
        ctx.session = "us"

    # Pull from signal object if provided
    if signal is not None:
        ctx.entry_price = getattr(signal, "entry", 0.0) or 0.0
        ctx.stop_loss = getattr(signal, "sl", 0.0) or 0.0
        ctx.take_profit_1 = getattr(signal, "tp1", 0.0) or 0.0
        ctx.take_profit_2 = getattr(signal, "tp2", 0.0) or 0.0
        ctx.confidence = getattr(signal, "confidence", 0.0) or 0.0
        metadata = getattr(signal, "metadata", {}) or {}
        ctx.num_strategies_agree = metadata.get("num_agree", 1)
        ctx.volume_ratio = metadata.get("volume_ratio", 1.0)
        ctx.chop_score = metadata.get("chop_score", 0.0)
        ctx.regime_1h = metadata.get("regime", "")

    # RIP-OUT P3 (measurement-integrity, 2026-07-21): edge data used to be pulled
    # here from deep_memory key '_quant_backtest_2026_03_26', which has no writer
    # in the live strategy_fingerprints store (dead — lookup always returned {},
    # so ctx.edge_* fields were never actually set; they keep their dataclass
    # defaults). Dead try/except removed. See strategies/ensemble.py:230-236 for
    # the scoped-in-file replacement that already documented this as dead.

    # Pull portfolio state if provided
    if portfolio_state:
        ctx.current_equity = portfolio_state.get("equity", 0.0)
        ctx.open_positions = portfolio_state.get("open_positions", 0)
        ctx.open_position_symbols = portfolio_state.get("open_symbols", [])
        ctx.daily_pnl = portfolio_state.get("daily_pnl", 0.0)
        ctx.recent_wr_20 = portfolio_state.get("recent_wr_20", 0.0)
        ctx.survival_score = portfolio_state.get("survival_score", 100)
        ctx.consecutive_losses = portfolio_state.get("consecutive_losses", 0)

    # Pull override history
    try:
        from llm.override_ledger import get_override_ledger
        ledger = get_override_ledger()
        stats = ledger.get_stats()
        ctx.recent_override_accuracy = stats.get("recent_accuracy_20")
        # Count today's overrides
        today_start = time.time() - 86400
        ctx.recent_overrides_today = sum(
            1 for r in ledger._records.values()
            if r.timestamp >= today_start and r.override_approved
        )
    except Exception as e:
        logger.debug(f"[OVERRIDE-CTX] Ledger unavailable: {e}")

    return ctx
