"""Tests for the cross-asset signal amplification module."""

import pytest
from datetime import datetime, timezone, timedelta

from execution.cross_asset_signals import (
    AmplificationSignal,
    CrossAssetAmplifier,
    LeadLagPair,
    DEFAULT_PAIRS,
)


def _utc(minutes_ago: float = 0) -> datetime:
    """Helper: return a UTC datetime *minutes_ago* before 'now'."""
    return datetime(2026, 3, 25, 12, 0, 0, tzinfo=timezone.utc) - timedelta(minutes=minutes_ago)


NOW = _utc(0)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def amp() -> CrossAssetAmplifier:
    """Fresh amplifier with default pairs."""
    return CrossAssetAmplifier()


# ------------------------------------------------------------------
# BTC breakout -> HYPE amplification
# ------------------------------------------------------------------

class TestBtcHypeAmplification:
    """BTC leads HYPE by 15-30 min."""

    def test_btc_breakout_generates_hype_long(self, amp: CrossAssetAmplifier):
        """When BTC rises >0.5% in 15 min and HYPE hasn't moved, amplify HYPE LONG."""
        # BTC rises from 60000 to 60600 (+1.0%) over 10 minutes
        amp.update_price("BTC", 60000.0, _utc(12))
        amp.update_price("BTC", 60300.0, _utc(6))
        amp.update_price("BTC", 60600.0, _utc(1))

        # HYPE is flat
        amp.update_price("HYPE", 25.0, _utc(12))
        amp.update_price("HYPE", 25.02, _utc(1))

        sig = amp.check_amplification("HYPE", "BUY", now=NOW)
        assert sig is not None
        assert isinstance(sig, AmplificationSignal)
        assert sig.leader == "BTC"
        assert sig.follower == "HYPE"
        assert sig.leader_move_pct > 0.5
        assert sig.confidence_boost > 0
        assert "LONG" in sig.rationale
        assert "BTC" in sig.rationale

    def test_btc_breakdown_generates_hype_short(self, amp: CrossAssetAmplifier):
        """When BTC drops >0.5% and HYPE hasn't moved, amplify HYPE SHORT."""
        amp.update_price("BTC", 60000.0, _utc(12))
        amp.update_price("BTC", 59600.0, _utc(1))  # -0.67%

        amp.update_price("HYPE", 25.0, _utc(12))
        amp.update_price("HYPE", 24.99, _utc(1))

        sig = amp.check_amplification("HYPE", "SELL", now=NOW)
        assert sig is not None
        assert sig.leader_move_pct < -0.5
        assert "SHORT" in sig.rationale

    def test_no_amplification_when_hype_already_moved(self, amp: CrossAssetAmplifier):
        """If HYPE already followed BTC, no amplification."""
        amp.update_price("BTC", 60000.0, _utc(12))
        amp.update_price("BTC", 60600.0, _utc(1))  # +1%

        # HYPE also moved up significantly
        amp.update_price("HYPE", 25.0, _utc(12))
        amp.update_price("HYPE", 25.20, _utc(1))  # +0.8% — already followed

        sig = amp.check_amplification("HYPE", "BUY", now=NOW)
        assert sig is None


# ------------------------------------------------------------------
# No amplification when leader hasn't moved
# ------------------------------------------------------------------

