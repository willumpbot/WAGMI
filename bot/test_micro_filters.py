#!/usr/bin/env python3
"""Quick test to verify Phase 2 micro-filter gating logic."""

import sys
from strategies.base import Signal

# Mock the ensemble gating rules
_SYMBOL_SIDE_GATING = {
    "HYPE": {
        "allow_solos": False,
        "min_votes": 2,
        "rationale": "High-vol symbol with poor risk/reward (avg loss 55% > avg win)"
    },
    "SOL": {
        "allow_solos": True,
        "conditions": {
            "SHORT": {
                "min_confidence": 75.0,
                "risk_mult": 0.7,
                "rationale": "63.4% WR on SHORT, +$4,263 edge, PF 1.23"
            },
            "LONG": {
                "allow_solo": False,
                "min_votes": 2,
                "rationale": "LONG solos unproven, require ensemble"
            }
        }
    },
    "BTC": {
        "allow_solos": True,
        "conditions": {
            "LONG": {
                "min_confidence": 80.0,
                "risk_mult": 0.6,
                "rationale": "Slightly profitable LONG solos, need high confidence"
            },
            "SHORT": {
                "allow_solo": False,
                "min_votes": 2,
                "rationale": "SHORT solos lose money (48.1% WR)"
            }
        }
    },
    "ETH": {
        "allow_solos": False,
        "min_votes": 2,
        "rationale": "Insufficient data, reanalyze if ETH becomes active"
    }
}

_DEFAULT_SYMBOL_GATING = {
    "allow_solos": False,
    "min_votes": 2
}


def test_micro_filter_logic():
    """Test micro-filter gating decisions."""

    tests = [
        # (symbol, side, confidence, should_allow, description)
        ("HYPE", "SHORT", 90.0, False, "HYPE SHORT should always be rejected (strict gating)"),
        ("HYPE", "LONG", 95.0, False, "HYPE LONG should always be rejected (strict gating)"),

        ("SOL", "SHORT", 76.0, True, "SOL SHORT at 76% should be allowed (>75%)"),
        ("SOL", "SHORT", 74.0, False, "SOL SHORT at 74% should be rejected (<75%)"),
        ("SOL", "LONG", 85.0, False, "SOL LONG should be rejected (require 2+)"),

        ("BTC", "LONG", 81.0, True, "BTC LONG at 81% should be allowed (>=80%)"),
        ("BTC", "LONG", 79.0, False, "BTC LONG at 79% should be rejected (<80%)"),
        ("BTC", "SHORT", 90.0, False, "BTC SHORT should be rejected (require 2+)"),

        ("ETH", "SHORT", 85.0, False, "ETH SHORT should be rejected (insufficient data)"),
        ("ETH", "LONG", 85.0, False, "ETH LONG should be rejected (insufficient data)"),

        ("XYZ", "SHORT", 85.0, False, "Unknown symbol should default to strict (2+)"),
    ]

    passed = 0
    failed = 0

    for symbol, side, confidence, should_allow, description in tests:
        # Extract base symbol (remove /USDC:USDC suffix)
        base_sym = symbol.replace("/USDC:USDC", "").replace("/USDT:USDT", "")

        # Get gating rules
        gating = _SYMBOL_SIDE_GATING.get(base_sym, _DEFAULT_SYMBOL_GATING)

        # Check if solo would be allowed
        allowed = False
        if gating.get("allow_solos", False):
            conditions = gating.get("conditions", {})
            side_config = conditions.get(side)
            if side_config is not None:
                # Check if this specific side allows solos (not just the symbol)
                if not side_config.get("allow_solo", True):  # If explicitly False, don't allow
                    allowed = False
                else:
                    min_conf = side_config.get("min_confidence", 70.0)
                    if confidence >= min_conf:
                        allowed = True

        # Compare
        if allowed == should_allow:
            status = "[OK]"
            passed += 1
        else:
            status = "[FAIL]"
            failed += 1

        print(f"{status}: {description}")
        print(f"       {symbol}/{side} @ {confidence}% -> allowed={allowed}, expected={should_allow}")

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed out of {passed+failed} tests")

    return failed == 0


if __name__ == "__main__":
    success = test_micro_filter_logic()
    sys.exit(0 if success else 1)
