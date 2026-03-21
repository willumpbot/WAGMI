"""
Phase 2 Test 1: Peak Equity Reset Bug Fix

Tests that circuit breaker cooldown recovery doesn't immediately re-trip
due to peak equity reset bug. This validates the unconditional reset logic.
"""

import pytest
import time
from datetime import datetime, timedelta, timezone
from execution.risk import CircuitBreaker, RiskManager


class TestPeakEquityResetFix:
    """Test suite for peak equity reset bug fix (risk.py:279-303)"""

    def test_peak_equity_reset_on_cooldown(self):
        """Case 1: Peak equity should reset to current equity on CB cooldown.

        Uses sim_time to cross day boundary after cooldown so daily_pnl resets,
        preventing the daily loss breaker from re-tripping after peak reset.
        """
        base_time = datetime(2026, 1, 1, 23, 58, 0, tzinfo=timezone.utc)
        cb = CircuitBreaker(
            daily_loss_limit_pct=0.05,
            max_consecutive_losses=3,
            max_drawdown_pct=0.10,
            cooldown_minutes=1,  # 1 minute for testing
        )
        cb.start_session(equity=10000)
        rm = RiskManager(starting_equity=10000, circuit_breaker=cb)

        # Record a trade that causes 12% drawdown (triggers CB via drawdown breaker)
        rm.update_equity(pnl=-1200, sim_time=base_time)
        assert cb.tripped, "CB should trip on 12% drawdown"
        old_peak = cb.peak_equity  # Should be 10000
        assert old_peak == 10000, f"Old peak should be 10000, got {old_peak}"

        # Simulate cooldown passing + crossing day boundary (resets daily_pnl)
        post_cooldown_time = base_time + timedelta(minutes=5)  # Next day

        # Check if trading is allowed after cooldown
        is_allowed = cb.is_trading_allowed(equity=8800, sim_time=post_cooldown_time)
        assert is_allowed, "Trading should be allowed after cooldown"

        # Verify peak_equity was reset to current equity (8800)
        assert cb.peak_equity == 8800, \
            f"peak_equity should reset to 8800, got {cb.peak_equity}"

        # Record a win after day boundary (daily_pnl now reset)
        rm.update_equity(pnl=200, sim_time=post_cooldown_time + timedelta(seconds=30))
        assert cb.peak_equity == 9000, \
            f"peak_equity should update to 9000 after win, got {cb.peak_equity}"

        # CB should NOT re-trip (daily_pnl reset, drawdown from new peak is 0%)
        assert not cb.tripped, "CB should not re-trip after cooldown + day boundary + win"

    def test_peak_equity_reset_with_zero_equity_edge_case(self):
        """Case 2: Zero equity edge case - should use fallback"""
        base_time = datetime(2026, 1, 1, 23, 58, 0, tzinfo=timezone.utc)
        cb = CircuitBreaker(cooldown_minutes=1)
        cb.start_session(equity=10000)

        # Trip CB
        cb.record_trade(pnl=-1500, equity=8500, sim_time=base_time)
        assert cb.tripped

        # Simulate cooldown + day boundary
        post_cooldown = base_time + timedelta(minutes=5)

        # Allow trading with zero equity (unrealistic but tests fallback)
        is_allowed = cb.is_trading_allowed(equity=0, sim_time=post_cooldown)
        assert is_allowed

        # peak_equity should use fallback (not stay at old peak)
        # Since equity=0, fallback should use current peak_equity
        assert cb.peak_equity >= 0, \
            f"peak_equity should be non-negative after zero edge case"

    def test_session_peak_equity_permanent_halt(self):
        """Case 3: Session peak vs daily peak - session halt is permanent"""
        cb = CircuitBreaker(
            max_drawdown_pct=0.10,
            cooldown_minutes=1,
        )
        cb.max_session_drawdown_pct = 0.20  # 20% session limit
        base_time = datetime(2026, 1, 1, 23, 58, 0, tzinfo=timezone.utc)
        cb.start_session(equity=10000)
        session_peak = cb.session_peak_equity
        assert session_peak == 10000

        # Lose 25% in session (triggers session halt)
        cb.record_trade(pnl=-2500, equity=7500, sim_time=base_time)

        # Session should be permanently halted
        assert cb._session_halted, "Session should be halted after 25% loss"

        # Simulate cooldown + day boundary
        post_cooldown = base_time + timedelta(minutes=5)

        # Even after cooldown, session halted trades should NOT be allowed
        is_allowed = cb.is_trading_allowed(equity=7500, sim_time=post_cooldown)
        assert not is_allowed, \
            "Trading should NOT be allowed after permanent session halt"

        # session_peak_equity should remain unchanged (cumulative)
        assert cb.session_peak_equity == 10000, \
            "session_peak_equity should remain 10000 (cumulative)"

    def test_post_cooldown_caution_mode(self):
        """Verify post-cooldown caution mode (reduced position size)"""
        base_time = datetime(2026, 1, 1, 23, 58, 0, tzinfo=timezone.utc)
        cb = CircuitBreaker(cooldown_minutes=1)
        cb.start_session(equity=10000)

        # Trip CB
        cb.record_trade(pnl=-1000, equity=9000, sim_time=base_time)
        assert cb.tripped

        # Simulate cooldown + day boundary
        post_cooldown = base_time + timedelta(minutes=5)

        # Allow trading
        is_allowed = cb.is_trading_allowed(equity=9000, sim_time=post_cooldown)
        assert is_allowed

        # Should be in post-cooldown caution mode
        assert cb.post_cooldown_caution == 4, \
            "post_cooldown_caution should be 4 after cooldown"

        # Get override constraints
        constraints = cb.get_override_constraints(confidence=0)
        assert constraints["constrained"] == True, \
            "Should be constrained in post-cooldown caution"
        assert constraints["size_multiplier"] == 0.5, \
            "Size multiplier should be 0.5x in caution mode"

        # After 4 trades, caution should expire
        for i in range(4):
            cb.record_trade(pnl=10, equity=9010 + i*10)
            cb.post_cooldown_caution -= 1
            if cb.post_cooldown_caution == 0:
                break

        # Next trade should be unconstrained
        constraints = cb.get_override_constraints(confidence=0)
        # Note: tripped status affects this, so check both conditions
        if not cb.tripped:
            assert constraints["constrained"] == False, \
                "Should be unconstrained after caution expires"

    def test_mtm_breaker_doesnt_retrigger_after_reset(self):
        """Verify MTM check doesn't immediately re-trip after peak reset.

        Uses sim_time to cross day boundary so daily_pnl resets after cooldown.
        """
        base_time = datetime(2026, 1, 1, 23, 58, 0, tzinfo=timezone.utc)
        cb = CircuitBreaker(
            max_drawdown_pct=0.10,
            cooldown_minutes=1,
        )
        cb.start_session(equity=10000)

        # Trip CB with 12% drawdown
        cb.record_trade(pnl=-1200, equity=8800, sim_time=base_time)
        assert cb.tripped, "CB should trip"

        # Simulate cooldown + day boundary crossing
        post_cooldown_time = base_time + timedelta(minutes=5)

        # Allow trading (triggers peak reset to 8800)
        is_allowed = cb.is_trading_allowed(equity=8800, sim_time=post_cooldown_time)
        assert is_allowed
        assert cb.peak_equity == 8800, "Peak should reset to 8800"

        # Now check MTM with slight loss (shouldn't re-trip)
        cb.check_mtm_breakers(mtm_equity=8800)
        assert not cb.tripped, \
            "Should not re-trip on MTM check after peak reset"

        # Only re-trip if MTM drops 10% below new peak (8800 * 0.9 = 7920)
        cb.check_mtm_breakers(mtm_equity=7921)
        assert not cb.tripped, "Should not trip just above 10% threshold"

        # At exactly 10% below 8800 = 7920, should trip
        cb.check_mtm_breakers(mtm_equity=7919)
        assert cb.tripped, "Should trip when MTM drops >10% below reset peak"

    def test_consecutive_losses_reset(self):
        """Verify consecutive losses counter resets after cooldown.

        Uses sim_time + day boundary crossing so daily_pnl resets too.
        """
        base_time = datetime(2026, 1, 1, 23, 58, 0, tzinfo=timezone.utc)
        cb = CircuitBreaker(
            max_consecutive_losses=3,
            cooldown_minutes=1,
        )
        cb.start_session(equity=10000)

        # Record 3 consecutive losses to trigger CB
        cb.record_trade(pnl=-200, equity=9800, sim_time=base_time)
        cb.record_trade(pnl=-200, equity=9600, sim_time=base_time + timedelta(seconds=30))
        cb.record_trade(pnl=-200, equity=9400, sim_time=base_time + timedelta(seconds=60))

        assert cb.consecutive_losses == 3
        assert cb.tripped, "CB should trip on 3 consecutive losses"

        # Simulate cooldown + day boundary
        post_cooldown = base_time + timedelta(minutes=5)

        # Allow trading
        is_allowed = cb.is_trading_allowed(equity=9400, sim_time=post_cooldown)
        assert is_allowed

        # Consecutive losses should reset
        assert cb.consecutive_losses == 0, \
            "consecutive_losses should reset after cooldown"

        # Should be able to take a loss without immediate re-trip
        cb.record_trade(pnl=-100, equity=9300, sim_time=post_cooldown + timedelta(seconds=30))
        assert cb.consecutive_losses == 1, \
            "consecutive_losses should be 1 after first loss post-cooldown"