class TestNoAmplificationWhenLeaderFlat:

    def test_btc_flat_no_hype_amplification(self, amp: CrossAssetAmplifier):
        """No amplification when BTC is flat."""
        amp.update_price("BTC", 60000.0, _utc(12))
        amp.update_price("BTC", 60050.0, _utc(1))  # +0.08% — below threshold

        amp.update_price("HYPE", 25.0, _utc(12))
        amp.update_price("HYPE", 25.0, _utc(1))

        sig = amp.check_amplification("HYPE", "BUY", now=NOW)
        assert sig is None

    def test_no_data_no_amplification(self, amp: CrossAssetAmplifier):
        """No amplification when we have no price data at all."""
        sig = amp.check_amplification("HYPE", "BUY", now=NOW)
        assert sig is None

    def test_direction_mismatch_no_amplification(self, amp: CrossAssetAmplifier):
        """BTC up but asking for HYPE SHORT -> no amplification."""
        amp.update_price("BTC", 60000.0, _utc(12))
        amp.update_price("BTC", 60600.0, _utc(1))

        amp.update_price("HYPE", 25.0, _utc(12))
        amp.update_price("HYPE", 25.0, _utc(1))

        sig = amp.check_amplification("HYPE", "SELL", now=NOW)
        assert sig is None


# ------------------------------------------------------------------
# Stale data (>30 min old) is ignored
# ------------------------------------------------------------------

class TestStaleDataIgnored:

    def test_stale_leader_data_ignored(self, amp: CrossAssetAmplifier):
        """Leader data older than 30 min should not produce amplification."""
        amp.update_price("BTC", 60000.0, _utc(45))
        amp.update_price("BTC", 60600.0, _utc(35))  # big move, but 35 min ago

        amp.update_price("HYPE", 25.0, _utc(5))
        amp.update_price("HYPE", 25.0, _utc(1))

        sig = amp.check_amplification("HYPE", "BUY", now=NOW)
        assert sig is None

    def test_fresh_data_after_stale_works(self, amp: CrossAssetAmplifier):
        """After adding fresh data, amplification should work again."""
        # Old stale data
        amp.update_price("BTC", 60000.0, _utc(45))
        amp.update_price("BTC", 60600.0, _utc(35))

        # Fresh data with a breakout
        amp.update_price("BTC", 61000.0, _utc(10))
        amp.update_price("BTC", 61700.0, _utc(1))  # +1.15%

        amp.update_price("HYPE", 25.0, _utc(10))
        amp.update_price("HYPE", 25.01, _utc(1))

        sig = amp.check_amplification("HYPE", "BUY", now=NOW)
        assert sig is not None
        assert sig.leader_move_pct > 0.5


# ------------------------------------------------------------------
# All lead-lag pairs work
# ------------------------------------------------------------------

class TestAllPairs:

    def test_btc_sol_pair(self, amp: CrossAssetAmplifier):
        """BTC -> SOL pair: breakout amplifies SOL."""
        amp.update_price("BTC", 60000.0, _utc(12))
        amp.update_price("BTC", 60600.0, _utc(1))

        amp.update_price("SOL", 150.0, _utc(12))
        amp.update_price("SOL", 150.1, _utc(1))

        sig = amp.check_amplification("SOL", "BUY", now=NOW)
        assert sig is not None
        assert sig.leader == "BTC"
        assert sig.follower == "SOL"
        assert sig.lag_minutes == 10  # BTC->SOL min lag

    def test_sol_hype_pair(self, amp: CrossAssetAmplifier):
        """SOL -> HYPE pair: SOL breakout amplifies HYPE."""
        # Only SOL data (no BTC) so we isolate the SOL->HYPE pair
        amp.update_price("SOL", 150.0, _utc(12))
        amp.update_price("SOL", 151.5, _utc(1))  # +1.0%

        amp.update_price("HYPE", 25.0, _utc(12))
        amp.update_price("HYPE", 25.01, _utc(1))

        sig = amp.check_amplification("HYPE", "BUY", now=NOW)
        assert sig is not None
        # Could be BTC or SOL — here only SOL has data
        assert sig.leader == "SOL"
        assert sig.lag_minutes == 5  # SOL->HYPE min lag

    def test_hype_picks_best_leader(self, amp: CrossAssetAmplifier):
        """When both BTC and SOL are breaking out, HYPE picks the best signal."""
        # BTC big move
        amp.update_price("BTC", 60000.0, _utc(12))
        amp.update_price("BTC", 60900.0, _utc(1))  # +1.5%

        # SOL smaller move
        amp.update_price("SOL", 150.0, _utc(12))
        amp.update_price("SOL", 151.0, _utc(1))  # +0.67%

        # HYPE flat
        amp.update_price("HYPE", 25.0, _utc(12))
        amp.update_price("HYPE", 25.01, _utc(1))

        sig = amp.check_amplification("HYPE", "BUY", now=NOW)
        assert sig is not None
        # BTC's 1.5% * 0.70 corr = higher boost than SOL's 0.67% * 0.65 corr
        assert sig.leader == "BTC"

    def test_unknown_symbol_returns_none(self, amp: CrossAssetAmplifier):
        """Symbols not in any pair return None."""
        amp.update_price("BTC", 60000.0, _utc(12))
        amp.update_price("BTC", 60600.0, _utc(1))

        sig = amp.check_amplification("DOGE", "BUY", now=NOW)
        assert sig is None


