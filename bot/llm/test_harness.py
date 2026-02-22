#!/usr/bin/env python3
"""
LLM Meta-Brain Test Harness

Builds a realistic fake snapshot and runs it through the full pipeline:
  snapshot -> serialize -> call LLM -> parse -> validate -> risk gate -> log

Modes:
  --live       Actually call Claude API (requires ANTHROPIC_API_KEY)
  --mock       Use a fake LLM response (no API key needed, tests validation + gating)
  --validate   Test validation with good and bad inputs

Usage:
  python -m llm.test_harness --mock
  python -m llm.test_harness --live
  python -m llm.test_harness --validate
"""

import argparse
import json
import os
import sys
import time

# Ensure bot/ is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from llm.decision_types import (
    StrategySignal,
    MarketSnapshot,
    GlobalContext,
    LLMDecision,
    StrategyWeights,
)
from llm.snapshot_builder import build_snapshot, snapshot_to_json
from llm.validation import validate_and_parse, parse_llm_response, is_valid_decision
from llm.risk_gating import gate_decision, RiskContext
from llm.memory_store import load_memory, get_memory_summary, apply_memory_update
from llm.autonomy import LLMMode, describe_mode


def build_fake_snapshot():
    """Build a realistic test snapshot with 5 symbols."""
    markets = [
        MarketSnapshot(
            symbol="BTC",
            price=97500.0,
            price_change_1h_pct=-0.3,
            price_change_24h_pct=1.2,
            volume_ratio=1.1,
            volatility=1.8,
            funding_rate=0.005,
            open_interest_change_pct=2.1,
            signals=[
                StrategySignal("BTC", "regime_trend", "long", 0.72, regime_score=0.6),
                StrategySignal("BTC", "monte_carlo_zones", "long", 0.68),
                StrategySignal("BTC", "confidence_scorer", "neutral", 0.45),
                StrategySignal("BTC", "multi_tier_quality", "long", 0.65, quality_score=0.7),
            ],
        ),
        MarketSnapshot(
            symbol="ETH",
            price=3250.0,
            price_change_1h_pct=-0.8,
            price_change_24h_pct=-1.5,
            volume_ratio=0.9,
            volatility=2.1,
            funding_rate=-0.002,
            signals=[
                StrategySignal("ETH", "regime_trend", "short", 0.61),
                StrategySignal("ETH", "monte_carlo_zones", "neutral", 0.40),
                StrategySignal("ETH", "confidence_scorer", "short", 0.58),
                StrategySignal("ETH", "multi_tier_quality", "short", 0.55),
            ],
        ),
        MarketSnapshot(
            symbol="SOL",
            price=185.0,
            price_change_1h_pct=1.5,
            price_change_24h_pct=4.2,
            volume_ratio=2.3,
            volatility=3.5,
            funding_rate=0.01,
            open_interest_change_pct=8.5,
            signals=[
                StrategySignal("SOL", "regime_trend", "long", 0.85, regime_score=0.9),
                StrategySignal("SOL", "monte_carlo_zones", "long", 0.78),
                StrategySignal("SOL", "confidence_scorer", "long", 0.71),
                StrategySignal("SOL", "multi_tier_quality", "long", 0.80, quality_score=0.85),
            ],
        ),
        MarketSnapshot(
            symbol="HYPE",
            price=28.5,
            price_change_1h_pct=0.2,
            price_change_24h_pct=0.5,
            volume_ratio=0.6,
            volatility=4.2,
            signals=[
                StrategySignal("HYPE", "regime_trend", "neutral", 0.40),
                StrategySignal("HYPE", "monte_carlo_zones", "long", 0.52),
            ],
        ),
        MarketSnapshot(
            symbol="DOGE",
            price=0.185,
            price_change_1h_pct=-2.1,
            price_change_24h_pct=-5.3,
            volume_ratio=3.5,
            volatility=6.8,
            signals=[
                StrategySignal("DOGE", "regime_trend", "short", 0.75),
                StrategySignal("DOGE", "confidence_scorer", "short", 0.68),
            ],
        ),
    ]

    global_context = GlobalContext(
        timestamp=int(time.time() * 1000),
        btc_price=97500.0,
        btc_change_1h_pct=-0.3,
        btc_change_24h_pct=1.2,
        eth_btc_ratio=0.0333,
        total_open_positions=1,
        daily_pnl=-45.0,
        equity=9955.0,
        circuit_breaker_active=False,
    )

    active_positions = [
        {"symbol": "SOL", "side": "LONG", "entry": 180.0, "unrealized_pnl": 25.0},
    ]

    return markets, global_context, active_positions


def build_fake_risk_context():
    return RiskContext(
        daily_pnl=-45.0,
        max_daily_loss=500.0,
        equity=9955.0,
        max_leverage=25.0,
        current_leverage=5.0,
        volatility=2.5,
        max_volatility=10.0,
        open_positions=1,
        max_positions=5,
        circuit_breaker_active=False,
        consecutive_losses=1,
    )


MOCK_LLM_RESPONSE = json.dumps({
    "action": "long",
    "confidence": 0.72,
    "regime": "trend",
    "strategy_weights": {
        "regime_trend": 0.85,
        "monte_carlo_zones": 0.70,
        "confidence_scorer": 0.50,
        "multi_tier_quality": 0.65,
        "funding_rate": 0.30,
        "open_interest": 0.60,
        "volume_momentum": 0.55,
        "cross_asset": 0.40,
    },
    "memory_update": "SOL showing strong trend with OI expansion, regime_trend reliable",
    "notes": "BTC stable, SOL leading with 3/4 strategies long. OI expanding 8.5%. Volume 2.3x confirms. Trend regime.",
})


