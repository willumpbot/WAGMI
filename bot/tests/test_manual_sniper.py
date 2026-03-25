"""
Tests for the Manual Sniper Signal System.

Validates:
- Aggressive $100 account mode (high leverage, heavy sizing, strict filtering)
- Standard mode compatibility
- Signal filtering logic (confidence, consensus, regime gates)
- Tier classification (STANDARD / PREMIUM / SNIPER)
- Leverage calculation per tier
- Position sizing, margin, and P&L math
- Dedup and rate limiting
- Alert formatting
"""

import pytest
from dataclasses import dataclass, field
from typing import Dict, Any


# Minimal Signal stub for testing
@dataclass
class MockSignal:
    strategy: str = "regime_trend"
    symbol: str = "HYPE"
    side: str = "BUY"
    confidence: float = 82.0
    entry: float = 40.0
    sl: float = 39.0
    tp1: float = 42.0
    tp2: float = 44.0
    atr: float = 1.5
    metadata: Dict[str, Any] = field(default_factory=dict)
    signal_context: str = "Strong trend continuation"

    @property
    def is_valid(self):
        return True


class TestManualSniperConfig:
    """Test configuration defaults for aggressive mode."""

    def test_aggressive_defaults(self):
        from manual.config import ManualSniperConfig
        config = ManualSniperConfig()
        assert config.mode == "aggressive"
        assert config.equity == 100.0
        assert config.daily_target == 20.0
        assert config.max_leverage == 25.0
        assert config.max_daily_signals == 5

    def test_aggressive_risk_tiers(self):
        from manual.config import ManualSniperConfig
        config = ManualSniperConfig()
        assert config.risk_pct_standard == 0.05   # 5%
        assert config.risk_pct_premium == 0.08     # 8%
        assert config.risk_pct_sniper == 0.10      # 10%

    def test_aggressive_leverage_tiers(self):
        from manual.config import ManualSniperConfig
        config = ManualSniperConfig()
        assert config.leverage_tier_1 == 10.0
        assert config.leverage_tier_2 == 15.0
        assert config.leverage_tier_3 == 20.0
        assert config.leverage_tier_4 == 25.0
        assert config.leverage_tier_5 == 25.0


