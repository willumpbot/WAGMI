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
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-5": (15.0, 75.0),
}

# Default pricing for unknown models (use Sonnet as conservative estimate)
_DEFAULT_PRICING = (3.0, 15.0)

# Exit agent throttle: evaluate every N candles per position
# Exit-agent cadence: evaluate open positions EVERY bar. Live evaluates exits
# every scan with a 120s cooldown (bot/llm/exit_engine.py EXIT_EVAL_COOLDOWN_S);
# at the backtest's 1h bar resolution the faithful mapping is ceil(120/3600)=1,
# i.e. every bar (the old value of 6 left a 6-hour blind window live never had).
_EXIT_EVAL_INTERVAL = 1


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
        self._symbol_cost_usd: float = 0.0
        self._budget_per_symbol: float = budget_usd  # updated when symbols known
        self._num_symbols: int = 1

        # Call tracking
        self.llm_calls: int = 0
        self.llm_failures: int = 0
        self.candles_with_llm: int = 0
        self.candles_fallback: int = 0
        self.pre_filter_skips: int = 0  # Signals skipped before LLM call

        # Decision log
        self.decisions: List[Dict[str, Any]] = []
        self.decisions_log_path = os.path.join("data", "llm", "backtest_decisions.jsonl")

        # Exit decisions log (captures ALL exit agent responses)
        self.exit_decisions: List[Dict[str, Any]] = []

        # Learning lessons buffer
        self.learning_lessons: List[Dict[str, Any]] = []

        # Regime timeline (tracks transitions)
        self.regime_timeline: List[Dict[str, Any]] = []

        # Per-agent cost tracking
        self.agent_costs: Dict[str, float] = {}

        # Exit agent throttle
        self._exit_eval_counters: Dict[str, int] = {}

        # Resume state
        self.resume_state: Optional[CheckpointState] = None
        if resume:
            self.resume_state = self._load_checkpoint()

        # ── Replay-harness discipline (tools/replay_harness.py) ──────
        # All default OFF; a normal backtest is unaffected.
        # REPLAY_MAX_LLM_CALLS: hard cap on total LLM calls per run (0 = off).
        #   NOTE (call-cap semantics, documented not changed here — lower
        #   priority per the align-to-live task): this cap counts raw
        #   coordinator AGENT calls (stats["total_calls"], typically 4-5 per
        #   entry-pipeline DECISION: regime+quant+trade+risk+critic), not
        #   entry DECISIONS. A cap of e.g. 100 therefore buys ~20-25 entry
        #   decisions, not 100 — budget the cap accordingly when configuring
        #   REPLAY_MAX_LLM_CALLS, or divide by ~4-5 to estimate decisions.
        # REPLAY_LLM_SLEEP_S: sleep after each coordinator invocation so the
        #   live bot's CLI quota isn't starved by the replay burst.
        # REPLAY_MODE: journal every LLM invocation to data/replay_llm_journal.jsonl.
        try:
            self.max_llm_calls = int(os.getenv("REPLAY_MAX_LLM_CALLS", "0") or 0)
        except (TypeError, ValueError):
            self.max_llm_calls = 0
        try:
            self.llm_sleep_s = float(os.getenv("REPLAY_LLM_SLEEP_S", "0") or 0)
        except (TypeError, ValueError):
            self.llm_sleep_s = 0.0
        self.call_cap_reached = False
        self._journal_path = (
            os.path.join("data", "replay_llm_journal.jsonl")
            if os.getenv("REPLAY_MODE") else None
        )

        # ── Entry-event trigger filter (REPLAY_CAMPAIGN_PLAN §2.1) ────
        # REPLAY-gated: normal backtests keep the legacy confidence
        # pre-filter below. Fixes VAL1's first-come-first-served starvation
        # (cap burned on the weakest solo signals; multi-agree never seen).
        # LLM pipeline fires ONLY on entry events:
        #   num_agree >= 2, OR solo conf >= REPLAY_SOLO_CONF_MIN from the
        #   whitelist strategies (matched against the ORIGINATING solo
        #   strategy, not signal.strategy — see _replay_is_entry_event);
        # plus a per-symbol same-direction cooldown (only the first bar of a
        # signal cluster spends calls, default REPLAY_COOLDOWN_H=0.167 i.e.
        # ~10min, matching live's LLM-first dispatcher cooldown) and a
        # per-symbol call budget of cap/num_symbols (BTC cannot starve
        # ETH/SOL).
        #
        # ALIGN-TO-LIVE FIX A (diagnostic swarm finding): defaults were
        # solo_conf=75 + a 4h cooldown, invented for this harness and
        # present nowhere in live. Live's actual dispatcher
        # (multi_strategy_main.py:5429-5475) sends every non-None solo
        # signal to the LLM (ROUTER_SOLO_CONF_ENFORCE defaults false, so the
        # 60% mechanical floor never engages) on a 10-minute LLM-first
        # cooldown. Defaults now mirror that: conf floor 0, cooldown ~10min.
        # The whitelist mechanism itself is kept (env-tunable) rather than
        # removed, per the fix's explicit scope.
        self._replay_filter_on = bool(os.getenv("REPLAY_MODE"))
        try:
            self._replay_solo_conf = float(
                os.getenv("REPLAY_SOLO_CONF_MIN", "0"))
        except (TypeError, ValueError):
            self._replay_solo_conf = 0.0
        self._replay_solo_whitelist = {
            s.strip() for s in os.getenv(
                "REPLAY_SOLO_WHITELIST",
                "regime_trend,bollinger_squeeze,vmc_cipher,mean_reversion",
            ).split(",") if s.strip()
        }
        try:
            self._replay_cooldown_s = float(
                os.getenv("REPLAY_COOLDOWN_H", "0.167")) * 3600.0
        except (TypeError, ValueError):
            self._replay_cooldown_s = 0.167 * 3600.0
        self._replay_last_fire: Dict[str, float] = {}   # "SYM:SIDE" -> sim ts
        self._replay_symbol_calls: Dict[str, int] = {}  # symbol -> calls spent
        self.replay_entry_events = 0    # signals qualifying as entry events
        self.replay_starved_events = 0  # entry events lost to call caps
        self.replay_cooldown_skips = 0  # entry events inside a cluster cooldown

        # ── Point-in-time edge map (Fix B) ────────────────────────────
        # Live agents cite a setup EDGE MAP (g.edge / g.confl_wr / g.stperf,
        # llm/snapshot_builder.py:302-320) to justify going on otherwise-weak
        # signals ("SOL_SELL_consolidation 70% WR n=10"). The backtest never
        # populated these (no live deep-memory history exists inside a
        # replay), so agents saw only negative mechanical stats and skipped.
        # REPLAY_PIT_EDGE_MAP reconstructs the SAME g.edge/g.confl_wr/g.stperf
        # shape from data/trade_ledger.csv (+ data/trades.csv for the
        # per-strategy breakdown) using ONLY rows that had CLOSED strictly
        # before the current decision bar's timestamp — see
        # _build_pit_edge_map() for the leak-safety argument. Default ON
        # when REPLAY_MODE is set (this is what the replay harness needs),
        # default OFF otherwise so ordinary/mechanical backtests are
        # byte-for-byte unaffected.
        self._pit_edge_map_on = os.getenv(
            "REPLAY_PIT_EDGE_MAP",
            "true" if os.getenv("REPLAY_MODE") else "false",
        ).lower() in ("1", "true", "yes")
        # PIT edge-map sources: prefer the harness-provided frozen LIVE-history
        # seed (absolute paths via WAGMI_PIT_*), since the sandbox's own data tree
        # is empty by design. Fall back to the relative path for unit tests / bare
        # (non-harness) use. Leak-safety is enforced downstream by the strict
        # `row_close_ts < decision_ts` filter in _build_pit_edge_map, not by source.
        self._pit_ledger_path = os.getenv("WAGMI_PIT_LEDGER") or os.path.join("data", "trade_ledger.csv")
        self._pit_trades_path = os.getenv("WAGMI_PIT_TRADES") or os.path.join("data", "trades.csv")
        self._pit_ledger_rows_cache: Optional[List[Dict[str, Any]]] = None
        self._pit_trades_rows_cache: Optional[List[Dict[str, Any]]] = None

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

        # 1. API key check — allow CLI path (USE_CLI_LLM=true) to bypass API key requirement
        use_cli_llm = os.getenv("USE_CLI_LLM", "").lower() in ("true", "1", "yes")
        if use_cli_llm:
            logger.info("[PREFLIGHT] USE_CLI_LLM=true detected — skipping API key check, using claude CLI")
        else:
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

        # 2. API ping (one cheap Haiku call) — for CLI path, do a session-limit check
        if use_cli_llm:
            # Test the CLI session with a minimal call to detect session-limit 429 early.
            # Without this, the backtest runs all candles with every LLM call failing silently.
            try:
                from llm.claude_cli_client import call_agent as _cli_ping
                ping = _cli_ping(
                    user_prompt='{"ping":1}',
                    system_prompt="Reply with exactly: {\"ok\":true}",
                    model="haiku",
                    max_budget_usd=0.01,
                    timeout=30,
                )
                if not ping.ok and ("session limit" in (ping.error or "").lower() or "429" in (ping.error or "")):
                    result.passed = False
                    result.errors.append(
                        f"CLI SESSION LIMIT HIT — all LLM calls will fail. "
                        f"Retry after session resets (error: {ping.error[:120]})"
                    )
                    return result
                logger.info(f"[PREFLIGHT] CLI session OK (latency {ping.latency_s:.1f}s)")
            except Exception as e:
                result.warnings.append(f"CLI session ping failed (non-fatal): {e}")

        else:
            try:
                from llm.client import call_llm
                text, usage = call_llm(
                    system_prompt="Reply with exactly: OK",
                    snapshot_json="{}",
                    model="claude-haiku-4-5",
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
            # PREFLIGHT_RETURN_FIX (2026-07-14): this `return result` was indented at
            # the try/except level, returning UNCONDITIONALLY after a successful ping
            # and short-circuiting data-validation (steps 3-7) — so preflight "passed"
            # even with empty data / candle_count=0. Now returns only on ping failure.

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

        # 6. Coordinator instantiation — use env-var-aware factory so that
        # AGENT_*_ENABLED flags (e.g. AGENT_QUANT_ENABLED=false) are honoured.
        try:
            from llm.agents.coordinator import get_coordinator
            self._coordinator = get_coordinator()
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

        # Set per-symbol budget so each symbol gets a fair share
        self._num_symbols = max(len(symbols), 1)
        self._budget_per_symbol = self.budget_usd / self._num_symbols
        logger.info(
            f"[PREFLIGHT] Per-symbol budget: ${self._budget_per_symbol:.2f} "
            f"({self._num_symbols} symbols)"
        )

        # 8. Learning systems validation — prevent spend-then-crash
        try:
            from llm.agents.learning_integration import process_agent_lesson  # noqa: F401
            from llm.deep_memory import get_deep_memory
            get_deep_memory()
        except Exception as e:
            result.warnings.append(
                f"Learning systems init warning: {e}. "
                f"Lessons may not persist to deep memory."
            )

        return result

    def reset_for_symbol(self, symbol: str):
        """Reset per-symbol budget tracking at the start of each symbol walk.

        This ensures each symbol gets a fair share of the total LLM budget
        instead of the first symbol consuming everything.
        """
        self._symbol_cost_usd = 0.0
        # Re-enable LLM if global budget not yet exhausted
        if self.total_cost_usd < self.budget_usd:
            self.budget_exhausted = False
        logger.info(
            f"[BACKTEST-LLM] Starting {symbol}: "
            f"symbol budget ${self._budget_per_symbol:.2f}, "
            f"global spent ${self.total_cost_usd:.2f}/${self.budget_usd:.2f}"
        )

    # ── Replay discipline ─────────────────────────────────────────

    def _replay_discipline(self, kind: str, calls_delta: int, cost: float,
                           symbol: str = "", extra: Optional[Dict[str, Any]] = None):
        """Replay-harness bookkeeping after a coordinator invocation.

        Journals the call, enforces the hard call cap, and rate-limits so
        the live bot's CLI quota isn't starved. No-op unless the REPLAY_*
        env vars are set (normal backtests are unaffected).
        """
        if symbol and calls_delta:
            # Per-symbol call accounting for the entry-event filter budget
            self._replay_symbol_calls[symbol] = (
                self._replay_symbol_calls.get(symbol, 0) + calls_delta)
        if self._journal_path:
            try:
                os.makedirs(os.path.dirname(self._journal_path), exist_ok=True)
                record = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "kind": kind,
                    "symbol": symbol,
                    "calls_delta": calls_delta,
                    "total_calls": self.llm_calls,
                    "cost_delta_usd": round(cost, 6),
                    "total_cost_usd": round(self.total_cost_usd, 6),
                    "cap": self.max_llm_calls,
                }
                if extra:
                    record.update(extra)
                with open(self._journal_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, default=str) + "\n")
            except Exception:
                pass  # Journaling must never break the run
        if (self.max_llm_calls > 0 and self.llm_calls >= self.max_llm_calls
                and not self.call_cap_reached):
            self.call_cap_reached = True
            logger.warning(
                f"[REPLAY] LLM call cap reached ({self.llm_calls}/"
                f"{self.max_llm_calls}) — no further LLM calls this run."
            )
        if self.llm_sleep_s > 0 and calls_delta > 0:
            time.sleep(self.llm_sleep_s)

    # ── Pre-LLM Signal Filter ─────────────────────────────────────

    def _replay_is_entry_event(self, signal) -> bool:
        """True if the signal qualifies as an entry event (plan §2.1):
        multi-strategy confluence (num_agree >= 2) OR a whitelisted solo
        strategy at conf >= REPLAY_SOLO_CONF_MIN (0-100 scale).

        ALIGN-TO-LIVE FIX A: the ensemble stamps `strategy="ensemble"` on
        EVERY signal it emits, including solo (num_agree==1) ones —
        strategies/ensemble.py's merge step (~line 3275) always constructs
        the merged Signal with strategy="ensemble" regardless of how many
        underlying strategies fired. Comparing `signal.strategy` against the
        solo whitelist therefore NEVER matched (it was always "ensemble",
        never "regime_trend"/"bollinger_squeeze"/etc.), so every solo signal
        fell through and was dropped as a non-entry-event. The actual
        originating strategy for a solo signal is recorded by the SAME
        ensemble merge step in `metadata["strategies_agree"]` (a length-1
        list when num_agree==1) — match against that instead, which is
        exactly the strategy live's dispatcher would see for this signal.
        """
        meta = getattr(signal, "metadata", None) or {}
        try:
            if int(meta.get("num_agree", 1) or 1) >= 2:
                return True
        except (TypeError, ValueError):
            pass
        try:
            conf = float(getattr(signal, "confidence", 0) or 0)
        except (TypeError, ValueError):
            conf = 0.0
        strategies_agree = meta.get("strategies_agree") if isinstance(meta, dict) else None
        if strategies_agree:
            solo_strategy = str(strategies_agree[0] or "")
        else:
            # Fallback for signals with no metadata (e.g. direct strategy-level
            # unit tests that never went through ensemble merge) — behave as
            # before rather than silently dropping them.
            solo_strategy = str(getattr(signal, "strategy", "") or "")
        return solo_strategy in self._replay_solo_whitelist and conf >= self._replay_solo_conf

    def _replay_symbol_cap(self) -> int:
        """Per-symbol LLM call budget = global cap / num_symbols (0 = off)."""
        if self.max_llm_calls <= 0:
            return 0
        return max(1, self.max_llm_calls // max(self._num_symbols, 1))

    def _replay_should_skip(self, signal, symbol: str) -> bool:
        """REPLAY-only entry-event trigger filter (REPLAY_CAMPAIGN_PLAN §2.1).

        Returns True (skip the LLM pipeline) unless:
        - the signal is an entry event (multi-agree OR whitelisted solo >= 75), AND
        - the symbol still has per-symbol call budget (cap/num_symbols), AND
        - the symbol+direction is outside its 4h cooldown (only the first bar
          of a persistent signal cluster spends calls).
        """
        if not self._replay_is_entry_event(signal):
            return True
        self.replay_entry_events += 1

        cap = self._replay_symbol_cap()
        if cap and self._replay_symbol_calls.get(symbol, 0) >= cap:
            self.replay_starved_events += 1
            return True

        meta = getattr(signal, "metadata", None) or {}
        side = str(getattr(signal, "side", "") or "").upper()
        key = f"{symbol}:{side}"
        sim_ts = meta.get("replay_sim_ts")  # stamped by engine._apply_llm_entry
        try:
            sim_ts = float(sim_ts) if sim_ts is not None else None
        except (TypeError, ValueError):
            sim_ts = None
        last = self._replay_last_fire.get(key)
        if (sim_ts is not None and last is not None
                and 0 <= (sim_ts - last) < self._replay_cooldown_s):
            self.replay_cooldown_skips += 1
            return True
        if sim_ts is not None:
            self._replay_last_fire[key] = sim_ts
        return False

    def _should_skip_llm(self, snapshot_data: Optional[dict], signal) -> bool:
        """Pre-filter signals BEFORE calling the LLM API to save budget.

        Skips signals that are almost certainly going to be vetoed anyway:
        - No signal at all
        - Solo strategy signal with low confidence (< 55%)
        - Signal in low_liquidity regime (hard limit in Trade Agent prompt)

        In REPLAY_MODE the legacy check is replaced by the entry-event
        trigger filter (see _replay_should_skip).

        Returns True if we should skip the LLM call entirely.
        """
        if not snapshot_data or not signal:
            return True

        if self._replay_filter_on:
            symbol = ""
            markets = snapshot_data.get("m", [])
            if markets:
                symbol = markets[0].get("s", "")
            return self._replay_should_skip(signal, symbol)

        # Check signal confidence — solo signals below floor almost always get vetoed.
        # Threshold reads from ENSEMBLE_CONFIDENCE_FLOOR (default 55% if not set).
        # In OVERDRIVE/paper-trading mode with floor=20, solo signals down to 20% pass through.
        _solo_floor = float(os.getenv("ENSEMBLE_CONFIDENCE_FLOOR", "55")) / 100.0
        markets = snapshot_data.get("m", [])
        if markets:
            sigs = markets[0].get("sg", [])
            if sigs and len(sigs) == 1:
                # Solo strategy signal — check confidence
                sig_conf = sigs[0].get("c", 0)
                if sig_conf < _solo_floor:
                    return True

        return False

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
        if self.budget_exhausted or self.call_cap_reached:
            # Replay sample purity: post-cap signals stay forced-skip, but
            # count the entry events the cap starved (report honesty).
            if (self._replay_filter_on and signal is not None
                    and self._replay_is_entry_event(signal)):
                self.replay_starved_events += 1
            self.candles_fallback += 1
            return None

        if not snapshot_data or not isinstance(snapshot_data, dict):
            self.candles_fallback += 1
            return None

        if self._coordinator is None:
            self.candles_fallback += 1
            return None

        # Pre-filter: skip obviously bad signals before spending API credits
        if self._should_skip_llm(snapshot_data, signal):
            self.pre_filter_skips += 1
            self.candles_fallback += 1
            return None

        try:
            decision = self._coordinator.get_trading_decision(
                snapshot_data, trigger_reason=trigger_reason
            )

            # Track cost (global + per-symbol)
            stats = self._coordinator.get_stats()
            call_cost = self._compute_cost_from_stats(stats)
            self.total_cost_usd += call_cost
            self._symbol_cost_usd += call_cost
            _calls_delta = stats.get("total_calls", 0)
            self.llm_calls += _calls_delta
            self._replay_discipline(
                "entry", _calls_delta, call_cost,
                symbol=(snapshot_data.get("m", [{}])[0].get("s", "")
                        if snapshot_data else ""),
                extra={
                    "decision": (getattr(decision, "action", None) or "none")
                                if decision else "none",
                    "decision_confidence": getattr(decision, "confidence", None)
                                           if decision else None,
                    "regime": getattr(decision, "regime", None)
                              if decision else None,
                    # A/B verdict metrics (THOUGHT_JOURNAL 2026-07-02 23:30Z):
                    # discrimination spread + positive-subset test need the
                    # forward return of REJECTED signals too — journal the
                    # signal's side/price/sim-time so synthesis can score
                    # approved vs rejected against the candle cache.
                    "signal_side": str(getattr(signal, "side", "") or ""),
                    "signal_entry": getattr(signal, "entry", None),
                    "signal_strategy": str(getattr(signal, "strategy", "")
                                           or ""),
                    "signal_confidence": getattr(signal, "confidence", None),
                    "sim_ts": (getattr(signal, "metadata", None)
                               or {}).get("replay_sim_ts"),
                },
            )

            if decision:
                self.candles_with_llm += 1
                self._log_decision(decision, snapshot_data, call_cost, trigger_reason)

                # Persist memory update from Trade Agent's 'mu' field
                # (mirrors decision_engine.py:726-730 behavior)
                if decision.memory_update:
                    try:
                        from llm.memory_store import apply_memory_update
                        symbol = ""
                        markets = snapshot_data.get("m", []) if snapshot_data else []
                        if markets:
                            symbol = markets[0].get("s", "")
                        apply_memory_update(
                            decision.memory_update,
                            symbol=symbol,
                            regime=decision.regime or "",
                        )
                    except Exception as e:
                        logger.debug(f"[BACKTEST-LLM] Memory update failed: {e}")
            else:
                self.candles_fallback += 1
                self._log_skipped_decision(
                    snapshot_data, call_cost, trigger_reason,
                    reason="coordinator_returned_none",
                )

            # Check budget (per-symbol first, then global)
            if self._symbol_cost_usd >= self._budget_per_symbol:
                self.budget_exhausted = True
                logger.warning(
                    f"[BACKTEST-LLM] Symbol budget exhausted: "
                    f"${self._symbol_cost_usd:.2f} >= ${self._budget_per_symbol:.2f}. "
                    f"Remaining candles for this symbol use strategy-only."
                )
            elif self.total_cost_usd >= self.budget_usd:
                self.budget_exhausted = True
                logger.warning(
                    f"[BACKTEST-LLM] Budget exhausted: "
                    f"${self.total_cost_usd:.2f} >= ${self.budget_usd:.2f}. "
                    f"Remaining candles will use strategy-only."
                )

            return decision

        except Exception as e:
            import traceback
            logger.warning(
                f"[BACKTEST-LLM] Entry evaluation failed: {e}\n"
                f"{traceback.format_exc()}"
            )
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
        if self.budget_exhausted or self.call_cap_reached or self._coordinator is None:
            return None

        symbol = position_data.get("symbol", "")

        # Throttle: evaluate on first candle (counter==1) and every N candles after
        counter = self._exit_eval_counters.get(symbol, 0) + 1
        self._exit_eval_counters[symbol] = counter
        if counter != 1 and counter % _EXIT_EVAL_INTERVAL != 0:
            return None

        try:
            result = self._coordinator.get_exit_intelligence(
                position_data, market_data
            )

            stats = self._coordinator.get_stats()
            call_cost = self._compute_cost_from_stats(stats)
            self.total_cost_usd += call_cost
            _calls_delta = stats.get("total_calls", 0)
            self.llm_calls += _calls_delta
            self._replay_discipline("exit", _calls_delta, call_cost, symbol=symbol)

            if self.total_cost_usd >= self.budget_usd:
                self.budget_exhausted = True

            # Log ALL exit decisions for audit trail and learning
            if result:
                self._log_exit_decision(result, position_data, call_cost, market_data)

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
        """Run Learning Agent after a trade closes. Returns lesson or None.

        Feeds lessons into ALL 6 growth systems via process_agent_lesson():
        deep memory, post-trade learner, hypothesis tracker, self-teaching,
        improvement proposals, and calibration ledger.
        """
        if self.budget_exhausted or self.call_cap_reached or self._coordinator is None:
            return None

        try:
            result = self._coordinator.get_post_trade_lesson(trade_data)

            stats = self._coordinator.get_stats()
            call_cost = self._compute_cost_from_stats(stats)
            self.total_cost_usd += call_cost
            _calls_delta = stats.get("total_calls", 0)
            self.llm_calls += _calls_delta
            self._replay_discipline(
                "learning", _calls_delta, call_cost,
                symbol=str(trade_data.get("symbol", "")),
            )

            if self.total_cost_usd >= self.budget_usd:
                self.budget_exhausted = True

            # CRITICAL: Feed lesson into ALL growth systems
            if result:
                self.learning_lessons.append(result)
                try:
                    from llm.agents.learning_integration import process_agent_lesson
                    process_agent_lesson(result, trade_data)
                except Exception as e:
                    logger.debug(f"[BACKTEST-LLM] Learning integration feed error: {e}")

            return result

        except Exception as e:
            logger.warning(f"[BACKTEST-LLM] Learning agent failed: {e}")
            self.llm_failures += 1
            return None

    # ── Point-in-Time Edge Map (Fix B) ──────────────────────────────
    #
    # Reconstructs the same g.edge / g.confl_wr / g.stperf shape live builds
    # from deep-memory trade history (core/llm_integration.py:557-609,
    # consumed via `trade_data = dict(snapshot)` in
    # llm/agents/coordinator.py's _build_trade_input, and via the explicit
    # `critic_data["g"] = snapshot["g"]` in _build_critic_input) — but
    # sourced from data/trade_ledger.csv (+ data/trades.csv for the
    # per-strategy breakdown) instead of live's deep-memory store, which is
    # empty/meaningless inside a replay.
    #
    # LEAK-SAFETY (the load-bearing property of this whole feature): both
    # source files are written to ONLY at trade CLOSE —
    # feedback/trade_ledger.py's `record_trade()` defaults `timestamp` to
    # `time.time()` at call time, and it is invoked from
    # core/close_pipeline/close_subscribers_accounting.py inside the CLOSE
    # event handler; data/trade_log.py's docstring is explicit: "File:
    # data/trades.csv / Written on every full trade close." So the
    # `timestamp` column IS the close time already — there is no separate
    # open-time field to be tricked by. Every row-inclusion test below uses
    # a STRICT `<` against the caller-supplied `cutoff_ts` (the decision
    # bar's own timestamp): a trade is included iff `row_close_ts <
    # cutoff_ts`. That is at least as strict as "<=T" (it only excludes the
    # single knife-edge instant where a close and a decision would share the
    # exact same epoch-float second, which in practice never happens) while
    # being unambiguously leak-free at the boundary. See
    # tests/test_backtest_llm.py TestPITEdgeMapLeakSafety for the assertion
    # that every row surviving the filter has close_ts < cutoff_ts.

    def _load_pit_ledger_rows(self) -> List[Dict[str, Any]]:
        """Load + cache data/trade_ledger.csv as (ts, symbol, side, regime,
        agreement_level, win, pnl) tuples. Read once per backtest run —
        the file is append-only and read-only here, so caching the parse
        is safe and avoids re-reading disk on every decision."""
        if self._pit_ledger_rows_cache is not None:
            return self._pit_ledger_rows_cache
        rows: List[Dict[str, Any]] = []
        try:
            import csv
            if os.path.exists(self._pit_ledger_path):
                with open(self._pit_ledger_path, "r", encoding="utf-8", newline="") as f:
                    for raw in csv.DictReader(f):
                        try:
                            ts = float(raw.get("timestamp", "") or "nan")
                        except (TypeError, ValueError):
                            continue
                        if ts != ts:  # NaN guard (unparsable timestamp)
                            continue
                        symbol = (raw.get("symbol") or "").strip()
                        side = (raw.get("side") or "").strip()
                        if not symbol or not side:
                            continue
                        regime = (raw.get("regime_1h") or "").strip() or "unknown"
                        try:
                            agreement = int(float(raw.get("agreement_level", "") or 0))
                        except (TypeError, ValueError):
                            agreement = 0
                        try:
                            win = int(float(raw.get("win", "") or 0)) == 1
                        except (TypeError, ValueError):
                            win = False
                        try:
                            pnl = float(raw.get("net_pnl", "") or 0.0)
                        except (TypeError, ValueError):
                            pnl = 0.0
                        rows.append({
                            "ts": ts, "symbol": symbol, "side": side,
                            "regime": regime, "agreement_level": agreement,
                            "win": win, "pnl": pnl,
                        })
        except Exception as e:
            logger.debug(f"[BACKTEST-LLM] PIT ledger load failed (non-fatal): {e}")
            rows = []
        self._pit_ledger_rows_cache = rows
        return rows

    def _load_pit_trades_rows(self) -> List[Dict[str, Any]]:
        """Load + cache data/trades.csv as (ts, strategies_agree, win) tuples.

        Used only for the per-strategy breakdown (g.stperf): trade_ledger.csv
        has no per-strategy attribution field (its `contributing_factors`
        column holds the merged signal's `strategy="ensemble"` stamp, not
        the underlying strategy list — same root cause as Fix A). trades.csv
        carries the real list in its `entry_reasons` JSON blob
        (`strategies_agree`), and its `timestamp` column is ALSO close-time
        (see module docstring), so the same strict `<cutoff_ts` filter
        applies identically.
        """
        if self._pit_trades_rows_cache is not None:
            return self._pit_trades_rows_cache
        rows: List[Dict[str, Any]] = []
        try:
            import csv
            if os.path.exists(self._pit_trades_path):
                with open(self._pit_trades_path, "r", encoding="utf-8", newline="") as f:
                    for raw in csv.DictReader(f):
                        ts_str = (raw.get("timestamp") or "").strip()
                        if not ts_str:
                            continue
                        try:
                            ts = datetime.fromisoformat(
                                ts_str.replace("Z", "+00:00")).timestamp()
                        except (TypeError, ValueError):
                            continue
                        strategies: List[str] = []
                        er = raw.get("entry_reasons") or ""
                        if er:
                            try:
                                parsed = json.loads(er)
                                sa = parsed.get("strategies_agree") if isinstance(parsed, dict) else None
                                if isinstance(sa, list):
                                    strategies = [str(s) for s in sa if s]
                            except (json.JSONDecodeError, AttributeError, TypeError):
                                pass
                        if not strategies:
                            continue
                        outcome = str(raw.get("outcome") or "")
                        if outcome:
                            win = "WIN" in outcome.upper()
                        else:
                            try:
                                win = float(raw.get("pnl", "") or 0.0) > 0
                            except (TypeError, ValueError):
                                win = False
                        rows.append({"ts": ts, "strategies": strategies, "win": win})
        except Exception as e:
            logger.debug(f"[BACKTEST-LLM] PIT trades.csv load failed (non-fatal): {e}")
            rows = []
        self._pit_trades_rows_cache = rows
        return rows

    def _build_pit_edge_map(self, cutoff_ts: float) -> Dict[str, Dict[str, Any]]:
        """Build {"edge": ..., "confl_wr": ..., "stperf": ...} from trade
        history that had CLOSED strictly before `cutoff_ts` (the current
        decision bar's timestamp, epoch seconds UTC).

        Shapes mirror live (llm/snapshot_builder.py:302-320 /
        core/llm_integration.py:557-609):
          - edge:     {"{symbol}_{side}_{regime}": {"wr": pct0-100, "n": int, "pnl": float}}
                      (n>=5, matching live's setup_edge_map threshold)
          - confl_wr: {"{agreement_level}": {"wr": pct0-100, "n": int, "pnl": float}}
                      (n>=3, matching live's per-level threshold)
          - stperf:   {"{strategy}": {"wr": pct0-100, "n": int}}
                      (n>=3, matching live's strategy_performance threshold)

        Empty sub-dicts are omitted entirely (matches live's conditional
        `if g.extra.get(...)` inclusion pattern).
        """
        out: Dict[str, Dict[str, Any]] = {}

        # ── g.edge: per symbol+side+regime ──
        ledger_rows = [r for r in self._load_pit_ledger_rows() if r["ts"] < cutoff_ts]
        edge_groups: Dict[str, Dict[str, Any]] = {}
        for r in ledger_rows:
            key = f"{r['symbol']}_{r['side']}_{r['regime']}"
            g = edge_groups.setdefault(key, {"n": 0, "wins": 0, "pnl": 0.0})
            g["n"] += 1
            g["wins"] += 1 if r["win"] else 0
            g["pnl"] += r["pnl"]
        edge_map = {
            k: {"wr": round(g["wins"] / g["n"] * 100), "n": g["n"], "pnl": round(g["pnl"], 2)}
            for k, g in edge_groups.items() if g["n"] >= 5
        }
        if edge_map:
            out["edge"] = edge_map

        # ── g.confl_wr: per agreement level ──
        confl_groups: Dict[str, Dict[str, Any]] = {}
        for r in ledger_rows:
            if r["agreement_level"] <= 0:
                continue
            key = str(r["agreement_level"])
            g = confl_groups.setdefault(key, {"n": 0, "wins": 0, "pnl": 0.0})
            g["n"] += 1
            g["wins"] += 1 if r["win"] else 0
            g["pnl"] += r["pnl"]
        confl_wr = {
            k: {"wr": round(g["wins"] / g["n"] * 100), "n": g["n"], "pnl": round(g["pnl"], 2)}
            for k, g in confl_groups.items() if g["n"] >= 3
        }
        if confl_wr:
            out["confl_wr"] = confl_wr

        # ── g.stperf: per contributing strategy ──
        trades_rows = [r for r in self._load_pit_trades_rows() if r["ts"] < cutoff_ts]
        strat_groups: Dict[str, Dict[str, Any]] = {}
        for r in trades_rows:
            for strat in r["strategies"]:
                g = strat_groups.setdefault(strat, {"n": 0, "wins": 0})
                g["n"] += 1
                g["wins"] += 1 if r["win"] else 0
        stperf = {
            k: {"wr": round(g["wins"] / g["n"] * 100), "n": g["n"]}
            for k, g in strat_groups.items() if g["n"] >= 3
        }
        if stperf:
            out["stperf"] = stperf

        return out

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
        decision_ts: Optional[float] = None,
    ) -> Optional[dict]:
        """Build a snapshot dict compatible with coordinator.get_trading_decision().

        Constructs the compact format that agents expect from the data available
        in the backtest walk loop.

        `decision_ts` (epoch seconds, UTC) is the current decision bar's own
        timestamp — the engine passes `sim_dt.timestamp()` (see
        backtest/engine.py's `_apply_llm_entry`/`_run_llm_exit`, same pattern
        already used for `signal.metadata["replay_sim_ts"]`). When provided
        and REPLAY_PIT_EDGE_MAP is enabled, it gates the point-in-time edge
        map (Fix B) — see `_build_pit_edge_map()` for the leak-safety
        argument. When omitted (None, the default), no edge map is injected
        and behavior is byte-for-byte identical to before this fix.
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
                # GAP FIX (confluence metadata): mirror live's sg structure
                # (llm/snapshot_builder.py:225-250), which surfaces flags/quality
                # prominently and passes the full per-signal meta blob through so
                # Trade/Risk/Critic agents see num_agree / strategies_agree / chop
                # score / regime alignment etc. Source: signal.metadata, populated
                # earlier in the SAME candle's walk-loop iteration (engine.py, e.g.
                # ~lines 870-988) from data already ≤T — no forward-looking fields.
                _meta = signal.metadata if isinstance(getattr(signal, "metadata", None), dict) else {}
                if _meta:
                    _flags = _meta.get("signal_flags")
                    if _flags:
                        sig["flags"] = _flags
                    _fpri = _meta.get("flag_max_priority")
                    if _fpri and _fpri >= 3:
                        sig["fpri"] = _fpri
                    _qs = _meta.get("quality_multiplier") or _meta.get("quality_score")
                    if _qs:
                        sig["qs"] = round(float(_qs), 2)
                    # Full confluence metadata (num_agree, strategies_agree, chop_score,
                    # regime, win_prob, ev_per_dollar, etc.) — same catch-all pattern as
                    # live's `sig["meta"] = s.meta`.
                    sig["meta"] = _meta
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

            # FIX B: point-in-time edge map (g.edge/g.confl_wr/g.stperf).
            # Gated on decision_ts being supplied (engine passes
            # sim_dt.timestamp(), the decision bar's own timestamp) AND the
            # REPLAY_PIT_EDGE_MAP flag. cutoff_ts=decision_ts means
            # _build_pit_edge_map only aggregates trades that had closed
            # strictly BEFORE this decision bar — see that method's
            # docstring for the full leak-safety argument. trade_data =
            # dict(snapshot) in coordinator.py's _build_trade_input, and the
            # explicit `critic_data["g"] = snapshot["g"]` in
            # _build_critic_input, both copy this "g" dict wholesale into
            # the Trade/Critic agent inputs unfiltered by _is_backtest — the
            # ONLY place that gate applies is the separate Quant-agent input
            # builder (coordinator.py ~3656), which is deliberately left
            # untouched (out of scope: a live-path file).
            if decision_ts is not None and self._pit_edge_map_on:
                try:
                    _pit = self._build_pit_edge_map(float(decision_ts))
                    if _pit:
                        global_ctx.update(_pit)
                except Exception as e:
                    logger.debug(f"[BACKTEST-LLM] PIT edge map build failed (non-fatal): {e}")

            # GAP FIX (BTC context): live's Regime agent gets BTC price + 1h/24h
            # change for every symbol (llm/snapshot_builder.py:256-266); backtest
            # previously hardcoded these to 0 for non-BTC symbols, blinding the
            # BTC-conditioned TAILWIND edge. Source: for symbol=="BTC" we reuse the
            # market's own d1h/d24h (already computed above from windowed_data["1h"],
            # strictly ≤T). For other symbols we use windowed_data["_btc_1h"] — the
            # engine (bot/backtest/engine.py:396-400) injects BTC's full 1h series
            # into this symbol's `data` dict before the walk begins, and the SAME
            # per-candle windowing (engine.py:577-595, cutoff=searchsorted(<candle
            # time, side="left")) that slices every other timeframe to strictly
            # before the decision bar also slices "_btc_1h" — so this is ≤T like
            # everything else here. If BTC data isn't available for this run at all,
            # the key is simply absent and we fall back to the 0.0 defaults above.
            if symbol == "BTC":
                global_ctx["b1h"] = market.get("d1h", 0.0)
                global_ctx["b24h"] = market.get("d24h", 0.0)
            else:
                _btc_1h = windowed_data.get("_btc_1h")
                if _btc_1h is not None and not _btc_1h.empty:
                    _btc_last_close = float(_btc_1h["close"].iloc[-1])
                    global_ctx["btc"] = _round_price(_btc_last_close)
                    if len(_btc_1h) >= 2:
                        _btc_prev = float(_btc_1h["close"].iloc[-2])
                        if _btc_prev > 0:
                            global_ctx["b1h"] = round(
                                (_btc_last_close - _btc_prev) / _btc_prev * 100, 1
                            )
                    if len(_btc_1h) >= 25:
                        _btc_24h_ago = float(_btc_1h["close"].iloc[-25])
                        if _btc_24h_ago > 0:
                            global_ctx["b24h"] = round(
                                (_btc_last_close - _btc_24h_ago) / _btc_24h_ago * 100, 1
                            )

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

            # GAP FIX (technical arrays): the coordinator's technicals enrichment
            # (RSI/MACD/ADX/Bollinger/ATR/EMA — llm/agents/coordinator.py, gated on
            # "ohlcv_1h" in snapshot_data) and the mech-regime overlay need raw OHLCV
            # candles; without them they silently produce nothing. Live builds this
            # array from the last 50 CLOSED candles (core/llm_integration.py:296-311)
            # as [ts_ms, open, high, low, close, volume]. Source here is
            # windowed_data["1h"]/["5m"] — the SAME dict already sliced to strictly
            # before the decision bar by engine.py's per-candle cutoff
            # (cutoff = df["time"].searchsorted(current_time, side="left");
            # windowed = df.iloc[start:cutoff], engine.py:577-595/1106-1116), i.e. it
            # never contains the decision candle itself or anything after it.
            _ohlcv_1h = _build_ohlcv_array(windowed_data.get("1h"))
            if _ohlcv_1h:
                snapshot["ohlcv_1h"] = _ohlcv_1h
            _ohlcv_5m = _build_ohlcv_array(windowed_data.get("5m"))
            if _ohlcv_5m:
                snapshot["ohlcv_5m"] = _ohlcv_5m

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
        """Save checkpoint state atomically.

        Flushes accumulated decisions to JSONL first so they survive crashes.
        """
        # Flush accumulated data to disk before checkpointing
        self.flush_decisions()

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
                    "agent_costs": dict(self.agent_costs),
                    "regime_timeline": self.regime_timeline,
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
            self.agent_costs = stats.get("agent_costs", {})
            self.regime_timeline = stats.get("regime_timeline", [])

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
            f"Pre-filtered: {self.pre_filter_skips} | "
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
            "pre_filter_skips": self.pre_filter_skips,
            "budget_exhausted": self.budget_exhausted,
            "decisions_logged": len(self.decisions),
            "agent_costs": dict(self.agent_costs),
            "exit_decisions_logged": len(self.exit_decisions),
            "learning_lessons_processed": len(self.learning_lessons),
            "regime_transitions": len(self.regime_timeline),
            "regime_timeline": self.regime_timeline,
            "veto_stats": self._compute_veto_stats(),
            "replay_filter": {
                "enabled": self._replay_filter_on,
                "entry_events": self.replay_entry_events,
                "starved_events": self.replay_starved_events,
                "cooldown_skips": self.replay_cooldown_skips,
                "per_symbol_calls": dict(self._replay_symbol_calls),
                "per_symbol_cap": self._replay_symbol_cap(),
                "solo_conf_min": self._replay_solo_conf,
                "solo_whitelist": sorted(self._replay_solo_whitelist),
                "cooldown_h": round(self._replay_cooldown_s / 3600, 1),
            },
        }

    def _compute_veto_stats(self) -> Dict[str, Any]:
        """Compute veto/approval stats from logged decisions."""
        total = len(self.decisions)
        if total == 0:
            return {"total_decisions": 0, "approved": 0, "vetoed": 0,
                    "veto_rate": 0.0}
        vetoed = sum(1 for d in self.decisions if d["action"] == "flat")
        approved = total - vetoed

        # Identify critic-driven vetoes vs other
        critic_vetoes = 0
        for d in self.decisions:
            if d["action"] != "flat":
                continue
            agents = d.get("agents", {})
            critic = agents.get("critic", {})
            if critic.get("ok") and critic.get("data", {}).get("verdict") == "challenge":
                critic_vetoes += 1

        return {
            "total_decisions": total,
            "approved": approved,
            "vetoed": vetoed,
            "critic_vetoes": critic_vetoes,
            "veto_rate": round(vetoed / max(total, 1), 3),
        }

    def flush_decisions(self):
        """Write all buffered decisions and exit decisions to JSONL log files."""
        if self.decisions:
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

        if self.exit_decisions:
            exit_log_path = os.path.join("data", "llm", "backtest_exits.jsonl")
            try:
                os.makedirs(os.path.dirname(exit_log_path), exist_ok=True)
                with open(exit_log_path, "a") as f:
                    for dec in self.exit_decisions:
                        f.write(json.dumps(dec, default=str) + "\n")
                logger.info(
                    f"[BACKTEST-LLM] Flushed {len(self.exit_decisions)} exit decisions"
                )
            except Exception as e:
                logger.warning(f"[BACKTEST-LLM] Failed to flush exit decisions: {e}")

    # ── Private Helpers ───────────────────────────────────────────

    def _log_decision(
        self,
        decision,
        snapshot_data: dict,
        cost: float,
        trigger: str,
    ):
        """Buffer a decision with full per-agent breakdown for learning."""
        # Extract symbol from snapshot data
        symbol = ""
        try:
            markets = snapshot_data.get("m", []) if snapshot_data else []
            if markets:
                symbol = markets[0].get("s", "")
        except (AttributeError, IndexError):
            pass

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "action": decision.action,
            "confidence": decision.confidence,
            "regime": decision.regime,
            "size_multiplier": decision.size_multiplier,
            "notes": decision.notes[:500] if decision.notes else "",
            "cost_usd": round(cost, 6),
            "trigger": trigger,
            "source": "backtest",
            # TRACE CAPTURE: full input snapshot for the study corpus (previously
            # missing entirely). This is the exact dict passed to
            # coordinator.get_trading_decision() for this decision.
            "snapshot": snapshot_data,
        }

        # Capture per-agent breakdown (regime, trade thesis, risk, critic)
        if self._coordinator:
            agent_detail = self._coordinator.get_last_pipeline_detail()
            if agent_detail:
                _attach_raw_text(agent_detail, self._coordinator.last_pipeline_results)
                entry["agents"] = agent_detail
                # Track per-agent costs with actual model pricing
                for agent_name, detail in agent_detail.items():
                    if not isinstance(detail, dict):
                        continue
                    if detail.get("ok"):
                        model = detail.get("model", "")
                        pricing = _MODEL_PRICING.get(model, _DEFAULT_PRICING)
                        agent_cost = (
                            detail.get("input_tokens", 0) * pricing[0] / 1_000_000
                            + detail.get("output_tokens", 0) * pricing[1] / 1_000_000
                        )
                        self.agent_costs[agent_name] = (
                            self.agent_costs.get(agent_name, 0) + agent_cost
                        )

        # Track regime timeline (only on transitions)
        regime = decision.regime
        if regime and (
            not self.regime_timeline
            or self.regime_timeline[-1]["regime"] != regime
        ):
            self.regime_timeline.append({
                "timestamp": entry["timestamp"],
                "regime": regime,
                "confidence": decision.confidence,
            })

        self.decisions.append(entry)

    def _log_exit_decision(
        self,
        result: Dict[str, Any],
        position_data: Dict[str, Any],
        cost: float,
        market_data: Optional[Dict[str, Any]] = None,
    ):
        """Buffer an exit agent decision for the audit trail."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": "exit",
            "symbol": position_data.get("symbol", ""),
            "action": result.get("action", "hold"),
            "urgency": result.get("urgency", "low"),
            "thesis_still_valid": result.get("thesis_still_valid"),
            "reason": result.get("reason", "")[:300],
            "cost_usd": round(cost, 6),
            "source": "backtest",
            # TRACE CAPTURE: full input snapshot (same rationale as _log_decision)
            "snapshot": market_data,
        }
        # Store exit agent detail
        if self._coordinator and self._coordinator.last_exit_output:
            out = self._coordinator.last_exit_output
            entry["agent_detail"] = {
                "data": out.data,
                "model": out.model_used,
                "input_tokens": out.input_tokens,
                "output_tokens": out.output_tokens,
                # Raw text as captured by coordinator.py's AgentOutput (already
                # capped to 500 chars at the source — see _attach_raw_text() docstring
                # for why we can't go further without touching shared/live code).
                "raw_text": getattr(out, "raw_text", "") or "",
            }
        self.exit_decisions.append(entry)

    def _log_skipped_decision(
        self,
        snapshot_data: Optional[dict],
        cost: float,
        trigger: str,
        reason: str,
    ):
        """Log a decision that was skipped (coordinator returned None)."""
        symbol = ""
        try:
            markets = snapshot_data.get("m", []) if snapshot_data else []
            if markets:
                symbol = markets[0].get("s", "")
        except (AttributeError, IndexError):
            pass

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "action": "skipped",
            "confidence": 0,
            "regime": "",
            "cost_usd": round(cost, 6),
            "trigger": trigger,
            "source": "backtest",
            "skip_reason": reason,
            # TRACE CAPTURE: full input snapshot, even for skipped decisions —
            # the study corpus needs to see what the pipeline was fed when it
            # produced nothing, not just the successful cases.
            "snapshot": snapshot_data,
        }
        # Capture partial pipeline results even on failure
        if self._coordinator:
            agent_detail = self._coordinator.get_last_pipeline_detail()
            if agent_detail:
                _attach_raw_text(agent_detail, self._coordinator.last_pipeline_results)
                entry["agents"] = agent_detail
        self.decisions.append(entry)

    def _compute_cost_from_stats(self, stats: Dict[str, Any]) -> float:
        """Compute cost from coordinator stats using actual per-agent model pricing."""
        # Use per-agent costs from pipeline results when available
        if self._coordinator and self._coordinator.last_pipeline_results:
            total = 0.0
            for role, output in self._coordinator.last_pipeline_results.items():
                if output.ok:
                    pricing = _MODEL_PRICING.get(output.model_used, _DEFAULT_PRICING)
                    total += output.input_tokens * pricing[0] / 1_000_000
                    total += output.output_tokens * pricing[1] / 1_000_000
            if total > 0:
                return total
        # Fallback to stats-based estimate
        in_tokens = stats.get("total_input_tokens", 0)
        out_tokens = stats.get("total_output_tokens", 0)
        in_cost = in_tokens * _DEFAULT_PRICING[0] / 1_000_000
        out_cost = out_tokens * _DEFAULT_PRICING[1] / 1_000_000
        return in_cost + out_cost

    def _compute_cost_from_usage(self, usage: Dict[str, Any]) -> float:
        """Compute cost from a single call_llm usage dict."""
        in_tokens = usage.get("input_tokens", 0)
        out_tokens = usage.get("output_tokens", 0)
        in_cost = in_tokens * _MODEL_PRICING["claude-haiku-4-5"][0] / 1_000_000
        out_cost = out_tokens * _MODEL_PRICING["claude-haiku-4-5"][1] / 1_000_000
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


