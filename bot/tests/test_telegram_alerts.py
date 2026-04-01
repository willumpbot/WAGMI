"""
Tests for Telegram alert bridge: critical event notifications.

Covers:
- TRADE_OPENED formatting and dispatch
- TRADE_CLOSED / TP_HIT / SL_HIT formatting
- Circuit breaker alerts
- Bot restart alerts
- Daily summary alerts
- Silent skip when no token/chat_id configured
- Telegram failures never propagate to caller
- TradeEventLogger callback integration
"""

import os
import sys
from unittest.mock import MagicMock, patch, ANY

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from alerts.telegram_alert_bridge import (
    TelegramAlertBridge,
    format_trade_opened,
    format_trade_closed,
    format_circuit_breaker,
    format_bot_restart,
    format_daily_summary,
    _fmt_price,
    _fmt_hold_time,
)


# ────────────────────────────────────────────────────────────────────
# Helper formatters
# ────────────────────────────────────────────────────────────────────

class TestFmtPrice:
    def test_large_price(self):
        assert _fmt_price(84500.0) == "84,500.00"

    def test_medium_price(self):
        assert _fmt_price(23.456) == "23.4560"

    def test_small_price(self):
        assert _fmt_price(0.005432) == "0.005432"

    def test_zero(self):
        assert _fmt_price(0) == "0"


class TestFmtHoldTime:
    def test_hours_and_minutes(self):
        assert _fmt_hold_time(4 * 3600 + 32 * 60) == "4h32m"

    def test_minutes_only(self):
        assert _fmt_hold_time(15 * 60) == "15m"

    def test_seconds(self):
        assert _fmt_hold_time(45) == "45s"

    def test_zero(self):
        assert _fmt_hold_time(0) == "0s"


# ────────────────────────────────────────────────────────────────────
# TRADE_OPENED formatting
# ────────────────────────────────────────────────────────────────────

class TestFormatTradeOpened:
    def test_basic_open(self):
        record = {
            "event": "TRADE_OPENED",
            "symbol": "BTC",
            "side": "SELL",
            "entry": 84500.0,
            "leverage": 3.2,
            "position_size": 45.0,
            "strategy": "regime_trend",
            "confidence": 82.0,
        }
        msg = format_trade_opened(record)
        assert "OPENED" in msg
        assert "BTC" in msg
        assert "SHORT" in msg
        assert "84,500.00" in msg
        assert "3.2x" in msg
        assert "$45.00" in msg
        assert "82%" in msg
        assert "regime_trend" in msg

    def test_long_side(self):
        record = {
            "event": "TRADE_OPENED",
            "symbol": "SOL",
            "side": "BUY",
            "entry": 135.50,
            "leverage": 5.0,
            "confidence": 75.0,
        }
        msg = format_trade_opened(record)
        assert "LONG" in msg
        assert "SOL" in msg

    def test_missing_fields_graceful(self):
        record = {"event": "TRADE_OPENED", "symbol": "ETH"}
        msg = format_trade_opened(record)
        assert "OPENED" in msg
        assert "ETH" in msg


# ────────────────────────────────────────────────────────────────────
# TRADE_CLOSED formatting
# ────────────────────────────────────────────────────────────────────

