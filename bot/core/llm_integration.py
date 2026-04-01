"""
LLM integration mixin for MultiStrategyBot.

Extracted from multi_strategy_main.py — contains LLM trigger management,
meta-brain invocation, veto checks, context building, scout preparation,
and re-entry clearance logic.

All methods are designed to be mixed into MultiStrategyBot via inheritance.
They access bot state through `self.*` attributes.
"""

import logging
import os
import time
from typing import Dict, Any, Optional

import pandas as pd

from trading_config import DEFAULT_SYMBOLS
from data.fetchers.telemetry import Telemetry

# LLM meta-brain
from llm.autonomy import LLMMode, get_llm_mode, should_call_llm, llm_has_veto
from llm.decision_engine import get_trading_decision, DecisionResult
from llm.decision_types import (
    StrategySignal as LLMStrategySignal,
    MarketSnapshot as LLMMarketSnapshot,
    GlobalContext as LLMGlobalContext,
)
from llm.risk_gating import RiskContext as LLMRiskContext
from llm.triggers import LLMTrigger, TRIGGER_LABELS
from execution.candidate import TradeCandidate

# Global Brain + Portfolio Brain
from llm.global_brain import build_global_context, apply_global_bias
from llm.portfolio_brain import build_portfolio_snapshot

# Self-Tuning Risk Engine
from risk.self_tuning import (
    get_dynamic_leverage_cap,
    get_profile_params as get_risk_profile_params,
)

# Optional imports
try:
    from llm.survival_pressure import get_survival_context_for_llm
    _SURVIVAL_PRESSURE_AVAILABLE = True
except ImportError:
    _SURVIVAL_PRESSURE_AVAILABLE = False

try:
    from llm.learning_mode import (
        is_learning_mode_active, get_current_phase, LearningPhase,
    )
    _LEARNING_MODE_AVAILABLE = True
except ImportError:
    _LEARNING_MODE_AVAILABLE = False

try:
    from llm.deep_memory import get_deep_memory
    _DEEP_MEMORY_AVAILABLE = True
except ImportError:
    _DEEP_MEMORY_AVAILABLE = False

try:
    from llm.self_performance import get_compact_stats as get_llm_self_stats
    _SELF_PERF_AVAILABLE = True
except ImportError:
    _SELF_PERF_AVAILABLE = False

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