class TestManualSniperFilter:
    """Test signal filtering and classification."""

    def _make_filter(self, **overrides):
        from manual.sniper_filter import ManualSniperFilter
        from manual.config import ManualSniperConfig
        config = ManualSniperConfig()
        for k, v in overrides.items():
            setattr(config, k, v)
        f = ManualSniperFilter(config)
        f._running_equity = overrides.get('equity', 100.0)
        return f

    def _make_signal(self, **overrides) -> MockSignal:
        defaults = {
            "symbol": "HYPE",
            "side": "BUY",
            "confidence": 82.0,
            "entry": 40.0,
            "sl": 39.0,
            "tp1": 42.0,
            "tp2": 44.0,
            "atr": 1.5,
            "metadata": {
                "num_agree": 3,
                "strategies_agree": ["regime_trend", "monte_carlo_zones", "confidence_scorer"],
                "regime": "consolidation",
                "ev_per_dollar": 0.15,
            },
        }
        defaults.update(overrides)
        return MockSignal(**defaults)

    # ── Gate tests ──

    def test_hype_buy_passes_any_confidence(self):
        """HYPE BUY is a proven 85% WR setup — passes at any confidence."""
        filt = self._make_filter()
        sig = self._make_signal(confidence=55.0)  # Low confidence
        result = filt.evaluate(sig)
        assert result is not None  # Setup IS the edge, not confidence
        assert result.tier in ("PREMIUM", "SNIPER")

    def test_rejects_low_confidence_unproven_setup(self):
        """Non-proven setups still need confidence filter."""
        filt = self._make_filter()
        sig = self._make_signal(symbol="BTC", side="BUY", confidence=60.0,
                                 entry=70000, sl=69000, tp1=72000, tp2=74000,
                                 metadata={"num_agree": 1, "strategies_agree": ["x"], "regime": "trend"})
        assert filt.evaluate(sig) is None

    def test_rejects_low_consensus_unproven(self):
        """Non-proven setups need 2+ agree."""
        filt = self._make_filter()
        sig = self._make_signal(symbol="BTC", side="SELL", confidence=82.0,
                                 entry=70000, sl=71000, tp1=68000, tp2=66000,
                                 metadata={"num_agree": 1, "strategies_agree": ["x"], "regime": "trend"})
        assert filt.evaluate(sig) is None

    def test_rejects_low_rr(self):
        filt = self._make_filter()
        sig = self._make_signal(entry=40.0, sl=37.0, tp1=40.5)
        assert filt.evaluate(sig) is None

    def test_proven_setup_ignores_regime(self):
        """HYPE BUY passes even in panic — setup IS the edge."""
        filt = self._make_filter()
        sig = self._make_signal(
            confidence=80.0,
            metadata={"num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "panic"},
        )
        result = filt.evaluate(sig)
        assert result is not None

    def test_unproven_rejects_weak_regime(self):
        filt = self._make_filter()
        sig = self._make_signal(
            symbol="BTC", side="BUY", confidence=80.0,
            entry=70000, sl=69000, tp1=72000, tp2=74000,
            metadata={"num_agree": 2, "strategies_agree": ["a", "b"], "regime": "panic"},
        )
        assert filt.evaluate(sig) is None

    # ── Aggressive mode ──

    def test_aggressive_skips_unproven_standard(self):
        filt = self._make_filter(mode="aggressive")
        sig = self._make_signal(symbol="BTC", side="BUY", confidence=79.0,
                                 entry=70000, sl=69000, tp1=72000, tp2=74000,
                                 metadata={"num_agree": 2, "strategies_agree": ["a", "b"], "regime": "consolidation"})
        assert filt.evaluate(sig) is None  # Unproven + STANDARD = rejected

    def test_aggressive_passes_proven_setup(self):
        filt = self._make_filter(mode="aggressive")
        sig = self._make_signal(confidence=55.0, metadata={
            "num_agree": 1, "strategies_agree": ["a"], "regime": "trend",
        })
        result = filt.evaluate(sig)
        assert result is not None  # HYPE BUY passes at any confidence

    def test_proven_setup_always_premium_or_higher(self):
        """HYPE BUY is auto-promoted to at least PREMIUM regardless of confidence."""
        filt = self._make_filter(mode="standard")
        sig = self._make_signal(confidence=55.0, metadata={
            "num_agree": 1, "strategies_agree": ["a"], "regime": "consolidation",
        })
        result = filt.evaluate(sig)
        assert result is not None
        assert result.tier in ("PREMIUM", "SNIPER")

    # ── Tier classification ──

    def test_sniper_tier(self):
        filt = self._make_filter()
        sig = self._make_signal(confidence=87.0, metadata={
            "num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend",
        })
        result = filt.evaluate(sig)
        assert result is not None
        assert result.tier == "SNIPER"
        assert result.leverage >= 20.0  # High leverage for SNIPER (dynamic based on stop width)

    def test_hype_buy_82_is_sniper(self):
        """HYPE BUY at 82% with 3 agree = SNIPER (proven setup auto-promote)."""
        filt = self._make_filter()
        sig = self._make_signal(confidence=82.0, metadata={
            "num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend",
        })
        result = filt.evaluate(sig)
        assert result is not None
        assert result.tier == "SNIPER"

    # ── Sizing math for $100 account ──

    # ── Dynamic leverage tests ──

    def test_tight_stop_gets_higher_leverage(self):
        """Tighter stops should result in higher leverage."""
        filt = self._make_filter()
        # Tight stop: 0.5% (entry=40, sl=39.8)
        sig_tight = self._make_signal(confidence=87.0, entry=40.0, sl=39.8, tp1=42.0, tp2=44.0,
                                       metadata={"num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend"})
        result_tight = filt.evaluate(sig_tight)

        filt2 = self._make_filter()
        # Wide stop: 5% (entry=40, sl=38.0)
        sig_wide = self._make_signal(confidence=87.0, entry=40.0, sl=38.0, tp1=44.0, tp2=48.0,
                                      metadata={"num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend"})
        result_wide = filt2.evaluate(sig_wide)

        assert result_tight is not None
        assert result_wide is not None
        assert result_tight.leverage > result_wide.leverage, \
            f"Tight stop lev ({result_tight.leverage}) should be > wide stop lev ({result_wide.leverage})"

    def test_leverage_capped_at_max(self):
        """Even with tight stops and high confidence, leverage stays <= max."""
        filt = self._make_filter()
        sig = self._make_signal(confidence=95.0, entry=40.0, sl=39.9, tp1=42.0, tp2=44.0,
                                 metadata={"num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend"})
        result = filt.evaluate(sig)
        assert result is not None
        assert result.leverage <= 25.0

    def test_sniper_sizing_100_account(self):
        filt = self._make_filter(equity=100.0)
        sig = self._make_signal(confidence=87.0, metadata={
            "num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend",
        })
        result = filt.evaluate(sig)
        assert result is not None
        assert result.account_equity == 100.0
        # 10% risk on $100 = $10
        assert result.risk_amount == 10.0
        assert result.loss_amount == 10.0
        # Position size = $10 / (1/40) = $400
        assert result.position_size_usd == 400.0
        # Leverage is dynamic based on 2.5% stop width
        assert result.leverage >= 20.0
        # Margin = position / leverage
        assert result.margin_required <= result.account_equity

    def test_hype_buy_sizing_100_account(self):
        """HYPE BUY at 82%/3-agree is now SNIPER tier (auto-promoted)."""
        filt = self._make_filter(equity=100.0)
        sig = self._make_signal()  # 82% conf, 3 agree, HYPE BUY → SNIPER
        result = filt.evaluate(sig)
        assert result is not None
        assert result.tier == "SNIPER"
        # 10% risk on $100 = $10
        assert result.risk_amount == 10.0
        # Position size = $10 / (1/40) = $400
        assert result.position_size_usd == 400.0

    def test_margin_cannot_exceed_equity(self):
        """Even with high leverage, margin stays within account."""
        filt = self._make_filter(equity=50.0)  # Very small account
        sig = self._make_signal(confidence=87.0, metadata={
            "num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend",
        })
        result = filt.evaluate(sig)
        assert result is not None
        assert result.margin_required <= 50.0

    # ── Account growth tracking ──

    def test_account_after_win(self):
        filt = self._make_filter(equity=100.0)
        sig = self._make_signal()
        result = filt.evaluate(sig)
        assert result is not None
        assert result.account_after_win > result.account_equity
        assert result.account_after_loss < result.account_equity

    def test_growth_pct_positive(self):
        filt = self._make_filter(equity=100.0)
        sig = self._make_signal()
        result = filt.evaluate(sig)
        assert result is not None
        assert result.growth_pct > 0

    def test_compound_equity_update(self):
        filt = self._make_filter(equity=100.0)
        filt.update_equity(150.0)
        assert filt._running_equity == 150.0

    # ── Dedup ──

    def test_dedup_blocks_duplicate(self):
        filt = self._make_filter(dedup_window_s=600, min_alert_gap_s=0)
        sig = self._make_signal()
        assert filt.evaluate(sig) is not None
        assert filt.evaluate(sig) is None  # Same signal, blocked by dedup

    def test_dedup_allows_different_symbol(self):
        """Different symbols pass independently."""
        filt = self._make_filter(dedup_window_s=600, min_alert_gap_s=0, max_daily_signals=10)
        sig_hype = self._make_signal(confidence=87.0, metadata={
            "num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend",
        })
        sig_sol = self._make_signal(symbol="SOL", side="SELL", confidence=87.0,
                                     entry=90.0, sl=92.0, tp1=86.0, tp2=82.0,
                                     metadata={
            "num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend",
        })
        assert filt.evaluate(sig_hype) is not None
        assert filt.evaluate(sig_sol) is not None  # Different symbol, allowed

    # ── Daily limit ──

    def test_daily_signal_limit(self):
        filt = self._make_filter(max_daily_signals=2, dedup_window_s=0, min_alert_gap_s=0)
        # Use proven setups only (HYPE BUY, SOL SELL, and a high-conf discovery)
        sig1 = self._make_signal(symbol="HYPE", side="BUY", confidence=87.0, metadata={
            "num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend",
        })
        sig2 = self._make_signal(symbol="SOL", side="SELL", confidence=87.0,
                                  entry=90, sl=92, tp1=86, tp2=82,
                                  metadata={
            "num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend",
        })
        sig3 = self._make_signal(symbol="DOGE", side="BUY", confidence=92.0,
                                  entry=0.15, sl=0.14, tp1=0.17, tp2=0.19,
                                  metadata={
            "num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend",
        })
        assert filt.evaluate(sig1) is not None
        assert filt.evaluate(sig2) is not None
        assert filt.evaluate(sig3) is None  # Limit hit

    # ── SELL signals ──

    def test_sell_tp_direction(self):
        """SOL SELL (proven edge) has TPs below entry."""
        filt = self._make_filter()
        sig = self._make_signal(
            symbol="SOL", side="SELL", confidence=87.0,
            entry=90.0, sl=92.0, tp1=86.0, tp2=82.0,
            metadata={"num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend"},
        )
        result = filt.evaluate(sig)
        assert result is not None
        assert result.tp_scalp < result.entry
        assert result.tp_swing < result.entry

    # ── Disabled ──

    def test_disabled_returns_none(self):
        filt = self._make_filter(enabled=False)
        sig = self._make_signal()
        assert filt.evaluate(sig) is None


class TestManualSniperAlerts:
    """Test alert formatting for $100 account."""

    def _make_sniper(self, **overrides):
        from manual.sniper_filter import SniperSignal
        defaults = dict(
            symbol="HYPE", side="BUY", tier="SNIPER",
            entry=40.0, sl=39.0, tp_scalp=40.6, tp_swing=42.0,
            leverage=25.0, risk_pct=0.10, risk_amount=10.0,
            position_size_usd=400.0, qty=10.0,
            margin_required=16.0,
            pnl_scalp=15.0, pnl_swing=30.0, loss_amount=10.0,
            rr_scalp=1.5, rr_swing=3.0,
            account_equity=100.0, account_after_win=115.0,
            account_after_loss=90.0, growth_pct=15.0,
            confidence=88.0, num_agree=3,
            strategies=["regime_trend", "monte_carlo", "confidence_scorer"],
            regime="consolidation", ev_per_dollar=0.15,
            signal_context="Strong breakout setup",
            timestamp="2026-03-24T10:00:00Z",
            daily_target_pct=150.0, hold_target_hours="1-4h (scalp)",
        )
        defaults.update(overrides)
        return SniperSignal(**defaults)

    def test_alert_contains_key_info(self):
        from manual.alerts import format_sniper_alert
        sniper = self._make_sniper()
        msg = format_sniper_alert(sniper)
        assert "HYPE" in msg
        assert "LONG" in msg
        assert "SNIPER" in msg
        assert "25x" in msg
        assert "$100.00" in msg    # account equity
        assert "+$15.00" in msg    # win amount
        assert "-$10.00" in msg    # loss amount
        assert "15%" in msg        # growth pct

    def test_alert_shows_margin(self):
        from manual.alerts import format_sniper_alert
        sniper = self._make_sniper()
        msg = format_sniper_alert(sniper)
        assert "Margin" in msg
        assert "$16.00" in msg

    def test_short_signal(self):
        from manual.alerts import format_sniper_alert
        sniper = self._make_sniper(side="SELL", tier="PREMIUM")
        msg = format_sniper_alert(sniper)
        assert "SHORT" in msg
        assert "PREMIUM" in msg

    def test_daily_summary_shows_mode(self):
        from manual.alerts import format_daily_summary
        summary = {
            "date": "2026-03-24",
            "mode": "aggressive",
            "account_equity": 100.0,
            "signals_sent": 2,
            "max_signals": 5,
            "total_potential_scalp": 25.0,
            "total_potential_swing": 50.0,
            "total_risk": 20.0,
            "daily_target": 10.0,
            "target_coverage_scalp_pct": 250.0,
            "by_tier": {"SNIPER": 1, "PREMIUM": 1, "STANDARD": 0},
        }
        msg = format_daily_summary(summary)
        assert "AGGRESSIVE" in msg
        assert "$100.00" in msg


class TestAggressiveAccountMath:
    """Verify the math works for $100 → $1000+ compounding."""

    def test_sniper_ev_positive(self):
        """At 85% WR, EV must be positive."""
        from manual.sniper_filter import ManualSniperFilter
        from manual.config import ManualSniperConfig
        config = ManualSniperConfig()
        filt = ManualSniperFilter(config)
        filt._running_equity = 100.0

        sig = MockSignal(
            symbol="HYPE", side="BUY", confidence=87.0,
            entry=40.0, sl=39.0, tp1=42.0, tp2=44.0, atr=1.5,
            metadata={
                "num_agree": 3,
                "strategies_agree": ["a", "b", "c"],
                "regime": "consolidation",
                "ev_per_dollar": 0.15,
            },
        )
        result = filt.evaluate(sig)
        assert result is not None

        # EV at 85% WR
        wr = 0.85
        ev = wr * result.pnl_scalp - (1 - wr) * result.loss_amount
        assert ev > 0, f"EV should be positive: {ev}"

        # Growth should be meaningful on $100
        assert result.growth_pct >= 10, f"Growth should be >=10% on SNIPER: {result.growth_pct}%"

    def test_compounding_projection(self):
        """Simulate 10 trades at 85% WR to verify compounding."""
        from manual.sniper_filter import ManualSniperFilter
        from manual.config import ManualSniperConfig
        import random

        config = ManualSniperConfig()
        filt = ManualSniperFilter(config)
        filt._running_equity = 100.0

        # Simulate: 85% WR, SNIPER signals only
        equity = 100.0
        random.seed(42)
        wins = 0
        losses = 0

        for i in range(10):
            # Reset dedup/cooldown for simulation
            filt._dedup_cache = {}
            filt._last_alert_ts = {}
            filt._daily_signals = []
            filt._running_equity = equity

            sig = MockSignal(
                symbol="HYPE", side="BUY", confidence=87.0,
                entry=40.0, sl=39.0, tp1=42.0, tp2=44.0, atr=1.5,
                metadata={
                    "num_agree": 3,
                    "strategies_agree": ["a", "b", "c"],
                    "regime": "consolidation",
                },
            )
            result = filt.evaluate(sig)
            assert result is not None

            # 85% WR
            if random.random() < 0.85:
                equity += result.pnl_scalp
                wins += 1
            else:
                equity -= result.loss_amount
                losses += 1

        # After 10 trades at ~85% WR, equity should have grown
        assert equity > 100, f"Should have grown from $100: ${equity:.2f} (W:{wins} L:{losses})"

    def test_rr_always_positive(self):
        """R:R must always be >= 1.0 for all passing signals."""
        from manual.sniper_filter import ManualSniperFilter
        from manual.config import ManualSniperConfig
        filt = ManualSniperFilter(ManualSniperConfig())
        filt._running_equity = 100.0

        sig = MockSignal(
            symbol="HYPE", side="BUY", confidence=87.0,
            entry=40.0, sl=39.0, tp1=42.0, tp2=44.0, atr=1.5,
            metadata={"num_agree": 3, "strategies_agree": ["a", "b", "c"], "regime": "trend"},
        )
        result = filt.evaluate(sig)
        assert result is not None
        assert result.rr_scalp >= 1.0
        assert result.rr_swing >= result.rr_scalp


class TestDipBuyDetection:
    """Test dip-buy signal detection and tier boosting."""

    def _make_filter(self, **overrides):
        from manual.sniper_filter import ManualSniperFilter
        from manual.config import ManualSniperConfig
        config = ManualSniperConfig()
        for k, v in overrides.items():
            setattr(config, k, v)
        f = ManualSniperFilter(config)
        f._running_equity = overrides.get('equity', 100.0)
        return f

    def _make_signal(self, **overrides) -> MockSignal:
        defaults = {
            "symbol": "HYPE",
            "side": "BUY",
            "confidence": 82.0,
            "entry": 40.0,
            "sl": 39.0,
            "tp1": 42.0,
            "tp2": 44.0,
            "atr": 1.5,
            "metadata": {
                "num_agree": 3,
                "strategies_agree": ["regime_trend", "monte_carlo_zones", "confidence_scorer"],
                "regime": "consolidation",
                "ev_per_dollar": 0.15,
                "chop_score": 0.1,
            },
        }
        defaults.update(overrides)
        return MockSignal(**defaults)

    def test_dip_buy_detected_via_regime_low_chop(self):
        """HYPE BUY in consolidation with low chop = dip-buy."""
        filt = self._make_filter()
        sig = self._make_signal(metadata={
            "num_agree": 3, "strategies_agree": ["a", "b", "c"],
            "regime": "consolidation", "chop_score": 0.1,
        })
        result = filt.evaluate(sig)
        assert result is not None
        assert result.is_dip_buy is True

    def test_dip_buy_detected_via_explicit_metadata(self):
        """Explicit dip_detected=True in metadata triggers dip-buy."""
        filt = self._make_filter()
        sig = self._make_signal(metadata={
            "num_agree": 3, "strategies_agree": ["a", "b", "c"],
            "regime": "trend", "dip_detected": True,
        })
        result = filt.evaluate(sig)
        assert result is not None
        assert result.is_dip_buy is True

    def test_dip_buy_detected_via_dip_depth(self):
        """dip_depth_pct >= 2.0 triggers dip-buy."""
        filt = self._make_filter()
        sig = self._make_signal(metadata={
            "num_agree": 3, "strategies_agree": ["a", "b", "c"],
            "regime": "trend", "dip_depth_pct": 3.5,
        })
        result = filt.evaluate(sig)
        assert result is not None
        assert result.is_dip_buy is True

    def test_dip_buy_detected_via_price_vs_high(self):
        """price_vs_high_pct <= -2.0 triggers dip-buy."""
        filt = self._make_filter()
        sig = self._make_signal(metadata={
            "num_agree": 3, "strategies_agree": ["a", "b", "c"],
            "regime": "trend", "price_vs_high_pct": -4.0,
        })
        result = filt.evaluate(sig)
        assert result is not None
        assert result.is_dip_buy is True

    def test_no_dip_buy_in_trending_high_chop(self):
        """Trending regime with moderate chop should NOT be dip-buy."""
        filt = self._make_filter()
        # chop=0.35 passes HYPE BUY max_chop=0.4 but is high enough to not trigger dip-buy
        sig = self._make_signal(metadata={
            "num_agree": 3, "strategies_agree": ["a", "b", "c"],
            "regime": "trend", "chop_score": 0.35,
        })
        result = filt.evaluate(sig)
        assert result is not None
        assert result.is_dip_buy is False

    def test_no_dip_buy_on_sell_signals(self):
        """SELL signals should never be marked as dip-buy."""
        filt = self._make_filter()
        sig = self._make_signal(
            symbol="SOL", side="SELL", confidence=87.0,
            entry=90.0, sl=92.0, tp1=86.0, tp2=82.0,
            metadata={
                "num_agree": 3, "strategies_agree": ["a", "b", "c"],
                "regime": "consolidation", "chop_score": 0.1,
            },
        )
        result = filt.evaluate(sig)
        assert result is not None
        assert result.is_dip_buy is False

    def test_dip_buy_boosts_proven_premium_to_sniper(self):
        """Dip-buy on a proven PREMIUM setup should boost to SNIPER."""
        filt = self._make_filter()
        # HYPE BUY with low confidence (would normally be PREMIUM)
        sig = self._make_signal(confidence=60.0, metadata={
            "num_agree": 1, "strategies_agree": ["a"],
            "regime": "consolidation", "chop_score": 0.1,
        })
        result = filt.evaluate(sig)
        assert result is not None
        assert result.is_dip_buy is True
        assert result.tier == "SNIPER"  # Boosted from PREMIUM

    def test_dip_buy_does_not_boost_unproven_setups(self):
        """Unproven setups should NOT get tier boost from dip-buy."""
        filt = self._make_filter(mode="standard")
        sig = self._make_signal(
            symbol="DOGE", side="BUY", confidence=87.0,
            entry=0.15, sl=0.14, tp1=0.17, tp2=0.19,
            metadata={
                "num_agree": 3, "strategies_agree": ["a", "b", "c"],
                "regime": "consolidation", "chop_score": 0.1,
            },
        )
        result = filt.evaluate(sig)
        assert result is not None
        # Dip-buy detected but no tier boost (unproven setup)
        assert result.is_dip_buy is True
        assert result.tier == "SNIPER"  # Already SNIPER from confidence/agree, not from boost
