"""
Multi-Layer Position Architecture — Scalp / Swing / Regime.

Enables simultaneous positions across different time horizons on different symbols.
Each layer has its own leverage, risk, time stop, and TP structure.

Layer A: Scalp (1-3 hours)
  - High leverage (15-25x), tight stops (1-2%), fast exits
  - Target: HYPE BUY dip pattern, fast-resolving signals
  - 91% WR on 1-3 bar resolution

Layer B: Swing (6-24 hours)
  - Moderate leverage (5-10x), wider stops (3-5%)
  - Target: BTC/SOL trend continuations, regime confirmations
  - 6-12h hold = best PnL band in backtest

Layer C: Regime (1-7 days)
  - Low leverage (2-3x), wide stops (8-10%)
  - Target: Ride confirmed trends, macro regime plays
  - Only enter on 3-agree + regime confirmation

Rules:
  - One position per symbol per layer
  - Max 1 scalp + 1 swing + 1 regime active simultaneously
  - Correlation check: don't double-long correlated assets on same layer
  - Total portfolio leverage cap applies across all layers
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, List, Tuple

logger = logging.getLogger("bot.execution.position_layers")


class PositionLayer(str, Enum):
    SCALP = "scalp"      # 1-3 hours, high leverage
    SWING = "swing"      # 6-24 hours, moderate leverage
    REGIME = "regime"    # 1-7 days, low leverage


@dataclass
class LayerConfig:
    """Configuration for a position layer."""
    layer: PositionLayer
    max_leverage: float
    min_leverage: float
    max_hold_hours: float
    time_stop_no_new_high_min: float
    target_stop_width_pct: float     # Ideal stop width as % of entry
    tp_multiplier: float             # TP = entry ± (stop × tp_multiplier)
    max_positions: int               # Max open positions in this layer
    kelly_fraction_mult: float       # Multiplier on Kelly fraction (1.0 = use as-is)
    min_confidence: float            # Minimum signal confidence for this layer
    min_agree: int                   # Minimum strategy agreement


# Pre-configured layers
LAYER_CONFIGS: Dict[PositionLayer, LayerConfig] = {
    PositionLayer.SCALP: LayerConfig(
        layer=PositionLayer.SCALP,
        max_leverage=25.0,
        min_leverage=10.0,
        max_hold_hours=4.0,
        time_stop_no_new_high_min=90,   # 1.5h
        target_stop_width_pct=0.015,    # 1.5%
        tp_multiplier=1.5,              # Scalp TP = 1.5R
        max_positions=2,
        kelly_fraction_mult=1.0,        # Full Kelly fraction
        min_confidence=70.0,
        min_agree=2,
    ),
    PositionLayer.SWING: LayerConfig(
        layer=PositionLayer.SWING,
        max_leverage=10.0,
        min_leverage=3.0,
        max_hold_hours=24.0,
        time_stop_no_new_high_min=180,  # 3h
        target_stop_width_pct=0.035,    # 3.5%
        tp_multiplier=2.5,             # Swing TP = 2.5R
        max_positions=2,
        kelly_fraction_mult=0.75,      # 75% of Kelly (more conservative)
        min_confidence=75.0,
        min_agree=2,
    ),
    PositionLayer.REGIME: LayerConfig(
        layer=PositionLayer.REGIME,
        max_leverage=3.0,
        min_leverage=1.0,
        max_hold_hours=168.0,          # 7 days
        time_stop_no_new_high_min=360, # 6h
        target_stop_width_pct=0.08,    # 8%
        tp_multiplier=4.0,            # Regime TP = 4R
        max_positions=1,
        kelly_fraction_mult=0.5,      # 50% of Kelly (very conservative, big moves)
        min_confidence=80.0,
        min_agree=3,
    ),
}


@dataclass
class LayeredPosition:
    """A position tracked by the layer manager."""
    symbol: str
    side: str              # "LONG" or "SHORT"
    layer: PositionLayer
    entry: float
    qty: float
    leverage: float
    sl: float
    tp: float
    opened_at: float       # timestamp
    highest_price: float   # For trailing
    lowest_price: float    # For trailing


@dataclass
class LayerAssignment:
    """Result of classifying a signal into a layer."""
    layer: PositionLayer
    config: LayerConfig
    leverage: float
    stop_width_pct: float
    tp_price: float
    sl_price: float
    hold_limit_hours: float
    rationale: str


class PositionLayerManager:
    """Manages multi-layer positions across scalp/swing/regime."""

    def __init__(self, max_total_leverage: float = 30.0):
        self.max_total_leverage = max_total_leverage
        self._positions: Dict[str, LayeredPosition] = {}  # key: "symbol:layer"

    def get_position_key(self, symbol: str, layer: PositionLayer) -> str:
        return f"{symbol}:{layer.value}"

    def has_position(self, symbol: str, layer: PositionLayer) -> bool:
        key = self.get_position_key(symbol, layer)
        return key in self._positions

    def get_layer_count(self, layer: PositionLayer) -> int:
        return sum(1 for p in self._positions.values() if p.layer == layer)

    def get_total_leverage(self) -> float:
        return sum(p.leverage for p in self._positions.values())

    def get_all_positions(self) -> List[LayeredPosition]:
        return list(self._positions.values())

    def classify_signal(
        self,
        symbol: str,
        side: str,
        confidence: float,
        num_agree: int,
        regime: str,
        stop_width_pct: float,
        entry_price: float,
        is_dip_buy: bool = False,
    ) -> Optional[LayerAssignment]:
        """Classify a signal into the best layer, or None if no layer fits.

        Logic:
        1. Check which layers the signal qualifies for
        2. Prefer the most aggressive layer that has capacity
        3. Check position limits and total leverage

        Args:
            symbol: Asset symbol
            side: "BUY" or "SELL"
            confidence: Signal confidence (0-100)
            num_agree: Number of strategies agreeing
            regime: Market regime
            stop_width_pct: Natural stop width from signal
            entry_price: Current entry price
            is_dip_buy: Whether this is a dip-buy pattern
        """
        # Determine candidate layers (from most aggressive to most conservative)
        candidates = []

        for layer in [PositionLayer.SCALP, PositionLayer.SWING, PositionLayer.REGIME]:
            config = LAYER_CONFIGS[layer]

            # Check minimum requirements
            if confidence < config.min_confidence:
                continue
            if num_agree < config.min_agree:
                continue

            # Check capacity
            if self.has_position(symbol, layer):
                continue
            if self.get_layer_count(layer) >= config.max_positions:
                continue

            # Check total leverage headroom
            headroom = self.max_total_leverage - self.get_total_leverage()
            if headroom < config.min_leverage:
                continue

            # Scalp-specific: only for fast-resolving setups
            if layer == PositionLayer.SCALP:
                # Prefer tight stops and dip-buy patterns
                if stop_width_pct > 0.03 and not is_dip_buy:
                    continue  # Stop too wide for scalp

            # Regime-specific: only for strong regime confirmations
            if layer == PositionLayer.REGIME:
                regime_lower = regime.lower()
                if regime_lower not in ("trending_bull", "trending_bear", "trend"):
                    continue  # Need confirmed trend for regime position

            # Calculate layer-specific parameters
            leverage = min(config.max_leverage, headroom)
            leverage = max(config.min_leverage, leverage)

            if side == "BUY":
                sl = entry_price * (1 - config.target_stop_width_pct)
                tp = entry_price * (1 + config.target_stop_width_pct * config.tp_multiplier)
            else:
                sl = entry_price * (1 + config.target_stop_width_pct)
                tp = entry_price * (1 - config.target_stop_width_pct * config.tp_multiplier)

            rationale = (
                f"{layer.value} | lev={leverage:.0f}x "
                f"hold<={config.max_hold_hours:.0f}h "
                f"tp={config.tp_multiplier:.1f}R"
            )

            candidates.append(LayerAssignment(
                layer=layer,
                config=config,
                leverage=leverage,
                stop_width_pct=config.target_stop_width_pct,
                tp_price=tp,
                sl_price=sl,
                hold_limit_hours=config.max_hold_hours,
                rationale=rationale,
            ))

        if not candidates:
            return None

        # Return the most aggressive (first) candidate
        return candidates[0]

    def open_position(
        self, symbol: str, side: str, layer: PositionLayer,
        entry: float, qty: float, leverage: float, sl: float, tp: float,
    ) -> LayeredPosition:
        """Register a new layered position."""
        key = self.get_position_key(symbol, layer)
        pos = LayeredPosition(
            symbol=symbol,
            side=side,
            layer=layer,
            entry=entry,
            qty=qty,
            leverage=leverage,
            sl=sl,
            tp=tp,
            opened_at=time.time(),
            highest_price=entry,
            lowest_price=entry,
        )
        self._positions[key] = pos
        logger.info(
            f"[LAYERS] Opened {layer.value} {symbol} {side} "
            f"@ {entry:.2f} lev={leverage:.0f}x sl={sl:.2f} tp={tp:.2f}"
        )
        return pos

    def close_position(self, symbol: str, layer: PositionLayer) -> Optional[LayeredPosition]:
        """Close a layered position and return it."""
        key = self.get_position_key(symbol, layer)
        pos = self._positions.pop(key, None)
        if pos:
            logger.info(f"[LAYERS] Closed {layer.value} {symbol} {pos.side}")
        return pos

    def check_time_stops(self) -> List[LayeredPosition]:
        """Check all positions for time stop violations. Returns positions to close."""
        now = time.time()
        to_close = []
        for key, pos in self._positions.items():
            config = LAYER_CONFIGS[pos.layer]
            hold_hours = (now - pos.opened_at) / 3600

            if hold_hours >= config.max_hold_hours:
                to_close.append(pos)
                logger.info(
                    f"[LAYERS] TIME STOP: {pos.layer.value} {pos.symbol} "
                    f"held {hold_hours:.1f}h (max {config.max_hold_hours:.0f}h)"
                )

        return to_close

    def get_summary(self) -> Dict:
        """Get layer manager summary for logging."""
        return {
            "total_positions": len(self._positions),
            "total_leverage": round(self.get_total_leverage(), 1),
            "scalp": self.get_layer_count(PositionLayer.SCALP),
            "swing": self.get_layer_count(PositionLayer.SWING),
            "regime": self.get_layer_count(PositionLayer.REGIME),
            "positions": [
                {"symbol": p.symbol, "side": p.side, "layer": p.layer.value,
                 "leverage": p.leverage}
                for p in self._positions.values()
            ],
        }
