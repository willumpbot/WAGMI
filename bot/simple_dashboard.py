"""
Web dashboard for monitoring paper trading — powered by SQLite.

Shows:
- Performance metrics (equity, win rate, PnL, profit factor)
- Open positions with live P&L
- Equity curve chart
- Recent trades
- Signal performance scoring
- Strategy & symbol breakdowns
- Health events

Run: cd bot && python simple_dashboard.py
Access: http://localhost:5000
"""

import logging
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any

logger = logging.getLogger("bot.dashboard")

# Ensure bot/ is in path
sys.path.insert(0, str(Path(__file__).parent))


def _create_app():
    """Create Flask app with all routes."""
    from flask import Flask, jsonify, render_string, request
    try:
        from flask_cors import CORS
    except ImportError:
        CORS = None

    app = Flask(__name__)
    if CORS:
        CORS(app)

    # Initialize database
    from data.db import (
        init_db, get_dashboard_data, get_daily_summary,
        get_recent_trades, get_equity_curve, get_signal_performance,
        get_health_events, get_performance_history, get_signals_today,
    )
    init_db()

    @app.route("/")
    def index():
        return render_string(DASHBOARD_HTML)

    @app.route("/api/dashboard")
    def dashboard_data():
        """All-in-one dashboard endpoint."""
        return jsonify(get_dashboard_data())

    @app.route("/api/metrics")
    def metrics():
        return jsonify(get_daily_summary())

    @app.route("/api/recent-trades")
    def recent_trades():
        limit = request.args.get("limit", 20, type=int)
        return jsonify(get_recent_trades(limit))

    @app.route("/api/equity-curve")
    def equity_curve():
        days = request.args.get("days", 30, type=int)
        return jsonify(get_equity_curve(days))

    @app.route("/api/signal-performance")
    def signal_performance():
        days = request.args.get("days", 7, type=int)
        symbol = request.args.get("symbol", "")
        strategy = request.args.get("strategy", "")
        return jsonify(get_signal_performance(days, symbol, strategy))

    @app.route("/api/health")
    def health():
        hours = request.args.get("hours", 24, type=int)
        return jsonify(get_health_events(hours))

    @app.route("/api/performance-history")
    def performance_history():
        days = request.args.get("days", 30, type=int)
        return jsonify(get_performance_history(days))

    return app


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <title>NunuIRL Trading Dashboard</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        :root {
            --bg: #0a0a0f;
            --card: #12121a;
            --border: #1e1e2e;
            --text: #e0e0e0;
            --muted: #6b7280;
            --green: #10b981;
            --red: #ef4444;
            --blue: #3b82f6;
            --yellow: #f59e0b;
            --purple: #8b5cf6;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'SF Mono', 'Cascadia Code', 'Consolas', monospace;
            background: var(--bg);
            color: var(--text);
            padding: 20px;
            font-size: 13px;
        }
        .container { max-width: 1600px; margin: 0 auto; }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 24px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--border);
        }
        .header h1 { font-size: 20px; font-weight: 700; }
        .header .status {
            display: flex;
            gap: 16px;
            align-items: center;
            font-size: 12px;
            color: var(--muted);
        }
        .status-dot {
            width: 8px; height: 8px;
            border-radius: 50%;
            background: var(--green);
            display: inline-block;
            margin-right: 4px;
        }
        .status-dot.error { background: var(--red); }
        .grid {
            display: grid;
            grid-template-columns: repeat(5, 1fr);
            gap: 12px;
            margin-bottom: 20px;
        }
        .grid-2 {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-bottom: 20px;
        }
        .grid-3 {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 16px;
            margin-bottom: 20px;
        }
        .card {
            background: var(--card);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 16px;
        }
        .card h3 {
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--muted);
            margin-bottom: 8px;
        }
        .metric {
            font-size: 28px;
            font-weight: 700;
            line-height: 1.2;
        }
        .metric.green { color: var(--green); }
        .metric.red { color: var(--red); }
        .metric.blue { color: var(--blue); }
        .metric-sub {
            font-size: 11px;
            color: var(--muted);
            margin-top: 4px;
        }
        .section-title {
            font-size: 14px;
            font-weight: 600;
            margin: 20px 0 12px 0;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th {
            text-align: left;
            padding: 8px 12px;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            color: var(--muted);
            border-bottom: 1px solid var(--border);
            font-weight: 600;
        }
        td {
            padding: 8px 12px;
            border-bottom: 1px solid #15151f;
            font-size: 13px;
        }
        tr:hover { background: rgba(255, 255, 255, 0.02); }
        .pill {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }
        .pill.long { background: rgba(16, 185, 129, 0.15); color: var(--green); }
        .pill.short { background: rgba(239, 68, 68, 0.15); color: var(--red); }
        .pill.win { background: rgba(16, 185, 129, 0.15); color: var(--green); }
        .pill.loss { background: rgba(239, 68, 68, 0.15); color: var(--red); }
        .bar-container {
            width: 100%;
            height: 6px;
            background: #1e1e2e;
            border-radius: 3px;
            overflow: hidden;
            margin-top: 8px;
        }
        .bar-fill {
            height: 100%;
            border-radius: 3px;
            transition: width 0.3s ease;
        }
        .equity-chart {
            width: 100%;
            height: 200px;
            position: relative;
            overflow: hidden;
        }
        .chart-canvas {
            width: 100%;
            height: 100%;
        }
        .health-event {
            padding: 8px 12px;
            border-left: 3px solid var(--border);
            margin-bottom: 6px;
            font-size: 12px;
        }
        .health-event.ALERT { border-left-color: var(--red); }
        .health-event.WARNING { border-left-color: var(--yellow); }
        .health-event.INFO { border-left-color: var(--blue); }
        @media (max-width: 1200px) {
            .grid { grid-template-columns: repeat(3, 1fr); }
            .grid-3 { grid-template-columns: 1fr; }
        }
        @media (max-width: 768px) {
            .grid { grid-template-columns: repeat(2, 1fr); }
            .grid-2 { grid-template-columns: 1fr; }
        }
    </style>
</head>
<body>
<div class="container">
    <div class="header">
        <h1>NunuIRL Trading Dashboard</h1>
        <div class="status">
            <span><span class="status-dot" id="health-dot"></span> <span id="health-text">Connecting...</span></span>
            <span id="last-update">--</span>
        </div>
    </div>

    <!-- KPI Cards -->
    <div class="grid" id="kpi-grid">
        <div class="card">
            <h3>Equity</h3>
            <div class="metric blue" id="kpi-equity">$0</div>
            <div class="metric-sub" id="kpi-equity-sub">--</div>
        </div>
        <div class="card">
            <h3>Daily PnL</h3>
            <div class="metric" id="kpi-pnl">$0</div>
            <div class="metric-sub" id="kpi-pnl-sub">--</div>
        </div>
        <div class="card">
            <h3>Win Rate</h3>
            <div class="metric" id="kpi-wr">0%</div>
            <div class="bar-container"><div class="bar-fill" id="wr-bar" style="width:0;background:var(--green)"></div></div>
        </div>
        <div class="card">
            <h3>Today's Trades</h3>
            <div class="metric blue" id="kpi-trades">0</div>
            <div class="metric-sub" id="kpi-trades-sub">0W / 0L</div>
        </div>
        <div class="card">
            <h3>Signal Score</h3>
            <div class="metric purple" id="kpi-score" style="color:var(--purple)">0</div>
            <div class="metric-sub" id="kpi-score-sub">7-day avg</div>
        </div>
    </div>

    <!-- Equity Curve + Signal Performance -->
    <div class="grid-2">
        <div class="card">
            <h3>Equity Curve (30d)</h3>
            <div class="equity-chart">
                <canvas class="chart-canvas" id="equity-canvas"></canvas>
            </div>
        </div>
        <div class="card">
            <h3>Signal Performance (7d)</h3>
            <div id="signal-perf">
                <table>
                    <thead><tr><th>Strategy</th><th>Trades</th><th>WR</th><th>PnL</th><th>Score</th></tr></thead>
                    <tbody id="signal-perf-body"><tr><td colspan="5" style="color:var(--muted)">Loading...</td></tr></tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- Recent Trades -->
    <div class="section-title">Recent Trades</div>
    <div class="card">
        <table>
            <thead>
                <tr><th>Time</th><th>Symbol</th><th>Side</th><th>Action</th><th>Price</th><th>PnL</th><th>Strategy</th></tr>
            </thead>
            <tbody id="trades-body">
                <tr><td colspan="7" style="color:var(--muted)">Loading...</td></tr>
            </tbody>
        </table>
    </div>

    <!-- Strategy + Symbol + Health -->
    <div class="grid-3">
        <div class="card">
            <h3>By Strategy</h3>
            <table>
                <thead><tr><th>Strategy</th><th>Trades</th><th>WR</th><th>PnL</th></tr></thead>
                <tbody id="by-strat-body"><tr><td colspan="4" style="color:var(--muted)">--</td></tr></tbody>
            </table>
        </div>
        <div class="card">
            <h3>By Symbol</h3>
            <table>
                <thead><tr><th>Symbol</th><th>Trades</th><th>WR</th><th>PnL</th></tr></thead>
                <tbody id="by-sym-body"><tr><td colspan="4" style="color:var(--muted)">--</td></tr></tbody>
            </table>
        </div>
        <div class="card">
            <h3>Health Events (24h)</h3>
            <div id="health-events" style="max-height:300px;overflow-y:auto">
                <div style="color:var(--muted);padding:8px">No events</div>
            </div>
        </div>
    </div>
</div>

<script>
async function loadDashboard() {
    try {
        const resp = await fetch('/api/dashboard');
        const data = await resp.json();

        // KPIs
        const ds = data.daily_summary || {};
        const sp = data.signal_performance || {};
        const eq = data.equity_curve || [];
        const lastEq = eq.length > 0 ? eq[eq.length - 1] : {};

        // Equity
        const equity = lastEq.equity || 0;
        setMetric('kpi-equity', '$' + equity.toLocaleString(undefined, {minimumFractionDigits: 2}), equity > 0);
        if (eq.length > 1) {
            const prevEq = eq[Math.max(0, eq.length - 2)].equity || equity;
            const eqChange = equity - prevEq;
            document.getElementById('kpi-equity-sub').textContent =
                (eqChange >= 0 ? '+' : '') + '$' + eqChange.toFixed(2);
        }

        // Daily PnL
        const pnl = ds.net_pnl || 0;
        const pnlEl = document.getElementById('kpi-pnl');
        pnlEl.textContent = (pnl >= 0 ? '+' : '') + '$' + pnl.toFixed(2);
        pnlEl.className = 'metric ' + (pnl >= 0 ? 'green' : 'red');
        document.getElementById('kpi-pnl-sub').textContent =
            (ds.total_trades || 0) + ' trades, $' + (ds.total_fees || 0).toFixed(2) + ' fees';

        // Win Rate
        const wr = (ds.win_rate || 0) * 100;
        const wrEl = document.getElementById('kpi-wr');
        wrEl.textContent = wr.toFixed(0) + '%';
        wrEl.className = 'metric ' + (wr >= 50 ? 'green' : 'red');
        document.getElementById('wr-bar').style.width = wr + '%';
        document.getElementById('wr-bar').style.background = wr >= 50 ? 'var(--green)' : 'var(--red)';

        // Trades
        document.getElementById('kpi-trades').textContent = ds.total_trades || 0;
        document.getElementById('kpi-trades-sub').textContent =
            (ds.wins || 0) + 'W / ' + (ds.losses || 0) + 'L';

        // Signal Score
        const score = sp.avg_score || 0;
        document.getElementById('kpi-score').textContent = score.toFixed(0);
        document.getElementById('kpi-score-sub').textContent =
            (sp.total || 0) + ' signals scored';

        // Equity curve
        drawEquityCurve(eq);

        // Signal performance by strategy
        const spBody = document.getElementById('signal-perf-body');
        const byStrat = sp.by_strategy || {};
        if (Object.keys(byStrat).length > 0) {
            spBody.innerHTML = Object.entries(byStrat).sort((a, b) => b[1].pnl - a[1].pnl).map(([name, s]) =>
                `<tr>
                    <td>${name}</td>
                    <td>${s.trades}</td>
                    <td class="${s.win_rate >= 0.5 ? 'pill win' : 'pill loss'}">${(s.win_rate * 100).toFixed(0)}%</td>
                    <td style="color:${s.pnl >= 0 ? 'var(--green)' : 'var(--red)'}">$${s.pnl.toFixed(2)}</td>
                    <td>${(s.avg_score || 0).toFixed(0)}</td>
                </tr>`
            ).join('');
        }

        // Recent trades
        const trades = data.recent_trades || [];
        const tBody = document.getElementById('trades-body');
        if (trades.length > 0) {
            tBody.innerHTML = trades.map(t => {
                const time = new Date(t.timestamp).toLocaleTimeString();
                const side = (t.side || '').toUpperCase();
                return `<tr>
                    <td>${time}</td>
                    <td><strong>${t.symbol}</strong></td>
                    <td><span class="pill ${side === 'BUY' || side === 'LONG' ? 'long' : 'short'}">${side}</span></td>
                    <td>${t.action}</td>
                    <td>$${(t.price || 0).toFixed(2)}</td>
                    <td style="color:${t.pnl >= 0 ? 'var(--green)' : 'var(--red)'}">$${(t.pnl || 0).toFixed(2)}</td>
                    <td style="color:var(--muted)">${t.strategy || ''}</td>
                </tr>`;
            }).join('');
        }

        // By strategy
        const bsBody = document.getElementById('by-strat-body');
        const bsData = ds.by_strategy || {};
        if (Object.keys(bsData).length > 0) {
            bsBody.innerHTML = Object.entries(bsData).sort((a, b) => b[1].pnl - a[1].pnl).map(([name, s]) => {
                const swr = s.trades > 0 ? (s.wins / s.trades * 100) : 0;
                return `<tr>
                    <td>${name}</td><td>${s.trades}</td>
                    <td>${swr.toFixed(0)}%</td>
                    <td style="color:${s.pnl >= 0 ? 'var(--green)' : 'var(--red)'}">$${s.pnl.toFixed(2)}</td>
                </tr>`;
            }).join('');
        }

        // By symbol from signal performance
        const symBody = document.getElementById('by-sym-body');
        const symData = sp.by_symbol || {};
        if (Object.keys(symData).length > 0) {
            symBody.innerHTML = Object.entries(symData).sort((a, b) => b[1].pnl - a[1].pnl).map(([sym, s]) =>
                `<tr>
                    <td><strong>${sym}</strong></td><td>${s.trades}</td>
                    <td>${(s.win_rate * 100).toFixed(0)}%</td>
                    <td style="color:${s.pnl >= 0 ? 'var(--green)' : 'var(--red)'}">$${s.pnl.toFixed(2)}</td>
                </tr>`
            ).join('');
        }

        // Health events
        const healthEl = document.getElementById('health-events');
        const events = data.health_events || [];
        if (events.length > 0) {
            healthEl.innerHTML = events.slice(0, 20).map(e =>
                `<div class="health-event ${e.severity}">
                    <strong>${e.event_type}</strong> ${new Date(e.timestamp).toLocaleTimeString()}
                    <br><span style="color:var(--muted)">${e.message.substring(0, 120)}</span>
                </div>`
            ).join('');
        }

        // Health status
        const dot = document.getElementById('health-dot');
        const htxt = document.getElementById('health-text');
        const hasAlerts = events.some(e => e.severity === 'ALERT');
        dot.className = 'status-dot' + (hasAlerts ? ' error' : '');
        htxt.textContent = hasAlerts ? 'Issues detected' : 'Healthy';

        document.getElementById('last-update').textContent = new Date().toLocaleTimeString();

    } catch (err) {
        console.error('Dashboard load error:', err);
        document.getElementById('health-dot').className = 'status-dot error';
        document.getElementById('health-text').textContent = 'Connection error';
    }
}

function setMetric(id, text, positive) {
    const el = document.getElementById(id);
    el.textContent = text;
}

function drawEquityCurve(data) {
    const canvas = document.getElementById('equity-canvas');
    if (!canvas || data.length < 2) return;
    const ctx = canvas.getContext('2d');
    const rect = canvas.parentElement.getBoundingClientRect();
    canvas.width = rect.width * 2;
    canvas.height = rect.height * 2;
    ctx.scale(2, 2);
    const w = rect.width;
    const h = rect.height;

    const values = data.map(d => d.equity);
    const mn = Math.min(...values) * 0.998;
    const mx = Math.max(...values) * 1.002;
    const range = mx - mn || 1;

    ctx.clearRect(0, 0, w, h);

    // Fill gradient
    const grad = ctx.createLinearGradient(0, 0, 0, h);
    const isUp = values[values.length - 1] >= values[0];
    grad.addColorStop(0, isUp ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)');
    grad.addColorStop(1, 'rgba(0, 0, 0, 0)');

    ctx.beginPath();
    ctx.moveTo(0, h);
    for (let i = 0; i < values.length; i++) {
        const x = (i / (values.length - 1)) * w;
        const y = h - ((values[i] - mn) / range) * h * 0.9 - h * 0.05;
        ctx.lineTo(x, y);
    }
    ctx.lineTo(w, h);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // Line
    ctx.beginPath();
    for (let i = 0; i < values.length; i++) {
        const x = (i / (values.length - 1)) * w;
        const y = h - ((values[i] - mn) / range) * h * 0.9 - h * 0.05;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    }
    ctx.strokeStyle = isUp ? '#10b981' : '#ef4444';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Labels
    ctx.fillStyle = '#6b7280';
    ctx.font = '10px monospace';
    ctx.fillText('$' + mx.toFixed(0), 4, 14);
    ctx.fillText('$' + mn.toFixed(0), 4, h - 4);
}

// Initial load + auto-refresh
loadDashboard();
setInterval(loadDashboard, 30000);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    # Load .env
    try:
        from dotenv import load_dotenv
        root_env = Path(__file__).parent.parent / ".env"
        if root_env.exists():
            load_dotenv(root_env)
        else:
            load_dotenv()
    except ImportError:
        pass

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    app = _create_app()
    port = int(os.getenv("DASHBOARD_PORT", "5000"))
    print(f"Starting NunuIRL Dashboard on http://localhost:{port}")
    app.run(debug=False, host="0.0.0.0", port=port)
