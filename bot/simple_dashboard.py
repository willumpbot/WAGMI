"""
Simple Flask dashboard for monitoring paper trading.

Shows:
- Current positions + live P&L
- Recent signals + outcomes
- Equity curve
- Win rate, profit factor, etc.

Run: python simple_dashboard.py
Access: http://localhost:5000
"""

import logging
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional

import pandas as pd
from flask import Flask, jsonify, render_string
from flask_cors import CORS

logger = logging.getLogger("bot.dashboard")

# Create Flask app
app = Flask(__name__)
CORS(app)

# Configuration
TRADE_HISTORY_DIR = Path("paper_trades")
REFRESH_INTERVAL = 30  # seconds


class DashboardData:
    """Loads and serves dashboard data."""

    def __init__(self, trade_dir: str = "paper_trades"):
        self.trade_dir = Path(trade_dir)
        self.trades_df = None
        self.signals_df = None
        self._reload()

    def _reload(self):
        """Reload trade and signal data from CSVs."""
        # Load latest trades
        trades_files = sorted(list(self.trade_dir.glob("trades_*.csv")))
        if trades_files:
            try:
                self.trades_df = pd.read_csv(trades_files[-1])
                self.trades_df["timestamp"] = pd.to_datetime(self.trades_df["timestamp"])
            except Exception as e:
                logger.warning(f"Could not load trades: {e}")

        # Load latest signals
        signals_files = sorted(list(self.trade_dir.glob("signals_*.csv")))
        if signals_files:
            try:
                self.signals_df = pd.read_csv(signals_files[-1])
                self.signals_df["timestamp"] = pd.to_datetime(self.signals_df["timestamp"])
            except Exception as e:
                logger.warning(f"Could not load signals: {e}")

    def get_positions(self) -> List[Dict[str, Any]]:
        """Get current open positions."""
        if self.trades_df is None:
            return []

        # Get all OPEN positions that haven't been closed
        opens = self.trades_df[self.trades_df["action"] == "OPEN"].copy()
        if opens.empty:
            return []

        positions = []
        for symbol in opens["symbol"].unique():
            sym_opens = opens[opens["symbol"] == symbol]
            if sym_opens.empty:
                continue

            open_trade = sym_opens.iloc[0]

            # Check if this position has a close
            closes = self.trades_df[
                (self.trades_df["symbol"] == symbol)
                & (self.trades_df["timestamp"] > open_trade["timestamp"])
                & (self.trades_df["action"].isin(["TP1", "TP2", "SL"]))
            ]

            if not closes.empty:
                continue  # Position is closed

            positions.append({
                "symbol": symbol,
                "side": open_trade["side"],
                "entry": float(open_trade["price"]),
                "qty": float(open_trade["qty"]),
                "entry_time": open_trade["timestamp"].isoformat(),
                "leverage": float(open_trade["leverage"]),
            })

        return positions

    def get_recent_trades(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent closed trades."""
        if self.trades_df is None:
            return []

        closed = self.trades_df[self.trades_df["action"].isin(["TP1", "TP2", "SL", "TRAILING_STOP"])].copy()
        if closed.empty:
            return []

        trades = []
        for _, trade in closed.tail(limit).iterrows():
            trades.append({
                "symbol": trade["symbol"],
                "side": trade["side"],
                "action": trade["action"],
                "price": float(trade["price"]),
                "pnl": float(trade["pnl"]),
                "timestamp": trade["timestamp"].isoformat(),
            })

        return list(reversed(trades))  # Most recent first

    def get_performance_metrics(self) -> Dict[str, Any]:
        """Get overall performance stats."""
        if self.trades_df is None:
            return {}

        closed = self.trades_df[self.trades_df["action"].isin(["TP1", "TP2", "SL", "TRAILING_STOP"])]
        if closed.empty:
            return {
                "total_trades": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "profit_factor": 0,
            }

        total = len(closed)
        wins = len(closed[closed["pnl"] > 0])
        losses = len(closed[closed["pnl"] < 0])
        total_pnl = closed["pnl"].sum()
        total_fees = closed["fee"].sum()

        # Profit factor
        winning_pnl = closed[closed["pnl"] > 0]["pnl"].sum()
        losing_pnl = abs(closed[closed["pnl"] < 0]["pnl"].sum())
        profit_factor = winning_pnl / losing_pnl if losing_pnl > 0 else 0

        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "win_rate": wins / total * 100 if total > 0 else 0,
            "total_pnl": round(total_pnl, 2),
            "total_fees": round(total_fees, 2),
            "net_pnl": round(total_pnl - total_fees, 2),
            "profit_factor": round(profit_factor, 2),
            "avg_win": round(closed[closed["pnl"] > 0]["pnl"].mean(), 2) if wins > 0 else 0,
            "avg_loss": round(closed[closed["pnl"] < 0]["pnl"].mean(), 2) if losses > 0 else 0,
        }

    def get_by_symbol(self) -> Dict[str, Dict[str, Any]]:
        """Get stats by symbol."""
        if self.trades_df is None:
            return {}

        closed = self.trades_df[self.trades_df["action"].isin(["TP1", "TP2", "SL", "TRAILING_STOP"])]
        if closed.empty:
            return {}

        results = {}
        for symbol in closed["symbol"].unique():
            sym_trades = closed[closed["symbol"] == symbol]
            wins = len(sym_trades[sym_trades["pnl"] > 0])
            total = len(sym_trades)

            results[symbol] = {
                "trades": total,
                "wins": wins,
                "win_rate": wins / total * 100 if total > 0 else 0,
                "pnl": round(sym_trades["pnl"].sum(), 2),
            }

        return results


# Initialize data loader
data_loader = DashboardData(str(TRADE_HISTORY_DIR))


@app.route("/")
def index():
    """Serve dashboard HTML."""
    return render_string(DASHBOARD_HTML)


@app.route("/api/refresh", methods=["POST"])
def refresh():
    """Reload all data."""
    data_loader._reload()
    return jsonify({"status": "ok"})


@app.route("/api/positions")
def positions():
    """Get current positions."""
    return jsonify(data_loader.get_positions())


@app.route("/api/recent-trades")
def recent_trades():
    """Get recent trades."""
    return jsonify(data_loader.get_recent_trades())


@app.route("/api/metrics")
def metrics():
    """Get performance metrics."""
    return jsonify(data_loader.get_performance_metrics())


@app.route("/api/by-symbol")
def by_symbol():
    """Get stats by symbol."""
    return jsonify(data_loader.get_by_symbol())


# HTML Template
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>WAGMI Trading Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f0f0f;
            color: #fff;
            padding: 20px;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 { font-size: 28px; margin-bottom: 20px; }
        h2 { font-size: 18px; margin: 20px 0 10px 0; color: #888; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-bottom: 30px; }
        .card {
            background: #1a1a1a;
            border: 1px solid #333;
            padding: 20px;
            border-radius: 8px;
        }
        .metric { font-size: 32px; font-weight: bold; color: #00ff00; }
        .metric.negative { color: #ff4444; }
        .label { font-size: 12px; color: #888; text-transform: uppercase; margin-bottom: 5px; }
        .position { background: #1a1a1a; border-left: 3px solid #00ff00; padding: 15px; margin-bottom: 10px; border-radius: 4px; }
        .position.short { border-left-color: #ff4444; }
        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { text-align: left; padding: 10px; border-bottom: 1px solid #333; }
        th { font-weight: 600; color: #888; font-size: 12px; }
        tr:hover { background: #1a1a1a; }
        .win { color: #00ff00; }
        .loss { color: #ff4444; }
        .refresh { background: #00ff00; color: #000; border: none; padding: 8px 15px; border-radius: 4px; cursor: pointer; font-weight: 600; }
        .refresh:hover { background: #00dd00; }
        .status { margin-top: 10px; font-size: 12px; color: #666; }
    </style>
</head>
<body>
    <div class="container">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 30px;">
            <h1>📊 WAGMI Trading Dashboard</h1>
            <button class="refresh" onclick="refresh()">🔄 Refresh</button>
        </div>

        <h2>📈 Performance Metrics</h2>
        <div class="grid">
            <div class="card">
                <div class="label">Total Trades</div>
                <div class="metric" id="total-trades">0</div>
            </div>
            <div class="card">
                <div class="label">Win Rate</div>
                <div class="metric" id="win-rate">0%</div>
            </div>
            <div class="card">
                <div class="label">Net P&L</div>
                <div class="metric" id="net-pnl">$0.00</div>
            </div>
            <div class="card">
                <div class="label">Profit Factor</div>
                <div class="metric" id="profit-factor">0.00x</div>
            </div>
        </div>

        <h2>📍 Open Positions</h2>
        <div id="positions">
            <div class="card" style="color: #888;">No open positions</div>
        </div>

        <h2>💰 Recent Trades</h2>
        <div class="card">
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Price</th>
                        <th>Exit</th>
                        <th>P&L</th>
                        <th>Time</th>
                    </tr>
                </thead>
                <tbody id="recent-trades">
                    <tr><td colspan="6" style="color: #666;">Loading...</td></tr>
                </tbody>
            </table>
        </div>

        <h2>📊 By Symbol</h2>
        <div class="card">
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Trades</th>
                        <th>Win Rate</th>
                        <th>P&L</th>
                    </tr>
                </thead>
                <tbody id="by-symbol">
                    <tr><td colspan="4" style="color: #666;">Loading...</td></tr>
                </tbody>
            </table>
        </div>

        <div class="status">
            Last updated: <span id="last-update">never</span> | Auto-refresh every 30s
        </div>
    </div>

    <script>
        async function loadData() {
            try {
                // Load metrics
                const metricsResp = await fetch('/api/metrics');
                const metrics = await metricsResp.json();
                document.getElementById('total-trades').innerText = metrics.total_trades || 0;
                document.getElementById('win-rate').innerText = (metrics.win_rate || 0).toFixed(1) + '%';
                const pnlEl = document.getElementById('net-pnl');
                pnlEl.innerText = '$' + (metrics.net_pnl || 0).toFixed(2);
                pnlEl.className = 'metric' + (metrics.net_pnl < 0 ? ' negative' : '');
                document.getElementById('profit-factor').innerText = (metrics.profit_factor || 0).toFixed(2) + 'x';

                // Load positions
                const posResp = await fetch('/api/positions');
                const positions = await posResp.json();
                const posDiv = document.getElementById('positions');
                if (positions.length === 0) {
                    posDiv.innerHTML = '<div class="card" style="color: #888;">No open positions</div>';
                } else {
                    posDiv.innerHTML = positions.map(pos =>
                        `<div class="position ${pos.side === 'SHORT' ? 'short' : ''}">
                            <strong>${pos.symbol}</strong> ${pos.side} @ $${pos.entry.toFixed(2)} (${pos.leverage}x) | ${pos.qty.toFixed(4)} qty
                        </div>`
                    ).join('');
                }

                // Load recent trades
                const tradesResp = await fetch('/api/recent-trades');
                const trades = await tradesResp.json();
                const tbodyTrades = document.getElementById('recent-trades');
                if (trades.length === 0) {
                    tbodyTrades.innerHTML = '<tr><td colspan="6" style="color: #666;">No trades yet</td></tr>';
                } else {
                    tbodyTrades.innerHTML = trades.map(t => `
                        <tr>
                            <td><strong>${t.symbol}</strong></td>
                            <td>${t.side}</td>
                            <td>$${t.price.toFixed(2)}</td>
                            <td>${t.action}</td>
                            <td class="${t.pnl > 0 ? 'win' : 'loss'}">$${t.pnl.toFixed(2)}</td>
                            <td>${new Date(t.timestamp).toLocaleTimeString()}</td>
                        </tr>
                    `).join('');
                }

                // Load by symbol
                const symbolResp = await fetch('/api/by-symbol');
                const bySymbol = await symbolResp.json();
                const tbodySymbol = document.getElementById('by-symbol');
                if (Object.keys(bySymbol).length === 0) {
                    tbodySymbol.innerHTML = '<tr><td colspan="4" style="color: #666;">No trades yet</td></tr>';
                } else {
                    tbodySymbol.innerHTML = Object.entries(bySymbol).map(([sym, stats]) => `
                        <tr>
                            <td><strong>${sym}</strong></td>
                            <td>${stats.trades}</td>
                            <td>${stats.win_rate.toFixed(1)}%</td>
                            <td class="${stats.pnl > 0 ? 'win' : 'loss'}">$${stats.pnl.toFixed(2)}</td>
                        </tr>
                    `).join('');
                }

                document.getElementById('last-update').innerText = new Date().toLocaleTimeString();
            } catch (err) {
                console.error('Error loading data:', err);
            }
        }

        async function refresh() {
            await fetch('/api/refresh', { method: 'POST' });
            await loadData();
        }

        // Load on page load
        loadData();
        // Auto-refresh every 30 seconds
        setInterval(loadData, 30000);
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    print("🚀 Starting dashboard on http://localhost:5000")
    print("📊 View your trading performance in real-time!")
    app.run(debug=True, host="0.0.0.0", port=5000)
