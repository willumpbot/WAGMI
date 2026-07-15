"""RR_ZERO_FIX: predicted_ev / realized_rr / win must survive the ledger write,
and the additive schema migration must pad pre-existing rows."""
import csv
import os

from feedback.trade_ledger import LEDGER_COLUMNS, TradeLedger

NEW_COLS = ("predicted_ev", "realized_rr", "win")


def test_ev_calibration_columns_in_schema():
    for col in NEW_COLS:
        assert col in LEDGER_COLUMNS, f"{col} missing from LEDGER_COLUMNS"


def test_record_trade_preserves_ev_fields(tmp_path):
    led = TradeLedger(data_dir=str(tmp_path))
    led.record_trade({
        "symbol": "ETH", "side": "SHORT", "net_pnl": "10.0",
        "predicted_ev": "0.012", "realized_rr": "1.75", "win": "1",
    })
    with open(os.path.join(str(tmp_path), "trade_ledger.csv"), newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["predicted_ev"] == "0.012"
    assert rows[0]["realized_rr"] == "1.75"
    assert rows[0]["win"] == "1"


def test_migration_pads_old_rows(tmp_path):
    old_cols = [c for c in LEDGER_COLUMNS if c not in NEW_COLS]
    p = os.path.join(str(tmp_path), "trade_ledger.csv")
    with open(p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=old_cols)
        w.writeheader()
        row = {c: "" for c in old_cols}
        row.update({"trade_id": "abc123def456", "symbol": "BTC"})
        w.writerow(row)
    led = TradeLedger(data_dir=str(tmp_path))
    led.record_trade({"symbol": "ETH", "realized_rr": "2.0", "win": "1"})
    with open(p, newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["symbol"] == "BTC"
    assert rows[0]["realized_rr"] == ""  # old row padded, not corrupted
    assert rows[1]["realized_rr"] == "2.0"
    assert rows[1]["win"] == "1"
