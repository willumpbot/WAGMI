"""
Lightweight web dashboard for the NunuIRL trading bot.

Uses Python's built-in http.server (zero external dependencies).
Serves a single-page HTML dashboard with auto-refreshing data via
fetch() calls to JSON API endpoints backed by the SQLite data layer.

Usage:
    # As a background thread inside the bot:
    from dashboard import get_dashboard_server
    srv = get_dashboard_server()
    srv.start(bot_instance=bot)

    # Standalone:
    cd bot && python -m dashboard.server
"""

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, Optional
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure bot/ is on sys.path so ``from data.db import ...`` works regardless
# of how this module is invoked.
# ---------------------------------------------------------------------------
_BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)

logger = logging.getLogger("bot.dashboard")

# ---------------------------------------------------------------------------
# Startup timestamp -- used to calculate uptime in the health endpoint.
# ---------------------------------------------------------------------------
_START_TIME = time.time()


# ═══════════════════════════════════════════════════════════════════════════
# HTML Dashboard (inline single-page app)
# ═══════════════════════════════════════════════════════════════════════════

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NunuIRL Trading Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
/* ── CSS Variables ─────────────────────────────────────────────────── */
:root {
    --bg:      #080810;
    --bg2:     #0d0d18;
    --card:    #111120;
    --border:  #1c1c30;
    --text:    #d8d8e8;
    --muted:   #5e5e80;
    --green:   #00e6a0;
    --red:     #ff4466;
    --blue:    #4488ff;
    --yellow:  #ffc444;
    --purple:  #a366ff;
    --cyan:    #22d3ee;
    --radius:  8px;
}

/* ── Reset & Base ──────────────────────────────────────────────────── */
*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
html { font-size: 13px; }
body {
    font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
    min-height: 100vh;
}
a { color: var(--blue); text-decoration: none; }

/* ── Layout ────────────────────────────────────────────────────────── */
.container { max-width: 1680px; margin: 0 auto; padding: 20px 24px; }

.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-bottom: 16px;
    margin-bottom: 20px;
    border-bottom: 1px solid var(--border);
}
.header h1 {
    font-size: 18px;
    font-weight: 700;
    letter-spacing: -0.5px;
    background: linear-gradient(135deg, var(--blue), var(--purple));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}
.header-right {
    display: flex;
    align-items: center;
    gap: 20px;
    font-size: 11px;
    color: var(--muted);
}

/* Status dot */
.dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    display: inline-block;
    margin-right: 5px;
    vertical-align: middle;
}
.dot-green  { background: var(--green);  box-shadow: 0 0 6px var(--green); }
.dot-yellow { background: var(--yellow); box-shadow: 0 0 6px var(--yellow); }
.dot-red    { background: var(--red);    box-shadow: 0 0 6px var(--red); }

/* ── Grid helpers ──────────────────────────────────────────────────── */
.grid-5 { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 20px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
.grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-bottom: 20px; }

/* ── Card ──────────────────────────────────────────────────────────── */
.card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 16px 18px;
    position: relative;
    overflow: hidden;
}
.card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--border), transparent);
}
.card h3 {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--muted);
    margin-bottom: 10px;
    font-weight: 600;
}

/* ── KPI metrics ───────────────────────────────────────────────────── */
.metric {
    font-size: 26px;
    font-weight: 700;
    letter-spacing: -0.5px;
    line-height: 1.1;
}
.metric-sub {
    font-size: 11px;
    color: var(--muted);
    margin-top: 4px;
}
.green  { color: var(--green); }
.red    { color: var(--red); }
.blue   { color: var(--blue); }
.yellow { color: var(--yellow); }
.purple { color: var(--purple); }
.cyan   { color: var(--cyan); }

/* ── Progress bar ──────────────────────────────────────────────────── */
.bar-track {
    width: 100%;
    height: 5px;
    background: var(--border);
    border-radius: 3px;
    overflow: hidden;
    margin-top: 10px;
}
.bar-fill {
    height: 100%;
    border-radius: 3px;
    transition: width 0.6s ease;
}

/* ── Tables ────────────────────────────────────────────────────────── */
table { width: 100%; border-collapse: collapse; }
th {
    text-align: left;
    padding: 8px 10px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: var(--muted);
    border-bottom: 1px solid var(--border);
    font-weight: 600;
}
td {
    padding: 7px 10px;
    border-bottom: 1px solid rgba(28, 28, 48, 0.5);
    font-size: 12px;
    white-space: nowrap;
}
tr:hover td { background: rgba(255,255,255,0.015); }

/* ── Pills / badges ───────────────────────────────────────────────── */
.pill {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.3px;
}
.pill-long  { background: rgba(0,230,160,0.12); color: var(--green); }
.pill-short { background: rgba(255,68,102,0.12); color: var(--red); }
.pill-win   { background: rgba(0,230,160,0.12); color: var(--green); }
.pill-loss  { background: rgba(255,68,102,0.12); color: var(--red); }
.pill-action {
    background: rgba(68,136,255,0.12); color: var(--blue);
    font-size: 10px; font-weight: 700;
}

