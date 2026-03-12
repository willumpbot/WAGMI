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
            "signal_digest_patterns": "",
            "signal_quality_seeded": 0,
            "calibration_seeded": 0,
            "params_tuned": [],
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

        # Feed signal digest patterns for quant learning (Block 4)
        if hasattr(engine, "_signal_digests") and engine._signal_digests:
            self._feed_signal_digest_patterns(engine._signal_digests, trade_records)

        # Pre-seed signal quality and calibration from backtest data (Block 5)
        self._preseed_signal_quality(trade_records)

        # Pre-seed parameter tuner from backtest results (Block 6)
        self._preseed_parameters(trade_records, engine)

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

    def finalize(self, merge_to_live: bool = False) -> Dict:
        """Merge backtest learning data into live/paper trading data stores.

        Call after ingest() to transfer backtest-learned strategy weights into
        the production weights file so the ensemble can use them immediately.

        Args:
            merge_to_live: If True, merge seed data into live files.
        Returns:
            Summary dict of what was merged.
        """
        if not merge_to_live:
            return {"status": "skipped"}

        merged = {}

        # Merge backtest strategy weights into live weights file
        try:
            from data.strategy_weights import StrategyWeightManager

            seed_path = "ml_data/strategy_weights_backtest_seed.json"
            live_path = "ml_data/strategy_weights.json"

            seed_mgr = StrategyWeightManager(path=seed_path)
            if not seed_mgr.data:
                logger.info("[LEARN-BRIDGE] No backtest seed weights to merge")
                return {"status": "no_seed_data"}

            live_mgr = StrategyWeightManager(path=live_path)

            for name, entry in seed_mgr.data.items():
                seed_wins = entry.get("wins", 0)
                seed_trials = entry.get("trials", 0)
                seed_recent = entry.get("recent_outcomes", [])

                if name not in live_mgr.data:
                    live_mgr.data[name] = entry.copy()
                else:
                    # Merge: add seed counts to live counts
                    live_mgr.data[name]["wins"] = live_mgr.data[name].get("wins", 0) + seed_wins
                    live_mgr.data[name]["trials"] = live_mgr.data[name].get("trials", 0) + seed_trials
                    # Append recent outcomes (keep last 20)
                    existing = live_mgr.data[name].get("recent_outcomes", [])
                    combined = existing + seed_recent
                    live_mgr.data[name]["recent_outcomes"] = combined[-20:]

                live_mgr.data[name]["weight"] = live_mgr.get_weight(name)

            live_mgr._save()
            merged["strategy_weights_merged"] = len(seed_mgr.data)
            logger.info(
                f"[LEARN-BRIDGE] Merged {len(seed_mgr.data)} strategy weights "
                f"from backtest into live: {list(seed_mgr.data.keys())}"
            )
        except Exception as e:
            logger.warning(f"[LEARN-BRIDGE] Strategy weight merge failed: {e}")
            merged["strategy_weights_error"] = str(e)

        return {"status": "merged", **merged}

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

    # ── Block 4: Signal Digest Pattern Extraction ───────────────────────

    def _feed_signal_digest_patterns(self, digests, trade_records):
        """Extract quant patterns from per-candle signal digests and feed to knowledge base."""
        try:
            from collections import defaultdict

            # 1. Strategy combo win rates
            combo_outcomes = defaultdict(lambda: {"wins": 0, "total": 0})
            for rec in trade_records:
                strategy = rec.get("strategy", "")
                win = rec.get("win", rec.get("pnl", 0) > 0)
                if strategy:
                    combo_outcomes[strategy]["total"] += 1
                    if win:
                        combo_outcomes[strategy]["wins"] += 1

            # 2. Near-miss analysis
            min_votes = 3
            near_miss_count = 0
            for entry in digests:
                d = entry.get("digest", {})
                consensus = d.get("consensus", {})
                agreement = consensus.get("agreement", 0)
                min_votes = consensus.get("min_votes_needed", 3)
                if agreement == min_votes - 1 and not entry.get("signal_generated"):
                    near_miss_count += 1

            # 3. Regime-strategy fire rates
            regime_strat_fires = defaultdict(lambda: defaultdict(int))
            for entry in digests:
                d = entry.get("digest", {})
                readings = d.get("readings", {})
                for strat_name, reading in readings.items():
                    regime = reading.get("regime", "unknown")
                    if reading.get("side") and reading["side"] != "NONE":
                        regime_strat_fires[regime][strat_name] += 1

            # Feed patterns to self-teaching knowledge base
            try:
                from llm.self_teaching import get_teaching_engine
                engine = get_teaching_engine()
                if engine:
                    # Feed strategy combo win rates as principles
                    for combo, data in combo_outcomes.items():
                        if data["total"] >= 5:
                            wr = data["wins"] / data["total"]
                            engine.knowledge.add(
                                knowledge_type="principle",
                                content=f"Strategy {combo}: {wr:.0%} WR over {data['total']} backtest trades",
                                confidence=min(0.9, 0.5 + data["total"] / 100),
                            )

                    # Feed near-miss observation
                    if near_miss_count > 0:
                        total_evals = len(digests)
                        engine.knowledge.add(
                            knowledge_type="observation",
                            content=(
                                f"Backtest near-misses: {near_miss_count} signals missed by 1 vote "
                                f"out of {total_evals} total evaluations "
                                f"({near_miss_count/total_evals:.1%} near-miss rate)"
                            ),
                            confidence=0.8,
                        )

                    # Feed regime-strategy fire rates
                    for regime, strats in regime_strat_fires.items():
                        if regime == "unknown":
                            continue
                        top_strats = sorted(strats.items(), key=lambda x: -x[1])[:3]
                        top_str = ", ".join(f"{s}({n})" for s, n in top_strats)
                        engine.knowledge.add(
                            knowledge_type="observation",
                            content=f"In {regime} regime, most active strategies: {top_str}",
                            confidence=0.7,
                        )

                    self._stats["signal_digest_patterns"] = (
                        f"{len(combo_outcomes)} combos, {near_miss_count} near-misses, "
                        f"{len(regime_strat_fires)} regimes"
                    )
            except Exception as e:
                logger.debug(f"[LEARN-BRIDGE] Self-teaching feed failed: {e}")

            logger.info(
                f"[LEARN-BRIDGE] Signal digest: {len(digests)} evaluations, "
                f"{near_miss_count} near-misses, {len(combo_outcomes)} strategy combos"
            )
        except Exception as e:
            logger.warning(f"[LEARN-BRIDGE] Signal digest pattern extraction failed: {e}")

    # ── Block 5: Pre-seed Signal Quality & Calibration ──────────────────

    def _preseed_signal_quality(self, trade_records):
        """Pre-seed signal quality scorer and confidence calibrator from backtest data.

        This means paper trading starts with calibrated quality scores
        instead of cold-start defaults.
        """
        if not trade_records:
            return

        # Pre-seed signal quality scorer
        try:
            from feedback.signal_quality import SignalQualityScorer
            scorer = SignalQualityScorer()
            seeded = 0
            for rec in trade_records:
                try:
                    scorer.update(
                        symbol=rec.get("symbol", "unknown"),
                        regime=rec.get("regime", "unknown"),
                        strategy=rec.get("strategy", "unknown"),
                        side=rec.get("side", "BUY"),
                        confidence=rec.get("confidence", 50),
                        win=rec.get("win", rec.get("pnl", 0) > 0),
                        pnl=rec.get("pnl", 0),
                    )
                    seeded += 1
                except Exception:
                    pass
            scorer.save()
            self._stats["signal_quality_seeded"] = seeded
            logger.info(f"[LEARN-BRIDGE] Signal quality pre-seeded with {seeded} trades")
        except Exception as e:
            logger.debug(f"[LEARN-BRIDGE] Signal quality pre-seed failed: {e}")

        # Pre-seed confidence calibrator
        try:
            from llm.confidence_calibrator import ConfidenceCalibrator
            calibrator = ConfidenceCalibrator()
            seeded = 0
            for rec in trade_records:
                conf = rec.get("confidence", 0)
                win = rec.get("win", rec.get("pnl", 0) > 0)
                if conf > 0:
                    calibrator.record(claimed_confidence=conf, actual_win=win)
                    seeded += 1
            calibrator.save()
            self._stats["calibration_seeded"] = seeded
            logger.info(f"[LEARN-BRIDGE] Confidence calibrator pre-seeded with {seeded} records")
        except Exception as e:
            logger.debug(f"[LEARN-BRIDGE] Confidence calibrator pre-seed failed: {e}")

    # ── Block 6: Pre-seed Parameter Tuner ───────────────────────────────

    def _preseed_parameters(self, trade_records, engine):
        """Pre-seed parameter tuner with optimized values from backtest analysis.

        Computes per-regime, per-symbol, and per-strategy performance to set:
        - regime_leverage_caps
        - symbol_confidence_offsets
        - strategy_weights
        - confidence_floor (first EV-positive bin)
        """
        if not trade_records or len(trade_records) < 10:
            return

        try:
            from collections import defaultdict
            import json
            from pathlib import Path

            # Group by regime
            regime_stats = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
            for rec in trade_records:
                regime = rec.get("regime", "unknown")
                regime_stats[regime]["total"] += 1
                regime_stats[regime]["pnl"] += float(rec.get("pnl", 0))
                if rec.get("win", rec.get("pnl", 0) > 0):
                    regime_stats[regime]["wins"] += 1

            # Group by symbol
            symbol_stats = defaultdict(lambda: {"wins": 0, "total": 0})
            for rec in trade_records:
                sym = rec.get("symbol", "unknown")
                symbol_stats[sym]["total"] += 1
                if rec.get("win", rec.get("pnl", 0) > 0):
                    symbol_stats[sym]["wins"] += 1

            # Group by strategy
            strategy_stats = defaultdict(lambda: {"wins": 0, "total": 0})
            for rec in trade_records:
                strat = rec.get("strategy", "unknown")
                strategy_stats[strat]["total"] += 1
                if rec.get("win", rec.get("pnl", 0) > 0):
                    strategy_stats[strat]["wins"] += 1

            # Confidence bin analysis
            conf_bins = defaultdict(lambda: {"wins": 0, "total": 0, "pnl": 0.0})
            for rec in trade_records:
                conf = rec.get("confidence", 0)
                bin_key = int(conf // 10) * 10  # 50, 60, 70, 80, 90
                conf_bins[bin_key]["total"] += 1
                conf_bins[bin_key]["pnl"] += float(rec.get("pnl", 0))
                if rec.get("win", rec.get("pnl", 0) > 0):
                    conf_bins[bin_key]["wins"] += 1

            # Build optimized parameters
            tuned = {}

            # Regime leverage caps: lower cap for losing regimes
            regime_caps = {}
            for regime, stats in regime_stats.items():
                if stats["total"] >= 3:
                    wr = stats["wins"] / stats["total"]
                    if wr < 0.40:
                        regime_caps[regime] = 3  # Very conservative
                    elif wr < 0.50:
                        regime_caps[regime] = 5
                    else:
                        regime_caps[regime] = 10  # Let it breathe
            if regime_caps:
                tuned["regime_leverage_caps"] = regime_caps

            # Symbol confidence offsets: raise floor on losing symbols
            overall_wr = sum(s["wins"] for s in symbol_stats.values()) / max(1, sum(s["total"] for s in symbol_stats.values()))
            symbol_offsets = {}
            for sym, stats in symbol_stats.items():
                if stats["total"] >= 5:
                    sym_wr = stats["wins"] / stats["total"]
                    offset = round((sym_wr - overall_wr) * 20, 1)  # Scale to ±10
                    offset = max(-10, min(10, offset))
                    if abs(offset) >= 2:
                        symbol_offsets[sym] = offset
            if symbol_offsets:
                tuned["symbol_confidence_offsets"] = symbol_offsets

            # Strategy weights: Laplace-smoothed WR
            strategy_weights = {}
            for strat, stats in strategy_stats.items():
                if stats["total"] >= 3:
                    wr = (stats["wins"] + 1) / (stats["total"] + 2)  # Laplace
                    strategy_weights[strat] = round(max(0.2, min(2.0, wr / 0.5)), 3)
            if strategy_weights:
                tuned["strategy_weights"] = strategy_weights

            # Confidence floor: first EV-positive bin
            for bin_key in sorted(conf_bins.keys()):
                stats = conf_bins[bin_key]
                if stats["total"] >= 3 and stats["pnl"] > 0:
                    tuned["confidence_floor"] = bin_key
                    break

            # Save tuned parameters
            if tuned:
                data_dir = Path("data")
                data_dir.mkdir(exist_ok=True)
                params_file = data_dir / "tuned_params.json"
                with open(params_file, "w") as f:
                    json.dump(tuned, f, indent=2)

                self._stats["params_tuned"] = list(tuned.keys())
                logger.info(
                    f"[LEARN-BRIDGE] Parameters pre-seeded: {list(tuned.keys())} "
                    f"→ {params_file}"
                )
        except Exception as e:
            logger.warning(f"[LEARN-BRIDGE] Parameter pre-seed failed: {e}")