class TestFormatTradeClosed:
    def test_winning_close(self):
        record = {
            "event": "TRADE_CLOSED",
            "symbol": "BTC",
            "side": "SELL",
            "exit_price": 83200.0,
            "entry_price": 84500.0,
            "pnl": 15.40,
            "hold_time": 4 * 3600 + 32 * 60,
            "exit_reason": "TP2",
        }
        msg = format_trade_closed(record)
        assert "CLOSED" in msg
        assert "BTC" in msg
        assert "SHORT" in msg
        assert "+$15.40" in msg
        assert "4h32m" in msg
        assert "TP2 hit" in msg

    def test_losing_close(self):
        record = {
            "event": "SL_HIT",
            "symbol": "ETH",
            "side": "BUY",
            "exit_price": 3100.0,
            "entry_price": 3200.0,
            "pnl": -8.50,
            "hold_time": 900,
            "exit_reason": "SL",
        }
        msg = format_trade_closed(record)
        assert "CLOSED" in msg
        assert "ETH" in msg
        assert "LONG" in msg
        assert "-$8.50" in msg
        assert "stopped out" in msg

    def test_trailing_win(self):
        record = {
            "event": "TRADE_CLOSED",
            "symbol": "SOL",
            "side": "BUY",
            "exit_price": 140.0,
            "entry_price": 135.0,
            "pnl": 5.0,
            "hold_time": 7200,
            "exit_reason": "TRAILING_WIN",
        }
        msg = format_trade_closed(record)
        assert "trailing win" in msg

    def test_missing_exit_reason(self):
        record = {
            "event": "TRADE_CLOSED",
            "symbol": "BTC",
            "side": "SELL",
            "exit_price": 84000,
            "pnl": 2.0,
            "hold_time": 600,
        }
        msg = format_trade_closed(record)
        assert "closed" in msg


# ────────────────────────────────────────────────────────────────────
# Circuit breaker formatting
# ────────────────────────────────────────────────────────────────────

class TestFormatCircuitBreaker:
    def test_consecutive_losses(self):
        msg = format_circuit_breaker(
            reason="5 consecutive losses >= 5 limit",
            daily_pnl=-23.40,
            consecutive_losses=5,
            cooldown_minutes=60,
        )
        assert "CB TRIPPED" in msg
        assert "5 consecutive losses" in msg
        assert "Pausing 60min" in msg
        assert "-$23.40" in msg

    def test_daily_loss_limit(self):
        msg = format_circuit_breaker(
            reason="Daily loss 5.2% >= 5.0% limit",
            daily_pnl=-52.00,
            cooldown_minutes=120,
        )
        assert "CB TRIPPED" in msg
        assert "Daily loss" in msg
        assert "120min" in msg


# ────────────────────────────────────────────────────────────────────
# Bot restart formatting
# ────────────────────────────────────────────────────────────────────

class TestFormatBotRestart:
    def test_restart_with_positions(self):
        msg = format_bot_restart(
            downtime_seconds=720,
            positions_reconciled=2,
            phantoms_closed=0,
        )
        assert "BOT RESTARTED" in msg
        assert "12m" in msg
        assert "2 positions reconciled" in msg

    def test_restart_with_phantoms(self):
        msg = format_bot_restart(
            downtime_seconds=60,
            positions_reconciled=1,
            phantoms_closed=3,
        )
        assert "Phantom" in msg
        assert "3" in msg

    def test_restart_zero_downtime(self):
        msg = format_bot_restart(downtime_seconds=0, positions_reconciled=0)
        assert "BOT RESTARTED" in msg
        assert "0s" in msg


# ────────────────────────────────────────────────────────────────────
# Daily summary formatting
# ────────────────────────────────────────────────────────────────────

class TestFormatDailySummary:
    def test_full_summary(self):
        msg = format_daily_summary(
            total_trades=12,
            wins=7,
            net_pnl=18.50,
            best_trade={"symbol": "SOL", "pnl": 8.20},
            worst_trade={"symbol": "ETH", "pnl": -3.40},
            active_positions=2,
        )
        assert "DAILY SUMMARY" in msg
        assert "12 trades" in msg
        assert "58% WR" in msg
        assert "+$18.50" in msg
        assert "SOL" in msg
        assert "+$8.20" in msg
        assert "ETH" in msg
        assert "-$3.40" in msg
        assert "Active positions: 2" in msg

    def test_zero_trades(self):
        msg = format_daily_summary(total_trades=0, wins=0, net_pnl=0)
        assert "0 trades" in msg
        assert "0% WR" in msg

    def test_no_best_worst(self):
        msg = format_daily_summary(total_trades=3, wins=2, net_pnl=5.0)
        assert "DAILY SUMMARY" in msg
        assert "3 trades" in msg


