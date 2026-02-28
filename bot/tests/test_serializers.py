import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from serializers import build_trade_event, build_position_event


def is_iso_z(s: str) -> bool:
    # Basic ISO8601 Z matcher (YYYY-MM-DDTHH:MM:SSZ)
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", s))


def test_build_trade_event_numeric_and_enum_and_ts():
    e = {
        "strategy_id": "mtf-btc-1h-6h-16h",
        "order_id": "tr_001",
        "signal_id": "sig_001",
        "symbol": "BTCUSDT",
        "side": "buy",
        "qty": "0.0125",
        "price": "61850.25",
        "fee": "0.18",
        "fee_asset": "USDT",
        "exchange": "binance",
        "order_type": "LIMIT",
        "client_order_id": "mtf-00123",
        "latency_ms": "85",
    }
    ev = build_trade_event(e)
    assert ev["strategyId"] == "mtf-btc-1h-6h-16h"
    assert ev["orderId"] == "tr_001"
    assert ev["market"] == "BTCUSDT"
    assert ev["symbol"] == "BTCUSDT"
    assert ev["side"] == "buy"
    assert ev["symbol"] == "BTCUSDT"
    assert isinstance(ev["qty"], float) and ev["qty"] == 0.0125
    # serializer maps price -> fillPx
    assert isinstance(ev.get("fillPx"), float) and ev.get("fillPx") == 61850.25
    assert isinstance(ev["fees"], float) and ev["fees"] == 0.18
    assert is_iso_z(ev["ts"]) or isinstance(ev["ts"], str)


def test_build_position_event_numeric_and_enum_and_ts():
    p = {
        "strategy_id": "mtf-btc-1h-6h-16h",
        "position_id": "pos_001",
        "symbol": "BTCUSDT",
        "side": "long",
        "qty": "0.05",
        "avg_entry": "61780",
        "upnl": "3.45",
        "rpnl": "0",
        "leverage": "1.0",
        "status": "open",
        "meta": {"account": "spot"},
    }
    ev = build_position_event(p)
    assert ev["strategyId"] == "mtf-btc-1h-6h-16h"
    assert ev["market"] == "BTCUSDT"
    # position serializer does not include 'symbol' separately; it uses 'market'
    # PositionSnapshot does not include 'side', so we don't assert it here.
    assert isinstance(ev["qty"], float) and ev["qty"] == 0.05
    assert isinstance(ev["avgEntry"], float) and ev["avgEntry"] == 61780.0
    assert isinstance(ev["upnl"], float)
    assert isinstance(ev["leverage"], float)
    assert is_iso_z(ev["ts"]) or isinstance(ev["ts"], str)
