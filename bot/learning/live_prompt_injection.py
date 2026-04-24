"""
Live Prompt Injection: Inject real-time edge data into every agent call.

Computes live win rates by symbol/regime/confidence/time-of-day and injects
into agent prompts so they have current context when reasoning.
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, Any, List

logger = logging.getLogger("bot.learning.live_prompt_injection")


class LivePromptInjection:
    """Builds and injects live edge data into agent prompts."""

    def __init__(self, trades_csv_path: str = "data/trades.csv", data_dir: str = "data/learning"):
        self.trades_csv_path = trades_csv_path
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

        self._edge_data_file = os.path.join(data_dir, "live_edge_data.json")
        logger.info("[LIVE_INJECT] Initialized")

    def compute_live_edges(self, lookback_trades: int = 100) -> Dict[str, Any]:
        """
        Compute live win rates and edge metrics from recent trades.

        Returns:
            {
              by_symbol: {BTC: {WR, count, edge}, ...},
              by_regime: {trending: {WR, count}, ...},
              by_confidence_bin: {70-80: {WR, count}, ...},
              by_time_of_day: {6-12: {WR, count}, ...},
              high_edges: [(symbol, side, regime, time, WR, count), ...],
            }
        """
        logger.info(f"[LIVE_INJECT] Computing live edges from last {lookback_trades} trades")

        # TODO: Implementation
        # 1. Read trades.csv (last N)
        # 2. For each trade, compute:
        #    - win = pnl > 0
        #    - symbol, side, regime, confidence, hour (UTC)
        # 3. Group and calculate WR for:
        #    - By symbol
        #    - By regime (trending/ranging/illiquid/unknown)
        #    - By confidence bin (50-60%, 60-70%, 70-80%, 80-90%, 90%+)
        #    - By time-of-day (UTC hour 0-3, 4-7, 8-11, 12-15, 16-19, 20-23)
        #    - By symbol+side+regime (high-res)
        # 4. Identify high edges (WR > 60%, count >= 5)
        # 5. Sort by evidence (higher count = more reliable)

        edges = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "lookback_trades": lookback_trades,
            "by_symbol": {},  # {symbol: {WR, count, avg_pnl}}
            "by_regime": {},  # {regime: {WR, count, avg_pnl}}
            "by_confidence_bin": {},  # {bin: {WR, count}}
            "by_time_of_day": {},  # {hour_range: {WR, count}}
            "high_edges": [],  # [(setup, WR, count, avg_pnl)]
            "weak_setups": [],  # [(setup, WR, count) where WR < 30%]
        }

        self._save_edge_data(edges)
        return edges

    def build_injection_prompt(self, edges: Dict[str, Any]) -> str:
        """
        Build a prompt section that agents can read for live context.

        Returns a markdown string that can be injected into agent prompts.
        """
        logger.info("[LIVE_INJECT] Building injection prompt")

        # TODO: Format edges into readable markdown for agents
        prompt_section = f"""
# LIVE MARKET INTELLIGENCE (as of {edges['timestamp']})

## High-Confidence Edges (WR > 60%, N >= 5)
{self._format_edges(edges.get('high_edges', []))}

## Symbol Win Rates (Last {edges['lookback_trades']} Trades)
{self._format_symbol_stats(edges.get('by_symbol', {}))}

## Regime Profitability
{self._format_regime_stats(edges.get('by_regime', {}))}

## Time-of-Day Patterns
{self._format_time_patterns(edges.get('by_time_of_day', {}))}

## Weak Setups to Avoid (WR < 30%)
{self._format_weak_setups(edges.get('weak_setups', []))}
"""
        return prompt_section

    def _format_edges(self, edges: List[tuple]) -> str:
        if not edges:
            return "No high edges found yet."
        lines = []
        for setup, wr, count, pnl in edges[:5]:  # Top 5
            lines.append(f"- **{setup}**: {wr:.1f}% WR (n={count}, ${pnl:+.2f} avg)")
        return "\n".join(lines)

    def _format_symbol_stats(self, by_symbol: Dict[str, Any]) -> str:
        if not by_symbol:
            return "No symbol data yet."
        lines = []
        for sym in sorted(by_symbol.keys()):
            stats = by_symbol[sym]
            wr = stats.get("WR", 0)
            count = stats.get("count", 0)
            lines.append(f"- **{sym}**: {wr:.1f}% WR (n={count})")
        return "\n".join(lines)

    def _format_regime_stats(self, by_regime: Dict[str, Any]) -> str:
        if not by_regime:
            return "No regime data yet."
        lines = []
        for regime in ["trending", "ranging", "illiquid", "unknown"]:
            if regime in by_regime:
                stats = by_regime[regime]
                wr = stats.get("WR", 0)
                lines.append(f"- **{regime.capitalize()}**: {wr:.1f}% WR")
        return "\n".join(lines) if lines else "No regime data."

    def _format_time_patterns(self, by_time: Dict[str, Any]) -> str:
        if not by_time:
            return "No time-of-day data yet."
        lines = []
        for time_range in sorted(by_time.keys()):
            stats = by_time[time_range]
            wr = stats.get("WR", 0)
            lines.append(f"- **{time_range} UTC**: {wr:.1f}% WR")
        return "\n".join(lines)

    def _format_weak_setups(self, weak: List[tuple]) -> str:
        if not weak:
            return "No weak setups identified (good sign!)."
        lines = []
        for setup, wr, count in weak[:3]:
            lines.append(f"- {setup}: {wr:.1f}% WR (n={count}) — avoid or reduce size")
        return "\n".join(lines)

    def _save_edge_data(self, edges: Dict[str, Any]):
        try:
            with open(self._edge_data_file, "w") as f:
                json.dump(edges, f, indent=2)
            logger.info(f"[LIVE_INJECT] Saved edge data to {self._edge_data_file}")
        except Exception as e:
            logger.error(f"[LIVE_INJECT] Failed to save: {e}")

    def get_current_edges(self) -> Optional[Dict[str, Any]]:
        if os.path.exists(self._edge_data_file):
            try:
                with open(self._edge_data_file) as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load edges: {e}")
        return None
