"""
Backtest Learning Bridge — Connects backtest outcomes to ALL learning systems.

Previously, backtesting was a pure dry run: it computed rich per-trade data
(PnL, strategy, symbol, confidence, leverage, regime) but discarded it all
when the process exited. None of the bot's feedback/learning systems were fed.

This module bridges that gap. After a backtest completes, it:

1. Feeds StrategyWeightManager — updates ensemble weights from historical performance
2. Seeds DeepMemoryManager — populates Trade DNA, strategy fingerprints, patterns
3. Feeds FeedbackLoop — primes confidence calibration, signal quality, parameter tuner
4. Primes SelfTeachingFramework — adds observations and principles from backtest data
5. Feeds GrowthOrchestrator — hypothesis evidence, learning cycles
6. Generates InsightJournal entries — auto-detected strategy/symbol/regime insights

Usage:
    from backtest.learning_bridge import BacktestLearningBridge

    engine = BacktestEngine(config)
    report = engine.run(symbols, days)

    bridge = BacktestLearningBridge()
    summary = bridge.ingest(engine)
    print(summary)
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

logger = logging.getLogger("bot.backtest.learning_bridge")


class BacktestLearningBridge:
    """
    Connects backtest results to all learning systems.

    Call `ingest(engine)` after a backtest completes to feed all
    learning systems with the backtest trade data.
    """

    def __init__(self, tag: str = "backtest"):
        self.tag = tag  # Source tag for all records
        self._stats = {
            "trades_ingested": 0,
            "strategy_weights_updated": 0,
            "deep_memory_records": 0,
            "feedback_outcomes": 0,
            "knowledge_entries": 0,
            "insights_generated": 0,
            "hypotheses_evidence": 0,
            "growth_trades": 0,
            "llm_decisions_ingested": 0,
        }

    def ingest(self, engine) -> Dict[str, Any]:
        """
        Ingest all trade data from a completed BacktestEngine into learning systems.

        Args:
            engine: A BacktestEngine instance that has completed a run.

        Returns:
            Summary dict of what was ingested.
        """
        trade_log = engine.pos_mgr.trade_log
        signals = engine.signals_generated

        # Filter to close events only (not OPENs) — must match engine._CLOSE_ACTIONS
        close_actions = ("SL", "TP1", "TP2", "TRAILING_STOP", "EARLY_EXIT",
                         "EMERGENCY", "BACKTEST_END", "HOLD_LIMIT",
                         "ROTATE_PROFIT", "ROTATE_LOSS_AVOIDANCE")
        closed_trades = [e for e in trade_log if e.action in close_actions]

        if not closed_trades:
            logger.info("[LEARN-BRIDGE] No closed trades to ingest")
            return {"status": "no_trades", **self._stats}

        logger.info(
            f"[LEARN-BRIDGE] Ingesting {len(closed_trades)} closed trades "
            f"from {len(signals)} signals into learning systems"
        )

        # Build enriched trade records from trade events
        trade_records = self._build_trade_records(closed_trades, signals, engine)

        # Build LLM regime lookup if LLM integration was used
        llm_regime_map = {}
        if hasattr(engine, "llm") and engine.llm and engine.llm.decisions:
            llm_regime_map = self._build_llm_regime_map(engine.llm.decisions)

        # Enrich trade records with LLM regime data
        if llm_regime_map:
            for record in trade_records:
                sym = record.get("symbol", "")
                # Try per-symbol regime, fall back to latest regime classification
                if sym in llm_regime_map:
                    record["regime"] = llm_regime_map[sym]
                elif "_latest" in llm_regime_map:
                    record["regime"] = llm_regime_map["_latest"]

        # Feed each learning system (each one is independent, wrapped in try/except)
        self._feed_strategy_weights(trade_records)
        self._feed_deep_memory(trade_records)
        self._feed_feedback_loop(trade_records)
        self._feed_self_teaching(trade_records)
        self._feed_growth_orchestrator(trade_records)
        self._generate_insights(trade_records)

        # Feed LLM-specific learnings
        if hasattr(engine, "llm") and engine.llm:
            self._feed_llm_decisions(engine.llm)

        logger.info(f"[LEARN-BRIDGE] Ingestion complete: {self._stats}")
        return {"status": "ok", **self._stats}

    def _build_trade_records(self, closed_trades, signals, engine) -> List[Dict]:
        """Build enriched trade records by joining trade events with signal data."""
        records = []

        # Build a signal lookup by symbol for enrichment
        signal_by_symbol = {}
        for sig in signals:
            sym = sig.get("symbol", "")
            if sym not in signal_by_symbol:
                signal_by_symbol[sym] = []
            signal_by_symbol[sym].append(sig)

        # Track open events for hold time calculation
        open_events = {}
        for event in engine.pos_mgr.trade_log:
            if event.action == "OPEN":
                open_events[event.symbol] = event

        for event in closed_trades:
            open_event = open_events.get(event.symbol)

            # Calculate hold time
            hold_time_s = 0.0
            if open_event:
                hold_time_s = (event.timestamp - open_event.timestamp).total_seconds()

            # Find matching signal for enrichment
            sym_signals = signal_by_symbol.get(event.symbol, [])
            matching_signal = None
            if sym_signals:
                # Use first unused signal for this symbol
                matching_signal = sym_signals.pop(0)

            record = {
                "symbol": event.symbol,
                "side": event.side,
                "strategy": event.strategy or (matching_signal or {}).get("strategy", "unknown"),
                "confidence": (matching_signal or {}).get("confidence", 50.0),
                "leverage": event.leverage,
                "pnl": event.pnl,
                "fee": event.fee,
                "outcome": "WIN" if event.pnl > 0 else "LOSS",
                "exit_reason": event.action,
                "hold_time_s": hold_time_s,
                "entry_price": open_event.price if open_event else 0.0,
                "exit_price": event.price,
                "sl": (matching_signal or {}).get("sl", 0.0),
                "tp1": (matching_signal or {}).get("tp1", 0.0),
                "tp2": (matching_signal or {}).get("tp2", 0.0),
                "entry": (matching_signal or {}).get("entry", 0.0),
                "source": self.tag,
            }
            records.append(record)

        self._stats["trades_ingested"] = len(records)
        return records

    # ── 1. Strategy Weight Manager ──────────────────────────────

    def _feed_strategy_weights(self, records: List[Dict]):
        """Feed backtest trade outcomes into StrategyWeightManager."""
        try:
            from data.strategy_weights import StrategyWeightManager

            # Use a separate file for backtest-seeded weights so we don't
            # overwrite live-trading weights
            mgr = StrategyWeightManager(
                path="ml_data/strategy_weights_backtest_seed.json"
            )

            for record in records:
                strategy = record.get("strategy", "")
                if not strategy or strategy == "unknown":
                    continue
                win = record["outcome"] == "WIN"
                mgr.record_outcome(strategy, win)
                self._stats["strategy_weights_updated"] += 1

            logger.info(
                f"[LEARN-BRIDGE] Strategy weights updated: "
                f"{mgr.get_all_weights()}"
            )
        except Exception as e:
            logger.warning(f"[LEARN-BRIDGE] Strategy weights feed failed: {e}")

    # ── 2. Deep Memory Manager ──────────────────────────────────

    def _feed_deep_memory(self, records: List[Dict]):
        """Seed deep memory with backtest trade DNA and strategy fingerprints."""
        try:
            from llm.deep_memory import get_deep_memory

            dm = get_deep_memory()

            for i, record in enumerate(records):
                trade_id = f"bt_{self.tag}_{i}_{int(time.time())}"

                dm.record_full_trade(
                    trade_id=trade_id,
                    symbol=record["symbol"],
                    side=record["side"],
                    entry_price=record.get("entry_price", 0.0),
                    exit_price=record["exit_price"],
                    sl=record.get("sl", 0.0),
                    tp1=record.get("tp1", 0.0),
                    tp2=record.get("tp2", 0.0),
                    confidence=record["confidence"],
                    leverage=record["leverage"],
                    regime=record.get("regime", "unknown"),  # LLM-enriched if --llm used
                    strategies_agreed=[record["strategy"]],
                    outcome=record["outcome"],
                    pnl=record["pnl"],
                    hold_time_s=record["hold_time_s"],
                    exit_reason=record["exit_reason"],
                    entry_type=self.tag,
                )
                self._stats["deep_memory_records"] += 1

            logger.info(
                f"[LEARN-BRIDGE] Deep memory seeded with "
                f"{self._stats['deep_memory_records']} trade DNA records"
            )
        except Exception as e:
            logger.warning(f"[LEARN-BRIDGE] Deep memory feed failed: {e}")

    # ── 3. Feedback Loop ────────────────────────────────────────

    def _feed_feedback_loop(self, records: List[Dict]):
        """Feed backtest outcomes into the FeedbackLoop for confidence calibration."""
        try:
            from feedback.loop import FeedbackLoop

            # Use a separate data dir for backtest feedback so we don't
            # pollute live feedback data
            fl = FeedbackLoop(data_dir="data/feedback_backtest")

            for record in records:
                # Record the signal
                fl.record_signal(
                    symbol=record["symbol"],
                    side=record["side"],
                    confidence=record["confidence"],
                    strategy=record["strategy"],
                    entry=record.get("entry", record.get("entry_price", 0.0)),
                    sl=record.get("sl", 0.0),
                    tp1=record.get("tp1", 0.0),
                    leverage=record["leverage"],
                )

                # Record the outcome
                fl.record_outcome(
                    confidence=record["confidence"],
                    win=record["outcome"] == "WIN",
                    pnl=record["pnl"],
                    strategy=record["strategy"],
                    symbol=record["symbol"],
                    side=record["side"],
                    hold_time_s=record["hold_time_s"],
                    exit_action=record["exit_reason"],
                    leverage=record["leverage"],
                )
                self._stats["feedback_outcomes"] += 1

            logger.info(
                f"[LEARN-BRIDGE] Feedback loop primed with "
                f"{self._stats['feedback_outcomes']} outcomes"
            )
        except Exception as e:
            logger.warning(f"[LEARN-BRIDGE] Feedback loop feed failed: {e}")

    # ── 4. Self-Teaching Knowledge Base ─────────────────────────

    def _feed_self_teaching(self, records: List[Dict]):
        """Extract observations and principles from backtest data and add to knowledge base."""
        try:
            from llm.self_teaching import get_teaching_engine

            st = get_teaching_engine()
            kb = st.knowledge

            # Aggregate stats for knowledge extraction
            by_strategy = {}
            by_symbol = {}
            by_side = {}
            total_pnl = 0.0
            wins = 0
            total = len(records)

            for r in records:
                strat = r["strategy"]
                sym = r["symbol"]
                side = r["side"]
                win = r["outcome"] == "WIN"

                if strat not in by_strategy:
                    by_strategy[strat] = {"wins": 0, "total": 0, "pnl": 0.0}
                by_strategy[strat]["total"] += 1
                if win:
                    by_strategy[strat]["wins"] += 1
                by_strategy[strat]["pnl"] += r["pnl"]

                if sym not in by_symbol:
                    by_symbol[sym] = {"wins": 0, "total": 0, "pnl": 0.0}
                by_symbol[sym]["total"] += 1
                if win:
                    by_symbol[sym]["wins"] += 1
                by_symbol[sym]["pnl"] += r["pnl"]

                if side not in by_side:
                    by_side[side] = {"wins": 0, "total": 0, "pnl": 0.0}
                by_side[side]["total"] += 1
                if win:
                    by_side[side]["wins"] += 1
                by_side[side]["pnl"] += r["pnl"]

                total_pnl += r["pnl"]
                if win:
                    wins += 1

            # Add overall observation
            if total > 0:
                wr = wins / total
                kb.add(
                    knowledge_type="observation",
                    content=(
                        f"Backtest ({total} trades): {wr:.0%} WR, "
                        f"${total_pnl:+.0f} PnL"
                    ),
                    confidence=0.7,
                    category="performance",
                    tags=["backtest", "overall"],
                    source="backtest",
                    evidence=f"{total} simulated trades",
                )
                self._stats["knowledge_entries"] += 1

            # Per-strategy observations
            for strat, stats in by_strategy.items():
                if stats["total"] >= 3:
                    wr = stats["wins"] / stats["total"]
                    knowledge_type = "principle" if stats["total"] >= 10 else "observation"
                    confidence = min(0.9, 0.5 + stats["total"] / 50)

                    kb.add(
                        knowledge_type=knowledge_type,
                        content=(
                            f"{strat}: {wr:.0%} WR over {stats['total']} backtest trades, "
                            f"${stats['pnl']:+.0f} PnL"
                        ),
                        confidence=confidence,
                        category="strategy",
                        tags=["backtest", strat],
                        source="backtest",
                        evidence=f"{stats['total']} trades, {stats['wins']} wins",
                    )
                    self._stats["knowledge_entries"] += 1

            # Per-symbol observations
            for sym, stats in by_symbol.items():
                if stats["total"] >= 3:
                    wr = stats["wins"] / stats["total"]
                    kb.add(
                        knowledge_type="observation",
                        content=(
                            f"{sym}: {wr:.0%} WR over {stats['total']} backtest trades, "
                            f"${stats['pnl']:+.0f} PnL"
                        ),
                        confidence=min(0.8, 0.5 + stats["total"] / 40),
                        category="symbol",
                        tags=["backtest", sym],
                        source="backtest",
                        evidence=f"{stats['total']} trades",
                    )
                    self._stats["knowledge_entries"] += 1

            # Side bias detection
            for side, stats in by_side.items():
                if stats["total"] >= 5:
                    wr = stats["wins"] / stats["total"]
                    if wr >= 0.65 or wr <= 0.35:
                        kb.add(
                            knowledge_type="observation",
                            content=(
                                f"{side} trades: {wr:.0%} WR over {stats['total']} "
                                f"backtest trades — {'strong' if wr >= 0.65 else 'weak'} side"
                            ),
                            confidence=0.6,
                            category="direction",
                            tags=["backtest", side.lower()],
                            source="backtest",
                        )
                        self._stats["knowledge_entries"] += 1

            # Anti-patterns: detect consistently losing strategies
            for strat, stats in by_strategy.items():
                if stats["total"] >= 5 and stats["wins"] / stats["total"] < 0.35:
                    wr = stats["wins"] / stats["total"]
                    kb.add(
                        knowledge_type="anti_pattern",
                        content=(
                            f"ANTI-PATTERN: {strat} has {wr:.0%} WR in backtest "
                            f"({stats['total']} trades, ${stats['pnl']:+.0f}). "
                            f"Consider reducing weight or investigating conditions."
                        ),
                        confidence=0.7,
                        category="strategy",
                        tags=["backtest", strat, "warning"],
                        source="backtest",
                    )
                    self._stats["knowledge_entries"] += 1

            logger.info(
                f"[LEARN-BRIDGE] Self-teaching primed with "
                f"{self._stats['knowledge_entries']} knowledge entries"
            )
        except Exception as e:
            logger.warning(f"[LEARN-BRIDGE] Self-teaching feed failed: {e}")

    # ── 5. Growth Orchestrator ──────────────────────────────────

    def _feed_growth_orchestrator(self, records: List[Dict]):
        """Feed trade outcomes into the growth orchestrator for hypothesis tracking."""
        try:
            from llm.growth.orchestrator import get_growth_orchestrator

            growth = get_growth_orchestrator()

            for record in records:
                trade_data = {
                    "symbol": record["symbol"],
                    "side": record["side"],
                    "outcome": record["outcome"],
                    "pnl": record["pnl"],
                    "confidence": record["confidence"],
                    "strategy": record["strategy"],
                    "leverage": record["leverage"],
                    "hold_time_s": record["hold_time_s"],
                    "num_agree": 1,
                    "source": self.tag,
                }
                growth.on_trade_closed(trade_data)
                self._stats["growth_trades"] += 1

            logger.info(
                f"[LEARN-BRIDGE] Growth orchestrator fed "
                f"{self._stats['growth_trades']} trades"
            )
        except Exception as e:
            logger.warning(f"[LEARN-BRIDGE] Growth orchestrator feed failed: {e}")

    # ── 6. Auto-Generated Insights ──────────────────────────────

    def _generate_insights(self, records: List[Dict]):
        """Auto-detect insights from backtest data and write to InsightJournal."""
        try:
            from llm.deep_memory import get_deep_memory

            dm = get_deep_memory()
            journal = dm.insights

            # Strategy effectiveness insights
            by_strategy = {}
            for r in records:
                strat = r["strategy"]
                if strat not in by_strategy:
                    by_strategy[strat] = {"wins": 0, "total": 0, "pnl": 0.0, "confidences": []}
                by_strategy[strat]["total"] += 1
                if r["outcome"] == "WIN":
                    by_strategy[strat]["wins"] += 1
                by_strategy[strat]["pnl"] += r["pnl"]
                by_strategy[strat]["confidences"].append(r["confidence"])

            for strat, stats in by_strategy.items():
                if stats["total"] < 3:
                    continue
                wr = stats["wins"] / stats["total"]

                # High-performing strategy
                if wr >= 0.60 and stats["total"] >= 5:
                    journal.add_insight(
                        category="strategy_insight",
                        insight=(
                            f"{strat} shows strong backtest performance: "
                            f"{wr:.0%} WR over {stats['total']} trades, "
                            f"${stats['pnl']:+.0f} PnL"
                        ),
                        confidence=min(0.85, 0.5 + stats["total"] / 30),
                        evidence=f"Backtest data: {stats['total']} trades",
                        source="backtest",
                    )
                    self._stats["insights_generated"] += 1

                # Underperforming strategy
                elif wr <= 0.35 and stats["total"] >= 5:
                    journal.add_insight(
                        category="strategy_insight",
                        insight=(
                            f"{strat} underperforms in backtest: "
                            f"{wr:.0%} WR over {stats['total']} trades, "
                            f"${stats['pnl']:+.0f} PnL. Needs investigation."
                        ),
                        confidence=min(0.8, 0.5 + stats["total"] / 30),
                        evidence=f"Backtest data: {stats['total']} trades",
                        source="backtest",
                    )
                    self._stats["insights_generated"] += 1

                # Confidence calibration insight
                avg_conf = sum(stats["confidences"]) / len(stats["confidences"])
                if abs(avg_conf / 100 - wr) > 0.15 and stats["total"] >= 5:
                    direction = "over" if avg_conf / 100 > wr else "under"
                    journal.add_insight(
                        category="execution_insight",
                        insight=(
                            f"{strat} is {direction}-confident: avg confidence "
                            f"{avg_conf:.0f}% but actual WR {wr:.0%} "
                            f"(gap: {abs(avg_conf/100 - wr):.0%})"
                        ),
                        confidence=0.6,
                        evidence=f"Backtest: {stats['total']} trades",
                        source="backtest",
                    )
                    self._stats["insights_generated"] += 1

            # Symbol-level insights
            by_symbol = {}
            for r in records:
                sym = r["symbol"]
                if sym not in by_symbol:
                    by_symbol[sym] = {"wins": 0, "total": 0, "pnl": 0.0}
                by_symbol[sym]["total"] += 1
                if r["outcome"] == "WIN":
                    by_symbol[sym]["wins"] += 1
                by_symbol[sym]["pnl"] += r["pnl"]

            for sym, stats in by_symbol.items():
                if stats["total"] < 5:
                    continue
                wr = stats["wins"] / stats["total"]
                if wr >= 0.65:
                    journal.add_insight(
                        category="symbol_insight",
                        insight=(
                            f"{sym} is a high-WR symbol in backtest: "
                            f"{wr:.0%} over {stats['total']} trades"
                        ),
                        confidence=0.7,
                        source="backtest",
                    )
                    self._stats["insights_generated"] += 1
                elif wr <= 0.30:
                    journal.add_insight(
                        category="symbol_insight",
                        insight=(
                            f"{sym} is a low-WR symbol in backtest: "
                            f"{wr:.0%} over {stats['total']} trades. "
                            f"Consider excluding or investigating."
                        ),
                        confidence=0.7,
                        source="backtest",
                    )
                    self._stats["insights_generated"] += 1

            # Leverage vs PnL insight
            lev_trades = [r for r in records if r["leverage"] > 1.0]
            spot_trades = [r for r in records if r["leverage"] <= 1.0]
            if len(lev_trades) >= 3 and len(spot_trades) >= 3:
                lev_wr = sum(1 for r in lev_trades if r["outcome"] == "WIN") / len(lev_trades)
                spot_wr = sum(1 for r in spot_trades if r["outcome"] == "WIN") / len(spot_trades)
                if abs(lev_wr - spot_wr) > 0.10:
                    better = "leveraged" if lev_wr > spot_wr else "spot"
                    journal.add_insight(
                        category="risk_insight",
                        insight=(
                            f"{better} trades perform better in backtest: "
                            f"leveraged={lev_wr:.0%} WR ({len(lev_trades)} trades) vs "
                            f"spot={spot_wr:.0%} WR ({len(spot_trades)} trades)"
                        ),
                        confidence=0.6,
                        source="backtest",
                    )
                    self._stats["insights_generated"] += 1

            logger.info(
                f"[LEARN-BRIDGE] Generated {self._stats['insights_generated']} insights"
            )
        except Exception as e:
            logger.warning(f"[LEARN-BRIDGE] Insight generation failed: {e}")

    # ── 7. LLM Decision Learnings ─────────────────────────────────

    def _build_llm_regime_map(self, decisions: list) -> dict:
        """Build a symbol -> latest regime mapping from LLM decisions.

        Each decision entry now has a 'symbol' field (added by Bug 17 fix).
        Falls back to '_latest' for decisions without symbol.
        """
        regime_map = {}
        for dec in decisions:
            regime = dec.get("regime")
            if regime and regime != "unknown":
                regime_map["_latest"] = regime
                symbol = dec.get("symbol", "")
                if symbol:
                    regime_map[symbol] = regime
        return regime_map

    def _feed_llm_decisions(self, llm_integration):
        """Feed LLM agent decisions into learning systems for persistence.

        Uses enriched per-agent data (regime, trade thesis, critic reasoning)
        to feed deep memory, insights, and calibration systems.
        """
        try:
            decisions = llm_integration.decisions
            if not decisions:
                return

            from llm.deep_memory import get_deep_memory
            dm = get_deep_memory()

            for dec in decisions:
                regime = dec.get("regime")
                if regime and regime != "unknown":
                    # Record regime observation using correct API
                    try:
                        dm.regime_history.record_transition(
                            from_regime=regime,
                            to_regime=regime,
                            symbol=dec.get("symbol", "market"),
                            trigger="backtest_llm_classified",
                            context={
                                "confidence": dec.get("confidence", 0.5),
                                "source": "backtest_llm",
                            },
                        )
                    except (AttributeError, TypeError):
                        pass

                # Feed per-agent data for richer learning
                agents = dec.get("agents", {})

                # Critic counter-theses as prediction insights
                critic = agents.get("critic", {})
                if critic.get("ok"):
                    critic_data = critic.get("data", {})
                    counter_thesis = critic_data.get("counter_thesis", "")
                    if counter_thesis and critic_data.get("verdict") == "challenge":
                        try:
                            dm.insights.add_insight(
                                category="prediction",
                                insight=f"Critic counter-thesis: {counter_thesis[:150]}",
                                confidence=0.5,
                                evidence=f"Backtest veto: {critic_data.get('reason', '')[:100]}",
                                source="backtest_critic",
                            )
                        except (AttributeError, TypeError):
                            pass

                # Trade agent thesis accuracy tracking
                trade = agents.get("trade", {})
                if trade.get("ok"):
                    trade_data = trade.get("data", {})
                    thesis = trade_data.get("thesis", "")
                    if thesis:
                        try:
                            dm.insights.add_insight(
                                category="strategy",
                                insight=f"Trade thesis: {thesis[:150]}",
                                confidence=dec.get("confidence", 0.5),
                                evidence=f"Regime: {regime or 'unknown'}, action: {dec.get('action', '')}",
                                source="backtest_trade_agent",
                            )
                        except (AttributeError, TypeError):
                            pass

            self._stats["llm_decisions_ingested"] = len(decisions)
            logger.info(
                f"[LEARN-BRIDGE] LLM decisions ingested: "
                f"{self._stats['llm_decisions_ingested']} "
                f"(with per-agent data)"
            )
        except Exception as e:
            logger.warning(f"[LEARN-BRIDGE] LLM decision feed failed: {e}")

    def get_summary(self) -> str:
        """Get a human-readable summary of what was ingested."""
        lines = [
            "BACKTEST LEARNING SUMMARY",
            "=" * 40,
            f"  Trades ingested:       {self._stats['trades_ingested']}",
            f"  Strategy weights:      {self._stats['strategy_weights_updated']} updates",
            f"  Deep memory records:   {self._stats['deep_memory_records']}",
            f"  Feedback outcomes:     {self._stats['feedback_outcomes']}",
            f"  Knowledge entries:     {self._stats['knowledge_entries']}",
            f"  Insights generated:    {self._stats['insights_generated']}",
            f"  Growth trades fed:     {self._stats['growth_trades']}",
            f"  LLM decisions:         {self._stats['llm_decisions_ingested']}",
            "=" * 40,
        ]
        return "\n".join(lines)