# ────────────────────────────────────────────────────────────────────
# TelegramAlertBridge
# ────────────────────────────────────────────────────────────────────

class TestTelegramAlertBridge:
    def test_not_enabled_without_creds(self):
        bridge = TelegramAlertBridge()
        assert not bridge.enabled

    def test_enabled_with_creds(self):
        bridge = TelegramAlertBridge(
            telegram_token="test_token",
            telegram_chat_id="test_chat",
        )
        assert bridge.enabled

    @patch("alerts.telegram_alert_bridge.requests.post")
    def test_trade_opened_sends_telegram(self, mock_post):
        bridge = TelegramAlertBridge(
            telegram_token="tok123",
            telegram_chat_id="chat456",
        )
        record = {
            "event": "TRADE_OPENED",
            "symbol": "BTC",
            "side": "SELL",
            "entry": 84500.0,
            "leverage": 3.2,
            "position_size": 45.0,
            "strategy": "regime_trend",
            "confidence": 82.0,
        }
        msg = bridge.on_trade_event(record)
        assert msg is not None
        assert "OPENED" in msg
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "tok123" in call_kwargs[0][0] or "tok123" in str(call_kwargs)
        assert "chat456" in str(call_kwargs)

    @patch("alerts.telegram_alert_bridge.requests.post")
    def test_trade_closed_sends_telegram(self, mock_post):
        bridge = TelegramAlertBridge(
            telegram_token="tok",
            telegram_chat_id="chat",
        )
        record = {
            "event": "SL_HIT",
            "symbol": "ETH",
            "side": "BUY",
            "exit_price": 3100.0,
            "entry_price": 3200.0,
            "pnl": -8.50,
            "hold_time": 900,
            "exit_reason": "SL",
        }
        msg = bridge.on_trade_event(record)
        assert msg is not None
        assert "CLOSED" in msg
        mock_post.assert_called_once()

    def test_skips_non_alert_events(self):
        bridge = TelegramAlertBridge(
            telegram_token="tok",
            telegram_chat_id="chat",
        )
        record = {"event": "SIGNAL_GENERATED", "symbol": "BTC"}
        msg = bridge.on_trade_event(record)
        assert msg is None

    def test_skips_unknown_events(self):
        bridge = TelegramAlertBridge(
            telegram_token="tok",
            telegram_chat_id="chat",
        )
        record = {"event": "SOMETHING_ELSE", "symbol": "BTC"}
        msg = bridge.on_trade_event(record)
        assert msg is None

    @patch("alerts.telegram_alert_bridge.requests.post")
    def test_no_send_when_not_configured(self, mock_post):
        bridge = TelegramAlertBridge()
        record = {
            "event": "TRADE_OPENED",
            "symbol": "BTC",
            "side": "BUY",
            "entry": 84000,
            "leverage": 1.0,
        }
        msg = bridge.on_trade_event(record)
        # Message is formatted but not sent
        assert msg is not None
        mock_post.assert_not_called()

    @patch("alerts.telegram_alert_bridge.requests.post", side_effect=Exception("network error"))
    def test_send_failure_never_raises(self, mock_post):
        bridge = TelegramAlertBridge(
            telegram_token="tok",
            telegram_chat_id="chat",
        )
        record = {
            "event": "TRADE_OPENED",
            "symbol": "BTC",
            "side": "BUY",
            "entry": 84000,
            "leverage": 1.0,
        }
        # Should not raise
        msg = bridge.on_trade_event(record)
        assert msg is not None

    @patch("alerts.telegram_alert_bridge.requests.post")
    def test_circuit_breaker_alert(self, mock_post):
        bridge = TelegramAlertBridge(
            telegram_token="tok",
            telegram_chat_id="chat",
        )
        msg = bridge.send_circuit_breaker(
            reason="5 consecutive losses",
            daily_pnl=-23.40,
            consecutive_losses=5,
            cooldown_minutes=60,
        )
        assert msg is not None
        assert "CB TRIPPED" in msg
        mock_post.assert_called_once()

    @patch("alerts.telegram_alert_bridge.requests.post")
    def test_bot_restart_alert(self, mock_post):
        bridge = TelegramAlertBridge(
            telegram_token="tok",
            telegram_chat_id="chat",
        )
        msg = bridge.send_bot_restart(
            downtime_seconds=720,
            positions_reconciled=2,
        )
        assert msg is not None
        assert "BOT RESTARTED" in msg
        mock_post.assert_called_once()

    @patch("alerts.telegram_alert_bridge.requests.post")
    def test_daily_summary_alert(self, mock_post):
        bridge = TelegramAlertBridge(
            telegram_token="tok",
            telegram_chat_id="chat",
        )
        msg = bridge.send_daily_summary(
            total_trades=12,
            wins=7,
            net_pnl=18.50,
            best_trade={"symbol": "SOL", "pnl": 8.20},
            worst_trade={"symbol": "ETH", "pnl": -3.40},
            active_positions=2,
        )
        assert msg is not None
        assert "DAILY SUMMARY" in msg
        mock_post.assert_called_once()