/* ── Section title ─────────────────────────────────────────────────── */
.section-title {
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--muted);
    margin: 24px 0 12px 0;
}

/* ── Chart container ───────────────────────────────────────────────── */
.chart-wrap { position: relative; height: 220px; }
.chart-wrap canvas { width: 100% !important; height: 100% !important; }

/* ── Strategy performance bars ─────────────────────────────────────── */
.strat-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.strat-label { width: 120px; font-size: 11px; color: var(--text); text-align: right; overflow: hidden; text-overflow: ellipsis; }
.strat-bar-track { flex: 1; height: 18px; background: var(--border); border-radius: 4px; position: relative; overflow: hidden; }
.strat-bar-fill { height: 100%; border-radius: 4px; transition: width 0.4s ease; display: flex; align-items: center; padding-left: 6px; font-size: 10px; font-weight: 700; color: #fff; min-width: 0; }
.strat-pnl { width: 80px; font-size: 11px; text-align: right; font-weight: 600; }

/* ── Health events ─────────────────────────────────────────────────── */
.health-item {
    padding: 8px 10px;
    border-left: 3px solid var(--border);
    margin-bottom: 6px;
    font-size: 11px;
    border-radius: 0 4px 4px 0;
    background: rgba(255,255,255,0.01);
}
.health-item.sev-INFO    { border-left-color: var(--blue); }
.health-item.sev-WARNING { border-left-color: var(--yellow); }
.health-item.sev-ALERT   { border-left-color: var(--red); }
.health-item.sev-ERROR   { border-left-color: var(--red); }
.health-time { color: var(--muted); font-size: 10px; }
.health-type { font-weight: 700; margin-right: 6px; }

/* ── Open positions ────────────────────────────────────────────────── */
.pos-pnl-positive { color: var(--green); font-weight: 700; }
.pos-pnl-negative { color: var(--red);   font-weight: 700; }

/* ── Empty state ───────────────────────────────────────────────────── */
.empty { color: var(--muted); padding: 16px; text-align: center; font-size: 12px; }

/* ── Refresh indicator ─────────────────────────────────────────────── */
.refresh-pulse {
    display: inline-block;
    width: 6px; height: 6px;
    border-radius: 50%;
    background: var(--blue);
    margin-right: 6px;
    animation: pulse 1.5s ease infinite;
}
@keyframes pulse {
    0%, 100% { opacity: 0.3; transform: scale(0.8); }
    50%      { opacity: 1;   transform: scale(1.2); }
}

/* ── Scrollable containers ─────────────────────────────────────────── */
.scroll-y { max-height: 340px; overflow-y: auto; }
.scroll-y::-webkit-scrollbar { width: 4px; }
.scroll-y::-webkit-scrollbar-track { background: transparent; }
.scroll-y::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }

