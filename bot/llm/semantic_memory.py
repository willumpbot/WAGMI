"""
TIER 3.1: Semantic Memory Search

Find relevant past trades using vector similarity.

Why this matters for slow mechanical systems:
- Mechanical system generates ~10 trades/day
- Not all 10 are equal quality
- LLM can learn: "In 'range + low confidence' regime, past 7 similar trades:
  - 5 won (+$45 total)
  - 2 lost (-$10 total)
  - So reduce size by 30%"

This is pattern recognition without explicit rules.

Implementation:
1. Embed each trade: (regime, setup_type, confidence, time_of_day, volatility)
2. Store 500 recent trades with embeddings
3. On new signal, find 5 most similar past trades
4. Use their outcomes to adjust current decision

Expected impact: +0.5-1% daily by learning from past patterns
"""

import json
import logging
import os
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
import time
import math

logger = logging.getLogger("bot.llm.semantic_memory")


@dataclass
class TradeEmbedding:
    """A trade with its semantic embedding."""
    trade_id: str
    symbol: str
    timestamp: float

    # Trade context
    regime: str
    setup_type: str
    entry_confidence: float
    leverage: float
    hold_time_minutes: float

    # Outcome
    pnl: float
    win: bool

    # Embedding (normalized vector)
    embedding: List[float] = None  # Will be computed


class TradeEmbedder:
    """
    Creates semantic embeddings for trades.

    Embedding dimensions:
    1. Regime (one-hot): trend, range, panic, volatile, unknown
    2. Setup type (one-hot): 10 common setups
    3. Confidence: 0-1
    4. Leverage: 1x, 1.5x, 2x, etc.
    5. Hold time: minutes (log scale)
    6. Time of day: 0-24 (cyclical: sin/cos)
    7. Win flag: 0-1

    Total: ~15-20 dimensions
    """

    REGIMES = ["trend", "range", "panic", "volatile", "consolidation", "unknown"]
    SETUP_TYPES = [
        "multi_tier_quality", "regime_trend", "confidence_scorer",
        "monte_carlo_zones", "bollinger_squeeze", "vmc_cipher",
        "funding_rate", "oi_delta", "lead_lag", "liquidation_cascade"
    ]

    def embed_trade(
        self,
        trade_id: str,
        symbol: str,
        timestamp: float,
        regime: str,
        setup_type: str,
        entry_confidence: float,
        leverage: float,
        hold_time_minutes: float,
        pnl: float,
        win: bool,
    ) -> TradeEmbedding:
        """
        Create embedding for a trade.

        Returns normalized vector suitable for cosine similarity.
        """
        embedding = TradeEmbedding(
            trade_id=trade_id,
            symbol=symbol,
            timestamp=timestamp,
            regime=regime,
            setup_type=setup_type,
            entry_confidence=entry_confidence,
            leverage=leverage,
            hold_time_minutes=hold_time_minutes,
            pnl=pnl,
            win=win,
        )

        # Build embedding vector
        vector = []

        # 1. Regime (one-hot encoding)
        regime_lower = regime.lower()
        for r in self.REGIMES:
            vector.append(1.0 if r in regime_lower else 0.0)

        # 2. Setup type (one-hot encoding)
        for s in self.SETUP_TYPES:
            vector.append(1.0 if s == setup_type else 0.0)

        # 3. Confidence (0-1)
        vector.append(float(entry_confidence))

        # 4. Leverage (normalized)
        vector.append(min(leverage, 3.0) / 3.0)  # Cap at 3x

        # 5. Hold time (log scale, normalized)
        log_hold_time = math.log(max(hold_time_minutes, 1) + 1)
        vector.append(min(log_hold_time, 6) / 6)  # Cap log at 6

        # 6. Time of day (cyclical: hour as sin/cos)
        hour = (timestamp % 86400) / 3600  # 0-24
        vector.append(math.sin(hour * math.pi / 12))  # sin(hour * 15°)
        vector.append(math.cos(hour * math.pi / 12))  # cos(hour * 15°)

        # 7. Win (0 or 1)
        vector.append(1.0 if win else 0.0)

        # Normalize vector to unit length
        magnitude = math.sqrt(sum(x ** 2 for x in vector))
        if magnitude > 0:
            embedding.embedding = [x / magnitude for x in vector]
        else:
            embedding.embedding = vector

        return embedding