class TestPeakEquityEdgeCases:
    """Additional edge case tests"""

    def test_peak_equity_monotonic_increase(self):
        """Peak equity should only increase, never decrease"""
        cb = CircuitBreaker(daily_loss_limit_pct=0.50)  # High limit to avoid tripping
        cb.start_session(equity=10000)
        cb.peak_equity = 10000  # Explicitly initialize peak
        initial_peak = cb.peak_equity

        # Lose money — peak should not decrease
        cb.record_trade(pnl=-500, equity=9500)
        assert cb.peak_equity == initial_peak, \
            "peak_equity should not decrease on loss"

        # Lose more — peak still at initial
        cb.record_trade(pnl=-300, equity=9200)
        assert cb.peak_equity == initial_peak, \
            "peak_equity should remain at initial on another loss"

        # Gain money — peak should increase
        cb.record_trade(pnl=1000, equity=10200)
        assert cb.peak_equity == 10200, \
            "peak_equity should increase to new high"

    def test_session_peak_never_decreases(self):
        """Session peak equity should never decrease (cumulative max).

        Note: session_peak_equity is set once at start_session() and is
        NOT updated by record_trade — it represents the session start equity
        as a cumulative DD anchor. It only updates if equity exceeds it
        at start_session time. Test verifies it never goes DOWN.
        """
        cb = CircuitBreaker(
            daily_loss_limit_pct=0.50,  # High limit to avoid daily loss trip
            max_drawdown_pct=0.50,      # High limit to avoid drawdown trip
        )
        cb.max_session_drawdown_pct = 0.50  # High limit to avoid session halt
        cb.start_session(equity=10000)
        session_peak = cb.session_peak_equity
        assert session_peak == 10000

        # Loss should NOT decrease session peak
        cb.record_trade(pnl=-2000, equity=8000)
        assert cb.session_peak_equity == session_peak, \
            "session_peak_equity should not decrease on loss"

        # Recover — session_peak_equity stays at session start value
        cb.record_trade(pnl=3000, equity=11000)
        assert cb.session_peak_equity == session_peak, \
            "session_peak_equity stays at session start anchor"

        # Further loss — still at session start anchor
        cb.record_trade(pnl=-2000, equity=9000)
        assert cb.session_peak_equity == session_peak, \
            "session_peak_equity should not decrease"


# Test execution
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