/* ── Responsive ────────────────────────────────────────────────────── */
@media (max-width: 1280px) {
    .grid-5 { grid-template-columns: repeat(3, 1fr); }
    .grid-3 { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 900px) {
    .grid-5 { grid-template-columns: repeat(2, 1fr); }
    .grid-2 { grid-template-columns: 1fr; }
    .grid-3 { grid-template-columns: 1fr; }
    .container { padding: 12px; }
    .metric { font-size: 22px; }
}
@media (max-width: 540px) {
    .grid-5 { grid-template-columns: 1fr; }
    html { font-size: 12px; }
}
</style>
</head>
<body>
<div class="container">

    <!-- ═══ Header ═══════════════════════════════════════════════════ -->
    <div class="header">
        <h1>NunuIRL Trading Dashboard</h1>
        <div class="header-right">
            <span id="uptime-display">Uptime: --</span>
            <span>
                <span class="dot dot-green" id="health-dot"></span>
                <span id="health-label">Connecting...</span>
            </span>
            <span>
                <span class="refresh-pulse"></span>
                <span id="last-refresh">--</span>
            </span>
        </div>
    </div>

    <!-- ═══ KPI Cards ════════════════════════════════════════════════ -->
    <div class="grid-5" id="kpi-section">
        <!-- Equity -->
        <div class="card">
            <h3>Equity</h3>
            <div class="metric blue" id="kpi-equity">--</div>
            <div class="metric-sub" id="kpi-equity-change">--</div>
        </div>
        <!-- Daily PnL -->
        <div class="card">
            <h3>Daily PnL</h3>
            <div class="metric" id="kpi-pnl">$0.00</div>
            <div class="metric-sub" id="kpi-pnl-detail">0 trades | $0.00 fees</div>
        </div>
        <!-- Win Rate -->
        <div class="card">
            <h3>Win Rate</h3>
            <div class="metric" id="kpi-winrate">0%</div>
            <div class="bar-track"><div class="bar-fill" id="wr-bar" style="width:0%;background:var(--green)"></div></div>
            <div class="metric-sub" id="kpi-wl">0W / 0L</div>
        </div>
        <!-- Trades Today -->
        <div class="card">
            <h3>Trades Today</h3>
            <div class="metric blue" id="kpi-trades">0</div>
            <div class="metric-sub" id="kpi-best-worst">--</div>
        </div>
        <!-- Signal Score -->
        <div class="card">
            <h3>Signal Score (7d)</h3>
            <div class="metric purple" id="kpi-score">--</div>
            <div class="bar-track"><div class="bar-fill" id="score-bar" style="width:0%;background:var(--purple)"></div></div>
            <div class="metric-sub" id="kpi-score-detail">--</div>
        </div>
    </div>

    <!-- ═══ Equity Curve + Open Positions ════════════════════════════ -->
    <div class="grid-2">
        <div class="card">
            <h3>Equity Curve (30d)</h3>
            <div class="chart-wrap">
                <canvas id="equity-chart"></canvas>
            </div>
        </div>
        <div class="card">
            <h3>Open Positions</h3>
            <div class="scroll-y">
                <table>
                    <thead>
                        <tr>
                            <th>Symbol</th>
                            <th>Side</th>
                            <th>Entry</th>
                            <th>Unrealized PnL</th>
                            <th>Leverage</th>
                            <th>Hold Time</th>
                        </tr>
                    </thead>
                    <tbody id="positions-body">
                        <tr><td colspan="6" class="empty">No open positions</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- ═══ Today's Performance + Signal Performance ═════════════════ -->
    <div class="section-title">Performance</div>
    <div class="grid-2">
        <div class="card">
            <h3>Signal Performance by Strategy (7d)</h3>
            <div class="scroll-y">
                <table>
                    <thead>
                        <tr><th>Strategy</th><th>Trades</th><th>Wins</th><th>Win Rate</th><th>PnL</th><th>Avg Score</th></tr>
                    </thead>
                    <tbody id="signal-strat-body">
                        <tr><td colspan="6" class="empty">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
        <div class="card">
            <h3>Signal Performance by Symbol (7d)</h3>
            <div class="scroll-y">
                <table>
                    <thead>
                        <tr><th>Symbol</th><th>Trades</th><th>Wins</th><th>Win Rate</th><th>PnL</th></tr>
                    </thead>
                    <tbody id="signal-sym-body">
                        <tr><td colspan="5" class="empty">Loading...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- ═══ Strategy Breakdown Bars ══════════════════════════════════ -->
    <div class="section-title">Strategy Breakdown (Today)</div>
    <div class="card">
        <div id="strategy-bars">
            <div class="empty">No strategy data yet</div>
        </div>
    </div>

    <!-- ═══ Recent Trades ════════════════════════════════════════════ -->
    <div class="section-title">Recent Trades (last 20)</div>
    <div class="card">
        <div class="scroll-y">
            <table>
                <thead>
                    <tr>
                        <th>Time</th>
                        <th>Symbol</th>
                        <th>Side</th>
                        <th>Action</th>
                        <th>Price</th>
                        <th>Qty</th>
                        <th>PnL</th>
                        <th>Fee</th>
                        <th>Strategy</th>
                    </tr>
                </thead>
                <tbody id="trades-body">
                    <tr><td colspan="9" class="empty">Loading...</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- ═══ Health Status ════════════════════════════════════════════ -->
    <div class="section-title">Health Status (24h)</div>
    <div class="grid-3">
        <div class="card">
            <h3>Bot Uptime</h3>
            <div class="metric cyan" id="health-uptime">--</div>
            <div class="metric-sub" id="health-started">--</div>
        </div>
        <div class="card">
            <h3>Last Heartbeat</h3>
            <div class="metric" id="health-heartbeat" style="font-size:18px;">--</div>
            <div class="metric-sub" id="health-heartbeat-ago">--</div>
        </div>
        <div class="card">
            <h3>Error Count (24h)</h3>
            <div class="metric" id="health-errors">0</div>
            <div class="metric-sub" id="health-warnings">0 warnings</div>
        </div>
    </div>
    <div class="card" style="margin-bottom:20px;">
        <h3>Recent Health Events</h3>
        <div class="scroll-y" id="health-events-list">
            <div class="empty">No health events</div>
        </div>
    </div>

    <!-- Footer -->
    <div style="text-align:center;color:var(--muted);font-size:10px;padding:16px 0;">
        NunuIRL Trading Bot &mdash; Dashboard v2.0 &mdash; Auto-refresh 30s
    </div>
</div>

<!-- ═══════════════════════════════════════════════════════════════════ -->
<!-- JavaScript                                                         -->
<!-- ═══════════════════════════════════════════════════════════════════ -->
<script>
// ── Chart.js instance ─────────────────────────────────────────────────
let equityChart = null;

// ── Helpers ───────────────────────────────────────────────────────────
function fmt$(v) {
    if (v == null || isNaN(v)) return '--';
    const sign = v >= 0 ? '+' : '';
    return sign + '$' + Math.abs(v).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

function fmtAbs$(v) {
    if (v == null || isNaN(v)) return '--';
    return '$' + Math.abs(v).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
}

function fmtPct(v) {
    if (v == null || isNaN(v)) return '0%';
    return (v * 100).toFixed(1) + '%';
}

function fmtTime(iso) {
    if (!iso) return '--';
    try { return new Date(iso).toLocaleTimeString(); }
    catch { return iso; }
}

function fmtDateTime(iso) {
    if (!iso) return '--';
    try {
        const d = new Date(iso);
        return d.toLocaleDateString() + ' ' + d.toLocaleTimeString();
    } catch { return iso; }
}

function fmtDuration(seconds) {
    if (!seconds || seconds < 0) return '--';
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (d > 0) return d + 'd ' + h + 'h ' + m + 'm';
    if (h > 0) return h + 'h ' + m + 'm ' + s + 's';
    if (m > 0) return m + 'm ' + s + 's';
    return s + 's';
}

function pnlColor(v) { return v >= 0 ? 'var(--green)' : 'var(--red)'; }
function pnlClass(v) { return v >= 0 ? 'green' : 'red'; }
function sidePill(side) {
    const s = (side || '').toUpperCase();
    const isLong = s === 'BUY' || s === 'LONG';
    return '<span class="pill ' + (isLong ? 'pill-long' : 'pill-short') + '">' + s + '</span>';
}

// ── Build equity chart ────────────────────────────────────────────────
function buildEquityChart(eqData) {
    const canvas = document.getElementById('equity-chart');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    const labels = eqData.map(d => {
        try { return new Date(d.timestamp).toLocaleDateString(undefined, {month:'short', day:'numeric'}); }
        catch { return ''; }
    });
    const values = eqData.map(d => d.equity);
    const dailyPnl = eqData.map(d => d.daily_pnl || 0);

    const isUp = values.length >= 2 && values[values.length - 1] >= values[0];
    const lineColor = isUp ? '#00e6a0' : '#ff4466';
    const fillColor = isUp ? 'rgba(0, 230, 160, 0.08)' : 'rgba(255, 68, 102, 0.08)';

    if (equityChart) {
        equityChart.data.labels = labels;
        equityChart.data.datasets[0].data = values;
        equityChart.data.datasets[0].borderColor = lineColor;
        equityChart.data.datasets[0].backgroundColor = fillColor;
        equityChart.update('none');
        return;
    }

    equityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Equity',
                data: values,
                borderColor: lineColor,
                backgroundColor: fillColor,
                borderWidth: 2,
                fill: true,
                tension: 0.3,
                pointRadius: 0,
                pointHitRadius: 10,
                pointHoverRadius: 4,
                pointHoverBackgroundColor: lineColor,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#1a1a2e',
                    borderColor: '#2a2a4a',
                    borderWidth: 1,
                    titleFont: { family: 'monospace', size: 11 },
                    bodyFont: { family: 'monospace', size: 11 },
                    callbacks: {
                        label: function(ctx) {
                            return 'Equity: $' + ctx.parsed.y.toLocaleString(undefined, {minimumFractionDigits:2});
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(28,28,48,0.5)', drawBorder: false },
                    ticks: { color: '#5e5e80', font: { size: 10, family: 'monospace' }, maxTicksLimit: 10 },
                },
                y: {
                    grid: { color: 'rgba(28,28,48,0.5)', drawBorder: false },
                    ticks: {
                        color: '#5e5e80',
                        font: { size: 10, family: 'monospace' },
                        callback: function(v) { return '$' + v.toLocaleString(); }
                    },
                }
            }
        }
    });
}

