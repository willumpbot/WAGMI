"""
Core types for the LLM meta-brain decision pipeline.

These types define the contract between:
  - the Python bot (producer of MarketSnapshot + GlobalContext)
  - the LLM (consumer of snapshots, producer of LLMDecision)
  - the risk gating layer (consumer of LLMDecision)

All fields are plain types (no numpy, no pandas) so they serialize cleanly to JSON.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


# ── Regime taxonomy ──────────────────────────────────────────────

class Regime(str, Enum):
    """Market regime classifications.

    Each regime maps to distinct strategy weighting and risk posture.
    The LLM classifies regime based on the numeric rubric below.
    """
    TREND = "trend"
    RANGE = "range"
    PANIC = "panic"
    HIGH_VOLATILITY = "high_volatility"
    LOW_LIQUIDITY = "low_liquidity"
    NEWS_DISLOCATION = "news_dislocation"
    UNKNOWN = "unknown"


# ── Regime rubric (numeric thresholds for consistent classification) ──

REGIME_RUBRIC: Dict[str, Dict[str, str]] = {
    "trend": {
        "volatility": "ATR > 1.2x 20-period average (directional, not chaotic)",
        "volume": "Sustained above average for 3+ candles",
        "oi": "Expanding (new money entering, trend continuation)",
        "funding": "Aligned with direction (positive for longs, negative for shorts)",
        "cross_asset": "BTC and target asset moving same direction",
        "summary": "Directional move with conviction. OI expanding, volume confirming.",
    },
    "range": {
        "volatility": "ATR < 0.8x average OR price oscillating within 2% band (1h)",
        "volume": "Declining or below 0.7x average",
        "oi": "Flat or slightly declining",
        "funding": "Near neutral (< 0.01% / 8h)",
        "cross_asset": "Mixed signals, no clear leader",
        "summary": "Choppy, mean-reverting. No edge for directional trades.",
    },
    "panic": {
        "volatility": "Price drop > 5% in 1h OR > 8% in 4h",
        "volume": "Spike > 3x average",
        "oi": "Contracting rapidly (forced liquidations)",
        "funding": "Deeply negative (< -0.05% / 8h)",
        "cross_asset": "Broad-based selloff, BTC leading down",
        "summary": "Liquidation cascade. Only trade with extreme conviction or stay flat.",
    },
    "high_volatility": {
        "volatility": "ATR > 2x 20-period average",
        "volume": "Elevated but not panic-level",
        "oi": "Mixed (not clearly contracting)",
        "funding": "Volatile, swinging between positive and negative",
        "cross_asset": "Correlations unstable",
        "summary": "Big moves both directions. Widen stops, reduce size, or stay flat.",
    },
    "low_liquidity": {
        "volatility": "Low absolute ATR but wide candle wicks",
        "volume": "< 0.3x average",
        "oi": "Low or declining",
        "funding": "Stale (barely moving)",
        "cross_asset": "Most assets flat, thin books",
        "summary": "Weekend/holiday/dead market. Avoid trading, spreads are wide.",
    },
    "news_dislocation": {
        "volatility": "Sudden spike with no prior technical setup",
        "volume": "Spike with no OI change (spot-driven, not perp)",
        "oi": "Unchanged (move is external, not from leveraged positioning)",
        "funding": "Lagging (hasn't adjusted yet)",
        "cross_asset": "Isolated to 1-2 assets, not broad-based",
        "summary": "External catalyst. Expect mean reversion. Don't chase.",
    },
    "unknown": {
        "summary": "Conflicting signals, unclear structure. Default to flat.",
    },
}


# ── Strategy weight keys ─────────────────────────────────────────

STRATEGY_WEIGHT_KEYS = [
    "regime_trend",
    "monte_carlo_zones",
    "confidence_scorer",
    "multi_tier_quality",
]

# Extended strategy influences the LLM can weight
EXTENDED_WEIGHT_KEYS = [
    "regime_trend",
    "monte_carlo_zones",
    "confidence_scorer",
    "multi_tier_quality",
    "funding_rate",
    "open_interest",
    "volume_momentum",
    "cross_asset",
]


# ── Core decision types ──────────────────────────────────────────

@dataclass
class StrategyWeights:
    """Per-strategy weight recommendations from the LLM.

    Each weight is 0.0-1.0 where:
      0.0 = ignore this strategy entirely
      0.5 = default / neutral weight
      1.0 = maximum trust in this strategy

    The bot's ensemble uses these to scale each strategy's vote.
    """
    regime_trend: float = 0.5
    monte_carlo_zones: float = 0.5
    confidence_scorer: float = 0.5
    multi_tier_quality: float = 0.5
    funding_rate: float = 0.0
    open_interest: float = 0.0
    volume_momentum: float = 0.0
    cross_asset: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "regime_trend": self.regime_trend,
            "monte_carlo_zones": self.monte_carlo_zones,
            "confidence_scorer": self.confidence_scorer,
            "multi_tier_quality": self.multi_tier_quality,
            "funding_rate": self.funding_rate,
            "open_interest": self.open_interest,
            "volume_momentum": self.volume_momentum,
            "cross_asset": self.cross_asset,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, float]) -> "StrategyWeights":
        return cls(**{k: d.get(k, 0.5) for k in EXTENDED_WEIGHT_KEYS})


@dataclass
class LLMDecision:
    """The structured output the LLM must produce.

    This is the ONLY format accepted. Anything else is rejected.
    """
    action: str              # "long", "short", or "flat"
    confidence: float        # 0.0 - 1.0
    regime: str              # one of Regime values
    strategy_weights: StrategyWeights
    memory_update: Optional[str]  # short note for persistent memory, or null
    notes: str               # brief explanation of reasoning

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "confidence": self.confidence,
            "regime": self.regime,
            "strategy_weights": self.strategy_weights.to_dict(),
            "memory_update": self.memory_update,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LLMDecision":
        sw = d.get("strategy_weights", {})
        return cls(
            action=d.get("action", "flat"),
            confidence=d.get("confidence", 0.0),
            regime=d.get("regime", "unknown"),
            strategy_weights=StrategyWeights.from_dict(sw) if isinstance(sw, dict) else StrategyWeights(),
            memory_update=d.get("memory_update"),
            notes=d.get("notes", ""),
        )


# ── Snapshot types (what the LLM receives) ───────────────────────

@dataclass
class StrategySignal:
    """One strategy's assessment of one symbol."""
    symbol: str
    strategy: str             # "regime_trend", "monte_carlo_zones", etc.
    side: str                 # "long", "short", "neutral"
    confidence: float         # 0.0 - 1.0
    regime_score: float = 0.0
    volatility_score: float = 0.0
    quality_score: float = 0.0
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MarketSnapshot:
    """Current state of one tradeable symbol."""
    symbol: str
    price: float
    price_change_1h_pct: float = 0.0
    price_change_24h_pct: float = 0.0
    volume_ratio: float = 1.0     # current / 20-period avg
    volatility: float = 0.0       # ATR / price as pct
    funding_rate: Optional[float] = None
    open_interest_change_pct: Optional[float] = None
    signals: List[StrategySignal] = field(default_factory=list)


