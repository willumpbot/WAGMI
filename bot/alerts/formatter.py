"""
Enhanced Discord alert formatter.

Transforms raw signal objects into beautiful, actionable Discord embeds
with strategy breakdown, confidence scores, position sizing, and historical context.

Usage:
    formatter = EnhancedAlertFormatter(trade_history_csv)
    embed = formatter.format_signal(signal, ensemble_metadata)
    await webhook.send(embed=embed)
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from pathlib import Path
from dataclasses import dataclass

import pandas as pd
from discord import Embed, Color

logger = logging.getLogger("bot.alerts.formatter")


@dataclass
class StrategySignal:
    """One strategy's signal for display."""
    name: str
    decision: str      # BUY, SELL, HOLD
    confidence: float  # 0-100
    agreed: bool       # Did this agree with ensemble?


class EnhancedAlertFormatter:
    """Formats signals into detailed Discord embeds."""

    def __init__(self, trade_history_path: str = "paper_trades"):
        self.trade_history_dir = Path(trade_history_path)
        self.trade_cache = {}
        self._load_trade_history()

    def _load_trade_history(self):
        """Load trade history from CSVs for win rate calculations."""
        trades_files = sorted(list(self.trade_history_dir.glob("trades_*.csv")))
        if trades_files:
            try:
                df = pd.concat([pd.read_csv(f) for f in trades_files], ignore_index=True)
                df["symbol"] = df["symbol"].str.upper()
                self.trade_cache["all_trades"] = df
                logger.info(f"✅ Loaded {len(df)} trades from history")
            except Exception as e:
                logger.warning(f"Could not load trade history: {e}")

    def format_signal(
        self,
        signal_obj: Any,  # strategies.base.Signal
        ensemble_metadata: Dict[str, Any],
        strategies_breakdown: Optional[List[StrategySignal]] = None,
    ) -> Embed:
        """
        Format a signal into a detailed Discord embed.

        Args:
            signal_obj: The Signal object from strategies
            ensemble_metadata: Metadata dict from ensemble (regime_score, num_agree, etc)
            strategies_breakdown: List of individual strategy signals

        Returns:
            Discord Embed (ready to send)
        """

        symbol = signal_obj.symbol
        side = signal_obj.side
        confidence = signal_obj.confidence
        regime_score = ensemble_metadata.get("regime_score", 0)
        num_agree = ensemble_metadata.get("num_agree", 1)
        total_strategies = ensemble_metadata.get("total_strategies", 4)

        # Determine color based on signal strength
        if confidence >= 75 and num_agree >= 3:
            color = Color.green() if side == "BUY" else Color.red()  # Strong signal
        elif confidence >= 60 and num_agree >= 2:
            color = Color.gold()  # Medium signal
        else:
            color = Color.greyple()  # Weak signal

        # Create embed
        title = f"{'📈 BUY' if side == 'BUY' else '📉 SELL'} {symbol}"
        embed = Embed(
            title=title,
            description=f"Confidence: **{confidence:.0f}%** | Regime: **{regime_score:.1f}★**",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )

        # --- STRATEGY BREAKDOWN SECTION ---
        if strategies_breakdown:
            breakdown_text = self._format_strategy_breakdown(strategies_breakdown, num_agree, total_strategies)
            embed.add_field(
                name="🎯 Strategy Consensus",
                value=breakdown_text,
                inline=False,
            )

        # --- CONFIDENCE & ALIGNMENT SECTION ---
        consensus_str = f"{num_agree}/{total_strategies} strategies agree"
        confidence_bar = self._make_confidence_bar(confidence)
        regime_stars = self._make_regime_stars(regime_score)

        embed.add_field(
            name="🔍 Confidence Breakdown",
            value=(
                f"**Confidence:** {confidence_bar} {confidence:.0f}%\n"
                f"**Consensus:** {consensus_str}\n"
                f"**Regime Align:** {regime_stars} {regime_score:.1f}/5"
            ),
            inline=False,
        )

        # --- ENTRY/EXIT SECTION ---
        risk_amount = max(0, signal_obj.entry - signal_obj.sl) if side == "BUY" else max(0, signal_obj.sl - signal_obj.entry)
        position_qty = self._calculate_position_size(risk_amount, signal_obj.entry)
        rr_ratio = abs(signal_obj.tp2 - signal_obj.entry) / max(risk_amount, 0.0001)

        embed.add_field(
            name="💰 Entry Details",
            value=(
                f"**Entry:** ${signal_obj.entry:.2f}\n"
                f"**Stop Loss:** ${signal_obj.sl:.2f}\n"
                f"**Risk per trade:** ${risk_amount:.2f}\n"
                f"**Position Size:** {position_qty:.4f} {symbol} (1.5% risk on $50k)"
            ),
            inline=True,
        )

        embed.add_field(
            name="🎯 Targets",
            value=(
                f"**TP1:** ${signal_obj.tp1:.2f}\n"
                f"**TP2:** ${signal_obj.tp2:.2f}\n"
                f"**Risk/Reward:** 1:{rr_ratio:.1f}\n"
                f"**ATR:** {signal_obj.atr:.4f}"
            ),
            inline=True,
        )

        # --- HISTORICAL CONTEXT SECTION ---
        win_rate_context = self._get_win_rate_context(symbol, side)
        if win_rate_context:
            embed.add_field(
                name="📊 Historical Context",
                value=win_rate_context,
                inline=False,
            )

        # --- ACTION FOOTER ---
        action_text = self._get_action_suggestion(confidence, num_agree, regime_score)
        embed.set_footer(text=f"Action: {action_text} | Next update in 15 min")

        return embed

    def _format_strategy_breakdown(
        self, strategies: List[StrategySignal], num_agree: int, total: int
    ) -> str:
        """Format the strategy voting breakdown."""
        lines = []
        for strat in strategies:
            # Use emoji based on agreement
            if strat.agreed:
                emoji = "✅"
            else:
                emoji = "❌"
            lines.append(f"{emoji} **{strat.name}**: {strat.decision} ({strat.confidence:.0f}%)")

        consensus = f"\n`{num_agree}/{total} agreed`"
        return "\n".join(lines) + consensus

    def _make_confidence_bar(self, confidence: float) -> str:
        """Create visual confidence bar."""
        filled = int(confidence / 10)
        empty = 10 - filled
        return f"`{'█' * filled}{'░' * empty}`"

    def _make_regime_stars(self, regime_score: float) -> str:
        """Create visual regime alignment stars."""
        filled = int(regime_score)
        empty = 5 - filled
        return f"{'⭐' * filled}{'☆' * empty}"

    def _calculate_position_size(self, risk_amount: float, entry_price: float) -> float:
        """Calculate position size for 1.5% account risk on $50k."""
        starting_equity = 50000
        risk_percent = 0.015
        account_risk = starting_equity * risk_percent

        if risk_amount <= 0 or entry_price <= 0:
            return 0.0

        position_qty = account_risk / risk_amount
        return position_qty

    def _get_win_rate_context(self, symbol: str, side: str) -> Optional[str]:
        """Get historical win rate for similar signals."""
        if "all_trades" not in self.trade_cache:
            return None

        try:
            df = self.trade_cache["all_trades"]

            # Filter by symbol and side
            sym_trades = df[(df["symbol"] == symbol.upper()) & (df["action"].isin(["TP2", "SL"]))]
            if sym_trades.empty:
                return None

            # Count wins/losses
            total = len(sym_trades)
            wins = len(sym_trades[sym_trades["pnl"] > 0])
            win_rate = wins / total * 100 if total > 0 else 0

            # Recent performance (last 7 days)
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            cutoff = datetime.now(timezone.utc).timestamp() - (7 * 86400)
            recent = sym_trades[sym_trades["timestamp"].dt.timestamp() >= cutoff]

            recent_text = ""
            if not recent.empty:
                recent_wins = len(recent[recent["pnl"] > 0])
                recent_wr = recent_wins / len(recent) * 100 if len(recent) > 0 else 0
                recent_text = f"\n**Last 7 days:** {len(recent)} trades, {recent_wr:.0f}% WR"

            return (
                f"**All Time ({symbol})**\n"
                f"Closed: {total} trades | **{win_rate:.0f}%** win rate"
                f"{recent_text}"
            )

        except Exception as e:
            logger.warning(f"Could not calculate win rate: {e}")
            return None

    def _get_action_suggestion(self, confidence: float, num_agree: int, regime_score: float) -> str:
        """Suggest action based on signal strength."""
        if confidence >= 75 and num_agree >= 3 and regime_score >= 3:
            return "🟢 STRONG - Consider auto-execution if comfortable"
        elif confidence >= 65 and num_agree >= 2 and regime_score >= 2:
            return "🟡 MEDIUM - Manual review recommended"
        elif confidence >= 55 and num_agree >= 2:
            return "🟠 WEAK - Wait for confirmed breakout"
        else:
            return "🔴 VERY WEAK - Likely skip this signal"


def create_alert_formatter() -> EnhancedAlertFormatter:
    """Factory function to create formatter with defaults."""
    return EnhancedAlertFormatter(trade_history_path="paper_trades")