# ------------------------------------------------------------------
# get_leader_momentum
# ------------------------------------------------------------------

class TestLeaderMomentum:

    def test_returns_leader_info(self, amp: CrossAssetAmplifier):
        """get_leader_momentum returns info about all leaders of a symbol."""
        amp.update_price("BTC", 60000.0, _utc(12))
        amp.update_price("BTC", 60600.0, _utc(1))
        amp.update_price("SOL", 150.0, _utc(12))
        amp.update_price("SOL", 150.5, _utc(1))

        mom = amp.get_leader_momentum("HYPE", now=NOW)
        assert "BTC" in mom
        assert "SOL" in mom
        assert mom["BTC"]["move_pct"] is not None
        assert mom["BTC"]["stale"] is False
        assert mom["BTC"]["correlation"] == 0.70

    def test_stale_leader_flagged(self, amp: CrossAssetAmplifier):
        """Stale leaders are flagged as stale."""
        amp.update_price("BTC", 60000.0, _utc(45))

        mom = amp.get_leader_momentum("HYPE", now=NOW)
        assert mom["BTC"]["stale"] is True

    def test_no_leaders(self, amp: CrossAssetAmplifier):
        """Symbol with no leaders returns empty dict."""
        mom = amp.get_leader_momentum("BTC", now=NOW)
        assert mom == {}


# ------------------------------------------------------------------
# Confidence boost capping
# ------------------------------------------------------------------

class TestConfidenceBoost:

    def test_boost_capped_at_20(self, amp: CrossAssetAmplifier):
        """Even with a huge leader move, confidence boost caps at 20."""
        amp.update_price("BTC", 60000.0, _utc(12))
        amp.update_price("BTC", 66000.0, _utc(1))  # +10% — massive move

        amp.update_price("SOL", 150.0, _utc(12))
        amp.update_price("SOL", 150.0, _utc(1))

        sig = amp.check_amplification("SOL", "BUY", now=NOW)
        assert sig is not None
        assert sig.confidence_boost <= 20.0

    def test_boost_scales_with_move_and_correlation(self, amp: CrossAssetAmplifier):
        """Larger moves and higher correlation produce bigger boosts."""
        # Test with BTC->SOL (0.80 corr) vs BTC->HYPE (0.70 corr)
        amp.update_price("BTC", 60000.0, _utc(12))
        amp.update_price("BTC", 60600.0, _utc(1))  # +1.0%

        amp.update_price("SOL", 150.0, _utc(12))
        amp.update_price("SOL", 150.0, _utc(1))
        amp.update_price("HYPE", 25.0, _utc(12))
        amp.update_price("HYPE", 25.0, _utc(1))

        sol_sig = amp.check_amplification("SOL", "BUY", now=NOW)
        hype_sig = amp.check_amplification("HYPE", "BUY", now=NOW)

        assert sol_sig is not None
        assert hype_sig is not None
        # SOL has higher correlation with BTC, so should get higher boost
        assert sol_sig.confidence_boost > hype_sig.confidence_boost