def run_mock_test():
    """Test the full pipeline with a mock LLM response."""
    print("=" * 70)
    print("LLM META-BRAIN TEST (MOCK MODE)")
    print("=" * 70)

    # Build snapshot
    markets, global_ctx, positions = build_fake_snapshot()
    memory_summary = get_memory_summary()

    snapshot = build_snapshot(markets, global_ctx, memory_summary, positions)
    snapshot_json = snapshot_to_json(snapshot)

    print(f"\n--- SNAPSHOT ({len(snapshot_json)} chars) ---")
    print(json.dumps(json.loads(snapshot_json), indent=2)[:2000])

    # Parse mock response
    print(f"\n--- MOCK LLM RESPONSE ---")
    decision, err = validate_and_parse(MOCK_LLM_RESPONSE)

    if err:
        print(f"VALIDATION FAILED: {err}")
        return

    print(f"Action:     {decision.action}")
    print(f"Confidence: {decision.confidence}")
    print(f"Regime:     {decision.regime}")
    print(f"Notes:      {decision.notes}")
    print(f"Memory:     {decision.memory_update}")
    print(f"Weights:    {decision.strategy_weights.to_dict()}")

    # Risk gate
    risk = build_fake_risk_context()
    gated = gate_decision(decision, risk)

    print(f"\n--- RISK GATING ---")
    print(f"Allowed: {gated.allowed}")
    print(f"Reason:  {gated.reason}")

    # Memory update
    if decision.memory_update:
        apply_memory_update(decision.memory_update)
        print(f"\n--- MEMORY UPDATED ---")
        print(f"Summary: {get_memory_summary()}")

    print("\n" + "=" * 70)
    print("MOCK TEST PASSED")
    print("=" * 70)


def run_live_test():
    """Test with an actual Claude API call."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: Set ANTHROPIC_API_KEY to run live test")
        return

    print("=" * 70)
    print("LLM META-BRAIN TEST (LIVE MODE)")
    print("=" * 70)

    from llm.decision_engine import get_trading_decision

    markets, global_ctx, positions = build_fake_snapshot()
    risk = build_fake_risk_context()

    # Force call (override throttle by importing and resetting)
    import llm.snapshot_builder as sb
    sb._last_call_ts = 0

    result = get_trading_decision(
        markets=markets,
        global_context=global_ctx,
        risk_context=risk,
        active_positions=positions,
        mode=LLMMode.ADVISORY,
    )

    print(f"\n--- RESULT ---")
    print(f"Source:  {result.source}")
    print(f"Reason:  {result.reason}")
    print(f"Usage:   {result.usage}")

    if result.decision:
        d = result.decision
        print(f"Action:     {d.action}")
        print(f"Confidence: {d.confidence}")
        print(f"Regime:     {d.regime}")
        print(f"Notes:      {d.notes}")
        print(f"Memory:     {d.memory_update}")
        print(f"Weights:    {d.strategy_weights.to_dict()}")
    else:
        print("No decision returned")

    print(f"\n--- CUMULATIVE API USAGE ---")
    from llm.client import get_usage_stats
    stats = get_usage_stats()
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print("\n" + "=" * 70)
    print("LIVE TEST COMPLETE")
    print("=" * 70)


def run_validation_tests():
    """Test validation with various inputs."""
    print("=" * 70)
    print("VALIDATION TESTS")
    print("=" * 70)

    tests = [
        ("Valid decision", MOCK_LLM_RESPONSE, True),
        ("Empty string", "", False),
        ("Not JSON", "hello world", False),
        ("Missing action", '{"confidence":0.5,"regime":"trend","strategy_weights":{},"notes":"x"}', False),
        ("Bad action", '{"action":"yolo","confidence":0.5,"regime":"trend","strategy_weights":{"regime_trend":0.5,"monte_carlo_zones":0.5,"confidence_scorer":0.5,"multi_tier_quality":0.5},"notes":"x"}', False),
        ("Confidence > 1", '{"action":"long","confidence":1.5,"regime":"trend","strategy_weights":{"regime_trend":0.5},"notes":"x"}', False),
        ("Bad regime", '{"action":"long","confidence":0.7,"regime":"yolo","strategy_weights":{"regime_trend":0.5},"notes":"x"}', False),
        ("Markdown wrapped", '```json\n' + MOCK_LLM_RESPONSE + '\n```', True),
        ("Flat always valid", '{"action":"flat","confidence":0.1,"regime":"unknown","strategy_weights":{"regime_trend":0},"notes":"uncertain"}', True),
    ]

    passed = 0
    for name, input_text, expected_valid in tests:
        decision, err = validate_and_parse(input_text)
        actual_valid = decision is not None
        status = "PASS" if actual_valid == expected_valid else "FAIL"
        if status == "PASS":
            passed += 1
        print(f"  [{status}] {name}: expected_valid={expected_valid}, actual_valid={actual_valid}")
        if status == "FAIL":
            print(f"         Error: {err}")
            if decision:
                print(f"         Decision: {decision.action}")

    print(f"\n{passed}/{len(tests)} tests passed")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="LLM Meta-Brain Test Harness")
    parser.add_argument("--mock", action="store_true", help="Mock test (no API key needed)")
    parser.add_argument("--live", action="store_true", help="Live test (requires ANTHROPIC_API_KEY)")
    parser.add_argument("--validate", action="store_true", help="Run validation tests")
    args = parser.parse_args()

    # Load memory on startup
    load_memory()

    if args.validate:
        run_validation_tests()
    elif args.live:
        run_live_test()
    elif args.mock:
        run_mock_test()
    else:
        # Default: run mock + validation
        run_validation_tests()
        print()
        run_mock_test()


if __name__ == "__main__":
    main()