def _attach_raw_text(agent_detail: Dict[str, Any], pipeline_results: Optional[Dict[Any, Any]]) -> None:
    """Attach each agent's raw LLM response text to its serialized detail dict.

    get_last_pipeline_detail() (llm/agents/coordinator.py) serializes data/model/
    tokens/latency/ok/error per agent but does NOT include raw_text, even though
    each AgentOutput already carries it. We pull it directly from the coordinator's
    public `last_pipeline_results` dict here — no coordinator.py edit required.

    LIMITATION (documented, not fixed here): coordinator.py's `_call_agent`
    (shared with the live trading path) truncates AgentOutput.raw_text to 500
    chars AT THE SOURCE before we ever see it (`raw_text=raw_text[:500]`). That
    truncation happens inside code this task's constraints forbid touching
    ("Do NOT modify llm/coordinator... or any live trading path"), so the text
    captured here is whatever the coordinator already kept (<=500 chars), not
    truly unbounded. Getting the full response would require either editing
    that shared truncation point, or process-local monkeypatching of the LLM
    call functions to side-channel-capture text before truncation — both
    considered too invasive/fragile for this change and flagged for the owner
    to approve separately if the full text is needed.
    """
    if not agent_detail or not pipeline_results:
        return
    for role, output in pipeline_results.items():
        role_key = getattr(role, "value", role)
        if role_key in agent_detail and isinstance(agent_detail[role_key], dict):
            agent_detail[role_key]["raw_text"] = getattr(output, "raw_text", "") or ""


def _build_ohlcv_array(df) -> Optional[List[List[float]]]:
    """Build a [ts_ms, open, high, low, close, volume] array from a windowed df.

    Matches the shape live builds in core/llm_integration.py:296-311 (last 50
    candles) so llm/agents/technicals.py:compute_all_technicals() (needs >=30
    rows, closes[-1] treated as "now") works identically in backtest.

    `df` must already be sliced to strictly-before-decision-bar by the caller
    (the backtest engine's windowing) — this function does no time filtering
    of its own, it only reshapes. Returns None on missing/insufficient/malformed
    data so callers can omit the key entirely (matches existing fallback
    behavior — never crashes the backtest).
    """
    if df is None or df.empty or len(df) < 30:
        return None
    try:
        rows = []
        for _, row in df.tail(50).iterrows():
            ts = row.get("time")
            ts_ms = int(ts.timestamp() * 1000) if hasattr(ts, "timestamp") else 0
            rows.append([
                ts_ms,
                float(row.get("open", 0)),
                float(row.get("high", 0)),
                float(row.get("low", 0)),
                float(row.get("close", 0)),
                float(row.get("volume", 0)),
            ])
        return rows if rows else None
    except Exception:
        return None


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
