"""
Analytics mixin for MultiStrategyBot.

Extracted from multi_strategy_main.py — contains performance tracking,
heartbeat, market updates, quant intel, portfolio calculations, and
periodic summaries.

All methods are designed to be mixed into MultiStrategyBot via inheritance.
They access bot state through `self.*` attributes.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any

from data.db import (
    log_equity, get_daily_summary, update_daily_performance,
    get_signal_performance,
)
from data.risk_log import get_rejection_counts
from data.ml_log import log_ml_stats
from data.learning import get_performance
from trading_config import DEFAULT_SYMBOLS
from data.fetchers.telemetry import Telemetry

# Enhanced Telegram alerts
from alerts.enhanced_telegram import format_heartbeat_telegram

# Feedback loop closers
from llm.cost_tracker import get_cost_tracker
from llm.self_performance import get_performance_stats

# Optional imports
try:
    from llm.survival_pressure import get_survival_report, get_survival_context_for_llm
    _SURVIVAL_PRESSURE_AVAILABLE = True
except ImportError:
    _SURVIVAL_PRESSURE_AVAILABLE = False

try:
    from llm.learning_mode import (
        is_learning_mode_active, get_learning_report,
    )
    _LEARNING_MODE_AVAILABLE = True
except ImportError:
    _LEARNING_MODE_AVAILABLE = False

try:
    from llm.deep_memory import get_deep_memory
    _DEEP_MEMORY_AVAILABLE = True
except ImportError:
    _DEEP_MEMORY_AVAILABLE = False

logger = logging.getLogger("bot.main")


def _fmt_price(price: float) -> str:
    """Format price with appropriate precision (handles micro-prices like PEPE)."""
    if price == 0:
        return "0"
    abs_p = abs(price)
    if abs_p >= 1.0:
        return f"{price:,.2f}"
    elif abs_p >= 0.001:
        return f"{price:.4f}"
    elif abs_p >= 0.000001:
        return f"{price:.8f}"
    else:
        return f"{price:.12f}"


class AnalyticsMixin:
    """Mixin providing analytics, heartbeat, and reporting methods."""

    def _compute_portfolio_leverage(self) -> float:
        """Compute total portfolio leverage as a fraction of equity.

        Formula: sum(abs(qty) * price * leverage) / equity
        E.g., 3 positions at 5x each with $1000 notional each = 15000 / equity.
        """
        open_pos = self.pos_mgr.get_open_positions()
        if not open_pos:
            return 0.0
        equity = self.risk_mgr.equity
        if equity <= 0:
            return 0.0
        total_notional = 0.0
        for sym, pos in open_pos.items():
            price = self._last_prices.get(sym, pos.entry)
            total_notional += abs(pos.qty) * price * pos.leverage
        return round(total_notional / equity, 2)

    def _compute_estimated_daily_funding(self) -> float:
        """Compute estimated daily funding cost as % of equity.

        Funding on Hyperliquid is paid 3x/day (every 8 hours).
        Cost = sum(abs(funding_rate) * 3 * leverage * position_value / equity) * 100
        Only counts positions paying funding (long+positive or short+negative rate).
        """
        open_pos = self.pos_mgr.get_open_positions()
        if not open_pos:
            return 0.0
        equity = self.risk_mgr.equity
        if equity <= 0:
            return 0.0
        total_daily_cost_pct = 0.0
        for sym, pos in open_pos.items():
            fr = self._last_funding_rates.get(sym, 0.0)
            if fr == 0:
                continue
            price = self._last_prices.get(sym, pos.entry)
            pos_value = abs(pos.qty) * price
            # Check if position is paying or receiving funding
            side_lower = pos.side.lower()
            is_paying = (
                (side_lower in ("long", "buy") and fr > 0) or
                (side_lower in ("short", "sell") and fr < 0)
            )
            if is_paying:
                # 3 payments per day, scaled by leverage
                daily_cost = abs(fr) * 3 * pos.leverage * pos_value / equity * 100
                total_daily_cost_pct += daily_cost
        return round(total_daily_cost_pct, 4)

    def _compute_portfolio_correlation(self) -> Dict[str, Any]:
        """Compute directional correlation risk across open positions.

        Returns risk assessment: low/medium/high based on same-direction
        exposure in correlated assets (BTC/ETH/SOL etc.).
        """
        open_pos = self.pos_mgr.get_open_positions()
        if len(open_pos) < 2:
            return {"avg_correlation": 0.0, "net_delta": 0, "risk_level": "low"}

        longs = [(s, p) for s, p in open_pos.items() if p.side == "LONG"]
        shorts = [(s, p) for s, p in open_pos.items() if p.side == "SHORT"]
        net_delta = len(longs) - len(shorts)

        HIGH_CORR_PAIRS = {
            frozenset({"BTC", "ETH"}): 0.85,
            frozenset({"SOL", "ETH"}): 0.70,
            frozenset({"BTC", "SOL"}): 0.65,
            frozenset({"AVAX", "SOL"}): 0.55,
            frozenset({"LINK", "ETH"}): 0.55,
        }

        # Check correlation among same-direction positions
        same_dir = [s for s, _ in longs] if len(longs) >= len(shorts) else [s for s, _ in shorts]
        max_corr = 0.0
        for i, s1 in enumerate(same_dir):
            for s2 in same_dir[i + 1:]:
                pair = frozenset({s1.split("/")[0], s2.split("/")[0]})
                corr = HIGH_CORR_PAIRS.get(pair, 0.3)
                max_corr = max(max_corr, corr)

        risk_level = "high" if max_corr > 0.7 or abs(net_delta) >= 3 else (
            "medium" if max_corr > 0.5 or abs(net_delta) >= 2 else "low"
        )

        return {
            "avg_correlation": round(max_corr, 2),
            "net_delta": net_delta,
            "same_dir_count": max(len(longs), len(shorts)),
            "risk_level": risk_level,
        }

    def _record_trade_dna(self, symbol: str, pos, event):
        """Record full trade DNA to deep memory after a position closes.

        Populates the deep memory system with complete trade anatomy
        so the LLM can learn from every trade: what worked, what failed,
        and which strategy/regime/symbol combos are most profitable.
        """
        if not _DEEP_MEMORY_AVAILABLE:
            return
        try:
            dm = get_deep_memory()

            # Determine outcome
            total_pnl = pos.realized_pnl if pos else event.pnl
            if total_pnl > 0:
                outcome = "WIN"
            elif total_pnl < -0.01:
                outcome = "LOSS"
            else:
                outcome = "BREAKEVEN"

            # Extract trade profile data
            _regime = ""
            _entry_type = ""
            if pos.trade_profile:
                _regime = pos.trade_profile.regime or ""
                _entry_type = pos.trade_profile.entry_type or ""

            # Extract LLM decision context from entry_reasons
            _er = pos.entry_reasons or {}
            _llm_action = _er.get("llm_action", "")
            _llm_conf = _er.get("llm_confidence", 0.0)
            _llm_reasoning = _er.get("llm_reasoning", "")
            _strategies_agreed = _er.get("strategies_agreed", [])
            if not _strategies_agreed and pos.strategy:
                _strategies_agreed = [pos.strategy]

            # Hold time
            hold_time_s = 0.0
            if pos.open_time:
                hold_time_s = (datetime.now(timezone.utc) - pos.open_time).total_seconds()

            # BTC trend context
            btc_price = self._last_prices.get("BTC", 0)
            btc_1h_change = self._price_changes_1h.get("BTC", 0)
            if btc_1h_change > 0.5:
                btc_trend = "bullish"
            elif btc_1h_change < -0.5:
                btc_trend = "bearish"
            else:
                btc_trend = "neutral"

            # Volume ratio and funding rate
            _vol_ratio = 0.0
            _funding_rate = self._last_funding_rates.get(symbol, 0.0)

            # ATR at entry (stored on position)
            _atr = pos.atr if pos.atr else 0.0

            # Generate trade ID
            trade_id = f"{symbol}_{pos.side}_{int(pos.open_time.timestamp())}"

            dm.record_full_trade(
                trade_id=trade_id,
                symbol=symbol,
                side=pos.side,
                entry_price=pos.entry,
                exit_price=event.price,
                sl=pos.original_sl,
                tp1=pos.tp1,
                tp2=pos.tp2,
                confidence=pos.confidence,
                leverage=pos.leverage,
                regime=_regime,
                strategies_agreed=_strategies_agreed,
                outcome=outcome,
                pnl=total_pnl,
                hold_time_s=hold_time_s,
                exit_reason=event.action,
                llm_action=_llm_action,
                llm_confidence=_llm_conf,
                llm_reasoning=_llm_reasoning,
                entry_type=_entry_type,
                btc_trend=btc_trend,
                volume_ratio=_vol_ratio,
                funding_rate=_funding_rate,
                atr=_atr,
            )

            # Record regime transition if regime changed during trade
            if _regime:
                current_regime = ""
                try:
                    current_regime = self.regime_detector.get_transition_summary()
                    if isinstance(current_regime, dict):
                        current_regime = current_regime.get("current", "")
                    elif isinstance(current_regime, list) and current_regime:
                        current_regime = str(current_regime[0])
                    else:
                        current_regime = str(current_regime) if current_regime else ""
                except Exception:
                    pass
                if current_regime and current_regime != _regime:
                    dm.regimes.record_transition(
                        from_regime=_regime,
                        to_regime=current_regime,
                        symbol=symbol,
                        trigger=f"trade_close_{event.action}",
                        context={"pnl": total_pnl, "hold_time_s": hold_time_s},
                    )

            logger.info(
                f"[DEEP-MEM] Recorded trade DNA: {symbol} {pos.side} "
                f"{outcome} PnL=${total_pnl:+.2f}"
            )

        except Exception as e:
            logger.debug(f"[DEEP-MEM] Failed to record trade DNA: {e}")

    def _send_heartbeat(self):
        """Send periodic status heartbeat."""
        # Measure rejection outcomes with current prices
        if hasattr(self, '_rejection_tracker') and self._rejection_tracker is not None:
            try:
                _prices = {sym: self._last_prices.get(sym, 0) for sym in self.symbols}
                _completed = self._rejection_tracker.measure_outcomes(_prices)
                if _completed:
                    _stats = self._rejection_tracker.get_stats_summary()
                    logger.info(
                        f"[REJECTION-TRACKER] {len(_completed)} outcomes measured. "
                        f"Marginal miss rate: {self._rejection_tracker.get_miss_rate('marginal_neg'):.0%}"
                    )
            except Exception as e:
                logger.debug(f"[REJECTION-TRACKER] Measurement error: {e}")
        fetcher_stats = self.fetcher.get_stats()
        ml_snap_filled = 0
        if self.ml:
            ml_snap_filled = sum(1 for s in self.ml.snapshots if s.future_return_1h is not None)
        status = {
            "equity": self.risk_mgr.equity,
            "open_positions": self.pos_mgr.get_open_count(),
            "daily_pnl": self.risk_mgr.circuit_breaker.daily_pnl,
            "ml_samples": len(self.ml.outcomes) if self.ml else 0,
            "ml_snapshots": len(self.ml.snapshots) if self.ml else 0,
            "ml_snap_trained": ml_snap_filled,
            "ml_direction_model": self.ml.snapshot_weights is not None if self.ml else False,
            "circuit_breaker": self.risk_mgr.circuit_breaker.get_status(),
        }

        # Log equity snapshot to database
        log_equity(
            equity=self.risk_mgr.equity,
            open_positions=self.pos_mgr.get_open_count(),
            daily_pnl=self.risk_mgr.circuit_breaker.daily_pnl,
            unrealized_pnl=self.pos_mgr.get_total_unrealized_pnl({
                sym: self.fetcher.latest_price(sym, DEFAULT_SYMBOLS[sym].coingecko_id) or 0
                for sym in DEFAULT_SYMBOLS.keys()
            })
        )

        # Daily strategy weight recompute from trades DB
        self.weight_mgr.recompute_from_db()

        # ML stats logging (data/ml/ml_stats.jsonl)
        ml_conf_trade = 0.0
        ml_conf_snapshot = 0.0
        ml_conf_fast = 0.0
        if self.ml:
            ml_conf_trade = self.ml.predict_win_probability(70, 0, False, False, 1.5) if self.ml.weights is not None and len(self.ml.weights) > 0 else 0.0
            ml_conf_snapshot = 1.0 if self.ml.snapshot_weights is not None else 0.0
            ml_conf_fast = 1.0 if self.ml.fast_weights is not None else 0.0
        log_ml_stats(
            ml_samples_total=status["ml_samples"],
            ml_conf_trade=ml_conf_trade,
            ml_conf_snapshot=ml_conf_snapshot,
            ml_conf_fast=ml_conf_fast,
            equity=status["equity"],
            open_positions=status["open_positions"],
        )

        # Risk rejection counts for heartbeat
        rejections = get_rejection_counts()

        # Rolling performance from learning hooks
        perf = get_performance()

        # Veto resolution is handled by growth.tick() via check_unresolved()

        # Operator channel: detect and report operational anomalies
        try:
            perf_stats = get_performance_stats()
            correlation_info = self._compute_portfolio_correlation()
            cost_stats = get_cost_tracker().get_stats()

            op_context = {
                "consecutive_losses": self.risk_mgr.circuit_breaker.consecutive_losses,
                "llm_accuracy": perf_stats.get("accuracy", 0.5),
                "llm_decisions_count": perf_stats.get("total_decisions", 0),
                "budget_used_pct": cost_stats.get("budget_used_pct", 0),
                "correlation_risk": correlation_info.get("risk_level", "low"),
                "hours_since_last_trade": 0,  # populated below
                "signals_generated": len(get_daily_summary().get("by_strategy", {})),
                "estimated_daily_funding_cost": self._compute_estimated_daily_funding(),
                "flip_success_rate": perf_stats.get("flip_success_rate", 0.5),
                "flip_count": perf_stats.get("flip_count", 0),
                "calibration": perf_stats.get("calibration", 0.0),
                "veto_accuracy": perf_stats.get("veto_accuracy", 0.5),
                "veto_count": 0,  # populated from growth veto_feedback via get_performance_stats()
                "streak": perf_stats.get("streak", ""),
            }
            self.operator_channel.check_and_report(op_context)
        except Exception as e:
            logger.debug(f"[HEARTBEAT] Operator channel check failed: {e}")

        # Survival Pressure: include survival score in heartbeat
        if _SURVIVAL_PRESSURE_AVAILABLE:
            try:
                _surv_report = get_survival_report()
                status["survival_score"] = _surv_report.get("survival_score", 50)
                status["survival_trend"] = _surv_report.get("improvement_trend", "neutral")
                status["net_pnl_after_funding"] = _surv_report.get("net_pnl_after_funding", 0)
            except Exception:
                pass

        # Learning Mode: include phase in heartbeat
        if _LEARNING_MODE_AVAILABLE:
            try:
                _lm_report = get_learning_report()
                status["learning_phase"] = _lm_report.get("phase", "UNKNOWN")
                status["learning_graduated"] = _lm_report.get("graduated", False)
            except Exception:
                pass

        self.alerts.send_heartbeat(status)

        # Enhanced Telegram heartbeat with actionable format
        try:
            _hb_ds = get_daily_summary()
            _hb_msg = format_heartbeat_telegram(
                equity=status["equity"],
                open_positions=status["open_positions"],
                daily_pnl=status.get("daily_pnl", 0),
                daily_trades=_hb_ds.get("total_trades", 0),
                daily_wins=_hb_ds.get("wins", 0),
                llm_mode=self.llm_mode.name,
                health_status="OK" if self.watchdog.get_status().get("stalled") is False else "STALLED",
            )
            # Heartbeat to Discord only — Telegram stays clean
            pass  # Enhanced heartbeat disabled for Telegram (was cluttering)
        except Exception:
            pass

        # Update daily performance aggregation in SQLite
        try:
            update_daily_performance()
        except Exception:
            pass

        # Wave 3: Portfolio Risk — rebalance suggestions in heartbeat
        if self.portfolio_risk and self.pos_mgr.get_open_count() >= 2:
            try:
                _rebal = self.portfolio_risk.get_rebalance_suggestions(
                    open_positions={s: {"side": p.side, "entry": p.entry,
                                       "qty": p.qty, "leverage": p.leverage}
                                   for s, p in self.pos_mgr.get_open_positions().items()},
                    equity=self.risk_mgr.equity,
                )
                if _rebal:
                    _rebal_str = "; ".join(
                        f"{r.get('symbol')}: {r.get('action')} ({r.get('reason', '')})"
                        for r in _rebal[:3]
                    )
                    logger.info(f"[REBALANCE] Suggestions: {_rebal_str}")
                    status["rebalance_suggestions"] = _rebal_str
            except Exception as e:
                logger.debug(f"Rebalance suggestion error: {e}")

        # Wave 4: Counterfactual — include veto accuracy in heartbeat
        if self.counterfactual:
            try:
                _cf_acc = self.counterfactual.get_veto_accuracy()
                if _cf_acc.get("total_resolved", 0) > 0:
                    status["veto_accuracy_cf"] = round(_cf_acc.get("accuracy", 0), 2)
                    status["veto_net_value"] = round(_cf_acc.get("net_veto_value", 0), 2)
            except Exception:
                pass

        strat_weights = self.weight_mgr.get_all_weights()
        weights_str = " ".join(f"{k}={v:.2f}" for k, v in strat_weights.items()) if strat_weights else "none"
        rej_str = " ".join(f"{k}={v}" for k, v in rejections.items()) if rejections else "none"
        wr20 = perf.get("win_rate_20", 0)

        _surv_str = ""
        if "survival_score" in status:
            _surv_str = f"survival={status['survival_score']:.0f}/{status['survival_trend']} "
        _learn_str = ""
        if "learning_phase" in status:
            _learn_str = f"learn={status['learning_phase']} "

        logger.info(
            f"[HEARTBEAT] equity=${status['equity']:,.2f} "
            f"positions={status['open_positions']} "
            f"daily_pnl=${status['daily_pnl']:+,.2f} "
            f"WR20={wr20:.0%} "
            f"{_surv_str}"
            f"{_learn_str}"
            f"ml_trades={status['ml_samples']} "
            f"ml_snaps={status['ml_snapshots']}({status['ml_snap_trained']}filled) "
            f"direction_model={'YES' if status['ml_direction_model'] else 'no'} "
            f"strat_weights=[{weights_str}] "
            f"rejections=[{rej_str}] "
            f"pending_orders={len(self.pending_orders.get_pending())} "
            f"{self._get_anticipatory_heartbeat_str()}"
            f"api={fetcher_stats['total_requests']} "
            f"cache={fetcher_stats['cache_hits']}"
        )

    def _get_anticipatory_heartbeat_str(self) -> str:
        """Build anticipatory engine status string for heartbeat log."""
        if self._anticipation_engine is None:
            return ""
        try:
            st = self._anticipation_engine.get_status()
            n_pending = st.get("active_pending", 0)
            n_triggered = st.get("total_triggered", 0)
            if n_pending == 0 and n_triggered == 0:
                return "anticipatory=idle "
            # Find nearest trigger level
            nearest = ""
            entries = st.get("pending_entries", [])
            if entries and hasattr(self, '_last_prices') and self._last_prices:
                best_dist = float("inf")
                for e in entries:
                    sym = e.get("symbol", "")
                    tgt = e.get("target_price", 0)
                    cur = self._last_prices.get(sym, 0)
                    if cur > 0 and tgt > 0:
                        dist = abs(cur - tgt) / cur
                        if dist < best_dist:
                            best_dist = dist
                            nearest = f" nearest={sym}@${tgt:.2f}({best_dist*100:.1f}%)"
            return f"anticipatory={n_pending}pending/{n_triggered}triggered{nearest} "
        except Exception:
            return ""

    def _send_quant_intel(self):
        """Send quant brain market intelligence to Telegram every ~30 min.

        Helps manual traders understand market structure during quiet periods.
        """
        try:
            lines = ["\U0001f4ca *MARKET INTEL*\n"]
            for symbol in DEFAULT_SYMBOLS:
                price = self._last_prices.get(symbol, 0)
                if price <= 0:
                    continue

                # Get regime and bias from quant brain's last decision
                regime = "unknown"
                bias = "neutral"
                wp_str = ""
                if self._quant_brain:
                    try:
                        # Use the last evaluation result cached by quant brain
                        last = getattr(self._quant_brain, '_last_decisions', {}).get(symbol)
                        if last:
                            regime = getattr(last, 'regime', 'unknown')
                            thesis = getattr(last, 'trade_thesis', None)
                            if thesis:
                                wp = getattr(thesis, 'win_prob', 0)
                                wp_str = f" WP={wp:.0%}"
                                action = getattr(thesis, 'action', '')
                                if 'entry' in action or action == 'go':
                                    setup = getattr(thesis, 'setup_key', '')
                                    if 'SELL' in setup or 'SHORT' in setup:
                                        bias = "bearish"
                                    elif 'BUY' in setup or 'LONG' in setup:
                                        bias = "bullish"
                    except Exception:
                        pass
                # Fallback: check ensemble's multi-TF trend
                if bias == "neutral":
                    mkt = self._price_changes_1h.get(symbol)
                    if mkt is not None:
                        if mkt < -0.5:
                            bias = "bearish"
                        elif mkt > 0.5:
                            bias = "bullish"

                # Get open position info
                pos_str = ""
                open_pos = self.pos_mgr.get_open_positions()
                if symbol in open_pos:
                    p = open_pos[symbol]
                    upnl = (price - p.entry) * p.qty if p.side == "LONG" else (p.entry - price) * p.qty
                    upnl *= p.leverage
                    pos_str = f" | \U0001f4cd {p.side} {p.leverage:.0f}x uPnL=${upnl:+.2f}"

                # Get anticipatory levels
                antici_str = ""
                if self._anticipation_engine:
                    try:
                        st = self._anticipation_engine.get_status()
                        for e in st.get("pending_entries", []):
                            if e.get("symbol") == symbol:
                                tgt = e.get("target_price", 0)
                                side = e.get("side", "?")
                                dist = abs(price - tgt) / price * 100
                                antici_str = f" | \U0001f3af {side} @ ${tgt:.2f} ({dist:.1f}% away)"
                                break
                    except Exception:
                        pass

                bias_icon = {"bullish": "\U0001f7e2", "bearish": "\U0001f534", "neutral": "\u26aa"}.get(bias, "\u26aa")
                lines.append(f"{bias_icon} *{symbol}* ${_fmt_price(price)} [{regime}] {bias}{wp_str}{pos_str}{antici_str}")

            # Sim equity
            if hasattr(self, '_sniper_simulator') and self._sniper_simulator is not None:
                try:
                    sim_eq = self._sniper_simulator._equity
                    sim_open = len(self._sniper_simulator._open_positions)
                    lines.append(f"\n\U0001f3ae Sim: ${sim_eq:,.2f} ({sim_open} open)")
                except Exception:
                    pass

            # Bot equity
            eq = self.risk_mgr.equity
            daily = getattr(self.risk_mgr, '_daily_pnl', 0)
            n_open = len(self.pos_mgr.get_open_positions())
            lines.append(f"\n\U0001f4b0 Equity: ${eq:,.2f} | Open: {n_open} | Daily: ${daily:+,.2f}")

            msg = "\n".join(lines)
            self.alerts.send_market_intel(msg)
            logger.debug(f"[QUANT-INTEL] Sent market intel to Telegram")
        except Exception as e:
            logger.debug(f"[QUANT-INTEL] Error: {e}")

    def _handle_ingested_signal(self, signal):
        """Handle an incoming signal from the Telegram signal ingestion pipeline.

        Runs LLM analysis, sends the thought process to Telegram, and
        optionally routes TAKE signals into the trading pipeline.
        """
        logger.info(
            f"[SIGNAL-PIPE] Received: {signal.symbol} {signal.side} "
            f"entry={signal.entry_price} sl={signal.stop_loss} tp1={signal.take_profit_1} "
            f"quality={signal.parse_quality:.0%}"
        )

        # Skip low-quality parses
        if signal.parse_quality < 0.6:
            logger.info(f"[SIGNAL-PIPE] Skipping low-quality parse ({signal.parse_quality:.0%})")
            return

        # Get knowledge context for the LLM
        knowledge_context = ""
        try:
            from llm.knowledge_seed import get_course_summary_for_prompt
            from llm.self_teaching import get_teaching_engine
            engine = get_teaching_engine()
            knowledge_context = (
                get_course_summary_for_prompt(signal.symbol, "") + "\n" +
                engine.get_knowledge_for_prompt(signal.symbol, "")
            )
        except Exception as e:
            logger.debug(f"[SIGNAL-PIPE] Knowledge context error: {e}")

        # Get roadmap state for curriculum level
        curriculum_level = 1
        learning_phase = "ABSORB"
        try:
            from llm.knowledge_roadmap import get_roadmap_state, PHASE_CONFIGS
            state = get_roadmap_state()
            config = PHASE_CONFIGS.get(state.current_phase, {})
            curriculum_level = config.get("curriculum_level", 1)
            learning_phase = config.get("learning_phase", "ABSORB")
        except Exception:
            pass

        # Get market data for context
        market_data = {}
        sym_cfg = DEFAULT_SYMBOLS.get(signal.symbol)
        if sym_cfg:
            try:
                price = self.fetcher.latest_price(signal.symbol, sym_cfg.coingecko_id)
                if price:
                    market_data["current_price"] = price
                    market_data["signal_vs_market_pct"] = (
                        (signal.entry_price - price) / price * 100
                    ) if signal.entry_price > 0 else 0
            except Exception:
                pass

        # Run LLM analysis
        from dataclasses import asdict
        from signals.llm_analyzer import analyze_signal, format_analysis_for_telegram
        from data.db import log_signal

        analysis = analyze_signal(
            signal_data=asdict(signal),
            market_data=market_data,
            knowledge_context=knowledge_context,
            curriculum_level=curriculum_level,
            learning_phase=learning_phase,
        )

        if analysis:
            # Send the digestible thought process to Telegram
            telegram_msg = format_analysis_for_telegram(analysis)
            self.alerts.send_market_update(telegram_msg)

            logger.info(
                f"[SIGNAL-PIPE] Analysis complete: {signal.symbol} {signal.side} -> "
                f"{analysis.verdict} (conf={analysis.verdict_confidence:.0%})"
            )

            # Update the ingested signal with analysis results
            signal.llm_analyzed = True
            signal.llm_verdict = analysis.verdict
            signal.llm_reasoning = analysis.verdict_reasoning
            signal.llm_confidence = analysis.verdict_confidence
            signal.llm_analysis_id = analysis.analysis_id

            # Log updated signal
            from signals.telegram_ingest import log_ingested_signal
            log_ingested_signal(signal)

            # Route high-confidence TAKE verdicts into trading pipeline
            if (analysis.verdict == "TAKE"
                    and analysis.verdict_confidence >= 0.75
                    and signal.entry_price > 0
                    and signal.stop_loss > 0
                    and signal.take_profit_1 > 0):
                logger.info(
                    f"[SIGNAL-PIPE] TAKE verdict for {signal.symbol} "
                    f"(conf={analysis.verdict_confidence:.0%}) — logging as external signal"
                )
                # Log to signals DB so it appears in analytics
                log_signal(
                    symbol=signal.symbol,
                    strategy="external_telegram",
                    side=signal.side,
                    confidence=analysis.verdict_confidence * 100,
                    entry=signal.entry_price,
                    sl=signal.stop_loss,
                    tp1=signal.take_profit_1,
                    tp2=signal.take_profit_2 if signal.take_profit_2 else 0,
                    atr=0,
                    leverage=1.0,
                    traded=False,
                    metadata={
                        "source": "telegram_ingest",
                        "llm_verdict": analysis.verdict,
                        "llm_confidence": analysis.verdict_confidence,
                        "analysis_id": analysis.analysis_id,
                        "original_source": signal.source_channel,
                    }
                )
        else:
            logger.warning(f"[SIGNAL-PIPE] LLM analysis failed for {signal.symbol}")
            self.alerts.send_market_update(
                f"[SIGNAL] {signal.symbol} {signal.side} "
                f"entry={signal.entry_price} sl={signal.stop_loss} tp1={signal.take_profit_1}\n"
                f"(LLM analysis unavailable)"
            )

    def _send_market_update(self, trace_id: str = ""):
        """Send periodic market assessment even when no signals fire.
        Helps testers stay informed and feeds data for ML improvement."""
        lines = [f"[MARKET UPDATE] {datetime.now(timezone.utc).strftime('%H:%M UTC')}"]

        for symbol, sym_cfg in DEFAULT_SYMBOLS.items():
            try:
                data = self.fetcher.fetch_multi_timeframe(symbol, sym_cfg.coingecko_id, self._needed_tfs)
                price = self.fetcher.latest_price(symbol, sym_cfg.coingecko_id)
                if price is None:
                    continue

                # Get all strategy assessments
                statuses = self.ensemble.get_all_status(symbol, data)

                # Volume ratio for chop detection
                vol_str = ""
                df_1h = data.get("1h")
                if df_1h is not None and not df_1h.empty and len(df_1h) >= 20:
                    avg_v = float(df_1h["volume"].tail(20).mean())
                    cur_v = float(df_1h["volume"].iloc[-1])
                    if avg_v > 0:
                        vr = cur_v / avg_v
                        vol_str = f" vol={vr:.1f}x" + (" [LOW]" if vr < 0.4 else "")

                # Build compact summary
                assessments = []
                for s in statuses:
                    strat = s.get("strategy", "?")
                    if strat == "regime_trend":
                        align_l = s.get("align_long", 0)
                        align_s = s.get("align_short", 0)
                        cross = s.get("cross", "none")
                        assessments.append(f"RT: L{align_l}/S{align_s} cross={cross}")
                    elif strat == "monte_carlo_zones":
                        action = s.get("action", "?")
                        mc = s.get("mc_prediction", {})
                        up = mc.get("up_prob", 0) if mc else 0
                        assessments.append(f"MC: {action} up={up:.0%}")
                    elif strat == "confidence_scorer":
                        action = s.get("action", "?")
                        assessments.append(f"CS: {action}")
                    elif strat == "multi_tier_quality":
                        side = s.get("side", "?")
                        regime = s.get("regime_score", 0)
                        assessments.append(f"MT: {side} regime={regime}")

                assessment_str = " | ".join(assessments)

                # Check if any open position
                open_pos = self.pos_mgr.get_open_positions()
                pos_str = ""
                if symbol in open_pos:
                    pos = open_pos[symbol]
                    pnl = (price - pos.entry) * pos.qty if pos.side == "LONG" else (pos.entry - price) * pos.qty
                    pos_str = f" [OPEN {pos.side} {pos.leverage:.0f}x PnL=${pnl:+,.0f}]"

                lines.append(f"  {symbol} ${_fmt_price(price)}{vol_str}{pos_str}")
                lines.append(f"    {assessment_str}")

            except Exception as e:
                lines.append(f"  {symbol}: error ({e})")

        msg = "\n".join(lines)
        self.alerts.send_market_update(msg)
        logger.info(msg.replace("\n", " | "))

    def _log_periodic_summary(self, final: bool = False):
        """Log periodic paper trading summary (every ~6 hours + on shutdown).

        Computes win rate, PnL, per-symbol breakdown using TradeLogger data.
        """
        label = "FINAL SESSION SUMMARY" if final else "PERIODIC SUMMARY"
        lines = [f"[{label}] tick={self._tick}"]

        # Open positions snapshot
        open_pos = self.pos_mgr.get_open_positions()
        lines.append(f"  Open positions: {len(open_pos)}")
        for sym, pos in open_pos.items():
            price = self._last_prices.get(sym)
            if price and pos.qty > 0:
                if pos.side == "LONG":
                    upnl = (price - pos.entry) * pos.qty * pos.leverage
                else:
                    upnl = (pos.entry - price) * pos.qty * pos.leverage
                lines.append(f"    {sym} {pos.side} {pos.leverage:.0f}x uPnL=${upnl:+,.2f}")

        # Circuit breaker state
        cb = self.risk_mgr.circuit_breaker
        lines.append(f"  Equity: ${self.risk_mgr.equity:,.2f} | Daily PnL: ${cb.daily_pnl:+,.2f} | Consec losses: {cb.consecutive_losses}")
        if cb.tripped:
            lines.append("  ** CIRCUIT BREAKER TRIPPED **")

        # Use TradeLogger report if available
        if self.trade_logger:
            report = self.trade_logger.generate_report()
            if "error" not in report:
                s = report["summary"]
                p = report["pnl"]
                lines.append(f"  Closed trades: {s['total_closed_trades']} | WR: {s['win_rate_pct']:.1f}% | Net PnL: ${p['net_pnl']:+.2f}")
                lines.append(f"  Avg win: ${p['avg_win']:+.2f} | Avg loss: ${p['avg_loss']:+.2f} | PF: {p['profit_factor']:.2f}x")

                # Per-symbol breakdown
                if report.get("by_symbol"):
                    sym_parts = []
                    for sym, st in report["by_symbol"].items():
                        sym_parts.append(f"{sym}:{st['trades']}t/{st['win_rate']:.0f}%/${st['pnl']:+.0f}")
                    lines.append(f"  By symbol: {' | '.join(sym_parts)}")
            else:
                lines.append(f"  Trades: {report['error']}")

        msg = "\n".join(lines)
        logger.info(msg.replace("\n", " | "))

        # Also send via alerts so it reaches Telegram/Discord
        try:
            self.alerts.send_market_update(msg)
        except Exception:
            pass