class LLMIntegrationMixin:
    """Mixin providing LLM meta-brain integration methods."""

    def _llm_veto_check(self, candidate: TradeCandidate, trace_id: str = ""):
        """Synchronous LLM check before opening a trade (VETO_ONLY+ mode).

        Returns DecisionResult if LLM says "flat" (veto), None if "proceed".
        If LLM fails (API error, timeout), defaults to proceed (no veto).
        """
        logger.info(
            f"[{trace_id}][{candidate.symbol}] LLM veto check: "
            f"{candidate.side} {candidate.entry_type} "
            f"conf={candidate.ensemble_confidence:.0f}%"
        )

        markets, global_ctx, risk_ctx, positions = self._build_llm_context()
        if not markets:
            return None  # No data -> no veto

        trigger_ctx = (
            f"PRE_TRADE veto check: {candidate.side} {candidate.symbol} "
            f"@ {_fmt_price(candidate.entry)} "
            f"type={candidate.entry_type} conf={candidate.ensemble_confidence:.0f}% "
            f"regime={candidate.regime} rr1={candidate.risk_reward_tp1:.2f} "
            f"strategies={candidate.strategies_agree}"
        )

        result = get_trading_decision(
            markets=markets,
            global_context=global_ctx,
            risk_context=risk_ctx,
            active_positions=positions,
            mode=self.llm_mode,
            use_compact_prompt=True,  # Save tokens on veto checks
            trigger_reason="pre_trade_veto",
            trigger_context=trigger_ctx,
            event_triggered=True,  # Bypass periodic throttle
        )

        # Log API usage
        if result.usage and result.usage.get("input_tokens", 0) > 0:
            from llm.client import get_usage_stats
            stats = get_usage_stats()
            logger.info(
                f"[LLM-VETO] tokens={result.usage.get('input_tokens', 0)}in/"
                f"{result.usage.get('output_tokens', 0)}out "
                f"est=${stats['estimated_cost_usd']:.4f}"
            )

        if result.decision is None:
            # API error or validation failure -> default to proceed
            logger.info(
                f"[{trace_id}][{candidate.symbol}] LLM veto: "
                f"no decision ({result.reason}), defaulting to proceed"
            )
            return None

        if result.decision.action == "flat":
            # LLM says skip this trade
            return result

        # LLM says proceed (or was downgraded from flip)
        candidate.llm_action = result.decision.action
        candidate.llm_confidence = result.decision.confidence
        candidate.llm_regime = result.decision.regime
        candidate.llm_size_mult = result.decision.size_multiplier
        candidate.llm_entry_adj = result.decision.entry_adjustment
        candidate.llm_notes = result.decision.notes
        candidate.llm_memory_update = result.decision.memory_update
        return None

    def _build_llm_context(self):
        """Build MarketSnapshot + GlobalContext + RiskContext from current bot state.

        Uses cached fetcher data (still hot from _tick_once processing).
        Called once per tick, not per symbol.
        """
        markets = []
        btc_price = 0.0
        btc_1h = 0.0
        btc_24h = 0.0
        eth_price = 0.0
        # ETH isn't in DEFAULT_SYMBOLS but we need its price for ETH/BTC ratio context
        try:
            eth_price = self.fetcher.latest_price("ETH", "ethereum") or 0.0
        except Exception:
            pass

        for symbol, sym_cfg in DEFAULT_SYMBOLS.items():
            price = self._last_prices.get(symbol)
            if not price or price <= 0:
                continue

            # Track BTC/ETH for global context
            if symbol == "BTC":
                btc_price = price
            elif symbol == "ETH":
                eth_price = price

            # Get cached data (fetcher cache is still warm)
            data = self.fetcher.fetch_multi_timeframe(
                symbol, sym_cfg.coingecko_id, self._needed_tfs
            )

            # Compute market context from 1h data
            pchange_1h = 0.0
            pchange_24h = 0.0
            vol_ratio = 1.0
            volatility = 0.0

            df_1h = data.get("1h")
            if df_1h is not None and not df_1h.empty and len(df_1h) > 2:
                try:
                    pchange_1h = (price - float(df_1h["close"].iloc[-2])) / float(df_1h["close"].iloc[-2]) * 100
                    if len(df_1h) > 24:
                        pchange_24h = (price - float(df_1h["close"].iloc[-24])) / float(df_1h["close"].iloc[-24]) * 100
                    avg_vol = float(df_1h["volume"].tail(20).mean())
                    if avg_vol > 0:
                        vol_ratio = float(df_1h["volume"].iloc[-1]) / avg_vol
                    if len(df_1h) > 14:
                        prev_c = df_1h["close"].shift(1)
                        tr = pd.concat([
                            df_1h["high"] - df_1h["low"],
                            (df_1h["high"] - prev_c).abs(),
                            (df_1h["low"] - prev_c).abs(),
                        ], axis=1).max(axis=1)
                        atr14 = float(tr.rolling(14, min_periods=1).mean().iloc[-1])
                        volatility = atr14 / price * 100
                except Exception:
                    pass

                if symbol == "BTC":
                    btc_1h = pchange_1h
                    btc_24h = pchange_24h

            # Get strategy signals from ensemble (uses cached evaluations)
            signals = []
            try:
                statuses = self.ensemble.get_all_status(symbol, data)
                for s in statuses:
                    strat_name = s.get("strategy", "unknown")
                    # Determine side from strategy output
                    action = s.get("action", s.get("side", "neutral"))
                    if action in ("BUY", "buy"):
                        side = "long"
                    elif action in ("SELL", "sell"):
                        side = "short"
                    else:
                        side = "neutral"

                    # Extract confidence-like metric
                    conf = s.get("confidence", 0)
                    if conf == 0:
                        # Try to infer from other fields
                        align_l = s.get("align_long", 0)
                        align_s = s.get("align_short", 0)
                        best_align = max(align_l, align_s)
                        if best_align > 0:
                            # align values are 0-4 criteria counts, normalize to 0-1
                            conf = best_align / 4.0
                        elif side != "neutral":
                            # Strategy has definitive action but no confidence — assign moderate default
                            conf = 0.5

                    regime_score = s.get("regime_score", s.get("align_long", 0))
                    if isinstance(regime_score, (int, float)) and regime_score > 1:
                        # align values are 0-4 criteria counts, normalize to 0-1
                        regime_score = regime_score / 4.0

                    # Extract signal_context from cached strategy signal
                    sig_meta = {}
                    try:
                        last_sig = self.ensemble.get_last_signal(symbol, strat_name)
                        if last_sig and last_sig.signal_context:
                            sig_meta["ctx"] = last_sig.signal_context
                    except Exception:
                        pass

                    signals.append(LLMStrategySignal(
                        symbol=symbol,
                        strategy=strat_name,
                        side=side,
                        confidence=min(conf, 1.0),
                        regime_score=min(regime_score, 1.0) if isinstance(regime_score, (int, float)) else 0.0,
                        meta=sig_meta,
                    ))
            except Exception:
                pass

            markets.append(LLMMarketSnapshot(
                symbol=symbol,
                price=price,
                price_change_1h_pct=pchange_1h,
                price_change_24h_pct=pchange_24h,
                volume_ratio=vol_ratio,
                volatility=volatility,
                signals=signals,
            ))

        # Global Brain: build cross-market context for LLM reasoning
        try:
            _gb_ctx = build_global_context(
                btc_price=btc_price,
                btc_1h_change=btc_1h,
                btc_24h_change=btc_24h,
                eth_price=eth_price,
                last_prices=self._last_prices,
                funding_rates=self._last_funding_rates,
            )
            self._global_bias = _gb_ctx.get("classified_bias", "neutral")
            self._global_bias_adjustment = apply_global_bias(
                self._global_bias,
                max_positions=self.config.max_open_positions,
            )
        except Exception as e:
            _gb_ctx = {}
            logger.debug(f"Global brain context error: {e}")

        # Global context (enriched with telemetry for LLM learning)
        eth_btc = eth_price / btc_price if btc_price > 0 else 0.0
        telem_snap = Telemetry.snapshot()
        global_ctx = LLMGlobalContext(
            timestamp=int(time.time() * 1000),
            btc_price=btc_price,
            btc_change_1h_pct=btc_1h,
            btc_change_24h_pct=btc_24h,
            eth_btc_ratio=eth_btc,
            total_open_positions=self.pos_mgr.get_open_count(),
            daily_pnl=self.risk_mgr.circuit_breaker.daily_pnl,
            equity=self.risk_mgr.equity,
            circuit_breaker_active=self.risk_mgr.circuit_breaker.tripped,
        )
        # Attach telemetry so the LLM can learn from execution quality
        cb = self.risk_mgr.circuit_breaker
        # Build recent outcomes string (e.g., "WWLLL") from feedback quality scorer
        _recent_out_str = ""
        if self.feedback.quality.overall_recent:
            _recent_out_str = "".join(
                "W" if r else "L" for r in self.feedback.quality.overall_recent[-5:]
            )
        # Daily win rate from feedback
        _daily_wr = None
        if len(self.feedback.quality.overall_recent) >= 3:
            _daily_wr = sum(self.feedback.quality.overall_recent) / len(self.feedback.quality.overall_recent)

        global_ctx.extra = {
            "win_rate": telem_snap.get("win_rate", 0),
            "total_trades": telem_snap.get("total_trades", 0),
            "avg_slippage": telem_snap.get("avg_slippage", 0),
            "avg_snapshot_age": telem_snap.get("avg_snapshot_age", 0),
            "stale_signals": telem_snap.get("stale_signals", 0),
            "circuit_breaker_triggers": telem_snap.get("circuit_breaker_triggers", 0),
            "throttle_blocks": telem_snap.get("throttle_blocks", 0),
            "ops_guard_status": self.ops_guard.format_status(),
            # Loss streak context for LLM awareness
            "consecutive_losses": cb.consecutive_losses,
            "recent_outcomes": _recent_out_str,
            "daily_win_rate": _daily_wr,
            # Portfolio correlation risk for LLM sizing adjustment
            "correlation_risk": self._compute_portfolio_correlation().get("risk_level", "low"),
            # Portfolio leverage for risk awareness
            "portfolio_leverage": self._compute_portfolio_leverage(),
            # Estimated daily funding cost (% of equity)
            "estimated_daily_funding_cost": self._compute_estimated_daily_funding(),
            # D5: Session performance for LLM context
            "session_performance": self.feedback.quality.get_session_performance(),
            # E2: Active regime transitions
            "regime_transitions": self.regime_detector.get_transition_summary(),
            # Global Brain: market-wide bias classification
            "global_bias": self._global_bias,
            "sector_activity": _gb_ctx.get("sectors_active", {}),
            "net_funding": _gb_ctx.get("net_funding", 0.0),
        }

        # ML Intelligence: inject model predictions into LLM context
        # so agents can see direction probability, win probability, and strategy weights
        if self.ml:
            try:
                ml_ctx = {}
                # Model training status
                ml_ctx["phase"] = "mature" if len(self.ml.outcomes) >= 50 else ("learning" if len(self.ml.outcomes) >= self.ml.min_samples else "cold_start")
                ml_ctx["trades_trained"] = len(self.ml.outcomes)

                # Direction prediction (1h) — the 78% accurate model
                dir_prob = self.ml.predict_direction(
                    price_change_1h_pct=global_ctx.btc_change_1h_pct,
                    price_change_24h_pct=global_ctx.btc_change_24h_pct,
                )
                if dir_prob is not None:
                    ml_ctx["direction_prob"] = round(dir_prob, 3)

                # Strategy win rates (ML-observed, rolling 20 trades)
                strat_wrs = {}
                for strat_name in ("regime_trend", "monte_carlo_zones", "multi_tier_quality", "confidence_scorer"):
                    wr = self.ml.get_strategy_win_rate(strat_name)
                    if wr is not None:
                        strat_wrs[strat_name] = round(wr, 2)
                if strat_wrs:
                    ml_ctx["strategy_win_rates"] = strat_wrs

                # ML-recommended strategy weights
                ml_weights = self.ml.get_strategy_weights()
                if ml_weights:
                    ml_ctx["strategy_weights"] = {k: round(v, 2) for k, v in ml_weights.items()}

                # Snapshot model stats
                if self.ml.snapshot_weights is not None:
                    filled = sum(1 for s in self.ml.snapshots if s.future_return_1h is not None)
                    ml_ctx["snapshot_model_samples"] = filled

                global_ctx.extra["ml_intelligence"] = ml_ctx
            except Exception as e:
                logger.debug(f"ML intelligence injection error: {e}")

        # Cross-symbol pattern signals: inject lead-lag relationships for LLM
        if self.cross_symbol_tracker:
            try:
                _cs_signals = self.cross_symbol_tracker.get_active_signals()
                if _cs_signals:
                    global_ctx.extra["cross_symbol_signals"] = _cs_signals[:5]  # Cap at 5
                _cs_patterns = self.cross_symbol_tracker.get_pattern_summary()
                if _cs_patterns:
                    global_ctx.extra["cross_symbol_patterns"] = _cs_patterns
            except Exception as e:
                logger.debug(f"Cross-symbol pattern injection error: {e}")

        # Inject Scout Agent preparation findings into LLM context
        # Scout results persist across ticks (refreshed every 10 ticks)
        scout = getattr(self, '_last_scout_result', None)
        scout_ts = getattr(self, '_last_scout_ts', 0)
        if scout and (time.time() - scout_ts) < 600:  # Fresh within 10 min
            scout_compact = {}
            wl = scout.get("watchlist", [])
            if wl:
                scout_compact["watchlist"] = [
                    {"sym": w.get("symbol"), "pri": w.get("priority"),
                     "setup": w.get("setup_forming"), "dir": w.get("direction"),
                     "thesis": w.get("pre_thesis", "")[:80]}
                    for w in wl[:5]
                ]
            rf = scout.get("regime_forecast")
            if rf:
                scout_compact["regime_forecast"] = rf
            ll = scout.get("lead_lag_alerts", [])
            if ll:
                scout_compact["lead_lag"] = ll[:3]
            cw = scout.get("correlation_warning")
            if cw:
                scout_compact["corr_warning"] = cw
            global_ctx.extra["scout_preparation"] = scout_compact

        # Inject deep memory edge map: which setups and strategies have proven edge
        try:
            from llm.deep_memory import get_deep_memory
            _dm = get_deep_memory()
            # Setup type win rates (most actionable for Trade Agent)
            _setup_wr = _dm.trade_dna.get_win_rate_by("setup_type")
            if _setup_wr:
                edge_map = {}
                for stype, stats in _setup_wr.items():
                    if stats["total"] >= 5:  # Only include statistically meaningful
                        wr = stats["wins"] / stats["total"] if stats["total"] else 0
                        edge_map[stype] = {
                            "wr": round(wr * 100),
                            "n": stats["total"],
                            "pnl": round(stats["pnl"], 2),
                        }
                if edge_map:
                    global_ctx.extra["setup_edge_map"] = edge_map
            # Strategy win rates by regime (helps Trade Agent weigh signals)
            _strat_wr = _dm.trade_dna.get_win_rate_by("strategy")
            if _strat_wr:
                strat_perf = {}
                for strat, stats in _strat_wr.items():
                    if stats["total"] >= 3:
                        wr = stats["wins"] / stats["total"] if stats["total"] else 0
                        strat_perf[strat] = {"wr": round(wr * 100), "n": stats["total"]}
                if strat_perf:
                    global_ctx.extra["strategy_performance"] = strat_perf
            # Confluence win rates by agreement count (how many strategies agreed)
            _combo_wr = _dm.trade_dna.get_strategy_effectiveness()
            if _combo_wr:
                confl_wr = {}
                for combo_key, stats in _combo_wr.items():
                    if combo_key == "unknown" or stats["total"] < 3:
                        continue
                    n_strats = len(combo_key.split(",")) if combo_key else 0
                    level = str(n_strats)
                    if level not in confl_wr:
                        confl_wr[level] = {"wins": 0, "total": 0, "pnl": 0.0}
                    confl_wr[level]["wins"] += stats["wins"]
                    confl_wr[level]["total"] += stats["total"]
                    confl_wr[level]["pnl"] += stats["pnl"]
                for level, agg in confl_wr.items():
                    wr = agg["wins"] / agg["total"] if agg["total"] else 0
                    confl_wr[level] = {
                        "wr": round(wr * 100),
                        "n": agg["total"],
                        "pnl": round(agg["pnl"], 2),
                    }
                if confl_wr:
                    global_ctx.extra["confluence_wr"] = confl_wr
        except Exception as e:
            logger.debug(f"Deep memory edge map injection error: {e}")

        # Strategy Signal Digest: full visibility into what ALL strategies are reading
        # This gives the LLM brain access to every strategy's output — not just passing ones
        try:
            all_digests = self.ensemble.get_all_signal_digests()
            if all_digests:
                # Compact for token efficiency: only include symbols with signals
                compact_digests = {}
                for sym, digest in all_digests.items():
                    if digest and digest.get("n_strategies", 0) > 0:
                        compact_digests[sym] = {
                            "n": digest["n_strategies"],
                            "side": digest["consensus"]["dominant_side"],
                            "agree": digest["consensus"]["agreement"],
                            "dissent": digest["consensus"]["dissent"],
                            "avg_conf": digest["consensus"]["avg_confidence"],
                            "pass_votes": digest["consensus"]["would_pass_votes"],
                            "readings": [
                                {
                                    "s": r["strategy"][:15],
                                    "sd": r["side"][0],  # B or S
                                    "c": r["confidence"],
                                    "w": r["weight"],
                                }
                                for r in digest.get("readings", [])
                            ],
                        }
                        if digest.get("chop_score", 0) > 0.3:
                            compact_digests[sym]["chop"] = digest["chop_score"]
                        # Include rejection reason so LLM knows why signals were blocked
                        rej = digest.get("last_rejection")
                        if rej:
                            compact_digests[sym]["rejected"] = {
                                "reason": rej["reason"],
                                "conf": rej["confidence"],
                                "side": rej["side"][0],  # B or S
                            }
                if compact_digests:
                    global_ctx.extra["signal_digest"] = compact_digests
        except Exception as e:
            logger.debug(f"Signal digest injection error: {e}")

        # Risk context
        risk_ctx = LLMRiskContext(
            daily_pnl=self.risk_mgr.circuit_breaker.daily_pnl,
            max_daily_loss=self.risk_mgr.equity * self.config.circuit_breaker_daily_loss_pct,
            equity=self.risk_mgr.equity,
            max_leverage=self.config.max_leverage,
            current_leverage=self._compute_portfolio_leverage(),
            volatility=max((m.volatility for m in markets), default=0.0),
            max_volatility=15.0,  # 15% ATR/price = extreme
            open_positions=self.pos_mgr.get_open_count(),
            max_positions=self.config.max_open_positions,
            circuit_breaker_active=self.risk_mgr.circuit_breaker.tripped,
            consecutive_losses=self.risk_mgr.circuit_breaker.consecutive_losses,
        )

        # Active positions
        active_positions = []
        open_pos = self.pos_mgr.get_open_positions()
        for sym, pos in open_pos.items():
            p = self._last_prices.get(sym, 0)
            if pos.side == "LONG":
                unrealized = (p - pos.entry) * pos.qty * pos.leverage if p else 0
            else:
                unrealized = (pos.entry - p) * pos.qty * pos.leverage if p else 0
            active_positions.append({
                "symbol": sym,
                "side": pos.side,
                "entry": pos.entry,
                "leverage": pos.leverage,
                "unrealized_pnl": round(unrealized, 2),
                "funding_rate": self._last_funding_rates.get(sym, 0.0),
            })

        # Portfolio Brain: cross-symbol portfolio reasoning for LLM
        try:
            _portfolio_snap = build_portfolio_snapshot(
                pos_mgr=self.pos_mgr,
                last_prices=self._last_prices,
                equity=self.risk_mgr.equity,
            )
            global_ctx.extra["portfolio_snapshot"] = _portfolio_snap
        except Exception as e:
            logger.debug(f"Portfolio brain snapshot error: {e}")

        # Self-Tuning Risk: inject current profile for LLM awareness
        try:
            _risk_profile = get_risk_profile_params()
            global_ctx.extra["risk_profile"] = _risk_profile.get("description", "normal")
            global_ctx.extra["dynamic_leverage_cap"] = get_dynamic_leverage_cap(
                self.config.max_leverage
            )
        except Exception as e:
            logger.debug(f"Risk profile context error: {e}")

        # Survival Pressure: inject accountability context into LLM prompt
        if _SURVIVAL_PRESSURE_AVAILABLE:
            try:
                global_ctx.extra["survival_status"] = get_survival_context_for_llm()
            except Exception as e:
                logger.debug(f"Survival context injection error: {e}")

        # Wave 3: Portfolio Risk Engine — inject vol forecasts and risk budget
        if self.portfolio_risk:
            try:
                _pr_budget = self.portfolio_risk.compute_risk_budget(
                    equity=self.risk_mgr.equity,
                    open_positions={s: {"side": p.side, "entry": p.entry,
                                       "qty": p.qty, "leverage": p.leverage}
                                   for s, p in self.pos_mgr.get_open_positions().items()},
                )
                global_ctx.extra["portfolio_risk_budget"] = {
                    "utilization": round(_pr_budget.utilization, 2),
                    "remaining_pct": round(_pr_budget.remaining_budget, 2),
                    "concentration_warning": _pr_budget.concentration_warning,
                }
            except Exception as e:
                logger.debug(f"Portfolio risk context error: {e}")

        # Wave 4: Meta-Learning — inject active insights for LLM awareness
        if self.meta_engine:
            try:
                _meta_insights = self.meta_engine.get_active_ideas()
                if _meta_insights:
                    global_ctx.extra["meta_learning_ideas"] = [
                        {"name": i.name, "trigger": i.trigger_condition, "status": i.status}
                        for i in _meta_insights[:3]
                    ]
            except Exception as e:
                logger.debug(f"Meta-learning context error: {e}")

        # Wave 4: Counterfactual — inject veto accuracy for LLM calibration
        if self.counterfactual:
            try:
                _cf_stats = self.counterfactual.get_summary_stats()
                if _cf_stats:
                    global_ctx.extra["counterfactual_stats"] = _cf_stats
            except Exception as e:
                logger.debug(f"Counterfactual context error: {e}")

        # LLM Self-Performance: inject rolling accuracy stats for self-calibration
        if _SELF_PERF_AVAILABLE:
            try:
                _sp_stats = get_llm_self_stats()
                if _sp_stats:
                    global_ctx.extra["llm_self_performance"] = _sp_stats
            except Exception as e:
                logger.debug(f"Self-performance stats injection error: {e}")

        # Learning Mode: inject current phase for LLM awareness
        if _LEARNING_MODE_AVAILABLE:
            try:
                if is_learning_mode_active():
                    _lm_phase = get_current_phase()
                    global_ctx.extra["learning_mode"] = {
                        "active": True,
                        "phase": _lm_phase.name,
                        "description": (
                            "ABSORB: Observing only, cannot veto" if _lm_phase == LearningPhase.ABSORB
                            else "APPRENTICE: Learning, limited influence" if _lm_phase == LearningPhase.APPRENTICE
                            else "ACTIVE: Full autonomy earned"
                        ),
                    }
                else:
                    global_ctx.extra["learning_mode"] = {"active": False, "phase": "GRADUATED"}
            except Exception as e:
                logger.debug(f"Learning mode context injection error: {e}")

        # Adaptive Risk: inject current risk multiplier for LLM sizing awareness
        if self.adaptive_risk:
            try:
                _ar_status = self.adaptive_risk.get_status()
                global_ctx.extra["adaptive_risk"] = {
                    "recent_streak": _ar_status.get("recent_streak", ""),
                    "recent_wr": round(_ar_status.get("recent_wr", 0), 2),
                }
            except Exception as e:
                logger.debug(f"Adaptive risk context injection error: {e}")

        # ── Soft-filter annotations: inject into LLM context ──
        if getattr(self.config, 'enable_soft_filters', False) or getattr(self.config, 'soft_filter_log_only', False):
            if hasattr(self, '_pending_annotations') and self._pending_annotations:
                try:
                    # Build compact filter assessment for each annotated signal
                    filter_assessments = []
                    near_misses = []
                    for sym, ann_sig in self._pending_annotations.items():
                        compact = ann_sig.to_compact_dict()
                        compact["sym"] = sym
                        if ann_sig.passed_all:
                            filter_assessments.append(compact)
                        elif not ann_sig.hard_rejected:
                            near_misses.append(compact)

                    if filter_assessments:
                        global_ctx.extra["filter_annotations"] = filter_assessments
                    if near_misses and getattr(self.config, 'soft_filter_near_miss', True):
                        global_ctx.extra["near_miss_signals"] = near_misses[:5]  # Cap at 5

                    # Clear pending annotations for next tick
                    self._pending_annotations = {}
                except Exception as e:
                    logger.debug(f"Filter annotation injection error: {e}")

        return markets, global_ctx, risk_ctx, active_positions

    def _run_llm_metabrain(self, trace_id: str = ""):
        """Run the LLM meta-brain via hybrid trigger system.

        Called when at least one trigger has fired. The trigger accumulator
        determines the highest-priority trigger and combines context from
        all pending events.

        In ADVISORY mode: call LLM, log decision, send to alerts, no influence.
        """
        # Get the best trigger, combined context, and all reason labels
        trigger_type, trigger_ctx, all_reasons = self._llm_triggers.get_best()
        trigger_label = TRIGGER_LABELS.get(trigger_type, "unknown") if trigger_type else "periodic"
        is_event = trigger_type is not None and trigger_type != LLMTrigger.PERIODIC

        logger.info(
            f"[{trace_id}][LLM] Trigger: {trigger_label} "
            f"reasons=[{', '.join(all_reasons)}] "
            f"(events: {self._llm_triggers.event_summary})"
        )

        # F3: Graceful degradation — skip LLM if API is degraded
        if self.degradation.should_skip_llm():
            logger.info(
                f"[{trace_id}][LLM] Skipping — LLM API degraded (ensemble-only mode)"
            )
            return

        markets, global_ctx, risk_ctx, positions = self._build_llm_context()

        if not markets:
            return

        result = get_trading_decision(
            markets=markets,
            global_context=global_ctx,
            risk_context=risk_ctx,
            active_positions=positions,
            mode=self.llm_mode,
            trigger_reason=trigger_label,
            trigger_context=trigger_ctx,
            event_triggered=is_event,
        )

        # F3: Track LLM API health for graceful degradation
        if result.reason and result.reason.startswith("api_error"):
            self.degradation.record_llm_error()
        else:
            self.degradation.record_llm_success()

        # Mark the trigger as called (for cooldown tracking)
        if trigger_type:
            self._llm_triggers.mark_called(trigger_type)

        # Log result
        if result.source == "none" and result.reason in ("throttled_no_cache", "off"):
            return  # Silent skip

        if result.source == "cache":
            return  # Already logged when cached

        if result.decision:
            d = result.decision
            logger.info(
                f"[{trace_id}][LLM] {d.action.upper()} conf={d.confidence:.2f} "
                f"regime={d.regime} size_mult={d.size_multiplier:.2f} "
                f"trigger={trigger_label} | {d.notes}"
            )

            # Feed LLM regime classification back to system-wide regime detector
            # This closes the loop: LLM Regime Agent -> system cache -> strategy filters
            if d.regime and d.regime != "unknown":
                try:
                    for sym in DEFAULT_SYMBOLS:
                        self.regime_detector.update(sym, d.regime)
                        self._tick_regime_cache[sym] = d.regime
                except Exception:
                    pass

            # In ADVISORY/VETO_ONLY mode: send to alerts for visibility
            if self.llm_mode in (LLMMode.ADVISORY, LLMMode.VETO_ONLY):
                reasons_str = ", ".join(all_reasons) if all_reasons else trigger_label
                orig_str = ""
                if result.original_action and result.original_action != d.action:
                    orig_str = f"\nOriginal: {result.original_action} (downgraded)"
                self.alerts.send_market_update(
                    f"[LLM META-BRAIN] {d.action.upper()} "
                    f"conf={d.confidence:.0%} regime={d.regime}\n"
                    f"Size mult: {d.size_multiplier:.2f}x\n"
                    f"Trigger: {trigger_label}\n"
                    f"All reasons: {reasons_str}"
                    f"{orig_str}\n"
                    f"{d.notes}"
                )
        elif result.reason:
            logger.info(f"[{trace_id}][LLM] No decision: {result.reason}")

        # Log API usage periodically
        if result.usage and result.usage.get("input_tokens", 0) > 0:
            from llm.client import get_usage_stats
            stats = get_usage_stats()
            logger.info(
                f"[LLM-COST] calls={stats['total_calls']} "
                f"tokens={stats['total_input_tokens']}in/{stats['total_output_tokens']}out "
                f"est=${stats['estimated_cost_usd']:.4f}"
            )

    def _run_scout_preparation(self, trace_id: str):
        """Run the Scout Agent during idle time for trade preparation.

        Gathers cross-market data and runs the Scout Agent (Haiku) to:
        - Build a watchlist of symbols approaching key levels
        - Pre-form directional theses for likely setups
        - Forecast regime transitions
        - Surface lead-lag opportunities
        - Calculate risk budget and correlation warnings

        Findings are written to the pipeline scratchpad for downstream
        agents to consume when a signal fires.
        """
        try:
            from llm.agents.coordinator import get_coordinator, is_multi_agent_enabled
            if not is_multi_agent_enabled():
                return
            coordinator = get_coordinator()
        except Exception:
            return

        # Build scout context: all symbols, prices, regimes, positions, lead-lag
        scout_data = {"symbols": {}}

        for symbol in DEFAULT_SYMBOLS:
            sym_data = {}
            # Current price and recent change
            price = self._last_prices.get(symbol)
            if price:
                sym_data["price"] = round(price, 4)
                change_1h = self._price_changes_1h.get(symbol, 0.0)
                sym_data["change_1h_pct"] = round(change_1h, 2)

            # Current regime (use tick cache)
            sym_data["regime"] = self._tick_regime_cache.get(symbol, "unknown")

            # Funding rate
            funding = self._last_funding_rates.get(symbol, 0.0)
            if funding:
                sym_data["funding_rate"] = round(funding, 6)

            scout_data["symbols"][symbol] = sym_data

        # Open positions summary
        open_pos = self.pos_mgr.get_open_positions()
        if open_pos:
            scout_data["open_positions"] = {}
            for sym, pos in open_pos.items():
                price = self._last_prices.get(sym, pos.entry)
                is_long = pos.side == "LONG"
                upnl_pct = ((price - pos.entry) / pos.entry * 100) if is_long else ((pos.entry - price) / pos.entry * 100)
                scout_data["open_positions"][sym] = {
                    "side": pos.side,
                    "entry": pos.entry,
                    "unrealized_pct": round(upnl_pct, 2),
                }

        # Lead-lag signals
        if hasattr(self, 'cross_symbol_tracker') and self.cross_symbol_tracker:
            try:
                lead_lag = self.cross_symbol_tracker.get_active_signals()
                if lead_lag:
                    scout_data["lead_lag_signals"] = lead_lag[:5]
            except Exception:
                pass

        # Portfolio correlation risk
        if hasattr(self, 'portfolio_risk') and self.portfolio_risk and open_pos:
            try:
                positions_map = {sym: pos.side.lower() for sym, pos in open_pos.items()}
                corr_matrix = self.portfolio_risk.compute_correlation_matrix()
                if corr_matrix:
                    cluster_risk = corr_matrix.get_cluster_risk(positions_map)
                    scout_data["portfolio_cluster_risk"] = round(cluster_risk, 3)
            except Exception:
                pass

        # Risk budget
        equity = self.risk_mgr.equity
        open_count = self.pos_mgr.get_open_count()
        max_positions = self.risk_mgr.max_open_positions
        scout_data["risk_budget"] = {
            "equity": round(equity, 2),
            "open_positions": open_count,
            "max_positions": max_positions,
            "slots_available": max(0, max_positions - open_count),
            "risk_per_trade": self.risk_mgr.risk_per_trade,
        }

        # Enrich Scout with deep memory pattern data
        if _DEEP_MEMORY_AVAILABLE:
            try:
                from llm.deep_memory import get_deep_memory
                dm = get_deep_memory()
                strategy_eff = dm.trade_dna.get_strategy_effectiveness()
                if strategy_eff:
                    # Compact: top 5 setups by sample size
                    top_setups = sorted(strategy_eff.items(), key=lambda x: x[1].get("total", 0), reverse=True)[:5]
                    scout_data["pattern_library"] = {
                        k: {"wr": round(v.get("win_rate", 0.5), 2), "n": v.get("total", 0)}
                        for k, v in top_setups
                    }
            except Exception:
                pass

        # Run scout and cache results for Trade Agent to consume
        result = coordinator.run_scout(scout_data)
        if result:
            self._last_scout_result = result
            self._last_scout_ts = time.time()
            logger.info(f"[{trace_id}][SCOUT] Preparation complete: "
                        f"{len(result.get('watchlist', []))} watchlist items")

    def _check_llm_reentry_clearance(self, symbol: str) -> bool:
        """Check if LLM/Scout data supports re-entering this symbol.

        Uses cached Scout Agent data (no API call) to assess whether
        market structure supports a new entry after a recent close.
        Falls back to a lightweight Haiku call if Scout data is stale.

        Returns:
            True if cleared to evaluate signals, False if LLM says wait.
        """
        # Check cached re-entry decisions (5 min cache per symbol)
        cache = getattr(self, '_reentry_cache', {})
        cached = cache.get(symbol)
        if cached and (time.time() - cached[1]) < 300:
            return cached[0]

        # Check Scout Agent data (free — no API call)
        scout = getattr(self, '_last_scout_result', None)
        scout_ts = getattr(self, '_last_scout_ts', 0)

        if scout and (time.time() - scout_ts) < 600:
            watchlist = scout.get("watchlist", [])
            for item in watchlist:
                if item.get("symbol") == symbol and item.get("priority") == "high":
                    # Scout flagged this symbol as high priority — clear to re-enter
                    logger.info(f"[{symbol}] LLM re-entry cleared: Scout HIGH priority "
                                f"({item.get('setup_forming', 'unknown')})")
                    self._cache_reentry(symbol, True)
                    return True

            # Scout ran but didn't flag this symbol as high priority
            # Check if regime forecast suggests waiting
            forecast = scout.get("regime_forecast", {})
            if forecast.get("direction") == "transitioning":
                logger.info(f"[{symbol}] LLM re-entry blocked: regime transitioning")
                self._cache_reentry(symbol, False)
                return False

        # No Scout data or Scout is stale — use lightweight heuristic
        # Check last trade outcome: after a loss on the same side, require
        # the signal to be on the opposite side (handled downstream in ensemble)
        # For now, allow re-entry — the ensemble + LLM pipeline will filter
        last_side = self._last_close_side.get(symbol)
        was_win = self._last_close_win.get(symbol, False)

        if was_win:
            # Won last trade — structure likely favorable, clear to re-enter
            self._cache_reentry(symbol, True)
            return True

        # Lost last trade — allow re-entry but log it. The multi-agent
        # pipeline (Trade Agent + Critic) will assess structure quality.
        logger.debug(f"[{symbol}] Post-loss re-entry: allowing signal evaluation "
                     f"(last side={last_side}, LLM pipeline will gate)")
        self._cache_reentry(symbol, True)
        return True

    def _cache_reentry(self, symbol: str, cleared: bool):
        """Cache a re-entry decision for 5 minutes."""
        if not hasattr(self, '_reentry_cache'):
            self._reentry_cache = {}
        self._reentry_cache[symbol] = (cleared, time.time())
