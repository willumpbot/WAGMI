"""
Symbol config loading tests.

Guards the one-at-a-time symbol expansion guardrail: a newly added symbol must
load with a complete, valid config across every place that resolves it
(DEFAULT_SYMBOLS, RISK_MULTIPLIERS tier, symbol_precision.json, fetcher routing,
and the conservative SymbolOverrides that bound the n<10 uncalibrated period).

Run: cd bot && pytest tests/test_symbol_config.py
     cd bot && pytest tests/ -k "symbol or config"
"""

import os
import sys
import json

# Ensure bot/ is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trading_config import (
    DEFAULT_SYMBOLS,
    RISK_MULTIPLIERS,
    DEFAULT_SYMBOL_OVERRIDES,
    SYMBOL_RISK_MULTIPLIERS,
    SymbolConfig,
    SymbolOverrides,
)

NEW_SYMBOL = "XRP"

# Symbol set grew to 5 with the XRP expansion (BTC/ETH/SOL/HYPE + XRP).
EXPECTED_SYMBOL_COUNT = 5


def _load_precision():
    path = os.path.join(os.path.dirname(__file__), "..", "config", "symbol_precision.json")
    with open(path, "r") as fh:
        return json.load(fh)


def test_symbol_list_length_increased():
    """Symbol list grew by exactly 1 (4 -> 5) — one-at-a-time expansion."""
    assert len(DEFAULT_SYMBOLS) == EXPECTED_SYMBOL_COUNT, (
        f"Expected {EXPECTED_SYMBOL_COUNT} symbols, got {len(DEFAULT_SYMBOLS)}: "
        f"{sorted(DEFAULT_SYMBOLS)}"
    )


def test_new_symbol_present_and_valid_config():
    """New symbol loads as a complete SymbolConfig with a valid risk tier."""
    assert NEW_SYMBOL in DEFAULT_SYMBOLS, f"{NEW_SYMBOL} missing from DEFAULT_SYMBOLS"
    cfg = DEFAULT_SYMBOLS[NEW_SYMBOL]
    assert isinstance(cfg, SymbolConfig)
    assert cfg.name == NEW_SYMBOL
    assert cfg.coinbase_pair == "XRP-USD"
    assert cfg.coingecko_id == "ripple"
    # Risk tier must be one of the defined tiers (maps to RISK_MULTIPLIERS).
    assert cfg.risk_tier in RISK_MULTIPLIERS, (
        f"{NEW_SYMBOL} tier {cfg.risk_tier!r} not in RISK_MULTIPLIERS"
    )


def test_new_symbol_precision_present():
    """symbol_precision.json must resolve the new symbol with a leverage cap."""
    precision = _load_precision()
    assert NEW_SYMBOL in precision, f"{NEW_SYMBOL} missing from symbol_precision.json"
    p = precision[NEW_SYMBOL]
    for key in ("price", "qty", "min_qty", "tick_size", "max_leverage"):
        assert key in p, f"{NEW_SYMBOL} precision missing {key}"
    assert p["max_leverage"] > 0


def test_new_symbol_leverage_cap_present_and_conservative():
    """SymbolOverrides bound the uncalibrated (n<10) period conservatively."""
    assert NEW_SYMBOL in DEFAULT_SYMBOL_OVERRIDES, (
        f"{NEW_SYMBOL} missing from DEFAULT_SYMBOL_OVERRIDES"
    )
    ov = DEFAULT_SYMBOL_OVERRIDES[NEW_SYMBOL]
    assert isinstance(ov, SymbolOverrides)
    # Leverage cap present and present-and-low: <= every calibrated peer override.
    assert ov.max_leverage is not None and ov.max_leverage > 0
    peer_caps = [
        o.max_leverage
        for s, o in DEFAULT_SYMBOL_OVERRIDES.items()
        if s != NEW_SYMBOL and o.max_leverage is not None
    ]
    assert ov.max_leverage <= min(peer_caps), (
        f"{NEW_SYMBOL} leverage cap {ov.max_leverage} should be the most "
        f"conservative; peers min={min(peer_caps)}"
    )
    # Per-trade risk override must be below the global default (0.10).
    assert ov.risk_per_trade is not None and 0 < ov.risk_per_trade <= 0.05
    assert ov.volatility_profile == "medium"


def test_new_symbol_leverage_cap_within_exchange_max():
    """Override leverage cap must not exceed the exchange precision max."""
    precision = _load_precision()
    ov = DEFAULT_SYMBOL_OVERRIDES[NEW_SYMBOL]
    assert ov.max_leverage <= precision[NEW_SYMBOL]["max_leverage"]


def test_new_symbol_risk_multiplier_conservative():
    """Optional SYMBOL_RISK_MULTIPLIERS keeps early sizing small (<= 1.0)."""
    assert NEW_SYMBOL in SYMBOL_RISK_MULTIPLIERS
    assert 0 < SYMBOL_RISK_MULTIPLIERS[NEW_SYMBOL] <= 1.0