// ── Render strategy bars ──────────────────────────────────────────────
function renderStrategyBars(byStrategy) {
    const container = document.getElementById('strategy-bars');
    if (!byStrategy || Object.keys(byStrategy).length === 0) {
        container.innerHTML = '<div class="empty">No strategy data yet</div>';
        return;
    }

    const entries = Object.entries(byStrategy).sort((a, b) => b[1].pnl - a[1].pnl);
    const maxAbs = Math.max(...entries.map(([_, s]) => Math.abs(s.pnl)), 1);

    container.innerHTML = entries.map(([name, s]) => {
        const wr = s.trades > 0 ? (s.wins / s.trades) : 0;
        const barPct = Math.min((Math.abs(s.pnl) / maxAbs) * 100, 100);
        const barColor = s.pnl >= 0 ? 'var(--green)' : 'var(--red)';
        const wrLabel = (wr * 100).toFixed(0) + '% WR';
        return '<div class="strat-row">' +
            '<div class="strat-label" title="' + name + '">' + name + '</div>' +
            '<div class="strat-bar-track">' +
                '<div class="strat-bar-fill" style="width:' + barPct + '%;background:' + barColor + ';">' +
                    (barPct > 25 ? wrLabel : '') +
                '</div>' +
            '</div>' +
            '<div class="strat-pnl" style="color:' + pnlColor(s.pnl) + '">' + fmt$(s.pnl) + '</div>' +
        '</div>';
    }).join('');
}

