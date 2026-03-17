"""
Lightweight web dashboard for the NunuIRL trading bot.

Uses Python's built-in http.server (zero external dependencies).
Serves a single-page HTML dashboard with auto-refreshing data via
fetch() calls to JSON API endpoints backed by the SQLite data layer.

Features:
  v4.2 — Professional Trading Intelligence Terminal
  - 7-tab layout: Overview | Charts & Zones | Signals | Trades | Analytics | System | Learn
  - TradingView Lightweight Charts with Monte Carlo zone overlays
  - Educational tooltips on every concept (click ? icons)
  - Live positions with price range bars (10s refresh)
  - Market awareness heatmap (regime, bias, danger zones)
  - Signal pipeline funnel visualization
  - Rejected signals / "What If" section
  - Copy Trade Intelligence (LLM insights when active)
  - Equity curve, daily PnL bars, strategy breakdown
  - Circuit breaker status, go-live gates
  - Health monitoring

Usage:
    # As a background thread inside the bot:
    from dashboard import get_dashboard_server
    srv = get_dashboard_server()
    srv.start(bot_instance=bot)

    # Standalone:
    cd bot && python -m dashboard
"""

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any, Dict, List, Optional
from pathlib import Path
from urllib.parse import urlparse, parse_qs

_BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)

logger = logging.getLogger("bot.dashboard")
_START_TIME = time.time()


# ═══════════════════════════════════════════════════════════════════════════
# HTML Dashboard (inline single-page app) — v4.2
# ═══════════════════════════════════════════════════════════════════════════

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<title>NunuIRL Trading Intelligence</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js" onerror="window._chartJsFailed=true"></script>
<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js" onerror="window._lwcFailed=true"></script>
<style>
:root {
  --bg: #060611;
  --bg2: #0a0a1a;
  --card: #0f0f1e;
  --card-hover: #13132a;
  --border: #1a1a35;
  --border-bright: #2a2a50;
  --text: #e0e0f0;
  --text-dim: #9090b0;
  --muted: #5e5e80;
  --green: #00e6a0;
  --green-dim: rgba(0,230,160,0.12);
  --red: #ff4466;
  --red-dim: rgba(255,68,102,0.12);
  --blue: #4488ff;
  --blue-dim: rgba(68,136,255,0.12);
  --yellow: #ffc444;
  --yellow-dim: rgba(255,196,68,0.12);
  --purple: #a366ff;
  --purple-dim: rgba(163,102,255,0.12);
  --cyan: #22d3ee;
  --cyan-dim: rgba(34,211,238,0.12);
  --orange: #ff9100;
  --radius: 10px;
  --radius-sm: 6px;
  --shadow-sm: 0 2px 8px rgba(0,0,0,0.3);
  --shadow-md: 0 4px 20px rgba(0,0,0,0.4);
  --shadow-glow-green: 0 0 20px rgba(0,230,160,0.08);
  --shadow-glow-red: 0 0 20px rgba(255,68,102,0.08);
  --transition: 0.2s ease;
}

*, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }

body {
  font-family: 'SF Mono', 'Cascadia Code', 'Fira Code', 'JetBrains Mono', Consolas, monospace;
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
  min-height: 100vh;
  line-height: 1.5;
  overflow-x: hidden;
}

a { color: var(--blue); text-decoration: none; }
a:hover { text-decoration: underline; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-bright); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--muted); }

/* ── Layout ── */
.app { display: flex; flex-direction: column; min-height: 100vh; }

.top-bar {
  position: sticky; top: 0; z-index: 100;
  background: rgba(6,6,17,0.92);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
  display: flex; justify-content: space-between; align-items: center;
  height: 52px;
}

.top-bar .brand {
  font-size: 16px; font-weight: 800; letter-spacing: -0.5px;
  background: linear-gradient(135deg, var(--cyan), var(--blue), var(--purple));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}

.top-bar .brand span { font-weight: 400; opacity: 0.7; }

.top-bar .status-strip {
  display: flex; gap: 20px; align-items: center; font-size: 11px; color: var(--muted);
}

.top-bar .equity-ticker {
  font-size: 15px; font-weight: 700; letter-spacing: -0.3px;
  padding: 4px 14px; border-radius: 6px;
  background: var(--card); border: 1px solid var(--border);
}

/* ── Status Dots ── */
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-right: 5px; vertical-align: middle; }
.dot-green { background: var(--green); box-shadow: 0 0 8px var(--green); }
.dot-yellow { background: var(--yellow); box-shadow: 0 0 8px var(--yellow); }
.dot-red { background: var(--red); box-shadow: 0 0 8px var(--red); }

/* ── Tab Navigation ── */
.tab-nav {
  display: flex; gap: 0;
  background: var(--bg2);
  border-bottom: 1px solid var(--border);
  padding: 0 24px;
  overflow-x: auto;
}

.tab-btn {
  padding: 12px 22px;
  font-size: 12px; font-weight: 600; letter-spacing: 0.5px; text-transform: uppercase;
  color: var(--muted); cursor: pointer;
  border: none; background: none;
  border-bottom: 2px solid transparent;
  transition: color var(--transition), border-color var(--transition);
  font-family: inherit;
  white-space: nowrap;
}

.tab-btn:hover { color: var(--text-dim); }
.tab-btn.active {
  color: var(--cyan);
  border-bottom-color: var(--cyan);
}

.tab-btn .tab-icon { margin-right: 6px; font-size: 14px; }

.tab-content { display: none; padding: 20px 24px; animation: fadeIn 0.25s ease; }
.tab-content.active { display: block; }
@keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: translateY(0); } }

/* ── Cards ── */
.card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px 20px;
  position: relative;
  transition: border-color var(--transition), box-shadow var(--transition);
}

.card:hover { border-color: var(--border-bright); }

.card h3 {
  font-size: 10px; text-transform: uppercase; letter-spacing: 1.2px;
  color: var(--muted); margin-bottom: 12px; font-weight: 700;
  display: flex; align-items: center; gap: 8px;
}

.card-hero {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
  box-shadow: var(--shadow-glow-green);
}

.card-hero h3 {
  font-size: 12px; text-transform: uppercase; letter-spacing: 0.8px;
  color: var(--cyan); margin-bottom: 14px; font-weight: 700;
  display: flex; align-items: center; gap: 8px;
}

/* ── Grids ── */
.grid-5 { display: grid; grid-template-columns: repeat(5,1fr); gap: 12px; margin-bottom: 20px; }
.grid-4 { display: grid; grid-template-columns: repeat(4,1fr); gap: 14px; margin-bottom: 20px; }
.grid-3 { display: grid; grid-template-columns: repeat(3,1fr); gap: 16px; margin-bottom: 20px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
.full-width { margin-bottom: 20px; }

/* ── Metrics ── */
.metric { font-size: 28px; font-weight: 800; letter-spacing: -0.5px; line-height: 1.1; }
.metric-sub { font-size: 11px; color: var(--muted); margin-top: 5px; }
.green { color: var(--green); } .red { color: var(--red); } .blue { color: var(--blue); }
.yellow { color: var(--yellow); } .purple { color: var(--purple); } .cyan { color: var(--cyan); }

/* ── Progress Bars ── */
.bar-track { width: 100%; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; margin-top: 10px; }
.bar-fill { height: 100%; border-radius: 3px; transition: width 0.6s ease; }

/* ── Tables ── */
table { width: 100%; border-collapse: collapse; }
th { text-align: left; padding: 10px 12px; font-size: 10px; text-transform: uppercase; letter-spacing: 0.8px; color: var(--muted); border-bottom: 1px solid var(--border); font-weight: 700; white-space: nowrap; }
td { padding: 9px 12px; border-bottom: 1px solid rgba(26,26,53,0.5); font-size: 12px; white-space: nowrap; }
tr:hover td { background: rgba(255,255,255,0.015); }
.scroll-y { max-height: 420px; overflow-y: auto; }

/* ── Pills / Badges ── */
.pill { display: inline-block; padding: 3px 10px; border-radius: 5px; font-size: 10px; font-weight: 700; letter-spacing: 0.3px; }
.pill-long { background: var(--green-dim); color: var(--green); }
.pill-short { background: var(--red-dim); color: var(--red); }
.pill-win { background: var(--green-dim); color: var(--green); }
.pill-loss { background: var(--red-dim); color: var(--red); }
.pill-action { background: var(--blue-dim); color: var(--blue); }
.pill-neutral { background: rgba(94,94,128,0.15); color: var(--muted); }

.gate-pill { display: inline-block; padding: 3px 10px; border-radius: 5px; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.3px; }
.gate-hard { background: var(--red-dim); color: var(--red); border: 1px solid rgba(255,68,102,0.2); }
.gate-soft { background: var(--yellow-dim); color: var(--yellow); border: 1px solid rgba(255,196,68,0.2); }
.gate-info { background: var(--blue-dim); color: var(--blue); border: 1px solid rgba(68,136,255,0.2); }

/* ── Heatmap ── */
.heatmap-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
.heatmap-cell {
  background: var(--bg2); border: 1px solid var(--border); border-left: 4px solid var(--muted);
  border-radius: var(--radius-sm); padding: 14px;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
  cursor: pointer;
}
.heatmap-cell:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); }
.heatmap-cell .sym-name { font-size: 15px; font-weight: 800; margin-bottom: 6px; }
.regime-pill { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.3px; }
.opportunity-glow { box-shadow: 0 0 16px rgba(0,230,160,0.12); border-color: rgba(0,230,160,0.25); }
.danger-glow { box-shadow: 0 0 16px rgba(255,68,102,0.12); border-color: rgba(255,68,102,0.25); }

/* ── Educational Tooltip System ── */
.info-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 16px; height: 16px; border-radius: 50%;
  background: var(--border); color: var(--muted);
  font-size: 9px; font-weight: 800; cursor: pointer;
  transition: all var(--transition);
  border: none; font-family: inherit;
  line-height: 1;
}
.info-btn:hover { background: var(--blue-dim); color: var(--blue); transform: scale(1.1); }

.edu-modal-overlay {
  display: none; position: fixed; inset: 0; z-index: 1000;
  background: rgba(0,0,0,0.6); backdrop-filter: blur(4px);
  justify-content: center; align-items: center;
}
.edu-modal-overlay.visible { display: flex; animation: fadeIn 0.2s ease; }

.edu-modal {
  background: var(--card); border: 1px solid var(--border-bright);
  border-radius: 14px; padding: 28px 32px; max-width: 520px; width: 90%;
  max-height: 80vh; overflow-y: auto;
  box-shadow: 0 20px 60px rgba(0,0,0,0.5);
}

.edu-modal .edu-icon { font-size: 32px; margin-bottom: 12px; }
.edu-modal .edu-title { font-size: 18px; font-weight: 800; margin-bottom: 8px; color: var(--text); }
.edu-modal .edu-short { font-size: 14px; color: var(--cyan); margin-bottom: 16px; font-weight: 600; }
.edu-modal .edu-detail { font-size: 13px; color: var(--text-dim); line-height: 1.7; }
.edu-modal .edu-detail p { margin-bottom: 12px; }
.edu-modal .edu-detail strong { color: var(--text); }
.edu-modal .edu-close {
  position: absolute; top: 16px; right: 16px;
  background: none; border: none; color: var(--muted); font-size: 18px; cursor: pointer;
  font-family: inherit;
}
.edu-modal .edu-close:hover { color: var(--text); }

/* ── Chart Container ── */
.chart-container { position: relative; width: 100%; border-radius: var(--radius-sm); overflow: hidden; }
.chart-container.large { height: 420px; }
.chart-container.medium { height: 280px; }
.chart-container.small { height: 200px; }
.chart-wrap { position: relative; height: 250px; }
.chart-wrap canvas { width: 100% !important; height: 100% !important; }

/* ── Symbol Selector ── */
.symbol-tabs {
  display: flex; gap: 6px; margin-bottom: 14px; flex-wrap: wrap;
}
.symbol-tab {
  padding: 6px 14px; border-radius: 6px; font-size: 12px; font-weight: 700;
  background: var(--bg2); border: 1px solid var(--border); color: var(--muted);
  cursor: pointer; transition: all var(--transition); font-family: inherit;
}
.symbol-tab:hover { border-color: var(--border-bright); color: var(--text-dim); }
.symbol-tab.active { background: var(--cyan-dim); border-color: var(--cyan); color: var(--cyan); }

/* ── Zone Legend ── */
.zone-legend {
  display: flex; gap: 16px; flex-wrap: wrap; padding: 10px 0; font-size: 11px;
}
.zone-legend-item { display: flex; align-items: center; gap: 6px; color: var(--text-dim); cursor: pointer; }
.zone-legend-dot { width: 10px; height: 10px; border-radius: 3px; }

/* ── Signal Cards ── */
.signal-card {
  background: var(--bg2); border: 1px solid var(--border); border-radius: var(--radius-sm);
  padding: 16px; margin-bottom: 10px;
  transition: border-color var(--transition);
}
.signal-card:hover { border-color: var(--border-bright); }
.signal-card .signal-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.signal-card .signal-sym { font-size: 16px; font-weight: 800; }
.signal-card .signal-conf { font-size: 24px; font-weight: 800; }

/* ── Confluence Meter ── */
.confluence-meter {
  display: flex; gap: 3px; margin: 8px 0;
}
.confluence-bar {
  height: 6px; flex: 1; border-radius: 3px; background: var(--border);
  transition: background var(--transition);
}
.confluence-bar.filled { background: var(--green); }
.confluence-bar.partial { background: var(--yellow); }

/* ── Price Range Bar ── */
.price-range-bar {
  position: relative; height: 24px; background: var(--border); border-radius: 4px;
  margin: 8px 0; overflow: visible;
}
.price-range-sl { position: absolute; top: 0; height: 100%; background: var(--red-dim); border-radius: 4px 0 0 4px; }
.price-range-tp { position: absolute; top: 0; height: 100%; background: var(--green-dim); border-radius: 0 4px 4px 0; }
.price-range-current {
  position: absolute; top: -3px; width: 4px; height: 30px;
  background: var(--cyan); border-radius: 2px;
  box-shadow: 0 0 6px var(--cyan);
}
.price-range-label {
  position: absolute; top: -18px; font-size: 9px; font-weight: 700;
  transform: translateX(-50%); white-space: nowrap;
}

/* ── Strategy Bars ── */
.strat-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.strat-label { width: 140px; font-size: 11px; color: var(--text); text-align: right; overflow: hidden; text-overflow: ellipsis; }
.strat-bar-track { flex: 1; height: 16px; background: var(--border); border-radius: 5px; overflow: hidden; }
.strat-bar-fill { height: 100%; border-radius: 5px; transition: width 0.4s ease; display: flex; align-items: center; padding-left: 8px; font-size: 10px; font-weight: 700; color: #fff; }
.strat-pnl { width: 90px; font-size: 12px; text-align: right; font-weight: 700; }

/* ── Health Events ── */
.health-item { padding: 10px 14px; border-left: 3px solid var(--border); margin-bottom: 6px; font-size: 11px; border-radius: 0 6px 6px 0; background: rgba(255,255,255,0.01); }
.health-item.sev-INFO { border-left-color: var(--blue); }
.health-item.sev-WARNING { border-left-color: var(--yellow); }
.health-item.sev-ALERT, .health-item.sev-ERROR { border-left-color: var(--red); }

/* ── Copy Trade ── */
.copytrade-card { background: var(--card); border: 1px solid var(--border); border-left: 4px solid var(--purple); border-radius: var(--radius); padding: 18px; }
.copytrade-card h3 { font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--purple); margin-bottom: 10px; font-weight: 700; }

/* ── Pipeline Funnel ── */
.funnel-step {
  display: flex; align-items: center; gap: 12px; margin-bottom: 6px;
}
.funnel-bar-track { flex: 1; height: 28px; background: var(--border); border-radius: 6px; overflow: hidden; position: relative; }
.funnel-bar-fill { height: 100%; border-radius: 6px; display: flex; align-items: center; padding: 0 12px; font-size: 11px; font-weight: 700; transition: width 0.6s ease; }
.funnel-label { width: 130px; font-size: 11px; font-weight: 600; text-align: right; color: var(--text-dim); }
.funnel-count { width: 50px; font-size: 13px; font-weight: 800; text-align: left; }

/* ── Circuit Breaker ── */
.cb-gauge { display: flex; flex-direction: column; gap: 12px; }
.cb-row { display: flex; align-items: center; gap: 12px; }
.cb-label { width: 140px; font-size: 11px; color: var(--text-dim); }
.cb-bar { flex: 1; height: 10px; background: var(--border); border-radius: 5px; overflow: hidden; }
.cb-fill { height: 100%; border-radius: 5px; transition: width 0.5s ease; }
.cb-value { width: 80px; font-size: 12px; font-weight: 700; text-align: right; }

/* ── Animations ── */
@keyframes pulse { 0%,100% { opacity: 0.3; transform: scale(0.8); } 50% { opacity: 1; transform: scale(1.2); } }
@keyframes danger-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
@keyframes glow-pulse { 0%,100% { box-shadow: 0 0 10px rgba(34,211,238,0.1); } 50% { box-shadow: 0 0 20px rgba(34,211,238,0.2); } }
.refresh-pulse { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--blue); margin-right: 6px; animation: pulse 1.5s ease infinite; }
.danger-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--red); margin-left: 6px; animation: danger-pulse 1.2s ease-in-out infinite; }

/* ── Empty States ── */
.empty { color: var(--muted); padding: 24px; text-align: center; font-size: 12px; }
.empty-icon { font-size: 28px; margin-bottom: 8px; opacity: 0.5; }
.empty-msg { margin-top: 4px; font-size: 11px; }

/* ── Section Titles ── */
.section-title { font-size: 12px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin: 24px 0 12px 0; display: flex; align-items: center; gap: 8px; }

/* ── Footer ── */
.footer { text-align: center; color: var(--muted); font-size: 10px; padding: 24px 0 12px 0; border-top: 1px solid var(--border); margin-top: 24px; }

/* ── Learn Tab — Course Dashboard ── */
.lesson-item:hover { background: var(--bg2); }

/* Course Layout */
.course-layout { display:flex; gap:0; min-height:calc(100vh - 120px); margin:-20px -24px; }
.course-sidebar { width:260px; min-width:260px; background:var(--bg2); border-right:1px solid var(--border); padding:16px 0; overflow-y:auto; max-height:calc(100vh - 120px); position:sticky; top:0; }
.course-main { flex:1; padding:24px 28px; overflow-y:auto; max-width:calc(100% - 260px); }

.course-nav-section { padding:0 12px; margin-bottom:8px; }
.course-nav-label { font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:1.2px; color:var(--muted); padding:12px 12px 6px; }
.course-nav-item { display:flex; align-items:center; gap:10px; padding:9px 12px; border-radius:6px; cursor:pointer; font-size:12px; color:var(--text-dim); transition:all 0.15s; border:1px solid transparent; margin-bottom:2px; }
.course-nav-item:hover { background:var(--card); color:var(--text); }
.course-nav-item.active { background:var(--cyan-dim); color:var(--cyan); border-color:rgba(34,211,238,0.15); font-weight:700; }
.course-nav-item .nav-num { width:22px; height:22px; border-radius:50%; background:var(--border); display:flex; align-items:center; justify-content:center; font-size:10px; font-weight:800; color:var(--muted); flex-shrink:0; }
.course-nav-item.active .nav-num { background:var(--cyan); color:var(--bg); }
.course-nav-item.completed .nav-num { background:var(--green); color:var(--bg); }
.course-nav-icon { font-size:16px; flex-shrink:0; width:22px; text-align:center; }

/* Course Page Header */
.course-page-header { margin-bottom:24px; }
.course-page-header h1 { font-size:24px; font-weight:800; margin-bottom:6px; letter-spacing:-0.5px; }
.course-page-header .subtitle { font-size:13px; color:var(--text-dim); line-height:1.6; }

/* Progress Bar */
.progress-wrap { margin:16px 0; }
.progress-bar-outer { width:100%; height:8px; background:var(--border); border-radius:4px; overflow:hidden; }
.progress-bar-fill { height:100%; background:linear-gradient(90deg, var(--cyan), var(--green)); border-radius:4px; transition:width 0.5s ease; }
.progress-label { font-size:11px; color:var(--muted); margin-top:4px; }

/* Course Cards Grid */
.course-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:16px; margin:16px 0; }
.course-card { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:20px; cursor:pointer; transition:all 0.2s; position:relative; overflow:hidden; }
.course-card:hover { border-color:var(--border-bright); transform:translateY(-2px); box-shadow:var(--shadow-md); }
.course-card .card-icon { font-size:32px; margin-bottom:12px; }
.course-card .card-title { font-size:15px; font-weight:800; margin-bottom:6px; }
.course-card .card-desc { font-size:12px; color:var(--text-dim); line-height:1.6; }
.course-card .card-tag { position:absolute; top:12px; right:12px; font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; padding:3px 8px; border-radius:4px; }

/* Step Navigation */
.step-nav { display:flex; justify-content:space-between; margin-top:32px; padding-top:20px; border-top:1px solid var(--border); }
.step-nav-btn { padding:10px 20px; border-radius:6px; font-size:12px; font-weight:700; cursor:pointer; font-family:inherit; border:1px solid var(--border); background:var(--card); color:var(--text-dim); transition:all 0.2s; }
.step-nav-btn:hover { border-color:var(--cyan); color:var(--cyan); }
.step-nav-btn.primary { background:var(--cyan); color:var(--bg); border-color:var(--cyan); }
.step-nav-btn.primary:hover { opacity:0.9; }

/* Quiz Styles */
.quiz-container { margin:20px 0; }
.quiz-question { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:20px; margin-bottom:16px; }
.quiz-question h4 { font-size:13px; font-weight:700; margin-bottom:14px; color:var(--text); }
.quiz-option { display:flex; align-items:center; gap:10px; padding:10px 14px; border:1px solid var(--border); border-radius:6px; margin-bottom:8px; cursor:pointer; transition:all 0.15s; font-size:12px; }
.quiz-option:hover { border-color:var(--cyan-dim); background:var(--bg2); }
.quiz-option.selected { border-color:var(--cyan); background:var(--cyan-dim); }
.quiz-option.correct { border-color:var(--green); background:var(--green-dim); }
.quiz-option.incorrect { border-color:var(--red); background:var(--red-dim); }
.quiz-radio { width:16px; height:16px; border-radius:50%; border:2px solid var(--border-bright); flex-shrink:0; transition:all 0.15s; }
.quiz-option.selected .quiz-radio { border-color:var(--cyan); background:var(--cyan); box-shadow:inset 0 0 0 3px var(--card); }
.quiz-submit { padding:10px 24px; background:var(--cyan); color:var(--bg); border:none; border-radius:6px; font-size:12px; font-weight:700; cursor:pointer; font-family:inherit; margin-top:8px; transition:opacity 0.2s; }
.quiz-submit:hover { opacity:0.9; }
.quiz-result { padding:12px 16px; border-radius:6px; margin-top:12px; font-size:12px; font-weight:600; display:none; }
.quiz-result.quiz-pass, .quiz-result.pass { background:var(--green-dim); color:var(--green); border:1px solid rgba(0,230,160,0.2); display:block; }
.quiz-result.quiz-fail, .quiz-result.fail { background:var(--red-dim); color:var(--red); border:1px solid rgba(255,68,102,0.2); display:block; }

/* Calculator */
.calc-container { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:20px; margin:16px 0; }
.calc-row { display:flex; gap:16px; margin-bottom:14px; flex-wrap:wrap; }
.calc-field { flex:1; min-width:180px; }
.calc-field label { display:block; font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; color:var(--muted); margin-bottom:6px; }
.calc-field input, .calc-field select { width:100%; padding:8px 12px; background:var(--bg2); border:1px solid var(--border); border-radius:6px; color:var(--text); font-family:inherit; font-size:13px; outline:none; }
.calc-field input:focus, .calc-field select:focus { border-color:var(--cyan); }
.calc-btn { padding:10px 24px; background:var(--cyan); color:var(--bg); border:none; border-radius:6px; font-size:12px; font-weight:700; cursor:pointer; font-family:inherit; }
.calc-results { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:12px; margin-top:16px; }
.calc-result-item { background:var(--bg2); border-radius:6px; padding:12px; text-align:center; }
.calc-result-item .label { font-size:10px; color:var(--muted); text-transform:uppercase; margin-bottom:4px; }
.calc-result-item .value { font-size:18px; font-weight:800; }

/* Checklist */
.checklist { margin:16px 0; }
.checklist-item { display:flex; align-items:flex-start; gap:10px; padding:10px 14px; border-bottom:1px solid var(--border); font-size:12px; cursor:pointer; transition:background 0.15s; }
.checklist-item:hover { background:var(--bg2); }
.checklist-item:last-child { border-bottom:none; }
.checklist-box { width:18px; height:18px; border:2px solid var(--border-bright); border-radius:4px; flex-shrink:0; margin-top:1px; display:flex; align-items:center; justify-content:center; transition:all 0.15s; font-size:11px; }
.checklist-item.checked .checklist-box { background:var(--green); border-color:var(--green); color:var(--bg); }

/* Info Boxes */
.info-box { padding:16px; border-radius:var(--radius); margin:16px 0; font-size:12px; line-height:1.7; }
.info-box.tip { background:var(--cyan-dim); border-left:3px solid var(--cyan); }
.info-box.warning { background:var(--yellow-dim); border-left:3px solid var(--yellow); }
.info-box.danger { background:var(--red-dim); border-left:3px solid var(--red); }
.info-box.success { background:var(--green-dim); border-left:3px solid var(--green); }
.info-box strong { color:var(--text); }

/* Strategy Metric Cards */
.metric-row { display:flex; gap:12px; margin:16px 0; flex-wrap:wrap; }
.metric-card { flex:1; min-width:120px; background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:14px; text-align:center; }
.metric-card .metric-val { font-size:22px; font-weight:800; }
.metric-card .metric-label { font-size:10px; color:var(--muted); text-transform:uppercase; margin-top:4px; }

/* Indicator Phase Box */
.phase-box { display:flex; gap:3px; margin:16px 0; }
.phase-item { flex:1; padding:14px 8px; text-align:center; border-radius:6px; font-size:11px; font-weight:600; position:relative; }
.phase-item.active-phase { outline:2px solid var(--cyan); outline-offset:2px; }
.phase-item .phase-num { font-size:18px; font-weight:800; display:block; margin-bottom:4px; }

/* FAQ Accordion */
.faq-item { border:1px solid var(--border); border-radius:var(--radius); margin-bottom:8px; overflow:hidden; }
.faq-q { padding:14px 18px; cursor:pointer; font-size:13px; font-weight:700; display:flex; justify-content:space-between; align-items:center; background:var(--card); transition:background 0.15s; }
.faq-q:hover { background:var(--card-hover); }
.faq-a { padding:0 18px; max-height:0; overflow:hidden; transition:all 0.3s ease; font-size:12px; color:var(--text-dim); line-height:1.7; }
.faq-item.open .faq-a { padding:14px 18px; max-height:2000px; }
.faq-arrow { transition:transform 0.3s; color:var(--muted); }
.faq-item.open .faq-arrow { transform:rotate(180deg); }

/* Dictionary */
.dict-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(320px,1fr)); gap:12px; }
.dict-card { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:16px; transition:border-color 0.2s; }
.dict-card:hover { border-color:var(--border-bright); }
.dict-card .term { font-size:14px; font-weight:800; margin-bottom:4px; }
.dict-card .cat-badge { font-size:9px; font-weight:700; text-transform:uppercase; padding:2px 8px; border-radius:10px; display:inline-block; margin-bottom:8px; }
.dict-card .def { font-size:12px; color:var(--text-dim); line-height:1.6; }
.dict-card .example { font-size:11px; color:var(--muted); margin-top:8px; font-style:italic; }
.dict-card .related { display:flex; gap:4px; flex-wrap:wrap; margin-top:8px; }
.dict-card .related span { font-size:9px; padding:2px 6px; background:var(--bg2); border-radius:4px; color:var(--text-dim); }

/* Video Card */
.video-card { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:20px; margin:16px 0; display:flex; align-items:center; gap:16px; cursor:pointer; transition:all 0.2s; }
.video-card:hover { border-color:var(--cyan); transform:translateY(-1px); }
.video-card .play-icon { width:48px; height:48px; border-radius:50%; background:var(--cyan); display:flex; align-items:center; justify-content:center; font-size:20px; flex-shrink:0; color:var(--bg); }

/* Indicator Cards */
.indicator-card { background:var(--card); border:1px solid var(--border); border-radius:var(--radius); padding:16px; }
.indicator-card h4 { font-size:13px; font-weight:800; margin-bottom:10px; }
.indicator-card .param-row { display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid var(--border); font-size:11px; }
.indicator-card .param-row:last-child { border-bottom:none; }

/* Peak Indicator */
.peak-indicator { display:flex; align-items:center; gap:12px; padding:12px; background:var(--bg2); border-radius:6px; margin-bottom:8px; }
.peak-indicator .pi-name { flex:1; font-size:12px; font-weight:600; }
.peak-indicator .pi-status { font-size:11px; font-weight:700; padding:3px 10px; border-radius:10px; }

/* Responsive overrides */
@media(max-width:900px) {
  .course-sidebar { display:none; }
  .course-main { max-width:100%; padding:16px; }
  .course-layout { margin:-14px -12px; }
}
@media(max-width:600px) {
  .metric-row { flex-direction:column; }
  .calc-row { flex-direction:column; }
  .dict-grid { grid-template-columns:1fr; }
}

/* ── Toast Notifications ── */
.toast-container { position:fixed; top:60px; right:20px; z-index:10000; display:flex; flex-direction:column; gap:8px; pointer-events:none; }
.toast { pointer-events:auto; padding:12px 18px; border-radius:8px; font-size:12px; font-weight:600; color:var(--text); background:var(--card); border:1px solid var(--border); box-shadow:var(--shadow-md); transform:translateX(120%); opacity:0; transition:all 0.3s ease; max-width:360px; display:flex; align-items:center; gap:10px; }
.toast.show { transform:translateX(0); opacity:1; }
.toast-success { border-left:4px solid var(--green); }
.toast-error { border-left:4px solid var(--red); }
.toast-warning { border-left:4px solid var(--yellow); }
.toast-info { border-left:4px solid var(--blue); }
.toast-icon { font-size:16px; flex-shrink:0; }
.toast-body { flex:1; }
.toast-title { font-weight:800; font-size:11px; text-transform:uppercase; margin-bottom:2px; }
.toast-msg { font-size:11px; color:var(--text-dim); }
.toast-close { background:none; border:none; color:var(--muted); cursor:pointer; font-size:16px; padding:0 0 0 8px; }

/* ── Sortable Tables ── */
th.sortable { cursor:pointer; user-select:none; position:relative; transition:color var(--transition); }
th.sortable:hover { color:var(--cyan); }
th.sortable::after { content:'⇅'; font-size:9px; margin-left:4px; opacity:0.3; }
th.sort-asc::after { content:'↑'; opacity:1; color:var(--cyan); }
th.sort-desc::after { content:'↓'; opacity:1; color:var(--cyan); }

/* ── Countdown Timer ── */
.countdown-wrap { display:flex; align-items:center; gap:6px; }
.countdown-bar { width:50px; height:3px; background:var(--border); border-radius:2px; overflow:hidden; }
.countdown-fill { height:100%; background:var(--cyan); border-radius:2px; transition:width 1s linear; }
.countdown-text { font-size:9px; color:var(--muted); min-width:18px; }

/* ── PnL Calendar Heatmap ── */
.pnl-calendar { display:flex; flex-direction:column; gap:2px; }
.pnl-cal-row { display:flex; gap:2px; align-items:center; }
.pnl-cal-label { width:24px; font-size:9px; color:var(--muted); text-align:right; padding-right:4px; flex-shrink:0; }
.cal-cell { width:14px; height:14px; border-radius:2px; position:relative; cursor:pointer; transition:transform 0.1s; }
.cal-cell:hover { transform:scale(1.6); z-index:10; outline:1px solid var(--cyan); }
.cal-tooltip { position:absolute; bottom:calc(100% + 8px); left:50%; transform:translateX(-50%); background:var(--card); border:1px solid var(--border); border-radius:6px; padding:8px 12px; font-size:10px; white-space:nowrap; z-index:100; pointer-events:none; opacity:0; transition:opacity 0.15s; box-shadow:var(--shadow-md); }
.cal-cell:hover .cal-tooltip { opacity:1; }
.cal-month-label { font-size:9px; color:var(--muted); text-align:center; }

/* ── Export Button ── */
.btn-export { padding:4px 12px; font-size:10px; font-weight:700; background:var(--bg2); border:1px solid var(--border); color:var(--cyan); border-radius:4px; cursor:pointer; font-family:inherit; text-transform:uppercase; letter-spacing:0.5px; transition:all var(--transition); }
.btn-export:hover { background:var(--cyan-dim); border-color:var(--cyan); }
.btn-group { display:flex; gap:6px; align-items:center; }

/* ── Fullscreen Chart ── */
.btn-fullscreen { position:absolute; top:8px; right:8px; padding:4px 8px; font-size:11px; background:var(--bg2); border:1px solid var(--border); color:var(--text-dim); border-radius:4px; cursor:pointer; font-family:inherit; z-index:10; transition:all var(--transition); }
.btn-fullscreen:hover { color:var(--cyan); border-color:var(--cyan); }
.chart-fullscreen { position:fixed!important; top:0; left:0; width:100vw!important; height:100vh!important; z-index:9999; background:var(--bg); padding:20px; margin:0!important; border-radius:0!important; }
.chart-fullscreen .btn-fullscreen { top:20px; right:20px; font-size:14px; padding:8px 14px; }

/* ── Position Expand ── */
.pos-expand-row td { padding:0!important; }
.pos-detail { background:var(--bg2); padding:14px 20px; border-top:1px dashed var(--border); font-size:11px; }
.pos-detail-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(180px,1fr)); gap:12px; }
.pos-detail-item { display:flex; flex-direction:column; gap:2px; }
.pos-detail-label { color:var(--muted); font-size:10px; text-transform:uppercase; letter-spacing:0.5px; }
.pos-detail-value { color:var(--text); font-weight:700; }
tr.pos-row { cursor:pointer; transition:background var(--transition); }
tr.pos-row:hover { background:var(--card-hover); }

/* ── Streak Badge ── */
.streak-badge { display:inline-flex; align-items:center; gap:4px; padding:3px 10px; border-radius:12px; font-size:11px; font-weight:700; }
.streak-win { background:var(--green-dim); color:var(--green); }
.streak-loss { background:var(--red-dim); color:var(--red); }

/* ── Quick Stats Row ── */
.quick-stats { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:16px; }
.quick-stat { display:flex; align-items:center; gap:6px; padding:6px 14px; background:var(--card); border:1px solid var(--border); border-radius:20px; font-size:11px; white-space:nowrap; }
.quick-stat-label { color:var(--muted); }
.quick-stat-value { font-weight:800; }

/* ── Keyboard Shortcut Hints ── */
.kb-hint { font-size:8px; color:var(--muted); background:var(--bg2); border:1px solid var(--border); border-radius:3px; padding:1px 4px; margin-left:3px; opacity:0; transition:opacity 0.2s; vertical-align:middle; }
.tab-btn:hover .kb-hint { opacity:0.8; }

/* ── Skeleton Loading ── */
@keyframes skeleton-pulse { 0%,100% { opacity:0.15; } 50% { opacity:0.35; } }
.skeleton { background:linear-gradient(90deg,var(--border) 25%,var(--card-hover) 50%,var(--border) 75%); background-size:200% 100%; animation:skeleton-pulse 1.5s ease-in-out infinite; border-radius:4px; }
.skeleton-text { height:12px; margin-bottom:6px; width:80%; }
.skeleton-metric { height:28px; width:120px; margin-bottom:4px; }
.skeleton-card { height:60px; border-radius:var(--radius); }

/* ── Latency Indicator ── */
.latency-dot { display:inline-block; width:6px; height:6px; border-radius:50%; margin-right:4px; }
.latency-good { background:var(--green); }
.latency-ok { background:var(--yellow); }
.latency-bad { background:var(--red); }

/* ── Keyboard Shortcut Modal ── */
.kb-modal { display:none; position:fixed; top:50%; left:50%; transform:translate(-50%,-50%); background:var(--card); border:1px solid var(--border-bright); border-radius:var(--radius); padding:24px; z-index:10001; min-width:340px; box-shadow:var(--shadow-md); }
.kb-modal.visible { display:block; }
.kb-modal-overlay { display:none; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.5); z-index:10000; }
.kb-modal-overlay.visible { display:block; }
.kb-row { display:flex; justify-content:space-between; padding:6px 0; border-bottom:1px solid var(--border); font-size:12px; }
.kb-key { background:var(--bg2); border:1px solid var(--border); border-radius:4px; padding:2px 8px; font-weight:700; font-size:11px; color:var(--cyan); min-width:28px; text-align:center; }

/* ── Responsive ── */
@media(max-width:1400px) { .grid-5 { grid-template-columns: repeat(3,1fr); } .grid-4 { grid-template-columns: repeat(2,1fr); } }
@media(max-width:1000px) { .grid-5 { grid-template-columns: repeat(2,1fr); } .grid-3,.grid-2 { grid-template-columns: 1fr; } .heatmap-grid { grid-template-columns: repeat(auto-fill,minmax(180px,1fr)); } .tab-btn { padding: 10px 14px; font-size: 11px; } .toast-container { right:10px; left:10px; } .kb-hint { display:none; } }
@media(max-width:600px) { .grid-5,.grid-4 { grid-template-columns: 1fr; } .heatmap-grid { grid-template-columns: 1fr; } .top-bar { padding: 0 12px; } .tab-content { padding: 14px 12px; } .top-bar .equity-ticker { display: none; } .quick-stats { gap:6px; } .quick-stat { padding:4px 10px; font-size:10px; } }
</style>
</head>
<body>
<div class="app">

<!-- ═══ Top Bar ═══ -->
<div class="top-bar">
  <div class="brand">NunuIRL <span>Trading Intelligence</span></div>
  <div class="status-strip">
    <span class="equity-ticker" id="top-equity">$--</span>
    <span><span class="dot dot-green" id="health-dot"></span><span id="health-label">Connecting...</span></span>
    <span id="uptime-display">--</span>
    <span><span class="refresh-pulse"></span><span id="last-refresh">--</span></span>
    <span class="countdown-wrap"><span class="latency-dot latency-good" id="latency-dot" title="API latency"></span><span class="countdown-bar"><span class="countdown-fill" id="countdown-fill" style="width:100%"></span></span><span class="countdown-text" id="countdown-text">30s</span></span>
  </div>
</div>

<!-- ═══ Tab Navigation ═══ -->
<div class="tab-nav">
  <button class="tab-btn active" data-tab="overview"><span class="tab-icon">&#9670;</span>Overview<span class="kb-hint">1</span></button>
  <button class="tab-btn" data-tab="charts"><span class="tab-icon">&#9636;</span>Charts &amp; Zones<span class="kb-hint">2</span></button>
  <button class="tab-btn" data-tab="signals"><span class="tab-icon">&#9889;</span>Signals<span class="kb-hint">3</span></button>
  <button class="tab-btn" data-tab="trades"><span class="tab-icon">&#9733;</span>Trades<span class="kb-hint">4</span></button>
  <button class="tab-btn" data-tab="analytics"><span class="tab-icon">&#9776;</span>Analytics<span class="kb-hint">5</span></button>
  <button class="tab-btn" data-tab="system"><span class="tab-icon">&#9881;</span>System<span class="kb-hint">6</span></button>
  <button class="tab-btn" data-tab="learn"><span class="tab-icon">&#127891;</span>Learn<span class="kb-hint">7</span></button>
</div>

<!-- ════════════════════════════════════════════════════════════════════ -->
<!-- TAB 1: OVERVIEW -->
<!-- ════════════════════════════════════════════════════════════════════ -->
<div class="tab-content active" id="tab-overview">

  <!-- KPI Cards -->
  <div class="grid-5">
    <div class="card">
      <h3>Equity <button class="info-btn" onclick="showEdu('equity')">?</button></h3>
      <div class="metric blue" id="kpi-equity">--</div>
      <div class="metric-sub" id="kpi-equity-change">--</div>
    </div>
    <div class="card">
      <h3>Daily PnL <button class="info-btn" onclick="showEdu('daily_pnl')">?</button></h3>
      <div class="metric" id="kpi-pnl">$0.00</div>
      <div class="metric-sub" id="kpi-pnl-detail">0 trades | $0.00 fees</div>
    </div>
    <div class="card">
      <h3>Win Rate <button class="info-btn" onclick="showEdu('win_rate')">?</button></h3>
      <div class="metric" id="kpi-winrate">0%</div>
      <div class="bar-track"><div class="bar-fill" id="wr-bar" style="width:0%;background:var(--green)"></div></div>
      <div class="metric-sub" id="kpi-wl">0W / 0L</div>
    </div>
    <div class="card">
      <h3>Open Positions <button class="info-btn" onclick="showEdu('open_positions')">?</button></h3>
      <div class="metric cyan" id="kpi-open-positions">0</div>
      <div class="metric-sub" id="kpi-open-positions-sub">--</div>
    </div>
    <div class="card">
      <h3>Unrealized PnL <button class="info-btn" onclick="showEdu('unrealized_pnl')">?</button></h3>
      <div class="metric" id="kpi-unrealized-pnl">$0.00</div>
      <div class="metric-sub" id="kpi-unrealized-pnl-sub">across all positions</div>
    </div>
  </div>

  <!-- Quick Stats Strip -->
  <div class="quick-stats" id="quick-stats">
    <div class="quick-stat"><span class="quick-stat-label">Streak:</span><span class="quick-stat-value" id="qs-streak">--</span></div>
    <div class="quick-stat"><span class="quick-stat-label">Best Trade:</span><span class="quick-stat-value" id="qs-best-trade">--</span></div>
    <div class="quick-stat"><span class="quick-stat-label">Worst Trade:</span><span class="quick-stat-value" id="qs-worst-trade">--</span></div>
    <div class="quick-stat"><span class="quick-stat-label">Avg Hold:</span><span class="quick-stat-value" id="qs-avg-hold">--</span></div>
    <div class="quick-stat"><span class="quick-stat-label">Profit Factor:</span><span class="quick-stat-value" id="qs-profit-factor">--</span></div>
    <div class="quick-stat"><span class="quick-stat-label">Signals Today:</span><span class="quick-stat-value" id="qs-signals-today">--</span></div>
  </div>

  <!-- Live Positions Hero -->
  <div class="full-width">
    <div class="card-hero" style="animation: glow-pulse 3s ease infinite;">
      <h3>Live Positions <button class="info-btn" onclick="showEdu('positions')">?</button></h3>
      <div class="scroll-y">
        <table>
          <thead><tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Current</th><th>Range</th><th>Unrealized PnL</th><th>PnL%</th><th>Leverage</th><th>State</th><th>Hold Time</th><th>Profile</th></tr></thead>
          <tbody id="positions-body"><tr><td colspan="11" class="empty"><div class="empty-icon">&#128269;</div>No open positions<div class="empty-msg">The bot is scanning for opportunities...</div></td></tr></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- System Activity Status -->
  <div class="full-width">
    <div class="card" style="border-left:3px solid var(--cyan);">
      <h3 style="display:flex;align-items:center;gap:8px;">System Activity <span id="system-activity-dot" style="width:8px;height:8px;border-radius:50%;background:var(--green);display:inline-block;"></span></h3>
      <div id="system-activity-status" style="font-size:12px;color:var(--text-dim);padding:8px 0;">
        <span>Scanning for high-probability setups... The system only trades when all conditions align.</span>
      </div>
    </div>
  </div>

  <!-- Market Heatmap -->
  <div class="full-width">
    <div class="card">
      <h3>Market Awareness <button class="info-btn" onclick="showEdu('market_regime')">?</button></h3>
      <div class="heatmap-grid" id="heatmap-grid"><div class="empty" style="grid-column:1/-1;"><div class="empty-icon">&#127758;</div>Loading market data...</div></div>
    </div>
  </div>

  <!-- Signal Feed + Rejection Summary (2-col) -->
  <div class="grid-2">
    <div class="card">
      <h3>Signal Pipeline <button class="info-btn" onclick="showEdu('signal_pipeline')">?</button></h3>
      <div id="pipeline-funnel"><div class="empty"><div class="empty-icon">&#9889;</div>Signal pipeline loading...</div></div>
    </div>
    <div class="card">
      <h3>Recent Rejections <button class="info-btn" onclick="showEdu('rejections')">?</button></h3>
      <div class="scroll-y" style="max-height:300px;">
        <table>
          <thead><tr><th>Symbol</th><th>Side</th><th>Blocked By</th><th>Reason</th></tr></thead>
          <tbody id="rejections-body-mini"><tr><td colspan="4" class="empty">No rejections</td></tr></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Portfolio Correlation Heatmap -->
  <div class="full-width">
    <div class="card">
      <h3>Portfolio Correlation Matrix <button class="info-btn" onclick="showEdu('correlation')">?</button></h3>
      <div id="correlation-heatmap"><div class="empty"><div class="empty-icon">&#128200;</div>Correlation data loading...<div class="empty-msg">Shows how correlated your watched symbols are</div></div></div>
    </div>
  </div>

</div>

<!-- ════════════════════════════════════════════════════════════════════ -->
<!-- TAB 2: CHARTS & ZONES -->
<!-- ════════════════════════════════════════════════════════════════════ -->
<div class="tab-content" id="tab-charts">

  <!-- Symbol Selector -->
  <div class="symbol-tabs" id="chart-symbol-tabs"></div>

  <!-- Zone Legend -->
  <div class="zone-legend">
    <div class="zone-legend-item"><div class="zone-legend-dot" style="background:#00e6a066;"></div>Deep Buy Zone <button class="info-btn" onclick="showEdu('deep_buy_zone')">?</button></div>
    <div class="zone-legend-item"><div class="zone-legend-dot" style="background:#00e6a033;"></div>Regular Buy Zone <button class="info-btn" onclick="showEdu('regular_buy_zone')">?</button></div>
    <div class="zone-legend-item"><div class="zone-legend-dot" style="background:#ff446633;"></div>Regular Sell Zone <button class="info-btn" onclick="showEdu('regular_sell_zone')">?</button></div>
    <div class="zone-legend-item"><div class="zone-legend-dot" style="background:#ff446666;"></div>Safe Sell Zone <button class="info-btn" onclick="showEdu('safe_sell_zone')">?</button></div>
    <div class="zone-legend-item"><div class="zone-legend-dot" style="background:var(--cyan);"></div>SMA20 <button class="info-btn" onclick="showEdu('sma')">?</button></div>
    <div class="zone-legend-item"><div class="zone-legend-dot" style="background:var(--purple);"></div>Entry Levels</div>
  </div>

  <!-- Main Chart -->
  <div class="card" style="padding:14px;position:relative;" id="chart-card">
    <button class="btn-fullscreen" onclick="toggleChartFullscreen()" title="Toggle fullscreen (F)">&#x26F6; Fullscreen</button>
    <div class="chart-container large" id="main-chart-container"></div>
  </div>

  <!-- Zone Details + Signal Context (below chart) -->
  <div class="grid-2" style="margin-top:16px;">
    <div class="card">
      <h3>Zone Analysis <button class="info-btn" onclick="showEdu('monte_carlo')">?</button></h3>
      <div id="zone-details"><div class="empty">Select a symbol to view zone analysis</div></div>
    </div>
    <div class="card">
      <h3>Active Signals on Chart <button class="info-btn" onclick="showEdu('signal_confluence')">?</button></h3>
      <div id="chart-signals"><div class="empty">Signal data will appear here</div></div>
    </div>
  </div>

</div>

<!-- ════════════════════════════════════════════════════════════════════ -->
<!-- TAB 3: SIGNALS -->
<!-- ════════════════════════════════════════════════════════════════════ -->
<div class="tab-content" id="tab-signals">

  <!-- ═══ LIVE MARKET INTELLIGENCE PANEL ═══ -->
  <div class="section-title">Live Market Intelligence <span style="font-size:10px;color:var(--green);margin-left:8px;">&#9679; Auto-refreshing</span></div>

  <!-- Market Regime Overview -->
  <div id="market-intel-regimes" class="grid-3" style="margin-bottom:16px;">
    <div class="card" style="text-align:center;padding:16px;"><div class="empty" style="font-size:11px;">Loading market regimes...</div></div>
  </div>

  <!-- Signal Pipeline Status + Why No Trades -->
  <div class="grid-2" style="margin-bottom:16px;">
    <div class="card">
      <h3 style="display:flex;align-items:center;gap:8px;">Signal Pipeline Status</h3>
      <div id="intel-pipeline-status"><div class="empty" style="font-size:11px;">Loading...</div></div>
    </div>
    <div class="card">
      <h3 style="display:flex;align-items:center;gap:8px;">Why No Trades?</h3>
      <div id="intel-why-no-trades"><div class="empty" style="font-size:11px;">Loading...</div></div>
    </div>
  </div>

  <!-- Strategy Consensus + Risk Status -->
  <div class="grid-2" style="margin-bottom:16px;">
    <div class="card">
      <h3>Strategy Consensus</h3>
      <div id="intel-strategy-consensus"><div class="empty" style="font-size:11px;">Loading strategy weights...</div></div>
    </div>
    <div class="card">
      <h3>Circuit Breaker & Risk</h3>
      <div id="intel-risk-status"><div class="empty" style="font-size:11px;">Loading risk data...</div></div>
    </div>
  </div>

  <!-- LLM Agent Intelligence -->
  <div class="card" style="margin-bottom:16px;">
    <h3>AI Agent Intelligence</h3>
    <div id="intel-agent-insights"><div class="empty"><div class="empty-icon">&#129302;</div>Loading agent data...<div class="empty-msg">Multi-agent insights will appear here when available</div></div></div>
  </div>

  <!-- Best Opportunities (Highest Confidence Rejections) -->
  <div class="card" style="margin-bottom:24px;">
    <h3>Best Current Opportunities <span style="font-size:10px;color:var(--text-dim);font-weight:400;">(highest confidence rejected signals)</span></h3>
    <div id="intel-best-opportunities"><div class="empty" style="font-size:11px;">Loading opportunity data...</div></div>
  </div>

  <hr style="border:none;border-top:1px solid var(--border);margin:24px 0;">

  <!-- Active Signals -->
  <div class="section-title">Active Signals <button class="info-btn" onclick="showEdu('signals')">?</button></div>
  <div id="active-signals-list"><div class="empty"><div class="empty-icon">&#128225;</div>No active signals right now<div class="empty-msg">The bot evaluates signals each scan cycle</div></div></div>

  <!-- Signal Pipeline Funnel (Full) -->
  <div class="section-title" style="margin-top:28px;">Signal Pipeline Funnel <button class="info-btn" onclick="showEdu('signal_pipeline')">?</button></div>
  <div class="card">
    <div id="pipeline-funnel-full"><div class="empty">Loading pipeline data...</div></div>
  </div>

  <!-- Rejected Signals Full Table -->
  <div class="section-title" style="margin-top:28px;">Rejected Signals / What If <button class="info-btn" onclick="showEdu('rejections')">?</button></div>
  <div class="card">
    <div class="scroll-y">
      <table>
        <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Confidence</th><th>Strategy</th><th>Blocked By</th><th>Reason</th><th>What If PnL</th></tr></thead>
        <tbody id="rejections-body"><tr><td colspan="8" class="empty">No rejected signals</td></tr></tbody>
      </table>
    </div>
  </div>

  <!-- Missed Trade Alpha -->
  <div class="section-title" style="margin-top:28px;">Missed Trade Alpha <button class="info-btn" onclick="showEdu('missed_alpha')">?</button></div>
  <div class="grid-3">
    <div class="card"><h3>Alpha Left on Table</h3><div class="metric green" id="missed-alpha-total">$0.00</div><div class="metric-sub">from rejected signals that would have won</div></div>
    <div class="card"><h3>Missed Wins</h3><div class="metric yellow" id="missed-win-count">0</div><div class="metric-sub" id="missed-win-pct">0% of rejections profitable</div></div>
    <div class="card"><h3>Correctly Rejected</h3><div class="metric cyan" id="missed-correct-count">0</div><div class="metric-sub">saved from losing trades</div></div>
  </div>
  <div class="card">
    <div class="scroll-y" style="max-height:300px;">
      <table>
        <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Confidence</th><th>Blocked By</th><th>Would Have Won?</th><th>Missed PnL</th></tr></thead>
        <tbody id="missed-trades-body"><tr><td colspan="7" class="empty">Loading missed trade data...</td></tr></tbody>
      </table>
    </div>
  </div>

  <!-- Copy Trade Intelligence -->
  <div class="section-title" style="margin-top:28px;">AI Intelligence <button class="info-btn" onclick="showEdu('llm_agents')">?</button></div>
  <div class="copytrade-card">
    <h3>Multi-Agent Insights</h3>
    <div id="copytrade-content"><div class="empty"><div class="empty-icon">&#129302;</div>LLM Intelligence Offline<div class="empty-msg">Enable multi-agent system (LLM_MULTI_AGENT=true) to activate AI-powered trade analysis</div></div></div>
  </div>

</div>

<!-- ════════════════════════════════════════════════════════════════════ -->
<!-- TAB 4: TRADES -->
<!-- ════════════════════════════════════════════════════════════════════ -->
<div class="tab-content" id="tab-trades">

  <!-- Trade Stats Summary -->
  <div class="grid-4" id="trade-stats-cards">
    <div class="card"><h3>Total Trades</h3><div class="metric" id="ts-total">0</div></div>
    <div class="card"><h3>Profit Factor</h3><div class="metric" id="ts-pf">--</div></div>
    <div class="card"><h3>Avg Win</h3><div class="metric green" id="ts-avg-win">--</div></div>
    <div class="card"><h3>Avg Loss</h3><div class="metric red" id="ts-avg-loss">--</div></div>
  </div>

  <!-- Recent Trades Table -->
  <div class="card">
    <h3 style="display:flex;justify-content:space-between;align-items:center;">
      <span>Recent Trades <button class="info-btn" onclick="showEdu('trades')">?</button></span>
      <div class="btn-group">
        <button class="btn-export" onclick="exportTrades('csv')" title="Export as CSV">&#8681; CSV</button>
        <button class="btn-export" onclick="exportTrades('json')" title="Export as JSON">&#8681; JSON</button>
      </div>
    </h3>
    <div class="scroll-y" style="max-height:500px;">
      <table>
        <thead><tr><th class="sortable" data-sort="time">Time</th><th class="sortable" data-sort="symbol">Symbol</th><th class="sortable" data-sort="side">Side</th><th>Action</th><th class="sortable" data-sort="price">Price</th><th class="sortable" data-sort="pnl">PnL</th><th>Strategy</th></tr></thead>
        <tbody id="trades-body"><tr><td colspan="7" class="empty"><div class="empty-icon">&#128203;</div>No trades yet<div class="empty-msg">Trades will appear here once the bot starts executing</div></td></tr></tbody>
      </table>
    </div>
  </div>

  <!-- Trade Outcome Breakdown -->
  <div class="grid-2" style="margin-top:16px;">
    <div class="card">
      <h3>Outcome Distribution <button class="info-btn" onclick="showEdu('trade_outcomes')">?</button></h3>
      <div id="outcome-distribution"><div class="empty">No outcome data yet</div></div>
    </div>
    <div class="card">
      <h3>PnL by Exit Type</h3>
      <div id="outcome-pnl-table"><div class="empty">No outcome data yet</div></div>
    </div>
  </div>

  <!-- Performance by Strategy + Symbol -->
  <div class="grid-2" style="margin-top:16px;">
    <div class="card">
      <h3>Performance by Strategy (7d) <button class="info-btn" onclick="showEdu('strategy_performance')">?</button></h3>
      <div class="scroll-y"><table><thead><tr><th>Strategy</th><th>Trades</th><th>Wins</th><th>Win Rate</th><th>PnL</th><th>Avg Score</th></tr></thead><tbody id="signal-strat-body"><tr><td colspan="6" class="empty">Loading...</td></tr></tbody></table></div>
    </div>
    <div class="card">
      <h3>Performance by Symbol (7d)</h3>
      <div class="scroll-y"><table><thead><tr><th>Symbol</th><th>Trades</th><th>Wins</th><th>Win Rate</th><th>PnL</th></tr></thead><tbody id="signal-sym-body"><tr><td colspan="5" class="empty">Loading...</td></tr></tbody></table></div>
    </div>
  </div>

</div>

<!-- ════════════════════════════════════════════════════════════════════ -->
<!-- TAB 5: ANALYTICS -->
<!-- ════════════════════════════════════════════════════════════════════ -->
<div class="tab-content" id="tab-analytics">

  <!-- Equity Curve -->
  <div class="card">
    <h3>Equity Curve (30d) <button class="info-btn" onclick="showEdu('equity_curve')">?</button></h3>
    <div class="chart-wrap" style="height:300px;"><canvas id="equity-chart"></canvas></div>
  </div>

  <!-- Strategy Breakdown -->
  <div class="grid-2" style="margin-top:16px;">
    <div class="card">
      <h3>Strategy Breakdown (Today) <button class="info-btn" onclick="showEdu('ensemble')">?</button></h3>
      <div id="strategy-bars"><div class="empty">No strategy data yet</div></div>
    </div>
    <div class="card">
      <h3>Strategy Weights <button class="info-btn" onclick="showEdu('strategy_weights')">?</button></h3>
      <div id="strategy-weights"><div class="empty">Strategy weights loading...</div></div>
    </div>
  </div>

  <!-- Daily PnL History -->
  <div class="card" style="margin-top:16px;">
    <h3>Daily PnL History <button class="info-btn" onclick="showEdu('daily_pnl')">?</button></h3>
    <div class="chart-wrap" style="height:200px;"><canvas id="daily-pnl-chart"></canvas></div>
  </div>

  <!-- PnL Calendar Heatmap -->
  <div class="card" style="margin-top:16px;">
    <h3 style="display:flex;justify-content:space-between;align-items:center;">
      <span>PnL Calendar (90d) <button class="info-btn" onclick="showEdu('daily_pnl')">?</button></span>
      <div style="display:flex;gap:12px;align-items:center;font-size:10px;color:var(--muted);">
        <span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:rgba(255,68,102,0.6);"></span>Loss</span>
        <span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:var(--border);"></span>$0</span>
        <span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:2px;background:rgba(0,230,160,0.6);"></span>Profit</span>
      </div>
    </h3>
    <div id="pnl-calendar" style="margin-top:12px;overflow-x:auto;"><div class="empty"><div class="empty-icon">&#128197;</div>PnL calendar loading...</div></div>
  </div>

  <!-- Strategy Fingerprint Heatmaps -->
  <div class="section-title" style="margin-top:28px;">Strategy Fingerprints <button class="info-btn" onclick="showEdu('strategy_fingerprints')">?</button></div>
  <div class="grid-2">
    <div class="card">
      <h3>Strategy x Symbol Win Rate</h3>
      <div id="fingerprint-symbol" class="scroll-y"><div class="empty">Loading strategy fingerprints...</div></div>
    </div>
    <div class="card">
      <h3>Strategy x Regime Win Rate</h3>
      <div id="fingerprint-regime" class="scroll-y"><div class="empty">Loading strategy fingerprints...</div></div>
    </div>
  </div>

  <!-- Regime Transition Timeline -->
  <div class="section-title" style="margin-top:28px;">Regime Transitions <button class="info-btn" onclick="showEdu('regime_transitions')">?</button></div>
  <div class="card">
    <h3>Regime Timeline (7d)</h3>
    <div id="regime-timeline" style="overflow-x:auto;"><div class="empty"><div class="empty-icon">&#127758;</div>Regime transition data loading...</div></div>
  </div>

  <!-- Confidence Calibration -->
  <div class="card" style="margin-top:16px;">
    <h3>Confidence Calibration <button class="info-btn" onclick="showEdu('calibration')">?</button></h3>
    <div id="calibration-chart-container"><div class="empty"><div class="empty-icon">&#127919;</div>Calibration data loading...<div class="empty-msg">Compares predicted confidence vs actual win rate</div></div></div>
  </div>

</div>

<!-- ════════════════════════════════════════════════════════════════════ -->
<!-- TAB 6: SYSTEM -->
<!-- ════════════════════════════════════════════════════════════════════ -->
<div class="tab-content" id="tab-system">

  <!-- Health Status -->
  <div class="grid-3">
    <div class="card"><h3>Bot Uptime</h3><div class="metric cyan" id="health-uptime">--</div><div class="metric-sub" id="health-started">--</div></div>
    <div class="card"><h3>Last Heartbeat</h3><div class="metric" id="health-heartbeat" style="font-size:18px;">--</div><div class="metric-sub" id="health-heartbeat-ago">--</div></div>
    <div class="card"><h3>Errors (24h)</h3><div class="metric" id="health-errors">0</div><div class="metric-sub" id="health-warnings">0 warnings</div></div>
  </div>

  <!-- Circuit Breaker + Risk -->
  <div class="grid-2">
    <div class="card">
      <h3>Circuit Breakers <button class="info-btn" onclick="showEdu('circuit_breaker')">?</button></h3>
      <div id="cb-status"><div class="empty">Circuit breaker data loading...</div></div>
    </div>
    <div class="card">
      <h3>Go-Live Gates <button class="info-btn" onclick="showEdu('go_live_gates')">?</button></h3>
      <div id="gates-status"><div class="empty">Gate data loading...</div></div>
    </div>
  </div>

  <!-- Agent Decision Pipeline -->
  <div class="card">
    <h3>Agent Decision Pipeline <button class="info-btn" onclick="showEdu('llm_agents')">?</button></h3>
    <div id="agent-pipeline"><div class="empty"><div class="empty-icon">&#129302;</div>Agent pipeline data loading...<div class="empty-msg">Shows last decision from each specialist agent</div></div></div>
  </div>

  <!-- LLM Insight Journal -->
  <div class="card" style="margin-top:16px;">
    <h3>LLM Insight Journal <button class="info-btn" onclick="showEdu('insight_journal')">?</button></h3>
    <div style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap;" id="insight-filters">
      <button class="symbol-tab active" onclick="filterInsights('all')">All</button>
      <button class="symbol-tab" onclick="filterInsights('strategy')">Strategy</button>
      <button class="symbol-tab" onclick="filterInsights('symbol')">Symbol</button>
      <button class="symbol-tab" onclick="filterInsights('regime')">Regime</button>
      <button class="symbol-tab" onclick="filterInsights('risk')">Risk</button>
      <button class="symbol-tab" onclick="filterInsights('timing')">Timing</button>
    </div>
    <div class="scroll-y" style="max-height:400px;" id="insight-journal-list"><div class="empty"><div class="empty-icon">&#128218;</div>No insights yet<div class="empty-msg">LLM insights will appear as the bot learns from trades</div></div></div>
  </div>

  <!-- Health Events -->
  <div class="card" style="margin-top:16px;">
    <h3>Recent Health Events</h3>
    <div class="scroll-y" id="health-events-list"><div class="empty">No health events</div></div>
  </div>

</div>

<!-- ════════════════════════════════════════════════════════════════════ -->
<!-- TAB 7: LEARN -->
<!-- ════════════════════════════════════════════════════════════════════ -->
<div class="tab-content" id="tab-learn">
  <div class="course-layout">
    <!-- Sidebar Navigation -->
    <div class="course-sidebar" id="course-sidebar">
      <div style="padding:8px 16px 12px;border-bottom:1px solid var(--border);margin-bottom:8px;">
        <div style="font-size:14px;font-weight:800;background:linear-gradient(135deg,var(--cyan),var(--green));-webkit-background-clip:text;-webkit-text-fill-color:transparent;">Nunu's Masterclass</div>
        <div style="font-size:10px;color:var(--muted);margin-top:2px;">Master the art of trading</div>
        <div class="progress-wrap" style="margin:8px 0 0;">
          <div class="progress-bar-outer" style="height:5px;">
            <div class="progress-bar-fill" id="course-progress-bar" style="width:0%"></div>
          </div>
          <div class="progress-label" id="course-progress-label">0/10 steps completed</div>
        </div>
      </div>

      <div class="course-nav-section">
        <div class="course-nav-label">Overview</div>
        <div class="course-nav-item active" onclick="navigateCourse('dashboard')"><span class="course-nav-icon">&#9670;</span>Dashboard</div>
        <div class="course-nav-item" onclick="navigateCourse('start-here')"><span class="course-nav-icon">&#128640;</span>Start Here</div>
      </div>

      <div class="course-nav-section">
        <div class="course-nav-label">Course Steps</div>
        <div class="course-nav-item" onclick="navigateCourse('step1')"><span class="nav-num">1</span>Basics &amp; Candlesticks</div>
        <div class="course-nav-item" onclick="navigateCourse('step2')"><span class="nav-num">2</span>TradingView Setup</div>
        <div class="course-nav-item" onclick="navigateCourse('step3')"><span class="nav-num">3</span>Market Structure</div>
        <div class="course-nav-item" onclick="navigateCourse('step4')"><span class="nav-num">4</span>Risk Management</div>
        <div class="course-nav-item" onclick="navigateCourse('step5')"><span class="nav-num">5</span>Technical Indicators</div>
        <div class="course-nav-item" onclick="navigateCourse('step6')"><span class="nav-num">6</span>Readiness Assessment</div>
      </div>

      <div class="course-nav-section">
        <div class="course-nav-label">Strategies</div>
        <div class="course-nav-item" onclick="navigateCourse('strat-trendline')"><span class="course-nav-icon">&#128200;</span>Trendline Breakout</div>
        <div class="course-nav-item" onclick="navigateCourse('strat-mfi')"><span class="course-nav-icon">&#9889;</span>MFI + MACD</div>
        <div class="course-nav-item" onclick="navigateCourse('strat-macro')"><span class="course-nav-icon">&#127758;</span>2-Week Macro</div>
      </div>

      <div class="course-nav-section">
        <div class="course-nav-label">Analysis</div>
        <div class="course-nav-item" onclick="navigateCourse('bull-market')"><span class="course-nav-icon">&#128200;</span>Bull Market Analysis</div>
        <div class="course-nav-item" onclick="navigateCourse('backtesting')"><span class="course-nav-icon">&#128202;</span>Backtesting Lab</div>
      </div>

      <div class="course-nav-section">
        <div class="course-nav-label">Resources</div>
        <div class="course-nav-item" onclick="navigateCourse('resources')"><span class="course-nav-icon">&#128218;</span>Resources &amp; Templates</div>
        <div class="course-nav-item" onclick="navigateCourse('alerts')"><span class="course-nav-icon">&#128276;</span>Alerts &amp; Signals</div>
        <div class="course-nav-item" onclick="navigateCourse('dictionary')"><span class="course-nav-icon">&#128214;</span>Trading Dictionary</div>
        <div class="course-nav-item" onclick="navigateCourse('faq')"><span class="course-nav-icon">&#10067;</span>FAQ</div>
        <div class="course-nav-item" onclick="navigateCourse('video-library')"><span class="course-nav-icon">&#127909;</span>Video Library</div>
      </div>
    </div>

    <!-- Main Content Area -->
    <div class="course-main" id="course-main">
      <!-- Content rendered by JavaScript -->
    </div>
  </div>
</div>

<!-- ═══ Educational Modal ═══ -->
<div class="edu-modal-overlay" id="edu-overlay" onclick="if(event.target===this)closeEdu()">
  <div class="edu-modal" style="position:relative;">
    <button class="edu-close" onclick="closeEdu()">&times;</button>
    <div class="edu-icon" id="edu-icon"></div>
    <div class="edu-title" id="edu-title"></div>
    <div class="edu-short" id="edu-short"></div>
    <div class="edu-detail" id="edu-detail"></div>
  </div>
</div>

<!-- ═══ Toast Container ═══ -->
<div class="toast-container" id="toast-container"></div>

<!-- ═══ Keyboard Shortcut Modal ═══ -->
<div class="kb-modal-overlay" id="kb-overlay" onclick="toggleKbModal()"></div>
<div class="kb-modal" id="kb-modal">
  <h3 style="color:var(--cyan);font-size:13px;margin-bottom:14px;">&#9000; Keyboard Shortcuts</h3>
  <div class="kb-row"><span>Overview tab</span><span class="kb-key">1</span></div>
  <div class="kb-row"><span>Charts &amp; Zones tab</span><span class="kb-key">2</span></div>
  <div class="kb-row"><span>Signals tab</span><span class="kb-key">3</span></div>
  <div class="kb-row"><span>Trades tab</span><span class="kb-key">4</span></div>
  <div class="kb-row"><span>Analytics tab</span><span class="kb-key">5</span></div>
  <div class="kb-row"><span>System tab</span><span class="kb-key">6</span></div>
  <div class="kb-row"><span>Learn tab</span><span class="kb-key">7</span></div>
  <div class="kb-row"><span>Refresh data</span><span class="kb-key">R</span></div>
  <div class="kb-row"><span>Toggle chart fullscreen</span><span class="kb-key">F</span></div>
  <div class="kb-row"><span>Show shortcuts</span><span class="kb-key">?</span></div>
  <div class="kb-row"><span>Close modal / Exit fullscreen</span><span class="kb-key">Esc</span></div>
  <div style="text-align:center;margin-top:14px;"><button onclick="toggleKbModal()" style="padding:6px 20px;background:var(--bg2);border:1px solid var(--border);color:var(--text-dim);border-radius:6px;cursor:pointer;font-family:inherit;">Close</button></div>
</div>

<!-- ═══ Footer ═══ -->
<div style="padding:0 24px;">
  <div class="footer">NunuIRL Trading Bot &mdash; Dashboard v4.2 &mdash; Positions 10s | Data 30s | Charts on demand &mdash; Press <span class="kb-key" style="font-size:9px;">?</span> for shortcuts</div>
</div>

</div>
<script>
/* ═══════════════════════════════════════════════════════════════════ */
/* EDUCATIONAL CONTENT                                                */
/* ═══════════════════════════════════════════════════════════════════ */
const EDUCATION = {
  equity: { title:"Equity", icon:"\ud83d\udcb0", short:"Your total account value including all open positions.",
    detail:"<p><strong>Equity</strong> is the total value of your trading account right now. It includes your cash balance plus any unrealized profit or loss from open positions.</p><p>Think of it like checking your bank balance, but it fluctuates in real-time as the market moves. If you have a $1,000 account and an open trade that's up $50, your equity is $1,050.</p><p>Watching equity over time tells you whether your overall trading approach is growing your account or shrinking it.</p>" },
  daily_pnl: { title:"Daily PnL", icon:"\ud83d\udcc8", short:"Profit and Loss for today \u2014 how much money you've made or lost.",
    detail:"<p><strong>PnL (Profit and Loss)</strong> is the net result of all trades closed today, minus any fees paid to the exchange.</p><p>A positive PnL means the bot made money today. A negative PnL means it lost money. This is the most direct measure of daily performance.</p><p><strong>Fees matter:</strong> Every trade costs a small fee (usually 0.02-0.06% per trade). These add up, especially with frequent trading. The fee amount is shown separately so you can see the true cost.</p>" },
  win_rate: { title:"Win Rate", icon:"\ud83c\udfaf", short:"Percentage of trades that made money.",
    detail:"<p><strong>Win Rate</strong> is simply: (winning trades \u00f7 total trades) \u00d7 100%. A 60% win rate means 6 out of every 10 trades were profitable.</p><p><strong>Important:</strong> Win rate alone doesn't tell the whole story. You can have a 40% win rate and still be very profitable if your average win is much larger than your average loss. This is why Risk:Reward ratio matters too.</p><p>Most successful trading systems have win rates between 40-65%. Anything above 70% is exceptional and should be examined carefully to make sure it's sustainable.</p>" },
  open_positions: { title:"Open Positions", icon:"\ud83d\udcca", short:"Number of trades currently active (not yet closed).",
    detail:"<p><strong>Open positions</strong> are trades the bot has entered but not yet exited. Each position has an entry price, stop loss, and take profit targets.</p><p>More open positions means more capital at risk but also more potential opportunity. The bot limits how many positions can be open simultaneously to manage risk.</p>" },
  unrealized_pnl: { title:"Unrealized PnL", icon:"\u23f3", short:"Potential profit/loss on open trades that haven't been closed yet.",
    detail:"<p><strong>Unrealized PnL</strong> is what your open trades are worth right now, but you haven't locked in yet. It's 'paper profit' or 'paper loss'.</p><p>If you have a trade that's up $20, that $20 is unrealized \u2014 it only becomes real (realized) when you close the trade. The market could reverse and turn that $20 gain into a loss.</p><p>This is why stop losses exist: they automatically close a trade to prevent unrealized losses from growing too large.</p>" },
  market_regime: { title:"Market Regime", icon:"\ud83c\udf0a", short:"The current 'personality' of the market \u2014 trending, ranging, or chaotic.",
    detail:"<p><strong>Market regime</strong> describes the current behavior pattern of the market. Different regimes require different trading strategies:</p><p><strong>\u2022 Trend:</strong> Price is moving consistently in one direction. Best for momentum strategies.<br><strong>\u2022 Range:</strong> Price is bouncing between support and resistance. Best for buy-low-sell-high strategies.<br><strong>\u2022 High Volatility:</strong> Large, unpredictable price swings. Higher risk, but also opportunity.<br><strong>\u2022 Panic:</strong> Sharp selloffs driven by fear. Very dangerous for longs.<br><strong>\u2022 Low Liquidity:</strong> Not many buyers/sellers. Prices can gap unexpectedly.</p><p>The bot detects the current regime and adjusts its strategy accordingly. Trading against the regime (e.g., buying in a panic) is the most common way to lose money.</p>" },
  signal_pipeline: { title:"Signal Pipeline", icon:"\ud83d\udd0d", short:"The step-by-step process signals go through before becoming trades.",
    detail:"<p>Every potential trade goes through a <strong>6-stage safety pipeline</strong> before the bot will execute it:</p><p><strong>1. Signal Generation:</strong> 4 independent strategies analyze the market and vote.<br><strong>2. Ensemble Vote:</strong> Multiple strategies must agree (confluence) for the signal to pass.<br><strong>3. Circuit Breaker:</strong> Checks if we've lost too much today or hit too many losses in a row.<br><strong>4. Position Limits:</strong> Ensures we're not over-exposed.<br><strong>5. Leverage &amp; Liquidation:</strong> Calculates safe leverage and checks liquidation risk.<br><strong>6. Size Check:</strong> Ensures the position size meets the exchange's minimum.</p><p>Each gate can reject a signal. This is intentional \u2014 the pipeline is conservative to protect your capital. Most signals get rejected, and that's a good thing.</p>" },
  rejections: { title:"Rejected Signals", icon:"\ud83d\udeab", short:"Signals that were blocked by safety gates before becoming trades.",
    detail:"<p>When a strategy generates a signal but it gets <strong>rejected</strong>, it means one of the safety gates blocked it. This is the bot protecting your money.</p><p><strong>Hard gates</strong> (red) are non-negotiable: circuit breakers, liquidation risk, max positions. These exist to prevent catastrophic losses.</p><p><strong>Soft gates</strong> (yellow) are quality filters: minimum R:R ratio, expected value floor, fee drag. These ensure trades are worth taking after costs.</p><p>The <strong>What If PnL</strong> column shows what would have happened if the trade had been taken. Sometimes rejected signals would have been winners \u2014 that's the cost of safety. But over time, the gates save more money than they cost.</p>" },
  monte_carlo: { title:"Monte Carlo Simulation", icon:"\ud83c\udfb2", short:"Running thousands of random price simulations to predict probable future zones.",
    detail:"<p><strong>Monte Carlo simulation</strong> is a statistical technique that runs thousands of random price path simulations to estimate where price is likely to go.</p><p>Based on recent volatility and price history, it calculates probability bands \u2014 zones where price is statistically likely to find support (buyers step in) or resistance (sellers take profit).</p><p>The zones are color-coded from green (strong buy zone \u2014 price rarely goes this low) to red (strong sell zone \u2014 price rarely goes this high). When price enters these zones, it's a statistical edge.</p><p><strong>Note:</strong> These are probabilities, not guarantees. Black swan events can blow through any zone.</p>" },
  deep_buy_zone: { title:"Deep Buy Zone", icon:"\ud83d\udfe2", short:"Strong support area \u2014 price rarely drops this far, historically a high-probability buying opportunity.",
    detail:"<p>The <strong>Deep Buy Zone</strong> is calculated as SMA20 minus 2.2 standard deviations. Statistically, price only reaches this level about 1-3% of the time.</p><p>When price enters this zone, it represents an oversold condition. The Monte Carlo simulation shows that from this level, there's a high probability of a bounce. However, if price breaks through this zone, it could signal a regime change to panic.</p><p><strong>For traders:</strong> This is the area where the bot identifies the highest-conviction buying opportunities. Positions entered here typically have the best risk:reward ratios.</p>" },
  regular_buy_zone: { title:"Regular Buy Zone", icon:"\ud83d\udfe9", short:"Moderate support area \u2014 good buying zone in normal conditions.",
    detail:"<p>The <strong>Regular Buy Zone</strong> sits between the SMA20 and the Deep Buy Zone (SMA20 minus 1.3 standard deviations). Price visits this zone more frequently than the Deep Buy Zone.</p><p>This is a good entry area during trending or range-bound markets. The risk:reward isn't as extreme as the Deep Buy Zone, but opportunities are more frequent.</p>" },
  regular_sell_zone: { title:"Regular Sell Zone", icon:"\ud83d\udfe5", short:"Moderate resistance area \u2014 good zone to take profits.",
    detail:"<p>The <strong>Regular Sell Zone</strong> is the mirror of Regular Buy (SMA20 plus 1.3 standard deviations). When price reaches this zone, it's statistically extended to the upside.</p><p>This is where take-profit orders are often placed. If you bought in the buy zone, selling here locks in a profit while price is still elevated.</p>" },
  safe_sell_zone: { title:"Safe Sell Zone", icon:"\ud83d\udd34", short:"Strong resistance area \u2014 price rarely goes this high, high-probability profit-taking zone.",
    detail:"<p>The <strong>Safe Sell Zone</strong> (SMA20 plus 2.2 standard deviations) is the strongest resistance area. Price reaches this level only 1-3% of the time statistically.</p><p>This is where aggressive profit-taking happens. The Monte Carlo simulation shows high probability of a pullback from this level. It's also where the bot identifies the best shorting opportunities.</p>" },
  sma: { title:"SMA (Simple Moving Average)", icon:"\u2796", short:"The average price over the last 20 periods \u2014 the center of the trading range.",
    detail:"<p>The <strong>SMA20 (Simple Moving Average)</strong> is just the average closing price over the last 20 candles. It acts as the center line for the Monte Carlo zones.</p><p>When price is above the SMA20, the short-term trend is bullish. When below, it's bearish. The SMA20 often acts as dynamic support in uptrends and resistance in downtrends.</p><p>All the zone calculations are based on how far price deviates from this average.</p>" },
  signal_confluence: { title:"Signal Confluence", icon:"\ud83e\udd1d", short:"When multiple independent strategies agree on the same trade direction.",
    detail:"<p><strong>Confluence</strong> is when multiple independent analysis methods point to the same conclusion. It's one of the strongest edges in trading.</p><p>The bot runs 4 different strategies simultaneously. When 3 or 4 of them agree on a direction (e.g., all saying BUY), that's high confluence. The more strategies that agree, the higher the confidence score.</p><p><strong>Why it matters:</strong> Each strategy can be wrong on its own. But when multiple independent methods agree, the probability of being right increases significantly. Think of it like getting a second (and third, and fourth) opinion.</p>" },
  circuit_breaker: { title:"Circuit Breaker", icon:"\u26a1", short:"Emergency safety system that stops trading after too many losses.",
    detail:"<p><strong>Circuit breakers</strong> are automatic safety switches that halt trading when risk thresholds are exceeded:</p><p><strong>\u2022 Daily Loss Limit:</strong> If losses exceed a percentage of current equity in one day, trading stops until tomorrow.<br><strong>\u2022 Consecutive Losses:</strong> If N trades in a row lose money, trading pauses to prevent tilt-driven losses.<br><strong>\u2022 Drawdown Cap:</strong> If the account drops too far from its peak, all trading stops.</p><p>These exist because the biggest risk in trading isn't individual losses \u2014 it's a cascade of losses that wipes out the account. Circuit breakers prevent that spiral.</p>" },
  go_live_gates: { title:"Go-Live Gates", icon:"\ud83d\udea6", short:"5 checkpoints the bot must pass before trading with real money.",
    detail:"<p>Before switching from paper trading to live trading, the bot must pass 5 validation gates:</p><p><strong>1. Walk Forward:</strong> Strategy works on unseen data.<br><strong>2. Net PnL:</strong> System is profitable over the test period.<br><strong>3. Max Drawdown:</strong> Worst peak-to-trough drop is within acceptable limits.<br><strong>4. Factor ICs:</strong> Individual prediction factors have statistical significance.<br><strong>5. Sharpe Ratio:</strong> Risk-adjusted returns meet the minimum threshold.</p><p>All 5 gates must be green before live trading is authorized. This prevents deploying an untested or unprofitable system with real money.</p>" },
  positions: { title:"Trading Positions", icon:"\ud83d\udcbc", short:"Active trades with entry, stop loss, and take profit levels.",
    detail:"<p>Each <strong>position</strong> represents an active trade. Key information:</p><p><strong>\u2022 Side:</strong> LONG (betting price goes up) or SHORT (betting price goes down).<br><strong>\u2022 Entry:</strong> The price where the trade was opened.<br><strong>\u2022 Stop Loss (SL):</strong> The price where the trade automatically closes to limit losses.<br><strong>\u2022 Take Profit (TP1/TP2):</strong> Target prices to lock in profits.<br><strong>\u2022 Leverage:</strong> How much borrowed money is used (2x = trading with twice your money).<br><strong>\u2022 State:</strong> OPEN \u2192 TP1_HIT \u2192 TRAILING \u2192 CLOSED.</p><p>The <strong>price range bar</strong> shows where current price sits between the stop loss and take profit targets.</p>" },
  ensemble: { title:"Ensemble Voting", icon:"\ud83d\uddf3\ufe0f", short:"4 independent strategies vote on each trade \u2014 majority rules.",
    detail:"<p>The bot uses an <strong>ensemble</strong> (team) of 4 independent trading strategies. Each strategy analyzes the market differently and casts a vote.</p><p><strong>The 4 strategies:</strong><br>\u2022 Regime Trend \u2014 Follows overall market direction using momentum indicators<br>\u2022 Monte Carlo Zones \u2014 Statistical support/resistance from price simulations<br>\u2022 Multi-Tier Quality \u2014 Multi-timeframe signal quality scoring<br>\u2022 Confidence Scorer \u2014 Multi-factor confidence aggregation</p><p>A trade only executes when enough strategies agree (minimum 2 same-direction votes). This <strong>weighted veto</strong> system prevents any single strategy from making a bad trade on its own.</p>" },
  strategy_weights: { title:"Strategy Weights", icon:"\u2696\ufe0f", short:"How much influence each strategy has in the ensemble vote.",
    detail:"<p>Not all strategies are weighted equally. <strong>Strategy weights</strong> are adaptive \u2014 strategies that have been performing well recently get more influence, while struggling strategies get less.</p><p>Weights are recalculated based on rolling performance with exponential decay (recent trades matter more). This means the system naturally adapts to changing market conditions.</p>" },
  strategy_performance: { title:"Strategy Performance", icon:"\ud83d\udcca", short:"How each individual strategy is performing over the last 7 days.",
    detail:"<p>This table breaks down the performance of each of the 4 trading strategies independently. Key metrics:</p><p><strong>\u2022 Trades:</strong> How many signals this strategy generated that became trades.<br><strong>\u2022 Win Rate:</strong> What percentage of those trades were profitable.<br><strong>\u2022 PnL:</strong> Total profit or loss from this strategy's trades.<br><strong>\u2022 Avg Score:</strong> Average confidence score of signals (higher = more confident).</p>" },
  equity_curve: { title:"Equity Curve", icon:"\ud83d\udcc8", short:"A chart showing how your account value has changed over time.",
    detail:"<p>The <strong>equity curve</strong> plots your account value day by day. An upward-sloping curve means you're making money; downward means you're losing.</p><p><strong>What to look for:</strong><br>\u2022 Steady upward slope = consistent profitability<br>\u2022 Sharp drops = drawdowns (normal but should recover)<br>\u2022 Flat periods = no edge in current market conditions<br>\u2022 Stair-step pattern = normal for low-frequency trading</p>" },
  trades: { title:"Trade Journal", icon:"\ud83d\udcd3", short:"A log of every trade the bot has made with full details.",
    detail:"<p>The <strong>trade journal</strong> records every trade with its timestamp, symbol, direction, entry/exit price, and PnL. This is essential for learning what's working and what isn't.</p><p>Review your trades regularly to spot patterns: Are losses clustered around certain times? Does one symbol consistently underperform? Are stop losses too tight?</p>" },
  llm_agents: { title:"AI Multi-Agent System", icon:"\ud83e\udd16", short:"6 specialized AI agents that analyze trades from different perspectives.",
    detail:"<p>When enabled, the bot uses <strong>6 specialized AI agents</strong> (powered by Claude) that each analyze trades from a different angle:</p><p><strong>\u2022 Regime Agent:</strong> Classifies the current market environment.<br><strong>\u2022 Trade Agent:</strong> Forms a directional thesis (buy/sell/skip).<br><strong>\u2022 Risk Agent:</strong> Sizes positions and flags portfolio risks.<br><strong>\u2022 Critic Agent:</strong> Stress-tests the thesis and can veto bad trades.<br><strong>\u2022 Learning Agent:</strong> Extracts lessons from closed trades.<br><strong>\u2022 Exit Agent:</strong> Monitors open positions and recommends exits.</p><p>This creates a checks-and-balances system where no single perspective dominates.</p>" },
  signals: { title:"Trading Signals", icon:"\u26a1", short:"Buy or sell recommendations generated by the bot's analysis strategies.",
    detail:"<p>A <strong>signal</strong> is a recommendation to buy or sell a specific asset. Each signal includes:</p><p><strong>\u2022 Direction:</strong> BUY (go long) or SELL (go short)<br><strong>\u2022 Confidence:</strong> How certain the bot is (0-100%)<br><strong>\u2022 Entry Price:</strong> The recommended entry level<br><strong>\u2022 Stop Loss:</strong> Where to cut losses if wrong<br><strong>\u2022 Take Profit:</strong> Target prices for locking in gains</p><p>Not every signal becomes a trade. Signals must pass through the safety pipeline first, and many get filtered out. This is intentional \u2014 quality over quantity.</p>" },
  leverage: { title:"Leverage", icon:"\ud83d\udd0d", short:"Borrowed money that amplifies both gains AND losses.",
    detail:"<p><strong>Leverage</strong> lets you trade with more money than you have. 3x leverage means you're controlling 3x your actual capital.</p><p><strong>\u26a0\ufe0f Warning:</strong> Leverage is a double-edged sword. If you use 3x leverage and price moves 10% in your favor, you make 30%. But if it moves 10% against you, you lose 30%.</p><p>The bot calculates leverage based on confidence level and stop loss distance. Higher confidence + wider stops = more leverage allowed. The system caps maximum leverage to prevent excessive risk.</p>" },
  correlation: { title:"Portfolio Correlation", icon:"\ud83d\udd17", short:"How similarly different assets move \u2014 helps understand diversification risk.",
    detail:"<p><strong>Correlation</strong> measures how much two assets move together. A correlation of +1.0 means they move identically; -1.0 means they move opposite; 0 means no relationship.</p><p>If your portfolio holds highly correlated assets (e.g., BTC and ETH often have 0.7+ correlation), a drop in one likely means a drop in all \u2014 magnifying losses. The correlation guard prevents the bot from opening too many correlated positions.</p>" },
  missed_alpha: { title:"Missed Trade Alpha", icon:"\ud83d\udcb8", short:"Profitable trades the bot rejected \u2014 the cost of being conservative.",
    detail:"<p><strong>Missed Alpha</strong> tracks signals that were rejected by safety gates but would have been profitable. This helps fine-tune gate sensitivity.</p><p>Some missed alpha is expected and healthy \u2014 safety gates protect against catastrophic losses. But if the bot consistently rejects winning signals, gate thresholds may be too tight.</p>" },
  trade_outcomes: { title:"Trade Outcomes", icon:"\ud83c\udfaf", short:"Detailed exit classification \u2014 not just win/loss but HOW the trade ended.",
    detail:"<p>Trade outcomes reveal the quality of exits:<br><strong>\u2022 CLEAN_WIN:</strong> Hit take profit target cleanly.<br><strong>\u2022 TP1_ONLY:</strong> Hit first target but stopped out before TP2.<br><strong>\u2022 TRAILING_WIN:</strong> Rode a trend with trailing stop for max profit.<br><strong>\u2022 EARLY_EXIT_SAVE:</strong> LLM recognized deterioration and exited early, saving money.<br><strong>\u2022 CLEAN_LOSS:</strong> Hit stop loss \u2014 normal cost of trading.<br><strong>\u2022 TP1_THEN_SL:</strong> Hit TP1 then reversed to stop loss.</p>" },
  strategy_fingerprints: { title:"Strategy Fingerprints", icon:"\ud83e\udded", short:"Performance DNA of each strategy across different conditions.",
    detail:"<p><strong>Strategy fingerprints</strong> map how each strategy performs across symbols and market regimes. This reveals:<br>\u2022 Which strategy works best for which coin<br>\u2022 Which regimes each strategy excels in or fails at<br>\u2022 Hidden correlations between strategy success and market conditions</p><p>Green cells = high win rate, Red = low win rate. The darker the color, the stronger the signal.</p>" },
  regime_transitions: { title:"Regime Transitions", icon:"\u23f0", short:"How market regimes flow from one to another over time.",
    detail:"<p><strong>Regime transitions</strong> track how the market moves between states (trend \u2192 range \u2192 panic, etc.). Common patterns:<br>\u2022 Range \u2192 Trend: Breakout, often profitable<br>\u2022 Trend \u2192 High Volatility: Exhaustion, watch for reversal<br>\u2022 Any \u2192 Panic: Sharp selloff, defensive mode needed</p><p>Understanding transitions helps anticipate regime changes before they happen.</p>" },
  calibration: { title:"Confidence Calibration", icon:"\ud83d\udccf", short:"Is the bot's confidence accurate? Compares predicted vs actual win rates.",
    detail:"<p><strong>Calibration</strong> answers: when the bot says '70% confident', does it actually win 70% of the time?<br>\u2022 Perfect calibration = the diagonal line<br>\u2022 Above the line = under-confident (wins more than predicted)<br>\u2022 Below the line = over-confident (wins less than predicted)</p><p>Good calibration is essential for proper position sizing \u2014 if confidence is inflated, the bot will over-size losing trades.</p>" },
  insight_journal: { title:"LLM Insight Journal", icon:"\ud83d\udcd6", short:"The bot's learned conclusions \u2014 validated patterns discovered through trading.",
    detail:"<p>The <strong>Insight Journal</strong> stores durable conclusions the LLM has extracted from trading experience. Each insight is categorized (strategy, symbol, regime, timing, risk) and tracked for validation.</p><p>Insights with high confidence scores have been repeatedly confirmed by trade outcomes. This is the bot's accumulated wisdom \u2014 its 'trading intuition' made explicit.</p>" },
  candlestick: { title:"Candlestick Charts", icon:"\ud83d\udcca", short:"Each candle shows the open, high, low, and close price for a time period.",
    detail:"<p>A <strong>candlestick</strong> represents price action for one time period (e.g., 1 hour):</p><p><strong>\u2022 Body (thick part):</strong> Shows open-to-close range. Green = price went up, Red = price went down.<br><strong>\u2022 Wicks (thin lines):</strong> Show the high and low reached during that period.<br><strong>\u2022 Long wick down:</strong> Buyers stepped in and pushed price back up (bullish).<br><strong>\u2022 Long wick up:</strong> Sellers stepped in and pushed price back down (bearish).</p><p>Reading candlestick patterns is one of the most fundamental skills in trading. The bot's Monte Carlo zones are overlaid on these charts to show key price levels.</p>" },
  paper_trading: { title:"Paper Trading", icon:"\ud83d\udcdd", short:"Simulated trading with fake money to test strategies before risking real capital.",
    detail:"<p><strong>Paper trading</strong> means the bot executes all its logic \u2014 signal generation, risk management, position sizing \u2014 but with simulated money instead of real funds.</p><p>This is how you validate that a trading system works before putting real money at risk. The bot tracks all trades as if they were real, including fees and slippage.</p><p>The Go-Live Gates system monitors paper trading performance and only authorizes live trading once specific performance benchmarks are met.</p>" }
};

/* ═══════════════════════════════════════════════════════════════════ */
/* UTILITY FUNCTIONS                                                  */
/* ═══════════════════════════════════════════════════════════════════ */
function fmt$(v) { if(v==null||isNaN(v)) return '--'; return (v>=0?'+':'')+'\u0024'+Math.abs(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}); }
function fmtAbs$(v) { if(v==null||isNaN(v)) return '--'; return '\u0024'+Math.abs(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}); }
function fmtPct(v) { if(v==null||isNaN(v)) return '--'; return (v>=0?'+':'')+v.toFixed(2)+'%'; }
function fmtTime(iso) { if(!iso) return '--'; try { return new Date(iso).toLocaleTimeString(); } catch { return iso; } }
function fmtDateTime(iso) { if(!iso) return '--'; try { const d=new Date(iso); return d.toLocaleDateString(undefined,{month:'short',day:'numeric'})+' '+d.toLocaleTimeString(); } catch { return iso; } }
function fmtDuration(s) { if(!s||s<0) return '--'; const d=Math.floor(s/86400),h=Math.floor((s%86400)/3600),m=Math.floor((s%3600)/60),sec=Math.floor(s%60); if(d>0) return d+'d '+h+'h '+m+'m'; if(h>0) return h+'h '+m+'m '+sec+'s'; if(m>0) return m+'m '+sec+'s'; return sec+'s'; }
function fmtPrice(v) { if(v==null||isNaN(v)) return '--'; if(v>1000) return '\u0024'+v.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2}); return '\u0024'+v.toFixed(v<1?6:4); }
function pnlColor(v) { return v>=0 ? 'var(--green)' : 'var(--red)'; }
function pnlClass(v) { return v>=0 ? 'green' : 'red'; }
function sidePill(side) { const s=(side||'').toUpperCase(); const isLong=s==='BUY'||s==='LONG'; return '<span class="pill '+(isLong?'pill-long':'pill-short')+'">'+(isLong?'LONG':'SHORT')+'</span>'; }

/* ═══════════════════════════════════════════════════════════════════ */
/* EDUCATIONAL MODAL                                                  */
/* ═══════════════════════════════════════════════════════════════════ */
function showEdu(key) {
  const info = EDUCATION[key];
  if(!info) return;
  document.getElementById('edu-icon').textContent = info.icon || '\u2753';
  document.getElementById('edu-title').textContent = info.title || key;
  document.getElementById('edu-short').textContent = info.short || '';
  document.getElementById('edu-detail').innerHTML = info.detail || '';
  document.getElementById('edu-overlay').classList.add('visible');
}
function closeEdu() { document.getElementById('edu-overlay').classList.remove('visible'); }
document.addEventListener('keydown', e => { if(e.key==='Escape') closeEdu(); });

/* ═══════════════════════════════════════════════════════════════════ */
/* TAB NAVIGATION                                                     */
/* ═══════════════════════════════════════════════════════════════════ */
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    btn.classList.add('active');
    const tab = document.getElementById('tab-' + btn.dataset.tab);
    if(tab) tab.classList.add('active');
    if(btn.dataset.tab === 'charts' && !chartInitialized) initChartTab();
    if(btn.dataset.tab === 'analytics' && !analyticsInitialized) loadAnalytics();
  });
});

/* ═══════════════════════════════════════════════════════════════════ */
/* CHART TAB — TradingView Lightweight Charts                         */
/* ═══════════════════════════════════════════════════════════════════ */
let chartInitialized = false;
let tvChart = null;
let tvCandleSeries = null;
let currentChartSymbol = null;
let zonePriceLines = [];

function initChartTab() {
  chartInitialized = true;
  loadChartSymbols();
}

async function loadChartSymbols() {
  try {
    const res = await fetch('/api/market');
    let symbols = [];
    if(res.ok) {
      const market = await res.json();
      symbols = market.map(m => m.symbol).filter(Boolean);
    }
    if(symbols.length === 0) symbols = ['BTC','SOL','HYPE','DOGE','FARTCOIN'];
    const container = document.getElementById('chart-symbol-tabs');
    container.innerHTML = symbols.map((s,i) =>
      '<button class="symbol-tab'+(i===0?' active':'')+'" data-symbol="'+s+'" onclick="selectChartSymbol(\''+s+'\')">'+s+'</button>'
    ).join('');
    selectChartSymbol(symbols[0]);
  } catch { selectChartSymbol('BTC'); }
}

async function selectChartSymbol(symbol) {
  currentChartSymbol = symbol;
  document.querySelectorAll('.symbol-tab').forEach(b => {
    b.classList.toggle('active', b.dataset.symbol === symbol);
  });
  await loadChartData(symbol);
}

async function loadChartData(symbol) {
  const container = document.getElementById('main-chart-container');
  if(!container) return;

  // Create or recreate chart
  if(tvChart) { tvChart.remove(); tvChart = null; }
  container.innerHTML = '';

  tvChart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height: 420,
    layout: { background: { type: 'solid', color: '#0f0f1e' }, textColor: '#9090b0', fontFamily: "'SF Mono','Fira Code',monospace", fontSize: 11 },
    grid: { vertLines: { color: 'rgba(26,26,53,0.5)' }, horzLines: { color: 'rgba(26,26,53,0.5)' } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal, vertLine: { color: 'rgba(34,211,238,0.3)', labelBackgroundColor: '#1a1a35' }, horzLine: { color: 'rgba(34,211,238,0.3)', labelBackgroundColor: '#1a1a35' } },
    rightPriceScale: { borderColor: '#1a1a35' },
    timeScale: { borderColor: '#1a1a35', timeVisible: true, secondsVisible: false },
    handleScroll: true, handleScale: true,
  });

  tvCandleSeries = tvChart.addSeries(LightweightCharts.CandlestickSeries, {
    upColor: '#00e6a0', downColor: '#ff4466',
    borderUpColor: '#00e6a0', borderDownColor: '#ff4466',
    wickUpColor: '#00e6a088', wickDownColor: '#ff446688',
  });

  // Fetch OHLCV + zones in parallel
  const [ohlcvRes, zonesRes] = await Promise.allSettled([
    fetch('/api/ohlcv?symbol='+symbol+'&timeframe=1h'),
    fetch('/api/zones?symbol='+symbol)
  ]);

  // Set candle data
  let hasChartData = false;
  if(ohlcvRes.status==='fulfilled' && ohlcvRes.value.ok) {
    try {
      const candles = await ohlcvRes.value.json();
      if(Array.isArray(candles) && candles.length > 0) {
        const chartData = candles.map(c => ({
          time: typeof c.time === 'string' ? Math.floor(new Date(c.time).getTime()/1000) : c.time,
          open: c.open, high: c.high, low: c.low, close: c.close
        })).filter(c => c.time && !isNaN(c.open));
        if(chartData.length > 0) {
          tvCandleSeries.setData(chartData);
          tvChart.timeScale().fitContent();
          hasChartData = true;
        }
      }
    } catch(e) { console.error('OHLCV parse error:', e); }
  }

  // Fallback: show TradingView widget if no OHLCV data available
  if(!hasChartData) {
    if(tvChart) { tvChart.remove(); tvChart = null; }
    var tvSymbolMap = { 'BTC': 'COINBASE:BTCUSD', 'SOL': 'COINBASE:SOLUSD', 'ETH': 'COINBASE:ETHUSD', 'HYPE': 'BYBIT:HYPEUSDT', 'DOGE': 'COINBASE:DOGEUSD', 'FARTCOIN': 'BYBIT:FARTCOINUSDT' };
    var tvSymbol = tvSymbolMap[symbol] || 'COINBASE:BTCUSD';
    container.innerHTML = '<div style="text-align:center;padding:12px 0 8px;"><span style="color:var(--yellow);font-size:11px;">Live data unavailable \u2014 showing TradingView widget for ' + symbol + '</span></div>' +
      '<iframe src="https://www.tradingview.com/widgetembed/?symbol=' + encodeURIComponent(tvSymbol) + '&interval=60&hidesidetoolbar=0&symboledit=1&saveimage=0&toolbarbg=0a0a1a&theme=dark&style=1&timezone=exchange&withdateranges=1&hidevolume=0&width=100%25&height=400" style="width:100%;height:400px;border:none;border-radius:8px;"></iframe>';
    return;
  }

  // Overlay zones
  zonePriceLines.forEach(pl => { try { tvCandleSeries.removePriceLine(pl); } catch {} });
  zonePriceLines = [];

  let zoneData = null;
  if(zonesRes.status==='fulfilled' && zonesRes.value.ok) {
    try { zoneData = await zonesRes.value.json(); } catch {}
  }

  if(zoneData && zoneData.zones) {
    const z = zoneData.zones;
    const zoneConfigs = [
      { price: z.safe_sell, title: 'Safe Sell Zone', color: '#ff4466', style: 2 },
      { price: z.regular_sell, title: 'Regular Sell', color: '#ff446688', style: 1 },
      { price: z.sma20, title: 'SMA20', color: '#22d3ee', style: 2 },
      { price: z.regular_buy, title: 'Regular Buy', color: '#00e6a088', style: 1 },
      { price: z.deep_buy, title: 'Deep Buy Zone', color: '#00e6a0', style: 2 },
    ];

    zoneConfigs.forEach(zc => {
      if(zc.price && !isNaN(zc.price)) {
        const pl = tvCandleSeries.createPriceLine({
          price: zc.price, color: zc.color, lineWidth: 1,
          lineStyle: zc.style, axisLabelVisible: true, title: zc.title,
        });
        zonePriceLines.push(pl);
      }
    });

    // Zone details panel
    renderZoneDetails(z, zoneData.regime);
  }

  // Signal markers
  if(zoneData && zoneData.signals && zoneData.signals.length > 0) {
    renderChartSignals(zoneData.signals);
    try {
      const markers = zoneData.signals.map(s => ({
        time: typeof s.timestamp === 'string' ? Math.floor(new Date(s.timestamp).getTime()/1000) : s.timestamp,
        position: (s.side||'').toUpperCase()==='BUY' ? 'belowBar' : 'aboveBar',
        color: (s.side||'').toUpperCase()==='BUY' ? '#00e6a0' : '#ff4466',
        shape: (s.side||'').toUpperCase()==='BUY' ? 'arrowUp' : 'arrowDown',
        text: (s.strategy||'Signal') + ' ' + (s.confidence||0).toFixed(0) + '%',
      })).filter(m => m.time && !isNaN(m.time)).sort((a,b) => a.time - b.time);
      if(markers.length > 0 && typeof LightweightCharts.createSeriesMarkers === 'function') {
        LightweightCharts.createSeriesMarkers(tvCandleSeries, markers);
      }
    } catch(e) { console.error('Marker error:', e); }
  }

  // Resize handler
  const resizeObserver = new ResizeObserver(entries => {
    if(tvChart) tvChart.applyOptions({ width: container.clientWidth });
  });
  resizeObserver.observe(container);
}

function renderZoneDetails(zones, regime) {
  const el = document.getElementById('zone-details');
  if(!el) return;
  const items = [
    { label: 'Safe Sell', price: zones.safe_sell, color: 'var(--red)', desc: 'Strong resistance \u2014 statistically unlikely to go higher' },
    { label: 'Regular Sell', price: zones.regular_sell, color: 'var(--red)', desc: 'Moderate resistance \u2014 good profit-taking zone' },
    { label: 'SMA20 (Center)', price: zones.sma20, color: 'var(--cyan)', desc: 'Moving average \u2014 fair value center' },
    { label: 'Regular Buy', price: zones.regular_buy, color: 'var(--green)', desc: 'Moderate support \u2014 good entry zone' },
    { label: 'Deep Buy', price: zones.deep_buy, color: 'var(--green)', desc: 'Strong support \u2014 high-probability bounce area' },
  ];
  let html = '<div style="margin-bottom:12px;">Regime: <span class="regime-pill" style="background:var(--blue-dim);color:var(--blue);">'+(regime||'unknown').toUpperCase()+'</span></div>';
  items.forEach(item => {
    if(item.price) {
      html += '<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;padding:8px;background:var(--bg2);border-radius:6px;border-left:3px solid '+item.color+';">' +
        '<div style="flex:1;"><div style="font-weight:700;font-size:12px;color:'+item.color+';">'+item.label+'</div><div style="font-size:10px;color:var(--muted);">'+item.desc+'</div></div>' +
        '<div style="font-size:14px;font-weight:800;">'+fmtPrice(item.price)+'</div></div>';
    }
  });
  el.innerHTML = html;
}

function renderChartSignals(signals) {
  const el = document.getElementById('chart-signals');
  if(!el) return;
  if(!signals || signals.length === 0) { el.innerHTML = '<div class="empty">No signals for this symbol</div>'; return; }
  el.innerHTML = signals.slice(0,8).map(s => {
    const isLong = (s.side||'').toUpperCase() === 'BUY';
    return '<div class="signal-card" style="border-left:3px solid '+(isLong?'var(--green)':'var(--red)')+';padding:10px 14px;margin-bottom:6px;">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;">' +
      '<div>'+sidePill(s.side)+' <span style="font-weight:700;font-size:13px;margin-left:6px;">'+(s.confidence||0).toFixed(0)+'%</span></div>' +
      '<span style="font-size:10px;color:var(--muted);">'+(s.strategy||'--')+'</span></div>' +
      '<div style="display:flex;gap:12px;margin-top:6px;font-size:10px;color:var(--text-dim);">' +
      '<span>Entry: '+fmtPrice(s.entry)+'</span><span>SL: '+fmtPrice(s.sl)+'</span><span>TP1: '+fmtPrice(s.tp1)+'</span></div></div>';
  }).join('');
}

/* ═══════════════════════════════════════════════════════════════════ */
/* EQUITY CHART (Chart.js)                                            */
/* ═══════════════════════════════════════════════════════════════════ */
let equityChart = null;
let dailyPnlChart = null;
let analyticsInitialized = false;

function buildEquityChart(eqData) {
  const canvas = document.getElementById('equity-chart');
  if(!canvas || !eqData || eqData.length < 2) return;
  const ctx = canvas.getContext('2d');
  const labels = eqData.map(d => { try { return new Date(d.timestamp).toLocaleDateString(undefined,{month:'short',day:'numeric'}); } catch { return ''; } });
  const values = eqData.map(d => d.equity);
  const isUp = values[values.length-1] >= values[0];
  const lineColor = isUp ? '#00e6a0' : '#ff4466';
  const fillColor = isUp ? 'rgba(0,230,160,0.08)' : 'rgba(255,68,102,0.08)';
  if(equityChart) { equityChart.data.labels=labels; equityChart.data.datasets[0].data=values; equityChart.data.datasets[0].borderColor=lineColor; equityChart.data.datasets[0].backgroundColor=fillColor; equityChart.update('none'); return; }
  equityChart = new Chart(ctx, {
    type:'line', data:{ labels, datasets:[{ label:'Equity', data:values, borderColor:lineColor, backgroundColor:fillColor, borderWidth:2, fill:true, tension:0.3, pointRadius:0, pointHitRadius:10, pointHoverRadius:4, pointHoverBackgroundColor:lineColor }] },
    options:{ responsive:true, maintainAspectRatio:false, interaction:{mode:'index',intersect:false}, plugins:{ legend:{display:false}, tooltip:{ backgroundColor:'#1a1a2e', borderColor:'#2a2a50', borderWidth:1, titleFont:{family:'monospace',size:11}, bodyFont:{family:'monospace',size:11}, callbacks:{ label:function(c){ return 'Equity: \u0024'+c.parsed.y.toLocaleString(undefined,{minimumFractionDigits:2}); } } } }, scales:{ x:{ grid:{color:'rgba(26,26,53,0.5)',drawBorder:false}, ticks:{color:'#5e5e80',font:{size:10,family:'monospace'},maxTicksLimit:10} }, y:{ grid:{color:'rgba(26,26,53,0.5)',drawBorder:false}, ticks:{color:'#5e5e80',font:{size:10,family:'monospace'},callback:v=>'\u0024'+v.toLocaleString()} } } }
  });
}

/* ═══════════════════════════════════════════════════════════════════ */
/* RENDER FUNCTIONS                                                   */
/* ═══════════════════════════════════════════════════════════════════ */

function renderPositions(positions) {
  const tbody = document.getElementById('positions-body');
  if(!tbody) return;
  if(!positions || positions.length === 0) {
    tbody.innerHTML = '<tr><td colspan="11" class="empty"><div class="empty-icon">\ud83d\udd0d</div>No open positions<div class="empty-msg">The bot is scanning for opportunities...</div></td></tr>';
    document.getElementById('kpi-open-positions').textContent = '0';
    const uEl = document.getElementById('kpi-unrealized-pnl'); uEl.textContent = '\u00240.00'; uEl.className = 'metric';
    return;
  }
  let totalPnl = 0;
  const stateColors = { OPEN:'var(--blue)', TP1_HIT:'var(--green)', TRAILING:'var(--yellow)', CLOSING:'var(--orange)' };
  let html = positions.map(p => {
    const uPnl = p.unrealized_pnl || 0; totalPnl += uPnl;
    const pnlPct = p.pnl_pct || 0;
    const state = (p.state || 'OPEN').toUpperCase();
    const stColor = stateColors[state] || 'var(--muted)';
    const entry = p.entry_price || p.entry || 0;
    const sl = p.sl || 0; const tp1 = p.tp1 || 0;
    const current = p.current_price || 0;
    // Price range bar
    let rangeHtml = '--';
    if(sl && tp1 && entry && current) {
      const lo = Math.min(sl, entry); const hi = Math.max(tp1, entry);
      const range = hi - lo || 1;
      const curPct = Math.max(0, Math.min(100, ((current - lo) / range) * 100));
      const entryPct = ((entry - lo) / range) * 100;
      rangeHtml = '<div class="price-range-bar" style="width:120px;height:16px;">' +
        '<div style="position:absolute;top:0;left:0;width:'+entryPct+'%;height:100%;background:var(--red-dim);border-radius:4px 0 0 4px;"></div>' +
        '<div style="position:absolute;top:0;left:'+entryPct+'%;width:'+(100-entryPct)+'%;height:100%;background:var(--green-dim);border-radius:0 4px 4px 0;"></div>' +
        '<div style="position:absolute;top:-1px;left:'+curPct+'%;width:3px;height:18px;background:var(--cyan);border-radius:2px;box-shadow:0 0 4px var(--cyan);"></div></div>';
    }
    return '<tr><td><strong>'+(p.symbol||'--')+'</strong></td><td>'+sidePill(p.side)+'</td><td>'+fmtPrice(entry)+'</td><td>'+fmtPrice(current)+'</td>' +
      '<td>'+rangeHtml+'</td>' +
      '<td class="'+(uPnl>=0?'pnl-pos':'pnl-neg')+'">'+fmt$(uPnl)+'</td><td style="color:'+pnlColor(pnlPct)+'">'+fmtPct(pnlPct)+'</td>' +
      '<td>'+(p.leverage||1)+'x</td><td><span style="color:'+stColor+';font-size:11px;font-weight:600;">'+state+'</span></td>' +
      '<td>'+fmtDuration(p.hold_time_s)+'</td><td style="color:var(--muted);font-size:11px;">'+(p.trade_profile||'--')+'</td></tr>';
  }).join('');
  html += '<tr style="border-top:2px solid var(--border);"><td colspan="5" style="text-align:right;font-weight:700;color:var(--muted);">Total Unrealized</td><td class="'+(totalPnl>=0?'pnl-pos':'pnl-neg')+'" style="font-size:14px;">'+fmt$(totalPnl)+'</td><td colspan="5"></td></tr>';
  tbody.innerHTML = html;
  document.getElementById('kpi-open-positions').textContent = positions.length;
  const uEl = document.getElementById('kpi-unrealized-pnl'); uEl.textContent = fmt$(totalPnl); uEl.className = 'metric ' + pnlClass(totalPnl);
}

function renderHeatmap(marketData) {
  const grid = document.getElementById('heatmap-grid');
  if(!grid) return;
  if(!marketData || marketData.length === 0) { grid.innerHTML = '<div class="empty" style="grid-column:1/-1;"><div class="empty-icon">\ud83c\udf0d</div>No market data available<div class="empty-msg">Market data will populate once the bot starts scanning</div></div>'; return; }
  const regimeColors = { trend:'var(--green)', range:'var(--yellow)', panic:'var(--red)', high_volatility:'var(--orange)', low_liquidity:'var(--purple)', consolidation:'var(--blue)', news_dislocation:'var(--cyan)', unknown:'var(--muted)' };
  grid.innerHTML = marketData.map(m => {
    const regime = (m.regime||'unknown').toLowerCase();
    const borderColor = regimeColors[regime] || regimeColors.unknown;
    const bias = (m.signal_bias||'neutral').toLowerCase();
    const conf = Math.max(0,Math.min(100,m.confidence||0));
    const danger = m.danger_level || 0;
    const isOpp = bias==='bullish' && conf>60;
    const isDanger = danger > 60;
    let biasArrow, biasColor;
    if(bias==='bullish') { biasArrow='\u2191 Bullish'; biasColor='var(--green)'; }
    else if(bias==='bearish') { biasArrow='\u2193 Bearish'; biasColor='var(--red)'; }
    else { biasArrow='\u2014 Neutral'; biasColor='var(--muted)'; }
    const confColor = conf>70?'var(--green)':conf>40?'var(--yellow)':'var(--red)';
    let extra = '';
    if(isDanger) extra += '<div style="color:var(--red);font-size:10px;margin-top:4px;">\u26a0 Danger: '+danger+'%<span class="danger-dot"></span></div>';
    if(m.recent_pnl != null && !isNaN(m.recent_pnl)) extra += '<div style="color:'+pnlColor(m.recent_pnl)+';font-size:10px;margin-top:2px;">PnL: '+fmt$(m.recent_pnl)+'</div>';
    if(m.signal_count) extra += '<div style="color:var(--muted);font-size:10px;margin-top:2px;">'+m.signal_count+' signals today</div>';
    return '<div class="heatmap-cell'+(isOpp?' opportunity-glow':'')+(isDanger?' danger-glow':'')+'" style="border-left-color:'+borderColor+';" onclick="switchToChart(\''+m.symbol+'\')">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;"><span class="sym-name">'+(m.symbol||'--')+'</span></div>' +
      '<div style="margin-bottom:6px;"><span class="regime-pill" style="background:'+borderColor+'22;color:'+borderColor+';">'+regime.toUpperCase()+'</span></div>' +
      '<div style="color:'+biasColor+';font-size:12px;font-weight:600;margin-bottom:4px;">'+biasArrow+'</div>' +
      '<div style="font-size:10px;color:var(--muted);margin-bottom:2px;">Confidence: '+conf+'%</div>' +
      '<div style="background:var(--border);border-radius:3px;height:5px;overflow:hidden;"><div style="width:'+conf+'%;height:100%;background:'+confColor+';border-radius:3px;transition:width 0.4s;"></div></div>' +
      extra + '<div style="font-size:9px;color:var(--muted);margin-top:6px;opacity:0.6;">Click for chart \u2192</div></div>';
  }).join('');
}

function switchToChart(symbol) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.querySelector('[data-tab="charts"]').classList.add('active');
  document.getElementById('tab-charts').classList.add('active');
  if(!chartInitialized) initChartTab();
  selectChartSymbol(symbol);
}

function renderRejections(rejections) {
  const tbody = document.getElementById('rejections-body');
  const tbodyMini = document.getElementById('rejections-body-mini');
  if(!rejections || rejections.length === 0) {
    if(tbody) tbody.innerHTML = '<tr><td colspan="8" class="empty">No rejected signals</td></tr>';
    if(tbodyMini) tbodyMini.innerHTML = '<tr><td colspan="4" class="empty">No rejections</td></tr>';
    return;
  }
  const hardGates = ['circuit_breaker','liquidation','max_positions'];
  const softGates = ['fee_drag','ev_floor','rr_floor','lev_ev_floor'];
  // Full table
  if(tbody) {
    tbody.innerHTML = rejections.slice(0,50).map(r => {
      const gate = (r.gate||'unknown').toLowerCase();
      let gateClass = 'gate-info';
      if(hardGates.includes(gate)) gateClass = 'gate-hard';
      else if(softGates.includes(gate)) gateClass = 'gate-soft';
      const cfPnl = r.counterfactual_pnl;
      const cfDisplay = (cfPnl!=null&&!isNaN(cfPnl)) ? '<span style="color:'+pnlColor(cfPnl)+';font-weight:600;">'+fmt$(cfPnl)+'</span>' : '<span style="color:var(--muted);">--</span>';
      return '<tr><td>'+fmtDateTime(r.timestamp)+'</td><td><strong>'+(r.symbol||'--')+'</strong></td><td>'+sidePill(r.side)+'</td><td>'+(r.confidence!=null?r.confidence.toFixed(0)+'%':'--')+'</td><td style="color:var(--muted)">'+(r.strategy||'--')+'</td><td><span class="gate-pill '+gateClass+'">'+gate.toUpperCase()+'</span></td><td style="color:var(--muted);font-size:11px;max-width:160px;overflow:hidden;text-overflow:ellipsis;" title="'+((r.reason||'').replace(/"/g,'&quot;'))+'">'+(r.reason||'--')+'</td><td>'+cfDisplay+'</td></tr>';
    }).join('');
  }
  // Mini table on overview
  if(tbodyMini) {
    tbodyMini.innerHTML = rejections.slice(0,10).map(r => {
      const gate = (r.gate||'unknown').toLowerCase();
      let gateClass = 'gate-info';
      if(hardGates.includes(gate)) gateClass = 'gate-hard';
      else if(softGates.includes(gate)) gateClass = 'gate-soft';
      return '<tr><td><strong>'+(r.symbol||'--')+'</strong></td><td>'+sidePill(r.side)+'</td><td><span class="gate-pill '+gateClass+'">'+gate.toUpperCase()+'</span></td><td style="color:var(--muted);font-size:11px;max-width:140px;overflow:hidden;text-overflow:ellipsis;">'+(r.reason||'--')+'</td></tr>';
    }).join('');
  }
}

function renderPipeline(pipelineData, targetId) {
  const el = document.getElementById(targetId);
  if(!el) return;
  if(!pipelineData || !pipelineData.total_signals) {
    el.innerHTML = '<div class="empty"><div class="empty-icon">\u26a1</div>No pipeline data yet<div class="empty-msg">Signal pipeline stats will appear once the bot generates signals</div></div>';
    return;
  }
  const total = pipelineData.total_signals || 0;
  const passed = pipelineData.passed || 0;
  const byGate = pipelineData.by_gate || {};
  const steps = [
    { label: 'Signals Generated', count: total, color: 'var(--blue)' },
  ];
  Object.entries(byGate).sort((a,b) => b[1]-a[1]).forEach(([gate, count]) => {
    steps.push({ label: gate.replace(/_/g,' '), count: count, color: 'var(--yellow)' });
  });
  steps.push({ label: 'Executed', count: passed, color: 'var(--green)' });

  const maxCount = Math.max(...steps.map(s => s.count), 1);
  el.innerHTML = steps.map(s => {
    const pct = Math.max(5, (s.count / maxCount) * 100);
    return '<div class="funnel-step"><div class="funnel-label">'+s.label+'</div><div class="funnel-bar-track"><div class="funnel-bar-fill" style="width:'+pct+'%;background:'+s.color+';color:#fff;">'+s.count+'</div></div></div>';
  }).join('');
}

function renderCopyTrade(data) {
  const container = document.getElementById('copytrade-content');
  if(!container) return;
  if(!data || !data.active) {
    container.innerHTML = '<div class="empty"><div class="empty-icon">\ud83e\udd16</div>LLM Intelligence Offline<div class="empty-msg">Enable multi-agent system (LLM_MULTI_AGENT=true) to activate AI analysis</div></div>';
    return;
  }
  let html = '';
  if(data.recommendation) {
    html += '<div style="background:var(--bg2);border-radius:8px;padding:14px;margin-bottom:12px;border-left:4px solid var(--purple);"><div style="color:var(--purple);font-size:10px;font-weight:700;margin-bottom:6px;">AI RECOMMENDATION</div><div style="color:var(--text);font-size:12px;">'+data.recommendation+'</div></div>';
  }
  if(data.insights && data.insights.length > 0) {
    const agentColors = { regime:'var(--blue)', trade:'var(--green)', risk:'var(--orange)', critic:'var(--red)', learning:'var(--purple)', exit:'var(--yellow)', scout:'var(--cyan)' };
    data.insights.forEach(ins => {
      const agent = (ins.agent||'unknown').toLowerCase();
      const color = agentColors[agent] || 'var(--muted)';
      html += '<div style="background:var(--bg2);border-radius:8px;padding:12px;margin-bottom:6px;border-left:3px solid '+color+';"><div style="display:flex;justify-content:space-between;"><span style="color:'+color+';font-size:10px;font-weight:700;text-transform:uppercase;">'+(ins.agent||'Agent')+'</span><span style="color:var(--muted);font-size:10px;">'+fmtTime(ins.timestamp)+'</span></div><div style="color:var(--text-dim);font-size:11px;margin-top:4px;">'+ins.summary+'</div></div>';
    });
  }
  container.innerHTML = html || '<div style="color:var(--muted);text-align:center;padding:15px;">Awaiting agent insights...</div>';
}

function renderStrategyBars(byStrategy) {
  const container = document.getElementById('strategy-bars');
  if(!byStrategy || Object.keys(byStrategy).length === 0) { container.innerHTML = '<div class="empty">No strategy data yet</div>'; return; }
  const entries = Object.entries(byStrategy).sort((a,b) => b[1].pnl - a[1].pnl);
  const maxAbs = Math.max(...entries.map(([_,s]) => Math.abs(s.pnl)), 1);
  container.innerHTML = entries.map(([name,s]) => {
    const wr = s.trades > 0 ? (s.wins/s.trades) : 0;
    const barPct = Math.min((Math.abs(s.pnl)/maxAbs)*100, 100);
    const barColor = s.pnl >= 0 ? 'var(--green)' : 'var(--red)';
    return '<div class="strat-row"><div class="strat-label">'+name+'</div><div class="strat-bar-track"><div class="strat-bar-fill" style="width:'+barPct+'%;background:'+barColor+';">'+(barPct>25?(wr*100).toFixed(0)+'% WR':'')+'</div></div><div class="strat-pnl" style="color:'+pnlColor(s.pnl)+'">'+fmt$(s.pnl)+'</div></div>';
  }).join('');
}

function renderWeights(weightsData) {
  const el = document.getElementById('strategy-weights');
  if(!el) return;
  if(!weightsData || Object.keys(weightsData).length === 0) { el.innerHTML = '<div class="empty">No weight data available</div>'; return; }
  const maxW = Math.max(...Object.values(weightsData), 1);
  el.innerHTML = Object.entries(weightsData).sort((a,b) => b[1]-a[1]).map(([name, w]) => {
    const pct = (w / maxW) * 100;
    return '<div class="strat-row"><div class="strat-label">'+name+'</div><div class="strat-bar-track"><div class="strat-bar-fill" style="width:'+pct+'%;background:var(--cyan);">'+w.toFixed(2)+'</div></div></div>';
  }).join('');
}

function renderCircuitBreakers(riskData) {
  const el = document.getElementById('cb-status');
  if(!el) return;
  if(!riskData) { el.innerHTML = '<div class="empty">Risk data unavailable</div>'; return; }
  const tripped = riskData.cb_tripped;
  let html = '';
  if(tripped) {
    html += '<div style="background:var(--red-dim);border:1px solid rgba(255,68,102,0.3);border-radius:8px;padding:12px;margin-bottom:12px;text-align:center;"><span style="color:var(--red);font-weight:800;font-size:14px;">\u26a0 CIRCUIT BREAKER TRIPPED</span></div>';
  }
  const gauges = [
    { label: 'Daily PnL', current: Math.abs(riskData.daily_pnl||0), max: Math.abs(riskData.daily_limit||100), unit: '\u0024', color: (riskData.daily_pnl||0) < 0 ? 'var(--red)' : 'var(--green)' },
    { label: 'Consecutive Losses', current: riskData.consecutive_losses||0, max: riskData.max_consecutive||5, unit: '', color: (riskData.consecutive_losses||0) >= (riskData.max_consecutive||5)*0.7 ? 'var(--yellow)' : 'var(--green)' },
    { label: 'Drawdown', current: Math.abs(riskData.drawdown_pct||0), max: 10, unit: '%', color: Math.abs(riskData.drawdown_pct||0) > 5 ? 'var(--red)' : 'var(--green)' },
  ];
  gauges.forEach(g => {
    const pct = Math.min((g.current / g.max) * 100, 100);
    html += '<div class="cb-row"><div class="cb-label">'+g.label+'</div><div class="cb-bar"><div class="cb-fill" style="width:'+pct+'%;background:'+g.color+';"></div></div><div class="cb-value" style="color:'+g.color+';">'+g.current.toFixed(g.unit==='\u0024'?2:0)+g.unit+' / '+g.max+g.unit+'</div></div>';
  });
  el.innerHTML = html;
}

function renderActiveSignals(signalData) {
  const el = document.getElementById('active-signals-list');
  if(!el) return;
  if(!signalData || signalData.length === 0) {
    el.innerHTML = '<div class="empty"><div class="empty-icon">\ud83d\udce1</div>No active signals right now<div class="empty-msg">The bot evaluates signals each scan cycle (~30s)</div></div>';
    return;
  }
  el.innerHTML = signalData.map(s => {
    const isLong = (s.side||'').toUpperCase() === 'BUY';
    const conf = s.confidence || 0;
    const confColor = conf>70?'var(--green)':conf>40?'var(--yellow)':'var(--red)';
    const strategies = s.strategies_agreeing || 0;
    const totalStrats = 4;
    let confluenceBars = '';
    for(let i=0; i<totalStrats; i++) {
      confluenceBars += '<div class="confluence-bar '+(i<strategies?'filled':'')+'"></div>';
    }
    return '<div class="signal-card">' +
      '<div class="signal-header"><div style="display:flex;align-items:center;gap:10px;"><span class="signal-sym">'+(s.symbol||'--')+'</span>'+sidePill(s.side)+'</div>' +
      '<div class="signal-conf" style="color:'+confColor+';">'+conf.toFixed(0)+'%</div></div>' +
      '<div style="font-size:11px;color:var(--text-dim);margin-bottom:8px;">'+(s.signal_context||s.reason||'Signal generated by ensemble')+'</div>' +
      '<div style="display:flex;gap:16px;font-size:11px;margin-bottom:8px;">' +
      '<span>Entry: <strong>'+fmtPrice(s.entry)+'</strong></span>' +
      '<span>SL: <strong style="color:var(--red);">'+fmtPrice(s.sl)+'</strong></span>' +
      '<span>TP1: <strong style="color:var(--green);">'+fmtPrice(s.tp1)+'</strong></span>' +
      '<span>TP2: <strong style="color:var(--green);">'+fmtPrice(s.tp2)+'</strong></span></div>' +
      '<div style="display:flex;align-items:center;gap:8px;font-size:10px;color:var(--muted);">' +
      '<span>Confluence: '+strategies+'/'+totalStrats+'</span><div class="confluence-meter">'+confluenceBars+'</div>' +
      '<span style="margin-left:auto;">'+((s.strategy||''))+'</span></div></div>';
  }).join('');
}

/* ═══════════════════════════════════════════════════════════════════ */
/* DATA LOADING                                                       */
/* ═══════════════════════════════════════════════════════════════════ */

async function loadAll() {
  try {
    const [dataRes, healthRes, marketRes, rejectionsRes, pipelineRes] = await Promise.allSettled([
      fetch('/api/data'), fetch('/api/health'), fetch('/api/market'), fetch('/api/rejections'), fetch('/api/pipeline')
    ]);
    let data=null, healthInfo=null, market=null, rejections=null, pipeline=null;
    if(dataRes.status==='fulfilled' && dataRes.value.ok) try { data = await dataRes.value.json(); } catch {}
    if(healthRes.status==='fulfilled' && healthRes.value.ok) try { healthInfo = await healthRes.value.json(); } catch {}
    if(marketRes.status==='fulfilled' && marketRes.value.ok) try { market = await marketRes.value.json(); } catch {}
    if(rejectionsRes.status==='fulfilled' && rejectionsRes.value.ok) try { rejections = await rejectionsRes.value.json(); } catch {}
    if(pipelineRes.status==='fulfilled' && pipelineRes.value.ok) try { pipeline = await pipelineRes.value.json(); } catch {}

    if(data) {
      const ds = data.daily_summary || {};
      const rt = data.recent_trades || [];
      const eq = data.equity_curve || [];
      const sp = data.signal_performance || {};
      const positions = data.positions || [];

      // Top bar equity ticker
      const lastEq = eq.length > 0 ? eq[eq.length-1] : {};
      const equity = lastEq.equity || 0;
      document.getElementById('kpi-equity').textContent = '\u0024'+equity.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
      document.getElementById('top-equity').textContent = '\u0024'+equity.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
      document.getElementById('top-equity').style.color = pnlColor(equity > 0 ? 1 : 0);
      if(eq.length>=2) { const prevEq=eq[0].equity||equity; const change=equity-prevEq; const changePct=prevEq>0?((change/prevEq)*100).toFixed(2):'0.00'; const el=document.getElementById('kpi-equity-change'); el.textContent=fmt$(change)+' ('+changePct+'% 30d)'; el.style.color=pnlColor(change); }

      const pnl = ds.net_pnl || 0;
      const pnlEl = document.getElementById('kpi-pnl'); pnlEl.textContent = fmt$(pnl); pnlEl.className = 'metric ' + pnlClass(pnl);
      document.getElementById('kpi-pnl-detail').textContent = (ds.total_trades||0)+' trades | \u0024'+(ds.total_fees||0).toFixed(2)+' fees';
      const wr = (ds.win_rate||0)*100; const wrEl = document.getElementById('kpi-winrate'); wrEl.textContent = wr.toFixed(1)+'%'; wrEl.className = 'metric '+(wr>=50?'green':(wr>0?'red':''));
      document.getElementById('wr-bar').style.width = wr+'%'; document.getElementById('wr-bar').style.background = wr>=50?'var(--green)':'var(--red)';
      document.getElementById('kpi-wl').textContent = (ds.wins||0)+'W / '+(ds.losses||0)+'L';

      renderPositions(positions);

      // Signal Performance
      const byStrat = sp.by_strategy || {}; const ssBody = document.getElementById('signal-strat-body');
      if(Object.keys(byStrat).length > 0) { ssBody.innerHTML = Object.entries(byStrat).sort((a,b) => b[1].pnl-a[1].pnl).map(([name,s]) => '<tr><td><strong>'+name+'</strong></td><td>'+s.trades+'</td><td>'+(s.wins||0)+'</td><td><span class="pill '+(s.win_rate>=0.5?'pill-win':'pill-loss')+'">'+(s.win_rate*100).toFixed(1)+'%</span></td><td style="color:'+pnlColor(s.pnl)+';font-weight:600">'+fmt$(s.pnl)+'</td><td>'+(s.avg_score||0).toFixed(1)+'</td></tr>').join(''); }
      const bySym = sp.by_symbol || {}; const symBody = document.getElementById('signal-sym-body');
      if(Object.keys(bySym).length > 0) { symBody.innerHTML = Object.entries(bySym).sort((a,b) => b[1].pnl-a[1].pnl).map(([sym,s]) => '<tr><td><strong>'+sym+'</strong></td><td>'+s.trades+'</td><td>'+(s.wins||0)+'</td><td><span class="pill '+(s.win_rate>=0.5?'pill-win':'pill-loss')+'">'+(s.win_rate*100).toFixed(1)+'%</span></td><td style="color:'+pnlColor(s.pnl)+';font-weight:600">'+fmt$(s.pnl)+'</td></tr>').join(''); }

      // Recent Trades
      const tBody = document.getElementById('trades-body');
      if(rt.length > 0) {
        tBody.innerHTML = rt.map(t => '<tr><td>'+fmtDateTime(t.timestamp)+'</td><td><strong>'+(t.symbol||'--')+'</strong></td><td>'+sidePill(t.side)+'</td><td><span class="pill pill-action">'+(t.action||'--')+'</span></td><td>'+fmtPrice(t.price)+'</td><td style="color:'+pnlColor(t.pnl||0)+';font-weight:600">'+fmt$(t.pnl||0)+'</td><td style="color:var(--muted)">'+(t.strategy||'')+'</td></tr>').join('');
        // Trade stats
        const wins = rt.filter(t => (t.pnl||0) > 0);
        const losses = rt.filter(t => (t.pnl||0) < 0);
        document.getElementById('ts-total').textContent = rt.length;
        const avgWin = wins.length > 0 ? wins.reduce((a,t) => a+(t.pnl||0), 0)/wins.length : 0;
        const avgLoss = losses.length > 0 ? losses.reduce((a,t) => a+(t.pnl||0), 0)/losses.length : 0;
        document.getElementById('ts-avg-win').textContent = fmt$(avgWin);
        document.getElementById('ts-avg-loss').textContent = fmt$(avgLoss);
        const grossWin = wins.reduce((a,t) => a+(t.pnl||0), 0);
        const grossLoss = Math.abs(losses.reduce((a,t) => a+(t.pnl||0), 0));
        document.getElementById('ts-pf').textContent = grossLoss > 0 ? (grossWin/grossLoss).toFixed(2) : '--';
      }

      renderStrategyBars(ds.by_strategy || {});
      if(data.copytrade) renderCopyTrade(data.copytrade);
    }

    if(healthInfo) {
      const uptime = healthInfo.uptime_seconds || 0;
      document.getElementById('health-uptime').textContent = fmtDuration(uptime);
      document.getElementById('health-started').textContent = 'Started: '+(healthInfo.started_at||'--');
      document.getElementById('health-heartbeat').textContent = healthInfo.last_heartbeat || '--';
      if(healthInfo.heartbeat_age_s != null) { const age=healthInfo.heartbeat_age_s; const ageEl=document.getElementById('health-heartbeat-ago'); ageEl.textContent=fmtDuration(age)+' ago'; ageEl.style.color=age>300?'var(--red)':(age>120?'var(--yellow)':'var(--muted)'); }
      const errCount = healthInfo.error_count||0; const warnCount = healthInfo.warning_count||0;
      const errEl = document.getElementById('health-errors'); errEl.textContent = errCount; errEl.className = 'metric '+(errCount>0?'red':'green');
      document.getElementById('health-warnings').textContent = warnCount + ' warnings';
      document.getElementById('uptime-display').textContent = 'Up: '+fmtDuration(uptime);
      const dot = document.getElementById('health-dot'); const label = document.getElementById('health-label');
      if(errCount>0) { dot.className='dot dot-red'; label.textContent=errCount+' error(s)'; }
      else if(warnCount>0) { dot.className='dot dot-yellow'; label.textContent='Warnings'; }
      else { dot.className='dot dot-green'; label.textContent='Healthy'; }
    }

    renderHeatmap(market);
    renderRejections(rejections);
    renderPipeline(pipeline, 'pipeline-funnel');
    renderPipeline(pipeline, 'pipeline-funnel-full');

    // System Activity Status
    var actEl = document.getElementById('system-activity-status');
    var dotEl = document.getElementById('system-activity-dot');
    if(actEl) {
      var executed = pipeline ? (pipeline.executed || 0) : 0;
      var generated = pipeline ? (pipeline.generated || 0) : 0;
      var lastTrade = rt && rt.length > 0 ? rt[0] : null;
      var regimes = market && Array.isArray(market) ? market.map(function(m) { return (m.symbol||'?') + ': ' + (m.regime||'unknown'); }).join(' | ') : 'No regime data';
      var statusParts = [];
      if(executed > 0) { statusParts.push('\u2705 ' + executed + ' trade(s) executed today'); if(dotEl) dotEl.style.background='var(--green)'; }
      else if(generated > 0) { statusParts.push('\u26A0 ' + generated + ' signals generated but none passed all gates'); if(dotEl) dotEl.style.background='var(--yellow)'; }
      else { statusParts.push('\uD83D\uDD0D Scanning for setups \u2014 no signals yet this cycle'); if(dotEl) dotEl.style.background='var(--cyan)'; }
      statusParts.push('\uD83C\uDF0D Regimes: ' + regimes);
      if(lastTrade) { statusParts.push('\u23F1 Last trade: ' + (lastTrade.symbol||'--') + ' ' + fmtDateTime(lastTrade.timestamp)); }
      actEl.innerHTML = statusParts.map(function(s) { return '<div style="margin-bottom:3px;">' + s + '</div>'; }).join('');
    }
    document.getElementById('last-refresh').textContent = new Date().toLocaleTimeString();
  } catch(err) {
    console.error('Dashboard load error:', err);
    document.getElementById('health-dot').className = 'dot dot-red';
    document.getElementById('health-label').textContent = 'Connection error';
  }
}

async function refreshPositionsOnly() {
  try { const res = await fetch('/api/positions'); if(res.ok) { const positions = await res.json(); renderPositions(positions); } } catch {}
}

async function loadAnalytics() {
  analyticsInitialized = true;
  // Load weights and risk data
  const [weightsRes, riskRes, perfRes] = await Promise.allSettled([
    fetch('/api/weights'), fetch('/api/risk'), fetch('/api/performance')
  ]);
  if(weightsRes.status==='fulfilled' && weightsRes.value.ok) { try { renderWeights(await weightsRes.value.json()); } catch {} }
  if(riskRes.status==='fulfilled' && riskRes.value.ok) { try { renderCircuitBreakers(await riskRes.value.json()); } catch {} }
  // Equity chart
  try { const eqRes = await fetch('/api/equity'); if(eqRes.ok) { const eq = await eqRes.json(); if(eq.length >= 2) buildEquityChart(eq); } } catch {}
  // Daily PnL chart
  if(perfRes.status==='fulfilled' && perfRes.value.ok) {
    try {
      const perf = await perfRes.value.json();
      if(Array.isArray(perf) && perf.length > 0) {
        const canvas = document.getElementById('daily-pnl-chart');
        if(canvas) {
          const ctx = canvas.getContext('2d');
          const labels = perf.map(d => d.date || '');
          const pnls = perf.map(d => d.pnl || 0);
          const colors = pnls.map(v => v >= 0 ? 'rgba(0,230,160,0.8)' : 'rgba(255,68,102,0.8)');
          dailyPnlChart = new Chart(ctx, {
            type:'bar', data:{ labels, datasets:[{ data:pnls, backgroundColor:colors, borderRadius:4 }] },
            options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}}, scales:{x:{grid:{display:false},ticks:{color:'#5e5e80',font:{size:10,family:'monospace'}}},y:{grid:{color:'rgba(26,26,53,0.5)'},ticks:{color:'#5e5e80',callback:v=>'\u0024'+v}}} }
          });
        }
      }
    } catch {}
  }
}

async function loadSystemTab() {
  const [riskRes, gatesRes] = await Promise.allSettled([
    fetch('/api/risk'), fetch('/api/gates')
  ]);
  if(riskRes.status==='fulfilled' && riskRes.value.ok) { try { renderCircuitBreakers(await riskRes.value.json()); } catch {} }
  if(gatesRes.status==='fulfilled' && gatesRes.value.ok) {
    try {
      const gates = await gatesRes.value.json();
      const el = document.getElementById('gates-status');
      if(el && gates) {
        el.innerHTML = Object.entries(gates).map(([name, g]) => {
          const passed = g.passed || g.status === 'pass';
          const val = g.current != null ? g.current : '--';
          const thresh = g.threshold != null ? g.threshold : '--';
          return '<div style="display:flex;align-items:center;gap:10px;padding:8px;background:var(--bg2);border-radius:6px;margin-bottom:6px;border-left:3px solid '+(passed?'var(--green)':'var(--red)')+';"><div style="flex:1;"><div style="font-weight:600;font-size:12px;">'+name.replace(/_/g,' ')+'</div><div style="font-size:10px;color:var(--muted);">Current: '+val+' / Threshold: '+thresh+'</div></div><span class="pill '+(passed?'pill-win':'pill-loss')+'">'+(passed?'PASS':'FAIL')+'</span></div>';
        }).join('');
      }
    } catch {}
  }
}

/* ═══════════════════════════════════════════════════════════════════ */
/* CDN FALLBACK DETECTION                                             */
/* ═══════════════════════════════════════════════════════════════════ */
function showChartFallback(containerId, libName) {
  const el = document.getElementById(containerId);
  if(el) el.innerHTML = '<div class="empty" style="padding:40px;"><div class="empty-icon">&#128200;</div><div style="font-size:14px;font-weight:700;margin-bottom:8px;">Charts Unavailable</div><div class="empty-msg">Could not load '+libName+'. Check your internet connection.</div><button onclick="location.reload()" style="margin-top:12px;padding:8px 20px;background:var(--blue-dim);border:1px solid var(--blue);color:var(--blue);border-radius:6px;cursor:pointer;font-family:inherit;font-weight:600;">Retry</button></div>';
}
window.addEventListener('load', function() {
  if(window._chartJsFailed || typeof Chart === 'undefined') {
    showChartFallback('equity-chart', 'Chart.js');
    showChartFallback('daily-pnl-chart', 'Chart.js');
  }
  if(window._lwcFailed || typeof LightweightCharts === 'undefined') {
    showChartFallback('main-chart-container', 'TradingView Charts');
  }
});

/* ═══════════════════════════════════════════════════════════════════ */
/* TAB HELPER                                                         */
/* ═══════════════════════════════════════════════════════════════════ */
function switchToTab(tabName) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  const btn = document.querySelector('[data-tab="'+tabName+'"]');
  if(btn) btn.classList.add('active');
  const tab = document.getElementById('tab-'+tabName);
  if(tab) tab.classList.add('active');
}

/* ═══════════════════════════════════════════════════════════════════ */
/* CORRELATION HEATMAP (Overview Tab)                                 */
/* ═══════════════════════════════════════════════════════════════════ */
async function loadCorrelation() {
  try {
    const res = await fetch('/api/correlation');
    if(!res.ok) return;
    const data = await res.json();
    const el = document.getElementById('correlation-heatmap');
    if(!el || !data.symbols || data.symbols.length === 0) { if(el) el.innerHTML='<div class="empty">No correlation data available</div>'; return; }
    const syms = data.symbols;
    const matrix = data.matrix || {};
    let html = '<div style="overflow-x:auto;"><table style="font-size:11px;"><thead><tr><th></th>';
    syms.forEach(s => { html += '<th style="text-align:center;min-width:60px;">'+s+'</th>'; });
    html += '</tr></thead><tbody>';
    syms.forEach((s1,i) => {
      html += '<tr><td style="font-weight:700;">'+s1+'</td>';
      syms.forEach((s2,j) => {
        const key = s1+'_'+s2;
        const val = (matrix[key] != null) ? matrix[key] : (i===j ? 1.0 : 0);
        const abs = Math.abs(val);
        let bg;
        if(i===j) bg = 'var(--cyan-dim)';
        else if(val > 0.5) bg = 'rgba(255,68,102,'+(abs*0.4).toFixed(2)+')';
        else if(val > 0) bg = 'rgba(255,196,68,'+(abs*0.3).toFixed(2)+')';
        else bg = 'rgba(0,230,160,'+(abs*0.3).toFixed(2)+')';
        html += '<td style="text-align:center;background:'+bg+';font-weight:600;padding:6px;">'+val.toFixed(2)+'</td>';
      });
      html += '</tr>';
    });
    html += '</tbody></table></div>';
    if(data.diversification_score != null) {
      html += '<div style="margin-top:12px;font-size:12px;">Portfolio Diversification Score: <strong style="color:var(--cyan);">'+data.diversification_score.toFixed(0)+'/100</strong></div>';
    }
    el.innerHTML = html;
  } catch(e) { console.error('Correlation load error:', e); }
}

/* ═══════════════════════════════════════════════════════════════════ */
/* MISSED TRADE ALPHA (Signals Tab)                                   */
/* ═══════════════════════════════════════════════════════════════════ */
async function loadMissedTrades() {
  try {
    const res = await fetch('/api/missed-trades');
    if(!res.ok) return;
    const data = await res.json();
    const trades = data.trades || [];
    const tbody = document.getElementById('missed-trades-body');

    // Summary stats
    const missedWins = trades.filter(t => t.would_have_won);
    const totalMissedPnl = missedWins.reduce((a,t) => a + (t.missed_pnl||0), 0);
    document.getElementById('missed-alpha-total').textContent = fmt$(totalMissedPnl);
    document.getElementById('missed-win-count').textContent = missedWins.length;
    document.getElementById('missed-win-pct').textContent = trades.length > 0 ? ((missedWins.length/trades.length)*100).toFixed(0)+'% of rejections profitable' : '0% of rejections profitable';
    document.getElementById('missed-correct-count').textContent = trades.length - missedWins.length;

    if(!tbody || trades.length === 0) { if(tbody) tbody.innerHTML='<tr><td colspan="7" class="empty">No missed trade data available</td></tr>'; return; }
    tbody.innerHTML = trades.slice(0,30).map(t => {
      const won = t.would_have_won;
      const rowBg = won ? 'rgba(0,230,160,0.03)' : '';
      return '<tr style="background:'+rowBg+';"><td>'+fmtDateTime(t.timestamp)+'</td><td><strong>'+(t.symbol||'--')+'</strong></td><td>'+sidePill(t.side)+'</td><td>'+(t.confidence!=null?t.confidence.toFixed(0)+'%':'--')+'</td><td><span class="gate-pill '+(won?'gate-soft':'gate-info')+'">'+(t.gate||'--').toUpperCase()+'</span></td><td><span style="color:'+(won?'var(--green)':'var(--muted)')+';font-weight:600;">'+(won?'YES':'NO')+'</span></td><td style="color:'+pnlColor(t.missed_pnl||0)+';font-weight:600;">'+fmt$(t.missed_pnl||0)+'</td></tr>';
    }).join('');
  } catch(e) { console.error('Missed trades error:', e); }
}

/* ═══════════════════════════════════════════════════════════════════ */
/* TRADE OUTCOME BREAKDOWN (Trades Tab)                               */
/* ═══════════════════════════════════════════════════════════════════ */
async function loadOutcomes() {
  try {
    const res = await fetch('/api/outcomes');
    if(!res.ok) return;
    const data = await res.json();
    const outcomes = data.outcomes || {};
    const distEl = document.getElementById('outcome-distribution');
    const pnlEl = document.getElementById('outcome-pnl-table');
    if(Object.keys(outcomes).length === 0) { return; }

    const outcomeColors = { CLEAN_WIN:'var(--green)', TP1_ONLY:'var(--cyan)', TRAILING_WIN:'var(--blue)', EARLY_EXIT_SAVE:'var(--yellow)', CLEAN_LOSS:'var(--red)', TP1_THEN_SL:'var(--orange)', SL_HIT:'var(--red)', OTHER:'var(--muted)' };
    const total = Object.values(outcomes).reduce((a,o) => a + (o.count||0), 0) || 1;

    // Visual distribution bars
    let html = '';
    Object.entries(outcomes).sort((a,b) => b[1].count - a[1].count).forEach(([name, o]) => {
      const pct = ((o.count||0)/total*100).toFixed(1);
      const color = outcomeColors[name] || 'var(--muted)';
      html += '<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;"><div style="width:120px;font-size:11px;text-align:right;color:'+color+';font-weight:600;">'+name.replace(/_/g,' ')+'</div><div style="flex:1;height:20px;background:var(--border);border-radius:5px;overflow:hidden;"><div style="width:'+pct+'%;height:100%;background:'+color+';border-radius:5px;display:flex;align-items:center;padding:0 8px;font-size:10px;font-weight:700;color:#fff;">'+(pct>8?pct+'%':'')+'</div></div><div style="width:40px;font-size:11px;text-align:right;font-weight:700;">'+o.count+'</div></div>';
    });
    if(distEl) distEl.innerHTML = html;

    // PnL table
    let tblHtml = '<table><thead><tr><th>Exit Type</th><th>Count</th><th>Avg PnL</th><th>Total PnL</th></tr></thead><tbody>';
    Object.entries(outcomes).sort((a,b) => (b[1].total_pnl||0) - (a[1].total_pnl||0)).forEach(([name, o]) => {
      const color = outcomeColors[name] || 'var(--muted)';
      tblHtml += '<tr><td style="color:'+color+';font-weight:600;">'+name.replace(/_/g,' ')+'</td><td>'+o.count+'</td><td style="color:'+pnlColor(o.avg_pnl||0)+'">'+fmt$(o.avg_pnl||0)+'</td><td style="color:'+pnlColor(o.total_pnl||0)+';font-weight:600;">'+fmt$(o.total_pnl||0)+'</td></tr>';
    });
    tblHtml += '</tbody></table>';
    if(pnlEl) pnlEl.innerHTML = tblHtml;
  } catch(e) { console.error('Outcomes error:', e); }
}

/* ═══════════════════════════════════════════════════════════════════ */
/* STRATEGY FINGERPRINTS (Analytics Tab)                              */
/* ═══════════════════════════════════════════════════════════════════ */
async function loadFingerprints() {
  try {
    const res = await fetch('/api/fingerprints');
    if(!res.ok) return;
    const data = await res.json();

    function renderHeatmapGrid(container, rowLabel, colLabel, matrix) {
      const el = document.getElementById(container);
      if(!el || !matrix || Object.keys(matrix).length === 0) { if(el) el.innerHTML='<div class="empty">No data yet</div>'; return; }
      const rows = [...new Set(Object.keys(matrix).map(k => k.split('|')[0]))];
      const cols = [...new Set(Object.keys(matrix).map(k => k.split('|')[1]))];
      let html = '<table style="font-size:11px;"><thead><tr><th>'+rowLabel+'</th>';
      cols.forEach(c => { html += '<th style="text-align:center;min-width:70px;">'+c+'</th>'; });
      html += '</tr></thead><tbody>';
      rows.forEach(r => {
        html += '<tr><td style="font-weight:700;">'+r+'</td>';
        cols.forEach(c => {
          const key = r+'|'+c;
          const cell = matrix[key];
          if(cell) {
            const wr = cell.win_rate != null ? cell.win_rate : 0;
            const n = cell.trades || 0;
            const bg = n===0 ? 'transparent' : (wr >= 0.6 ? 'rgba(0,230,160,'+(0.1+wr*0.3).toFixed(2)+')' : (wr >= 0.4 ? 'rgba(255,196,68,0.15)' : 'rgba(255,68,102,'+(0.1+(1-wr)*0.3).toFixed(2)+')'));
            html += '<td style="text-align:center;background:'+bg+';font-weight:600;" title="'+n+' trades, '+fmt$(cell.pnl||0)+' PnL">'+(n>0?(wr*100).toFixed(0)+'%':'')+'<div style="font-size:9px;color:var(--muted);">'+n+'</div></td>';
          } else {
            html += '<td style="text-align:center;color:var(--muted);">-</td>';
          }
        });
        html += '</tr>';
      });
      html += '</tbody></table>';
      el.innerHTML = html;
    }

    renderHeatmapGrid('fingerprint-symbol', 'Strategy', 'Symbol', data.by_symbol);
    renderHeatmapGrid('fingerprint-regime', 'Strategy', 'Regime', data.by_regime);
  } catch(e) { console.error('Fingerprints error:', e); }
}

/* ═══════════════════════════════════════════════════════════════════ */
/* REGIME TIMELINE (Analytics Tab)                                    */
/* ═══════════════════════════════════════════════════════════════════ */
async function loadRegimeTimeline() {
  try {
    const res = await fetch('/api/regimes/history');
    if(!res.ok) return;
    const data = await res.json();
    const el = document.getElementById('regime-timeline');
    if(!el) return;
    const periods = data.periods || [];
    const transitions = data.transitions || {};
    if(periods.length === 0) { el.innerHTML = '<div class="empty">No regime history available</div>'; return; }

    const regimeColors = { trend:'var(--green)', range:'var(--yellow)', panic:'var(--red)', high_volatility:'var(--orange)', low_liquidity:'var(--purple)', consolidation:'var(--blue)', unknown:'var(--muted)' };

    // Timeline blocks
    let html = '<div style="display:flex;height:40px;border-radius:6px;overflow:hidden;margin-bottom:16px;">';
    const totalDur = periods.reduce((a,p) => a + (p.duration_h||1), 0) || 1;
    periods.forEach(p => {
      const pct = ((p.duration_h||1)/totalDur*100).toFixed(1);
      const color = regimeColors[p.regime] || 'var(--muted)';
      html += '<div style="width:'+pct+'%;background:'+color+'33;border-right:1px solid var(--bg);display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;color:'+color+';overflow:hidden;white-space:nowrap;" title="'+p.regime+' ('+p.duration_h+'h)">'+((pct>8)?p.regime.substring(0,6):'')+'</div>';
    });
    html += '</div>';

    // Legend
    html += '<div style="display:flex;gap:14px;flex-wrap:wrap;font-size:11px;margin-bottom:16px;">';
    Object.entries(regimeColors).forEach(([r,c]) => {
      html += '<span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;border-radius:3px;background:'+c+';"></span>'+r+'</span>';
    });
    html += '</div>';

    // Transition matrix (if available)
    if(Object.keys(transitions).length > 0) {
      const regimes = [...new Set([...Object.keys(transitions).map(k => k.split('->')[0]),...Object.keys(transitions).map(k => k.split('->')[1])])];
      html += '<div style="font-size:11px;font-weight:700;margin-bottom:8px;color:var(--muted);">TRANSITION FREQUENCY</div>';
      html += '<table style="font-size:11px;"><thead><tr><th>From \\ To</th>';
      regimes.forEach(r => { html += '<th style="text-align:center;">'+r.substring(0,6)+'</th>'; });
      html += '</tr></thead><tbody>';
      regimes.forEach(from => {
        html += '<tr><td style="font-weight:700;">'+from+'</td>';
        regimes.forEach(to => {
          const count = transitions[from+'->'+to] || 0;
          const bg = count > 0 ? 'rgba(34,211,238,'+(Math.min(count/10,0.4)).toFixed(2)+')' : 'transparent';
          html += '<td style="text-align:center;background:'+bg+';font-weight:'+(count>0?'700':'400')+';">'+(count||'-')+'</td>';
        });
        html += '</tr>';
      });
      html += '</tbody></table>';
    }
    el.innerHTML = html;
  } catch(e) { console.error('Regime timeline error:', e); }
}

/* ═══════════════════════════════════════════════════════════════════ */
/* CALIBRATION CURVES (Analytics Tab)                                 */
/* ═══════════════════════════════════════════════════════════════════ */
async function loadCalibration() {
  try {
    const res = await fetch('/api/calibration');
    if(!res.ok) return;
    const data = await res.json();
    const el = document.getElementById('calibration-chart-container');
    if(!el) return;
    const buckets = data.buckets || [];
    if(buckets.length === 0) { el.innerHTML='<div class="empty">Not enough data for calibration</div>'; return; }

    // Render as pure HTML/CSS bar chart (no Chart.js dependency)
    let html = '<div style="display:flex;gap:20px;align-items:flex-end;height:200px;padding:10px 0;">';
    buckets.forEach(b => {
      const predicted = b.predicted || 0;
      const actual = b.actual || 0;
      const n = b.trades || 0;
      const predH = predicted * 1.8;
      const actH = actual * 1.8;
      html += '<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;">' +
        '<div style="display:flex;gap:2px;align-items:flex-end;height:160px;">' +
        '<div style="width:16px;height:'+predH+'px;background:var(--blue);border-radius:3px 3px 0 0;opacity:0.5;" title="Predicted: '+predicted.toFixed(0)+'%"></div>' +
        '<div style="width:16px;height:'+actH+'px;background:'+(actual>=predicted?'var(--green)':'var(--red)') +';border-radius:3px 3px 0 0;" title="Actual: '+actual.toFixed(0)+'%"></div></div>' +
        '<div style="font-size:9px;color:var(--muted);">'+predicted.toFixed(0)+'%</div>' +
        '<div style="font-size:8px;color:var(--muted);">n='+n+'</div></div>';
    });
    html += '</div>';
    html += '<div style="display:flex;gap:16px;font-size:11px;margin-top:8px;"><span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;background:var(--blue);opacity:0.5;border-radius:2px;"></span>Predicted</span><span style="display:flex;align-items:center;gap:4px;"><span style="width:10px;height:10px;background:var(--green);border-radius:2px;"></span>Actual Win Rate</span></div>';
    if(data.brier_score != null) {
      html += '<div style="margin-top:8px;font-size:12px;">Brier Score: <strong style="color:var(--cyan);">'+data.brier_score.toFixed(4)+'</strong> <span style="color:var(--muted);font-size:10px;">(lower is better, 0 = perfect)</span></div>';
    }
    el.innerHTML = html;
  } catch(e) { console.error('Calibration error:', e); }
}

/* ═══════════════════════════════════════════════════════════════════ */
/* AGENT DECISION PIPELINE (System Tab)                               */
/* ═══════════════════════════════════════════════════════════════════ */
async function loadAgentPipeline() {
  try {
    const res = await fetch('/api/agents/last');
    if(!res.ok) return;
    const data = await res.json();
    const el = document.getElementById('agent-pipeline');
    if(!el) return;
    if(!data.active) { el.innerHTML='<div class="empty"><div class="empty-icon">&#129302;</div>Multi-Agent System Offline<div class="empty-msg">Enable with LLM_MULTI_AGENT=true</div></div>'; return; }

    const agents = data.agents || [];
    if(agents.length === 0) { el.innerHTML='<div class="empty">No agent decisions recorded yet</div>'; return; }

    const agentColors = { regime:'var(--blue)', trade:'var(--green)', risk:'var(--orange)', critic:'var(--red)', learning:'var(--purple)', exit:'var(--yellow)', scout:'var(--cyan)' };
    const actionColors = { proceed:'var(--green)', go:'var(--green)', skip:'var(--muted)', veto:'var(--red)', flat:'var(--muted)', hold:'var(--yellow)', adjust:'var(--orange)', close:'var(--red)' };

    // Pipeline flow
    let html = '<div style="display:flex;gap:8px;overflow-x:auto;padding:10px 0;">';
    agents.forEach((a,i) => {
      const color = agentColors[(a.agent||'').toLowerCase()] || 'var(--muted)';
      const action = (a.action||a.decision||'--').toLowerCase();
      const actColor = actionColors[action] || 'var(--muted)';
      html += '<div style="flex:0 0 auto;min-width:140px;background:var(--bg2);border:1px solid var(--border);border-top:3px solid '+color+';border-radius:8px;padding:12px;">' +
        '<div style="font-size:10px;font-weight:700;text-transform:uppercase;color:'+color+';margin-bottom:6px;">'+(a.agent||'Agent')+'</div>' +
        '<div style="font-size:9px;color:var(--muted);margin-bottom:4px;">'+(a.model||'')+'</div>' +
        '<div style="font-size:13px;font-weight:800;color:'+actColor+';margin-bottom:4px;">'+(a.action||a.decision||'--').toUpperCase()+'</div>' +
        (a.confidence != null ? '<div style="font-size:10px;color:var(--text-dim);">Conf: '+a.confidence.toFixed(0)+'%</div>' : '') +
        (a.reasoning ? '<div style="font-size:10px;color:var(--muted);margin-top:6px;line-height:1.4;max-height:60px;overflow:hidden;">'+a.reasoning.substring(0,120)+'</div>' : '') +
        '</div>';
      if(i < agents.length - 1) html += '<div style="display:flex;align-items:center;color:var(--muted);font-size:18px;">&rarr;</div>';
    });
    html += '</div>';
    if(data.timestamp) html += '<div style="font-size:10px;color:var(--muted);margin-top:8px;">Last decision: '+fmtDateTime(data.timestamp)+'</div>';
    el.innerHTML = html;
  } catch(e) { console.error('Agent pipeline error:', e); }
}

/* ═══════════════════════════════════════════════════════════════════ */
/* LLM INSIGHT JOURNAL (System Tab)                                   */
/* ═══════════════════════════════════════════════════════════════════ */
let allInsights = [];
async function loadInsights() {
  try {
    const res = await fetch('/api/insights');
    if(!res.ok) return;
    const data = await res.json();
    allInsights = data.insights || [];
    renderInsights(allInsights);
  } catch(e) { console.error('Insights error:', e); }
}

function filterInsights(category) {
  document.querySelectorAll('#insight-filters .symbol-tab').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  if(category === 'all') renderInsights(allInsights);
  else renderInsights(allInsights.filter(i => (i.category||'').toLowerCase() === category));
}

function renderInsights(insights) {
  const el = document.getElementById('insight-journal-list');
  if(!el) return;
  if(!insights || insights.length === 0) { el.innerHTML='<div class="empty"><div class="empty-icon">&#128218;</div>No insights in this category</div>'; return; }
  const catColors = { strategy:'var(--green)', symbol:'var(--blue)', regime:'var(--orange)', timing:'var(--cyan)', risk:'var(--red)', correlation:'var(--purple)', execution:'var(--yellow)', meta:'var(--muted)' };
  el.innerHTML = insights.slice(0,50).map(i => {
    const cat = (i.category||'other').toLowerCase();
    const color = catColors[cat] || 'var(--muted)';
    const conf = i.confidence || 0;
    const status = i.validation_status || 'pending';
    const statusColor = status==='confirmed'?'var(--green)':(status==='rejected'?'var(--red)':'var(--yellow)');
    return '<div style="background:var(--bg2);border-radius:8px;padding:12px;margin-bottom:8px;border-left:3px solid '+color+';">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">' +
      '<span style="color:'+color+';font-size:10px;font-weight:700;text-transform:uppercase;">'+cat+'</span>' +
      '<div style="display:flex;gap:8px;align-items:center;"><span style="font-size:10px;color:'+statusColor+';font-weight:600;">'+status.toUpperCase()+'</span><span style="font-size:10px;color:var(--muted);">'+fmtDateTime(i.timestamp)+'</span></div></div>' +
      '<div style="font-size:12px;color:var(--text);margin-bottom:6px;">'+i.text+'</div>' +
      '<div style="display:flex;align-items:center;gap:6px;"><span style="font-size:10px;color:var(--muted);">Confidence:</span><div style="width:80px;height:5px;background:var(--border);border-radius:3px;"><div style="width:'+conf+'%;height:100%;background:'+color+';border-radius:3px;"></div></div><span style="font-size:10px;color:var(--muted);">'+conf.toFixed(0)+'%</span></div></div>';
  }).join('');
}

/* ═══════════════════════════════════════════════════════════════════ */
/* EDUCATIONAL TAB — LEARN (Course Dashboard)                         */
/* ═══════════════════════════════════════════════════════════════════ */

// ============================================================
// Course Navigation System & Core Renderers
// ============================================================

const COURSE_STEPS = ['step1', 'step2', 'step3', 'step4', 'step5', 'step6'];

// ---- Progress Tracking (localStorage) ----

function getCourseProgress() {
  try {
    var raw = localStorage.getItem('courseProgress');
    if (raw) {
      var parsed = JSON.parse(raw);
      return {
        quizzesPassed: parsed.quizzesPassed || {},
        checklistItems: parsed.checklistItems || {},
        practiceTrades: parsed.practiceTrades || []
      };
    }
  } catch (e) {
    console.warn('Failed to read courseProgress:', e);
  }
  return { quizzesPassed: {}, checklistItems: {}, practiceTrades: [] };
}

function saveCourseProgress(progress) {
  try {
    localStorage.setItem('courseProgress', JSON.stringify(progress));
  } catch (e) {
    console.warn('Failed to save courseProgress:', e);
  }
}

function getCompletedSteps() {
  var progress = getCourseProgress();
  var count = 0;
  COURSE_STEPS.forEach(function(step) {
    if (progress.quizzesPassed[step]) count++;
  });
  return count;
}

function updateProgressUI() {
  var completed = getCompletedSteps();
  var total = COURSE_STEPS.length;
  var pct = Math.round((completed / total) * 100);

  var barFill = document.querySelector('.progress-bar-fill');
  if (barFill) barFill.style.width = pct + '%';

  var label = document.querySelector('.progress-label');
  if (label) label.textContent = completed + '/' + total + ' steps completed (' + pct + '%)';

  var progress = getCourseProgress();
  document.querySelectorAll('.course-nav-item').forEach(function(el) {
    var onclick = el.getAttribute('onclick') || '';
    COURSE_STEPS.forEach(function(step) {
      if (onclick.includes("'" + step + "'") && progress.quizzesPassed[step]) {
        el.classList.add('completed');
      }
    });
  });
}

// ---- Navigation ----

var currentCoursePage = 'dashboard';

function navigateCourse(page) {
  currentCoursePage = page;
  var main = document.getElementById('course-main');
  if (!main) return;

  document.querySelectorAll('.course-nav-item').forEach(function(el) {
    el.classList.remove('active');
  });
  document.querySelectorAll('.course-nav-item').forEach(function(el) {
    var onclick = el.getAttribute('onclick') || '';
    if (onclick.includes("'" + page + "'")) {
      el.classList.add('active');
    }
  });

  var renderers = {
    'dashboard': renderDashboard,
    'start-here': renderStartHere,
    'step1': renderStep1,
    'step2': renderStep2,
    'step3': renderStep3,
    'step4': renderStep4,
    'step5': renderStep5,
    'step6': renderStep6,
    'strat-trendline': renderStratTrendline,
    'strat-mfi': renderStratMfi,
    'strat-macro': renderStratMacro,
    'bull-market': renderBullMarket,
    'backtesting': renderBacktesting,
    'resources': renderResources,
    'alerts': renderAlerts,
    'dictionary': renderDictionary,
    'faq': renderFaq,
    'video-library': renderVideoLibrary
  };

  var fn = renderers[page] || renderDashboard;
  main.innerHTML = fn();
  main.scrollTop = 0;
  updateProgressUI();

  // Initialize any quiz on the rendered page
  var quizContainers = main.querySelectorAll('.quiz-container[id]');
  quizContainers.forEach(function(qc) { initQuiz(qc.id); });
}

// ---- Quiz System ----

function initQuiz(quizId) {
  var container = document.getElementById(quizId);
  if (!container) return;

  container.querySelectorAll('.quiz-option').forEach(function(opt) {
    opt.addEventListener('click', function() {
      var question = opt.closest('.quiz-question');
      if (!question) return;
      question.querySelectorAll('.quiz-option').forEach(function(sib) {
        sib.classList.remove('selected');
      });
      opt.classList.add('selected');
      // Also check the radio input
      var radio = opt.querySelector('input.quiz-radio');
      if (radio) radio.checked = true;
    });
  });
}

function submitQuiz(quizId, stepId) {
  var container = document.getElementById(quizId);
  if (!container) return;

  var questions = container.querySelectorAll('.quiz-question');
  var total = questions.length;
  var correct = 0;

  questions.forEach(function(q) {
    var correctAnswer = q.getAttribute('data-correct');
    var checkedRadio = q.querySelector('input.quiz-radio:checked');
    var selectedVal = checkedRadio ? checkedRadio.value : null;

    q.querySelectorAll('.quiz-option').forEach(function(opt) {
      var radio = opt.querySelector('input.quiz-radio');
      var val = radio ? radio.value : null;
      opt.classList.remove('correct', 'incorrect');
      if (val === correctAnswer) {
        opt.classList.add('correct');
      } else if (radio && radio.checked && val !== correctAnswer) {
        opt.classList.add('incorrect');
      }
    });

    if (selectedVal === correctAnswer) correct++;
  });

  var pct = total > 0 ? Math.round((correct / total) * 100) : 0;
  var passed = pct >= 75;

  var resultEl = container.querySelector('.quiz-result');
  if (resultEl) {
    if (passed) {
      resultEl.className = 'quiz-result quiz-pass';
      resultEl.innerHTML = '<strong>Passed!</strong> You scored ' + correct + '/' + total + ' (' + pct + '%). Great job!';
    } else {
      resultEl.className = 'quiz-result quiz-fail';
      resultEl.innerHTML = '<strong>Not quite.</strong> You scored ' + correct + '/' + total + ' (' + pct + '%). You need 75% to pass. Review the material and try again.';
    }
    resultEl.style.display = 'block';
  }

  if (passed) {
    var progress = getCourseProgress();
    progress.quizzesPassed[stepId] = true;
    saveCourseProgress(progress);
  }

  updateProgressUI();
}

// ---- Checklist System ----

function toggleChecklist(itemId) {
  var el = document.getElementById(itemId);
  if (!el) return;

  el.classList.toggle('checked');

  var progress = getCourseProgress();
  progress.checklistItems[itemId] = el.classList.contains('checked');
  saveCourseProgress(progress);
}

// ---- Dashboard Renderer ----

function renderDashboard() {
  var progress = getCourseProgress();
  var completed = getCompletedSteps();
  var total = COURSE_STEPS.length;
  var pct = Math.round((completed / total) * 100);
  var allDone = completed === total && (progress.practiceTrades || []).length > 0;

  var stepData = [
    { id: 'step1', num: 1, title: 'Basics', desc: 'Candlesticks & Timeframes', icon: '\ud83d\udcca' },
    { id: 'step2', num: 2, title: 'Setup', desc: 'TradingView Configuration', icon: '\u2699\ufe0f' },
    { id: 'step3', num: 3, title: 'Structure', desc: 'Trends & Levels', icon: '\ud83d\udcd0' },
    { id: 'step4', num: 4, title: 'Risk', desc: 'Position Sizing & Stops', icon: '\ud83d\udee1\ufe0f' },
    { id: 'step5', num: 5, title: 'Indicators', desc: 'RSI, MACD, MFI, Stoch RSI', icon: '\ud83d\udcc8' },
    { id: 'step6', num: 6, title: 'Assessment', desc: 'Readiness Evaluation', icon: '\ud83c\udfaf' }
  ];

  var stepCards = '';
  for (var i = 0; i < stepData.length; i++) {
    var s = stepData[i];
    var isCompleted = !!progress.quizzesPassed[s.id];
    var prevDone = s.num === 1 ? true : !!progress.quizzesPassed['step' + (s.num - 1)];
    var isAvailable = s.num === 1 || prevDone;
    var statusTag, statusClass;

    if (isCompleted) {
      statusTag = 'Completed';
      statusClass = 'completed';
    } else if (isAvailable) {
      statusTag = 'Available';
      statusClass = 'available';
    } else {
      statusTag = 'Locked';
      statusClass = 'locked';
    }

    var cardOpacity = (!isAvailable && !isCompleted) ? 'opacity:0.5;' : '';
    stepCards += '<div class="course-card ' + statusClass + '" onclick="navigateCourse(\'' + s.id + '\')" style="cursor:pointer;' + cardOpacity + '">' +
      '<div class="card-icon">' + s.icon + '</div>' +
      '<div class="card-tag">' + statusTag + '</div>' +
      '<div class="card-title">Step ' + s.num + ': ' + s.title + '</div>' +
      '<div class="card-desc">' + s.desc + '</div>' +
    '</div>';
  }

  var readinessHtml;
  if (allDone) {
    readinessHtml = '<div class="info-box success"><strong>Ready!</strong> You have completed all quizzes and logged practice trades. You are prepared to begin live trading with small positions.</div>';
  } else {
    readinessHtml = '<div class="info-box tip"><strong>Am I ready?</strong> Not yet \u2014 pass all quizzes and log practice trades in Step 6 to unlock your readiness assessment.</div>';
  }

  return '<div class="course-page-header">' +
    '<h1>Welcome to Nunu\'s Masterclass</h1>' +
    '<p class="subtitle">Master the art of trading with our comprehensive program</p>' +
  '</div>' +

  '<div class="card" style="margin-bottom:24px;">' +
    '<h3 style="margin-top:0;">Progress: ' + completed + '/' + total + ' steps (' + pct + '%)</h3>' +
    '<div class="progress-wrap"><div class="progress-bar-outer"><div class="progress-bar-fill" style="width:' + pct + '%"></div></div></div>' +
    '<div class="progress-label">' + completed + '/' + total + ' steps completed (' + pct + '%)</div>' +
    readinessHtml +
  '</div>' +

  '<h2 style="margin-bottom:16px;">Your Learning Journey</h2>' +
  '<div class="course-grid">' + stepCards + '</div>' +

  '<h2 style="margin-top:32px;margin-bottom:16px;">Bull Market Analysis</h2>' +
  '<div class="course-card" onclick="navigateCourse(\'bull-market\')" style="cursor:pointer;max-width:480px;">' +
    '<div class="card-icon">\ud83d\udc02</div>' +
    '<div class="card-title">Bull Market Analysis</div>' +
    '<div class="card-desc">Current Market Phase: <strong>Phase 2: Early Bull Market</strong></div>' +
    '<div class="card-desc">Peak Probability: <strong>15%</strong></div>' +
    '<div class="card-tag">Explore</div>' +
  '</div>' +

  '<h2 style="margin-top:32px;margin-bottom:16px;">Core Concepts</h2>' +
  '<div class="course-grid">' +
    '<div class="course-card" onclick="navigateCourse(\'step3\')" style="cursor:pointer;">' +
      '<div class="card-icon">\ud83d\udcd0</div>' +
      '<div class="card-title">Trend Analysis</div>' +
      '<div class="card-desc">Learn to identify trends, support & resistance on higher timeframes.</div>' +
    '</div>' +
    '<div class="course-card" onclick="navigateCourse(\'step5\')" style="cursor:pointer;">' +
      '<div class="card-icon">\ud83d\udcc8</div>' +
      '<div class="card-title">Entry Signals</div>' +
      '<div class="card-desc">Master RSI, MACD, MFI, and Stochastic RSI for high-probability entries.</div>' +
    '</div>' +
    '<div class="course-card" onclick="navigateCourse(\'step4\')" style="cursor:pointer;">' +
      '<div class="card-icon">\ud83d\udee1\ufe0f</div>' +
      '<div class="card-title">Risk Management</div>' +
      '<div class="card-desc">Position sizing, stop placement, and protecting your capital.</div>' +
    '</div>' +
  '</div>' +

  '<div class="card" style="margin-top:32px;text-align:center;">' +
    '<h2 style="margin-top:0;">Ready to Begin?</h2>' +
    '<p style="color:var(--text-dim);margin-bottom:16px;">Start your journey from the very first step.</p>' +
    '<button class="step-nav-btn primary" onclick="navigateCourse(\'start-here\')">Start Here</button>' +
  '</div>' +

  '<h2 style="margin-top:32px;margin-bottom:16px;">Strategies</h2>' +
  '<div class="course-grid">' +
    '<div class="course-card" onclick="navigateCourse(\'strat-trendline\')" style="cursor:pointer;">' +
      '<div class="card-icon">\ud83d\udcc9</div>' +
      '<div class="card-title">Trendline Breakout</div>' +
      '<div class="card-desc">Win Rate: <strong>65%</strong> | R:R 1:2.5</div>' +
      '<div class="card-tag">Strategy</div>' +
    '</div>' +
    '<div class="course-card" onclick="navigateCourse(\'strat-mfi\')" style="cursor:pointer;">' +
      '<div class="card-icon">\ud83d\udca7</div>' +
      '<div class="card-title">MFI + MACD</div>' +
      '<div class="card-desc">Win Rate: <strong>62%</strong> | R:R 1:2.0</div>' +
      '<div class="card-tag">Strategy</div>' +
    '</div>' +
    '<div class="course-card" onclick="navigateCourse(\'strat-macro\')" style="cursor:pointer;">' +
      '<div class="card-icon">\ud83d\udd2d</div>' +
      '<div class="card-title">2-Week Macro</div>' +
      '<div class="card-desc">Win Rate: <strong>68%</strong> | R:R 1:3.0</div>' +
      '<div class="card-tag">Strategy</div>' +
    '</div>' +
  '</div>';
}

// ---- Start Here Renderer ----

function renderStartHere() {
  var progress = getCourseProgress();

  var timelineSteps = [
    { label: 'Foundation Setup', note: 'You\'re here!', time: '5 min', active: true },
    { label: 'Step 1: Master the Basics', note: '', time: '30\u201345 min', done: !!progress.quizzesPassed['step1'] },
    { label: 'Step 2: Trading Terminology & Setup', note: '', time: '20\u201330 min', done: !!progress.quizzesPassed['step2'] },
    { label: 'Step 3: HTF Structure Analysis', note: '', time: '45\u201360 min', done: !!progress.quizzesPassed['step3'] },
    { label: 'Step 4: Risk Management', note: '', time: '30\u201345 min', done: !!progress.quizzesPassed['step4'] },
    { label: 'Step 5: Technical Indicators', note: '', time: '60\u201390 min', done: !!progress.quizzesPassed['step5'] },
    { label: 'Step 6: Practice & Assessment', note: '', time: '1\u20132 weeks', done: !!progress.quizzesPassed['step6'] },
    { label: 'Advanced Strategies Unlocked', note: '', time: 'Ongoing', done: false }
  ];

  var timelineHtml = '';
  for (var i = 0; i < timelineSteps.length; i++) {
    var ts = timelineSteps[i];
    var cls = '';
    if (ts.active) cls = ' active-phase';
    else if (ts.done) cls = ' completed';
    var dotSymbol = ts.done ? '\u2713' : (ts.active ? '\u25b6' : '\u25cf');
    timelineHtml += '<div class="phase-item' + cls + '">' +
      '<span class="phase-num">' + dotSymbol + '</span>' +
      '<div>' +
        '<strong>' + ts.label + '</strong>' +
        (ts.note ? ' <em style="color:var(--cyan);">(' + ts.note + ')</em>' : '') +
        '<div style="color:var(--text-dim);font-size:0.85em;">' + ts.time + '</div>' +
      '</div>' +
    '</div>';
  }

  return '<div class="course-page-header">' +
    '<h1>Start Your Trading Journey</h1>' +
    '<p class="subtitle">Welcome to Nunu\'s Masterclass!</p>' +
  '</div>' +

  '<div class="info-box tip">' +
    '<strong>What you\'ll learn:</strong>' +
    '<ul style="margin:8px 0 0 0;padding-left:20px;">' +
      '<li>Professional BTC trading strategies</li>' +
      '<li>Multi-timeframe analysis (16H \u2192 6H \u2192 1H)</li>' +
      '<li>High-probability setups with 60\u201370% win rates</li>' +
      '<li>Advanced risk management</li>' +
      '<li>Market psychology</li>' +
    '</ul>' +
  '</div>' +

  '<div class="info-box" style="margin-bottom:24px;">' +
    '<strong>Time Investment:</strong> 2\u20133 weeks to complete all modules.' +
  '</div>' +

  '<h2 style="margin-bottom:16px;">Your Learning Path</h2>' +
  '<div class="phase-box">' + timelineHtml + '</div>' +

  '<h2 style="margin-top:32px;margin-bottom:16px;">What Makes This Program Different</h2>' +
  '<div class="course-grid">' +
    '<div class="course-card">' +
      '<div class="card-icon">\ud83c\udf0d</div>' +
      '<div class="card-title">Real-World Focus</div>' +
      '<div class="card-desc">Every concept is taught with live BTC chart examples and actionable setups.</div>' +
    '</div>' +
    '<div class="course-card">' +
      '<div class="card-icon">\ud83d\udd0d</div>' +
      '<div class="card-title">Multi-Timeframe Approach</div>' +
      '<div class="card-desc">Learn to read charts from 16H down to 1H for confluence-based entries.</div>' +
    '</div>' +
    '<div class="course-card">' +
      '<div class="card-icon">\ud83d\udee1\ufe0f</div>' +
      '<div class="card-title">Risk-First Mentality</div>' +
      '<div class="card-desc">Capital preservation is priority one. You learn sizing and stops before entries.</div>' +
    '</div>' +
    '<div class="course-card">' +
      '<div class="card-icon">\ud83e\udde0</div>' +
      '<div class="card-title">Psychology Integration</div>' +
      '<div class="card-desc">Mindset, discipline, and emotional control woven into every module.</div>' +
    '</div>' +
  '</div>' +

  '<h2 style="margin-top:32px;margin-bottom:16px;">Prerequisites</h2>' +
  '<div class="course-grid">' +
    '<div class="card" style="flex:1;min-width:280px;">' +
      '<h3 style="margin-top:0;color:var(--green);">What You Need</h3>' +
      '<ul style="padding-left:20px;color:var(--text-dim);">' +
        '<li>A free TradingView account</li>' +
        '<li>2\u20133 hours per week to study</li>' +
        '<li>A demo/paper trading account</li>' +
        '<li>A notebook for journaling trades</li>' +
        '<li>Commitment to follow the process</li>' +
      '</ul>' +
    '</div>' +
    '<div class="card" style="flex:1;min-width:280px;">' +
      '<h3 style="margin-top:0;color:var(--text-dim);">What You DON\'T Need</h3>' +
      '<ul style="padding-left:20px;color:var(--text-dim);">' +
        '<li>Prior trading experience</li>' +
        '<li>Large starting capital</li>' +
        '<li>Expensive software or tools</li>' +
        '<li>Advanced math background</li>' +
        '<li>Full-time availability</li>' +
      '</ul>' +
    '</div>' +
  '</div>' +

  '<h2 style="margin-top:32px;margin-bottom:16px;">Success Metrics</h2>' +
  '<div class="metric-row">' +
    '<div class="metric-card">' +
      '<div class="metric-val" style="color:var(--green);">60\u201370%</div>' +
      '<div class="metric-label">Target Win Rate</div>' +
    '</div>' +
    '<div class="metric-card">' +
      '<div class="metric-val" style="color:var(--cyan);">1:2+</div>' +
      '<div class="metric-label">Risk / Reward</div>' +
    '</div>' +
    '<div class="metric-card">' +
      '<div class="metric-val" style="color:var(--yellow);">2\u20133%</div>' +
      '<div class="metric-label">Max Risk Per Trade</div>' +
    '</div>' +
    '<div class="metric-card">' +
      '<div class="metric-val" style="color:var(--purple);">6\u201312 Mo</div>' +
      '<div class="metric-label">Time to Proficiency</div>' +
    '</div>' +
  '</div>' +

  '<div class="info-box warning" style="margin-top:24px;">' +
    '<strong>Important Disclaimers:</strong>' +
    '<ul style="margin:8px 0 0 0;padding-left:20px;">' +
      '<li>This course is for <strong>educational purposes only</strong> and is not financial advice.</li>' +
      '<li>Trading cryptocurrency involves <strong>significant risk of loss</strong>.</li>' +
      '<li>Past performance does not guarantee future results.</li>' +
      '<li>Always <strong>practice on a demo account</strong> before risking real capital.</li>' +
      '<li>You are solely responsible for your own trading decisions.</li>' +
    '</ul>' +
  '</div>' +

  '<h2 style="margin-top:32px;margin-bottom:16px;">Ready to Start?</h2>' +
  '<div class="course-grid">' +
    '<div class="course-card" onclick="navigateCourse(\'step1\')" style="cursor:pointer;">' +
      '<div class="card-icon">\ud83d\udcca</div>' +
      '<div class="card-title">Step 1: The Basics</div>' +
      '<div class="card-desc">Begin learning candlesticks and timeframes.</div>' +
    '</div>' +
    '<div class="course-card" onclick="navigateCourse(\'resources\')" style="cursor:pointer;">' +
      '<div class="card-icon">\ud83d\udcda</div>' +
      '<div class="card-title">Resources</div>' +
      '<div class="card-desc">Tools, links, and reference materials.</div>' +
    '</div>' +
    '<div class="course-card" onclick="navigateCourse(\'bull-market\')" style="cursor:pointer;">' +
      '<div class="card-icon">\ud83d\udc02</div>' +
      '<div class="card-title">Bull Market Analysis</div>' +
      '<div class="card-desc">Understand the current market cycle.</div>' +
    '</div>' +
    '<div class="course-card" onclick="navigateCourse(\'faq\')" style="cursor:pointer;">' +
      '<div class="card-icon">\u2753</div>' +
      '<div class="card-title">FAQ</div>' +
      '<div class="card-desc">Common questions answered.</div>' +
    '</div>' +
  '</div>' +

  '<div class="step-nav" style="margin-top:32px;">' +
    '<button class="step-nav-btn" onclick="navigateCourse(\'dashboard\')">\u2190 Dashboard</button>' +
    '<button class="step-nav-btn primary" onclick="navigateCourse(\'step1\')">Step 1 \u2192</button>' +
  '</div>';
}

// ---- Init ----

function initLearnTab() {
  navigateCourse('dashboard');
}

// ── Steps 1-3 ──
function renderStep1() {
  return `
    <div class="course-page-header">
      <h1>Step 1: Trading Fundamentals</h1>
      <p class="subtitle">Master the essential building blocks of technical analysis</p>
    </div>
    <div style="position:relative;padding-bottom:56.25%;height:0;margin:1rem 0;border-radius:10px;overflow:hidden;">
      <iframe src="https://www.youtube.com/embed/JzTMlClbM84" style="position:absolute;top:0;left:0;width:100%;height:100%;border:none;" allowfullscreen></iframe>
    </div>

    <h2>What You'll Learn</h2>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-icon">🕯️</div>
        <div class="card-title">Candlestick Mastery</div>
        <div class="card-desc">Read price action like a professional trader through candlestick analysis</div>
      </div>
      <div class="course-card">
        <div class="card-icon">⏱️</div>
        <div class="card-title">Timeframe Analysis</div>
        <div class="card-desc">Understand how different timeframes interact and influence each other</div>
      </div>
      <div class="course-card">
        <div class="card-icon">📐</div>
        <div class="card-title">Pattern Recognition</div>
        <div class="card-desc">Identify high-probability reversal and continuation patterns</div>
      </div>
      <div class="course-card">
        <div class="card-icon">🧠</div>
        <div class="card-title">Market Psychology</div>
        <div class="card-desc">Decode the emotions behind price movements and exploit crowd behavior</div>
      </div>
    </div>

    <h2>Candlestick Anatomy Deep Dive</h2>
    <div class="info-box tip">
      <p>Every candlestick tells a story of battle between buyers and sellers. Learning to read them is the foundation of all technical analysis.</p>
    </div>

    <h3>The Four Critical Price Points</h3>
    <div class="metric-row">
      <div class="metric-card">
        <div class="metric-val" style="color: var(--green)">Open</div>
        <div class="metric-label">The price at which the candle began trading during the period</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--cyan)">High</div>
        <div class="metric-label">The highest price reached during the period — top of the upper wick</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--red)">Low</div>
        <div class="metric-label">The lowest price reached during the period — bottom of the lower wick</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--yellow)">Close</div>
        <div class="metric-label">The price at which the candle finished trading — determines body color</div>
      </div>
    </div>

    <h3>Candlestick Types</h3>
    <div class="course-grid">
      <div class="course-card" style="border-left: 3px solid var(--green)">
        <div class="card-icon" style="color: var(--green)">&#9650;</div>
        <div class="card-title" style="color: var(--green)">Bullish</div>
        <div class="card-desc">Green body — close is higher than open. Buyers controlled the period and pushed price up.</div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--red)">
        <div class="card-icon" style="color: var(--red)">&#9660;</div>
        <div class="card-title" style="color: var(--red)">Bearish</div>
        <div class="card-desc">Red body — close is lower than open. Sellers controlled the period and pushed price down.</div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--yellow)">
        <div class="card-icon" style="color: var(--yellow)">&#10010;</div>
        <div class="card-title" style="color: var(--yellow)">Doji</div>
        <div class="card-desc">Tiny body — open is approximately equal to close. Neither buyers nor sellers won the battle.</div>
      </div>
    </div>

    <h3>Wick Analysis</h3>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-icon" style="color: var(--green)">&#9475;</div>
        <div class="card-title">Long Lower Wick</div>
        <div class="card-desc">Buyers rejected lower prices — price was pushed down but recovered. Potential bullish reversal signal, especially near support.</div>
      </div>
      <div class="course-card">
        <div class="card-icon" style="color: var(--red)">&#9475;</div>
        <div class="card-title">Long Upper Wick</div>
        <div class="card-desc">Sellers rejected higher prices — price was pushed up but pulled back. Potential bearish reversal signal, especially near resistance.</div>
      </div>
      <div class="course-card">
        <div class="card-icon" style="color: var(--cyan)">&#9608;</div>
        <div class="card-title">Large Body, Small Wicks</div>
        <div class="card-desc">Strong directional conviction — one side completely dominated with little opposition. High confidence move.</div>
      </div>
    </div>

    <h2>Timeframe Mastery</h2>
    <div class="card" style="text-align: center; padding: 24px; margin-bottom: 20px;">
      <p style="color: var(--text-dim); margin-bottom: 12px;">Timeframe Hierarchy</p>
      <div style="display: flex; align-items: center; justify-content: center; gap: 12px; flex-wrap: wrap; font-size: 1.2em; font-weight: bold;">
        <span style="color: var(--purple)">1Y</span>
        <span style="color: var(--muted)">&rarr;</span>
        <span style="color: var(--blue)">1M</span>
        <span style="color: var(--muted)">&rarr;</span>
        <span style="color: var(--cyan)">1W</span>
        <span style="color: var(--muted)">&rarr;</span>
        <span style="color: var(--green)">1D</span>
        <span style="color: var(--muted)">&rarr;</span>
        <span style="color: var(--yellow)">4H</span>
        <span style="color: var(--muted)">&rarr;</span>
        <span style="color: var(--red)">1H</span>
      </div>
    </div>
    <div class="course-grid">
      <div class="course-card" style="border-left: 3px solid var(--cyan)">
        <div class="card-title" style="color: var(--cyan)">Higher Timeframes (HTF)</div>
        <div class="card-desc"><strong>1W &amp; 1D</strong> — Identify the major trend direction. These timeframes show the big picture and should always be checked first. Use <strong>16H &amp; 6H</strong> to confirm bias and find entry zones.</div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--yellow)">
        <div class="card-title" style="color: var(--yellow)">Entry Timeframes</div>
        <div class="card-desc"><strong>4H &amp; 1H</strong> — Use these for precise entry timing. Once higher timeframes confirm the direction, drop to lower timeframes to find optimal entry points with tight stop losses.</div>
      </div>
    </div>

    <h2>Essential Candlestick Patterns</h2>

    <h3 style="color: var(--green)">Reversal Patterns</h3>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-icon" style="color: var(--green)">T</div>
        <div class="card-title">Hammer</div>
        <div class="card-desc">Bullish reversal at support. Long lower wick, small body near the top. Sellers pushed down but buyers reclaimed control.</div>
      </div>
      <div class="course-card">
        <div class="card-icon" style="color: var(--red)">&#8593;</div>
        <div class="card-title">Shooting Star</div>
        <div class="card-desc">Bearish reversal at resistance. Long upper wick, small body near the bottom. Buyers pushed up but sellers rejected the advance.</div>
      </div>
      <div class="course-card">
        <div class="card-icon" style="color: var(--green)">&#9646;&#9608;</div>
        <div class="card-title">Bullish Engulfing</div>
        <div class="card-desc">Large green candle completely engulfs the prior red candle. Strong shift from selling to buying pressure.</div>
      </div>
      <div class="course-card">
        <div class="card-icon" style="color: var(--red)">&#9608;&#9646;</div>
        <div class="card-title">Bearish Engulfing</div>
        <div class="card-desc">Large red candle completely engulfs the prior green candle. Strong shift from buying to selling pressure.</div>
      </div>
    </div>

    <h3 style="color: var(--cyan)">Continuation Patterns</h3>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-icon" style="color: var(--green)">&#9650;&#9650;&#9650;</div>
        <div class="card-title">Three White Soldiers</div>
        <div class="card-desc">Three consecutive bullish candles with higher closes. Strong buying momentum and trend continuation signal.</div>
      </div>
      <div class="course-card">
        <div class="card-icon" style="color: var(--red)">&#9660;&#9660;&#9660;</div>
        <div class="card-title">Three Black Crows</div>
        <div class="card-desc">Three consecutive bearish candles with lower closes. Strong selling momentum and bearish continuation.</div>
      </div>
      <div class="course-card">
        <div class="card-icon" style="color: var(--yellow)">&#10010;</div>
        <div class="card-title">Doji</div>
        <div class="card-desc">Open equals close with visible wicks. Signals indecision — wait for the next candle to confirm direction.</div>
      </div>
      <div class="course-card">
        <div class="card-icon" style="color: var(--green)">&#9585;</div>
        <div class="card-title">Piercing Pattern</div>
        <div class="card-desc">Green candle opens below prior red candle and closes above its midpoint. Bullish reversal signal at support levels.</div>
      </div>
    </div>

    <h2>Market Psychology</h2>
    <div class="course-grid">
      <div class="course-card" style="border-left: 3px solid var(--green)">
        <div class="card-icon">&#128200;</div>
        <div class="card-title">FOMO (Fear of Missing Out)</div>
        <div class="card-desc">Appears as long green candles with increasing volume. The crowd is piling in. <strong>Strategy:</strong> Wait for pullbacks rather than chasing. FOMO entries are often the worst entries.</div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--red)">
        <div class="card-icon">&#128200;</div>
        <div class="card-title">Panic Selling</div>
        <div class="card-desc">Appears as long red candles on high volume. Fear dominates. <strong>Strategy:</strong> Look for buying opportunities at key support levels. Panic often marks bottoms.</div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--yellow)">
        <div class="card-icon">&#9878;</div>
        <div class="card-title">Indecision</div>
        <div class="card-desc">Appears as doji candles and small-bodied candles. Neither side is winning. <strong>Strategy:</strong> Wait for confirmation before entering. Let the market show its hand.</div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--cyan)">
        <div class="card-icon">&#128170;</div>
        <div class="card-title">Strong Conviction</div>
        <div class="card-desc">Appears as large bodies with small wicks. One side is in full control. <strong>Strategy:</strong> Trade in the direction of conviction. These moves tend to follow through.</div>
      </div>
    </div>

    <h2>Practice Exercises</h2>
    <div class="checklist">
      <div class="checklist-item">
        <span class="checklist-box">1</span>
        <div>
          <strong>Candlestick Identification:</strong> Open a 1D chart on BTC. Identify and label 10 candles as bullish, bearish, or doji. Note the body size and wick lengths for each.
        </div>
      </div>
      <div class="checklist-item">
        <span class="checklist-box">2</span>
        <div>
          <strong>Wick Analysis:</strong> Find 5 candles with long lower wicks and 5 with long upper wicks. Record what happened on the next candle after each. Do wicks predict direction?
        </div>
      </div>
      <div class="checklist-item">
        <span class="checklist-box">3</span>
        <div>
          <strong>Timeframe Comparison:</strong> Look at the same date on 1W, 1D, 4H, and 1H charts. Write down how the story changes at each timeframe. Which gives the clearest picture?
        </div>
      </div>
      <div class="checklist-item">
        <span class="checklist-box">4</span>
        <div>
          <strong>Psychology Reading:</strong> Find recent examples of FOMO (long green run), panic selling (sharp drop), and indecision (doji cluster). What happened after each?
        </div>
      </div>
    </div>

    <h2>Knowledge Check Quiz</h2>
    <div class="quiz-container" id="quiz-step1">
      <div class="quiz-question" data-correct="b">
        <p><strong>1.</strong> What does a long lower wick indicate?</p>
        <label class="quiz-option"><input type="radio" name="q1" value="a" class="quiz-radio"> a) Strong buying pressure</label>
        <label class="quiz-option"><input type="radio" name="q1" value="b" class="quiz-radio"> b) Price was rejected at lower levels by buyers</label>
        <label class="quiz-option"><input type="radio" name="q1" value="c" class="quiz-radio"> c) Sellers dominated</label>
      </div>
      <div class="quiz-question" data-correct="c">
        <p><strong>2.</strong> Which timeframe should you check FIRST?</p>
        <label class="quiz-option"><input type="radio" name="q2" value="a" class="quiz-radio"> a) 1 minute</label>
        <label class="quiz-option"><input type="radio" name="q2" value="b" class="quiz-radio"> b) 1 hour</label>
        <label class="quiz-option"><input type="radio" name="q2" value="c" class="quiz-radio"> c) Daily or weekly for overall trend</label>
      </div>
      <div class="quiz-question" data-correct="b">
        <p><strong>3.</strong> A doji candle typically indicates:</p>
        <label class="quiz-option"><input type="radio" name="q3" value="a" class="quiz-radio"> a) Strong bullish momentum</label>
        <label class="quiz-option"><input type="radio" name="q3" value="b" class="quiz-radio"> b) Market indecision and potential reversal</label>
        <label class="quiz-option"><input type="radio" name="q3" value="c" class="quiz-radio"> c) Guaranteed price continuation</label>
      </div>
      <div class="quiz-question" data-correct="a">
        <p><strong>4.</strong> What psychology does a hammer pattern reveal?</p>
        <label class="quiz-option"><input type="radio" name="q4" value="a" class="quiz-radio"> a) Panic selling followed by buyer rejection</label>
        <label class="quiz-option"><input type="radio" name="q4" value="b" class="quiz-radio"> b) Strong seller conviction</label>
        <label class="quiz-option"><input type="radio" name="q4" value="c" class="quiz-radio"> c) Market consolidation</label>
      </div>
      <button class="quiz-submit" onclick="submitQuiz('quiz-step1','step1')">Check Answers</button>
      <div class="quiz-result"></div>
    </div>

    <h2>Key Takeaways</h2>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-icon">1</div>
        <div class="card-desc">Candlesticks encode the battle between buyers and sellers — body size shows conviction, wicks show rejection.</div>
      </div>
      <div class="course-card">
        <div class="card-icon">2</div>
        <div class="card-desc">Always start analysis on higher timeframes (Weekly/Daily) and work down to entry timeframes (4H/1H).</div>
      </div>
      <div class="course-card">
        <div class="card-icon">3</div>
        <div class="card-desc">Reversal patterns (hammer, engulfing) signal potential trend changes — always confirm with context and volume.</div>
      </div>
      <div class="course-card">
        <div class="card-icon">4</div>
        <div class="card-desc">Market psychology drives price — learn to recognize FOMO, panic, and indecision in candlestick formations.</div>
      </div>
      <div class="course-card">
        <div class="card-icon">5</div>
        <div class="card-desc">Practice reading candles daily until pattern recognition becomes second nature. Consistent practice is the fastest path to mastery.</div>
      </div>
    </div>

    <div class="step-nav">
      <button class="step-nav-btn" onclick="navigateCourse('dashboard')">&#8592; Back to Dashboard</button>
      <button class="step-nav-btn primary" onclick="navigateCourse('step2')">Next: Professional Setup &#8594;</button>
    </div>
  `;
}

function renderStep2() {
  return `
    <div class="course-page-header">
      <h1>Step 2: Professional Trading Setup</h1>
      <p class="subtitle">Build your professional trading workspace</p>
    </div>
    <div style="position:relative;padding-bottom:56.25%;height:0;margin:1rem 0;border-radius:10px;overflow:hidden;">
      <iframe src="https://www.youtube.com/embed/ucR2gg8v9Uo" style="position:absolute;top:0;left:0;width:100%;height:100%;border:none;" allowfullscreen></iframe>
    </div>

    <h2>What You'll Master</h2>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-icon">&#128202;</div>
        <div class="card-title">TradingView Mastery</div>
        <div class="card-desc">Set up and optimize TradingView for professional-grade charting and analysis</div>
      </div>
      <div class="course-card">
        <div class="card-icon">&#128200;</div>
        <div class="card-title">Indicator Setup</div>
        <div class="card-desc">Configure the exact indicators used by professionals — EMAs, RSI, MACD, and more</div>
      </div>
      <div class="course-card">
        <div class="card-icon">&#128187;</div>
        <div class="card-title">Multi-Chart Layout</div>
        <div class="card-desc">Build multi-timeframe workspaces for complete market visibility</div>
      </div>
      <div class="course-card">
        <div class="card-icon">&#128276;</div>
        <div class="card-title">Alert Systems</div>
        <div class="card-desc">Set up price and indicator alerts so you never miss a trade setup</div>
      </div>
    </div>

    <h2>TradingView Account Setup</h2>

    <h3>Step 1: Create Your Account</h3>
    <div class="info-box tip">
      <p>Go to <strong>tradingview.com</strong> and create a free account. For crypto charting, we recommend using <strong>COINBASE:BTCUSD</strong> as your primary chart for the cleanest data and highest liquidity.</p>
    </div>

    <h3>Account Tiers</h3>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-title">Free Tier</div>
        <div class="card-desc">
          <ul style="margin: 0; padding-left: 16px;">
            <li>1 chart per tab</li>
            <li>3 indicators per chart</li>
            <li>Basic price alerts</li>
            <li>Limited saved layouts</li>
          </ul>
          <p style="margin-top: 8px; color: var(--text-dim);">Good for getting started and learning the platform.</p>
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--cyan)">
        <div class="card-title" style="color: var(--cyan)">Pro — $14.95/mo</div>
        <div class="card-desc">
          <ul style="margin: 0; padding-left: 16px;">
            <li>Multiple chart layouts</li>
            <li>5 indicators per chart</li>
            <li>Advanced alerts (multi-condition)</li>
            <li>Multi-timeframe workspace</li>
          </ul>
          <p style="margin-top: 8px; color: var(--cyan);">Recommended for serious traders who need full indicator suite.</p>
        </div>
      </div>
    </div>

    <h3>Chart Settings</h3>
    <div class="info-box success">
      <p><strong>Chart Type:</strong> Candlesticks (always)<br>
      <strong>Scale:</strong> Log Scale for long-term analysis / Linear Scale for intraday<br>
      <strong>Colors:</strong> Green Up / Red Down (standard convention)</p>
    </div>

    <h2>Timeframe Configuration</h2>

    <h3>The 5-Timeframe System</h3>
    <div class="metric-row">
      <div class="metric-card">
        <div class="metric-val" style="color: var(--purple)">1W</div>
        <div class="metric-label">Weekly — Major trend direction and key levels</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--blue)">1D</div>
        <div class="metric-label">Daily — Swing structure and intermediate trend</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--cyan)">16H</div>
        <div class="metric-label">16-Hour — Bias confirmation between daily and intraday</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--green)">6H</div>
        <div class="metric-label">6-Hour — Setup alignment and zone identification</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--yellow)">1H</div>
        <div class="metric-label">1-Hour — Precise entry timing and stop placement</div>
      </div>
    </div>

    <h3>Analysis Workflow</h3>
    <div class="card" style="text-align: center; padding: 24px;">
      <div style="display: flex; align-items: center; justify-content: center; gap: 12px; flex-wrap: wrap; font-size: 1.1em; font-weight: bold;">
        <span style="color: var(--purple)">Weekly</span>
        <span style="color: var(--muted)">&rarr;</span>
        <span style="color: var(--blue)">Daily</span>
        <span style="color: var(--muted)">&rarr;</span>
        <span style="color: var(--cyan)">16H / 6H</span>
        <span style="color: var(--muted)">&rarr;</span>
        <span style="color: var(--yellow)">1H</span>
      </div>
      <p style="color: var(--text-dim); margin-top: 12px;">Always analyze from highest to lowest timeframe. Never skip the weekly check.</p>
    </div>

    <h2>Indicator Configuration</h2>

    <h3>Exponential Moving Averages (EMAs)</h3>
    <div class="course-grid">
      <div class="indicator-card">
        <div style="font-size: 1.3em; font-weight: bold; color: #3B82F6; margin-bottom: 8px;">EMA 20</div>
        <p style="margin: 0;"><strong>Color:</strong> Blue (#3B82F6)</p>
        <p style="margin: 4px 0; color: var(--text-dim);">Short-term trend. Price above = bullish bias. Acts as dynamic support/resistance on pullbacks.</p>
      </div>
      <div class="indicator-card">
        <div style="font-size: 1.3em; font-weight: bold; color: #F59E0B; margin-bottom: 8px;">EMA 50</div>
        <p style="margin: 0;"><strong>Color:</strong> Orange (#F59E0B)</p>
        <p style="margin: 4px 0; color: var(--text-dim);">Medium-term trend. Key level for swing traders. Crossover with EMA 20 signals trend shifts.</p>
      </div>
      <div class="indicator-card">
        <div style="font-size: 1.3em; font-weight: bold; color: #6B7280; margin-bottom: 8px;">EMA 200</div>
        <p style="margin: 0;"><strong>Color:</strong> Gray (#6B7280)</p>
        <p style="margin: 4px 0; color: var(--text-dim);">Long-term trend. The most watched moving average. Price above = bull market, below = bear market.</p>
      </div>
    </div>

    <div class="info-box tip">
      <p><strong>EMA Alignment Rules:</strong><br>
      <span style="color: var(--green);">&#9650; Bullish:</span> EMA 20 &gt; EMA 50 &gt; EMA 200 — all moving averages stacked in order<br>
      <span style="color: var(--red);">&#9660; Bearish:</span> EMA 20 &lt; EMA 50 &lt; EMA 200 — inverse stack confirms downtrend</p>
    </div>

    <h3>Oscillators &amp; Momentum</h3>
    <div class="course-grid">
      <div class="indicator-card">
        <div style="font-size: 1.1em; font-weight: bold; color: var(--cyan); margin-bottom: 8px;">RSI (Relative Strength Index)</div>
        <p style="margin: 0;"><strong>Length:</strong> 14</p>
        <p style="margin: 4px 0;"><strong>Overbought:</strong> 70 &nbsp;|&nbsp; <strong>Oversold:</strong> 30</p>
        <p style="margin: 4px 0; color: var(--text-dim);">Measures momentum. Above 70 = overbought, below 30 = oversold. Look for divergences with price.</p>
      </div>
      <div class="indicator-card">
        <div style="font-size: 1.1em; font-weight: bold; color: var(--purple); margin-bottom: 8px;">Stochastic RSI</div>
        <p style="margin: 0;"><strong>K:</strong> 3 &nbsp;|&nbsp; <strong>D:</strong> 3</p>
        <p style="margin: 4px 0;"><strong>RSI Length:</strong> 14 &nbsp;|&nbsp; <strong>Stoch Length:</strong> 14</p>
        <p style="margin: 4px 0; color: var(--text-dim);">More sensitive than RSI. Great for timing entries within a trend. K crossing above D = bullish.</p>
      </div>
      <div class="indicator-card">
        <div style="font-size: 1.1em; font-weight: bold; color: var(--green); margin-bottom: 8px;">MACD</div>
        <p style="margin: 0;"><strong>Fast:</strong> 12 &nbsp;|&nbsp; <strong>Slow:</strong> 26 &nbsp;|&nbsp; <strong>Signal:</strong> 9</p>
        <p style="margin: 4px 0; color: var(--text-dim);">Trend-following momentum. Histogram above zero = bullish. Signal line crossovers confirm entries.</p>
      </div>
      <div class="indicator-card">
        <div style="font-size: 1.1em; font-weight: bold; color: var(--yellow); margin-bottom: 8px;">MFI (Money Flow Index)</div>
        <p style="margin: 0;"><strong>Length:</strong> 14</p>
        <p style="margin: 4px 0;"><strong>Overbought:</strong> 80 &nbsp;|&nbsp; <strong>Oversold:</strong> 20</p>
        <p style="margin: 4px 0; color: var(--text-dim);">Volume-weighted RSI. Confirms whether money is flowing in or out. Divergences are powerful signals.</p>
      </div>
    </div>

    <h2>Workspace Layouts</h2>
    <div class="course-grid">
      <div class="course-card" style="border-left: 3px solid var(--green)">
        <div class="card-title" style="color: var(--green)">Single Chart Pro (Recommended)</div>
        <div class="card-desc">
          <p style="color: var(--text-dim); margin-bottom: 8px;">Works with the free tier. One chart with layered analysis.</p>
          <ul style="margin: 0; padding-left: 16px;">
            <li><strong>Main Chart:</strong> Candlesticks + EMA 20/50/200</li>
            <li><strong>Panel 1:</strong> RSI + Stochastic RSI overlay</li>
            <li><strong>Panel 2:</strong> MACD + MFI overlay</li>
          </ul>
          <p style="margin-top: 8px;">Switch timeframes manually using the toolbar. Start here.</p>
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--cyan)">
        <div class="card-title" style="color: var(--cyan)">Multi-Timeframe Pro (Advanced)</div>
        <div class="card-desc">
          <p style="color: var(--text-dim); margin-bottom: 8px;">Requires Pro subscription for multiple chart layouts.</p>
          <ul style="margin: 0; padding-left: 16px;">
            <li><strong>Chart 1:</strong> Weekly/Daily for trend direction</li>
            <li><strong>Chart 2:</strong> 16H/6H for setup identification</li>
            <li><strong>Chart 3:</strong> 1H for entry precision</li>
          </ul>
          <p style="margin-top: 8px;">See all timeframes simultaneously for faster analysis.</p>
        </div>
      </div>
    </div>

    <h2>Visual Optimization Tips</h2>
    <div class="info-box tip">
      <p><strong>Dark Theme:</strong> Easier on the eyes during long sessions. Go to Settings &gt; Appearance &gt; Dark.<br>
      <strong>Proper Scaling:</strong> Use Auto Scale for most charts. Lock scale when comparing specific levels.<br>
      <strong>Crosshair Magnet Mode:</strong> Enable to snap crosshair to OHLC values — reduces guesswork.<br>
      <strong>Subtle Grid:</strong> Reduce grid opacity so price action stands out. Grid is a guide, not a distraction.</p>
    </div>

    <h2>Knowledge Check Quiz</h2>
    <div class="quiz-container" id="quiz-step2">
      <div class="quiz-question" data-correct="b">
        <p><strong>1.</strong> What are the optimal EMA lengths for our setup?</p>
        <label class="quiz-option"><input type="radio" name="s2q1" value="a" class="quiz-radio"> a) 10, 30, 100</label>
        <label class="quiz-option"><input type="radio" name="s2q1" value="b" class="quiz-radio"> b) 20, 50, 200</label>
        <label class="quiz-option"><input type="radio" name="s2q1" value="c" class="quiz-radio"> c) 5, 20, 50</label>
      </div>
      <div class="quiz-question" data-correct="b">
        <p><strong>2.</strong> Which timeframes are used for higher timeframe (HTF) analysis?</p>
        <label class="quiz-option"><input type="radio" name="s2q2" value="a" class="quiz-radio"> a) 1m, 5m, 15m</label>
        <label class="quiz-option"><input type="radio" name="s2q2" value="b" class="quiz-radio"> b) 1W, 1D, 16H, 6H</label>
        <label class="quiz-option"><input type="radio" name="s2q2" value="c" class="quiz-radio"> c) 4H, 1H, 30m</label>
      </div>
      <div class="quiz-question" data-correct="a">
        <p><strong>3.</strong> What does bullish EMA alignment look like?</p>
        <label class="quiz-option"><input type="radio" name="s2q3" value="a" class="quiz-radio"> a) EMA 20 &gt; EMA 50 &gt; EMA 200</label>
        <label class="quiz-option"><input type="radio" name="s2q3" value="b" class="quiz-radio"> b) EMA 200 &gt; EMA 50 &gt; EMA 20</label>
        <label class="quiz-option"><input type="radio" name="s2q3" value="c" class="quiz-radio"> c) All EMAs at the same level</label>
      </div>
      <div class="quiz-question" data-correct="c">
        <p><strong>4.</strong> What is the recommended exchange for BTC charting?</p>
        <label class="quiz-option"><input type="radio" name="s2q4" value="a" class="quiz-radio"> a) BINANCE:BTCUSDT</label>
        <label class="quiz-option"><input type="radio" name="s2q4" value="b" class="quiz-radio"> b) KRAKEN:BTCUSD</label>
        <label class="quiz-option"><input type="radio" name="s2q4" value="c" class="quiz-radio"> c) COINBASE:BTCUSD</label>
      </div>
      <button class="quiz-submit" onclick="submitQuiz('quiz-step2','step2')">Check Answers</button>
      <div class="quiz-result"></div>
    </div>

    <div class="step-nav">
      <button class="step-nav-btn" onclick="navigateCourse('step1')">&#8592; Step 1: Fundamentals</button>
      <button class="step-nav-btn primary" onclick="navigateCourse('step3')">Next: Strategy Fundamentals &#8594;</button>
    </div>
  `;
}

function renderStep3() {
  return `
    <div class="course-page-header">
      <h1>Step 3: Strategy Fundamentals Mastery</h1>
      <p class="subtitle">Master market structure analysis, trend identification, and support/resistance</p>
    </div>
    <div style="position:relative;padding-bottom:56.25%;height:0;margin:1rem 0;border-radius:10px;overflow:hidden;">
      <iframe src="https://www.youtube.com/embed/XeNp9drLM9s" style="position:absolute;top:0;left:0;width:100%;height:100%;border:none;" allowfullscreen></iframe>
    </div>

    <h2>Market Structure Analysis</h2>
    <p style="color: var(--text-dim); margin-bottom: 16px;">Understanding market structure is the foundation of every trading decision. Markets move in three phases:</p>
    <div class="course-grid">
      <div class="course-card" style="border-left: 3px solid var(--green)">
        <div class="card-icon" style="color: var(--green)">&#8599;</div>
        <div class="card-title" style="color: var(--green)">Uptrend</div>
        <div class="card-desc">
          <p><strong>Structure:</strong> Higher Highs (HH) and Higher Lows (HL)</p>
          <p><strong>Characteristics:</strong> Each swing high surpasses the previous. Pullbacks find support above the prior low. Volume tends to increase on rallies.</p>
          <p><strong>Trading Bias:</strong> Look for long entries on pullbacks to higher lows or key support levels.</p>
          <p><strong>Invalidation:</strong> Break below the most recent higher low signals potential trend change.</p>
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--red)">
        <div class="card-icon" style="color: var(--red)">&#8600;</div>
        <div class="card-title" style="color: var(--red)">Downtrend</div>
        <div class="card-desc">
          <p><strong>Structure:</strong> Lower Highs (LH) and Lower Lows (LL)</p>
          <p><strong>Characteristics:</strong> Each swing low breaks below the previous. Rallies fail to reclaim the prior high. Volume tends to increase on sell-offs.</p>
          <p><strong>Trading Bias:</strong> Look for short entries on rallies to lower highs or key resistance levels.</p>
          <p><strong>Invalidation:</strong> Break above the most recent lower high signals potential trend change.</p>
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--yellow)">
        <div class="card-icon" style="color: var(--yellow)">&#8596;</div>
        <div class="card-title" style="color: var(--yellow)">Range (Consolidation)</div>
        <div class="card-desc">
          <p><strong>Structure:</strong> Horizontal support and resistance with price oscillating between</p>
          <p><strong>Characteristics:</strong> Swing highs and lows are roughly equal. Volume typically decreases. Market is building energy for a breakout.</p>
          <p><strong>Trading Bias:</strong> Buy at support, sell at resistance — or wait for breakout with confirmation.</p>
          <p><strong>Invalidation:</strong> A decisive break above resistance or below support ends the range.</p>
        </div>
      </div>
    </div>

    <h2>Professional Trendline Analysis</h2>

    <h3>Drawing Rules</h3>
    <div class="info-box tip">
      <p><strong>Connect 2+ significant swing points</strong> — the more touches, the more valid the trendline.<br>
      <strong>Use the ray tool</strong> to extend trendlines into the future for anticipating reactions.<br>
      <strong>Avoid forcing through minor wicks</strong> — trendlines should fit naturally, not be manufactured.<br>
      <strong>Focus on body closes</strong> rather than exact wick tips for more reliable trendlines.</p>
    </div>

    <h3>Breakout Criteria</h3>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-icon" style="color: var(--green)">&#10003;</div>
        <div class="card-title">Body Closes Beyond Trendline</div>
        <div class="card-desc">A wick piercing the trendline is not enough. The candle body must close beyond the trendline for a valid breakout.</div>
      </div>
      <div class="course-card">
        <div class="card-icon" style="color: var(--green)">&#10003;</div>
        <div class="card-title">Volume Confirmation</div>
        <div class="card-desc">Genuine breakouts occur on increased volume. Low-volume breakouts are more likely to fail and reverse.</div>
      </div>
      <div class="course-card">
        <div class="card-icon" style="color: var(--green)">&#10003;</div>
        <div class="card-title">Retest of Broken Level</div>
        <div class="card-desc">The best breakouts pull back to retest the broken trendline as new support or resistance before continuing.</div>
      </div>
      <div class="course-card">
        <div class="card-icon" style="color: var(--green)">&#10003;</div>
        <div class="card-title">Follow-Through</div>
        <div class="card-desc">After the breakout candle, subsequent candles should continue in the breakout direction with momentum.</div>
      </div>
    </div>

    <h3>False Breakout Signs</h3>
    <div class="info-box warning">
      <p><strong>Wick pierces but body stays inside</strong> — the breakout is not confirmed, likely a trap.<br>
      <strong>Low volume</strong> — no conviction behind the move, high probability of reversal.<br>
      <strong>Immediate reversal</strong> — price quickly snaps back inside, trapping breakout traders.<br>
      <strong>Multiple failed attempts</strong> — repeated tests without follow-through weaken the breakout case.</p>
    </div>

    <h3>Trendline Strength</h3>
    <div class="metric-row">
      <div class="metric-card">
        <div class="metric-val" style="color: var(--cyan)">Touches</div>
        <div class="metric-label">More touches = stronger trendline. 3+ touches confirms significance.</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--purple)">Timeframe</div>
        <div class="metric-label">Longer timeframe = more significant. A weekly trendline outweighs an hourly one.</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--yellow)">Angle</div>
        <div class="metric-label">Steeper = less reliable. Sustainable trends have moderate, not extreme, angles.</div>
      </div>
    </div>

    <h2>HTF Structure Analysis</h2>
    <div class="card" style="text-align: center; padding: 24px; margin-bottom: 20px;">
      <div style="display: flex; align-items: center; justify-content: center; gap: 12px; flex-wrap: wrap; font-size: 1.1em; font-weight: bold;">
        <span style="color: var(--purple)">Monthly<br><span style="font-weight: normal; font-size: 0.8em; color: var(--text-dim);">Overall market cycle</span></span>
        <span style="color: var(--muted)">&rarr;</span>
        <span style="color: var(--blue)">Weekly<br><span style="font-weight: normal; font-size: 0.8em; color: var(--text-dim);">Intermediate trend</span></span>
        <span style="color: var(--muted)">&rarr;</span>
        <span style="color: var(--cyan)">Daily<br><span style="font-weight: normal; font-size: 0.8em; color: var(--text-dim);">Short-term structure</span></span>
        <span style="color: var(--muted)">&rarr;</span>
        <span style="color: var(--yellow)">4H<br><span style="font-weight: normal; font-size: 0.8em; color: var(--text-dim);">Intraday structure</span></span>
      </div>
    </div>

    <h3>HTF Analysis Process</h3>
    <div class="metric-row">
      <div class="metric-card">
        <div class="metric-val" style="color: var(--purple)">1</div>
        <div class="metric-label"><strong>Start High</strong> — Begin with monthly/weekly to identify the macro trend and key levels</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--blue)">2</div>
        <div class="metric-label"><strong>Work Down</strong> — Move to daily to refine structure and identify swing points</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--cyan)">3</div>
        <div class="metric-label"><strong>Align Bias</strong> — Confirm all timeframes agree on direction before trading</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--green)">4</div>
        <div class="metric-label"><strong>Find Entries</strong> — Use 4H/1H for precise entry timing within the HTF bias</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--yellow)">5</div>
        <div class="metric-label"><strong>Manage Risk</strong> — Set stops based on structure, not arbitrary levels</div>
      </div>
    </div>

    <h2 style="margin-top: 32px;">Video Resource</h2>
    <div class="video-card">
      <div class="play-icon">&#9654;</div>
      <div>
        <div style="font-weight: bold; font-size: 1.1em; margin-bottom: 4px;">Trendline Breakout Strategy Masterclass</div>
        <div style="color: var(--text-dim);">Learn how to draw, validate, and trade trendline breakouts like a professional. Covers real chart examples with entry, stop loss, and target placement.</div>
      </div>
    </div>

    <h2>Practice Drills</h2>
    <div class="checklist">
      <div class="checklist-item">
        <span class="checklist-box">1</span>
        <div>
          <strong>HTF Structure Drill:</strong> Open BTC on Monthly, Weekly, and Daily charts. Mark all Higher Highs (HH), Higher Lows (HL), Lower Highs (LH), and Lower Lows (LL) on each timeframe. Identify the current structure phase.
        </div>
      </div>
      <div class="checklist-item">
        <span class="checklist-box">2</span>
        <div>
          <strong>Trendline Drawing Practice:</strong> Find a clear uptrend on the daily chart. Connect the swing lows with a trendline using the ray tool. Extend it forward and watch how price reacts at the projected trendline.
        </div>
      </div>
      <div class="checklist-item">
        <span class="checklist-box">3</span>
        <div>
          <strong>Breakout Analysis:</strong> Find a recent trendline breakout. Check: Did the body close beyond the line? Was there volume confirmation? Did price retest the broken level? Was there follow-through?
        </div>
      </div>
    </div>

    <h2>Mastery Checklist</h2>
    <div class="checklist">
      <div class="checklist-item">
        <input type="checkbox" class="checklist-box">
        <span>I can identify uptrends, downtrends, and ranges by marking HH/HL/LH/LL on any chart</span>
      </div>
      <div class="checklist-item">
        <input type="checkbox" class="checklist-box">
        <span>I can draw valid trendlines connecting 2+ significant swing points using body closes</span>
      </div>
      <div class="checklist-item">
        <input type="checkbox" class="checklist-box">
        <span>I can distinguish between genuine breakouts and false breakouts using volume and body close</span>
      </div>
      <div class="checklist-item">
        <input type="checkbox" class="checklist-box">
        <span>I can perform top-down multi-timeframe analysis from Monthly down to 4H</span>
      </div>
      <div class="checklist-item">
        <input type="checkbox" class="checklist-box">
        <span>I understand trendline strength factors: number of touches, timeframe significance, and angle</span>
      </div>
    </div>

    <h2>Knowledge Check Quiz</h2>
    <div class="quiz-container" id="quiz-step3">
      <div class="quiz-question" data-correct="b">
        <p><strong>1.</strong> Which confirms bullish market structure on the Weekly chart?</p>
        <label class="quiz-option"><input type="radio" name="s3q1" value="a" class="quiz-radio"> a) Lower highs and lower lows</label>
        <label class="quiz-option"><input type="radio" name="s3q1" value="b" class="quiz-radio"> b) Higher highs and higher lows</label>
        <label class="quiz-option"><input type="radio" name="s3q1" value="c" class="quiz-radio"> c) Price trading sideways in a range</label>
      </div>
      <div class="quiz-question" data-correct="c">
        <p><strong>2.</strong> What is the most reliable breakout confirmation?</p>
        <label class="quiz-option"><input type="radio" name="s3q2" value="a" class="quiz-radio"> a) A long wick piercing through the trendline</label>
        <label class="quiz-option"><input type="radio" name="s3q2" value="b" class="quiz-radio"> b) Price touching the trendline multiple times</label>
        <label class="quiz-option"><input type="radio" name="s3q2" value="c" class="quiz-radio"> c) Candle body closes beyond the trendline with volume confirmation</label>
      </div>
      <div class="quiz-question" data-correct="b">
        <p><strong>3.</strong> What is the correct trendline drawing approach?</p>
        <label class="quiz-option"><input type="radio" name="s3q3" value="a" class="quiz-radio"> a) Connect any two points and force through wicks</label>
        <label class="quiz-option"><input type="radio" name="s3q3" value="b" class="quiz-radio"> b) Connect 2+ significant swing points, focus on body closes</label>
        <label class="quiz-option"><input type="radio" name="s3q3" value="c" class="quiz-radio"> c) Draw horizontal lines at random price levels</label>
      </div>
      <div class="quiz-question" data-correct="a">
        <p><strong>4.</strong> What is the correct sequence for multi-timeframe analysis?</p>
        <label class="quiz-option"><input type="radio" name="s3q4" value="a" class="quiz-radio"> a) Monthly/Weekly down to Daily and then lower timeframes</label>
        <label class="quiz-option"><input type="radio" name="s3q4" value="b" class="quiz-radio"> b) Start with 1-minute and work up</label>
        <label class="quiz-option"><input type="radio" name="s3q4" value="c" class="quiz-radio"> c) Only use the 4-hour chart</label>
      </div>
      <button class="quiz-submit" onclick="submitQuiz('quiz-step3','step3')">Check Answers</button>
      <div class="quiz-result"></div>
    </div>

    <div class="step-nav">
      <button class="step-nav-btn" onclick="navigateCourse('step2')">&#8592; Step 2: Professional Setup</button>
      <button class="step-nav-btn primary" onclick="navigateCourse('step4')">Next: Step 4 &#8594;</button>
    </div>
  `;
}

// ── Steps 4-6 ──
function renderStep4() {
  return `
    <div class="course-page-header">
      <h1>Step 4: Professional Risk Management Mastery</h1>
      <p class="subtitle">Master institutional-level risk management, position sizing, and capital preservation</p>
    </div>
    <div style="position:relative;padding-bottom:56.25%;height:0;margin:1rem 0;border-radius:10px;overflow:hidden;">
      <iframe src="https://www.youtube.com/embed/T2D0PtADAu0" style="position:absolute;top:0;left:0;width:100%;height:100%;border:none;" allowfullscreen></iframe>
    </div>

    <div class="metric-row">
      <div class="metric-card">
        <div class="metric-val" style="color:var(--cyan)">1-3%</div>
        <div class="metric-label">Max Risk Per Trade</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color:var(--green)">1:2+</div>
        <div class="metric-label">Min Risk/Reward</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color:var(--red)">6%</div>
        <div class="metric-label">Max Daily Risk</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color:var(--purple)">Pro Level</div>
        <div class="metric-label">Skills</div>
      </div>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">Fundamental Principles</h2>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-icon">📐</div>
        <div class="card-title">Position Sizing Formula</div>
        <div class="card-desc">
          <strong>Position Size = Risk Amount / (Entry - Stop)</strong><br><br>
          Risk Amount = Balance × Risk%<br><br>
          Never exceed your predetermined risk limit. This formula ensures consistent risk regardless of asset price or volatility.
        </div>
      </div>
      <div class="course-card">
        <div class="card-icon">📊</div>
        <div class="card-title">Risk Percentage Guidelines</div>
        <div class="card-desc">
          <strong>By Style:</strong><br>
          Conservative: 0.5%<br>
          Standard: 1-2%<br>
          Aggressive: 2-3%<br><br>
          <strong>By Strategy:</strong><br>
          Scalping: 0.25-0.5%<br>
          Swing: 1-2%<br>
          Position: 2-3%<br><br>
          <span style="color:var(--red)">Never more than 6% daily.</span>
        </div>
      </div>
      <div class="course-card">
        <div class="card-icon">⚖️</div>
        <div class="card-title">Risk/Reward Ratios</div>
        <div class="card-desc">
          Minimum: <strong>1:2</strong><br>
          Target: <strong>1:3+</strong><br>
          Elite: <strong>1:5+</strong><br><br>
          1:2 = Risk $100 to make $200<br><br>
          Higher R/R allows lower win rates. At 1:3, you only need 25%+ win rate to be profitable.
        </div>
      </div>
      <div class="course-card">
        <div class="card-icon">🛑</div>
        <div class="card-title">Stop Loss Placement</div>
        <div class="card-desc">
          Place stops:<br>
          - Below/above key support/resistance<br>
          - Beyond significant swing points<br>
          - Outside consolidation ranges<br><br>
          <span style="color:var(--red)"><strong>Never move stops against your position.</strong></span> Only move them in your favor.
        </div>
      </div>
      <div class="course-card">
        <div class="card-icon">⏰</div>
        <div class="card-title">Time-Based Risk Management</div>
        <div class="card-desc">
          - Exit if no progress in expected timeframe<br>
          - Reduce size before major news events<br>
          - Close positions before weekends if needed<br><br>
          Time is a risk factor. A trade that hasn't moved is tying up capital and mental energy.
        </div>
      </div>
      <div class="course-card">
        <div class="card-icon">🔥</div>
        <div class="card-title">Portfolio Heat Management</div>
        <div class="card-desc">
          - Max 15-20% total portfolio risk at any time<br>
          - Correlated positions count as one combined risk<br>
          - Scale down position sizes during drawdowns<br><br>
          If BTC and ETH are both long, that's essentially one bet on crypto going up.
        </div>
      </div>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">Position Sizing Calculator</h2>
    <div class="calc-container">
      <div class="calc-row">
        <div class="calc-field">
          <label>Account Balance ($)</label>
          <input type="number" id="calc-balance" placeholder="10000" value="10000">
        </div>
        <div class="calc-field">
          <label>Risk Percentage (%)</label>
          <input type="number" id="calc-risk-pct" placeholder="1" value="1" step="0.25">
        </div>
      </div>
      <div class="calc-row">
        <div class="calc-field">
          <label>Entry Price ($)</label>
          <input type="number" id="calc-entry" placeholder="30000" step="0.01">
        </div>
        <div class="calc-field">
          <label>Stop Loss ($)</label>
          <input type="number" id="calc-sl" placeholder="29700" step="0.01">
        </div>
      </div>
      <div class="calc-row">
        <div class="calc-field">
          <label>Take Profit ($) <span style="color:var(--text-dim)">(optional)</span></label>
          <input type="number" id="calc-tp" placeholder="30900" step="0.01">
        </div>
        <div class="calc-field" style="display:flex;align-items:flex-end">
          <button class="calc-btn" onclick="calculatePosition()">Calculate Position</button>
        </div>
      </div>
      <div class="calc-results" id="calc-results">
        <div class="calc-result-item">
          <span class="label">Position Size</span>
          <span class="value" id="calc-res-size">--</span>
        </div>
        <div class="calc-result-item">
          <span class="label">Risk Amount ($)</span>
          <span class="value" id="calc-res-risk">--</span>
        </div>
        <div class="calc-result-item">
          <span class="label">Risk/Reward Ratio</span>
          <span class="value" id="calc-res-rr">--</span>
        </div>
        <div class="calc-result-item">
          <span class="label">Potential Profit</span>
          <span class="value" id="calc-res-profit">--</span>
        </div>
      </div>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">Institutional Risk Framework</h2>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-icon">✅</div>
        <div class="card-title">Pre-Trade Checklist</div>
        <div class="card-desc">
          Before every trade, confirm:<br>
          - Risk % predetermined<br>
          - Stop loss identified on chart<br>
          - R/R ratio calculated (min 1:2)<br>
          - Position size calculated via formula<br>
          - Total portfolio risk checked (<20%)
        </div>
      </div>
      <div class="course-card">
        <div class="card-icon">📏</div>
        <div class="card-title">Risk Scaling Rules</div>
        <div class="card-desc">
          <span style="color:var(--red)">Drawdown >10%:</span> Reduce size by 50%<br>
          <span style="color:var(--yellow)">Drawdown 5-10%:</span> Reduce size by 25%<br>
          <span style="color:var(--green)">Profitable streak:</span> Increase size by 25%<br><br>
          Scale with performance, not emotion.
        </div>
      </div>
      <div class="course-card">
        <div class="card-icon">🚨</div>
        <div class="card-title">Emergency Protocols</div>
        <div class="card-desc">
          <strong>Stop trading immediately when:</strong><br><br>
          <span style="color:var(--red)">Daily loss: 6%</span> → Stop for the day<br>
          <span style="color:var(--red)">Weekly loss: 10%</span> → Stop for the week<br>
          <span style="color:var(--red)">Monthly loss: 15%</span> → Stop, review strategy
        </div>
      </div>
      <div class="course-card">
        <div class="card-icon">📈</div>
        <div class="card-title">Performance Metrics</div>
        <div class="card-desc">
          Track these over 30+ trades:<br><br>
          Win Rate: Track across 30+ trades<br>
          Average R/R: Target 1:2.5+<br>
          Max Drawdown: Keep under 20%<br>
          Profit Factor: Target >1.5
        </div>
      </div>
      <div class="course-card">
        <div class="card-icon">🎯</div>
        <div class="card-title">Position Management</div>
        <div class="card-desc">
          - Scale out at key levels<br>
          - Trail stops with market structure<br>
          - Move to breakeven at 1:1<br>
          - Take partial profit at 1:2<br><br>
          Let winners run, cut losers short.
        </div>
      </div>
      <div class="course-card">
        <div class="card-icon">📝</div>
        <div class="card-title">Documentation</div>
        <div class="card-desc">
          - Log every single trade<br>
          - Record your reasoning before entry<br>
          - Track emotional state during trades<br>
          - Review your journal weekly<br><br>
          What gets measured gets managed.
        </div>
      </div>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">Trading Psychology</h2>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-icon">🧠</div>
        <div class="card-title">Emotional Risk Factors</div>
        <div class="card-desc">
          <strong>Fear:</strong> Missing entries, cutting winners early<br>
          <strong>Greed:</strong> Oversizing, ignoring exits<br>
          <strong>Revenge:</strong> Trading to recover losses<br>
          <strong>Overconfidence:</strong> Ignoring risk after wins<br><br>
          <span style="color:var(--green)"><strong>Solution:</strong> Mechanical rules, journaling, scheduled breaks</span>
        </div>
      </div>
      <div class="course-card">
        <div class="card-icon">🛡️</div>
        <div class="card-title">Mental Stop Losses</div>
        <div class="card-desc">
          Stop trading when:<br>
          - Daily loss reaches 6%<br>
          - 3-4 consecutive losses hit<br>
          - Emotional state compromised<br>
          - Market is choppy/unclear<br><br>
          Protecting your mental capital is as important as protecting financial capital.
        </div>
      </div>
      <div class="course-card">
        <div class="card-icon">💪</div>
        <div class="card-title">Building Discipline</div>
        <div class="card-desc">
          1. Start small (0.25% risk per trade)<br>
          2. Follow mechanical rules exactly<br>
          3. Track everything in a journal<br>
          4. Regular weekly/monthly reviews<br><br>
          Discipline is a muscle. Build it gradually with small, consistent actions.
        </div>
      </div>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">Practice Scenarios</h2>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-icon">1</div>
        <div class="card-title">Conservative Swing Trade</div>
        <div class="card-desc">
          <strong>Setup:</strong><br>
          Account: $5,000 | Risk: 1%<br>
          Entry: $28,000 | Stop: $27,580<br><br>
          <strong>Solution:</strong><br>
          Risk Amount: $5,000 × 1% = <span style="color:var(--green)">$50</span><br>
          Per-Unit Risk: $28,000 - $27,580 = <span style="color:var(--green)">$420</span><br>
          Position Size: $50 / $420 = <span style="color:var(--green)">0.119 units</span>
        </div>
      </div>
      <div class="course-card">
        <div class="card-icon">2</div>
        <div class="card-title">Scalping Setup</div>
        <div class="card-desc">
          <strong>Setup:</strong><br>
          Account: $12,000 | Risk: 0.5%<br>
          Entry: $31,200 | Stop: $30,936<br><br>
          <strong>Solution:</strong><br>
          Risk Amount: $12,000 × 0.5% = <span style="color:var(--green)">$60</span><br>
          Per-Unit Risk: $31,200 - $30,936 = <span style="color:var(--green)">$264</span><br>
          Position Size: $60 / $264 = <span style="color:var(--green)">0.227 units</span>
        </div>
      </div>
      <div class="course-card">
        <div class="card-icon">3</div>
        <div class="card-title">Aggressive Position</div>
        <div class="card-desc">
          <strong>Setup:</strong><br>
          Account: $20,000 | Risk: 2%<br>
          Entry: $29,500 | Stop: $28,905<br><br>
          <strong>Solution:</strong><br>
          Risk Amount: $20,000 × 2% = <span style="color:var(--green)">$400</span><br>
          Per-Unit Risk: $29,500 - $28,905 = <span style="color:var(--green)">$595</span><br>
          Position Size: $400 / $595 = <span style="color:var(--green)">0.672 units</span>
        </div>
      </div>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">Mastery Checklist</h2>
    <div class="checklist">
      <div class="checklist-item" onclick="toggleChecklist('s4-sizing')">
        <span class="checklist-box" id="s4-sizing"></span>
        I can calculate position size using the formula for any trade
      </div>
      <div class="checklist-item" onclick="toggleChecklist('s4-rr')">
        <span class="checklist-box" id="s4-rr"></span>
        I understand risk/reward ratios and only take 1:2+ setups
      </div>
      <div class="checklist-item" onclick="toggleChecklist('s4-stops')">
        <span class="checklist-box" id="s4-stops"></span>
        I know how to place stop losses at structural levels
      </div>
      <div class="checklist-item" onclick="toggleChecklist('s4-daily')">
        <span class="checklist-box" id="s4-daily"></span>
        I understand daily loss limits and emergency protocols
      </div>
      <div class="checklist-item" onclick="toggleChecklist('s4-psychology')">
        <span class="checklist-box" id="s4-psychology"></span>
        I recognize emotional risk factors and have mitigation strategies
      </div>
      <div class="checklist-item" onclick="toggleChecklist('s4-portfolio')">
        <span class="checklist-box" id="s4-portfolio"></span>
        I understand portfolio heat management and correlation risk
      </div>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">Knowledge Check</h2>
    <div class="quiz-container" id="quiz-step4">
      <div class="quiz-question" data-correct="b">
        <p><strong>1.</strong> With a $10,000 account and 1% risk per trade, what is your risk amount?</p>
        <label class="quiz-option"><input type="radio" name="q4-1" value="a" class="quiz-radio"> $10</label>
        <label class="quiz-option"><input type="radio" name="q4-1" value="b" class="quiz-radio"> $100</label>
        <label class="quiz-option"><input type="radio" name="q4-1" value="c" class="quiz-radio"> $1,000</label>
        <label class="quiz-option"><input type="radio" name="q4-1" value="d" class="quiz-radio"> $50</label>
      </div>
      <div class="quiz-question" data-correct="c">
        <p><strong>2.</strong> If your entry is $30,000 and stop loss is $29,700, what is the per-unit risk?</p>
        <label class="quiz-option"><input type="radio" name="q4-2" value="a" class="quiz-radio"> $30</label>
        <label class="quiz-option"><input type="radio" name="q4-2" value="b" class="quiz-radio"> $3,000</label>
        <label class="quiz-option"><input type="radio" name="q4-2" value="c" class="quiz-radio"> $300</label>
        <label class="quiz-option"><input type="radio" name="q4-2" value="d" class="quiz-radio"> $297</label>
      </div>
      <div class="quiz-question" data-correct="b">
        <p><strong>3.</strong> If you risk $100 with a 1:2 risk/reward ratio, what is your target profit?</p>
        <label class="quiz-option"><input type="radio" name="q4-3" value="a" class="quiz-radio"> $100</label>
        <label class="quiz-option"><input type="radio" name="q4-3" value="b" class="quiz-radio"> $200</label>
        <label class="quiz-option"><input type="radio" name="q4-3" value="c" class="quiz-radio"> $50</label>
        <label class="quiz-option"><input type="radio" name="q4-3" value="d" class="quiz-radio"> $300</label>
      </div>
      <div class="quiz-question" data-correct="c">
        <p><strong>4.</strong> What is the maximum recommended daily risk limit?</p>
        <label class="quiz-option"><input type="radio" name="q4-4" value="a" class="quiz-radio"> 2%</label>
        <label class="quiz-option"><input type="radio" name="q4-4" value="b" class="quiz-radio"> 10%</label>
        <label class="quiz-option"><input type="radio" name="q4-4" value="c" class="quiz-radio"> 6%</label>
        <label class="quiz-option"><input type="radio" name="q4-4" value="d" class="quiz-radio"> 15%</label>
      </div>
      <button class="quiz-submit" onclick="submitQuiz('quiz-step4','step4')">Submit Answers</button>
    </div>

    <div class="step-nav">
      <button class="step-nav-btn" onclick="navigateCourse('step3')">&#8592; Step 3: Market Structure</button>
      <button class="step-nav-btn primary" onclick="navigateCourse('step5')">Step 5: Technical Indicators &#8594;</button>
    </div>
  `;
}

function calculatePosition() {
  const bal = parseFloat(document.getElementById('calc-balance').value) || 0;
  const riskPct = parseFloat(document.getElementById('calc-risk-pct').value) || 1;
  const entry = parseFloat(document.getElementById('calc-entry').value) || 0;
  const sl = parseFloat(document.getElementById('calc-sl').value) || 0;
  const tp = parseFloat(document.getElementById('calc-tp').value) || 0;
  if (!bal || !entry || !sl) return;
  const riskAmt = bal * (riskPct / 100);
  const perUnitRisk = Math.abs(entry - sl);
  const posSize = perUnitRisk > 0 ? riskAmt / perUnitRisk : 0;
  const rr = tp && perUnitRisk > 0 ? (Math.abs(tp - entry) / perUnitRisk).toFixed(2) : 'N/A';
  const potProfit = tp ? (Math.abs(tp - entry) * posSize).toFixed(2) : 'N/A';
  const resultsEl = document.getElementById('calc-results');
  if (resultsEl) {
    document.getElementById('calc-res-size').textContent = posSize.toFixed(4) + ' units';
    document.getElementById('calc-res-risk').textContent = '$' + riskAmt.toFixed(2);
    document.getElementById('calc-res-rr').textContent = rr !== 'N/A' ? '1:' + rr : 'N/A';
    document.getElementById('calc-res-profit').textContent = potProfit !== 'N/A' ? '$' + potProfit : 'N/A';
    resultsEl.style.display = 'flex';
  }
}

function renderStep5() {
  return `
    <div class="course-page-header">
      <h1>Step 5: Technical Indicators Mastery</h1>
      <p class="subtitle">Master RSI, MACD, MFI, and Stochastic RSI for precise market timing</p>
    </div>
    <div style="position:relative;padding-bottom:56.25%;height:0;margin:1rem 0;border-radius:10px;overflow:hidden;">
      <iframe src="https://www.youtube.com/embed/F8LbNp7aUsg" style="position:absolute;top:0;left:0;width:100%;height:100%;border:none;" allowfullscreen></iframe>
    </div>

    <div class="metric-row">
      <div class="metric-card">
        <div class="metric-val" style="color:var(--cyan)">4</div>
        <div class="metric-label">Core Indicators</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color:var(--green)">MTF</div>
        <div class="metric-label">Multi-Timeframe</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color:var(--yellow)">Pro Level</div>
        <div class="metric-label">Signals</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color:var(--purple)">Real Time</div>
        <div class="metric-label">Analysis</div>
      </div>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">RSI (Relative Strength Index)</h2>
    <div class="indicator-card">
      <h3 style="color:var(--green);margin-bottom:1rem">Fundamentals</h3>
      <div class="metric-row">
        <div class="metric-card">
          <div class="metric-val" style="color:var(--cyan)">0-100</div>
          <div class="metric-label">Range</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color:var(--text)">14</div>
          <div class="metric-label">Period</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color:var(--red)">70</div>
          <div class="metric-label">Overbought</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color:var(--green)">30</div>
          <div class="metric-label">Oversold</div>
        </div>
      </div>

      <h3 style="color:var(--green);margin:1.5rem 0 1rem">Trading Signals</h3>
      <div class="course-grid">
        <div class="course-card">
          <div class="card-icon" style="color:var(--green)">BUY</div>
          <div class="card-title">Bullish Signal</div>
          <div class="card-desc">RSI crosses above 30 in an uptrend. Indicates oversold bounce with trend support.</div>
        </div>
        <div class="course-card">
          <div class="card-icon" style="color:var(--red)">SELL</div>
          <div class="card-title">Bearish Signal</div>
          <div class="card-desc">RSI crosses below 70 in a downtrend. Indicates overbought reversal with trend confirmation.</div>
        </div>
        <div class="course-card">
          <div class="card-icon" style="color:var(--yellow)">DIV</div>
          <div class="card-title">Divergence</div>
          <div class="card-desc">Price makes new high/low but RSI does not. Signals potential reversal or weakening momentum.</div>
        </div>
      </div>

      <div class="info-box warning" style="margin-top:1rem">
        <strong>Common Mistakes:</strong> Don't buy just because RSI is oversold in a downtrend. Don't sell just because RSI is overbought in an uptrend. Always consider the trend context first.
      </div>

      <h3 style="color:var(--green);margin:1.5rem 0 1rem">Multi-Timeframe RSI</h3>
      <p style="color:var(--text-dim)">
        <strong style="color:var(--cyan)">HTF (4H/Daily):</strong> Determine overall bias - is RSI trending up or down?<br>
        <strong style="color:var(--yellow)">MTF (1H):</strong> Timing - wait for RSI to reach actionable zones<br>
        <strong style="color:var(--green)">LTF (15m):</strong> Precise entries - fine-tune entry on lower timeframe RSI signals
      </p>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">MACD (Moving Average Convergence Divergence)</h2>
    <div class="indicator-card">
      <h3 style="color:var(--green);margin-bottom:1rem">Components</h3>
      <div class="metric-row">
        <div class="metric-card">
          <div class="metric-val" style="color:var(--cyan);font-size:1rem">12 EMA - 26 EMA</div>
          <div class="metric-label">MACD Line</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color:var(--yellow);font-size:1rem">9 EMA of MACD</div>
          <div class="metric-label">Signal Line</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color:var(--green);font-size:1rem">MACD - Signal</div>
          <div class="metric-label">Histogram</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color:var(--text-dim);font-size:1rem">Baseline</div>
          <div class="metric-label">Zero Line</div>
        </div>
      </div>

      <h3 style="color:var(--green);margin:1.5rem 0 1rem">Trading Signals</h3>
      <div class="course-grid">
        <div class="course-card">
          <div class="card-icon" style="color:var(--green)">BUY</div>
          <div class="card-title">Bullish Signals</div>
          <div class="card-desc">Histogram above zero and rising. Bullish crossover: MACD line crosses above signal line.</div>
        </div>
        <div class="course-card">
          <div class="card-icon" style="color:var(--red)">SELL</div>
          <div class="card-title">Bearish Signals</div>
          <div class="card-desc">Histogram below zero and falling. Bearish crossover: MACD line crosses below signal line.</div>
        </div>
      </div>

      <h3 style="color:var(--green);margin:1.5rem 0 1rem">Histogram Analysis</h3>
      <p style="color:var(--text-dim)">
        <span style="color:var(--green)">Rising histogram</span> = Bullish momentum building<br>
        <span style="color:var(--red)">Falling histogram</span> = Bearish momentum building<br>
        <span style="color:var(--green)">Above zero</span> = Bulls in control<br>
        <span style="color:var(--red)">Below zero</span> = Bears in control
      </p>

      <h3 style="color:var(--green);margin:1.5rem 0 1rem">Advanced MACD</h3>
      <p style="color:var(--text-dim)">
        <strong>Hidden Divergence:</strong> Continuation signal - trend likely to persist<br>
        <strong>Regular Divergence:</strong> Reversal signal - trend may be exhausting<br>
        <strong>Histogram Peaks:</strong> Extreme readings signal momentum exhaustion
      </p>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">MFI (Money Flow Index)</h2>
    <div class="indicator-card">
      <h3 style="color:var(--green);margin-bottom:1rem">Fundamentals</h3>
      <div class="metric-row">
        <div class="metric-card">
          <div class="metric-val" style="color:var(--cyan)">0-100</div>
          <div class="metric-label">Range</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color:var(--text)">14</div>
          <div class="metric-label">Period</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color:var(--red)">80</div>
          <div class="metric-label">Overbought</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color:var(--green)">20</div>
          <div class="metric-label">Oversold</div>
        </div>
      </div>

      <div class="info-box tip" style="margin:1rem 0">
        <strong>Key Difference from RSI:</strong> MFI incorporates volume data, making it a volume-weighted momentum indicator. This gives it an edge in detecting institutional money flow that pure price-based indicators miss.
      </div>

      <h3 style="color:var(--green);margin:1.5rem 0 1rem">Money Flow Signals</h3>
      <div class="course-grid">
        <div class="course-card">
          <div class="card-icon" style="color:var(--green)">IN</div>
          <div class="card-title">Capital Inflow</div>
          <div class="card-desc">MFI rising alongside price indicates genuine buying pressure with volume confirmation.</div>
        </div>
        <div class="course-card">
          <div class="card-icon" style="color:var(--red)">OUT</div>
          <div class="card-title">Capital Outflow</div>
          <div class="card-desc">MFI falling alongside price indicates selling pressure with volume confirmation.</div>
        </div>
        <div class="course-card">
          <div class="card-icon" style="color:var(--yellow)">DIV</div>
          <div class="card-title">Divergences</div>
          <div class="card-desc">MFI diverging from price signals that volume does not support the current move. High probability reversal signal.</div>
        </div>
      </div>

      <h3 style="color:var(--green);margin:1.5rem 0 1rem">Smart Money Detection</h3>
      <p style="color:var(--text-dim)">
        <span style="color:var(--green)">Rising MFI + Rising Price</span> = Smart money buying (strong signal)<br>
        <span style="color:var(--yellow)">Falling MFI + Rising Price</span> = Retail buying without volume support (weak/trap)<br>
        <span style="color:var(--red)">Rising MFI + Falling Price</span> = Accumulation phase (watch for reversal)<br>
        <span style="color:var(--red)">Falling MFI + Falling Price</span> = Smart money selling (strong bearish)
      </p>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">Stochastic RSI</h2>
    <div class="indicator-card">
      <h3 style="color:var(--green);margin-bottom:1rem">Basics</h3>
      <div class="metric-row">
        <div class="metric-card">
          <div class="metric-val" style="color:var(--cyan)">0-1</div>
          <div class="metric-label">Range</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color:var(--text)">%K / %D</div>
          <div class="metric-label">Lines</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color:var(--red)">0.8</div>
          <div class="metric-label">Overbought</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color:var(--green)">0.2</div>
          <div class="metric-label">Oversold</div>
        </div>
      </div>
      <p style="color:var(--text-dim);margin:1rem 0">More sensitive than standard RSI. Applies stochastic oscillator formula to RSI values for faster signals.</p>

      <h3 style="color:var(--green);margin:1.5rem 0 1rem">Crossover Signals</h3>
      <div class="course-grid">
        <div class="course-card">
          <div class="card-icon" style="color:var(--green)">BUY</div>
          <div class="card-title">Bullish Crossover</div>
          <div class="card-desc">%K crosses above %D in the oversold zone (below 0.2). Best signal when confirmed by higher timeframe trend.</div>
        </div>
        <div class="course-card">
          <div class="card-icon" style="color:var(--red)">SELL</div>
          <div class="card-title">Bearish Crossover</div>
          <div class="card-desc">%K crosses below %D in the overbought zone (above 0.8). Best signal when confirmed by higher timeframe trend.</div>
        </div>
      </div>

      <div class="info-box warning" style="margin-top:1rem">
        <strong>Warning:</strong> Stochastic RSI is very noisy on lower timeframes. Best used on 1H and above. On 5m/15m charts, expect many false signals. Always combine with higher timeframe analysis.
      </div>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">Multi-Timeframe Analysis Strategy</h2>
    <div class="indicator-card">
      <div class="course-grid">
        <div class="course-card">
          <div class="card-icon" style="color:var(--purple)">16H</div>
          <div class="card-title">Overall Trend Bias</div>
          <div class="card-desc">Use MACD direction and MFI trend to determine the dominant market direction. This is your directional filter.</div>
        </div>
        <div class="course-card">
          <div class="card-icon" style="color:var(--blue)">6H</div>
          <div class="card-title">Intermediate Confirmation</div>
          <div class="card-desc">Confirm with RSI levels and MACD alignment. Both timeframes should agree on direction before proceeding.</div>
        </div>
        <div class="course-card">
          <div class="card-icon" style="color:var(--cyan)">1H</div>
          <div class="card-title">Precise Entry Timing</div>
          <div class="card-desc">Use Stochastic RSI crossovers and MFI readings for precise entry timing once higher timeframes confirm.</div>
        </div>
      </div>

      <div class="info-box success" style="margin-top:1rem">
        <strong>MTF Strategy Flow:</strong> Check 16H bias (MACD + MFI) → Confirm 6H alignment (RSI + MACD) → Wait for 1H trigger signal (Stoch RSI + MFI) → Execute trade with trend
      </div>
    </div>

    <div class="video-card" style="margin:2rem 0">
      <div class="play-icon">&#9654;</div>
      <h3>Golden Pocket Fibonacci Strategy</h3>
      <p style="color:var(--text-dim)">Masterclass: Combining Fibonacci retracements with indicator confluence for high-probability entries</p>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">Mastery Checklist</h2>
    <div class="checklist">
      <div class="checklist-item" onclick="toggleChecklist('s5-rsi')">
        <span class="checklist-box" id="s5-rsi"></span>
        I understand RSI overbought/oversold levels and divergence signals
      </div>
      <div class="checklist-item" onclick="toggleChecklist('s5-macd')">
        <span class="checklist-box" id="s5-macd"></span>
        I can read MACD histogram, crossovers, and divergences
      </div>
      <div class="checklist-item" onclick="toggleChecklist('s5-mfi')">
        <span class="checklist-box" id="s5-mfi"></span>
        I understand MFI and how volume-weighting differs from RSI
      </div>
      <div class="checklist-item" onclick="toggleChecklist('s5-stoch')">
        <span class="checklist-box" id="s5-stoch"></span>
        I can identify Stochastic RSI crossover signals in overbought/oversold zones
      </div>
      <div class="checklist-item" onclick="toggleChecklist('s5-mtf')">
        <span class="checklist-box" id="s5-mtf"></span>
        I understand the multi-timeframe analysis workflow (16H → 6H → 1H)
      </div>
      <div class="checklist-item" onclick="toggleChecklist('s5-combine')">
        <span class="checklist-box" id="s5-combine"></span>
        I can combine multiple indicators for confluence-based entries
      </div>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">Knowledge Check</h2>
    <div class="quiz-container" id="quiz-step5">
      <div class="quiz-question" data-correct="b">
        <p><strong>1.</strong> MACD histogram above zero and rising suggests:</p>
        <label class="quiz-option"><input type="radio" name="q5-1" value="a" class="quiz-radio"> Bearish reversal incoming</label>
        <label class="quiz-option"><input type="radio" name="q5-1" value="b" class="quiz-radio"> Bullish momentum building and accelerating</label>
        <label class="quiz-option"><input type="radio" name="q5-1" value="c" class="quiz-radio"> Market is range-bound</label>
        <label class="quiz-option"><input type="radio" name="q5-1" value="d" class="quiz-radio"> Volume is declining</label>
      </div>
      <div class="quiz-question" data-correct="c">
        <p><strong>2.</strong> A Stochastic RSI bullish crossover in the oversold zone indicates:</p>
        <label class="quiz-option"><input type="radio" name="q5-2" value="a" class="quiz-radio"> Strong sell signal</label>
        <label class="quiz-option"><input type="radio" name="q5-2" value="b" class="quiz-radio"> Market is about to crash</label>
        <label class="quiz-option"><input type="radio" name="q5-2" value="c" class="quiz-radio"> Momentum turning up, potential buy opportunity</label>
        <label class="quiz-option"><input type="radio" name="q5-2" value="d" class="quiz-radio"> Indicator is broken</label>
      </div>
      <div class="quiz-question" data-correct="b">
        <p><strong>3.</strong> MFI green and rising while price is also rising suggests:</p>
        <label class="quiz-option"><input type="radio" name="q5-3" value="a" class="quiz-radio"> Retail panic buying</label>
        <label class="quiz-option"><input type="radio" name="q5-3" value="b" class="quiz-radio"> Capital inflow, smart money buying</label>
        <label class="quiz-option"><input type="radio" name="q5-3" value="c" class="quiz-radio"> Market is about to reverse</label>
        <label class="quiz-option"><input type="radio" name="q5-3" value="d" class="quiz-radio"> Low volume manipulation</label>
      </div>
      <div class="quiz-question" data-correct="c">
        <p><strong>4.</strong> The correct multi-timeframe sequence for an MFI+MACD strategy is:</p>
        <label class="quiz-option"><input type="radio" name="q5-4" value="a" class="quiz-radio"> Start on 1H, then check higher timeframes</label>
        <label class="quiz-option"><input type="radio" name="q5-4" value="b" class="quiz-radio"> Only use one timeframe for simplicity</label>
        <label class="quiz-option"><input type="radio" name="q5-4" value="c" class="quiz-radio"> Check 16H/6H for bias, trigger on 1H</label>
        <label class="quiz-option"><input type="radio" name="q5-4" value="d" class="quiz-radio"> Use 5m for all decisions</label>
      </div>
      <button class="quiz-submit" onclick="submitQuiz('quiz-step5','step5')">Submit Answers</button>
    </div>

    <div class="step-nav">
      <button class="step-nav-btn" onclick="navigateCourse('step4')">&#8592; Step 4: Risk Management</button>
      <button class="step-nav-btn primary" onclick="navigateCourse('step6')">Step 6: Readiness Assessment &#8594;</button>
    </div>
  `;
}

function renderStep6() {
  return `
    <div class="course-page-header">
      <h1>Step 6: Trading Readiness Assessment</h1>
      <p class="subtitle">Complete your comprehensive readiness evaluation</p>
    </div>
    <div style="position:relative;padding-bottom:56.25%;height:0;margin:1rem 0;border-radius:10px;overflow:hidden;">
      <iframe src="https://www.youtube.com/embed/H7Gnh1W6VuE" style="position:absolute;top:0;left:0;width:100%;height:100%;border:none;" allowfullscreen></iframe>
    </div>

    <div class="metric-row">
      <div class="metric-card">
        <div class="metric-val" style="color:var(--cyan)"><span id="ra-quizzes">0/5</span></div>
        <div class="metric-label">Quizzes Passed</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color:var(--green)"><span id="ra-trades">0/2</span></div>
        <div class="metric-label">Practice Trades</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color:var(--yellow)"><span id="ra-progress">0%</span></div>
        <div class="metric-label">Overall Progress</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color:var(--red)"><span id="ra-status">Not Ready</span></div>
        <div class="metric-label">Status</div>
      </div>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">Requirements Assessment</h2>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-icon">📝</div>
        <div class="card-title">Knowledge Assessment</div>
        <div class="card-desc">
          Pass all 5 core quizzes from Steps 1-5.<br><br>
          Each quiz tests critical trading knowledge. You must demonstrate understanding of fundamentals, market structure, risk management, and technical analysis.<br><br>
          <strong>Progress:</strong> <span id="ra-quiz-detail">Check your quiz results in each step.</span>
        </div>
      </div>
      <div class="course-card">
        <div class="card-icon">📊</div>
        <div class="card-title">Practical Application</div>
        <div class="card-desc">
          Submit at least 2 practice trades with detailed analysis.<br><br>
          Each practice trade must include a strategy, entry/stop/target levels, trade reasoning, and risk management plan.<br><br>
          <strong>Progress:</strong> <span id="ra-trade-detail">Submit practice trades below.</span>
        </div>
      </div>
      <div class="course-card">
        <div class="card-icon">🏆</div>
        <div class="card-title">Overall Readiness</div>
        <div class="card-desc">
          Combined score from quizzes and practice trades determines your readiness.<br><br>
          <strong>Quizzes:</strong> 70% weight<br>
          <strong>Practice Trades:</strong> 30% weight<br><br>
          You need 100% completion to be marked as ready.
        </div>
      </div>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">Learning Journey Progress</h2>
    <div class="card" style="padding:2rem">
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:1rem">
        <div class="phase-box" id="phase-step1">
          <div class="phase-item">
            <div style="font-size:1.5rem;margin-bottom:0.5rem">1</div>
            <div style="font-weight:600;color:var(--text)">Trading Fundamentals</div>
            <div style="color:var(--text-dim);font-size:0.85rem;margin-top:0.25rem" id="phase-status-1">Incomplete</div>
          </div>
        </div>
        <div class="phase-box" id="phase-step2">
          <div class="phase-item">
            <div style="font-size:1.5rem;margin-bottom:0.5rem">2</div>
            <div style="font-weight:600;color:var(--text)">Professional Setup</div>
            <div style="color:var(--text-dim);font-size:0.85rem;margin-top:0.25rem" id="phase-status-2">Incomplete</div>
          </div>
        </div>
        <div class="phase-box" id="phase-step3">
          <div class="phase-item">
            <div style="font-size:1.5rem;margin-bottom:0.5rem">3</div>
            <div style="font-weight:600;color:var(--text)">Market Structure</div>
            <div style="color:var(--text-dim);font-size:0.85rem;margin-top:0.25rem" id="phase-status-3">Incomplete</div>
          </div>
        </div>
        <div class="phase-box" id="phase-step4">
          <div class="phase-item">
            <div style="font-size:1.5rem;margin-bottom:0.5rem">4</div>
            <div style="font-weight:600;color:var(--text)">Risk Management</div>
            <div style="color:var(--text-dim);font-size:0.85rem;margin-top:0.25rem" id="phase-status-4">Incomplete</div>
          </div>
        </div>
        <div class="phase-box" id="phase-step5">
          <div class="phase-item">
            <div style="font-size:1.5rem;margin-bottom:0.5rem">5</div>
            <div style="font-weight:600;color:var(--text)">Technical Indicators</div>
            <div style="color:var(--text-dim);font-size:0.85rem;margin-top:0.25rem" id="phase-status-5">Incomplete</div>
          </div>
        </div>
        <div class="phase-box" id="phase-step6">
          <div class="phase-item">
            <div style="font-size:1.5rem;margin-bottom:0.5rem">6</div>
            <div style="font-weight:600;color:var(--text)">Readiness Assessment</div>
            <div style="color:var(--text-dim);font-size:0.85rem;margin-top:0.25rem" id="phase-status-6">In Progress</div>
          </div>
        </div>
      </div>
    </div>

    <div class="video-card" style="margin:2rem 0">
      <div class="play-icon">&#9654;</div>
      <h3>Advanced Fibonacci Extensions</h3>
      <p style="color:var(--text-dim)">Masterclass: Using Fibonacci extensions to identify high-probability profit targets and trend projections</p>
    </div>

    <h2 style="color:var(--cyan);margin:2rem 0 1rem">Practice Trade Logger</h2>
    <div class="card" style="padding:2rem">
      <div style="display:grid;gap:1rem">
        <div class="calc-row">
          <div class="calc-field">
            <label>Strategy</label>
            <select id="pt-strategy" style="width:100%;padding:0.5rem;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:6px">
              <option value="Trendline Breakout">Trendline Breakout</option>
              <option value="MFI+MACD">MFI+MACD</option>
              <option value="2-Week Macro">2-Week Macro</option>
              <option value="Custom">Custom</option>
            </select>
          </div>
        </div>
        <div class="calc-row">
          <div class="calc-field">
            <label>Entry Price ($)</label>
            <input type="number" id="pt-entry" placeholder="30000" step="0.01">
          </div>
          <div class="calc-field">
            <label>Stop Loss ($)</label>
            <input type="number" id="pt-stop" placeholder="29700" step="0.01">
          </div>
          <div class="calc-field">
            <label>Target Price ($)</label>
            <input type="number" id="pt-target" placeholder="30900" step="0.01">
          </div>
        </div>
        <div class="calc-field">
          <label>Trade Reasoning</label>
          <textarea id="pt-reasoning" rows="3" placeholder="Explain your trade thesis, confluence factors, and why you chose this entry..." style="width:100%;padding:0.5rem;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:6px;resize:vertical"></textarea>
        </div>
        <div class="calc-field">
          <label>Risk Management Notes</label>
          <textarea id="pt-risk-notes" rows="3" placeholder="Position size, risk %, R/R ratio, max daily risk, stop placement logic..." style="width:100%;padding:0.5rem;background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:6px;resize:vertical"></textarea>
        </div>
        <button class="calc-btn" onclick="submitPracticeTrade()">Submit Practice Trade</button>
      </div>
    </div>

    <div id="practice-trades-list" style="margin-top:1rem"></div>

    <div class="info-box warning" style="margin:2rem 0">
      <strong>Important Disclaimers</strong><br><br>
      <strong>Educational Purpose:</strong> This course is for educational purposes only and does not constitute financial advice.<br>
      <strong>Risk Warning:</strong> Trading cryptocurrencies involves substantial risk of loss and is not suitable for all investors.<br>
      <strong>No Financial Advice:</strong> Nothing in this course should be construed as investment advice or a recommendation to trade.<br>
      <strong>Practice First:</strong> Always practice with paper trading before risking real capital.<br>
      <strong>Market Volatility:</strong> Cryptocurrency markets are highly volatile. Past performance does not guarantee future results.<br>
      <strong>Continuous Learning:</strong> Markets evolve constantly. Commit to ongoing education and adaptation.
    </div>

    <div style="text-align:center;margin:2rem 0">
      <button class="step-nav-btn primary" onclick="navigateCourse('dashboard')" style="font-size:1.1rem;padding:1rem 2rem">Back to Dashboard</button>
    </div>

    <div class="step-nav">
      <button class="step-nav-btn" onclick="navigateCourse('step5')">&#8592; Step 5: Technical Indicators</button>
      <button class="step-nav-btn primary" onclick="navigateCourse('dashboard')">Back to Dashboard</button>
    </div>
  `;
}

function submitPracticeTrade() {
  const strategy = document.getElementById('pt-strategy').value;
  const entry = document.getElementById('pt-entry').value;
  const stop = document.getElementById('pt-stop').value;
  const target = document.getElementById('pt-target').value;
  const reasoning = document.getElementById('pt-reasoning').value;
  const riskNotes = document.getElementById('pt-risk-notes').value;

  if (!entry || !stop || !target || !reasoning) {
    alert('Please fill in all required fields (Entry, Stop, Target, and Reasoning).');
    return;
  }

  var progress = {};
  try {
    progress = JSON.parse(localStorage.getItem('courseProgress') || '{}');
  } catch (e) {
    progress = {};
  }

  if (!progress.practiceTrades) {
    progress.practiceTrades = [];
  }

  progress.practiceTrades.push({
    id: Date.now(),
    strategy: strategy,
    entry: parseFloat(entry),
    stop: parseFloat(stop),
    target: parseFloat(target),
    reasoning: reasoning,
    riskNotes: riskNotes,
    timestamp: new Date().toISOString()
  });

  localStorage.setItem('courseProgress', JSON.stringify(progress));

  document.getElementById('pt-entry').value = '';
  document.getElementById('pt-stop').value = '';
  document.getElementById('pt-target').value = '';
  document.getElementById('pt-reasoning').value = '';
  document.getElementById('pt-risk-notes').value = '';

  renderPracticeTradesList();
  updateReadinessMetrics();
}

function renderPracticeTradesList() {
  var progress = {};
  try {
    progress = JSON.parse(localStorage.getItem('courseProgress') || '{}');
  } catch (e) {
    progress = {};
  }

  var trades = progress.practiceTrades || [];
  var container = document.getElementById('practice-trades-list');
  if (!container) return;

  if (trades.length === 0) {
    container.innerHTML = '';
    return;
  }

  var html = '<h3 style="color:var(--green);margin-bottom:1rem">Submitted Practice Trades (' + trades.length + ')</h3>';

  trades.forEach(function(trade, index) {
    var entryVal = trade.entry;
    var stopVal = trade.stop;
    var targetVal = trade.target;
    var perUnitRisk = Math.abs(entryVal - stopVal);
    var rr = perUnitRisk > 0 ? (Math.abs(targetVal - entryVal) / perUnitRisk).toFixed(2) : 'N/A';
    var date = new Date(trade.timestamp).toLocaleDateString();

    html += '<div class="card" style="padding:1.5rem;margin-bottom:1rem">';
    html += '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.75rem">';
    html += '<strong style="color:var(--cyan)">Trade #' + (index + 1) + ' - ' + trade.strategy + '</strong>';
    html += '<span style="color:var(--text-dim);font-size:0.85rem">' + date + '</span>';
    html += '</div>';
    html += '<div class="metric-row" style="margin-bottom:0.75rem">';
    html += '<div class="metric-card"><div class="metric-val" style="font-size:1rem;color:var(--green)">$' + entryVal + '</div><div class="metric-label">Entry</div></div>';
    html += '<div class="metric-card"><div class="metric-val" style="font-size:1rem;color:var(--red)">$' + stopVal + '</div><div class="metric-label">Stop</div></div>';
    html += '<div class="metric-card"><div class="metric-val" style="font-size:1rem;color:var(--green)">$' + targetVal + '</div><div class="metric-label">Target</div></div>';
    html += '<div class="metric-card"><div class="metric-val" style="font-size:1rem;color:var(--cyan)">1:' + rr + '</div><div class="metric-label">R/R</div></div>';
    html += '</div>';
    html += '<p style="color:var(--text-dim);font-size:0.9rem;margin-bottom:0.5rem"><strong style="color:var(--text)">Reasoning:</strong> ' + trade.reasoning + '</p>';
    if (trade.riskNotes) {
      html += '<p style="color:var(--text-dim);font-size:0.9rem"><strong style="color:var(--text)">Risk Management:</strong> ' + trade.riskNotes + '</p>';
    }
    html += '</div>';
  });

  container.innerHTML = html;
}

function updateReadinessMetrics() {
  var progress = {};
  try {
    progress = JSON.parse(localStorage.getItem('courseProgress') || '{}');
  } catch (e) {
    progress = {};
  }

  var quizzesPassed = 0;
  var quizSteps = ['step1', 'step2', 'step3', 'step4', 'step5'];
  quizSteps.forEach(function(step) {
    if (progress[step] && progress[step].passed) {
      quizzesPassed++;
    }
  });

  var trades = progress.practiceTrades || [];
  var tradeCount = Math.min(trades.length, 2);

  var quizzesEl = document.getElementById('ra-quizzes');
  var tradesEl = document.getElementById('ra-trades');
  var progressEl = document.getElementById('ra-progress');
  var statusEl = document.getElementById('ra-status');

  if (quizzesEl) quizzesEl.textContent = quizzesPassed + '/5';
  if (tradesEl) tradesEl.textContent = tradeCount + '/2';

  var totalProgress = Math.round(((quizzesPassed / 5) * 70) + ((tradeCount / 2) * 30));
  if (progressEl) progressEl.textContent = totalProgress + '%';

  if (statusEl) {
    if (totalProgress >= 100) {
      statusEl.textContent = 'Ready';
      statusEl.style.color = 'var(--green)';
    } else if (totalProgress >= 50) {
      statusEl.textContent = 'In Progress';
      statusEl.style.color = 'var(--yellow)';
    } else {
      statusEl.textContent = 'Not Ready';
      statusEl.style.color = 'var(--red)';
    }
  }
}

// ── Strategies ──
// ============================================
// Nunu's Trading Masterclass - Part 4
// Strategy Pages: Trendline, MFI+MACD, Macro
// ============================================

// --- Fibonacci Calculator ---
function calcFibLevels() {
  var low = parseFloat(document.getElementById('fib-swing-low').value);
  var high = parseFloat(document.getElementById('fib-swing-high').value);
  var resultsEl = document.getElementById('fib-results');
  if (!resultsEl) return;
  if (isNaN(low) || isNaN(high) || low >= high) {
    resultsEl.innerHTML = '<div class="calc-result-item"><span class="label">Error</span><span class="value" style="color:var(--red)">Swing Low must be less than Swing High</span></div>';
    return;
  }
  var diff = high - low;
  var levels = [
    { name: '0.236 Retracement', val: high - diff * 0.236 },
    { name: '0.382 Retracement', val: high - diff * 0.382 },
    { name: '0.500 Retracement', val: high - diff * 0.5 },
    { name: '0.618 Retracement', val: high - diff * 0.618 },
    { name: '0.786 Retracement', val: high - diff * 0.786 },
    { name: '1.272 Extension', val: high + diff * 0.272 },
    { name: '1.618 Extension', val: high + diff * 0.618 },
    { name: '2.618 Extension', val: high + diff * 1.618 }
  ];
  var html = '';
  levels.forEach(function(l) {
    var color = l.name.includes('Extension') ? 'var(--green)' : 'var(--cyan)';
    html += '<div class="calc-result-item"><span class="label">' + l.name + '</span><span class="value" style="color:' + color + '">$' + l.val.toFixed(2) + '</span></div>';
  });
  resultsEl.innerHTML = html;
}

// --- MFI Position Size Calculator ---
function calcMfiPosition() {
  var balance = parseFloat(document.getElementById('mfi-balance').value);
  var riskPct = parseFloat(document.getElementById('mfi-risk').value);
  var entry = parseFloat(document.getElementById('mfi-entry').value);
  var stop = parseFloat(document.getElementById('mfi-stop').value);
  var resultsEl = document.getElementById('mfi-results');
  if (!resultsEl) return;
  if (isNaN(balance) || isNaN(riskPct) || isNaN(entry) || isNaN(stop) || entry <= 0 || stop <= 0) {
    resultsEl.innerHTML = '<div class="calc-result-item"><span class="label">Error</span><span class="value" style="color:var(--red)">Please fill all fields with valid numbers</span></div>';
    return;
  }
  var riskAmount = balance * (riskPct / 100);
  var stopDist = Math.abs(entry - stop);
  var stopPct = (stopDist / entry) * 100;
  var positionSize = riskAmount / stopDist;
  var positionValue = positionSize * entry;
  var leverage = positionValue / balance;
  resultsEl.innerHTML =
    '<div class="calc-result-item"><span class="label">Risk Amount</span><span class="value" style="color:var(--yellow)">$' + riskAmount.toFixed(2) + '</span></div>' +
    '<div class="calc-result-item"><span class="label">Stop Distance</span><span class="value" style="color:var(--red)">' + stopPct.toFixed(2) + '%</span></div>' +
    '<div class="calc-result-item"><span class="label">Position Size</span><span class="value" style="color:var(--green)">' + positionSize.toFixed(6) + ' units</span></div>' +
    '<div class="calc-result-item"><span class="label">Position Value</span><span class="value" style="color:var(--cyan)">$' + positionValue.toFixed(2) + '</span></div>' +
    '<div class="calc-result-item"><span class="label">Effective Leverage</span><span class="value" style="color:' + (leverage > 5 ? 'var(--red)' : 'var(--green)') + '">' + leverage.toFixed(2) + 'x</span></div>';
}

// --- Fib Trailing Calculator ---
function calcFibTrail() {
  var low = parseFloat(document.getElementById('fib-trail-low').value);
  var high = parseFloat(document.getElementById('fib-trail-high').value);
  var current = parseFloat(document.getElementById('fib-trail-current').value);
  var lastLevel = parseFloat(document.getElementById('fib-trail-level').value);
  var resultsEl = document.getElementById('fib-trail-results');
  if (!resultsEl) return;
  if (isNaN(low) || isNaN(high) || isNaN(current) || low >= high) {
    resultsEl.innerHTML = '<div class="calc-result-item"><span class="label">Error</span><span class="value" style="color:var(--red)">Please fill all fields correctly</span></div>';
    return;
  }
  var diff = high - low;
  var fibLevels = [
    { name: '0.618', mult: 0.618 },
    { name: '1.000', mult: 1.0 },
    { name: '1.618', mult: 1.618 },
    { name: '2.618', mult: 2.618 },
    { name: '3.618', mult: 3.618 },
    { name: '4.236', mult: 4.236 },
    { name: '6.618', mult: 6.618 },
    { name: '9.618', mult: 9.618 }
  ];
  var html = '';
  var suggestedStop = low;
  fibLevels.forEach(function(l) {
    var price = high + diff * (l.mult - 1);
    if (l.mult <= 1) price = low + diff * l.mult;
    else price = high + diff * (l.mult - 1);
    var active = current >= price ? 'var(--green)' : 'var(--text-dim)';
    html += '<div class="calc-result-item"><span class="label">' + l.name + ' Extension</span><span class="value" style="color:' + active + '">$' + price.toFixed(2) + '</span></div>';
  });
  // Determine suggested stop
  var trailRules = [
    { above: 1.618, stop: 0.618 },
    { above: 2.618, stop: 1.618 },
    { above: 3.618, stop: 2.618 },
    { above: 4.236, stop: 3.618 },
    { above: 6.618, stop: 4.236 },
    { above: 9.618, stop: 6.618 }
  ];
  var stopName = 'Initial (Swing Low)';
  var stopPrice = low;
  trailRules.forEach(function(r) {
    var abovePrice = high + diff * (r.above - 1);
    var stPrice = r.stop <= 1 ? low + diff * r.stop : high + diff * (r.stop - 1);
    if (current >= abovePrice) {
      stopPrice = stPrice;
      stopName = r.stop + ' level';
    }
  });
  html += '<div class="calc-result-item" style="border-top:1px solid var(--border);padding-top:8px;margin-top:8px"><span class="label">Suggested Trailing Stop</span><span class="value" style="color:var(--yellow)">$' + stopPrice.toFixed(2) + ' (' + stopName + ')</span></div>';
  resultsEl.innerHTML = html;
}

// --- Macro Position Calculator ---
function calcMacroPosition() {
  var balance = parseFloat(document.getElementById('macro-balance').value);
  var riskPct = parseFloat(document.getElementById('macro-risk').value);
  var entry = parseFloat(document.getElementById('macro-entry').value);
  var stop = parseFloat(document.getElementById('macro-stop').value);
  var tp1 = parseFloat(document.getElementById('macro-tp1').value);
  var tp2 = parseFloat(document.getElementById('macro-tp2').value);
  var resultsEl = document.getElementById('macro-results');
  if (!resultsEl) return;
  if (isNaN(balance) || isNaN(riskPct) || isNaN(entry) || isNaN(stop)) {
    resultsEl.innerHTML = '<div class="calc-result-item"><span class="label">Error</span><span class="value" style="color:var(--red)">Please fill all required fields</span></div>';
    return;
  }
  var riskAmount = balance * (riskPct / 100);
  var stopDist = Math.abs(entry - stop);
  var stopPct = (stopDist / entry) * 100;
  var positionSize = riskAmount / stopDist;
  var positionValue = positionSize * entry;
  var portfolioPct = (positionValue / balance) * 100;
  var html =
    '<div class="calc-result-item"><span class="label">Risk Amount</span><span class="value" style="color:var(--yellow)">$' + riskAmount.toFixed(2) + '</span></div>' +
    '<div class="calc-result-item"><span class="label">Stop Distance</span><span class="value" style="color:var(--red)">' + stopPct.toFixed(2) + '%</span></div>' +
    '<div class="calc-result-item"><span class="label">Position Size</span><span class="value" style="color:var(--green)">' + positionSize.toFixed(6) + ' units</span></div>' +
    '<div class="calc-result-item"><span class="label">Position Value</span><span class="value" style="color:var(--cyan)">$' + positionValue.toFixed(2) + '</span></div>' +
    '<div class="calc-result-item"><span class="label">Portfolio Allocation</span><span class="value" style="color:' + (portfolioPct > 20 ? 'var(--red)' : 'var(--green)') + '">' + portfolioPct.toFixed(1) + '%</span></div>';
  if (!isNaN(tp1) && tp1 > 0) {
    var rr1 = Math.abs(tp1 - entry) / stopDist;
    var profit1 = positionSize * Math.abs(tp1 - entry) * 0.25;
    html += '<div class="calc-result-item"><span class="label">TP1 R:R (25% exit)</span><span class="value" style="color:var(--green)">' + rr1.toFixed(2) + ':1 (+$' + profit1.toFixed(2) + ')</span></div>';
  }
  if (!isNaN(tp2) && tp2 > 0) {
    var rr2 = Math.abs(tp2 - entry) / stopDist;
    var profit2 = positionSize * Math.abs(tp2 - entry) * 0.50;
    html += '<div class="calc-result-item"><span class="label">TP2 R:R (50% exit)</span><span class="value" style="color:var(--green)">' + rr2.toFixed(2) + ':1 (+$' + profit2.toFixed(2) + ')</span></div>';
  }
  resultsEl.innerHTML = html;
}

// ============================================
// Trendline Breakout Strategy
// ============================================
function renderStratTrendline() {
  return `
    <div class="course-page-header">
      <h1>Trendline Breakout Strategy</h1>
      <p class="subtitle">Master trendline breakout trading with Bitcoin's 4-year cycle analysis</p>
    </div>

    <div class="metric-row">
      <div class="metric-card">
        <div class="metric-val" style="color: var(--green)">78%</div>
        <div class="metric-label">Win Rate (Backtested)</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--cyan)">3.2:1</div>
        <div class="metric-label">Risk/Reward</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--yellow)">Weekly</div>
        <div class="metric-label">Primary Timeframe</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--purple)">4-6</div>
        <div class="metric-label">Trades per Month</div>
      </div>
    </div>

    <div class="video-card" style="cursor:pointer; text-align:center; padding: 32px;">
      <div class="play-icon">&#9654;</div>
      <h3>Watch Complete Strategy Breakdown</h3>
      <p style="color: var(--text-dim)">Full masterclass walkthrough of the Trendline Breakout Strategy</p>
      <span style="color: var(--muted)">Duration: 15:32</span>
    </div>

    <h2>Strategy Overview</h2>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-icon" style="color: var(--cyan)">&#9585;</div>
        <div class="card-title">Market Structure Focus</div>
        <div class="card-desc">Identify key trendlines on BTC logarithmic scale. Focus on major structural levels that have been tested multiple times across the 4-year cycle.</div>
      </div>
      <div class="course-card">
        <div class="card-icon" style="color: var(--green)">&#128200;</div>
        <div class="card-title">Multi-Indicator Confirmation</div>
        <div class="card-desc">Combine Stochastic RSI, RSI, and MACD for triple confirmation. Each indicator must align before entry to filter out false breakouts.</div>
      </div>
      <div class="course-card">
        <div class="card-icon" style="color: var(--yellow)">&#9889;</div>
        <div class="card-title">Momentum-Based Execution</div>
        <div class="card-desc">Enter only on confirmed breakouts with strong volume. Momentum must be present to validate the trendline break and sustain the move.</div>
      </div>
      <div class="course-card">
        <div class="card-icon" style="color: var(--red)">&#128737;</div>
        <div class="card-title">Risk Management</div>
        <div class="card-desc">Strict stop loss placement and position sizing based on account risk percentage. Never risk more than 2% per trade.</div>
      </div>
    </div>

    <h2>Breakout Patterns</h2>
    <div class="course-grid">
      <div class="course-card" style="border-left: 3px solid var(--green)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <div class="card-title" style="color: var(--green)">Bullish Breakout</div>
          <span style="background:var(--green);color:var(--bg);padding:2px 10px;border-radius:4px;font-weight:bold;font-size:0.85em">BUY</span>
        </div>
        <div class="card-desc">Price breaks above a bearish (descending) trendline with significant volume increase. The candle must close above the trendline to confirm the breakout. Look for volume 2-3x the average to validate the move.</div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--red)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <div class="card-title" style="color: var(--red)">Bearish Breakout</div>
          <span style="background:var(--red);color:var(--bg);padding:2px 10px;border-radius:4px;font-weight:bold;font-size:0.85em">SELL</span>
        </div>
        <div class="card-desc">Price breaks below a bullish (ascending) trendline with significant volume increase. The candle must close below the trendline to confirm the breakdown. Volume should spike on the break to confirm seller conviction.</div>
      </div>
    </div>

    <div class="card" style="padding: 20px; margin-bottom: 20px;">
      <h3 style="color: var(--cyan); margin-bottom: 12px;">Key Principles</h3>
      <div class="course-grid" style="margin-bottom: 0;">
        <div class="course-card">
          <div class="card-title">Volume Confirmation</div>
          <div class="card-desc">Breakout candle must show 2-3x average volume. Low volume breakouts are likely to fail and reverse.</div>
        </div>
        <div class="course-card">
          <div class="card-title">Wait for Candle Close</div>
          <div class="card-desc">Never enter on a wick through the trendline. Wait for the candle to fully close beyond the level.</div>
        </div>
        <div class="course-card">
          <div class="card-title">Retest Opportunity</div>
          <div class="card-desc">After breakout, price often retests the broken trendline. This retest provides a second, often safer entry point.</div>
        </div>
        <div class="course-card">
          <div class="card-title">False Breakout Avoidance</div>
          <div class="card-desc">Use indicator confirmation to filter false breakouts. If RSI and Stoch RSI do not confirm, stay out of the trade.</div>
        </div>
      </div>
    </div>

    <h2>Professional Setup Checklist</h2>
    <div class="course-grid">
      <div class="course-card" style="border-left: 3px solid var(--green)">
        <div class="card-title" style="color: var(--green)">Part I &mdash; Trendline Breakout</div>
        <div class="checklist">
          <div class="checklist-item"><span class="checklist-box">&#10003;</span><div>Candle breaks and closes beyond the trendline</div></div>
          <div class="checklist-item"><span class="checklist-box">&#10003;</span><div>Volume spike of at least 2x average</div></div>
          <div class="checklist-item"><span class="checklist-box">&#10003;</span><div>No immediate rejection or long wick back inside</div></div>
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--cyan)">
        <div class="card-title" style="color: var(--cyan)">Part II &mdash; Stochastic RSI Confirmation</div>
        <div class="checklist">
          <div class="checklist-item"><span class="checklist-box">&#10003;</span><div>K line crosses above D line on the daily</div></div>
          <div class="checklist-item"><span class="checklist-box">&#10003;</span><div>Crossover occurs in oversold zone (&lt;20)</div></div>
          <div class="checklist-item"><span class="checklist-box">&#10003;</span><div>Strong momentum shown by steep upward angle</div></div>
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--yellow)">
        <div class="card-title" style="color: var(--yellow)">Part III &mdash; RSI Momentum</div>
        <div class="checklist">
          <div class="checklist-item"><span class="checklist-box">&#10003;</span><div>RSI breaks above 50 with conviction</div></div>
          <div class="checklist-item"><span class="checklist-box">&#10003;</span><div>No bearish divergence present</div></div>
          <div class="checklist-item"><span class="checklist-box">&#10003;</span><div>Strong upward slope on the RSI line</div></div>
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--purple)">
        <div class="card-title" style="color: var(--purple)">Part IV &mdash; MACD Confirmation (Optional)</div>
        <div class="checklist">
          <div class="checklist-item"><span class="checklist-box">&#10003;</span><div>MACD line crosses above the signal line</div></div>
          <div class="checklist-item"><span class="checklist-box">&#10003;</span><div>Histogram turning green / positive</div></div>
          <div class="checklist-item"><span class="checklist-box">&#10003;</span><div>Moving toward or above the zero line</div></div>
        </div>
      </div>
    </div>

    <div class="info-box tip">
      <p><strong>Note:</strong> Parts I, II, and III must all align before entering a trade. Part IV (MACD) adds extra confirmation but is not strictly required. When all four parts align, it represents the highest probability setup.</p>
    </div>

    <h2>Risk Management Framework</h2>
    <div class="course-grid">
      <div class="course-card" style="border-left: 3px solid var(--red)">
        <div class="card-icon" style="color: var(--red)">&#128721;</div>
        <div class="card-title">Stop Loss Placement</div>
        <div class="card-desc">
          <ul style="margin:8px 0;padding-left:18px;color:var(--text-dim)">
            <li>Place stop 2-3% below the broken trendline</li>
            <li>Account for current volatility (ATR-based adjustment)</li>
            <li>Maximum 2% account risk per trade</li>
          </ul>
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--green)">
        <div class="card-icon" style="color: var(--green)">&#127919;</div>
        <div class="card-title">Take Profit Targets</div>
        <div class="card-desc">
          <ul style="margin:8px 0;padding-left:18px;color:var(--text-dim)">
            <li>First target: 1.618 Fibonacci extension</li>
            <li>Second target: previous swing high/low</li>
            <li>Trail stops on remaining runners</li>
          </ul>
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--yellow)">
        <div class="card-icon" style="color: var(--yellow)">&#9878;</div>
        <div class="card-title">Position Sizing</div>
        <div class="card-desc">
          <ul style="margin:8px 0;padding-left:18px;color:var(--text-dim)">
            <li>Calculate position size based on stop distance</li>
            <li>Risk 1-2% of account maximum per trade</li>
            <li>Reduce size in periods of high volatility</li>
          </ul>
        </div>
      </div>
    </div>

    <h2>Fibonacci Calculator</h2>
    <div class="calc-container">
      <div class="calc-row">
        <div class="calc-field">
          <label>Swing Low Price</label>
          <input type="number" id="fib-swing-low" placeholder="e.g. 25000" step="any" />
        </div>
        <div class="calc-field">
          <label>Swing High Price</label>
          <input type="number" id="fib-swing-high" placeholder="e.g. 45000" step="any" />
        </div>
      </div>
      <button class="calc-btn" onclick="calcFibLevels()">Calculate Fibonacci Levels</button>
      <div class="calc-results" id="fib-results"></div>
    </div>

    <h2>Psychology Tips</h2>
    <div class="card" style="padding: 20px;">
      <div class="course-grid" style="margin-bottom:0">
        <div class="course-card">
          <div class="card-title" style="color: var(--cyan)">Wait for All Confirmations</div>
          <div class="card-desc">Patience is your edge. Never enter a trade until all three required parts of the checklist are satisfied. Half-confirmed setups lead to losses.</div>
        </div>
        <div class="course-card">
          <div class="card-title" style="color: var(--yellow)">Don't Chase Moves</div>
          <div class="card-desc">If price has already moved 5% or more beyond the breakout point, do not chase. Wait for a pullback retest or move on to the next opportunity.</div>
        </div>
        <div class="course-card">
          <div class="card-title" style="color: var(--red)">Accept Small Losses</div>
          <div class="card-desc">Losses are the cost of doing business. A 2% stop loss is a planned expense, not a failure. Protect capital by cutting losers quickly.</div>
        </div>
        <div class="course-card">
          <div class="card-title" style="color: var(--green)">Trust Your System</div>
          <div class="card-desc">Once your checklist is confirmed and you enter, trust the system. Do not second-guess mid-trade. Let the stop loss or take profit do its job.</div>
        </div>
      </div>
    </div>

    <div class="info-box warning">
      <p><strong>Disclaimer:</strong> This strategy is provided for educational purposes only. Past performance does not guarantee future results. Trading cryptocurrency involves substantial risk of loss. Never risk more than you can afford to lose. Always practice with paper trading before using real capital.</p>
    </div>

    <div class="step-nav">
      <button class="step-nav-btn" onclick="navigateCourse('dashboard')">&larr; Back to Dashboard</button>
    </div>
  `;
}

// ============================================
// MFI + MACD Multi-Timeframe Strategy
// ============================================
function renderStratMfi() {
  return `
    <div class="course-page-header">
      <h1>MFI + MACD Multi-Timeframe Strategy</h1>
      <p class="subtitle">Master momentum trading with MFI and MACD convergence across multiple timeframes</p>
    </div>

    <div class="metric-row">
      <div class="metric-card">
        <div class="metric-val" style="color: var(--green)">85%</div>
        <div class="metric-label">Win Rate</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--cyan)">3:1</div>
        <div class="metric-label">Risk/Reward</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--yellow)">16h/6h/1h</div>
        <div class="metric-label">Timeframes</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--purple)">Advanced</div>
        <div class="metric-label">Difficulty</div>
      </div>
    </div>

    <div class="video-card" style="cursor:pointer; text-align:center; padding: 32px;">
      <div class="play-icon">&#9654;</div>
      <h3>MFI + MACD Strategy Deep Dive</h3>
      <p style="color: var(--text-dim)">Complete masterclass on multi-timeframe momentum trading</p>
      <span style="color: var(--muted)">Duration: 45 min</span>
    </div>

    <h2>Strategy Overview</h2>
    <div class="course-grid">
      <div class="course-card" style="border-left: 3px solid var(--cyan)">
        <div class="card-icon" style="color: var(--cyan)">&#128200;</div>
        <div class="card-title">Primary Indicators</div>
        <div class="card-desc">
          <strong>MFI (Money Flow Index)</strong> &mdash; volume-weighted RSI that measures buying and selling pressure.<br/>
          <strong>MACD Histogram</strong> &mdash; momentum direction and strength above/below zero line.<br/>
          <strong>Stochastic RSI</strong> &mdash; VuManChu dot proxy for precise momentum entry signals.
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--yellow)">
        <div class="card-icon" style="color: var(--yellow)">&#9202;</div>
        <div class="card-title">Timeframe Structure</div>
        <div class="card-desc">
          <strong>16h</strong> &mdash; Primary trend direction and momentum bias.<br/>
          <strong>6h</strong> &mdash; Secondary momentum confirmation layer.<br/>
          <strong>1h</strong> &mdash; Precise entry timing with VuManChu dot signal.
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--green)">
        <div class="card-icon" style="color: var(--green)">&#9989;</div>
        <div class="card-title">Entry Conditions</div>
        <div class="card-desc">
          HTF structure must be bullish. 16h and 6h MFI must be green (above 50) with MACD histogram above zero. Enter when 1h MFI turns green and VuManChu dot confirms (Stoch RSI bull cross).
        </div>
      </div>
    </div>

    <h2>Setup Checklist</h2>
    <div class="card" style="padding: 20px; margin-bottom: 20px;">
      <h3 style="color: var(--cyan); margin-bottom: 16px;">TradingView Configuration</h3>
      <div class="course-grid" style="margin-bottom: 16px;">
        <div class="course-card">
          <div class="card-title">Chart Layouts</div>
          <div class="card-desc">Set up 3 chart layouts side by side: 16h, 6h, and 1h timeframes. This gives you simultaneous visibility across all confirmation layers.</div>
        </div>
        <div class="course-card">
          <div class="card-title">Indicators to Add</div>
          <div class="card-desc">
            <ul style="margin:4px 0;padding-left:18px;color:var(--text-dim)">
              <li>MFI (period: 14)</li>
              <li>MACD (12, 26, 9)</li>
              <li>Stochastic RSI (14, 14, 3, 3)</li>
            </ul>
          </div>
        </div>
      </div>

      <h3 style="color: var(--yellow); margin-bottom: 16px;">Indicator Configuration</h3>
      <div class="course-grid" style="margin-bottom: 0;">
        <div class="course-card">
          <div class="card-title">MFI Config</div>
          <div class="card-desc">
            <ul style="margin:4px 0;padding-left:18px;color:var(--text-dim)">
              <li>Period: 14</li>
              <li>Bullish: above 50 (green)</li>
              <li>Overbought: above 80</li>
              <li>Oversold: below 20</li>
              <li>Green = above 50 midline</li>
            </ul>
          </div>
        </div>
        <div class="course-card">
          <div class="card-title">MACD Config</div>
          <div class="card-desc">
            <ul style="margin:4px 0;padding-left:18px;color:var(--text-dim)">
              <li>Fast Length: 12</li>
              <li>Slow Length: 26</li>
              <li>Signal Smoothing: 9</li>
              <li>Focus on histogram above/below zero</li>
            </ul>
          </div>
        </div>
      </div>
    </div>

    <h2>Signal Checklist &mdash; Full 9-Point Confirmation</h2>
    <div class="card" style="padding: 20px; margin-bottom: 20px;">
      <div class="checklist">
        <div class="checklist-item"><span class="checklist-box" style="background:var(--purple);color:var(--bg)">1</span><div><strong>Monthly structure bullish</strong> &mdash; confirm the macro trend direction</div></div>
        <div class="checklist-item"><span class="checklist-box" style="background:var(--purple);color:var(--bg)">2</span><div><strong>Weekly structure bullish</strong> &mdash; intermediate trend aligns with monthly</div></div>
        <div class="checklist-item"><span class="checklist-box" style="background:var(--purple);color:var(--bg)">3</span><div><strong>Daily structure bullish</strong> &mdash; short-term trend supports the setup</div></div>
        <div class="checklist-item"><span class="checklist-box" style="background:var(--cyan);color:var(--bg)">4</span><div><strong>16h MFI green</strong> &mdash; MFI above 50 on the 16-hour chart</div></div>
        <div class="checklist-item"><span class="checklist-box" style="background:var(--cyan);color:var(--bg)">5</span><div><strong>16h MACD histogram > 0</strong> &mdash; positive momentum on 16h</div></div>
        <div class="checklist-item"><span class="checklist-box" style="background:var(--yellow);color:var(--bg)">6</span><div><strong>6h MFI green</strong> &mdash; MFI above 50 on the 6-hour chart</div></div>
        <div class="checklist-item"><span class="checklist-box" style="background:var(--yellow);color:var(--bg)">7</span><div><strong>6h MACD histogram > 0</strong> &mdash; positive momentum on 6h</div></div>
        <div class="checklist-item"><span class="checklist-box" style="background:var(--green);color:var(--bg)">8</span><div><strong>1h MFI turns green</strong> &mdash; MFI crosses above 50 on 1-hour chart</div></div>
        <div class="checklist-item"><span class="checklist-box" style="background:var(--green);color:var(--bg)">9</span><div><strong>1h VuManChu dot closes</strong> &mdash; Stoch RSI bullish cross from low region confirms entry</div></div>
      </div>
    </div>

    <div class="info-box tip">
      <p><strong>Pro Tips:</strong> For additional confluence, look for the 20 EMA above the 50 EMA with price holding above both. Both EMAs should be above the 200 EMA for the strongest setups. On pullbacks, watch for price to recross above the 20 EMA as a re-entry signal.</p>
    </div>

    <h2>VuManChu Dot Explanation</h2>
    <div class="card" style="padding: 20px; margin-bottom: 20px;">
      <h3 style="color: var(--green); margin-bottom: 12px;">Understanding the Entry Signal</h3>
      <div class="course-grid" style="margin-bottom: 0;">
        <div class="course-card">
          <div class="card-title">What Is the Dot?</div>
          <div class="card-desc">The VuManChu dot appears when multiple momentum conditions align simultaneously. It represents a high-probability momentum entry point. <strong>Always wait for the candle to CLOSE</strong> before acting on the dot.</div>
        </div>
        <div class="course-card">
          <div class="card-title">Stoch RSI Proxy</div>
          <div class="card-desc">If you do not have the VuManChu indicator, use Stochastic RSI as a proxy. Look for the K line crossing above the D line from the lower region (below 20-30) as the equivalent signal.</div>
        </div>
        <div class="course-card">
          <div class="card-title">Entry Rule</div>
          <div class="card-desc">After the dot closes (candle completes), enter on the <strong>next candle open</strong>. No early entries allowed. The dot must be fully confirmed with a closed candle.</div>
        </div>
        <div class="course-card">
          <div class="card-title">HTF Requirement</div>
          <div class="card-desc">A 1h VuManChu dot alone is not enough. You <strong>must</strong> have 16h and 6h confirmation (MFI green + MACD positive) before acting on any 1h entry signal.</div>
        </div>
      </div>
    </div>

    <h2>Trade Management: Trend-Based Fib Trailing</h2>
    <div class="card" style="padding: 20px; margin-bottom: 20px;">
      <h3 style="color: var(--yellow); margin-bottom: 12px;">Trailing Stop System</h3>
      <div class="course-grid" style="margin-bottom: 16px;">
        <div class="course-card">
          <div class="card-title">Initial Stop</div>
          <div class="card-desc">Place initial stop loss at the <strong>previous swing low</strong>. This gives the trade room to breathe while protecting against a full reversal.</div>
        </div>
        <div class="course-card">
          <div class="card-title">Fib Extension Levels</div>
          <div class="card-desc">Apply trend-based Fibonacci extension from swing low to swing high. Levels range from 0.618 all the way up to 9.618 for extended moves.</div>
        </div>
      </div>
      <h3 style="color: var(--cyan); margin-bottom: 12px;">Trailing Rules</h3>
      <div class="checklist">
        <div class="checklist-item"><span class="checklist-box" style="background:var(--green);color:var(--bg)">&#8593;</span><div>Price above <strong>1.618</strong> &rarr; Move stop to <strong>0.618</strong> level</div></div>
        <div class="checklist-item"><span class="checklist-box" style="background:var(--green);color:var(--bg)">&#8593;</span><div>Price above <strong>2.618</strong> &rarr; Move stop to <strong>1.618</strong> level</div></div>
        <div class="checklist-item"><span class="checklist-box" style="background:var(--green);color:var(--bg)">&#8593;</span><div>Price above <strong>3.618</strong> &rarr; Move stop to <strong>2.618</strong> level</div></div>
        <div class="checklist-item"><span class="checklist-box" style="background:var(--green);color:var(--bg)">&#8593;</span><div>Price above <strong>4.236</strong> &rarr; Move stop to <strong>3.618</strong> level</div></div>
        <div class="checklist-item"><span class="checklist-box" style="background:var(--green);color:var(--bg)">&#8593;</span><div>Continue trailing at each subsequent Fibonacci extension level</div></div>
      </div>
    </div>

    <h2>Position Size Calculator</h2>
    <div class="calc-container">
      <div class="calc-row">
        <div class="calc-field">
          <label>Account Balance ($)</label>
          <input type="number" id="mfi-balance" placeholder="e.g. 10000" step="any" />
        </div>
        <div class="calc-field">
          <label>Risk %</label>
          <input type="number" id="mfi-risk" placeholder="e.g. 2" step="any" />
        </div>
      </div>
      <div class="calc-row">
        <div class="calc-field">
          <label>Entry Price ($)</label>
          <input type="number" id="mfi-entry" placeholder="e.g. 65000" step="any" />
        </div>
        <div class="calc-field">
          <label>Stop Loss ($)</label>
          <input type="number" id="mfi-stop" placeholder="e.g. 63000" step="any" />
        </div>
      </div>
      <button class="calc-btn" onclick="calcMfiPosition()">Calculate Position Size</button>
      <div class="calc-results" id="mfi-results"></div>
    </div>

    <h2>Fib Trailing Calculator</h2>
    <div class="calc-container">
      <div class="calc-row">
        <div class="calc-field">
          <label>Swing Low ($)</label>
          <input type="number" id="fib-trail-low" placeholder="e.g. 60000" step="any" />
        </div>
        <div class="calc-field">
          <label>Swing High ($)</label>
          <input type="number" id="fib-trail-high" placeholder="e.g. 65000" step="any" />
        </div>
      </div>
      <div class="calc-row">
        <div class="calc-field">
          <label>Current Price ($)</label>
          <input type="number" id="fib-trail-current" placeholder="e.g. 72000" step="any" />
        </div>
        <div class="calc-field">
          <label>Last Closed Level</label>
          <select id="fib-trail-level">
            <option value="0">Initial (Swing Low)</option>
            <option value="0.618">0.618</option>
            <option value="1.0">1.000</option>
            <option value="1.618">1.618</option>
            <option value="2.618">2.618</option>
            <option value="3.618">3.618</option>
            <option value="4.236">4.236</option>
          </select>
        </div>
      </div>
      <button class="calc-btn" onclick="calcFibTrail()">Calculate Trailing Levels</button>
      <div class="calc-results" id="fib-trail-results"></div>
    </div>

    <h2>Psychology</h2>
    <div class="course-grid">
      <div class="course-card" style="border-left: 3px solid var(--cyan)">
        <div class="card-icon" style="color: var(--cyan)">&#128270;</div>
        <div class="card-title">Signal Discipline</div>
        <div class="card-desc">Wait for ALL 9 confirmation points before entering. Skipping even one reduces win rate significantly. The edge comes from confluence, not speed.</div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--yellow)">
        <div class="card-icon" style="color: var(--yellow)">&#129504;</div>
        <div class="card-title">Emotional Control</div>
        <div class="card-desc">Accept losses as part of the process. After 3 consecutive losses, take a mandatory break. Review your checklist adherence before resuming trading.</div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--green)">
        <div class="card-icon" style="color: var(--green)">&#128202;</div>
        <div class="card-title">Performance Tracking</div>
        <div class="card-desc">Track your win rate per setup type. Review your trading journal weekly. Identify which checklist points you most frequently skip and address the pattern.</div>
      </div>
    </div>

    <div class="info-box warning">
      <p><strong>Disclaimer:</strong> This strategy is provided for educational purposes only. Past performance does not guarantee future results. Trading cryptocurrency involves substantial risk of loss. Never risk more than you can afford to lose. Always practice with paper trading before using real capital.</p>
    </div>

    <div class="step-nav">
      <button class="step-nav-btn" onclick="navigateCourse('dashboard')">&larr; Back to Dashboard</button>
    </div>
  `;
}

// ============================================
// 2-Week Macro Trading Strategy
// ============================================
function renderStratMacro() {
  return `
    <div class="course-page-header">
      <h1>2-Week Macro Trading Strategy</h1>
      <p class="subtitle">Master institutional-level macro analysis with 2-week timeframe cycles</p>
    </div>

    <div class="metric-row">
      <div class="metric-card">
        <div class="metric-val" style="color: var(--green)">78%</div>
        <div class="metric-label">Win Rate</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--cyan)">5:1</div>
        <div class="metric-label">Risk/Reward</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--yellow)">2-Week</div>
        <div class="metric-label">Primary Timeframe</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color: var(--purple)">Institutional</div>
        <div class="metric-label">Approach</div>
      </div>
    </div>

    <div class="video-card" style="cursor:pointer; text-align:center; padding: 32px;">
      <div class="play-icon">&#9654;</div>
      <h3>2-Week Macro Strategy Masterclass</h3>
      <p style="color: var(--text-dim)">Complete institutional-level macro trading breakdown</p>
      <span style="color: var(--muted)">Full Masterclass</span>
    </div>

    <h2>Strategy Overview</h2>
    <div class="course-grid">
      <div class="course-card" style="border-left: 3px solid var(--purple)">
        <div class="card-icon" style="color: var(--purple)">&#127970;</div>
        <div class="card-title">Core Philosophy</div>
        <div class="card-desc">Think like an institution. Focus on major trends with high conviction. Higher timeframes provide stronger signals with less noise. Size positions for macro-scale moves that play out over weeks or months.</div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--cyan)">
        <div class="card-icon" style="color: var(--cyan)">&#9202;</div>
        <div class="card-title">Timeframe Hierarchy</div>
        <div class="card-desc">
          <strong>Monthly</strong> &mdash; overall market cycle direction.<br/>
          <strong>2-Week</strong> &mdash; primary analysis and bias.<br/>
          <strong>Weekly</strong> &mdash; trend confirmation.<br/>
          <strong>Daily</strong> &mdash; entry refinement and precise timing.
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--green)">
        <div class="card-icon" style="color: var(--green)">&#128176;</div>
        <div class="card-title">Position Characteristics</div>
        <div class="card-desc">
          Larger position sizes (3-5% account risk). Wider stop losses to accommodate macro volatility. Extended hold periods spanning weeks to months. Multiple take profit levels for scaled exits.
        </div>
      </div>
    </div>

    <h2>Timeframe Hierarchy</h2>
    <div class="card" style="text-align: center; padding: 24px; margin-bottom: 20px;">
      <p style="color: var(--text-dim); margin-bottom: 12px;">Analysis Flow: Top-Down Approach</p>
      <div style="display: flex; align-items: center; justify-content: center; gap: 12px; flex-wrap: wrap; font-size: 1.1em; font-weight: bold;">
        <div style="text-align:center">
          <div style="color: var(--purple); font-size: 1.3em;">1M</div>
          <div style="color: var(--muted); font-size: 0.7em;">Market Cycle</div>
        </div>
        <span style="color: var(--muted)">&rarr;</span>
        <div style="text-align:center">
          <div style="color: var(--blue); font-size: 1.3em;">2W</div>
          <div style="color: var(--muted); font-size: 0.7em;">Primary Analysis</div>
        </div>
        <span style="color: var(--muted)">&rarr;</span>
        <div style="text-align:center">
          <div style="color: var(--cyan); font-size: 1.3em;">1W</div>
          <div style="color: var(--muted); font-size: 0.7em;">Trend Confirmation</div>
        </div>
        <span style="color: var(--muted)">&rarr;</span>
        <div style="text-align:center">
          <div style="color: var(--green); font-size: 1.3em;">3D</div>
          <div style="color: var(--muted); font-size: 0.7em;">Structure</div>
        </div>
        <span style="color: var(--muted)">&rarr;</span>
        <div style="text-align:center">
          <div style="color: var(--yellow); font-size: 1.3em;">1D</div>
          <div style="color: var(--muted); font-size: 0.7em;">Entry Refinement</div>
        </div>
        <span style="color: var(--muted)">&rarr;</span>
        <div style="text-align:center">
          <div style="color: var(--red); font-size: 1.3em;">12H</div>
          <div style="color: var(--muted); font-size: 0.7em;">Precise Timing</div>
        </div>
      </div>
    </div>

    <h2>2-Week Candle Analysis</h2>
    <div class="card" style="padding: 20px; margin-bottom: 20px;">
      <h3 style="color: var(--cyan); margin-bottom: 16px;">Key Patterns</h3>
      <div class="course-grid" style="margin-bottom: 16px;">
        <div class="course-card">
          <div class="card-title" style="color: var(--green)">Bullish Engulfing on 2W</div>
          <div class="card-desc">Extremely powerful reversal signal. A green 2-week candle that fully engulfs the prior red candle indicates a major shift in institutional sentiment. High probability long setup.</div>
        </div>
        <div class="course-card">
          <div class="card-title" style="color: var(--yellow)">Hammer / Doji on 2W</div>
          <div class="card-desc">Long lower wick or doji at key support levels on the 2-week chart signals strong buyer interest. Wait for confirmation candle before entry.</div>
        </div>
        <div class="course-card">
          <div class="card-title" style="color: var(--cyan)">Higher Highs / Higher Lows</div>
          <div class="card-desc">Consecutive 2-week candles forming higher highs and higher lows confirm a macro uptrend. This is the most reliable directional confirmation on macro timeframes.</div>
        </div>
        <div class="course-card">
          <div class="card-title" style="color: var(--purple)">Key S/R Levels</div>
          <div class="card-desc">Support and resistance levels that have held across multiple 2-week candles are extremely significant. These levels represent true institutional interest zones.</div>
        </div>
      </div>
      <h3 style="color: var(--yellow); margin-bottom: 12px;">Volume Analysis</h3>
      <div class="info-box tip">
        <p>Volume should increase on breakouts above resistance, bounces from key support levels, and during trend continuation moves. Decreasing volume on pullbacks is healthy and suggests the trend remains intact.</p>
      </div>
    </div>

    <h2>Macro Setup Checklist</h2>
    <div class="card" style="padding: 20px; margin-bottom: 20px;">
      <div class="checklist">
        <div class="checklist-item"><span class="checklist-box" style="background:var(--purple);color:var(--bg)">1</span><div><strong>Monthly Trend</strong> &mdash; Confirm the overall direction on the 1M chart. Is the macro cycle bullish, bearish, or ranging?</div></div>
        <div class="checklist-item"><span class="checklist-box" style="background:var(--blue);color:var(--bg)">2</span><div><strong>2W Structure</strong> &mdash; Identify key support and resistance levels on the 2-week chart. Mark levels that have been tested multiple times.</div></div>
        <div class="checklist-item"><span class="checklist-box" style="background:var(--cyan);color:var(--bg)">3</span><div><strong>Weekly Confirmation</strong> &mdash; Verify that the 1W chart aligns with your 2W directional bias. Look for trend structure agreement.</div></div>
        <div class="checklist-item"><span class="checklist-box" style="background:var(--green);color:var(--bg)">4</span><div><strong>Daily Entry</strong> &mdash; Wait for a 1D or 12H signal that aligns with macro direction. Use candlestick patterns and momentum indicators for timing.</div></div>
        <div class="checklist-item"><span class="checklist-box" style="background:var(--yellow);color:var(--bg)">5</span><div><strong>Risk Management</strong> &mdash; Size position appropriately for macro timeframe. Wider stops require smaller position sizes to maintain acceptable account risk.</div></div>
      </div>
    </div>

    <h2>Market Structure Analysis</h2>
    <div class="course-grid">
      <div class="course-card" style="border-left: 3px solid var(--green)">
        <div class="card-title" style="color: var(--green)">Bullish Patterns</div>
        <div class="card-desc">
          <ul style="margin:4px 0;padding-left:18px;color:var(--text-dim)">
            <li>2W bullish engulfing at support</li>
            <li>Higher highs and higher lows on 2W</li>
            <li>Volume breakout above resistance</li>
            <li>Price reclaims key moving averages</li>
          </ul>
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--red)">
        <div class="card-title" style="color: var(--red)">Bearish Patterns</div>
        <div class="card-desc">
          <ul style="margin:4px 0;padding-left:18px;color:var(--text-dim)">
            <li>2W bearish engulfing at resistance</li>
            <li>Lower highs and lower lows on 2W</li>
            <li>Volume breakdown below support</li>
            <li>Price rejected at key moving averages</li>
          </ul>
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--yellow)">
        <div class="card-title" style="color: var(--yellow)">Reversal Signals</div>
        <div class="card-desc">
          <ul style="margin:4px 0;padding-left:18px;color:var(--text-dim)">
            <li>2W Hammer or Doji at key levels</li>
            <li>Volume spike at major support/resistance</li>
            <li>RSI divergence on 2W timeframe</li>
            <li>Market structure break (trend change)</li>
          </ul>
        </div>
      </div>
    </div>

    <h2>Risk Framework</h2>
    <div class="course-grid">
      <div class="course-card" style="border-left: 3px solid var(--cyan)">
        <div class="card-icon" style="color: var(--cyan)">&#9878;</div>
        <div class="card-title">Position Sizing</div>
        <div class="card-desc">
          <ul style="margin:4px 0;padding-left:18px;color:var(--text-dim)">
            <li>3-5% risk per macro trade</li>
            <li>Maximum 15% total portfolio exposure</li>
            <li>Scale size with conviction level</li>
          </ul>
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--red)">
        <div class="card-icon" style="color: var(--red)">&#128721;</div>
        <div class="card-title">Stop Management</div>
        <div class="card-desc">
          <ul style="margin:4px 0;padding-left:18px;color:var(--text-dim)">
            <li>Previous 2W swing as initial stop</li>
            <li>Never risk more than 15% on a single trade</li>
            <li>Move to breakeven after achieving 1:1 R:R</li>
          </ul>
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--green)">
        <div class="card-icon" style="color: var(--green)">&#127919;</div>
        <div class="card-title">Profit Taking</div>
        <div class="card-desc">
          <ul style="margin:4px 0;padding-left:18px;color:var(--text-dim)">
            <li>Scale out 25% at 2:1 R:R</li>
            <li>Scale out 50% at Fibonacci extensions</li>
            <li>Trail stop on final 25% position</li>
          </ul>
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--yellow)">
        <div class="card-icon" style="color: var(--yellow)">&#9202;</div>
        <div class="card-title">Time Management</div>
        <div class="card-desc">
          <ul style="margin:4px 0;padding-left:18px;color:var(--text-dim)">
            <li>Review positions weekly, not daily</li>
            <li>Exit if no progress after 4 weeks</li>
            <li>Reduce size before major macro events</li>
          </ul>
        </div>
      </div>
    </div>

    <h2>Macro Position Calculator</h2>
    <div class="calc-container">
      <div class="calc-row">
        <div class="calc-field">
          <label>Portfolio Balance ($)</label>
          <input type="number" id="macro-balance" placeholder="e.g. 50000" step="any" />
        </div>
        <div class="calc-field">
          <label>Risk %</label>
          <input type="number" id="macro-risk" placeholder="e.g. 3" step="any" />
        </div>
      </div>
      <div class="calc-row">
        <div class="calc-field">
          <label>Entry Price ($)</label>
          <input type="number" id="macro-entry" placeholder="e.g. 65000" step="any" />
        </div>
        <div class="calc-field">
          <label>Stop Loss ($)</label>
          <input type="number" id="macro-stop" placeholder="e.g. 58000" step="any" />
        </div>
      </div>
      <div class="calc-row">
        <div class="calc-field">
          <label>First Target ($)</label>
          <input type="number" id="macro-tp1" placeholder="e.g. 79000" step="any" />
        </div>
        <div class="calc-field">
          <label>Final Target ($)</label>
          <input type="number" id="macro-tp2" placeholder="e.g. 95000" step="any" />
        </div>
      </div>
      <button class="calc-btn" onclick="calcMacroPosition()">Calculate Macro Position</button>
      <div class="calc-results" id="macro-results"></div>
    </div>

    <h2>Setup Examples</h2>
    <div class="course-grid">
      <div class="course-card" style="border-left: 3px solid var(--green)">
        <div class="card-title" style="color: var(--green)">Bullish Macro Setup</div>
        <div class="card-desc">
          <ol style="margin:4px 0;padding-left:18px;color:var(--text-dim)">
            <li>Monthly chart in confirmed uptrend</li>
            <li>2W candle breaking above key resistance with 2x average volume</li>
            <li>Weekly chart showing higher highs and higher lows</li>
            <li>Enter on daily pullback to 50-61.8% Fibonacci retracement</li>
            <li>Targets at 1.618 / 2.618 / 4.236 Fibonacci extensions</li>
          </ol>
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--red)">
        <div class="card-title" style="color: var(--red)">Bearish Macro Setup</div>
        <div class="card-desc">
          <ol style="margin:4px 0;padding-left:18px;color:var(--text-dim)">
            <li>Monthly chart in confirmed downtrend</li>
            <li>2W candle breaking below key support with volume</li>
            <li>Weekly chart showing lower highs and lower lows</li>
            <li>Enter on daily rally to 38.2-50% Fibonacci retracement</li>
            <li>Target previous major lows and extension levels</li>
          </ol>
        </div>
      </div>
      <div class="course-card" style="border-left: 3px solid var(--yellow)">
        <div class="card-title" style="color: var(--yellow)">Accumulation Setup</div>
        <div class="card-desc">
          <ol style="margin:4px 0;padding-left:18px;color:var(--text-dim)">
            <li>Price in long-term range on 2W chart</li>
            <li>Multiple 2W tests of support level holding</li>
            <li>Decreasing volume on each retest (selling exhaustion)</li>
            <li>Scale into position on each support test</li>
            <li>Exit on confirmed range breakout to the upside</li>
          </ol>
        </div>
      </div>
    </div>

    <div class="info-box warning">
      <p><strong>Disclaimer:</strong> This strategy is provided for educational purposes only. Past performance does not guarantee future results. Trading cryptocurrency involves substantial risk of loss. Never risk more than you can afford to lose. Macro trading involves extended hold periods and wider stops — ensure you are comfortable with the capital at risk before entering any position.</p>
    </div>

    <div class="step-nav">
      <button class="step-nav-btn" onclick="navigateCourse('dashboard')">&larr; Back to Dashboard</button>
    </div>
  `;
}

// ── Bull Market, Backtesting, Resources, Alerts ──
// ============================================
// Nunu's Trading Masterclass - Part 5
// Bull Market, Backtesting, Resources, Alerts
// ============================================

function renderBullMarket() {
  return `
    <div class="course-page-header">
      <h1>Bull Market Analysis</h1>
      <p class="subtitle">Comprehensive analysis of bull market cycles, peak indicators, and the 2025 outlook</p>
    </div>

    <div class="course-grid">
      <div class="video-card" style="cursor:pointer;">
        <div class="play-icon">&#9654;</div>
        <div class="card-title">2025 Bull Run Breakdown</div>
        <div class="card-desc">Watch Bull Run Analysis</div>
      </div>
      <div class="video-card" style="cursor:pointer;">
        <div class="play-icon">&#9654;</div>
        <div class="card-title">5 Phase Bull Run Fib Retracement</div>
        <div class="card-desc">Watch 5 Phase Analysis</div>
      </div>
    </div>

    <h2>Bull Market Peak Indicators</h2>
    <div class="course-grid">
      <div class="peak-indicator">
        <div class="pi-name">Pi Cycle Top Indicator</div>
        <div class="card-desc">111-day MA crosses 350-day MA &times; 2</div>
        <div class="pi-status" style="background: var(--green); color: #000; display: inline-block; padding: 4px 12px; border-radius: 12px; font-weight: 600; margin-top: 8px;">Not Hit</div>
      </div>
      <div class="peak-indicator">
        <div class="pi-name">Stock-to-Flow Model</div>
        <div class="card-desc">Price vs predicted S2F value</div>
        <div class="pi-status" style="background: var(--green); color: #000; display: inline-block; padding: 4px 12px; border-radius: 12px; font-weight: 600; margin-top: 8px;">Below Target</div>
      </div>
      <div class="peak-indicator">
        <div class="pi-name">MVRV Z-Score</div>
        <div class="card-desc">Market cap vs realized cap</div>
        <div class="pi-status" style="background: var(--yellow); color: #000; display: inline-block; padding: 4px 12px; border-radius: 12px; font-weight: 600; margin-top: 8px;">Approaching</div>
      </div>
      <div class="peak-indicator">
        <div class="pi-name">Puell Multiple</div>
        <div class="card-desc">Daily issuance vs 365-day average</div>
        <div class="pi-status" style="background: var(--green); color: #000; display: inline-block; padding: 4px 12px; border-radius: 12px; font-weight: 600; margin-top: 8px;">Normal Range</div>
      </div>
      <div class="peak-indicator">
        <div class="pi-name">200-Week Moving Average</div>
        <div class="card-desc">Price distance from 200W MA</div>
        <div class="pi-status" style="background: var(--green); color: #000; display: inline-block; padding: 4px 12px; border-radius: 12px; font-weight: 600; margin-top: 8px;">Below Peak Zone</div>
      </div>
      <div class="peak-indicator">
        <div class="pi-name">NVT Golden Cross</div>
        <div class="card-desc">Network value to transactions</div>
        <div class="pi-status" style="background: var(--green); color: #000; display: inline-block; padding: 4px 12px; border-radius: 12px; font-weight: 600; margin-top: 8px;">Not Overvalued</div>
      </div>
    </div>

    <h3>Market Top Probability</h3>
    <div class="metric-row">
      <div class="metric-card" style="flex: 1;">
        <div class="metric-val" style="color: var(--green); font-size: 3rem;">15%</div>
        <div class="metric-label">Market Top Probability</div>
        <div style="width: 100%; background: var(--bg2); border-radius: 8px; height: 12px; margin-top: 12px; overflow: hidden;">
          <div style="width: 15%; height: 100%; background: var(--green); border-radius: 8px;"></div>
        </div>
        <div style="display: flex; justify-content: space-between; margin-top: 4px; color: var(--text-dim); font-size: 0.8rem;">
          <span>Low Risk</span>
          <span>High Risk</span>
        </div>
      </div>
    </div>

    <h2>5 Phases of a Bull Run</h2>
    <div class="phase-box">
      <div class="phase-item" style="border-left: 4px solid var(--blue);">
        <div class="phase-num" style="background: var(--blue); color: #000;">1</div>
        <div>
          <strong>Accumulation Phase</strong>
          <p style="margin: 4px 0 0; color: var(--text-dim);">Smart money accumulates, retail fearful. Key: 0.618-0.786 Fib retracement.</p>
        </div>
      </div>
      <div class="phase-item active-phase" style="border-left: 4px solid var(--cyan);">
        <div class="phase-num" style="background: var(--cyan); color: #000;">2</div>
        <div>
          <strong>Early Bull Phase <span style="background: var(--cyan); color: #000; padding: 2px 8px; border-radius: 8px; font-size: 0.75rem; margin-left: 8px;">ACTIVE</span></strong>
          <p style="margin: 4px 0 0; color: var(--text-dim);">Breaks key resistance, institutional interest. Previous cycle high becomes support.</p>
        </div>
      </div>
      <div class="phase-item" style="border-left: 4px solid var(--green);">
        <div class="phase-num" style="background: var(--green); color: #000;">3</div>
        <div>
          <strong>Main Bull Run</strong>
          <p style="margin: 4px 0 0; color: var(--text-dim);">Parabolic action, retail FOMO, media coverage. Key: 1.618-2.618 Fib extensions.</p>
        </div>
      </div>
      <div class="phase-item" style="border-left: 4px solid var(--yellow);">
        <div class="phase-num" style="background: var(--yellow); color: #000;">4</div>
        <div>
          <strong>Euphoria Phase</strong>
          <p style="margin: 4px 0 0; color: var(--text-dim);">Peak indicators flash, everyone talking. Key: 3.618-4.236 Fib.</p>
        </div>
      </div>
      <div class="phase-item" style="border-left: 4px solid var(--red);">
        <div class="phase-num" style="background: var(--red); color: #000;">5</div>
        <div>
          <strong>Distribution / Top</strong>
          <p style="margin: 4px 0 0; color: var(--text-dim);">Smart money distributes. Monitor all peak indicators.</p>
        </div>
      </div>
    </div>

    <div class="course-grid">
      <div class="card">
        <h3>Key Fibonacci Levels</h3>
        <div class="metric-row" style="flex-direction: column; gap: 8px;">
          <div style="display: flex; justify-content: space-between; padding: 8px 12px; background: var(--bg2); border-radius: 8px;">
            <span style="color: var(--cyan); font-weight: 600;">0.618 (Golden Pocket)</span>
            <span style="color: var(--text-dim);">Strong Support</span>
          </div>
          <div style="display: flex; justify-content: space-between; padding: 8px 12px; background: var(--bg2); border-radius: 8px;">
            <span style="color: var(--green); font-weight: 600;">1.618 (First Extension)</span>
            <span style="color: var(--text-dim);">Take Profits</span>
          </div>
          <div style="display: flex; justify-content: space-between; padding: 8px 12px; background: var(--bg2); border-radius: 8px;">
            <span style="color: var(--yellow); font-weight: 600;">2.618 (Second Extension)</span>
            <span style="color: var(--text-dim);">Major Resistance</span>
          </div>
          <div style="display: flex; justify-content: space-between; padding: 8px 12px; background: var(--bg2); border-radius: 8px;">
            <span style="color: var(--red); font-weight: 600;">3.618+ (Peak Zone)</span>
            <span style="color: var(--text-dim);">Distribution Zone</span>
          </div>
        </div>
      </div>
      <div class="card">
        <h3>Trading Strategy by Phase</h3>
        <div style="display: flex; flex-direction: column; gap: 8px;">
          <div style="display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--bg2); border-radius: 8px;">
            <span style="color: var(--blue); font-weight: 700; min-width: 80px;">Phase 1-2</span>
            <span style="color: var(--text-dim);">Accumulate on dips to key support</span>
          </div>
          <div style="display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--bg2); border-radius: 8px;">
            <span style="color: var(--green); font-weight: 700; min-width: 80px;">Phase 3</span>
            <span style="color: var(--text-dim);">Hold and ride, add on pullbacks</span>
          </div>
          <div style="display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--bg2); border-radius: 8px;">
            <span style="color: var(--yellow); font-weight: 700; min-width: 80px;">Phase 4</span>
            <span style="color: var(--text-dim);">Begin systematic profit-taking</span>
          </div>
          <div style="display: flex; align-items: center; gap: 10px; padding: 8px 12px; background: var(--bg2); border-radius: 8px;">
            <span style="color: var(--red); font-weight: 700; min-width: 80px;">Phase 5</span>
            <span style="color: var(--text-dim);">Complete distribution, prepare for bear</span>
          </div>
        </div>
      </div>
    </div>

    <h2>Current Market Assessment</h2>
    <div class="course-grid">
      <div class="card">
        <h3>Phase Analysis</h3>
        <div class="metric-val" style="color: var(--cyan); font-size: 1.4rem; margin-bottom: 12px;">Phase 2 (Early Bull)</div>
        <div style="display: flex; flex-direction: column; gap: 8px;">
          <div style="display: flex; align-items: center; gap: 8px; color: var(--green);">
            <span style="font-size: 1.1rem;">&#10003;</span> Broke above previous cycle high
          </div>
          <div style="display: flex; align-items: center; gap: 8px; color: var(--green);">
            <span style="font-size: 1.1rem;">&#10003;</span> Institutional adoption increasing
          </div>
          <div style="display: flex; align-items: center; gap: 8px; color: var(--text-dim);">
            <span style="font-size: 1.1rem;">&#9711;</span> Retail FOMO not peaked
          </div>
          <div style="display: flex; align-items: center; gap: 8px; color: var(--text-dim);">
            <span style="font-size: 1.1rem;">&#9711;</span> Peak indicators far from warning
          </div>
        </div>
      </div>
      <div class="card">
        <h3>Key Levels</h3>
        <div style="display: flex; flex-direction: column; gap: 10px;">
          <div style="padding: 10px 14px; background: var(--bg2); border-radius: 8px; border-left: 3px solid var(--yellow);">
            <div style="color: var(--yellow); font-weight: 600;">Next Resistance</div>
            <div style="color: var(--text-dim);">$85,000 - $90,000 (1.618 Fib)</div>
          </div>
          <div style="padding: 10px 14px; background: var(--bg2); border-radius: 8px; border-left: 3px solid var(--green);">
            <div style="color: var(--green); font-weight: 600;">Support Zone</div>
            <div style="color: var(--text-dim);">$55,000 - $60,000 (0.618 + previous ATH)</div>
          </div>
          <div style="padding: 10px 14px; background: var(--bg2); border-radius: 8px; border-left: 3px solid var(--cyan);">
            <div style="color: var(--cyan); font-weight: 600;">Cycle Target</div>
            <div style="color: var(--text-dim);">$120,000 - $150,000 (2.618-3.618 Fib)</div>
          </div>
        </div>
      </div>
    </div>

    <div class="step-nav">
      <button class="step-nav-btn" onclick="navigateCourse('dashboard')">&larr; Back to Dashboard</button>
    </div>
  `;
}

function renderBacktesting() {
  return `
    <div class="course-page-header">
      <h1>Strategy Backtesting Lab</h1>
      <p class="subtitle">Comprehensive backtesting tools and methodologies</p>
    </div>

    <h2>Why Backtest?</h2>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-icon">&#9989;</div>
        <div class="card-title">Validate Performance</div>
        <div class="card-desc">Prove your strategy works before risking real capital</div>
      </div>
      <div class="course-card">
        <div class="card-icon">&#128737;</div>
        <div class="card-title">Risk Assessment</div>
        <div class="card-desc">Understand worst-case drawdowns and risk exposure</div>
      </div>
      <div class="course-card">
        <div class="card-icon">&#128170;</div>
        <div class="card-title">Build Confidence</div>
        <div class="card-desc">Trade with conviction backed by data, not hope</div>
      </div>
      <div class="course-card">
        <div class="card-icon">&#9881;</div>
        <div class="card-title">Optimize Parameters</div>
        <div class="card-desc">Fine-tune indicator settings and risk parameters</div>
      </div>
    </div>

    <h2>5-Step Backtesting Process</h2>

    <div class="card" style="border-left: 4px solid var(--cyan); margin-bottom: 16px;">
      <h3><span style="background: var(--cyan); color: #000; padding: 2px 10px; border-radius: 8px; margin-right: 8px;">1</span> Setup Environment</h3>
      <div class="metric-row">
        <div class="metric-card">
          <div class="metric-val" style="color: var(--cyan);">BTC/USD</div>
          <div class="metric-label">Symbol</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color: var(--cyan);">4H</div>
          <div class="metric-label">TF Recommended</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color: var(--cyan);">6+ Months</div>
          <div class="metric-label">Min Data</div>
        </div>
      </div>
      <p style="color: var(--text-dim);">Add all indicators your strategy uses to the chart.</p>
      <div class="info-box tip">
        <p>Use different market conditions (trending, ranging, volatile) for more robust results.</p>
      </div>
    </div>

    <div class="card" style="border-left: 4px solid var(--green); margin-bottom: 16px;">
      <h3><span style="background: var(--green); color: #000; padding: 2px 10px; border-radius: 8px; margin-right: 8px;">2</span> Initialize Bar Replay</h3>
      <p style="color: var(--text-dim);">Go to earliest date, click Bar Replay, hide right portion.</p>
      <div class="info-box warning">
        <p>Never look at future price action. This introduces look-ahead bias and invalidates results.</p>
      </div>
    </div>

    <div class="card" style="border-left: 4px solid var(--yellow); margin-bottom: 16px;">
      <h3><span style="background: var(--yellow); color: #000; padding: 2px 10px; border-radius: 8px; margin-right: 8px;">3</span> Execute Strategy Rules</h3>
      <p style="color: var(--text-dim);">Step through each bar, apply exact criteria, record every setup.</p>
      <div class="checklist" style="margin-top: 12px;">
        <div class="checklist-item">
          <div class="checklist-box">&#9744;</div>
          <span>HTF trend confirmed?</span>
        </div>
        <div class="checklist-item">
          <div class="checklist-box">&#9744;</div>
          <span>Entry criteria met?</span>
        </div>
        <div class="checklist-item">
          <div class="checklist-box">&#9744;</div>
          <span>R/R acceptable?</span>
        </div>
        <div class="checklist-item">
          <div class="checklist-box">&#9744;</div>
          <span>SL identified?</span>
        </div>
        <div class="checklist-item">
          <div class="checklist-box">&#9744;</div>
          <span>TP set?</span>
        </div>
      </div>
    </div>

    <div class="card" style="border-left: 4px solid var(--purple); margin-bottom: 16px;">
      <h3><span style="background: var(--purple); color: #000; padding: 2px 10px; border-radius: 8px; margin-right: 8px;">4</span> Record Trade Details</h3>
      <div class="course-grid">
        <div class="course-card">
          <div class="card-title">Entry Details</div>
          <div class="card-desc">Date, time, price, position size</div>
        </div>
        <div class="course-card">
          <div class="card-title">Exit Details</div>
          <div class="card-desc">Date, time, price, reason for exit</div>
        </div>
        <div class="course-card">
          <div class="card-title">Risk Management</div>
          <div class="card-desc">Stop loss, take profit, R-multiple</div>
        </div>
        <div class="course-card">
          <div class="card-title">Notes</div>
          <div class="card-desc">Performance metrics, observations, lessons</div>
        </div>
      </div>
    </div>

    <div class="card" style="border-left: 4px solid var(--red); margin-bottom: 16px;">
      <h3><span style="background: var(--red); color: #000; padding: 2px 10px; border-radius: 8px; margin-right: 8px;">5</span> Calculate Metrics</h3>
      <div class="course-grid">
        <div class="metric-card">
          <div class="metric-val" style="color: var(--cyan);">Win Rate</div>
          <div class="metric-label">Wins / Total &times; 100</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color: var(--green);">Avg R-Multiple</div>
          <div class="metric-label">Average reward per unit of risk</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color: var(--yellow);">Profit Factor</div>
          <div class="metric-label">Gross Profit / Gross Loss</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color: var(--red);">Max Drawdown</div>
          <div class="metric-label">Largest peak-to-trough decline</div>
        </div>
        <div class="metric-card">
          <div class="metric-val" style="color: var(--purple);">Sharpe Ratio</div>
          <div class="metric-label">Risk-adjusted return measure</div>
        </div>
      </div>
      <div class="info-box success" style="margin-top: 12px;">
        <p><strong>Targets:</strong> Win Rate &ge; 50% &bull; Avg R &ge; 0.5 &bull; Profit Factor &ge; 1.5 &bull; Max Drawdown &lt; 15%</p>
      </div>
    </div>

    <h2>Performance Calculator</h2>
    <div class="calc-container">
      <div class="calc-row">
        <div class="calc-field">
          <label>Total Trades</label>
          <input type="number" id="bt-total-trades" placeholder="e.g. 100" />
        </div>
        <div class="calc-field">
          <label>Winning Trades</label>
          <input type="number" id="bt-winning-trades" placeholder="e.g. 58" />
        </div>
      </div>
      <div class="calc-row">
        <div class="calc-field">
          <label>Total Profit ($)</label>
          <input type="number" id="bt-total-profit" placeholder="e.g. 5000" />
        </div>
        <div class="calc-field">
          <label>Total Loss ($)</label>
          <input type="number" id="bt-total-loss" placeholder="e.g. 2500" />
        </div>
      </div>
      <button class="calc-btn" onclick="calcBacktestPerformance()">Calculate Performance</button>
      <div class="calc-results" id="bt-results" style="display:none;">
        <div class="calc-result-item">
          <span class="label">Win Rate</span>
          <span class="value" id="bt-winrate">--</span>
        </div>
        <div class="calc-result-item">
          <span class="label">Profit Factor</span>
          <span class="value" id="bt-pf">--</span>
        </div>
        <div class="calc-result-item">
          <span class="label">Net P&amp;L</span>
          <span class="value" id="bt-netpnl">--</span>
        </div>
        <div class="calc-result-item">
          <span class="label">Strategy Grade</span>
          <span class="value" id="bt-grade">--</span>
        </div>
      </div>
    </div>

    <h2>Best Practices</h2>
    <div class="course-grid">
      <div class="card" style="border-left: 4px solid var(--green);">
        <h3 style="color: var(--green);">Essential Do's</h3>
        <div class="checklist">
          <div class="checklist-item"><div class="checklist-box" style="color: var(--green);">&#10003;</div><span>Use sufficient data (100+ trades minimum)</span></div>
          <div class="checklist-item"><div class="checklist-box" style="color: var(--green);">&#10003;</div><span>Test across multiple timeframes</span></div>
          <div class="checklist-item"><div class="checklist-box" style="color: var(--green);">&#10003;</div><span>Include all trading costs and fees</span></div>
          <div class="checklist-item"><div class="checklist-box" style="color: var(--green);">&#10003;</div><span>Be honest with your results</span></div>
          <div class="checklist-item"><div class="checklist-box" style="color: var(--green);">&#10003;</div><span>Document every trade thoroughly</span></div>
          <div class="checklist-item"><div class="checklist-box" style="color: var(--green);">&#10003;</div><span>Test out-of-sample data separately</span></div>
        </div>
      </div>
      <div class="card" style="border-left: 4px solid var(--red);">
        <h3 style="color: var(--red);">Critical Don'ts</h3>
        <div class="checklist">
          <div class="checklist-item"><div class="checklist-box" style="color: var(--red);">&#10007;</div><span>No look-ahead bias — never peek at future price</span></div>
          <div class="checklist-item"><div class="checklist-box" style="color: var(--red);">&#10007;</div><span>No curve fitting — don't over-optimize to past data</span></div>
          <div class="checklist-item"><div class="checklist-box" style="color: var(--red);">&#10007;</div><span>No cherry picking — record ALL trades, not just winners</span></div>
          <div class="checklist-item"><div class="checklist-box" style="color: var(--red);">&#10007;</div><span>Don't use insufficient sample size</span></div>
          <div class="checklist-item"><div class="checklist-box" style="color: var(--red);">&#10007;</div><span>Don't ignore drawdowns — they matter most</span></div>
          <div class="checklist-item"><div class="checklist-box" style="color: var(--red);">&#10007;</div><span>Account for human error and slippage</span></div>
        </div>
      </div>
    </div>

    <h2>Ready to Start Backtesting?</h2>
    <div class="course-grid">
      <div class="course-card" onclick="navigateCourse('strat-trendline')" style="cursor:pointer;">
        <div class="card-icon">&#128200;</div>
        <div class="card-title">Trendline Strategy</div>
        <div class="card-desc">Backtest the Trendline Breakout strategy</div>
      </div>
      <div class="course-card" onclick="navigateCourse('strat-mfi')" style="cursor:pointer;">
        <div class="card-icon">&#128202;</div>
        <div class="card-title">MFI + MACD Strategy</div>
        <div class="card-desc">Backtest the MFI multi-timeframe strategy</div>
      </div>
      <div class="course-card" onclick="navigateCourse('resources')" style="cursor:pointer;">
        <div class="card-icon">&#128218;</div>
        <div class="card-title">Resources & Templates</div>
        <div class="card-desc">Download trading journal and cheatsheets</div>
      </div>
    </div>

    <div class="step-nav">
      <button class="step-nav-btn" onclick="navigateCourse('dashboard')">&larr; Back to Dashboard</button>
    </div>
  `;
}

function calcBacktestPerformance() {
  var totalTrades = parseFloat(document.getElementById('bt-total-trades').value) || 0;
  var winningTrades = parseFloat(document.getElementById('bt-winning-trades').value) || 0;
  var totalProfit = parseFloat(document.getElementById('bt-total-profit').value) || 0;
  var totalLoss = Math.abs(parseFloat(document.getElementById('bt-total-loss').value)) || 0;

  if (totalTrades <= 0) {
    alert('Please enter the total number of trades.');
    return;
  }

  var winRate = (winningTrades / totalTrades) * 100;
  var profitFactor = totalLoss > 0 ? totalProfit / totalLoss : totalProfit > 0 ? Infinity : 0;
  var netPnL = totalProfit - totalLoss;

  var grade = 'F';
  if (profitFactor >= 2 && winRate >= 60) {
    grade = 'A';
  } else if (profitFactor >= 1.5 && winRate >= 50) {
    grade = 'B';
  } else if (profitFactor >= 1.2) {
    grade = 'C';
  } else if (profitFactor >= 1) {
    grade = 'D';
  }

  var gradeColors = { A: 'var(--green)', B: 'var(--cyan)', C: 'var(--yellow)', D: 'var(--red)', F: 'var(--red)' };

  document.getElementById('bt-winrate').textContent = winRate.toFixed(1) + '%';
  document.getElementById('bt-winrate').style.color = winRate >= 50 ? 'var(--green)' : 'var(--red)';

  document.getElementById('bt-pf').textContent = profitFactor === Infinity ? 'Infinite' : profitFactor.toFixed(2);
  document.getElementById('bt-pf').style.color = profitFactor >= 1.5 ? 'var(--green)' : profitFactor >= 1 ? 'var(--yellow)' : 'var(--red)';

  document.getElementById('bt-netpnl').textContent = (netPnL >= 0 ? '+' : '') + '$' + netPnL.toFixed(2);
  document.getElementById('bt-netpnl').style.color = netPnL >= 0 ? 'var(--green)' : 'var(--red)';

  document.getElementById('bt-grade').textContent = grade;
  document.getElementById('bt-grade').style.color = gradeColors[grade];

  document.getElementById('bt-results').style.display = '';
}

function renderResources() {
  return `
    <div class="course-page-header">
      <h1>Resources</h1>
      <p class="subtitle">Professional trading resources, guides, and TradingView templates</p>
    </div>

    <h2>PDF Cheatsheets &amp; Guides</h2>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-icon">&#128196;</div>
        <div class="card-title">Terminology Cheatsheet</div>
        <div class="card-desc">Essential trading terms and definitions every trader must know</div>
      </div>
      <div class="course-card">
        <div class="card-icon">&#128295;</div>
        <div class="card-title">Indicator Settings Guide</div>
        <div class="card-desc">Optimized RSI, Stoch RSI, MACD, and MFI parameters for crypto</div>
      </div>
      <div class="course-card">
        <div class="card-icon">&#128203;</div>
        <div class="card-title">HTF Drill Worksheet</div>
        <div class="card-desc">Higher timeframe analysis practice worksheet for daily use</div>
      </div>
      <div class="course-card">
        <div class="card-icon">&#128178;</div>
        <div class="card-title">Risk Calculator Guide</div>
        <div class="card-desc">Position sizing and risk management reference guide</div>
      </div>
    </div>

    <h2>TradingView Templates</h2>

    <div class="card" style="margin-bottom: 16px;">
      <h3>Trendline Breakout Strategy</h3>
      <p style="color: var(--text-dim); margin-bottom: 12px;">Complete setup guide with all required indicators and settings.</p>
      <div style="background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 16px; font-family: monospace; font-size: 0.85rem; color: var(--cyan); overflow-x: auto; white-space: pre; line-height: 1.6;">{
  "indicators": {
    "EMA 21":  { "length": 21,  "color": "#FF6B35" },
    "EMA 50":  { "length": 50,  "color": "#4ECDC4" },
    "EMA 200": { "length": 200, "color": "#45B7D1" },
    "RSI":     { "length": 14 },
    "MACD":    { "fast": 12, "slow": 26, "signal": 9 },
    "Volume":  { "type": "standard" }
  }
}</div>
    </div>

    <div class="card" style="margin-bottom: 16px;">
      <h3>MFI + MACD Multi-Timeframe</h3>
      <p style="color: var(--text-dim); margin-bottom: 12px;">16H / 6H / 1H analysis system with alert configurations.</p>
      <h4 style="color: var(--cyan); margin-bottom: 8px;">6H MFI + MACD Setup Alert</h4>
      <div style="background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 16px; font-family: monospace; font-size: 0.85rem; color: var(--green); overflow-x: auto; white-space: pre; line-height: 1.6;">// Pine Script Alert Condition — 6H MFI + MACD
// Add to 6H chart
mfiVal = ta.mfi(hlc3, 14)
[macdLine, signalLine, hist] = ta.macd(close, 12, 26, 9)
longSetup = ta.crossover(macdLine, signalLine) and mfiVal > 50
alertcondition(longSetup, "6H MFI+MACD Long", "6H LONG setup: MACD crossed above signal, MFI > 50")</div>
      <h4 style="color: var(--cyan); margin-top: 16px; margin-bottom: 8px;">1H Stoch RSI Entry Alert</h4>
      <div style="background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 16px; font-family: monospace; font-size: 0.85rem; color: var(--green); overflow-x: auto; white-space: pre; line-height: 1.6;">// Pine Script Alert Condition — 1H Stoch RSI Entry
// Add to 1H chart
rsiVal = ta.rsi(close, 14)
[k, d] = ta.stoch(rsiVal, rsiVal, rsiVal, 14)
kSmooth = ta.sma(k, 3)
dSmooth = ta.sma(d, 3)
entrySignal = ta.crossover(kSmooth, dSmooth)
alertcondition(entrySignal, "1H StochRSI Entry", "1H ENTRY: Stoch RSI K crossed above D — confirm HTF bias")</div>
    </div>

    <div class="card" style="margin-bottom: 16px;">
      <h3>BTC Strategy Workspace</h3>
      <p style="color: var(--text-dim);">Professional 4-chart layout template for comprehensive BTC analysis. Set up TradingView with a 4-panel layout: Daily (HTF bias), 6H (setup identification), 1H (entry timing), and 15m (precision entries).</p>
    </div>

    <h2>Trade Journal Template</h2>
    <div class="card">
      <div style="background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 16px; line-height: 2;">
        <div style="display: grid; grid-template-columns: 1fr 2fr; gap: 4px 16px;">
          <span style="color: var(--cyan); font-weight: 600;">Date</span><span style="color: var(--text-dim);">YYYY-MM-DD HH:MM</span>
          <span style="color: var(--cyan); font-weight: 600;">Symbol</span><span style="color: var(--text-dim);">BTC/USD</span>
          <span style="color: var(--cyan); font-weight: 600;">Timeframe</span><span style="color: var(--text-dim);">1H / 4H / Daily</span>
          <span style="color: var(--cyan); font-weight: 600;">Setup Type</span><span style="color: var(--text-dim);">Trendline Break / MFI+MACD / etc.</span>
          <span style="color: var(--cyan); font-weight: 600;">Direction</span><span style="color: var(--text-dim);">Long / Short</span>
          <span style="color: var(--cyan); font-weight: 600;">Entry</span><span style="color: var(--text-dim);">$XX,XXX.XX</span>
          <span style="color: var(--cyan); font-weight: 600;">Stop Loss</span><span style="color: var(--text-dim);">$XX,XXX.XX</span>
          <span style="color: var(--cyan); font-weight: 600;">Take Profit</span><span style="color: var(--text-dim);">$XX,XXX.XX</span>
          <span style="color: var(--cyan); font-weight: 600;">R/R Ratio</span><span style="color: var(--text-dim);">X.X : 1</span>
          <span style="color: var(--cyan); font-weight: 600;">Position Size</span><span style="color: var(--text-dim);">X% of account</span>
          <span style="color: var(--cyan); font-weight: 600;">Setup Notes</span><span style="color: var(--text-dim);">Why did you take this trade?</span>
          <span style="color: var(--cyan); font-weight: 600;">Outcome</span><span style="color: var(--text-dim);">Win / Loss / Break-even</span>
          <span style="color: var(--cyan); font-weight: 600;">Lessons</span><span style="color: var(--text-dim);">What did you learn?</span>
        </div>
      </div>
    </div>

    <div class="step-nav">
      <button class="step-nav-btn" onclick="navigateCourse('dashboard')">&larr; Back to Dashboard</button>
    </div>
  `;
}

function renderAlerts() {
  return `
    <div class="course-page-header">
      <h1>Trading Alerts &amp; Signals</h1>
      <p class="subtitle">Professional alert setups for TradingView</p>
    </div>

    <div class="card" style="border: 2px solid var(--purple); margin-bottom: 24px; position: relative; overflow: hidden;">
      <div style="position: absolute; top: 12px; right: 12px; background: var(--purple); color: #000; padding: 2px 10px; border-radius: 8px; font-size: 0.75rem; font-weight: 700;">COMING SOON</div>
      <h3 style="color: var(--purple);">VIP Discord Community</h3>
      <div class="course-grid" style="margin: 16px 0;">
        <div class="course-card" style="border-color: var(--purple);">
          <div class="card-icon" style="color: var(--purple);">&#128227;</div>
          <div class="card-title">Live Trade Alerts</div>
          <div class="card-desc">Real-time entry and exit signals</div>
        </div>
        <div class="course-card" style="border-color: var(--purple);">
          <div class="card-icon" style="color: var(--purple);">&#128200;</div>
          <div class="card-title">Market Analysis</div>
          <div class="card-desc">Daily and weekly market breakdowns</div>
        </div>
        <div class="course-card" style="border-color: var(--purple);">
          <div class="card-icon" style="color: var(--purple);">&#128172;</div>
          <div class="card-title">Strategy Discussions</div>
          <div class="card-desc">Share and refine trading strategies</div>
        </div>
        <div class="course-card" style="border-color: var(--purple);">
          <div class="card-icon" style="color: var(--purple);">&#127942;</div>
          <div class="card-title">Elite Community</div>
          <div class="card-desc">Network with serious traders</div>
        </div>
      </div>
      <div style="text-align: center; padding: 16px; background: var(--bg2); border-radius: 8px;">
        <p style="color: var(--purple); font-weight: 600; margin-bottom: 4px;">Premium Access Required</p>
        <p style="color: var(--text-dim); font-size: 0.9rem;">Upgrade to Premium (Coming Soon)</p>
      </div>
    </div>

    <h2>Free TradingView Alert Setups</h2>

    <h3>MFI + MACD Strategy Alerts</h3>
    <div class="course-grid">
      <div class="card">
        <h4 style="color: var(--cyan);">HTF Bias Change (Weekly/Daily)</h4>
        <p style="color: var(--text-dim); margin: 8px 0;">Switch to 1W timeframe, add MFI + MACD indicators. Set alert when MACD Histogram crosses zero line.</p>
        <div style="background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 12px; font-family: monospace; font-size: 0.85rem; color: var(--green); margin-top: 8px; white-space: pre-wrap;">Alert Message:
"WEEKLY BIAS CHANGE: MACD histogram crossed zero.
Direction: {{strategy.order.action}}
Price: {{close}}
Check MFI confirmation before acting."</div>
      </div>
      <div class="card">
        <h4 style="color: var(--cyan);">16H/6H Alignment Signal</h4>
        <p style="color: var(--text-dim); margin: 8px 0;">Set chart to 16H timeframe, add MFI + MACD. Alert when MACD crosses above signal line AND MFI is above 50.</p>
        <div style="background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 12px; font-family: monospace; font-size: 0.85rem; color: var(--green); margin-top: 8px; white-space: pre-wrap;">Alert Message:
"16H ALIGNMENT: MACD crossed above signal.
MFI confirms bullish (>50).
Move to 1H for entry timing."</div>
      </div>
      <div class="card">
        <h4 style="color: var(--cyan);">1H Entry Trigger</h4>
        <p style="color: var(--text-dim); margin: 8px 0;">Set chart to 1H timeframe, add Stoch RSI. Alert when K line crosses above D line.</p>
        <div class="info-box warning" style="margin-top: 8px;">
          <p>Always confirm HTF bias is aligned before taking the entry signal.</p>
        </div>
        <div style="background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 12px; font-family: monospace; font-size: 0.85rem; color: var(--green); margin-top: 8px; white-space: pre-wrap;">Alert Message:
"1H ENTRY: Stoch RSI K crossed above D.
Price: {{close}}
Confirm 16H/6H bias before entering."</div>
      </div>
    </div>

    <h3>Trendline Breakout Alerts</h3>
    <div class="card" style="margin-bottom: 16px;">
      <h4 style="color: var(--cyan);">Trendline Break Alert</h4>
      <p style="color: var(--text-dim); margin: 8px 0;">Draw trendlines on your chart, right-click the trendline and select "Add Alert". Configure the crossing condition.</p>
      <div style="background: var(--bg2); border: 1px solid var(--border); border-radius: 8px; padding: 12px; font-family: monospace; font-size: 0.85rem; color: var(--green); margin-top: 8px; white-space: pre-wrap;">Alert Message:
"TRENDLINE BREAK: Price crossed trendline.
Price: {{close}}
Check volume + RSI for confirmation."</div>
      <div class="info-box warning" style="margin-top: 12px;">
        <p>Always confirm breakouts with volume expansion and RSI momentum before entering a trade.</p>
      </div>
    </div>

    <h2>Alert Management Best Practices</h2>
    <div class="course-grid">
      <div class="course-card">
        <div class="card-icon">&#128241;</div>
        <div class="card-title">Mobile Notifications</div>
        <div class="card-desc">Enable the TradingView mobile app for instant push notifications on all alerts</div>
      </div>
      <div class="course-card">
        <div class="card-icon">&#128264;</div>
        <div class="card-title">Custom Sounds</div>
        <div class="card-desc">Use different alert sounds for different strategies so you know what triggered</div>
      </div>
      <div class="course-card">
        <div class="card-icon">&#128231;</div>
        <div class="card-title">Email Backup</div>
        <div class="card-desc">Set up email notifications as a backup in case you miss a push notification</div>
      </div>
      <div class="course-card">
        <div class="card-icon">&#128465;</div>
        <div class="card-title">Regular Cleanup</div>
        <div class="card-desc">Review and delete old or expired alerts weekly to keep your alert list clean</div>
      </div>
    </div>

    <h2>Webhook Integration</h2>
    <div class="info-box tip">
      <h4 style="margin-bottom: 8px;">Automate Your Alerts</h4>
      <p style="margin-bottom: 12px;">Connect TradingView alerts to external services via webhooks for automated workflows.</p>
      <div style="display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px;">
        <span style="background: var(--bg2); padding: 4px 12px; border-radius: 8px; color: var(--cyan); font-weight: 600;">Discord Bots</span>
        <span style="background: var(--bg2); padding: 4px 12px; border-radius: 8px; color: var(--cyan); font-weight: 600;">Telegram</span>
        <span style="background: var(--bg2); padding: 4px 12px; border-radius: 8px; color: var(--cyan); font-weight: 600;">Slack</span>
        <span style="background: var(--bg2); padding: 4px 12px; border-radius: 8px; color: var(--cyan); font-weight: 600;">Custom APIs</span>
      </div>
      <p style="color: var(--text-dim); font-size: 0.9rem;"><strong>Note:</strong> Webhook functionality requires TradingView Pro+ or Premium subscription.</p>
    </div>

    <div class="step-nav">
      <button class="step-nav-btn" onclick="navigateCourse('dashboard')">&larr; Back to Dashboard</button>
    </div>
  `;
}

// ── Dictionary & FAQ ──
function renderDictionary() {
  const DICTIONARY = [
    // Market Structure (15 terms)
    { term: "Support", cat: "structure", def: "Price level where buying interest consistently prevents further decline. Acts as a floor where demand exceeds supply.", example: "Bitcoin finds support at $40,000 after multiple bounces from that level.", related: ["Resistance", "Breakout", "Retest", "Demand Zone"] },
    { term: "Resistance", cat: "structure", def: "Price level where selling pressure consistently prevents further advance. Acts as a ceiling where supply exceeds demand.", example: "Ethereum faces resistance at $3,000, failing to break through on three separate attempts.", related: ["Support", "Breakout", "Supply Zone", "Double Top"] },
    { term: "Trend", cat: "structure", def: "The general direction of price movement over time. Uptrends consist of higher highs and higher lows; downtrends consist of lower highs and lower lows.", example: "Stock makes successive peaks at $50, $55, $60 with lows at $45, $50, $55 \u2014 a clear uptrend.", related: ["Trendline", "Support", "Resistance", "Breakout"] },
    { term: "Breakout", cat: "structure", def: "A decisive price move beyond an established support or resistance level, typically accompanied by increased volume.", example: "Gold breaks above $1,800 resistance with 3x average volume, confirming the breakout.", related: ["Retest", "Volume", "Resistance", "Support"] },
    { term: "Retest", cat: "structure", def: "When price returns to test a recently broken support or resistance level, confirming the breakout\u2019s validity.", example: "After breaking $50 resistance, stock pulls back to test $50 as new support before continuing higher.", related: ["Breakout", "Support", "Resistance"] },
    { term: "Market Structure", cat: "structure", def: "The framework of swing highs and swing lows that indicates the current trend direction and potential reversals.", example: "Bullish market structure shows a series of higher highs and higher lows on the 4H chart.", related: ["Swing High/Low", "Break of Structure", "Trend"] },
    { term: "Liquidity", cat: "structure", def: "Areas where stop-loss orders and pending orders cluster, typically at key support/resistance levels. Smart money targets these pools.", example: "Stop losses cluster below $100 support level, creating a liquidity pool that gets swept before reversal.", related: ["Inducement", "Support", "Order Block"] },
    { term: "Fair Value Gap (FVG)", cat: "structure", def: "An imbalance created between candle wicks where price moved too quickly, leaving an area of inefficient price discovery that often gets filled.", example: "A large green candle creates a gap between $45 and $47 that price later returns to fill.", related: ["Order Block", "Liquidity", "Market Structure"] },
    { term: "Order Block", cat: "structure", def: "A consolidation zone before a strong directional move, where institutional orders were likely placed. These zones act as future support/resistance.", example: "Price consolidates between $95-$98 before breaking sharply higher; the zone becomes future support.", related: ["Fair Value Gap (FVG)", "Support", "Resistance", "Liquidity"] },
    { term: "Break of Structure (BOS)", cat: "structure", def: "Occurs when price breaks a significant swing high or swing low, signaling a potential change or continuation of trend.", example: "Price breaks above the previous swing high at $120, confirming bullish break of structure.", related: ["Market Structure", "Swing High/Low", "Trend"] },
    { term: "Inducement", cat: "structure", def: "A price move designed to trigger stop losses and trap retail traders before the real move occurs in the opposite direction.", example: "Price briefly breaks below support to trigger stops, then reverses sharply higher \u2014 a classic inducement.", related: ["Liquidity", "Stop Loss", "Market Structure"] },
    { term: "Premium/Discount", cat: "structure", def: "Price levels relative to a defined range. Premium zones (upper half) are ideal for selling; discount zones (lower half) are ideal for buying.", example: "In a $90-$110 range, buying below $95 (discount) and selling above $105 (premium) improves edge.", related: ["Support", "Resistance", "Fair Value Gap (FVG)"] },
    { term: "Swing High/Low", cat: "structure", def: "Local peaks (swing highs) and troughs (swing lows) in price action that define the market structure and trend direction.", example: "Swing high at $150 becomes key resistance; swing low at $130 becomes key support.", related: ["Market Structure", "Trend", "Break of Structure (BOS)"] },
    { term: "Trendline", cat: "structure", def: "A line connecting two or more price points that shows the direction and speed of a trend. Acts as dynamic support or resistance.", example: "Uptrend line connects rising lows at $40, $45, and $50, providing dynamic support.", related: ["Trend", "Support", "Resistance", "Channel"] },
    { term: "Channel", cat: "structure", def: "Two parallel trendlines containing price action, creating a trading range. Can be ascending, descending, or horizontal.", example: "Stock trades within an ascending channel between $95 support trendline and $105 resistance trendline.", related: ["Trendline", "Support", "Resistance", "Trend"] },

    // Indicators (12 terms)
    { term: "EMA", cat: "indicators", def: "Exponential Moving Average gives more weight to recent prices than a simple MA, making it more responsive to new information.", example: "The 21 EMA sits at $100 with price trading above it, suggesting bullish short-term momentum.", related: ["Golden Cross", "Death Cross", "VWAP"] },
    { term: "RSI", cat: "indicators", def: "Relative Strength Index measures momentum on a 0-100 scale. Above 70 is considered overbought; below 30 is oversold.", example: "RSI reads 78 on the daily chart, suggesting the asset is overbought and may pull back.", related: ["Stochastic RSI", "Divergence", "MACD"] },
    { term: "MACD", cat: "indicators", def: "Moving Average Convergence Divergence shows the relationship between two moving averages through a signal line and histogram.", example: "MACD histogram crosses above zero, confirming bullish momentum shift.", related: ["EMA", "Divergence", "RSI"] },
    { term: "Stochastic RSI", cat: "indicators", def: "A stochastic oscillator applied to RSI values, providing a more sensitive momentum indicator that oscillates between 0 and 1.", example: "Stochastic RSI crossing above 20 from oversold territory signals a potential bullish reversal.", related: ["RSI", "Divergence", "MACD"] },
    { term: "MFI", cat: "indicators", def: "Money Flow Index is a volume-weighted RSI that measures buying and selling pressure using both price and volume data.", example: "MFI reading green and rising above 50 indicates increasing buying pressure in the market.", related: ["RSI", "Volume", "VWAP"] },
    { term: "Volume", cat: "indicators", def: "The number of shares or contracts traded in a given period. Confirms price movements and signals strength of trends.", example: "Breakout accompanied by 3x average volume is significantly more reliable than one on low volume.", related: ["MFI", "VWAP", "Breakout", "Liquidity"] },
    { term: "Bollinger Bands", cat: "indicators", def: "Volatility bands placed above and below a moving average, typically 2 standard deviations. Bands widen with volatility.", example: "Price touching the upper Bollinger Band while RSI is overbought may indicate a reversal.", related: ["ATR", "EMA", "RSI"] },
    { term: "ATR", cat: "indicators", def: "Average True Range measures market volatility by calculating the average range between high and low prices over a period.", example: "Stock with a 2% ATR suggests placing stops at least 2-3% away to avoid noise.", related: ["Bollinger Bands", "Stop Loss", "Position Size"] },
    { term: "VWAP", cat: "indicators", def: "Volume Weighted Average Price represents the average price weighted by volume throughout the trading session.", example: "Price trading above VWAP suggests bullish intraday sentiment; institutional buyers are active.", related: ["EMA", "Volume", "MFI"] },
    { term: "Divergence", cat: "indicators", def: "When price and an indicator move in opposite directions, signaling potential trend exhaustion or reversal.", example: "Price makes a higher high while RSI makes a lower high \u2014 bearish divergence warns of potential reversal.", related: ["RSI", "MACD", "Stochastic RSI"] },
    { term: "Golden Cross", cat: "indicators", def: "A bullish signal when a short-term moving average crosses above a long-term moving average, suggesting upward momentum.", example: "The 50 EMA crosses above the 200 EMA on the daily chart, triggering a golden cross buy signal.", related: ["Death Cross", "EMA", "Trend"] },
    { term: "Death Cross", cat: "indicators", def: "A bearish signal when a short-term moving average crosses below a long-term moving average, suggesting downward momentum.", example: "The 50 EMA crosses below the 200 EMA, triggering a death cross and confirming the downtrend.", related: ["Golden Cross", "EMA", "Trend"] },

    // Patterns (8 terms)
    { term: "Double Top", cat: "patterns", def: "A bearish reversal pattern with two peaks at similar price levels, indicating resistance and potential trend change.", example: "Stock reaches $60 twice but fails to break higher, then drops below $55 neckline support.", related: ["Double Bottom", "Resistance", "Head and Shoulders"] },
    { term: "Double Bottom", cat: "patterns", def: "A bullish reversal pattern with two troughs at similar price levels, indicating support and potential trend change.", example: "Crypto finds support at $30,000 twice, forming a W-shape, then breaks above $35,000 neckline.", related: ["Double Top", "Support", "Cup and Handle"] },
    { term: "Head and Shoulders", cat: "patterns", def: "A bearish reversal pattern with three peaks where the middle peak (head) is highest. The pattern completes when price breaks the neckline.", example: "Left shoulder at $55, head at $60, right shoulder at $55 \u2014 pattern completes when price breaks below neckline.", related: ["Double Top", "Resistance", "Break of Structure (BOS)"] },
    { term: "Ascending Triangle", cat: "patterns", def: "A bullish continuation pattern with horizontal resistance and rising support, showing buyers becoming more aggressive.", example: "Price consolidates between flat $50 resistance and a rising support line from $42 to $48.", related: ["Descending Triangle", "Breakout", "Flag Pattern"] },
    { term: "Descending Triangle", cat: "patterns", def: "A bearish continuation pattern with horizontal support and declining resistance, showing sellers becoming more aggressive.", example: "Price consolidates between flat $40 support and declining resistance from $48 to $43.", related: ["Ascending Triangle", "Breakout", "Flag Pattern"] },
    { term: "Flag Pattern", cat: "patterns", def: "A rectangular consolidation pattern after a strong directional move (the flagpole), typically a continuation signal.", example: "After a 20% rally, price consolidates in a narrow downward-sloping range before continuing higher.", related: ["Ascending Triangle", "Wedge", "Breakout"] },
    { term: "Cup and Handle", cat: "patterns", def: "A bullish continuation pattern forming a rounded bottom (cup) followed by a small pullback (handle) before breakout.", example: "Stock forms a rounded bottom from $80 to $65 to $80 (cup), then pulls back to $76 (handle) before breaking out.", related: ["Double Bottom", "Breakout", "Flag Pattern"] },
    { term: "Wedge", cat: "patterns", def: "A pattern with converging trendlines. Rising wedges are bearish; falling wedges are bullish. Shows diminishing momentum.", example: "Rising wedge with higher highs and higher lows converging shows weakening bullish momentum before breakdown.", related: ["Flag Pattern", "Trendline", "Divergence"] },

    // Risk Management (8 terms)
    { term: "Stop Loss", cat: "risk", def: "A predetermined price level where a losing position is automatically closed to limit losses. Essential for capital preservation.", example: "Buy at $100 with stop loss at $95, limiting maximum loss to 5% of position value.", related: ["Take Profit", "Risk-Reward Ratio", "Position Size"] },
    { term: "Take Profit", cat: "risk", def: "A predetermined price level where a winning position is automatically closed to secure gains before potential reversal.", example: "Buy at $100 with take profit at $120, automatically securing a 20% gain.", related: ["Stop Loss", "Risk-Reward Ratio", "Trailing Stop"] },
    { term: "Risk-Reward Ratio", cat: "risk", def: "The ratio comparing potential loss to potential gain on a trade. Higher ratios allow profitability with lower win rates.", example: "Risking $100 to potentially make $200 gives a 1:2 risk-reward ratio \u2014 only need 40% win rate.", related: ["Stop Loss", "Take Profit", "Position Size"] },
    { term: "Position Size", cat: "risk", def: "The amount of capital allocated to a single trade, calculated based on account size and risk tolerance per trade.", example: "$10,000 account risking 2% per trade = $200 maximum loss, determining how many shares to buy.", related: ["Risk-Reward Ratio", "Leverage", "Stop Loss", "Drawdown"] },
    { term: "Drawdown", cat: "risk", def: "The peak-to-trough decline in account value, measuring the largest loss from a high point before recovery.", example: "Account drops from $10,000 peak to $8,500 trough = 15% maximum drawdown.", related: ["Position Size", "Risk-Reward Ratio", "Sharpe Ratio"] },
    { term: "Leverage", cat: "risk", def: "Using borrowed capital to amplify position size beyond account balance. Amplifies both gains and losses equally.", example: "2:1 leverage with $1,000 capital allows controlling a $2,000 position \u2014 gains and losses are doubled.", related: ["Position Size", "Drawdown", "Stop Loss"] },
    { term: "Sharpe Ratio", cat: "risk", def: "A risk-adjusted return metric comparing excess returns to volatility. Higher values indicate better risk-adjusted performance.", example: "A strategy with 15% annual return and 10% volatility has a Sharpe Ratio of 1.5 \u2014 considered good.", related: ["Drawdown", "Risk-Reward Ratio", "ATR"] },
    { term: "Maximum Adverse Excursion (MAE)", cat: "risk", def: "The largest unrealized loss experienced during a winning trade. Helps optimize stop placement by analyzing historical drawdowns.", example: "Winning trade bought at $100 dropped to $95 before reaching $115 profit target = $5 MAE.", related: ["Stop Loss", "Drawdown", "Position Size"] },

    // Orders & Execution (7 terms)
    { term: "Market Order", cat: "orders", def: "An order to buy or sell immediately at the best available current price. Guarantees execution but not price.", example: "Market buy order for 100 shares executes instantly at current ask price of $50.25.", related: ["Limit Order", "Slippage", "Bid-Ask Spread"] },
    { term: "Limit Order", cat: "orders", def: "An order to buy or sell at a specific price or better. Guarantees price but not execution.", example: "Limit buy at $49.50 only executes if price drops to $49.50 or lower \u2014 may not fill.", related: ["Market Order", "Stop Order", "Fill or Kill"] },
    { term: "Stop Order", cat: "orders", def: "An order that becomes a market order once the stop price is reached. Used to limit losses or enter on breakouts.", example: "Stop sell at $95 becomes a market order when price drops to $95, protecting against further decline.", related: ["Stop Loss", "Market Order", "Limit Order"] },
    { term: "OCO (One Cancels Other)", cat: "orders", def: "A pair of linked orders where execution of one automatically cancels the other. Commonly used for TP and SL.", example: "Buy at $100 with OCO: take profit at $110 and stop loss at $95 \u2014 whichever hits first cancels the other.", related: ["Stop Loss", "Take Profit", "Limit Order"] },
    { term: "Slippage", cat: "orders", def: "The difference between the expected execution price and the actual fill price, common during high volatility or low liquidity.", example: "Expected to buy at $100.00 but order fills at $100.15 = $0.15 negative slippage.", related: ["Market Order", "Bid-Ask Spread", "Liquidity"] },
    { term: "Bid-Ask Spread", cat: "orders", def: "The difference between the highest price a buyer will pay (bid) and the lowest price a seller will accept (ask).", example: "Bid at $99.95 and ask at $100.05 = $0.10 spread. Tighter spreads indicate better liquidity.", related: ["Slippage", "Liquidity", "Market Order"] },
    { term: "Fill or Kill", cat: "orders", def: "An order that must be executed immediately in its entirety or cancelled completely. No partial fills allowed.", example: "Fill or Kill order for 1,000 shares at $50 \u2014 either all 1,000 fill instantly or the entire order is cancelled.", related: ["Market Order", "Limit Order", "OCO (One Cancels Other)"] },

    // Psychology (8 terms)
    { term: "FOMO", cat: "psychology", def: "Fear Of Missing Out \u2014 the emotional urge to enter trades impulsively because of rapid price movement, often leading to buying tops.", example: "Chasing a stock after a 50% rally because you fear missing more upside, entering at the peak.", related: ["Revenge Trading", "Overconfidence", "Recency Bias"] },
    { term: "Revenge Trading", cat: "psychology", def: "Making aggressive, poorly planned trades in an attempt to quickly recover from losses, usually leading to larger losses.", example: "After a $500 loss, immediately doubling position size on the next trade to try to 'get even.'", related: ["FOMO", "Loss Aversion", "Overconfidence"] },
    { term: "Confirmation Bias", cat: "psychology", def: "The tendency to seek out information that confirms existing beliefs while ignoring contradictory evidence.", example: "Only reading bullish analysis and ignoring bearish signals while holding a long position.", related: ["Anchoring Bias", "Overconfidence", "Analysis Paralysis"] },
    { term: "Overconfidence", cat: "psychology", def: "Excessive confidence in trading abilities, especially after a winning streak, leading to oversized positions and ignored risk.", example: "After 5 consecutive wins, increasing position size by 3x without proper risk management.", related: ["FOMO", "Revenge Trading", "Position Size"] },
    { term: "Analysis Paralysis", cat: "psychology", def: "Overthinking and over-analyzing to the point of being unable to make a trading decision, missing valid opportunities.", example: "Spending hours analyzing every indicator and timeframe but never executing the trade.", related: ["Confirmation Bias", "FOMO", "Recency Bias"] },
    { term: "Anchoring Bias", cat: "psychology", def: "Over-relying on the first piece of information encountered when making decisions, even when it is no longer relevant.", example: "Fixating on a stock's 52-week high of $200 and refusing to sell at $180 because it 'should' return.", related: ["Confirmation Bias", "Loss Aversion", "Recency Bias"] },
    { term: "Loss Aversion", cat: "psychology", def: "The psychological tendency to prefer avoiding losses over acquiring equivalent gains, leading to holding losers too long.", example: "Holding a losing position for weeks hoping to break even while cutting winning trades after small gains.", related: ["Revenge Trading", "Anchoring Bias", "Stop Loss"] },
    { term: "Recency Bias", cat: "psychology", def: "Giving disproportionate weight to recent events while undervaluing historical patterns and long-term data.", example: "After three consecutive losing trades, assuming the next valid setup will also lose and skipping it.", related: ["FOMO", "Confirmation Bias", "Overconfidence"] }
  ];

  const catColors = {
    structure: 'var(--blue)',
    indicators: 'var(--cyan)',
    patterns: 'var(--purple)',
    risk: 'var(--red)',
    orders: 'var(--yellow)',
    psychology: 'var(--green)'
  };

  const catLabels = {
    structure: 'Market Structure',
    indicators: 'Indicators',
    patterns: 'Patterns',
    risk: 'Risk Management',
    orders: 'Orders & Execution',
    psychology: 'Psychology'
  };

  const catCounts = {};
  DICTIONARY.forEach(d => { catCounts[d.cat] = (catCounts[d.cat] || 0) + 1; });

  const advancedTerms = ['Fair Value Gap (FVG)', 'Order Block', 'Break of Structure (BOS)', 'Inducement', 'Premium/Discount', 'Maximum Adverse Excursion (MAE)', 'Sharpe Ratio', 'Divergence', 'Stochastic RSI', 'Fill or Kill'];

  window._dictionaryData = DICTIONARY;
  window._catColors = catColors;
  window._catLabels = catLabels;

  let html = `
    <div class="course-page-header">
      <h1>Trading Dictionary</h1>
      <p class="subtitle">Your comprehensive reference for all trading terminology</p>
    </div>

    <div style="margin-bottom:24px;">
      <input type="text" id="dict-search" oninput="filterDictionary()" placeholder="Search terms, definitions, examples..."
        style="width:100%;padding:12px 16px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text);font-size:15px;outline:none;">
    </div>

    <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:24px;" id="dict-cat-filters">
      <button onclick="filterDictCat('all')" class="cat-filter-btn active" data-cat="all"
        style="padding:8px 16px;border-radius:6px;border:1px solid var(--border);background:var(--cyan);color:var(--bg);cursor:pointer;font-weight:600;font-size:13px;">All Terms</button>
      <button onclick="filterDictCat('structure')" class="cat-filter-btn" data-cat="structure"
        style="padding:8px 16px;border-radius:6px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-size:13px;">Market Structure</button>
      <button onclick="filterDictCat('indicators')" class="cat-filter-btn" data-cat="indicators"
        style="padding:8px 16px;border-radius:6px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-size:13px;">Indicators</button>
      <button onclick="filterDictCat('patterns')" class="cat-filter-btn" data-cat="patterns"
        style="padding:8px 16px;border-radius:6px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-size:13px;">Patterns</button>
      <button onclick="filterDictCat('risk')" class="cat-filter-btn" data-cat="risk"
        style="padding:8px 16px;border-radius:6px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-size:13px;">Risk Management</button>
      <button onclick="filterDictCat('orders')" class="cat-filter-btn" data-cat="orders"
        style="padding:8px 16px;border-radius:6px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-size:13px;">Orders & Execution</button>
      <button onclick="filterDictCat('psychology')" class="cat-filter-btn" data-cat="psychology"
        style="padding:8px 16px;border-radius:6px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-size:13px;">Psychology</button>
    </div>

    <div class="metric-row" style="margin-bottom:24px;">
      <div class="metric-card">
        <div class="metric-val" style="color:var(--cyan)">${DICTIONARY.length}</div>
        <div class="metric-label">Total Terms</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color:var(--purple)">${Object.keys(catCounts).length}</div>
        <div class="metric-label">Categories</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color:var(--green)">${DICTIONARY.length}</div>
        <div class="metric-label">With Examples</div>
      </div>
      <div class="metric-card">
        <div class="metric-val" style="color:var(--yellow)">${advancedTerms.length}</div>
        <div class="metric-label">Advanced Terms</div>
      </div>
    </div>

    <div id="dict-count" style="margin-bottom:16px;color:var(--text-dim);font-size:14px;">Showing all ${DICTIONARY.length} terms</div>

    <div class="dict-grid" id="dict-grid">
  `;

  DICTIONARY.forEach((item, idx) => {
    const color = catColors[item.cat] || 'var(--text-dim)';
    const label = catLabels[item.cat] || item.cat;
    const relatedHtml = (item.related || []).map(r => `<span class="related">${r}</span>`).join(' ');
    const isAdvanced = advancedTerms.includes(item.term);

    html += `
      <div class="dict-card" data-cat="${item.cat}" data-term="${item.term.toLowerCase()}" data-def="${item.def.toLowerCase()}">
        <div class="term">${item.term}${isAdvanced ? ' <span style="font-size:10px;color:var(--yellow);vertical-align:super;">ADV</span>' : ''}</div>
        <span class="cat-badge" style="background:${color}22;color:${color};border:1px solid ${color}44;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;">${label}</span>
        <div class="def" style="margin-top:10px;">${item.def}</div>
        <div class="example" style="margin-top:8px;font-style:italic;color:var(--text-dim);font-size:13px;">Example: ${item.example}</div>
        ${relatedHtml ? `<div style="margin-top:10px;display:flex;flex-wrap:wrap;gap:4px;">${relatedHtml}</div>` : ''}
      </div>
    `;
  });

  html += `
    </div>

    <div style="text-align:center;margin-top:32px;">
      <button onclick="navigateCourse('dashboard')" style="padding:10px 24px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-size:14px;">&larr; Back to Dashboard</button>
    </div>
  `;

  return html;
}

function filterDictionary() {
  const query = document.getElementById('dict-search').value.toLowerCase().trim();
  const cards = document.querySelectorAll('#dict-grid .dict-card');
  let visible = 0;

  cards.forEach(card => {
    const term = card.getAttribute('data-term');
    const def = card.getAttribute('data-def');
    const match = !query || term.includes(query) || def.includes(query);
    card.style.display = match ? '' : 'none';
    if (match) visible++;
  });

  const countEl = document.getElementById('dict-count');
  if (countEl) {
    countEl.textContent = query ? `Showing ${visible} of ${document.querySelectorAll('#dict-grid .dict-card').length} terms` : `Showing all ${document.querySelectorAll('#dict-grid .dict-card').length} terms`;
  }
}

function filterDictCat(cat) {
  const buttons = document.querySelectorAll('#dict-cat-filters .cat-filter-btn');
  buttons.forEach(btn => {
    const isActive = btn.getAttribute('data-cat') === cat;
    btn.classList.toggle('active', isActive);
    if (isActive) {
      btn.style.background = 'var(--cyan)';
      btn.style.color = 'var(--bg)';
      btn.style.fontWeight = '600';
    } else {
      btn.style.background = 'var(--card)';
      btn.style.color = 'var(--text)';
      btn.style.fontWeight = 'normal';
    }
  });

  const cards = document.querySelectorAll('#dict-grid .dict-card');
  let visible = 0;

  cards.forEach(card => {
    const cardCat = card.getAttribute('data-cat');
    const match = cat === 'all' || cardCat === cat;
    card.style.display = match ? '' : 'none';
    if (match) visible++;
  });

  const countEl = document.getElementById('dict-count');
  if (countEl) {
    const total = document.querySelectorAll('#dict-grid .dict-card').length;
    countEl.textContent = cat === 'all' ? `Showing all ${total} terms` : `Showing ${visible} of ${total} terms`;
  }

  // Clear search when changing category
  const searchEl = document.getElementById('dict-search');
  if (searchEl) searchEl.value = '';
}


function renderFaq() {
  const faqs = [
    {
      q: "Signals conflict (e.g., HTF up, 1h dot appears during chop)",
      a: "Stay out. Always require 16H and 6H MFI+MACD alignment before acting on 1H signals. Higher timeframe takes priority \u2014 if the 6H or 16H is not confirming, the 1H signal is unreliable. Wait for multi-timeframe confluence before entering any position."
    },
    {
      q: "False VuManChu dots / Indicator signals",
      a: "Wait for candle close confirmation before acting on any signal. Require HTF + 16H/6H confirmations to validate the signal. Avoid trading during low-volume hours when false signals are most common. Always use volume as a confirmation filter \u2014 signals without volume support are unreliable."
    },
    {
      q: "Trading in choppy ranges",
      a: "Trade less frequently. Use the trendline strategy sparingly in ranges \u2014 it performs best in trending markets. Widen your filters by requiring stronger HTF bias and higher MFI thresholds. Focus on support and resistance bounces instead of breakout strategies during chop."
    },
    {
      q: "How do I know if a trendline is valid?",
      a: "A valid trendline needs at least 3 touch points with clear rejection wicks at each touch. The angle should be consistent \u2014 not too steep (unsustainable) or too flat (weak trend). Confirm across multiple timeframes and always draw trendlines on higher timeframes first, then validate on lower ones."
    },
    {
      q: "What's the best risk/reward ratio?",
      a: "Minimum 1:2 is recommended for most setups. A 1:1 ratio is only acceptable for setups with 80%+ historical win rate. At 1:2, you only need a 50%+ win rate to be profitable. For swing trades, aim for 1:3 or higher \u2014 this allows profitability even with a 40-50% win rate."
    },
    {
      q: "What are the best trading hours for BTC?",
      a: "Best hours: 8AM-12PM EST (European and US session overlap with highest volume), 9:30AM-4PM EST (US market hours, strong correlation moves), and 6PM-10PM EST (Asian session overlap). Avoid late Friday through early Monday (weekend gaps) and 2AM-6AM EST (lowest liquidity period)."
    },
    {
      q: "How much should I risk per trade?",
      a: "Conservative approach: 1-2% of account per trade. For accounts $1k-$10k: risk 1% maximum. For $10k-$50k: 1-2%. For $50k+: 0.5-1.5%. Never risk more than 6% of your account in a single day across all open positions. Reduce size during losing streaks."
    },
    {
      q: "When should I move my stop loss?",
      a: "Never move your stop against your position (further from entry). Move to breakeven after TP1 is hit. Trail using previous swing highs/lows or moving averages as dynamic levels. Use time-based stops: if a trade shows no progress in 24-48 hours, consider closing or tightening the stop."
    },
    {
      q: "Should I use leverage?",
      a: "Beginners: No leverage for the first 6 months \u2014 learn risk management with spot first. Intermediate traders: 2-3x maximum with tight stops and proven risk management. Advanced: Up to 5x only on highest conviction setups. Remember that leverage amplifies both gains AND losses equally."
    },
    {
      q: "My indicators aren't showing the same signals",
      a: "Check that your timeframes are synced across all charts. Verify you are using the exact indicator settings from the course templates. Always wait for candle close before reading signals \u2014 mid-candle readings change. Slight variations between exchanges are normal due to data feed differences."
    },
    {
      q: "How often should I review performance?",
      a: "Daily: Review open positions and current P&L. Weekly: Detailed analysis including win rate, average R-multiples, and best/worst trades. Monthly: Full strategy review \u2014 identify what patterns are working and what needs adjustment. Quarterly: Make major strategy adjustments based on accumulated data."
    },
    {
      q: "How long before I become profitable?",
      a: "Months 1-3: Learning phase, practice on demo accounts only. Months 4-6: Small live positions, focus on consistency over profit. Months 7-12: Developing your edge, refining strategy. Year 2+: Consistent profitability becomes achievable. Remember that 80% of traders lose money initially. Focus on education, risk management, and patience."
    }
  ];

  let html = `
    <div class="course-page-header">
      <h1>FAQ & Troubleshooting</h1>
      <p class="subtitle">Common questions and solutions for trading strategies, indicators, and platform usage</p>
    </div>

    <div style="margin-bottom:32px;">
  `;

  faqs.forEach((faq, idx) => {
    html += `
      <div class="faq-item" id="faq-item-${idx}" onclick="toggleFaq(${idx})">
        <div class="faq-q">
          <span>${faq.q}</span>
          <span class="faq-arrow">&#9660;</span>
        </div>
        <div class="faq-a">${faq.a}</div>
      </div>
    `;
  });

  html += `
    </div>

    <div class="card" style="text-align:center;padding:32px;">
      <h3 style="margin-bottom:12px;color:var(--text);">Still have questions?</h3>
      <p style="color:var(--text-dim);margin-bottom:20px;">Explore more resources to deepen your understanding.</p>
      <div style="display:flex;justify-content:center;gap:12px;flex-wrap:wrap;">
        <button onclick="navigateCourse('dictionary')" style="padding:10px 20px;border-radius:8px;border:1px solid var(--cyan);background:var(--cyan)22;color:var(--cyan);cursor:pointer;font-size:14px;font-weight:600;">Trading Dictionary</button>
        <button onclick="navigateCourse('bull-market')" style="padding:10px 20px;border-radius:8px;border:1px solid var(--green);background:var(--green)22;color:var(--green);cursor:pointer;font-size:14px;font-weight:600;">Bull Market Guide</button>
        <button onclick="navigateCourse('dashboard')" style="padding:10px 20px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-size:14px;">Back to Dashboard</button>
      </div>
    </div>

    <div style="text-align:center;margin-top:24px;">
      <button onclick="navigateCourse('dashboard')" style="padding:10px 24px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-size:14px;">&larr; Back to Dashboard</button>
    </div>
  `;

  return html;
}

function renderVideoLibrary() {
  var videos = [
    { id: 'JzTMlClbM84', title: 'Step 1: Trading Fundamentals', desc: 'Essential building blocks of technical analysis and candlestick reading.' },
    { id: 'ucR2gg8v9Uo', title: 'Step 2: Professional Setup', desc: 'Build your professional TradingView workspace with proper indicators.' },
    { id: 'XeNp9drLM9s', title: 'Step 3: Market Structure', desc: 'Master market structure, trend identification, and support/resistance.' },
    { id: 'T2D0PtADAu0', title: 'Step 4: Risk Management', desc: 'Institutional-level position sizing, stop losses, and capital preservation.' },
    { id: 'F8LbNp7aUsg', title: 'Step 5: Technical Indicators', desc: 'RSI, MACD, MFI, and Stochastic RSI for precise market timing.' },
    { id: 'H7Gnh1W6VuE', title: 'Step 6: Trading Readiness', desc: 'Complete your comprehensive readiness evaluation.' }
  ];

  var html = '<div class="course-page-header"><h1>Video Library</h1><p class="subtitle">All course videos in one place</p></div>';
  html += '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:24px;margin-top:20px;">';

  videos.forEach(function(v) {
    html += '<div class="card" style="padding:0;overflow:hidden;">' +
      '<div style="position:relative;padding-bottom:56.25%;height:0;">' +
      '<iframe src="https://www.youtube.com/embed/' + v.id + '" style="position:absolute;top:0;left:0;width:100%;height:100%;border:none;" allowfullscreen></iframe>' +
      '</div>' +
      '<div style="padding:16px;">' +
      '<h3 style="font-size:14px;color:var(--text);margin-bottom:6px;">' + v.title + '</h3>' +
      '<p style="font-size:12px;color:var(--text-dim);margin:0;">' + v.desc + '</p>' +
      '</div></div>';
  });

  html += '</div>';
  html += '<div style="text-align:center;margin-top:24px;"><button onclick="navigateCourse(\'dashboard\')" style="padding:10px 24px;border-radius:8px;border:1px solid var(--border);background:var(--card);color:var(--text);cursor:pointer;font-size:14px;">&larr; Back to Dashboard</button></div>';

  return html;
}

function toggleFaq(idx) {
  const item = document.getElementById('faq-item-' + idx);
  if (item) {
    item.classList.toggle('open');
  }
}


/* ═══════════════════════════════════════════════════════════════════ */
/* TOAST NOTIFICATION SYSTEM                                          */
/* ═══════════════════════════════════════════════════════════════════ */
function showToast(title, message, type='info', duration=4000) {
  const container = document.getElementById('toast-container');
  if(!container) return;
  const icons = { success:'&#10003;', error:'&#10007;', warning:'&#9888;', info:'&#8505;' };
  const toast = document.createElement('div');
  toast.className = 'toast toast-'+type;
  toast.innerHTML = '<span class="toast-icon">'+(icons[type]||icons.info)+'</span><div class="toast-body"><div class="toast-title" style="color:var(--'+({success:'green',error:'red',warning:'yellow',info:'blue'}[type]||'blue')+');">'+title+'</div><div class="toast-msg">'+message+'</div></div><button class="toast-close" onclick="this.parentElement.remove()">&times;</button>';
  container.appendChild(toast);
  requestAnimationFrame(() => { requestAnimationFrame(() => { toast.classList.add('show'); }); });
  setTimeout(() => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); }, duration);
}

/* ═══════════════════════════════════════════════════════════════════ */
/* KEYBOARD SHORTCUTS                                                  */
/* ═══════════════════════════════════════════════════════════════════ */
const TAB_ORDER = ['overview','charts','signals','trades','analytics','system','learn'];
function toggleKbModal() {
  document.getElementById('kb-overlay').classList.toggle('visible');
  document.getElementById('kb-modal').classList.toggle('visible');
}

document.addEventListener('keydown', function(e) {
  // Don't trigger when typing in inputs
  if(e.target.tagName==='INPUT'||e.target.tagName==='TEXTAREA'||e.target.isContentEditable) return;

  // Number keys 1-7 for tab switching
  if(e.key>='1' && e.key<='7' && !e.ctrlKey && !e.metaKey && !e.altKey) {
    const idx = parseInt(e.key) - 1;
    if(idx < TAB_ORDER.length) {
      const btn = document.querySelector('[data-tab="'+TAB_ORDER[idx]+'"]');
      if(btn) { btn.click(); showToast('Tab', 'Switched to '+TAB_ORDER[idx].charAt(0).toUpperCase()+TAB_ORDER[idx].slice(1), 'info', 1500); }
    }
    return;
  }

  // R = refresh
  if(e.key==='r' && !e.ctrlKey && !e.metaKey) { e.preventDefault(); loadAll(); showToast('Refresh', 'Data refreshed', 'success', 1500); countdownSeconds=30; return; }

  // F = fullscreen chart (only on charts tab)
  if(e.key==='f' && !e.ctrlKey && !e.metaKey) {
    const chartsTab = document.getElementById('tab-charts');
    if(chartsTab && chartsTab.classList.contains('active')) { toggleChartFullscreen(); return; }
  }

  // ? or / = keyboard shortcuts
  if(e.key==='?' || (e.key==='/' && !e.ctrlKey)) { toggleKbModal(); return; }

  // Escape = close modals, exit fullscreen
  if(e.key==='Escape') {
    closeEdu();
    const kb = document.getElementById('kb-modal');
    if(kb && kb.classList.contains('visible')) toggleKbModal();
    const card = document.getElementById('chart-card');
    if(card && card.classList.contains('chart-fullscreen')) toggleChartFullscreen();
  }
});

/* ═══════════════════════════════════════════════════════════════════ */
/* FULLSCREEN CHART TOGGLE                                             */
/* ═══════════════════════════════════════════════════════════════════ */
function toggleChartFullscreen() {
  const card = document.getElementById('chart-card');
  if(!card) return;
  const isFS = card.classList.toggle('chart-fullscreen');
  const btn = card.querySelector('.btn-fullscreen');
  if(btn) btn.innerHTML = isFS ? '&#10005; Exit' : '&#x26F6; Fullscreen';
  if(tvChart) {
    const container = document.getElementById('main-chart-container');
    setTimeout(() => {
      tvChart.applyOptions({ width: container.clientWidth, height: isFS ? window.innerHeight - 60 : 420 });
      tvChart.timeScale().fitContent();
    }, 100);
  }
}

/* ═══════════════════════════════════════════════════════════════════ */
/* REFRESH COUNTDOWN TIMER                                             */
/* ═══════════════════════════════════════════════════════════════════ */
let countdownSeconds = 30;
function updateCountdown() {
  countdownSeconds--;
  if(countdownSeconds <= 0) countdownSeconds = 30;
  const fill = document.getElementById('countdown-fill');
  const text = document.getElementById('countdown-text');
  if(fill) fill.style.width = ((countdownSeconds/30)*100)+'%';
  if(text) text.textContent = countdownSeconds+'s';
}
setInterval(updateCountdown, 1000);

/* ═══════════════════════════════════════════════════════════════════ */
/* CONNECTION QUALITY / LATENCY TRACKING                               */
/* ═══════════════════════════════════════════════════════════════════ */
let lastLatency = 0;
async function measureLatency() {
  const start = performance.now();
  try {
    await fetch('/api/health');
    lastLatency = Math.round(performance.now() - start);
  } catch { lastLatency = -1; }
  const dot = document.getElementById('latency-dot');
  if(dot) {
    if(lastLatency < 0) { dot.className='latency-dot latency-bad'; dot.title='Connection lost'; }
    else if(lastLatency < 200) { dot.className='latency-dot latency-good'; dot.title='Latency: '+lastLatency+'ms'; }
    else if(lastLatency < 1000) { dot.className='latency-dot latency-ok'; dot.title='Latency: '+lastLatency+'ms'; }
    else { dot.className='latency-dot latency-bad'; dot.title='Latency: '+lastLatency+'ms'; }
  }
}
setInterval(measureLatency, 60000);
setTimeout(measureLatency, 3000);

/* ═══════════════════════════════════════════════════════════════════ */
/* CSV / JSON EXPORT                                                   */
/* ═══════════════════════════════════════════════════════════════════ */
let cachedTrades = [];

function exportTrades(format) {
  if(cachedTrades.length === 0) { showToast('Export', 'No trade data to export', 'warning'); return; }
  let content, filename, mime;
  if(format === 'csv') {
    const headers = ['Time','Symbol','Side','Action','Price','PnL','Strategy'];
    const rows = cachedTrades.map(t => [
      t.timestamp||'', t.symbol||'', t.side||'', t.action||'', t.price||0, t.pnl||0, t.strategy||''
    ].map(v => '"'+String(v).replace(/"/g,'""')+'"').join(','));
    content = headers.join(',') + '\n' + rows.join('\n');
    filename = 'trades_'+new Date().toISOString().slice(0,10)+'.csv';
    mime = 'text/csv';
  } else {
    content = JSON.stringify(cachedTrades, null, 2);
    filename = 'trades_'+new Date().toISOString().slice(0,10)+'.json';
    mime = 'application/json';
  }
  const blob = new Blob([content], {type: mime});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
  showToast('Export', 'Downloaded '+filename+' ('+cachedTrades.length+' trades)', 'success');
}

/* ═══════════════════════════════════════════════════════════════════ */
/* SORTABLE TABLE COLUMNS                                              */
/* ═══════════════════════════════════════════════════════════════════ */
let sortState = {};
document.addEventListener('click', function(e) {
  const th = e.target.closest('th.sortable');
  if(!th) return;
  const table = th.closest('table');
  if(!table) return;
  const tbody = table.querySelector('tbody');
  if(!tbody) return;
  const idx = Array.from(th.parentElement.children).indexOf(th);
  const key = th.dataset.sort || idx;

  // Toggle sort direction
  const currentDir = sortState[key] || 'none';
  const newDir = currentDir === 'asc' ? 'desc' : 'asc';

  // Reset all headers in this table
  th.parentElement.querySelectorAll('th.sortable').forEach(h => { h.classList.remove('sort-asc','sort-desc'); });
  th.classList.add('sort-'+newDir);
  sortState[key] = newDir;

  // Sort rows
  const rows = Array.from(tbody.querySelectorAll('tr')).filter(r => !r.querySelector('.empty'));
  rows.sort((a,b) => {
    const aCell = a.children[idx]; const bCell = b.children[idx];
    if(!aCell||!bCell) return 0;
    let aVal = aCell.textContent.trim().replace(/[$+,%]/g,'');
    let bVal = bCell.textContent.trim().replace(/[$+,%]/g,'');
    const aNum = parseFloat(aVal); const bNum = parseFloat(bVal);
    if(!isNaN(aNum) && !isNaN(bNum)) return newDir==='asc' ? aNum-bNum : bNum-aNum;
    return newDir==='asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
  });
  rows.forEach(r => tbody.appendChild(r));
});

/* ═══════════════════════════════════════════════════════════════════ */
/* QUICK STATS & STREAK CALCULATION                                    */
/* ═══════════════════════════════════════════════════════════════════ */
function updateQuickStats(trades, pipeline) {
  if(!trades || trades.length === 0) return;

  // Win/Loss streak
  let streak = 0;
  let streakType = '';
  for(let i=trades.length-1; i>=0; i--) {
    const pnl = trades[i].pnl || 0;
    if(i === trades.length-1) { streakType = pnl >= 0 ? 'win' : 'loss'; streak = 1; }
    else {
      if((pnl >= 0 && streakType === 'win') || (pnl < 0 && streakType === 'loss')) streak++;
      else break;
    }
  }
  const streakEl = document.getElementById('qs-streak');
  if(streakEl) {
    streakEl.innerHTML = '<span class="streak-badge streak-'+streakType+'">'+streak+' '+streakType+(streak>1?'s':'')+(streakType==='win'?' &#128293;':' &#10052;')+'</span>';
  }

  // Best & worst trade
  const pnls = trades.map(t => t.pnl||0).filter(p => p !== 0);
  if(pnls.length > 0) {
    const best = Math.max(...pnls);
    const worst = Math.min(...pnls);
    const bestEl = document.getElementById('qs-best-trade');
    const worstEl = document.getElementById('qs-worst-trade');
    if(bestEl) { bestEl.textContent = fmt$(best); bestEl.style.color = 'var(--green)'; }
    if(worstEl) { worstEl.textContent = fmt$(worst); worstEl.style.color = 'var(--red)'; }
  }

  // Profit factor
  const grossWin = pnls.filter(p=>p>0).reduce((a,b)=>a+b,0);
  const grossLoss = Math.abs(pnls.filter(p=>p<0).reduce((a,b)=>a+b,0));
  const pfEl = document.getElementById('qs-profit-factor');
  if(pfEl) {
    const pf = grossLoss > 0 ? (grossWin/grossLoss).toFixed(2) : (grossWin > 0 ? '∞' : '--');
    pfEl.textContent = pf;
    pfEl.style.color = parseFloat(pf) >= 1.5 ? 'var(--green)' : (parseFloat(pf) >= 1 ? 'var(--yellow)' : 'var(--red)');
  }

  // Signals today
  if(pipeline) {
    const sigEl = document.getElementById('qs-signals-today');
    if(sigEl) sigEl.textContent = (pipeline.total_signals||0) + ' (' + (pipeline.passed||0) + ' passed)';
  }
}

/* ═══════════════════════════════════════════════════════════════════ */
/* PNL CALENDAR HEATMAP                                                */
/* ═══════════════════════════════════════════════════════════════════ */
async function loadPnlCalendar() {
  try {
    const res = await fetch('/api/performance?days=90');
    if(!res.ok) return;
    const data = await res.json();
    const el = document.getElementById('pnl-calendar');
    if(!el || !data || data.length === 0) { if(el) el.innerHTML='<div class="empty">No performance data for calendar</div>'; return; }

    // Build date->pnl map
    const pnlMap = {};
    let maxPnl = 0;
    data.forEach(d => {
      if(d.date && d.pnl != null) {
        pnlMap[d.date] = d.pnl;
        maxPnl = Math.max(maxPnl, Math.abs(d.pnl));
      }
    });
    if(maxPnl === 0) maxPnl = 1;

    // Generate 90-day grid (13 weeks)
    const today = new Date();
    const startDate = new Date(today);
    startDate.setDate(startDate.getDate() - 89);
    // Align to start of week (Sunday)
    startDate.setDate(startDate.getDate() - startDate.getDay());

    const dayNames = ['S','M','T','W','T','F','S'];
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    let weeks = [];
    let currentWeek = [];
    let d = new Date(startDate);

    while(d <= today || currentWeek.length > 0) {
      if(currentWeek.length === 7) { weeks.push(currentWeek); currentWeek = []; }
      if(d > today && currentWeek.length === 0) break;
      const dateStr = d.getFullYear()+'-'+(d.getMonth()+1).toString().padStart(2,'0')+'-'+d.getDate().toString().padStart(2,'0');
      currentWeek.push({ date:dateStr, day:d.getDay(), month:d.getMonth(), dayOfMonth:d.getDate(), pnl:pnlMap[dateStr], future:d > today });
      d.setDate(d.getDate() + 1);
    }
    if(currentWeek.length > 0) { while(currentWeek.length < 7) currentWeek.push({future:true}); weeks.push(currentWeek); }

    // Render
    let html = '<div class="pnl-calendar">';
    // Day labels row
    html += '<div class="pnl-cal-row"><div class="pnl-cal-label"></div>';
    // Month labels
    let lastMonth = -1;
    weeks.forEach((week,wi) => {
      const firstDay = week.find(d => !d.future && d.dayOfMonth);
      const mo = firstDay ? firstDay.month : -1;
      if(mo !== lastMonth && mo >= 0) { html += '<div style="width:14px;font-size:9px;color:var(--muted);text-align:center;">'+months[mo].charAt(0)+'</div>'; lastMonth = mo; }
      else { html += '<div style="width:14px;"></div>'; }
    });
    html += '</div>';

    // Rows for each day of week
    for(let dow=0; dow<7; dow++) {
      html += '<div class="pnl-cal-row"><div class="pnl-cal-label">'+dayNames[dow]+'</div>';
      weeks.forEach(week => {
        const cell = week[dow];
        if(!cell || cell.future) { html += '<div style="width:14px;height:14px;"></div>'; return; }
        const pnl = cell.pnl;
        let bg;
        if(pnl == null) bg = 'var(--border)';
        else if(pnl === 0) bg = 'var(--border)';
        else if(pnl > 0) { const intensity = Math.min(Math.abs(pnl)/maxPnl, 1); bg = 'rgba(0,230,160,'+(0.15 + intensity*0.65).toFixed(2)+')'; }
        else { const intensity = Math.min(Math.abs(pnl)/maxPnl, 1); bg = 'rgba(255,68,102,'+(0.15 + intensity*0.65).toFixed(2)+')'; }
        const tooltip = pnl != null ? '<div class="cal-tooltip"><strong>'+cell.date+'</strong><br>PnL: <span style="color:'+pnlColor(pnl)+'">'+fmt$(pnl)+'</span></div>' : '<div class="cal-tooltip">'+cell.date+' &mdash; No trades</div>';
        html += '<div class="cal-cell" style="background:'+bg+';" title="">'+tooltip+'</div>';
      });
      html += '</div>';
    }
    html += '</div>';

    // Summary stats
    const tradingDays = Object.keys(pnlMap).length;
    const profitDays = Object.values(pnlMap).filter(p => p > 0).length;
    const lossDays = Object.values(pnlMap).filter(p => p < 0).length;
    const totalPnl = Object.values(pnlMap).reduce((a,b)=>a+b, 0);
    html += '<div style="display:flex;gap:20px;margin-top:12px;font-size:11px;">';
    html += '<span style="color:var(--muted);">'+tradingDays+' trading days</span>';
    html += '<span style="color:var(--green);">'+profitDays+' profit days ('+(tradingDays>0?((profitDays/tradingDays)*100).toFixed(0):0)+'%)</span>';
    html += '<span style="color:var(--red);">'+lossDays+' loss days</span>';
    html += '<span style="color:'+pnlColor(totalPnl)+';font-weight:700;">Total: '+fmt$(totalPnl)+'</span>';
    html += '</div>';

    el.innerHTML = html;
  } catch(e) { console.error('PnL calendar error:', e); }
}

/* ═══════════════════════════════════════════════════════════════════ */
/* POSITION ROW EXPANSION                                              */
/* ═══════════════════════════════════════════════════════════════════ */
function makePositionsExpandable() {
  const tbody = document.getElementById('positions-body');
  if(!tbody) return;
  tbody.querySelectorAll('tr.pos-row').forEach(row => {
    row.addEventListener('click', function() {
      const next = this.nextElementSibling;
      if(next && next.classList.contains('pos-expand-row')) {
        next.style.display = next.style.display === 'none' ? 'table-row' : 'none';
      }
    });
  });
}

/* Enhanced position rendering with expandable details */
const _origRenderPositions = renderPositions;
renderPositions = function(positions) {
  const tbody = document.getElementById('positions-body');
  if(!tbody) return;
  if(!positions || positions.length === 0) {
    _origRenderPositions(positions);
    return;
  }
  _origRenderPositions(positions);

  // Now enhance rows with expandable details
  const rows = tbody.querySelectorAll('tr');
  const newRows = [];
  positions.forEach((p, i) => {
    if(i < rows.length) {
      rows[i].classList.add('pos-row');
      rows[i].title = 'Click to expand details';
      // Create detail row
      const detailRow = document.createElement('tr');
      detailRow.className = 'pos-expand-row';
      detailRow.style.display = 'none';
      detailRow.innerHTML = '<td colspan="11"><div class="pos-detail"><div class="pos-detail-grid">' +
        '<div class="pos-detail-item"><div class="pos-detail-label">Stop Loss</div><div class="pos-detail-value" style="color:var(--red);">'+fmtPrice(p.sl)+'</div></div>' +
        '<div class="pos-detail-item"><div class="pos-detail-label">Take Profit 1</div><div class="pos-detail-value" style="color:var(--green);">'+fmtPrice(p.tp1)+'</div></div>' +
        '<div class="pos-detail-item"><div class="pos-detail-label">Take Profit 2</div><div class="pos-detail-value" style="color:var(--green);">'+fmtPrice(p.tp2)+'</div></div>' +
        '<div class="pos-detail-item"><div class="pos-detail-label">Confidence</div><div class="pos-detail-value">'+(p.confidence!=null?p.confidence.toFixed(0)+'%':'--')+'</div></div>' +
        '<div class="pos-detail-item"><div class="pos-detail-label">Risk (SL Distance)</div><div class="pos-detail-value">'+(p.entry_price&&p.sl?((Math.abs(p.entry_price-p.sl)/p.entry_price)*100).toFixed(2)+'%':'--')+'</div></div>' +
        '<div class="pos-detail-item"><div class="pos-detail-label">R:R to TP1</div><div class="pos-detail-value">'+(p.entry_price&&p.sl&&p.tp1?((Math.abs(p.tp1-p.entry_price)/Math.abs(p.entry_price-p.sl))).toFixed(2)+'x':'--')+'</div></div>' +
        (p.notes ? '<div class="pos-detail-item" style="grid-column:1/-1;"><div class="pos-detail-label">Notes</div><div class="pos-detail-value" style="font-weight:400;color:var(--text-dim);">'+p.notes+'</div></div>' : '') +
        '</div></div></td>';
      newRows.push({after: rows[i], detail: detailRow});
    }
  });
  newRows.forEach(nr => nr.after.after(nr.detail));
  makePositionsExpandable();
};

/* ═══════════════════════════════════════════════════════════════════ */
/* ENHANCED DATA LOADING (with quick stats + toast alerts)             */
/* ═══════════════════════════════════════════════════════════════════ */
let prevCBTripped = false;
let prevPositionCount = 0;
let prevErrorCount = 0;

const _origLoadAll = loadAll;
loadAll = async function() {
  countdownSeconds = 30;
  const startTime = performance.now();
  await _origLoadAll();
  const elapsed = Math.round(performance.now() - startTime);

  // Update latency display
  const dot = document.getElementById('latency-dot');
  if(dot) {
    if(elapsed < 500) { dot.className='latency-dot latency-good'; }
    else if(elapsed < 2000) { dot.className='latency-dot latency-ok'; }
    else { dot.className='latency-dot latency-bad'; }
    dot.title = 'Last fetch: '+elapsed+'ms';
  }

  // Load quick stats data
  try {
    const [dataRes, pipelineRes] = await Promise.allSettled([fetch('/api/data'), fetch('/api/pipeline')]);
    let trades = [], pipeline = null;
    if(dataRes.status==='fulfilled' && dataRes.value.ok) {
      const data = await dataRes.value.json();
      trades = data.recent_trades || [];
      cachedTrades = trades;
    }
    if(pipelineRes.status==='fulfilled' && pipelineRes.value.ok) pipeline = await pipelineRes.value.json();
    updateQuickStats(trades, pipeline);

    // Toast alerts for state changes
    try {
      const riskRes = await fetch('/api/risk');
      if(riskRes.ok) {
        const risk = await riskRes.json();
        if(risk.cb_tripped && !prevCBTripped) showToast('Circuit Breaker', 'Circuit breaker has been TRIPPED! Trading paused.', 'error', 8000);
        else if(!risk.cb_tripped && prevCBTripped) showToast('Circuit Breaker', 'Circuit breaker reset. Trading resumed.', 'success', 5000);
        prevCBTripped = risk.cb_tripped;
      }
    } catch {}

    // Position change alerts
    try {
      const posRes = await fetch('/api/positions');
      if(posRes.ok) {
        const positions = await posRes.json();
        if(positions.length > prevPositionCount && prevPositionCount >= 0) {
          const newPos = positions[positions.length-1];
          if(prevPositionCount > 0) showToast('New Position', (newPos.symbol||'???')+' '+(newPos.side||'')+ ' opened at '+fmtPrice(newPos.entry_price), 'info', 5000);
        } else if(positions.length < prevPositionCount && prevPositionCount > 0) {
          showToast('Position Closed', 'A position was closed', 'info', 4000);
        }
        prevPositionCount = positions.length;
      }
    } catch {}
  } catch {}
};

/* ═══════════════════════════════════════════════════════════════════ */
/* LIVE MARKET INTELLIGENCE PANEL                                     */
/* ═══════════════════════════════════════════════════════════════════ */

let marketIntelInitialized = false;
let marketIntelInterval = null;

async function loadMarketIntel() {
  try {
    const [marketRes, pipelineRes, rejectionsRes, weightsRes, riskRes, agentsRes] = await Promise.allSettled([
      fetch('/api/market'), fetch('/api/pipeline'), fetch('/api/rejections'),
      fetch('/api/weights'), fetch('/api/risk'), fetch('/api/agents/last')
    ]);

    let market=null, pipeline=null, rejections=null, weights=null, risk=null, agents=null;
    if(marketRes.status==='fulfilled' && marketRes.value.ok) try { market = await marketRes.value.json(); } catch {}
    if(pipelineRes.status==='fulfilled' && pipelineRes.value.ok) try { pipeline = await pipelineRes.value.json(); } catch {}
    if(rejectionsRes.status==='fulfilled' && rejectionsRes.value.ok) try { rejections = await rejectionsRes.value.json(); } catch {}
    if(weightsRes.status==='fulfilled' && weightsRes.value.ok) try { weights = await weightsRes.value.json(); } catch {}
    if(riskRes.status==='fulfilled' && riskRes.value.ok) try { risk = await riskRes.value.json(); } catch {}
    if(agentsRes.status==='fulfilled' && agentsRes.value.ok) try { agents = await agentsRes.value.json(); } catch {}

    renderMarketRegimes(market);
    renderIntelPipeline(pipeline, rejections);
    renderStrategyConsensus(weights);
    renderRiskIntel(risk);
    renderAgentIntel(agents);
    renderBestOpportunities(rejections);
  } catch(e) { console.error('Market intel error:', e); }
}

function renderMarketRegimes(market) {
  var el = document.getElementById('market-intel-regimes');
  if(!el) return;
  if(!market || !Array.isArray(market) || market.length === 0) {
    el.innerHTML = '<div class="card" style="grid-column:1/-1;text-align:center;padding:20px;"><div style="color:var(--text-dim);font-size:12px;">No market data available yet. Regimes will appear once the bot generates signals.</div></div>';
    return;
  }
  var regimeColors = { trend:'var(--green)', range:'var(--yellow)', panic:'var(--red)', high_volatility:'var(--orange)', low_liquidity:'var(--purple)', news_dislocation:'var(--red)', consolidation:'var(--yellow)', unknown:'var(--muted)' };
  var regimeIcons = { trend:'\u2197', range:'\u2194', panic:'\u26A0', high_volatility:'\u26A1', low_liquidity:'\uD83D\uDCA7', news_dislocation:'\uD83D\uDCF0', consolidation:'\u23F8', unknown:'?' };
  el.innerHTML = market.map(function(m) {
    var regime = m.regime || 'unknown';
    var color = regimeColors[regime] || 'var(--muted)';
    var icon = regimeIcons[regime] || '?';
    var bias = m.bias || 'neutral';
    var biasColor = bias==='bullish' ? 'var(--green)' : (bias==='bearish' ? 'var(--red)' : 'var(--text-dim)');
    var danger = m.danger || 0;
    var dangerColor = danger > 60 ? 'var(--red)' : (danger > 30 ? 'var(--yellow)' : 'var(--green)');
    var confidence = m.confidence != null ? (m.confidence * 100).toFixed(0) + '%' : '--';
    return '<div class="card" style="padding:16px;">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">' +
      '<strong style="font-size:14px;color:var(--text);">' + (m.symbol||'--') + '</strong>' +
      '<span style="font-size:18px;">' + icon + '</span></div>' +
      '<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">' +
      '<span style="font-size:11px;font-weight:700;color:' + color + ';text-transform:uppercase;">' + regime + '</span>' +
      '<span style="font-size:10px;color:var(--text-dim);">' + confidence + ' conf</span></div>' +
      '<div style="font-size:11px;color:' + biasColor + ';margin-bottom:6px;">Bias: ' + bias + '</div>' +
      '<div style="font-size:10px;color:var(--text-dim);margin-bottom:4px;">Danger Level</div>' +
      '<div style="background:var(--bg2);border-radius:4px;height:6px;overflow:hidden;">' +
      '<div style="width:' + danger + '%;height:100%;background:' + dangerColor + ';border-radius:4px;transition:width 0.3s;"></div></div>' +
      '<div style="font-size:10px;color:' + dangerColor + ';text-align:right;margin-top:2px;">' + danger + '/100</div>' +
      '</div>';
  }).join('');
}

function renderIntelPipeline(pipeline, rejections) {
  var pipeEl = document.getElementById('intel-pipeline-status');
  var whyEl = document.getElementById('intel-why-no-trades');
  if(!pipeEl || !whyEl) return;

  if(pipeline) {
    var gen = pipeline.generated || 0;
    var approved = pipeline.approved || 0;
    var executed = pipeline.executed || 0;
    var rejected = gen - approved;
    pipeEl.innerHTML =
      '<div style="display:flex;gap:12px;margin-bottom:12px;">' +
      '<div style="flex:1;text-align:center;"><div style="font-size:18px;font-weight:700;color:var(--cyan);">' + gen + '</div><div style="font-size:10px;color:var(--text-dim);">Generated</div></div>' +
      '<div style="flex:1;text-align:center;"><div style="font-size:18px;font-weight:700;color:var(--yellow);">' + approved + '</div><div style="font-size:10px;color:var(--text-dim);">Approved</div></div>' +
      '<div style="flex:1;text-align:center;"><div style="font-size:18px;font-weight:700;color:var(--green);">' + executed + '</div><div style="font-size:10px;color:var(--text-dim);">Executed</div></div>' +
      '<div style="flex:1;text-align:center;"><div style="font-size:18px;font-weight:700;color:var(--red);">' + rejected + '</div><div style="font-size:10px;color:var(--text-dim);">Rejected</div></div></div>';

    // Gate breakdown from pipeline
    if(pipeline.gates) {
      var gateHtml = '<div style="font-size:10px;font-weight:700;color:var(--muted);margin-bottom:6px;text-transform:uppercase;">Gate Breakdown</div>';
      Object.entries(pipeline.gates).forEach(function(g) {
        var name = g[0], count = g[1];
        gateHtml += '<div style="display:flex;justify-content:space-between;font-size:11px;padding:3px 0;border-bottom:1px solid var(--border);">' +
          '<span style="color:var(--text-dim);">' + name + '</span><span style="color:var(--yellow);font-weight:600;">' + count + '</span></div>';
      });
      pipeEl.innerHTML += gateHtml;
    }
  } else {
    pipeEl.innerHTML = '<div style="font-size:11px;color:var(--text-dim);text-align:center;">No pipeline data \u2014 waiting for bot cycle</div>';
  }

  // Why no trades - analyze rejections
  if(rejections && Array.isArray(rejections) && rejections.length > 0) {
    var gateCounts = {};
    rejections.forEach(function(r) {
      var gate = r.gate || r.blocked_by || 'unknown';
      gateCounts[gate] = (gateCounts[gate] || 0) + 1;
    });
    var sorted = Object.entries(gateCounts).sort(function(a,b) { return b[1]-a[1]; });
    var topGate = sorted[0];
    var reasons = {
      'chop_filter': 'Market is too choppy \u2014 price is whipsawing without clear direction.',
      'confidence_floor': 'Signal confidence is below the adaptive minimum threshold.',
      'ensemble_veto': 'Not enough strategies agree on direction.',
      'circuit_breaker': 'Circuit breaker tripped due to recent losses.',
      'rr_floor': 'Risk/reward ratio is below minimum (< 1.2:1).',
      'fee_drag': 'Expected profit would be eaten by trading fees.',
      'ev_floor': 'Expected value per dollar risked is too low.',
      'max_positions': 'Maximum number of concurrent positions reached.',
      'correlation': 'Too correlated with existing open positions.'
    };
    whyEl.innerHTML = '<div style="padding:8px 12px;background:var(--bg2);border-radius:6px;margin-bottom:8px;">' +
      '<div style="font-size:12px;font-weight:700;color:var(--yellow);margin-bottom:4px;">Top blocker: ' + topGate[0] + ' (' + topGate[1] + 'x)</div>' +
      '<div style="font-size:11px;color:var(--text-dim);">' + (reasons[topGate[0]] || 'This gate is preventing signals from becoming trades.') + '</div></div>';
    if(sorted.length > 1) {
      whyEl.innerHTML += '<div style="font-size:10px;color:var(--muted);margin-top:6px;">Other blockers: ' +
        sorted.slice(1,4).map(function(g) { return g[0] + ' (' + g[1] + ')'; }).join(', ') + '</div>';
    }
  } else {
    whyEl.innerHTML = '<div style="font-size:11px;color:var(--text-dim);text-align:center;padding:12px;">No rejected signals yet. The bot may be between scan cycles, or conditions are very quiet.</div>';
  }
}

function renderStrategyConsensus(weights) {
  var el = document.getElementById('intel-strategy-consensus');
  if(!el) return;
  if(!weights || typeof weights !== 'object') {
    el.innerHTML = '<div style="font-size:11px;color:var(--text-dim);text-align:center;">No strategy weight data available</div>';
    return;
  }
  var stratNames = { 'regime_trend': 'Regime Trend', 'monte_carlo_zones': 'Monte Carlo Zones', 'multi_tier_quality': 'Multi-TF Quality', 'confidence_scorer': 'Confidence Scorer' };
  var html = '';
  Object.entries(weights).forEach(function(w) {
    var name = w[0], weight = w[1];
    if(typeof weight !== 'number') return;
    var pct = (weight * 100).toFixed(1);
    var barColor = weight > 0.3 ? 'var(--green)' : (weight > 0.15 ? 'var(--yellow)' : 'var(--red)');
    html += '<div style="margin-bottom:10px;">' +
      '<div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:3px;">' +
      '<span style="color:var(--text);">' + (stratNames[name] || name) + '</span>' +
      '<span style="color:' + barColor + ';font-weight:700;">' + pct + '%</span></div>' +
      '<div style="background:var(--bg2);border-radius:3px;height:5px;overflow:hidden;">' +
      '<div style="width:' + pct + '%;height:100%;background:' + barColor + ';border-radius:3px;"></div></div></div>';
  });
  el.innerHTML = html || '<div style="font-size:11px;color:var(--text-dim);">No weight data</div>';
}

function renderRiskIntel(risk) {
  var el = document.getElementById('intel-risk-status');
  if(!el) return;
  if(!risk) {
    el.innerHTML = '<div style="font-size:11px;color:var(--text-dim);text-align:center;">No risk data available</div>';
    return;
  }
  var cbActive = risk.circuit_breaker_active || false;
  var cbColor = cbActive ? 'var(--red)' : 'var(--green)';
  var cbText = cbActive ? 'TRIPPED' : 'OK';
  var consLosses = risk.consecutive_losses || 0;
  var dailyDD = risk.daily_drawdown_pct != null ? risk.daily_drawdown_pct.toFixed(2) : '0.00';
  var ddColor = parseFloat(dailyDD) > 3 ? 'var(--red)' : (parseFloat(dailyDD) > 1 ? 'var(--yellow)' : 'var(--green)');

  el.innerHTML =
    '<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">' +
    '<div style="background:var(--bg2);border-radius:6px;padding:10px;text-align:center;">' +
    '<div style="font-size:10px;color:var(--muted);margin-bottom:4px;">Circuit Breaker</div>' +
    '<div style="font-size:14px;font-weight:700;color:' + cbColor + ';">' + cbText + '</div></div>' +
    '<div style="background:var(--bg2);border-radius:6px;padding:10px;text-align:center;">' +
    '<div style="font-size:10px;color:var(--muted);margin-bottom:4px;">Consec. Losses</div>' +
    '<div style="font-size:14px;font-weight:700;color:' + (consLosses > 2 ? 'var(--red)' : 'var(--text)') + ';">' + consLosses + '</div></div>' +
    '<div style="background:var(--bg2);border-radius:6px;padding:10px;text-align:center;grid-column:1/-1;">' +
    '<div style="font-size:10px;color:var(--muted);margin-bottom:4px;">Daily Drawdown</div>' +
    '<div style="font-size:14px;font-weight:700;color:' + ddColor + ';">' + dailyDD + '%</div></div></div>';
}

function renderAgentIntel(agents) {
  var el = document.getElementById('intel-agent-insights');
  if(!el) return;
  if(!agents || (Array.isArray(agents) && agents.length === 0) || (typeof agents === 'object' && Object.keys(agents).length === 0)) {
    el.innerHTML = '<div class="empty"><div class="empty-icon">&#129302;</div>No agent data available<div class="empty-msg">Agent insights appear when LLM_MULTI_AGENT=true and the bot runs a decision cycle</div></div>';
    return;
  }

  var agentList = Array.isArray(agents) ? agents : (agents.agents || [agents]);
  var agentColors = { regime:'var(--cyan)', trade:'var(--green)', risk:'var(--yellow)', critic:'var(--red)', learning:'var(--purple)', exit:'var(--orange)', scout:'var(--blue)' };
  var agentIcons = { regime:'\uD83C\uDF0D', trade:'\uD83C\uDFAF', risk:'\uD83D\uDEE1', critic:'\uD83E\uDD14', learning:'\uD83D\uDCDA', exit:'\uD83D\uDEAA', scout:'\uD83D\uDD2D' };

  var html = '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;">';
  agentList.forEach(function(a) {
    if(!a) return;
    var role = (a.role || a.agent || 'unknown').toLowerCase();
    var color = agentColors[role] || 'var(--muted)';
    var icon = agentIcons[role] || '\uD83E\uDD16';
    var output = a.output || a.result || a;

    var summary = '';
    if(typeof output === 'string') { summary = output.substring(0, 150); }
    else if(typeof output === 'object') {
      if(output.rg) summary = 'Regime: ' + output.rg + (output.bias ? ' | Bias: ' + output.bias : '') + (output.conf != null ? ' | Conf: ' + (output.conf*100).toFixed(0) + '%' : '');
      else if(output.a) summary = 'Action: ' + output.a + (output.c != null ? ' | Conf: ' + output.c + '%' : '') + (output.thesis ? ' | ' + output.thesis.substring(0, 80) : '');
      else if(output.approved != null) summary = (output.approved ? '\u2705 Approved' : '\u274C Vetoed') + (output.counter_thesis ? ' \u2014 ' + output.counter_thesis.substring(0, 80) : '');
      else if(output.size != null) summary = 'Size: ' + output.size + ' | Lev: ' + (output.lev || '--') + (output.flags && output.flags.length > 0 ? ' | Flags: ' + output.flags.join(', ') : '');
      else summary = JSON.stringify(output).substring(0, 120);
    }

    html += '<div style="background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px;border-left:3px solid ' + color + ';">' +
      '<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">' +
      '<span style="font-size:16px;">' + icon + '</span>' +
      '<span style="font-size:11px;font-weight:700;color:' + color + ';text-transform:uppercase;">' + role + ' Agent</span></div>' +
      '<div style="font-size:11px;color:var(--text-dim);line-height:1.4;">' + summary + '</div></div>';
  });
  html += '</div>';
  el.innerHTML = html;
}

function renderBestOpportunities(rejections) {
  var el = document.getElementById('intel-best-opportunities');
  if(!el) return;
  if(!rejections || !Array.isArray(rejections) || rejections.length === 0) {
    el.innerHTML = '<div style="font-size:11px;color:var(--text-dim);text-align:center;padding:12px;">No rejected signals to analyze. The bot will show its best near-miss opportunities here.</div>';
    return;
  }

  // Sort by confidence descending - highest confidence rejections are the best opportunities
  var sorted = rejections.slice().sort(function(a,b) { return (b.confidence||0) - (a.confidence||0); }).slice(0, 5);
  var html = '<div style="overflow-x:auto;"><table style="width:100%;font-size:11px;"><thead><tr>' +
    '<th style="padding:6px;text-align:left;color:var(--muted);border-bottom:1px solid var(--border);">Symbol</th>' +
    '<th style="padding:6px;text-align:left;color:var(--muted);border-bottom:1px solid var(--border);">Side</th>' +
    '<th style="padding:6px;text-align:left;color:var(--muted);border-bottom:1px solid var(--border);">Confidence</th>' +
    '<th style="padding:6px;text-align:left;color:var(--muted);border-bottom:1px solid var(--border);">Strategy</th>' +
    '<th style="padding:6px;text-align:left;color:var(--muted);border-bottom:1px solid var(--border);">Blocked By</th>' +
    '<th style="padding:6px;text-align:left;color:var(--muted);border-bottom:1px solid var(--border);">Entry</th>' +
    '<th style="padding:6px;text-align:left;color:var(--muted);border-bottom:1px solid var(--border);">SL</th>' +
    '<th style="padding:6px;text-align:left;color:var(--muted);border-bottom:1px solid var(--border);">TP1</th>' +
    '</tr></thead><tbody>';

  sorted.forEach(function(r) {
    var side = (r.side || '').toUpperCase();
    var sideColor = side === 'BUY' ? 'var(--green)' : 'var(--red)';
    var conf = r.confidence || 0;
    var confColor = conf > 70 ? 'var(--green)' : (conf > 50 ? 'var(--yellow)' : 'var(--text-dim)');
    html += '<tr>' +
      '<td style="padding:6px;font-weight:700;color:var(--text);">' + (r.symbol || '--') + '</td>' +
      '<td style="padding:6px;color:' + sideColor + ';font-weight:600;">' + side + '</td>' +
      '<td style="padding:6px;color:' + confColor + ';font-weight:700;">' + conf.toFixed(1) + '</td>' +
      '<td style="padding:6px;color:var(--text-dim);">' + (r.strategy || '--') + '</td>' +
      '<td style="padding:6px;color:var(--yellow);">' + (r.gate || r.blocked_by || '--') + '</td>' +
      '<td style="padding:6px;color:var(--text);">' + (r.entry ? '$' + parseFloat(r.entry).toLocaleString() : '--') + '</td>' +
      '<td style="padding:6px;color:var(--red);">' + (r.sl ? '$' + parseFloat(r.sl).toLocaleString() : '--') + '</td>' +
      '<td style="padding:6px;color:var(--green);">' + (r.tp1 ? '$' + parseFloat(r.tp1).toLocaleString() : '--') + '</td>' +
      '</tr>';
  });

  html += '</tbody></table></div>';
  html += '<div style="font-size:10px;color:var(--text-dim);margin-top:8px;padding:6px;background:var(--bg2);border-radius:4px;">\u26A0 These signals were rejected by safety gates but had the highest confidence. Use your own judgment for manual trades.</div>';
  el.innerHTML = html;
}

/* ═══════════════════════════════════════════════════════════════════ */
/* INITIALIZATION                                                     */
/* ═══════════════════════════════════════════════════════════════════ */
loadAll();
setInterval(loadAll, 30000);
setInterval(refreshPositionsOnly, 10000);

// Load tab data on demand
let learnInitialized = false;
let systemDataLoaded = false;
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if(btn.dataset.tab === 'system' && !systemDataLoaded) { systemDataLoaded=true; setTimeout(() => { loadSystemTab(); loadAgentPipeline(); loadInsights(); }, 100); }
    else if(btn.dataset.tab === 'system') { loadAgentPipeline(); loadInsights(); }
    if(btn.dataset.tab === 'learn' && !learnInitialized) { learnInitialized=true; setTimeout(initLearnTab, 100); }
    if(btn.dataset.tab === 'signals') { loadMissedTrades(); loadMarketIntel(); if(!marketIntelInterval) { marketIntelInterval = setInterval(loadMarketIntel, 30000); } }
    if(btn.dataset.tab === 'trades') { loadOutcomes(); }
    if(btn.dataset.tab === 'analytics') { loadFingerprints(); loadRegimeTimeline(); loadCalibration(); loadPnlCalendar(); }
    if(btn.dataset.tab === 'overview') { loadCorrelation(); }
  });
});

// Initial overview load
setTimeout(loadCorrelation, 2000);

// Welcome toast
setTimeout(() => showToast('Dashboard Ready', 'Press ? for keyboard shortcuts', 'success', 3000), 1500);
</script>
</body>
</html>
"""


# ═══════════════════════════════════════════════════════════════════════════
# HTTP Handler
# ═══════════════════════════════════════════════════════════════════════════

class DashboardHandler(BaseHTTPRequestHandler):
    """Serves the dashboard HTML and JSON API endpoints."""

    bot_instance = None

    def log_message(self, format, *args):  # noqa: A002
        logger.debug("HTTP %s", format % args)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        routes = {
            "/":                 self._serve_dashboard,
            "/dashboard":        self._serve_dashboard,
            "/api/data":         self._serve_api_data,
            "/api/equity":       self._serve_equity_data,
            "/api/positions":    self._serve_positions,
            "/api/health":       self._serve_health,
            "/api/market":       self._serve_market,
            "/api/rejections":   self._serve_rejections,
            "/api/copytrade":    self._serve_copytrade,
            "/api/ohlcv":        self._serve_ohlcv,
            "/api/zones":        self._serve_zones,
            "/api/pipeline":     self._serve_pipeline,
            "/api/risk":         self._serve_risk,
            "/api/weights":      self._serve_weights,
            "/api/performance":  self._serve_performance,
            "/api/signals/active": self._serve_active_signals,
            "/api/gates":        self._serve_gates,
            "/api/missed-trades": self._serve_missed_trades,
            "/api/outcomes":     self._serve_outcomes,
            "/api/fingerprints": self._serve_fingerprints,
            "/api/agents/last":  self._serve_agents_last,
            "/api/regimes/history": self._serve_regimes_history,
            "/api/calibration":  self._serve_calibration,
            "/api/insights":     self._serve_insights,
            "/api/correlation":  self._serve_correlation,
        }
        handler = routes.get(path)
        if handler:
            handler()
        else:
            self.send_error(404, "Not Found")

    def _serve_dashboard(self):
        body = DASHBOARD_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, obj: Any, status: int = 200):
        body = json.dumps(obj, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _parse_query_params(self) -> Dict[str, str]:
        """Parse URL query parameters from self.path into a flat dict."""
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        return {k: v[-1] for k, v in qs.items()}

    # ── /api/data ──────────────────────────────────────────────────────
    def _serve_api_data(self):
        try:
            from data.db import get_dashboard_data
            data = get_dashboard_data()
            data["positions"] = self._get_positions_list()
            data["copytrade"] = self._get_copytrade_data()
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

    # ── /api/market (heatmap data) ─────────────────────────────────────
    def _serve_market(self):
        try:
            self._send_json(self._get_market_data())
        except Exception as exc:
            logger.exception("Error serving /api/market")
            self._send_json({"error": str(exc)}, status=500)

    # ── /api/rejections (missed signals) ───────────────────────────────
    def _serve_rejections(self):
        try:
            self._send_json(self._get_rejections_data())
        except Exception as exc:
            logger.exception("Error serving /api/rejections")
            self._send_json({"error": str(exc)}, status=500)

    # ── /api/copytrade (LLM intelligence) ──────────────────────────────
    def _serve_copytrade(self):
        try:
            self._send_json(self._get_copytrade_data())
        except Exception as exc:
            logger.exception("Error serving /api/copytrade")
            self._send_json({"error": str(exc)}, status=500)

    # ── /api/ohlcv — OHLCV candle data for charts ─────────────────────
    def _serve_ohlcv(self):
        try:
            params = self._parse_query_params()
            symbol = params.get("symbol", "BTC").upper()
            timeframe = params.get("timeframe", "1h")

            from trading_config import DEFAULT_SYMBOLS
            sym_cfg = DEFAULT_SYMBOLS.get(symbol)
            if sym_cfg is None:
                self._send_json(
                    {"error": f"Unknown symbol: {symbol}",
                     "available": list(DEFAULT_SYMBOLS.keys())},
                    status=400,
                )
                return

            from data.fetcher import DataFetcher
            fetcher = DataFetcher(cache_ttl=30)
            df = fetcher.fetch_ohlcv(symbol, sym_cfg.coingecko_id, timeframe)

            if df is None or df.empty:
                self._send_json([])
                return

            candles = []
            for _, row in df.iterrows():
                ts = row.get("time")
                if hasattr(ts, "isoformat"):
                    ts = ts.isoformat()
                candles.append({
                    "time": ts,
                    "open": round(float(row["open"]), 6),
                    "high": round(float(row["high"]), 6),
                    "low": round(float(row["low"]), 6),
                    "close": round(float(row["close"]), 6),
                    "volume": round(float(row.get("volume", 0)), 2),
                })

            self._send_json(candles)
        except Exception as exc:
            logger.exception("Error serving /api/ohlcv")
            self._send_json({"error": str(exc)}, status=500)

    # ── /api/zones — Monte Carlo S/R zones + signal levels ─────────────
    def _serve_zones(self):
        try:
            params = self._parse_query_params()
            symbol = params.get("symbol", "BTC").upper()

            from data.db import get_signals_today

            signals_raw = get_signals_today()
            sym_signals = [
                s for s in (signals_raw or [])
                if s.get("symbol", "").upper() == symbol
            ]

            zones = {}
            regime = "unknown"
            for sig in reversed(sym_signals):
                meta = sig.get("metadata")
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                if not isinstance(meta, dict):
                    continue
                zone_data = meta.get("zones", meta)
                if zone_data.get("deep_buy") is not None:
                    zones = {
                        "deep_buy": zone_data.get("deep_buy"),
                        "regular_buy": zone_data.get("regular_buy"),
                        "regular_sell": zone_data.get("regular_sell"),
                        "safe_sell": zone_data.get("safe_sell"),
                        "sma20": zone_data.get("sma20"),
                    }
                    break
                r = meta.get("regime") or meta.get("market_regime")
                if r:
                    regime = r

            if regime == "unknown":
                for sig in reversed(sym_signals):
                    meta = sig.get("metadata")
                    if isinstance(meta, str):
                        try:
                            meta = json.loads(meta)
                        except Exception:
                            meta = {}
                    if isinstance(meta, dict):
                        r = meta.get("regime") or meta.get("market_regime")
                        if r:
                            regime = r
                            break

            signal_overlays = []
            for sig in sym_signals[-20:]:
                signal_overlays.append({
                    "side": sig.get("side"),
                    "entry": sig.get("entry"),
                    "sl": sig.get("sl"),
                    "tp1": sig.get("tp1"),
                    "tp2": sig.get("tp2"),
                    "confidence": sig.get("confidence"),
                    "strategy": sig.get("strategy"),
                    "timestamp": sig.get("timestamp"),
                })

            self._send_json({
                "symbol": symbol,
                "zones": zones,
                "signals": signal_overlays,
                "regime": regime,
            })
        except Exception as exc:
            logger.exception("Error serving /api/zones")
            self._send_json({"error": str(exc)}, status=500)

    # ── /api/pipeline — Signal pipeline funnel stats ───────────────────
    def _serve_pipeline(self):
        try:
            from data.db import get_signals_today, get_rejection_summary

            signals = get_signals_today() or []
            total_signals = len(signals)
            traded_count = sum(1 for s in signals if s.get("traded"))

            try:
                rejection_summary = get_rejection_summary(hours=24)
            except Exception:
                rejection_summary = {}
            by_gate = {}
            total_rejected = 0
            for gate, info in (rejection_summary or {}).items():
                count = info.get("count", 0) if isinstance(info, dict) else int(info)
                by_gate[gate] = count
                total_rejected += count

            self._send_json({
                "total_signals": total_signals,
                "total_rejected": total_rejected,
                "by_gate": by_gate,
                "passed": traded_count,
                "executed": traded_count,
            })
        except Exception as exc:
            logger.exception("Error serving /api/pipeline")
            self._send_json({"error": str(exc)}, status=500)

    # ── /api/risk — Circuit breaker & risk state ───────────────────────
    def _serve_risk(self):
        try:
            bot = DashboardHandler.bot_instance
            risk_state = None

            if bot is not None:
                rm = getattr(bot, "risk_manager", None)
                if rm is None:
                    engine = getattr(bot, "engine", None) or getattr(bot, "trading_engine", None)
                    if engine:
                        rm = getattr(engine, "risk_manager", None)
                if rm is not None:
                    cb = getattr(rm, "circuit_breaker", None)
                    try:
                        cb_status = cb.get_status() if cb and hasattr(cb, "get_status") else {}
                    except Exception:
                        cb_status = {}
                    equity = getattr(rm, "equity", 0)
                    peak = cb_status.get("peak_equity", 0)
                    risk_state = {
                        "daily_pnl": cb_status.get("daily_pnl", 0),
                        "daily_limit": abs(equity * getattr(cb, "daily_loss_limit_pct", 0.05)) if cb else 50,
                        "consecutive_losses": cb_status.get("consecutive_losses", 0),
                        "max_consecutive": getattr(cb, "max_consecutive_losses", 5) if cb else 5,
                        "cb_tripped": cb_status.get("tripped", False),
                        "drawdown_pct": round(((peak - equity) / peak) * 100, 2) if peak > 0 else 0,
                        "source": "live",
                    }

            if risk_state is None:
                risk_state = {
                    "daily_pnl": 0, "daily_limit": 50,
                    "consecutive_losses": 0, "max_consecutive": 5,
                    "cb_tripped": False, "drawdown_pct": 0,
                    "source": "unavailable",
                }

            self._send_json(risk_state)
        except Exception as exc:
            logger.exception("Error serving /api/risk")
            self._send_json({"error": str(exc)}, status=500)

    # ── /api/weights — Current strategy weights ────────────────────────
    def _serve_weights(self):
        try:
            from data.strategy_weights import StrategyWeightManager
            mgr = StrategyWeightManager()
            weights = mgr.get_all_weights()
            self._send_json(weights)
        except Exception as exc:
            logger.exception("Error serving /api/weights")
            self._send_json({"error": str(exc)}, status=500)

    # ── /api/performance — Daily performance history ───────────────────
    def _serve_performance(self):
        try:
            from data.db import get_performance_history
            params = self._parse_query_params()
            days = int(params.get("days", "30"))
            days = max(1, min(days, 365))
            history = get_performance_history(days)
            result = []
            for row in (history or []):
                result.append({
                    "date": row.get("date"),
                    "trades": row.get("trades", 0),
                    "wins": row.get("wins", 0),
                    "pnl": row.get("net_pnl", row.get("pnl", 0)),
                    "fees": row.get("total_fees", 0),
                })
            self._send_json(result)
        except Exception as exc:
            logger.exception("Error serving /api/performance")
            self._send_json({"error": str(exc)}, status=500)

    # ── /api/signals/active — Current active signals ───────────────────
    def _serve_active_signals(self):
        try:
            from data.db import get_signals_today
            signals = get_signals_today() or []
            by_symbol: Dict[str, list] = {}
            for sig in signals:
                sym = sig.get("symbol", "???")
                by_symbol.setdefault(sym, []).append(sig)

            result = []
            for sig in signals:
                sym = sig.get("symbol", "???")
                sym_signals = by_symbol.get(sym, [])
                side = (sig.get("side") or "").upper()
                agree_count = sum(
                    1 for s in sym_signals
                    if (s.get("side") or "").upper() == side
                    and s.get("strategy") != sig.get("strategy")
                )
                meta = sig.get("metadata")
                if isinstance(meta, str):
                    try: meta = json.loads(meta)
                    except Exception: meta = {}
                regime = meta.get("regime", "unknown") if isinstance(meta, dict) else "unknown"

                result.append({
                    "timestamp": sig.get("timestamp"),
                    "symbol": sym, "strategy": sig.get("strategy"),
                    "side": sig.get("side"), "confidence": sig.get("confidence"),
                    "entry": sig.get("entry"), "sl": sig.get("sl"),
                    "tp1": sig.get("tp1"), "tp2": sig.get("tp2"),
                    "regime": regime,
                    "strategies_agreeing": agree_count + 1,
                    "signal_context": meta.get("signal_context", "") if isinstance(meta, dict) else "",
                })
            self._send_json(result)
        except Exception as exc:
            logger.exception("Error serving /api/signals/active")
            self._send_json({"error": str(exc)}, status=500)

    # ── /api/gates — Go-live gate status ───────────────────────────────
    def _serve_gates(self):
        try:
            # Try to get gate status from bot instance
            bot = DashboardHandler.bot_instance
            gates = {}
            if bot is not None:
                gate_eval = getattr(bot, "gate_evaluator", None) or getattr(bot, "go_live_gates", None)
                if gate_eval and hasattr(gate_eval, "evaluate"):
                    try:
                        gates = gate_eval.evaluate()
                    except Exception:
                        pass
            if not gates:
                gates = {
                    "walk_forward": {"passed": False, "current": "N/A", "threshold": "N/A"},
                    "net_pnl": {"passed": False, "current": "N/A", "threshold": "> $0"},
                    "max_drawdown": {"passed": False, "current": "N/A", "threshold": "< 15%"},
                    "factor_ics": {"passed": False, "current": "N/A", "threshold": "> 0.02"},
                    "sharpe_ratio": {"passed": False, "current": "N/A", "threshold": "> 0.5"},
                }
            self._send_json(gates)
        except Exception as exc:
            logger.exception("Error serving /api/gates")
            self._send_json({"error": str(exc)}, status=500)

    # ── /api/missed-trades — Counterfactual missed trade analysis ─────
    def _serve_missed_trades(self):
        try:
            from data.db import get_signal_rejections
            rejections = get_signal_rejections(hours=168)  # 7 days
            trades = []
            for r in (rejections or [])[:100]:
                meta = r.get("metadata")
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                if not isinstance(meta, dict):
                    meta = {}
                cf_pnl = meta.get("counterfactual_pnl") or meta.get("cf_pnl") or meta.get("missed_pnl")
                would_have_won = meta.get("would_have_won")
                if would_have_won is None and cf_pnl is not None:
                    would_have_won = float(cf_pnl) > 0
                trades.append({
                    "timestamp": r.get("timestamp"),
                    "symbol": r.get("symbol"),
                    "side": r.get("side"),
                    "confidence": r.get("confidence"),
                    "gate": r.get("gate"),
                    "would_have_won": bool(would_have_won) if would_have_won is not None else None,
                    "missed_pnl": float(cf_pnl) if cf_pnl is not None else 0,
                })
            self._send_json({"trades": trades})
        except Exception as exc:
            logger.exception("Error serving /api/missed-trades")
            self._send_json({"trades": []})

    # ── /api/outcomes — Trade outcome type breakdown ───────────────────
    def _serve_outcomes(self):
        try:
            from data.db import get_recent_trades
            trades = get_recent_trades(days=30) if hasattr(__import__('data.db', fromlist=['get_recent_trades']), 'get_recent_trades') else []
        except Exception:
            trades = []

        try:
            if not trades:
                from data.db import get_dashboard_data
                data = get_dashboard_data()
                trades = data.get("recent_trades", [])
        except Exception:
            trades = []

        outcomes = {}
        for t in (trades or []):
            action = (t.get("action") or t.get("exit_type") or "OTHER").upper()
            # Classify into outcome types
            pnl = t.get("pnl") or 0
            if action in ("TP1", "TP1_HIT"):
                otype = "TP1_ONLY"
            elif action in ("TP2", "TP2_HIT"):
                otype = "CLEAN_WIN"
            elif action in ("TRAILING_STOP", "TRAIL"):
                otype = "TRAILING_WIN" if pnl > 0 else "TRAILING_LOSS"
            elif action in ("SL", "STOP_LOSS", "SL_HIT"):
                otype = "CLEAN_LOSS"
            elif action in ("EARLY_EXIT", "EMERGENCY"):
                otype = "EARLY_EXIT_SAVE" if pnl > 0 else "EARLY_EXIT_LOSS"
            elif pnl > 0:
                otype = "CLEAN_WIN"
            elif pnl < 0:
                otype = "CLEAN_LOSS"
            else:
                otype = "OTHER"

            if otype not in outcomes:
                outcomes[otype] = {"count": 0, "total_pnl": 0, "avg_pnl": 0}
            outcomes[otype]["count"] += 1
            outcomes[otype]["total_pnl"] += pnl

        for otype, data in outcomes.items():
            data["avg_pnl"] = data["total_pnl"] / data["count"] if data["count"] > 0 else 0

        self._send_json({"outcomes": outcomes})

    # ── /api/fingerprints — Strategy performance matrix ────────────────
    def _serve_fingerprints(self):
        try:
            # Try deep memory first
            by_symbol = {}
            by_regime = {}
            try:
                fp_path = os.path.join(_BOT_DIR, "data", "llm", "deep_memory", "strategy_fingerprints.json")
                if os.path.exists(fp_path):
                    with open(fp_path, "r") as f:
                        fp_data = json.load(f)
                    # Parse fingerprint data into heatmap format
                    for strat, info in (fp_data or {}).items():
                        if isinstance(info, dict):
                            for sym, stats in info.get("by_symbol", {}).items():
                                key = f"{strat}|{sym}"
                                by_symbol[key] = {
                                    "win_rate": stats.get("win_rate", 0),
                                    "trades": stats.get("trades", 0),
                                    "pnl": stats.get("pnl", 0),
                                }
                            for reg, stats in info.get("by_regime", {}).items():
                                key = f"{strat}|{reg}"
                                by_regime[key] = {
                                    "win_rate": stats.get("win_rate", 0),
                                    "trades": stats.get("trades", 0),
                                    "pnl": stats.get("pnl", 0),
                                }
            except Exception:
                pass

            # Fallback: build from performance_daily table
            if not by_symbol:
                try:
                    from data.db import get_performance_history
                    history = get_performance_history(30) or []
                    for row in history:
                        strat = row.get("strategy", "unknown")
                        sym = row.get("symbol", "ALL")
                        trades = row.get("trades", 0)
                        wins = row.get("wins", 0)
                        pnl = row.get("net_pnl", row.get("pnl", 0))
                        if trades > 0 and strat and sym:
                            key = f"{strat}|{sym}"
                            if key not in by_symbol:
                                by_symbol[key] = {"win_rate": 0, "trades": 0, "pnl": 0}
                            by_symbol[key]["trades"] += trades
                            by_symbol[key]["pnl"] += pnl
                            total_t = by_symbol[key]["trades"]
                            by_symbol[key]["win_rate"] = (by_symbol[key].get("_wins", 0) + wins) / total_t if total_t > 0 else 0
                            by_symbol[key]["_wins"] = by_symbol[key].get("_wins", 0) + wins
                except Exception:
                    pass

            self._send_json({"by_symbol": by_symbol, "by_regime": by_regime})
        except Exception as exc:
            logger.exception("Error serving /api/fingerprints")
            self._send_json({"by_symbol": {}, "by_regime": {}})

    # ── /api/agents/last — Last agent pipeline decision ────────────────
    def _serve_agents_last(self):
        try:
            bot = DashboardHandler.bot_instance
            active = False
            agents = []
            timestamp = None

            if bot is not None:
                coord = None
                for attr in ("agent_coordinator", "coordinator", "llm_engine"):
                    coord = getattr(bot, attr, None)
                    if coord:
                        break
                if coord is None:
                    engine = getattr(bot, "engine", None) or getattr(bot, "trading_engine", None)
                    if engine:
                        coord = getattr(engine, "agent_coordinator", None)

                if coord and hasattr(coord, "last_pipeline_results"):
                    active = True
                    results = coord.last_pipeline_results or {}
                    for role, output in results.items():
                        if isinstance(output, dict):
                            agents.append({
                                "agent": role,
                                "model": output.get("model", ""),
                                "action": output.get("action") or output.get("decision", ""),
                                "confidence": output.get("confidence"),
                                "reasoning": output.get("reasoning", "")[:200],
                            })
                            if output.get("timestamp"):
                                timestamp = output["timestamp"]

            if not active:
                active = os.getenv("LLM_MULTI_AGENT", "").lower() in ("true", "1", "yes")

            # Fallback: read from decisions.jsonl
            if not agents:
                try:
                    decisions_path = os.path.join(_BOT_DIR, "data", "llm", "decisions.jsonl")
                    if os.path.exists(decisions_path):
                        with open(decisions_path, "r") as f:
                            lines = f.readlines()
                        for line in lines[-20:]:
                            try:
                                dec = json.loads(line.strip())
                                agent = dec.get("agent") or dec.get("source")
                                if agent:
                                    agents.append({
                                        "agent": agent,
                                        "model": dec.get("model", ""),
                                        "action": dec.get("action") or dec.get("decision", ""),
                                        "confidence": dec.get("confidence"),
                                        "reasoning": (dec.get("reasoning") or dec.get("summary") or "")[:200],
                                    })
                                    timestamp = dec.get("timestamp") or timestamp
                            except Exception:
                                pass
                except Exception:
                    pass

            self._send_json({"active": active, "agents": agents[-6:], "timestamp": timestamp})
        except Exception as exc:
            logger.exception("Error serving /api/agents/last")
            self._send_json({"active": False, "agents": [], "timestamp": None})

    # ── /api/regimes/history — Regime transition timeline ──────────────
    def _serve_regimes_history(self):
        try:
            periods = []
            transitions = {}

            # Try deep memory regime history
            try:
                rh_path = os.path.join(_BOT_DIR, "data", "llm", "deep_memory", "regime_history.json")
                if os.path.exists(rh_path):
                    with open(rh_path, "r") as f:
                        rh_data = json.load(f)
                    if isinstance(rh_data, dict):
                        periods = rh_data.get("periods", [])
                        transitions = rh_data.get("transitions", {})
                    elif isinstance(rh_data, list):
                        periods = rh_data
            except Exception:
                pass

            # Fallback: derive from market data signals
            if not periods:
                try:
                    from data.db import get_signals_today
                    signals = get_signals_today() or []
                    last_regime = None
                    for sig in signals:
                        meta = sig.get("metadata")
                        if isinstance(meta, str):
                            try:
                                meta = json.loads(meta)
                            except Exception:
                                continue
                        if isinstance(meta, dict):
                            regime = meta.get("regime") or meta.get("market_regime")
                            if regime and regime != last_regime:
                                if last_regime:
                                    key = f"{last_regime}->{regime}"
                                    transitions[key] = transitions.get(key, 0) + 1
                                periods.append({"regime": regime, "duration_h": 1, "start": sig.get("timestamp")})
                                last_regime = regime
                            elif regime == last_regime and periods:
                                periods[-1]["duration_h"] = periods[-1].get("duration_h", 0) + 1
                except Exception:
                    pass

            self._send_json({"periods": periods[-50:], "transitions": transitions})
        except Exception as exc:
            logger.exception("Error serving /api/regimes/history")
            self._send_json({"periods": [], "transitions": {}})

    # ── /api/calibration — Confidence calibration data ─────────────────
    def _serve_calibration(self):
        try:
            buckets = []
            brier_score = None

            # Try signal quality scorer
            try:
                sq_path = os.path.join(_BOT_DIR, "data", "feedback", "signal_quality.json")
                if os.path.exists(sq_path):
                    with open(sq_path, "r") as f:
                        sq_data = json.load(f)
                    cal = sq_data.get("calibration", {})
                    if cal:
                        for bucket_name, stats in sorted(cal.items()):
                            predicted = stats.get("predicted", 0)
                            actual = stats.get("actual_win_rate", 0)
                            n = stats.get("trades", 0)
                            buckets.append({"predicted": predicted, "actual": actual * 100 if actual <= 1 else actual, "trades": n})
            except Exception:
                pass

            # Fallback: compute from signal outcomes in DB
            if not buckets:
                try:
                    from data.db import get_dashboard_data
                    data = get_dashboard_data()
                    trades = data.get("recent_trades", [])
                    # Bucket by confidence
                    conf_buckets = {}
                    for t in trades:
                        conf = t.get("confidence")
                        if conf is None:
                            continue
                        bucket = int(conf // 20) * 20
                        if bucket not in conf_buckets:
                            conf_buckets[bucket] = {"wins": 0, "total": 0}
                        conf_buckets[bucket]["total"] += 1
                        if (t.get("pnl") or 0) > 0:
                            conf_buckets[bucket]["wins"] += 1
                    for bucket in sorted(conf_buckets.keys()):
                        stats = conf_buckets[bucket]
                        actual_wr = (stats["wins"] / stats["total"] * 100) if stats["total"] > 0 else 0
                        buckets.append({"predicted": bucket + 10, "actual": actual_wr, "trades": stats["total"]})
                except Exception:
                    pass

            self._send_json({"buckets": buckets, "brier_score": brier_score})
        except Exception as exc:
            logger.exception("Error serving /api/calibration")
            self._send_json({"buckets": [], "brier_score": None})

    # ── /api/insights — LLM insight journal ────────────────────────────
    def _serve_insights(self):
        try:
            insights = []
            try:
                ij_path = os.path.join(_BOT_DIR, "data", "llm", "deep_memory", "insight_journal.json")
                if os.path.exists(ij_path):
                    with open(ij_path, "r") as f:
                        ij_data = json.load(f)
                    if isinstance(ij_data, list):
                        for entry in ij_data:
                            insights.append({
                                "text": entry.get("text") or entry.get("insight") or "",
                                "category": entry.get("category", "meta"),
                                "confidence": entry.get("confidence", 50),
                                "validation_status": entry.get("validation_status") or entry.get("status", "pending"),
                                "timestamp": entry.get("timestamp"),
                            })
                    elif isinstance(ij_data, dict):
                        for cat, entries in ij_data.items():
                            if isinstance(entries, list):
                                for entry in entries:
                                    insights.append({
                                        "text": entry.get("text") or entry.get("insight") or str(entry),
                                        "category": cat,
                                        "confidence": entry.get("confidence", 50) if isinstance(entry, dict) else 50,
                                        "validation_status": entry.get("validation_status", "pending") if isinstance(entry, dict) else "pending",
                                        "timestamp": entry.get("timestamp") if isinstance(entry, dict) else None,
                                    })
            except Exception:
                pass

            # Sort by confidence descending
            insights.sort(key=lambda x: -(x.get("confidence") or 0))
            self._send_json({"insights": insights[:100]})
        except Exception as exc:
            logger.exception("Error serving /api/insights")
            self._send_json({"insights": []})

    # ── /api/correlation — Portfolio correlation matrix ─────────────────
    def _serve_correlation(self):
        try:
            symbols = []
            matrix = {}
            div_score = None

            # Try correlation cache
            try:
                cc_path = os.path.join(_BOT_DIR, "data", "portfolio_risk", "correlation_cache.json")
                if os.path.exists(cc_path):
                    with open(cc_path, "r") as f:
                        cc_data = json.load(f)
                    if isinstance(cc_data, dict):
                        symbols = cc_data.get("symbols", [])
                        raw_matrix = cc_data.get("matrix", cc_data.get("correlations", {}))
                        if isinstance(raw_matrix, dict):
                            matrix = raw_matrix
                        elif isinstance(raw_matrix, list) and symbols:
                            for i, row in enumerate(raw_matrix):
                                if isinstance(row, list):
                                    for j, val in enumerate(row):
                                        if i < len(symbols) and j < len(symbols):
                                            matrix[f"{symbols[i]}_{symbols[j]}"] = val
            except Exception:
                pass

            # Fallback: use watched symbols with placeholder
            if not symbols:
                try:
                    from trading_config import DEFAULT_SYMBOLS
                    symbols = list(DEFAULT_SYMBOLS.keys())[:8]
                except Exception:
                    symbols = []

            # Calculate diversification score from matrix
            if matrix and len(symbols) > 1:
                corr_sum = 0
                count = 0
                for i, s1 in enumerate(symbols):
                    for j, s2 in enumerate(symbols):
                        if i < j:
                            val = matrix.get(f"{s1}_{s2}", 0)
                            corr_sum += abs(val)
                            count += 1
                if count > 0:
                    avg_corr = corr_sum / count
                    div_score = max(0, min(100, (1 - avg_corr) * 100))

            self._send_json({"symbols": symbols, "matrix": matrix, "diversification_score": div_score})
        except Exception as exc:
            logger.exception("Error serving /api/correlation")
            self._send_json({"symbols": [], "matrix": {}, "diversification_score": None})

    # ═══════════════════════════════════════════════════════════════════
    # Data extraction helpers (all READ-ONLY)
    # ═══════════════════════════════════════════════════════════════════

    def _get_positions_list(self) -> list:
        """Pull open positions from the bot instance with enhanced fields."""
        bot = DashboardHandler.bot_instance
        if bot is None:
            return []

        positions_raw = None

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

        result = []
        now = time.time()

        if isinstance(positions_raw, dict):
            items = list(positions_raw.values()) if positions_raw else []
        elif isinstance(positions_raw, (list, tuple)):
            items = positions_raw
        else:
            return []

        for pos in items:
            try:
                result.append(self._extract_position(pos, now))
            except Exception:
                pass

        return result

    def _extract_position(self, pos, now: float) -> dict:
        """Extract position fields from a dict or object."""
        if isinstance(pos, dict):
            g = pos.get
        else:
            g = lambda k, d=None: getattr(pos, k, d)

        entry_ts = g("open_time") or g("entry_time") or g("timestamp")
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

        entry_price = g("entry_price") or g("entry") or 0
        current_price = g("current_price") or g("mark_price") or 0
        unrealized_pnl = g("unrealized_pnl") or g("pnl") or 0

        pnl_pct = 0
        if entry_price and entry_price > 0 and unrealized_pnl:
            qty = g("qty") or g("quantity") or g("size") or 1
            if qty:
                pnl_pct = (unrealized_pnl / (entry_price * abs(qty))) * 100

        tp = g("trade_profile")
        if tp and hasattr(tp, "name"):
            tp = tp.name
        elif tp and hasattr(tp, "value"):
            tp = tp.value

        return {
            "symbol":          g("symbol", "???"),
            "side":            g("side", "LONG"),
            "entry_price":     entry_price,
            "current_price":   current_price,
            "sl":              g("sl") or g("stop_loss") or 0,
            "tp1":             g("tp1") or g("take_profit_1") or 0,
            "tp2":             g("tp2") or g("take_profit_2") or 0,
            "unrealized_pnl":  unrealized_pnl,
            "pnl_pct":         pnl_pct,
            "leverage":        g("leverage", 1),
            "state":           g("state", "OPEN"),
            "hold_time_s":     hold_time,
            "trade_profile":   str(tp) if tp else None,
            "notes":           g("notes"),
            "confidence":      g("confidence"),
        }

    def _get_market_data(self) -> list:
        """Build market heatmap data from signals and regime detection."""
        result = []
        danger_by_regime = {
            "panic": 90, "high_volatility": 70, "news_dislocation": 60,
            "low_liquidity": 50, "range": 30, "consolidation": 20,
            "trend": 10, "unknown": 0,
        }

        try:
            from data.db import get_signals_today, get_signal_performance
        except ImportError:
            return result

        try:
            signals = get_signals_today()
        except Exception:
            signals = []

        if not signals:
            return result

        by_symbol: Dict[str, list] = {}
        for sig in signals:
            sym = sig.get("symbol", "???")
            by_symbol.setdefault(sym, []).append(sig)

        perf_by_sym = {}
        try:
            sp = get_signal_performance(days=7)
            perf_by_sym = sp.get("by_symbol", {}) if isinstance(sp, dict) else {}
        except Exception:
            pass

        for sym, sigs in by_symbol.items():
            regime = "unknown"
            for sig in reversed(sigs):
                meta = sig.get("metadata")
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                if isinstance(meta, dict):
                    r = meta.get("regime") or meta.get("market_regime")
                    if r:
                        regime = r
                        break

            buys = sum(1 for s in sigs if (s.get("side") or "").upper() in ("BUY", "LONG"))
            sells = sum(1 for s in sigs if (s.get("side") or "").upper() in ("SELL", "SHORT"))
            bias = "bullish" if buys > sells else ("bearish" if sells > buys else "neutral")

            confs = [s.get("confidence", 0) for s in sigs if s.get("confidence")]
            avg_conf = sum(confs) / len(confs) if confs else 0

            danger = danger_by_regime.get(regime.lower(), 0)
            sym_perf = perf_by_sym.get(sym, {})
            recent_pnl = sym_perf.get("pnl")
            last_time = sigs[-1].get("timestamp") if sigs else None

            result.append({
                "symbol": sym, "regime": regime, "signal_bias": bias,
                "confidence": round(avg_conf, 1), "danger_level": danger,
                "recent_pnl": recent_pnl, "signal_count": len(sigs),
                "last_signal_time": last_time,
            })

        result.sort(key=lambda x: (-x["danger_level"], -x["signal_count"]))
        return result

    def _get_rejections_data(self) -> list:
        """Get recent rejected signals for the What If section."""
        try:
            from data.db import get_signal_rejections
        except ImportError:
            return []

        try:
            rejections = get_signal_rejections(hours=24)
        except Exception:
            return []

        result = []
        for r in (rejections or [])[:50]:
            meta = r.get("metadata")
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {}
            if not isinstance(meta, dict):
                meta = {}

            result.append({
                "timestamp":          r.get("timestamp"),
                "symbol":             r.get("symbol"),
                "side":               r.get("side"),
                "confidence":         r.get("confidence"),
                "strategy":           r.get("strategy"),
                "gate":               r.get("gate"),
                "reason":             r.get("reason"),
                "counterfactual_pnl": meta.get("counterfactual_pnl") or meta.get("cf_pnl"),
            })

        return result

    def _get_copytrade_data(self) -> dict:
        """Get LLM copy-trade intelligence (placeholder when inactive)."""
        bot = DashboardHandler.bot_instance

        llm_active = False
        if bot is not None:
            for attr in ("llm_engine", "decision_engine", "agent_coordinator"):
                if getattr(bot, attr, None) is not None:
                    llm_active = True
                    break
            if not llm_active:
                llm_active = os.getenv("LLM_MULTI_AGENT", "").lower() in ("true", "1", "yes")

        if not llm_active:
            return {"active": False, "insights": [], "recommendation": "LLM system offline"}

        insights = []
        recommendation = ""
        decisions_path = os.path.join(_BOT_DIR, "data", "llm", "decisions.jsonl")
        try:
            if os.path.exists(decisions_path):
                with open(decisions_path, "r") as f:
                    lines = f.readlines()
                for line in lines[-10:]:
                    try:
                        dec = json.loads(line.strip())
                        agent = dec.get("agent") or dec.get("source") or "system"
                        summary = dec.get("summary") or dec.get("reasoning") or dec.get("decision", "")
                        if summary:
                            insights.append({
                                "agent": agent,
                                "summary": str(summary)[:300],
                                "timestamp": dec.get("timestamp"),
                            })
                    except Exception:
                        pass
                if insights:
                    recommendation = insights[-1].get("summary", "")
        except Exception:
            pass

        return {"active": llm_active, "insights": insights[-5:], "recommendation": recommendation}


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
        DashboardHandler.bot_instance = bot_instance
        self.server = HTTPServer((self.host, self.port), DashboardHandler)
        self._thread = threading.Thread(
            target=self.server.serve_forever, name="dashboard-http", daemon=True,
        )
        self._thread.start()
        logger.info("Dashboard running at http://%s:%s",
                     self.host if self.host != "0.0.0.0" else "localhost", self.port)

    def stop(self):
        if self.server:
            self.server.shutdown()
            logger.info("Dashboard server stopped.")

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


_singleton: Optional[DashboardServer] = None
_singleton_lock = threading.Lock()


def get_dashboard_server(host: str = "0.0.0.0", port: int = 8080) -> DashboardServer:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = DashboardServer(host=host, port=port)
        return _singleton


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        env_path = Path(_BOT_DIR).parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
        else:
            load_dotenv()
    except ImportError:
        pass

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s  %(message)s")

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
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        srv.stop()