class SemanticMemory:
    """
    Stores and searches trades by semantic similarity.
    """

    def __init__(self, max_trades: int = 500):
        """
        Args:
            max_trades: Keep only most recent N trades in memory
        """
        self.max_trades = max_trades
        self.embeddings: List[TradeEmbedding] = []
        self.embedder = TradeEmbedder()
        self.output_file = os.path.join("data/llm", "semantic_memory.jsonl")
        os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
        self._load_recent()

    def _load_recent(self) -> None:
        """Load recent trades from disk."""
        if not os.path.exists(self.output_file):
            return

        try:
            with open(self.output_file, "r") as f:
                for line in f.readlines()[-self.max_trades:]:
                    try:
                        data = json.loads(line.strip())
                        embedding = TradeEmbedding(
                            trade_id=data["trade_id"],
                            symbol=data["symbol"],
                            timestamp=data["timestamp"],
                            regime=data["regime"],
                            setup_type=data["setup_type"],
                            entry_confidence=data["entry_confidence"],
                            leverage=data["leverage"],
                            hold_time_minutes=data["hold_time_minutes"],
                            pnl=data["pnl"],
                            win=data["win"],
                            embedding=data.get("embedding"),
                        )
                        self.embeddings.append(embedding)
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Failed to load semantic memory: {e}")

    def add_trade(
        self,
        trade_id: str,
        symbol: str,
        regime: str,
        setup_type: str,
        entry_confidence: float,
        leverage: float,
        hold_time_minutes: float,
        pnl: float,
        win: bool,
    ) -> None:
        """
        Add a closed trade to semantic memory.
        """
        embedding = self.embedder.embed_trade(
            trade_id=trade_id,
            symbol=symbol,
            timestamp=time.time(),
            regime=regime,
            setup_type=setup_type,
            entry_confidence=entry_confidence,
            leverage=leverage,
            hold_time_minutes=hold_time_minutes,
            pnl=pnl,
            win=win,
        )

        self.embeddings.append(embedding)
        if len(self.embeddings) > self.max_trades:
            self.embeddings = self.embeddings[-self.max_trades:]

        # Persist to disk
        try:
            with open(self.output_file, "a") as f:
                data = {
                    "trade_id": embedding.trade_id,
                    "symbol": embedding.symbol,
                    "timestamp": embedding.timestamp,
                    "regime": embedding.regime,
                    "setup_type": embedding.setup_type,
                    "entry_confidence": embedding.entry_confidence,
                    "leverage": embedding.leverage,
                    "hold_time_minutes": embedding.hold_time_minutes,
                    "pnl": embedding.pnl,
                    "win": embedding.win,
                    "embedding": embedding.embedding,
                }
                f.write(json.dumps(data) + "\n")
        except Exception as e:
            logger.error(f"Failed to persist trade embedding: {e}")

    def find_similar_trades(
        self,
        regime: str,
        setup_type: str,
        entry_confidence: float,
        leverage: float,
        hold_time_minutes: float = 60,  # Estimate
        top_k: int = 5,
    ) -> List[Tuple[TradeEmbedding, float]]:
        """
        Find K most similar past trades.

        Returns:
            List of (TradeEmbedding, similarity_score) sorted by similarity
        """
        if not self.embeddings:
            return []

        # Create embedding for query
        query = self.embedder.embed_trade(
            trade_id="query",
            symbol="",
            timestamp=time.time(),
            regime=regime,
            setup_type=setup_type,
            entry_confidence=entry_confidence,
            leverage=leverage,
            hold_time_minutes=hold_time_minutes,
            pnl=0,
            win=False,
        )

        # Compute similarity to all stored trades
        similarities = []
        for stored in self.embeddings:
            similarity = self._cosine_similarity(query.embedding, stored.embedding)
            similarities.append((stored, similarity))

        # Sort by similarity (descending)
        similarities.sort(key=lambda x: x[1], reverse=True)

        return similarities[:top_k]

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        """Compute cosine similarity between two vectors."""
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(v1, v2))
        return float(dot_product)  # Already normalized

    def get_pattern_for_query(
        self,
        regime: str,
        setup_type: str,
        entry_confidence: float,
        leverage: float,
    ) -> Dict[str, Any]:
        """
        Get pattern insight for a potential trade.

        Returns analysis of similar past trades.
        """
        similar = self.find_similar_trades(regime, setup_type, entry_confidence, leverage, top_k=10)

        if not similar:
            return {
                "status": "no_data",
                "recommendation": "neutral",
                "reasoning": "No similar past trades found",
            }

        # Analyze outcomes
        similar_trades = [t for t, _ in similar]
        wins = sum(1 for t in similar_trades if t.win)
        losses = len(similar_trades) - wins
        avg_pnl = sum(t.pnl for t in similar_trades) / len(similar_trades) if similar_trades else 0
        win_rate = wins / len(similar_trades) if similar_trades else 0

        # Recommendation based on pattern
        if win_rate > 0.65:
            recommendation = "boost"  # Increase confidence/size
            reasoning = f"Similar patterns won {wins}/{len(similar_trades)} times (+${avg_pnl:+.2f} avg)"
        elif win_rate > 0.50:
            recommendation = "normal"
            reasoning = f"Pattern is neutral ({win_rate:.0%} win rate)"
        elif win_rate > 0.35:
            recommendation = "reduce"  # Reduce size
            reasoning = f"Similar patterns won only {wins}/{len(similar_trades)} times"
        else:
            recommendation = "avoid"  # Skip this setup
            reasoning = f"Pattern is consistently losing ({win_rate:.0%} win rate)"

        return {
            "status": "success",
            "similar_trades": len(similar_trades),
            "win_rate": f"{win_rate:.0%}",
            "avg_pnl": f"${avg_pnl:+.2f}",
            "recommendation": recommendation,
            "reasoning": reasoning,
            "similar_examples": [
                {
                    "trade_id": t.trade_id,
                    "pnl": f"${t.pnl:+.2f}",
                    "win": t.win,
                    "regime": t.regime,
                }
                for t, _ in similar[:3]
            ],
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        if not self.embeddings:
            return {"trades_stored": 0}

        wins = sum(1 for t in self.embeddings if t.win)
        total_pnl = sum(t.pnl for t in self.embeddings)

        regimes = {}
        for t in self.embeddings:
            regimes[t.regime] = regimes.get(t.regime, 0) + 1

        return {
            "trades_stored": len(self.embeddings),
            "win_rate": f"{wins / len(self.embeddings):.0%}" if self.embeddings else "0%",
            "total_pnl": f"${total_pnl:+.2f}",
            "regimes": regimes,
        }


# Global semantic memory
_global_memory: Optional[SemanticMemory] = None


def get_semantic_memory(max_trades: int = 500) -> SemanticMemory:
    """Get or create global semantic memory."""
    global _global_memory
    if _global_memory is None:
        _global_memory = SemanticMemory(max_trades)
    return _global_memory