// ── Main data loader ──────────────────────────────────────────────────
async function loadAll() {
    try {
        const [dataResp, healthResp] = await Promise.all([
            fetch('/api/data'),
            fetch('/api/health'),
        ]);

        const data = await dataResp.json();
        const healthInfo = await healthResp.json();

        const ds   = data.daily_summary        || {};
        const rt   = data.recent_trades         || [];
        const eq   = data.equity_curve          || [];
        const sp   = data.signal_performance    || {};
        const he   = data.health_events         || [];
        const ph   = data.performance_history   || [];

        // ── KPIs ──────────────────────────────────────────────────
        // Equity
        const lastEq = eq.length > 0 ? eq[eq.length - 1] : {};
        const equity = lastEq.equity || 0;
        document.getElementById('kpi-equity').textContent = '$' + equity.toLocaleString(undefined, {minimumFractionDigits:2, maximumFractionDigits:2});
        if (eq.length >= 2) {
            const prevEq = eq[0].equity || equity;
            const change = equity - prevEq;
            const changePct = prevEq > 0 ? ((change / prevEq) * 100).toFixed(2) : '0.00';
            const el = document.getElementById('kpi-equity-change');
            el.textContent = fmt$(change) + ' (' + changePct + '% 30d)';
            el.style.color = pnlColor(change);
        }

        // Daily PnL
        const pnl = ds.net_pnl || 0;
        const pnlEl = document.getElementById('kpi-pnl');
        pnlEl.textContent = fmt$(pnl);
        pnlEl.className = 'metric ' + pnlClass(pnl);
        document.getElementById('kpi-pnl-detail').textContent =
            (ds.total_trades || 0) + ' trades | $' + (ds.total_fees || 0).toFixed(2) + ' fees';

        // Win Rate
        const wr = (ds.win_rate || 0);
        const wrPct = wr * 100;
        const wrEl = document.getElementById('kpi-winrate');
        wrEl.textContent = wrPct.toFixed(1) + '%';
        wrEl.className = 'metric ' + (wrPct >= 50 ? 'green' : (wrPct > 0 ? 'red' : ''));
        document.getElementById('wr-bar').style.width = wrPct + '%';
        document.getElementById('wr-bar').style.background = wrPct >= 50 ? 'var(--green)' : 'var(--red)';
        document.getElementById('kpi-wl').textContent = (ds.wins || 0) + 'W / ' + (ds.losses || 0) + 'L';

        // Trades
        document.getElementById('kpi-trades').textContent = ds.total_trades || 0;
        const bestStrat = ds.best_strategy || '--';
        const worstStrat = ds.worst_strategy || '--';
        document.getElementById('kpi-best-worst').textContent = 'Best: ' + bestStrat;

        // Signal Score
        const avgScore = sp.avg_score || 0;
        document.getElementById('kpi-score').textContent = avgScore.toFixed(1);
        document.getElementById('score-bar').style.width = avgScore + '%';
        document.getElementById('kpi-score-detail').textContent =
            (sp.total || 0) + ' signals | WR ' + fmtPct(sp.win_rate || 0);

        // ── Equity chart ──────────────────────────────────────────
        if (eq.length >= 2) {
            buildEquityChart(eq);
        }

        // ── Open Positions ────────────────────────────────────────
        const positions = data.positions || [];
        const posBody = document.getElementById('positions-body');
        if (positions.length > 0) {
            posBody.innerHTML = positions.map(p => {
                const pnlVal = p.unrealized_pnl || p.pnl || 0;
                const holdSec = p.hold_time_s || 0;
                return '<tr>' +
                    '<td><strong>' + (p.symbol || '--') + '</strong></td>' +
                    '<td>' + sidePill(p.side) + '</td>' +
                    '<td>$' + (p.entry_price || p.entry || 0).toFixed(2) + '</td>' +
                    '<td class="' + (pnlVal >= 0 ? 'pos-pnl-positive' : 'pos-pnl-negative') + '">' + fmt$(pnlVal) + '</td>' +
                    '<td>' + (p.leverage || 1) + 'x</td>' +
                    '<td>' + fmtDuration(holdSec) + '</td>' +
                '</tr>';
            }).join('');
        } else {
            posBody.innerHTML = '<tr><td colspan="6" class="empty">No open positions</td></tr>';
        }

        // ── Signal Performance by Strategy ────────────────────────
        const byStrat = sp.by_strategy || {};
        const ssBody = document.getElementById('signal-strat-body');
        if (Object.keys(byStrat).length > 0) {
            ssBody.innerHTML = Object.entries(byStrat)
                .sort((a, b) => b[1].pnl - a[1].pnl)
                .map(([name, s]) =>
                    '<tr>' +
                    '<td><strong>' + name + '</strong></td>' +
                    '<td>' + s.trades + '</td>' +
                    '<td>' + (s.wins || 0) + '</td>' +
                    '<td><span class="pill ' + (s.win_rate >= 0.5 ? 'pill-win' : 'pill-loss') + '">' + (s.win_rate * 100).toFixed(1) + '%</span></td>' +
                    '<td style="color:' + pnlColor(s.pnl) + ';font-weight:600">' + fmt$(s.pnl) + '</td>' +
                    '<td>' + (s.avg_score || 0).toFixed(1) + '</td>' +
                    '</tr>'
                ).join('');
        } else {
            ssBody.innerHTML = '<tr><td colspan="6" class="empty">No signal data</td></tr>';
        }

        // ── Signal Performance by Symbol ──────────────────────────
        const bySym = sp.by_symbol || {};
        const symBody = document.getElementById('signal-sym-body');
        if (Object.keys(bySym).length > 0) {
            symBody.innerHTML = Object.entries(bySym)
                .sort((a, b) => b[1].pnl - a[1].pnl)
                .map(([sym, s]) =>
                    '<tr>' +
                    '<td><strong>' + sym + '</strong></td>' +
                    '<td>' + s.trades + '</td>' +
                    '<td>' + (s.wins || 0) + '</td>' +
                    '<td><span class="pill ' + (s.win_rate >= 0.5 ? 'pill-win' : 'pill-loss') + '">' + (s.win_rate * 100).toFixed(1) + '%</span></td>' +
                    '<td style="color:' + pnlColor(s.pnl) + ';font-weight:600">' + fmt$(s.pnl) + '</td>' +
                    '</tr>'
                ).join('');
        } else {
            symBody.innerHTML = '<tr><td colspan="5" class="empty">No signal data</td></tr>';
        }

        // ── Strategy Bars ─────────────────────────────────────────
        renderStrategyBars(ds.by_strategy || {});

        // ── Recent Trades ─────────────────────────────────────────
        const tBody = document.getElementById('trades-body');
        if (rt.length > 0) {
            tBody.innerHTML = rt.map(t =>
                '<tr>' +
                '<td>' + fmtDateTime(t.timestamp) + '</td>' +
                '<td><strong>' + (t.symbol || '--') + '</strong></td>' +
                '<td>' + sidePill(t.side) + '</td>' +
                '<td><span class="pill pill-action">' + (t.action || '--') + '</span></td>' +
                '<td>$' + (t.price || 0).toFixed(2) + '</td>' +
                '<td>' + (t.qty || 0) + '</td>' +
                '<td style="color:' + pnlColor(t.pnl || 0) + ';font-weight:600">' + fmt$(t.pnl || 0) + '</td>' +
                '<td style="color:var(--muted)">$' + (t.fee || 0).toFixed(4) + '</td>' +
                '<td style="color:var(--muted)">' + (t.strategy || '') + '</td>' +
                '</tr>'
            ).join('');
        } else {
            tBody.innerHTML = '<tr><td colspan="9" class="empty">No trades yet</td></tr>';
        }

        // ── Health Status ─────────────────────────────────────────
        const uptime = healthInfo.uptime_seconds || 0;
        document.getElementById('health-uptime').textContent = fmtDuration(uptime);
        document.getElementById('health-started').textContent = 'Started: ' + (healthInfo.started_at || '--');

        const lastHb = healthInfo.last_heartbeat || '--';
        document.getElementById('health-heartbeat').textContent = lastHb;
        if (healthInfo.heartbeat_age_s != null) {
            const age = healthInfo.heartbeat_age_s;
            const ageEl = document.getElementById('health-heartbeat-ago');
            ageEl.textContent = fmtDuration(age) + ' ago';
            ageEl.style.color = age > 300 ? 'var(--red)' : (age > 120 ? 'var(--yellow)' : 'var(--muted)');
        }

        const errCount = healthInfo.error_count || 0;
        const warnCount = healthInfo.warning_count || 0;
        const errEl = document.getElementById('health-errors');
        errEl.textContent = errCount;
        errEl.className = 'metric ' + (errCount > 0 ? 'red' : 'green');
        document.getElementById('health-warnings').textContent = warnCount + ' warnings';

        // Health events list
        const heList = document.getElementById('health-events-list');
        if (he.length > 0) {
            heList.innerHTML = he.slice(0, 30).map(e =>
                '<div class="health-item sev-' + (e.severity || 'INFO') + '">' +
                '<span class="health-type">' + (e.event_type || 'EVENT') + '</span>' +
                '<span class="health-time">' + fmtDateTime(e.timestamp) + '</span>' +
                '<br><span style="color:var(--muted)">' + (e.message || '').substring(0, 200) + '</span>' +
                '</div>'
            ).join('');
        } else {
            heList.innerHTML = '<div class="empty">No health events in the last 24h</div>';
        }

        // ── Overall health dot ────────────────────────────────────
        const dot = document.getElementById('health-dot');
        const label = document.getElementById('health-label');
        if (errCount > 0) {
            dot.className = 'dot dot-red';
            label.textContent = errCount + ' error' + (errCount > 1 ? 's' : '') + ' detected';
        } else if (warnCount > 0) {
            dot.className = 'dot dot-yellow';
            label.textContent = 'Warnings present';
        } else {
            dot.className = 'dot dot-green';
            label.textContent = 'Healthy';
        }

        // ── Last refresh time ─────────────────────────────────────
        document.getElementById('last-refresh').textContent = new Date().toLocaleTimeString();
        document.getElementById('uptime-display').textContent = 'Uptime: ' + fmtDuration(uptime);

    } catch (err) {
        console.error('Dashboard load error:', err);
        document.getElementById('health-dot').className = 'dot dot-red';
        document.getElementById('health-label').textContent = 'Connection error';
    }
}

