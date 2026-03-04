"""
LLM Multi-Agent Integration for Backtesting.

Wraps the AgentCoordinator for use in the backtest engine with:
  - Preflight validation (zero-waste: validates everything before any real API call)
  - Budget enforcement (stops LLM calls when budget exceeded, falls back to strategy-only)
  - Checkpoint/resume (atomic saves every N candles, resume from last checkpoint)
  - Per-candle error handling (never crashes the backtest, always falls back gracefully)
  - Cost tracking and progress reporting

Usage:
    llm = BacktestLLMIntegration(budget_usd=5.0)
    preflight = llm.run_preflight(symbols, all_data, ensemble, config)
    if not preflight.passed:
        print(preflight.errors)
        return

    # In walk loop:
    decision = llm.evaluate_entry(snapshot_data, signal, "pre_trade_backtest")
    exit_rec = llm.evaluate_exit(position_data, market_data)
    lesson = llm.run_learning(trade_data)
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("bot.backtest.llm")

# Model pricing per 1M tokens (input, output)
_MODEL_PRICING = {
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-4-5-20250929": (3.0, 15.0),
    "claude-opus-4-20250115": (15.0, 75.0),
}

# Default pricing for unknown models (use Sonnet as conservative estimate)
_DEFAULT_PRICING = (3.0, 15.0)

# Exit agent throttle: evaluate every N candles per position
_EXIT_EVAL_INTERVAL = 6


@dataclass
class PreflightResult:
    """Result of preflight validation."""
    passed: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    estimated_cost: float = 0.0
    estimated_llm_calls: int = 0
    candle_count: int = 0


@dataclass
class CheckpointState:
    """Serializable backtest state for resume."""
    candle_index: int
    symbol: str
    symbols_completed: List[str]
    equity: float
    llm_stats: Dict[str, Any]
    timestamp: str


class BacktestLLMIntegration:
    """Wraps AgentCoordinator for backtest with reliability safeguards."""

    def __init__(
        self,
        budget_usd: float = 5.0,
        checkpoint_dir: str = "data/backtest_checkpoints",
        resume: bool = False,
    ):
        self.budget_usd = budget_usd
        self.checkpoint_dir = checkpoint_dir
        self.resume = resume

        # Coordinator (created lazily after preflight)
        self._coordinator = None

        # Cost tracking
        self.total_cost_usd: float = 0.0
        self.budget_exhausted: bool = False

        # Call tracking
        self.llm_calls: int = 0
        self.llm_failures: int = 0
        self.candles_with_llm: int = 0
        self.candles_fallback: int = 0

        # Decision log
        self.decisions: List[Dict[str, Any]] = []
        self.decisions_log_path = os.path.join("data", "llm", "backtest_decisions.jsonl")

        # Exit agent throttle
        self._exit_eval_counters: Dict[str, int] = {}

        # Resume state
        self.resume_state: Optional[CheckpointState] = None
        if resume:
            self.resume_state = self._load_checkpoint()

    # ── Preflight ─────────────────────────────────────────────────

    def run_preflight(
        self,
        symbols: List[str],
        all_data: Dict[str, Any],
        ensemble,
        config,
    ) -> PreflightResult:
        """Validate everything before making any real API calls.

        Checks (ordered cheapest to most expensive):
        1. API key present
        2. API ping (one Haiku call, ~$0.0001)
        3. Data quality (non-empty DataFrames, >= 50 candles)
        4. Strategy dry-run (ensemble.evaluate on sample candles)
        5. Snapshot builder works
        6. Coordinator instantiates
        7. Cost estimation

        Returns PreflightResult with passed=False on any fatal error.
        """
        result = PreflightResult(passed=True)

        # 1. API key check
        try:
            from llm.client import get_client
            client = get_client()
            if client is None:
                result.passed = False
                result.errors.append(
                    "ANTHROPIC_API_KEY not set or anthropic package not installed. "
                    "No API calls possible."
                )
                return result
        except Exception as e:
            result.passed = False
            result.errors.append(f"Failed to initialize API client: {e}")
            return result

        # 2. API ping (one cheap Haiku call)
        try:
            from llm.client import call_llm
            text, usage = call_llm(
                system_prompt="Reply with exactly: OK",
                snapshot_json="{}",
                model="claude-haiku-4-5-20251001",
                max_tokens=8,
                max_retries=1,
                timeout=15.0,
            )
            if text is None:
                result.passed = False
                error_msg = usage.get("error", "unknown error")
                result.errors.append(
                    f"API ping failed: {error_msg}. "
                    "Check your API key and network connection."
                )
                return result
            ping_cost = self._compute_cost_from_usage(usage)
            self.total_cost_usd += ping_cost
            logger.info(f"[PREFLIGHT] API ping OK (cost: ${ping_cost:.6f})")
        except Exception as e:
            result.passed = False
            result.errors.append(f"API ping failed with exception: {e}")
            return result

        # 3. Data validation
        total_candles = 0
        for symbol in symbols:
            data = all_data.get(symbol, {})
            df_1h = data.get("1h")
            df_daily = data.get("daily")

            if df_1h is not None and not df_1h.empty:
                n = len(df_1h)
                if n < 50:
                    result.warnings.append(
                        f"{symbol}: only {n} 1h candles (need 50 for warmup)"
                    )
                else:
                    total_candles += n - 50  # Subtract warmup
            elif df_daily is not None and not df_daily.empty:
                n = len(df_daily)
                if n < 50:
                    result.warnings.append(
                        f"{symbol}: only {n} daily candles (need 50 for warmup)"
                    )
                else:
                    total_candles += n - 50
            else:
                result.warnings.append(f"{symbol}: no 1h or daily data available")

        if total_candles == 0:
            result.passed = False
            result.errors.append("No usable data for any symbol after warmup.")
            return result

        result.candle_count = total_candles

        # 4. Strategy dry-run (verify ensemble doesn't crash)
        try:
            import pandas as pd
            test_count = 0
            for symbol in symbols:
                data = all_data.get(symbol, {})
                df_1h = data.get("1h")
                if df_1h is None or df_1h.empty or len(df_1h) < 55:
                    continue
                # Test 3 candles after warmup
                for i in range(50, min(53, len(df_1h))):
                    windowed = {}
                    for tf, df in data.items():
                        if df is not None and not df.empty:
                            current_time = df_1h["time"].iloc[i]
                            mask = df["time"] <= current_time
                            windowed[tf] = df[mask].copy()
                    ensemble.evaluate(symbol, windowed)
                    test_count += 1
            if test_count == 0:
                result.warnings.append("Could not dry-run strategies (no suitable data)")
            else:
                logger.info(f"[PREFLIGHT] Strategy dry-run OK ({test_count} candles tested)")
        except Exception as e:
            result.passed = False
            result.errors.append(
                f"Strategy dry-run crashed: {e}. "
                "Fix strategy errors before spending API credits."
            )
            return result

        # 5. Snapshot builder validation
        try:
            snapshot = self._build_test_snapshot(symbols[0], 50000.0)
            snapshot_json = json.dumps(snapshot, separators=(",", ":"))
            parsed = json.loads(snapshot_json)
            if "m" not in parsed:
                result.warnings.append("Test snapshot missing 'm' key (markets)")
            logger.info(f"[PREFLIGHT] Snapshot builder OK ({len(snapshot_json)} bytes)")
        except Exception as e:
            result.passed = False
            result.errors.append(f"Snapshot builder failed: {e}")
            return result

        # 6. Coordinator instantiation
        try:
            from llm.agents.coordinator import AgentCoordinator
            self._coordinator = AgentCoordinator()
            logger.info("[PREFLIGHT] AgentCoordinator instantiated OK")
        except Exception as e:
            result.passed = False
            result.errors.append(f"AgentCoordinator failed to instantiate: {e}")
            return result

        # 7. Cost estimation
        # Conservative estimate: 10% of candles produce signals
        estimated_signal_rate = 0.10
        estimated_signals = int(total_candles * estimated_signal_rate)
        # ~30% of signals pass risk gates -> become trades
        estimated_trades = int(estimated_signals * 0.30)
        # Exit agent: runs every EXIT_EVAL_INTERVAL candles per open position
        # Assume avg 1 position open for 20% of candles
        estimated_exit_calls = int(total_candles * 0.20 / _EXIT_EVAL_INTERVAL)
        # Learning agent: once per closed trade
        estimated_learning_calls = estimated_trades

        # Cost per entry pipeline: ~$0.007 (documented average)
        # Cost per exit call: ~$0.0002 (Haiku)
        # Cost per learning call: ~$0.0004 (Haiku)
        cost_entry = estimated_signals * 0.007
        cost_exit = estimated_exit_calls * 0.0002
        cost_learning = estimated_learning_calls * 0.0004
        estimated_total = cost_entry + cost_exit + cost_learning

        result.estimated_cost = round(estimated_total, 2)
        result.estimated_llm_calls = (
            estimated_signals * 4  # 4 agents per entry pipeline
            + estimated_exit_calls
            + estimated_learning_calls
        )

        if estimated_total > self.budget_usd:
            result.warnings.append(
                f"Estimated cost ${estimated_total:.2f} exceeds budget ${self.budget_usd:.2f}. "
                f"LLM will be disabled after budget is exhausted; remaining candles use strategy-only."
            )

        logger.info(
            f"[PREFLIGHT] Cost estimate: ${estimated_total:.2f} "
            f"({result.estimated_llm_calls} API calls, {total_candles} candles)"
        )

        return result

    # ── Entry Evaluation ──────────────────────────────────────────

    def evaluate_entry(
        self,
        snapshot_data: Optional[dict],
        signal,
        trigger_reason: str = "pre_trade_backtest",
    ):
        """Run multi-agent pipeline on a signal. Returns LLMDecision or None.

        On ANY failure: returns None (strategy-only fallback), never crashes.
        """
        if self.budget_exhausted:
            self.candles_fallback += 1
            return None

        if not snapshot_data or not isinstance(snapshot_data, dict):
            self.candles_fallback += 1
            return None

        if self._coordinator is None:
            self.candles_fallback += 1
            return None

        try:
            decision = self._coordinator.get_trading_decision(
                snapshot_data, trigger_reason=trigger_reason
            )

            # Track cost
            stats = self._coordinator.get_stats()
            call_cost = self._compute_cost_from_stats(stats)
            self.total_cost_usd += call_cost
            self.llm_calls += stats.get("total_calls", 0)

            if decision:
                self.candles_with_llm += 1
                self._log_decision(decision, snapshot_data, call_cost, trigger_reason)
            else:
                self.candles_fallback += 1

            # Check budget
            if self.total_cost_usd >= self.budget_usd:
                self.budget_exhausted = True
                logger.warning(
                    f"[BACKTEST-LLM] Budget exhausted: "
                    f"${self.total_cost_usd:.2f} >= ${self.budget_usd:.2f}. "
                    f"Remaining candles will use strategy-only."
                )

            return decision

        except Exception as e:
            logger.warning(f"[BACKTEST-LLM] Entry evaluation failed: {e}")
            self.llm_failures += 1
            self.candles_fallback += 1
            return None

    # ── Exit Evaluation ───────────────────────────────────────────

    def evaluate_exit(
        self,
        position_data: Dict[str, Any],
        market_data: Optional[dict] = None,
    ) -> Optional[Dict[str, Any]]:
        """Run Exit Agent on an open position. Returns recommendation or None.

        Throttled: only evaluates every EXIT_EVAL_INTERVAL candles per position.
        """
        if self.budget_exhausted or self._coordinator is None:
            return None

        symbol = position_data.get("symbol", "")

        # Throttle: only evaluate every N candles
        counter = self._exit_eval_counters.get(symbol, 0) + 1
        self._exit_eval_counters[symbol] = counter
        if counter % _EXIT_EVAL_INTERVAL != 0:
            return None

        try:
            result = self._coordinator.get_exit_intelligence(
                position_data, market_data
            )

            stats = self._coordinator.get_stats()
            call_cost = self._compute_cost_from_stats(stats)
            self.total_cost_usd += call_cost
            self.llm_calls += stats.get("total_calls", 0)

            if self.total_cost_usd >= self.budget_usd:
                self.budget_exhausted = True

            return result

        except Exception as e:
            logger.warning(f"[BACKTEST-LLM] Exit evaluation failed for {symbol}: {e}")
            self.llm_failures += 1
            return None

    def clear_exit_counter(self, symbol: str):
        """Reset exit eval counter when a position closes."""
        self._exit_eval_counters.pop(symbol, None)

    # ── Learning ──────────────────────────────────────────────────

    def run_learning(self, trade_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Run Learning Agent after a trade closes. Returns lesson or None."""
        if self.budget_exhausted or self._coordinator is None:
            return None

        try:
            result = self._coordinator.get_post_trade_lesson(trade_data)

            stats = self._coordinator.get_stats()
            call_cost = self._compute_cost_from_stats(stats)
            self.total_cost_usd += call_cost
            self.llm_calls += stats.get("total_calls", 0)

            if self.total_cost_usd >= self.budget_usd:
                self.budget_exhausted = True

            return result

        except Exception as e:
            logger.warning(f"[BACKTEST-LLM] Learning agent failed: {e}")
            self.llm_failures += 1
            return None

    # ── Snapshot Building ─────────────────────────────────────────

    def build_backtest_snapshot(
        self,
        symbol: str,
        windowed_data: Dict[str, Any],
        signal,
        current_price: float,
        open_positions: Dict[str, Any],
        equity: float,
        daily_pnl: float = 0.0,
        circuit_breaker_active: bool = False,
    ) -> Optional[dict]:
        """Build a snapshot dict compatible with coordinator.get_trading_decision().

        Constructs the compact format that agents expect from the data available
        in the backtest walk loop.
        """
        try:
            import pandas as pd

            # Build market entry for this symbol
            market = {"s": symbol, "p": _round_price(current_price)}

            # Compute price changes from 1h data
            df_1h = windowed_data.get("1h")
            if df_1h is not None and not df_1h.empty and len(df_1h) >= 2:
                prev_close = float(df_1h["close"].iloc[-2])
                if prev_close > 0:
                    chg_1h = (current_price - prev_close) / prev_close * 100
                    market["d1h"] = round(chg_1h, 1)

                if len(df_1h) >= 25:
                    close_24h_ago = float(df_1h["close"].iloc[-25])
                    if close_24h_ago > 0:
                        chg_24h = (current_price - close_24h_ago) / close_24h_ago * 100
                        market["d24h"] = round(chg_24h, 1)

                # Volume ratio
                if "volume" in df_1h.columns:
                    recent_vol = float(df_1h["volume"].iloc[-1])
                    avg_vol = float(df_1h["volume"].iloc[-20:].mean())
                    if avg_vol > 0:
                        market["vr"] = round(recent_vol / avg_vol, 1)

                # Volatility (ATR-based)
                if len(df_1h) >= 14:
                    highs = df_1h["high"].iloc[-14:].values
                    lows = df_1h["low"].iloc[-14:].values
                    closes = df_1h["close"].iloc[-15:-1].values
                    if len(closes) == 14:
                        tr = []
                        for j in range(14):
                            tr.append(max(
                                float(highs[j]) - float(lows[j]),
                                abs(float(highs[j]) - float(closes[j])),
                                abs(float(lows[j]) - float(closes[j])),
                            ))
                        atr = sum(tr) / 14
                        if current_price > 0:
                            market["vol"] = round(atr / current_price, 4)

            # Add signal data
            if signal:
                sig = {
                    "st": signal.strategy,
                    "sd": signal.side.lower(),
                    "c": round(signal.confidence / 100.0, 2),  # Normalize to 0-1
                }
                market["sg"] = [sig]

            # Build global context
            global_ctx = {
                "eq": round(equity, 0),
                "pos": len(open_positions),
                "pnl": round(daily_pnl, 1),
                "btc": _round_price(current_price) if symbol == "BTC" else 0,
                "b1h": 0.0,
                "b24h": 0.0,
                "eb": 0.0,
            }
            if circuit_breaker_active:
                global_ctx["cb"] = True

            # Build position context
            positions = []
            for sym, pos in open_positions.items():
                positions.append({
                    "s": sym,
                    "sd": pos.side.lower() if hasattr(pos, "side") else "long",
                    "e": _round_price(pos.entry) if hasattr(pos, "entry") else 0,
                    "lev": pos.leverage if hasattr(pos, "leverage") else 1.0,
                    "st": pos.state if hasattr(pos, "state") else "OPEN",
                })

            snapshot = {
                "m": [market],
                "g": global_ctx,
            }
            if positions:
                snapshot["pos"] = positions

            return snapshot

        except Exception as e:
            logger.warning(f"[BACKTEST-LLM] Snapshot build failed for {symbol}: {e}")
            return None

    # ── Checkpoint / Resume ───────────────────────────────────────

    def save_checkpoint(
        self,
        candle_index: int,
        symbol: str,
        symbols_completed: List[str],
        equity: float,
    ):
        """Save checkpoint state atomically."""
        try:
            os.makedirs(self.checkpoint_dir, exist_ok=True)
            state = {
                "candle_index": candle_index,
                "symbol": symbol,
                "symbols_completed": symbols_completed,
                "equity": equity,
                "llm_stats": {
                    "total_cost_usd": self.total_cost_usd,
                    "llm_calls": self.llm_calls,
                    "llm_failures": self.llm_failures,
                    "candles_with_llm": self.candles_with_llm,
                    "candles_fallback": self.candles_fallback,
                    "budget_exhausted": self.budget_exhausted,
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            checkpoint_path = os.path.join(self.checkpoint_dir, "checkpoint.json")
            tmp_path = checkpoint_path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(state, f, indent=2)
            os.replace(tmp_path, checkpoint_path)

        except Exception as e:
            logger.warning(f"[BACKTEST-LLM] Checkpoint save failed: {e}")

    def _load_checkpoint(self) -> Optional[CheckpointState]:
        """Load most recent checkpoint."""
        checkpoint_path = os.path.join(self.checkpoint_dir, "checkpoint.json")
        if not os.path.exists(checkpoint_path):
            logger.info("[BACKTEST-LLM] No checkpoint found, starting fresh")
            return None

        try:
            with open(checkpoint_path) as f:
                data = json.load(f)

            # Restore LLM stats
            stats = data.get("llm_stats", {})
            self.total_cost_usd = stats.get("total_cost_usd", 0.0)
            self.llm_calls = stats.get("llm_calls", 0)
            self.llm_failures = stats.get("llm_failures", 0)
            self.candles_with_llm = stats.get("candles_with_llm", 0)
            self.candles_fallback = stats.get("candles_fallback", 0)
            self.budget_exhausted = stats.get("budget_exhausted", False)

            state = CheckpointState(
                candle_index=data["candle_index"],
                symbol=data["symbol"],
                symbols_completed=data.get("symbols_completed", []),
                equity=data["equity"],
                llm_stats=stats,
                timestamp=data.get("timestamp", ""),
            )

            logger.info(
                f"[BACKTEST-LLM] Resumed from checkpoint: "
                f"symbol={state.symbol}, candle={state.candle_index}, "
                f"equity=${state.equity:.2f}, cost=${self.total_cost_usd:.2f}"
            )
            return state

        except Exception as e:
            logger.warning(f"[BACKTEST-LLM] Checkpoint load failed: {e}")
            return None

    # ── Progress / Reporting ──────────────────────────────────────

    def get_progress_line(self, candle_idx: int, total_candles: int) -> str:
        """Format a progress line for console output."""
        budget_pct = (
            self.total_cost_usd / self.budget_usd * 100
            if self.budget_usd > 0
            else 0
        )
        return (
            f"[BACKTEST-LLM] [{candle_idx}/{total_candles}] "
            f"LLM: {self.candles_with_llm} calls (${self.total_cost_usd:.2f}) | "
            f"Fallback: {self.candles_fallback} | "
            f"Budget: ${self.total_cost_usd:.2f}/${self.budget_usd:.2f} ({budget_pct:.1f}%)"
        )

    def get_summary(self) -> Dict[str, Any]:
        """Return summary dict for the backtest report."""
        return {
            "total_cost_usd": round(self.total_cost_usd, 4),
            "budget_usd": self.budget_usd,
            "budget_used_pct": round(
                self.total_cost_usd / self.budget_usd * 100
                if self.budget_usd > 0
                else 0,
                1,
            ),
            "llm_calls": self.llm_calls,
            "llm_failures": self.llm_failures,
            "candles_with_llm": self.candles_with_llm,
            "candles_fallback": self.candles_fallback,
            "budget_exhausted": self.budget_exhausted,
            "decisions_logged": len(self.decisions),
        }

    def flush_decisions(self):
        """Write all buffered decisions to the JSONL log file."""
        if not self.decisions:
            return

        try:
            os.makedirs(os.path.dirname(self.decisions_log_path), exist_ok=True)
            with open(self.decisions_log_path, "a") as f:
                for dec in self.decisions:
                    f.write(json.dumps(dec, default=str) + "\n")
            logger.info(
                f"[BACKTEST-LLM] Flushed {len(self.decisions)} decisions to "
                f"{self.decisions_log_path}"
            )
        except Exception as e:
            logger.warning(f"[BACKTEST-LLM] Failed to flush decisions: {e}")

    # ── Private Helpers ───────────────────────────────────────────

    def _log_decision(
        self,
        decision,
        snapshot_data: dict,
        cost: float,
        trigger: str,
    ):
        """Buffer a decision for later flushing to JSONL."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": decision.action,
            "confidence": decision.confidence,
            "regime": decision.regime,
            "size_multiplier": decision.size_multiplier,
            "notes": decision.notes[:200] if decision.notes else "",
            "cost_usd": round(cost, 6),
            "trigger": trigger,
            "source": "backtest",
        }
        self.decisions.append(entry)

    def _compute_cost_from_stats(self, stats: Dict[str, Any]) -> float:
        """Compute cost from coordinator stats (uses Sonnet pricing as conservative estimate)."""
        in_tokens = stats.get("total_input_tokens", 0)
        out_tokens = stats.get("total_output_tokens", 0)
        # Use Sonnet pricing as conservative default
        in_cost = in_tokens * _DEFAULT_PRICING[0] / 1_000_000
        out_cost = out_tokens * _DEFAULT_PRICING[1] / 1_000_000
        return in_cost + out_cost

    def _compute_cost_from_usage(self, usage: Dict[str, Any]) -> float:
        """Compute cost from a single call_llm usage dict."""
        in_tokens = usage.get("input_tokens", 0)
        out_tokens = usage.get("output_tokens", 0)
        in_cost = in_tokens * _MODEL_PRICING["claude-haiku-4-5-20251001"][0] / 1_000_000
        out_cost = out_tokens * _MODEL_PRICING["claude-haiku-4-5-20251001"][1] / 1_000_000
        return in_cost + out_cost

    def _build_test_snapshot(self, symbol: str, price: float) -> dict:
        """Build a minimal test snapshot for preflight validation."""
        return {
            "m": [{
                "s": symbol,
                "p": _round_price(price),
                "d1h": 0.0,
                "d24h": 0.0,
            }],
            "g": {
                "btc": _round_price(price) if symbol == "BTC" else 0,
                "b1h": 0.0,
                "b24h": 0.0,
                "eb": 0.0,
                "pos": 0,
                "pnl": 0.0,
                "eq": 10000.0,
            },
        }


def _round_price(price: float) -> float:
    """Round price to appropriate precision."""
    if price >= 1000:
        return round(price, 1)
    elif price >= 1:
        return round(price, 2)
    elif price >= 0.01:
        return round(price, 4)
    else:
        return round(price, 6)
