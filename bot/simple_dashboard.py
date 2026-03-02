"""
SQLite-powered trading dashboard for monitoring the bot.

Shows:
- Equity curve (from SQLite equity_snapshots)
- Current positions + live P&L
- Recent trades + signals
- Strategy leaderboard (which strategies make money)
- Signal performance by confidence band
- Health monitoring status
- Win rate, profit factor, etc.

Run: cd bot && python simple_dashboard.py
Access: http://localhost:5000
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any

from flask import Flask, jsonify, render_template_string, request
from flask_cors import CORS

from data.db import (
    init_db, get_daily_summary, get_recent_trades, get_trades_today,
    get_equity_curve, get_recent_signals, get_signal_performance,
    get_strategy_leaderboard, get_health_events,
)

logger = logging.getLogger("bot.dashboard")

app = Flask(__name__)
CORS(app)


# ─── API Endpoints ──────────────────────────────────────────────

@app.route("/")
def index():
    """Serve dashboard HTML."""
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/summary")
def summary():
    """Get daily performance summary from SQLite."""
    return jsonify(get_daily_summary())


@app.route("/api/recent-trades")
def recent_trades():
    """Get recent closed trades from SQLite."""
    limit = request.args.get("limit", 20, type=int)
    return jsonify(get_recent_trades(limit))


@app.route("/api/equity-curve")
def equity_curve():
    """Get equity curve data for charting."""
    hours = request.args.get("hours", 168, type=int)
    return jsonify(get_equity_curve(hours))


@app.route("/api/signals")
def signals():
    """Get recent signals."""
    limit = request.args.get("limit", 20, type=int)
    return jsonify(get_recent_signals(limit))


@app.route("/api/signal-performance")
def signal_performance():
    """Get signal outcome performance stats."""
    days = request.args.get("days", 30, type=int)
    return jsonify(get_signal_performance(days))


@app.route("/api/strategy-leaderboard")
def strategy_leaderboard():
    """Get strategy ranking by profitability."""
    days = request.args.get("days", 7, type=int)
    return jsonify(get_strategy_leaderboard(days))


@app.route("/api/health")
def health():
    """Get recent health events."""
    hours = request.args.get("hours", 24, type=int)
    events = get_health_events(hours)
    # Also read heartbeat file
    heartbeat = {}
    try:
        with open("data/heartbeat.json") as f:
            heartbeat = json.load(f)
    except Exception:
        pass
    return jsonify({"heartbeat": heartbeat, "events": events})


# ─── HTML Dashboard ─────────────────────────────────────────────

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
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, monospace;
            background: #0a0a0f;
            color: #e0e0e0;
            padding: 20px;
        }
        .container { max-width: 1600px; margin: 0 auto; }
        h1 { font-size: 24px; margin-bottom: 20px; color: #fff; }
        h2 { font-size: 16px; margin: 20px 0 10px 0; color: #8888aa; text-transform: uppercase; letter-spacing: 1px; }
        .header {
            display: flex; justify-content: space-between; align-items: center;
            margin-bottom: 30px; padding-bottom: 15px; border-bottom: 1px solid #222;
        }
        .health-badge {
            padding: 6px 14px; border-radius: 20px; font-size: 12px; font-weight: 600;
        }
        .health-ok { background: #0a2e0a; color: #4caf50; border: 1px solid #2e7d32; }
        .health-warn { background: #2e2a0a; color: #ff9800; border: 1px solid #f57c00; }
        .health-bad { background: #2e0a0a; color: #f44336; border: 1px solid #c62828; }

        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 25px; }
        .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 25px; }
        @media (max-width: 900px) { .grid-2 { grid-template-columns: 1fr; } }

        .card {
            background: #12121a;
            border: 1px solid #1e1e2e;
            padding: 18px;
            border-radius: 8px;
        }
        .metric { font-size: 28px; font-weight: bold; color: #4caf50; }
        .metric.negative { color: #f44336; }
        .metric.neutral { color: #888; }
        .label { font-size: 11px; color: #666; text-transform: uppercase; margin-bottom: 4px; letter-spacing: 0.5px; }
        .sublabel { font-size: 11px; color: #555; margin-top: 4px; }

        /* Equity chart */
        .chart-container { position: relative; height: 250px; background: #12121a; border: 1px solid #1e1e2e; border-radius: 8px; padding: 15px; margin-bottom: 25px; overflow: hidden; }
        .chart-canvas { width: 100%; height: 100%; }

        table { width: 100%; border-collapse: collapse; font-size: 13px; }
        th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #1a1a2a; }
        th { font-weight: 600; color: #666; font-size: 11px; text-transform: uppercase; }
        tr:hover { background: #15152a; }
        .win { color: #4caf50; }
        .loss { color: #f44336; }
        .neutral { color: #888; }

        .refresh-btn {
            background: #1a1a2e; color: #4caf50; border: 1px solid #2e7d32;
            padding: 6px 14px; border-radius: 4px; cursor: pointer; font-size: 12px;
        }
        .refresh-btn:hover { background: #1e2e1e; }

        .status-bar {
            display: flex; justify-content: space-between; align-items: center;
            margin-top: 20px; padding: 10px; font-size: 11px; color: #555;
            border-top: 1px solid #1a1a2a;
        }

        .bar { display: inline-block; height: 14px; border-radius: 2px; margin-right: 2px; }
        .bar-win { background: #4caf50; }
        .bar-loss { background: #f44336; }

        .confidence-bar {
            display: inline-block; width: 60px; height: 8px; background: #1a1a2a;
            border-radius: 4px; overflow: hidden; vertical-align: middle;
        }
        .confidence-fill { height: 100%; border-radius: 4px; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>WAGMI Trading Dashboard</h1>
            <div style="display: flex; gap: 10px; align-items: center;">
                <span id="health-badge" class="health-badge health-ok">HEALTHY</span>
                <button class="refresh-btn" onclick="loadAll()">Refresh</button>
            </div>
        </div>

        <!-- Performance Metrics -->
        <h2>Performance</h2>
        <div class="grid">
            <div class="card">
                <div class="label">Total Trades</div>
                <div class="metric neutral" id="total-trades">0</div>
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
                <div class="label">Best Strategy</div>
                <div class="metric neutral" id="best-strategy" style="font-size:18px;">--</div>
            </div>
            <div class="card">
                <div class="label">Equity</div>
                <div class="metric neutral" id="equity">$0</div>
            </div>
        </div>

        <!-- Equity Curve -->
        <h2>Equity Curve (7d)</h2>
        <div class="chart-container">
            <canvas id="equity-chart" class="chart-canvas"></canvas>
        </div>

        <div class="grid-2">
            <!-- Strategy Leaderboard -->
            <div>
                <h2>Strategy Leaderboard (7d)</h2>
                <div class="card">
                    <table>
                        <thead>
                            <tr><th>Strategy</th><th>Trades</th><th>Win Rate</th><th>P&L</th><th>Avg</th></tr>
                        </thead>
                        <tbody id="leaderboard">
                            <tr><td colspan="5" style="color:#555">Loading...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>

            <!-- Signal Performance by Confidence -->
            <div>
                <h2>Signal Performance by Confidence</h2>
                <div class="card">
                    <table>
                        <thead>
                            <tr><th>Band</th><th>Total</th><th>Win Rate</th><th>P&L</th></tr>
                        </thead>
                        <tbody id="confidence-bands">
                            <tr><td colspan="4" style="color:#555">Loading...</td></tr>
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- Recent Trades -->
        <h2>Recent Trades</h2>
        <div class="card">
            <table>
                <thead>
                    <tr><th>Time</th><th>Symbol</th><th>Side</th><th>Action</th><th>Price</th><th>P&L</th><th>Strategy</th></tr>
                </thead>
                <tbody id="recent-trades">
                    <tr><td colspan="7" style="color:#555">Loading...</td></tr>
                </tbody>
            </table>
        </div>

        <!-- Recent Signals -->
        <h2>Recent Signals</h2>
        <div class="card">
            <table>
                <thead>
                    <tr><th>Time</th><th>Symbol</th><th>Side</th><th>Conf</th><th>Entry</th><th>SL</th><th>TP1</th><th>Traded</th></tr>
                </thead>
                <tbody id="recent-signals">
                    <tr><td colspan="8" style="color:#555">Loading...</td></tr>
                </tbody>
            </table>
        </div>

        <!-- Health Events -->
        <h2>Health Events (24h)</h2>
        <div class="card">
            <div id="health-info" style="margin-bottom:10px; font-size:12px; color:#888;"></div>
            <table>
                <thead>
                    <tr><th>Time</th><th>Type</th><th>Severity</th><th>Message</th></tr>
                </thead>
                <tbody id="health-events">
                    <tr><td colspan="4" style="color:#555">Loading...</td></tr>
                </tbody>
            </table>
        </div>

        <div class="status-bar">
            <span>Last updated: <span id="last-update">--</span></span>
            <span>Auto-refresh every 30s</span>
        </div>
    </div>

    <script>
        function fmt(v, dec=2) { return v != null ? Number(v).toFixed(dec) : '0'; }
        function fmtPrice(p) {
            if (!p || p === 0) return '0';
            const a = Math.abs(p);
            if (a >= 1) return p.toFixed(2);
            if (a >= 0.001) return p.toFixed(4);
            return p.toFixed(8);
        }
        function fmtTime(ts) {
            if (!ts) return '--';
            const d = new Date(ts);
            return d.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'});
        }
        function pnlClass(v) { return v > 0 ? 'win' : v < 0 ? 'loss' : 'neutral'; }

        async function loadSummary() {
            try {
                const r = await fetch('/api/summary');
                const d = await r.json();
                document.getElementById('total-trades').innerText = d.total_trades || 0;
                const wrEl = document.getElementById('win-rate');
                const wr = ((d.win_rate || 0) * 100).toFixed(1);
                wrEl.innerText = wr + '%';
                wrEl.className = 'metric ' + (wr >= 50 ? '' : 'negative');
                const pnlEl = document.getElementById('net-pnl');
                pnlEl.innerText = '$' + fmt(d.net_pnl);
                pnlEl.className = 'metric ' + pnlClass(d.net_pnl);
                document.getElementById('best-strategy').innerText = d.best_strategy || '--';
            } catch(e) { console.error('Summary error:', e); }
        }

        async function loadEquity() {
            try {
                const r = await fetch('/api/equity-curve?hours=168');
                const data = await r.json();
                if (!data || data.length === 0) return;

                document.getElementById('equity').innerText = '$' + fmt(data[data.length-1].equity, 0);

                // Draw equity chart on canvas
                const canvas = document.getElementById('equity-chart');
                const ctx = canvas.getContext('2d');
                canvas.width = canvas.parentElement.clientWidth - 30;
                canvas.height = canvas.parentElement.clientHeight - 30;

                const equities = data.map(d => d.equity);
                const minE = Math.min(...equities) * 0.998;
                const maxE = Math.max(...equities) * 1.002;
                const range = maxE - minE || 1;
                const w = canvas.width;
                const h = canvas.height;
                const step = w / (equities.length - 1 || 1);

                ctx.clearRect(0, 0, w, h);

                // Grid lines
                ctx.strokeStyle = '#1a1a2a';
                ctx.lineWidth = 1;
                for (let i = 0; i <= 4; i++) {
                    const y = h * i / 4;
                    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
                    ctx.fillStyle = '#444';
                    ctx.font = '10px monospace';
                    ctx.fillText('$' + (maxE - range * i / 4).toFixed(0), 5, y + 12);
                }

                // Equity line
                const startE = equities[0];
                const endE = equities[equities.length - 1];
                ctx.strokeStyle = endE >= startE ? '#4caf50' : '#f44336';
                ctx.lineWidth = 2;
                ctx.beginPath();
                for (let i = 0; i < equities.length; i++) {
                    const x = i * step;
                    const y = h - (equities[i] - minE) / range * h;
                    if (i === 0) ctx.moveTo(x, y);
                    else ctx.lineTo(x, y);
                }
                ctx.stroke();

                // Fill gradient
                ctx.lineTo(w, h); ctx.lineTo(0, h); ctx.closePath();
                const grad = ctx.createLinearGradient(0, 0, 0, h);
                grad.addColorStop(0, endE >= startE ? 'rgba(76,175,80,0.15)' : 'rgba(244,67,54,0.15)');
                grad.addColorStop(1, 'rgba(0,0,0,0)');
                ctx.fillStyle = grad;
                ctx.fill();

            } catch(e) { console.error('Equity error:', e); }
        }

        async function loadLeaderboard() {
            try {
                const r = await fetch('/api/strategy-leaderboard?days=7');
                const data = await r.json();
                const tbody = document.getElementById('leaderboard');
                if (!data || data.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="5" style="color:#555">No data</td></tr>';
                    return;
                }
                tbody.innerHTML = data.map(s => {
                    const wr = s.trades > 0 ? (s.wins / s.trades * 100).toFixed(0) : 0;
                    return `<tr>
                        <td><strong>${s.strategy || 'unknown'}</strong></td>
                        <td>${s.trades}</td>
                        <td>${wr}%</td>
                        <td class="${pnlClass(s.total_pnl)}">$${fmt(s.total_pnl)}</td>
                        <td class="${pnlClass(s.avg_pnl)}">$${fmt(s.avg_pnl)}</td>
                    </tr>`;
                }).join('');
            } catch(e) { console.error('Leaderboard error:', e); }
        }

        async function loadSignalPerformance() {
            try {
                const r = await fetch('/api/signal-performance?days=30');
                const data = await r.json();
                const tbody = document.getElementById('confidence-bands');
                if (!data || !data.by_confidence || Object.keys(data.by_confidence).length === 0) {
                    tbody.innerHTML = '<tr><td colspan="4" style="color:#555">No data</td></tr>';
                    return;
                }
                const bands = Object.entries(data.by_confidence).sort((a, b) => b[0].localeCompare(a[0]));
                tbody.innerHTML = bands.map(([band, stats]) => {
                    const wr = ((stats.win_rate || 0) * 100).toFixed(0);
                    return `<tr>
                        <td><strong>${band}</strong></td>
                        <td>${stats.total}</td>
                        <td>
                            <span class="confidence-bar"><span class="confidence-fill" style="width:${wr}%; background:${wr >= 50 ? '#4caf50' : '#f44336'}"></span></span>
                            ${wr}%
                        </td>
                        <td class="${pnlClass(stats.pnl)}">$${fmt(stats.pnl)}</td>
                    </tr>`;
                }).join('');
            } catch(e) { console.error('Signal perf error:', e); }
        }

        async function loadRecentTrades() {
            try {
                const r = await fetch('/api/recent-trades?limit=15');
                const data = await r.json();
                const tbody = document.getElementById('recent-trades');
                if (!data || data.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="7" style="color:#555">No trades</td></tr>';
                    return;
                }
                tbody.innerHTML = data.map(t => `<tr>
                    <td>${fmtTime(t.timestamp)}</td>
                    <td><strong>${t.symbol}</strong></td>
                    <td>${t.side}</td>
                    <td>${t.action}</td>
                    <td>${fmtPrice(t.price)}</td>
                    <td class="${pnlClass(t.pnl)}">$${fmt(t.pnl)}</td>
                    <td style="color:#666">${t.strategy || '--'}</td>
                </tr>`).join('');
            } catch(e) { console.error('Trades error:', e); }
        }

        async function loadRecentSignals() {
            try {
                const r = await fetch('/api/signals?limit=15');
                const data = await r.json();
                const tbody = document.getElementById('recent-signals');
                if (!data || data.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="8" style="color:#555">No signals</td></tr>';
                    return;
                }
                tbody.innerHTML = data.map(s => `<tr>
                    <td>${fmtTime(s.timestamp)}</td>
                    <td><strong>${s.symbol}</strong></td>
                    <td>${s.side}</td>
                    <td>
                        <span class="confidence-bar"><span class="confidence-fill" style="width:${s.confidence}%; background:${s.confidence >= 75 ? '#4caf50' : s.confidence >= 65 ? '#ff9800' : '#f44336'}"></span></span>
                        ${s.confidence.toFixed(0)}%
                    </td>
                    <td>${fmtPrice(s.entry)}</td>
                    <td>${fmtPrice(s.sl)}</td>
                    <td>${fmtPrice(s.tp1)}</td>
                    <td>${s.traded ? '<span class="win">YES</span>' : '<span style="color:#555">no</span>'}</td>
                </tr>`).join('');
            } catch(e) { console.error('Signals error:', e); }
        }

        async function loadHealth() {
            try {
                const r = await fetch('/api/health');
                const data = await r.json();
                const badge = document.getElementById('health-badge');
                const hb = data.heartbeat || {};

                if (hb.epoch) {
                    const ago = (Date.now() / 1000) - hb.epoch;
                    if (ago > 600) {
                        badge.className = 'health-badge health-bad';
                        badge.innerText = 'STALLED ' + Math.floor(ago/60) + 'm';
                    } else if (hb.errors > 10) {
                        badge.className = 'health-badge health-warn';
                        badge.innerText = 'ERRORS: ' + hb.errors;
                    } else {
                        badge.className = 'health-badge health-ok';
                        badge.innerText = 'HEALTHY';
                    }
                }

                const info = document.getElementById('health-info');
                if (hb.epoch) {
                    info.innerHTML = `Uptime: ${Math.floor((hb.uptime_s||0)/3600)}h | Scans: ${hb.scan_count||0} | Avg Loop: ${(hb.avg_loop_s||0).toFixed(1)}s | Errors: ${hb.errors||0}`;
                }

                const tbody = document.getElementById('health-events');
                const events = data.events || [];
                if (events.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="4" style="color:#555">No health events (good!)</td></tr>';
                } else {
                    tbody.innerHTML = events.slice(0, 10).map(e => {
                        const sevClass = e.severity === 'critical' ? 'loss' : e.severity === 'warning' ? '' : 'neutral';
                        return `<tr>
                            <td>${fmtTime(e.timestamp)}</td>
                            <td>${e.event_type}</td>
                            <td class="${sevClass}">${e.severity}</td>
                            <td>${e.message || '--'}</td>
                        </tr>`;
                    }).join('');
                }
            } catch(e) { console.error('Health error:', e); }
        }

        async function loadAll() {
            await Promise.all([
                loadSummary(),
                loadEquity(),
                loadLeaderboard(),
                loadSignalPerformance(),
                loadRecentTrades(),
                loadRecentSignals(),
                loadHealth(),
            ]);
            document.getElementById('last-update').innerText = new Date().toLocaleTimeString();
        }

        loadAll();
        setInterval(loadAll, 30000);
    </script>
</body>
</html>
"""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    init_db()
    print("Starting dashboard on http://localhost:5000")
    print("View your trading performance in real-time!")
    app.run(debug=True, host="0.0.0.0", port=5000)