// ── Initial load + auto-refresh ───────────────────────────────────────
loadAll();
setInterval(loadAll, 30000);
</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════════════════
# HTTP Handler
# ═══════════════════════════════════════════════════════════════════════════

class DashboardHandler(BaseHTTPRequestHandler):
    """Serves the dashboard HTML and JSON API endpoints."""

    # Attached externally so every request can reach bot state.
    bot_instance = None

    # Suppress default stderr request logging.
    def log_message(self, format, *args):  # noqa: A002
        logger.debug("HTTP %s", format % args)

    # ── Routing ────────────────────────────────────────────────────────
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]  # strip query string
        routes = {
            "/":               self._serve_dashboard,
            "/dashboard":      self._serve_dashboard,
            "/api/data":       self._serve_api_data,
            "/api/equity":     self._serve_equity_data,
            "/api/positions":  self._serve_positions,
            "/api/health":     self._serve_health,
        }
        handler = routes.get(path)
        if handler:
            handler()
        else:
            self.send_error(404, "Not Found")

    # ── HTML page ──────────────────────────────────────────────────────
    def _serve_dashboard(self):
        body = DASHBOARD_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # ── JSON helpers ───────────────────────────────────────────────────
    def _send_json(self, obj: Any, status: int = 200):
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # ── /api/data  (all-in-one) ────────────────────────────────────────
    def _serve_api_data(self):
        try:
            from data.db import get_dashboard_data
            data = get_dashboard_data()
            # Inject open positions from bot instance if available.
            data["positions"] = self._get_positions_list()
            self._send_json(data)
        except Exception as exc:
            logger.exception("Error serving /api/data")
            self._send_json({"error": str(exc)}, status=500)

    # ── /api/equity ────────────────────────────────────────────────────
    def _serve_equity_data(self):
        try:
            from data.db import get_equity_curve
            self._send_json(get_equity_curve(30))
        except Exception as exc:
            logger.exception("Error serving /api/equity")
            self._send_json({"error": str(exc)}, status=500)

    # ── /api/positions ─────────────────────────────────────────────────
    def _serve_positions(self):
        try:
            self._send_json(self._get_positions_list())
        except Exception as exc:
            logger.exception("Error serving /api/positions")
            self._send_json({"error": str(exc)}, status=500)

    # ── /api/health ────────────────────────────────────────────────────
    def _serve_health(self):
        try:
            from data.db import get_health_events
            events = get_health_events(24)
            error_count = sum(1 for e in events if e.get("severity") in ("ALERT", "ERROR"))
            warning_count = sum(1 for e in events if e.get("severity") == "WARNING")

            # Determine last heartbeat from health events
            heartbeats = [
                e for e in events
                if e.get("event_type", "").upper() in ("HEARTBEAT", "LOOP_TICK", "CYCLE")
            ]
            last_hb = heartbeats[0]["timestamp"] if heartbeats else None
            hb_age = None
            if last_hb:
                try:
                    hb_dt = datetime.fromisoformat(last_hb.replace("Z", "+00:00"))
                    hb_age = (datetime.now(timezone.utc) - hb_dt).total_seconds()
                except Exception:
                    pass

            started_at = datetime.fromtimestamp(_START_TIME, tz=timezone.utc).isoformat()
            uptime = time.time() - _START_TIME

            self._send_json({
                "uptime_seconds": uptime,
                "started_at": started_at,
                "last_heartbeat": last_hb or "--",
                "heartbeat_age_s": hb_age,
                "error_count": error_count,
                "warning_count": warning_count,
                "total_events_24h": len(events),
            })
        except Exception as exc:
            logger.exception("Error serving /api/health")
            self._send_json({"error": str(exc)}, status=500)

    # ── Position extraction from bot ───────────────────────────────────
    def _get_positions_list(self) -> list:
        """Try to pull open positions from the bot instance.

        The bot may expose positions in several ways depending on the
        engine implementation.  We try the most common attributes and
        gracefully return an empty list if nothing is available.
        """
        bot = DashboardHandler.bot_instance
        if bot is None:
            return []

        positions_raw = None

        # Try common attribute names.
        for attr in ("open_positions", "positions", "active_positions"):
            obj = getattr(bot, attr, None)
            if obj is not None:
                if callable(obj):
                    try:
                        positions_raw = obj()
                    except Exception:
                        pass
                else:
                    positions_raw = obj
                if positions_raw:
                    break

        # Also try nested engine/position_manager.
        if not positions_raw:
            engine = getattr(bot, "engine", None) or getattr(bot, "trading_engine", None)
            if engine:
                pm = getattr(engine, "position_manager", None) or engine
                for attr in ("open_positions", "positions", "get_positions"):
                    obj = getattr(pm, attr, None)
                    if obj is not None:
                        if callable(obj):
                            try:
                                positions_raw = obj()
                            except Exception:
                                pass
                        else:
                            positions_raw = obj
                        if positions_raw:
                            break

        if not positions_raw:
            return []

        # Normalise to list of dicts.
        result = []
        now = time.time()

        if isinstance(positions_raw, dict):
            items = positions_raw.values() if positions_raw else []
        elif isinstance(positions_raw, (list, tuple)):
            items = positions_raw
        else:
            return []

        for pos in items:
            if isinstance(pos, dict):
                entry_ts = pos.get("open_time") or pos.get("entry_time") or pos.get("timestamp")
                hold_time = 0
                if entry_ts:
                    try:
                        if isinstance(entry_ts, (int, float)):
                            hold_time = now - entry_ts
                        else:
                            dt = datetime.fromisoformat(str(entry_ts).replace("Z", "+00:00"))
                            hold_time = now - dt.timestamp()
                    except Exception:
                        pass

                result.append({
                    "symbol":          pos.get("symbol", "???"),
                    "side":            pos.get("side", "LONG"),
                    "entry_price":     pos.get("entry_price") or pos.get("entry") or 0,
                    "unrealized_pnl":  pos.get("unrealized_pnl") or pos.get("pnl") or 0,
                    "leverage":        pos.get("leverage", 1),
                    "hold_time_s":     hold_time,
                })
            else:
                # Object with attributes
                try:
                    entry_ts = getattr(pos, "open_time", None) or getattr(pos, "entry_time", None)
                    hold_time = 0
                    if entry_ts:
                        if isinstance(entry_ts, (int, float)):
                            hold_time = now - entry_ts
                        else:
                            dt = datetime.fromisoformat(str(entry_ts).replace("Z", "+00:00"))
                            hold_time = now - dt.timestamp()
                    result.append({
                        "symbol":          getattr(pos, "symbol", "???"),
                        "side":            getattr(pos, "side", "LONG"),
                        "entry_price":     getattr(pos, "entry_price", 0) or getattr(pos, "entry", 0),
                        "unrealized_pnl":  getattr(pos, "unrealized_pnl", 0) or getattr(pos, "pnl", 0),
                        "leverage":        getattr(pos, "leverage", 1),
                        "hold_time_s":     hold_time,
                    })
                except Exception:
                    pass

        return result