@dataclass
class GlobalContext:
    """Cross-market and macro context."""
    timestamp: int                 # unix ms
    btc_price: float = 0.0
    btc_change_1h_pct: float = 0.0
    btc_change_24h_pct: float = 0.0
    eth_btc_ratio: float = 0.0    # ETH/BTC for alt season detection
    total_open_positions: int = 0
    daily_pnl: float = 0.0
    equity: float = 10000.0
    circuit_breaker_active: bool = False


@dataclass
class LLMInputSnapshot:
    """The complete context sent to the LLM. Nothing else."""
    markets: List[MarketSnapshot]
    global_context: GlobalContext
    memory_summary: Optional[str] = None
    active_positions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "markets": [
                {
                    "symbol": m.symbol,
                    "price": m.price,
                    "price_change_1h_pct": round(m.price_change_1h_pct, 2),
                    "price_change_24h_pct": round(m.price_change_24h_pct, 2),
                    "volume_ratio": round(m.volume_ratio, 2),
                    "volatility": round(m.volatility, 3),
                    "funding_rate": m.funding_rate,
                    "oi_change_pct": m.open_interest_change_pct,
                    "signals": [
                        {
                            "strategy": s.strategy,
                            "side": s.side,
                            "confidence": round(s.confidence, 2),
                            **({"regime": round(s.regime_score, 2)} if s.regime_score else {}),
                            **({"meta": s.meta} if s.meta else {}),
                        }
                        for s in m.signals
                    ],
                }
                for m in self.markets
            ],
            "global": {
                "timestamp": self.global_context.timestamp,
                "btc_price": self.global_context.btc_price,
                "btc_1h": round(self.global_context.btc_change_1h_pct, 2),
                "btc_24h": round(self.global_context.btc_change_24h_pct, 2),
                "eth_btc": round(self.global_context.eth_btc_ratio, 4),
                "positions": self.global_context.total_open_positions,
                "daily_pnl": round(self.global_context.daily_pnl, 2),
                "equity": round(self.global_context.equity, 2),
                "cb_active": self.global_context.circuit_breaker_active,
            },
            **({"memory": self.memory_summary} if self.memory_summary else {}),
            **({"open_positions": self.active_positions} if self.active_positions else {}),
        }