# ────────────────────────────────────────────────────────────────────
# TradeEventLogger callback integration
# ────────────────────────────────────────────────────────────────────

class TestTradeEventLoggerCallback:
    def test_callback_invoked_on_log(self, tmp_path):
        from core.structured_logging import TradeEventLogger

        tel = TradeEventLogger(file_path=str(tmp_path / "events.jsonl"))
        captured = []
        tel.add_callback(lambda record: captured.append(record))

        tel.log("TRADE_OPENED", "BTC", side="BUY", entry=84000, leverage=2.0)
        assert len(captured) == 1
        assert captured[0]["event"] == "TRADE_OPENED"
        assert captured[0]["symbol"] == "BTC"

    def test_callback_error_does_not_block_logging(self, tmp_path):
        from core.structured_logging import TradeEventLogger

        tel = TradeEventLogger(file_path=str(tmp_path / "events.jsonl"))

        def bad_callback(record):
            raise RuntimeError("callback failed")

        tel.add_callback(bad_callback)

        # Should not raise, event still logged
        record = tel.log("TRADE_OPENED", "BTC", side="BUY", entry=84000)
        assert record["event"] == "TRADE_OPENED"

        # Verify file was written
        with open(str(tmp_path / "events.jsonl")) as f:
            lines = f.readlines()
        assert len(lines) == 1

    def test_multiple_callbacks(self, tmp_path):
        from core.structured_logging import TradeEventLogger

        tel = TradeEventLogger(file_path=str(tmp_path / "events.jsonl"))
        captured_a = []
        captured_b = []
        tel.add_callback(lambda r: captured_a.append(r))
        tel.add_callback(lambda r: captured_b.append(r))

        tel.log("SL_HIT", "ETH", side="SELL", pnl=-5.0)
        assert len(captured_a) == 1
        assert len(captured_b) == 1

    def test_bridge_receives_events_via_callback(self, tmp_path):
        from core.structured_logging import TradeEventLogger

        tel = TradeEventLogger(file_path=str(tmp_path / "events.jsonl"))
        bridge = TelegramAlertBridge()  # no creds = no actual send
        tel.add_callback(bridge.on_trade_event)

        # Log a trade open
        tel.log("TRADE_OPENED", "BTC", side="BUY", entry=84000, leverage=2.0, confidence=80)

        # Log a close — bridge should format it
        tel.log("SL_HIT", "ETH", side="SELL", exit_price=3100, pnl=-5.0, hold_time=300, exit_reason="SL")

        # Log a non-alert event — bridge should skip it
        tel.log("SIGNAL_GENERATED", "SOL", side="BUY", confidence=70)

        # No exceptions raised = success