# ═══════════════════════════════════════════════════════════════════════════
# Dashboard Server (threaded)
# ═══════════════════════════════════════════════════════════════════════════

class DashboardServer:
    """Manages the HTTP server lifecycle in a daemon thread."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = int(os.getenv("DASHBOARD_PORT", str(port)))
        self.server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def start(self, bot_instance=None):
        """Start the dashboard server in a background daemon thread.

        Parameters
        ----------
        bot_instance : optional
            The running bot object.  If provided, the dashboard can
            reflect live open positions and other runtime state.
        """
        DashboardHandler.bot_instance = bot_instance

        self.server = HTTPServer((self.host, self.port), DashboardHandler)
        self._thread = threading.Thread(
            target=self.server.serve_forever,
            name="dashboard-http",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Dashboard running at http://%s:%s",
            self.host if self.host != "0.0.0.0" else "localhost",
            self.port,
        )

    def stop(self):
        """Gracefully shut down the server."""
        if self.server:
            self.server.shutdown()
            logger.info("Dashboard server stopped.")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


# ═══════════════════════════════════════════════════════════════════════════
# Singleton accessor
# ═══════════════════════════════════════════════════════════════════════════

_singleton: Optional[DashboardServer] = None
_singleton_lock = threading.Lock()


def get_dashboard_server(host: str = "0.0.0.0", port: int = 8080) -> DashboardServer:
    """Return (and optionally create) a singleton DashboardServer."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = DashboardServer(host=host, port=port)
        return _singleton


# ═══════════════════════════════════════════════════════════════════════════
# Standalone entry point
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Load .env if available.
    try:
        from dotenv import load_dotenv
        env_path = Path(_BOT_DIR).parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
        else:
            load_dotenv()
    except ImportError:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
    )

    # Initialise the database so tables exist.
    try:
        from data.db import init_db
        init_db()
    except Exception as exc:
        logger.warning("Could not initialise DB: %s", exc)

    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    srv = DashboardServer(port=port)
    srv.start()

    print(f"NunuIRL Dashboard running at http://localhost:{port}")
    print("Press Ctrl+C to stop.\n")

    try:
        # Block forever (server runs in daemon thread).
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        srv.stop()
