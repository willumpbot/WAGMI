"""
Lightweight web dashboard for the NunuIRL trading bot.

Uses Python's built-in http.server (zero external dependencies).
Serves a single-page HTML dashboard with auto-refreshing data via
fetch() calls to JSON API endpoints backed by the SQLite data layer.

Features:
  - Live positions hero section (10s refresh)
  - Market awareness heatmap (regime, bias, danger zones)
  - Rejected signals / "What If" section
  - Copy Trade Intelligence (LLM insights when active)
  - Equity curve, strategy breakdown, signal performance
  - Health monitoring

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
from typing import Any, Dict, List, Optional
from pathlib import Path

_BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)

logger = logging.getLogger("bot.dashboard")
_START_TIME = time.time()


# ═══════════════════════════════════════════════════════════════════════════
# HTML Dashboard (inline single-page app)
# ═══════════════════════════════════════════════════════════════════════════

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<title>NunuIRL Trading Dashboard</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
:root{--bg:#080810;--bg2:#0d0d18;--card:#111120;--border:#1c1c30;--text:#d8d8e8;--muted:#5e5e80;--green:#00e6a0;--red:#ff4466;--blue:#4488ff;--yellow:#ffc444;--purple:#a366ff;--cyan:#22d3ee;--radius:8px}
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
body{font-family:'SF Mono','Cascadia Code','Fira Code',Consolas,monospace;background:var(--bg);color:var(--text);padding:20px;font-size:13px;min-height:100vh;line-height:1.5}
a{color:var(--blue);text-decoration:none}
.container{max-width:1680px;margin:0 auto}
.header{display:flex;justify-content:space-between;align-items:center;margin-bottom:24px;padding-bottom:16px;border-bottom:1px solid var(--border)}
.header h1{font-size:20px;font-weight:700;letter-spacing:-0.5px;background:linear-gradient(135deg,var(--blue),var(--purple));-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.header .status{display:flex;gap:20px;align-items:center;font-size:12px;color:var(--muted)}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:5px;vertical-align:middle}
.dot-green{background:var(--green);box-shadow:0 0 6px var(--green)}
.dot-yellow{background:var(--yellow);box-shadow:0 0 6px var(--yellow)}
.dot-red{background:var(--red);box-shadow:0 0 6px var(--red)}
.refresh-pulse{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--blue);margin-right:6px;animation:pulse 1.5s ease infinite}
@keyframes pulse{0%,100%{opacity:.3;transform:scale(.8)}50%{opacity:1;transform:scale(1.2)}}
.grid-5{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-bottom:20px}
.grid-2{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}
.grid-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:20px}
.full-width{margin-bottom:20px}
.card{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px;position:relative;overflow:hidden}
.card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--border),transparent)}
.card h3{font-size:10px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:10px;font-weight:600}
.card-hero{background:var(--card);border:1px solid var(--border);border-radius:var(--radius);padding:20px;box-shadow:0 0 40px rgba(0,230,160,0.03)}
.card-hero h3{font-size:13px;text-transform:uppercase;letter-spacing:.5px;color:var(--cyan);margin-bottom:12px;font-weight:700}
.metric{font-size:26px;font-weight:700;letter-spacing:-.5px;line-height:1.1}
.metric-sub{font-size:11px;color:var(--muted);margin-top:4px}
.green{color:var(--green)}.red{color:var(--red)}.blue{color:var(--blue)}.yellow{color:var(--yellow)}.purple{color:var(--purple)}.cyan{color:var(--cyan)}
.bar-track{width:100%;height:5px;background:var(--border);border-radius:3px;overflow:hidden;margin-top:10px}
.bar-fill{height:100%;border-radius:3px;transition:width .6s ease}
table{width:100%;border-collapse:collapse}
th{text-align:left;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);border-bottom:1px solid var(--border);font-weight:600;white-space:nowrap}
td{padding:7px 10px;border-bottom:1px solid rgba(28,28,48,.5);font-size:12px;white-space:nowrap}
tr:hover td{background:rgba(255,255,255,.015)}
.scroll-y{max-height:400px;overflow-y:auto}
.scroll-y::-webkit-scrollbar{width:4px}
.scroll-y::-webkit-scrollbar-track{background:transparent}
.scroll-y::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
.pill{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;letter-spacing:.3px}
.pill-long{background:rgba(0,230,160,.12);color:var(--green)}
.pill-short{background:rgba(255,68,102,.12);color:var(--red)}
.pill-win{background:rgba(0,230,160,.12);color:var(--green)}
.pill-loss{background:rgba(255,68,102,.12);color:var(--red)}
.pill-action{background:rgba(68,136,255,.12);color:var(--blue);font-size:10px;font-weight:700}
.gate-pill{display:inline-block;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.3px}
.gate-hard{background:rgba(255,68,102,.15);color:var(--red);border:1px solid rgba(255,68,102,.3)}
.gate-soft{background:rgba(255,196,68,.12);color:var(--yellow);border:1px solid rgba(255,196,68,.25)}
.gate-info{background:rgba(68,136,255,.12);color:var(--blue);border:1px solid rgba(68,136,255,.25)}
.heatmap-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}
.heatmap-cell{background:var(--bg2);border:1px solid var(--border);border-left:3px solid var(--muted);border-radius:6px;padding:12px;transition:transform .15s ease,box-shadow .15s ease}
.heatmap-cell:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(0,0,0,.3)}
.heatmap-cell .sym-name{font-size:14px;font-weight:700;margin-bottom:6px}
.regime-pill{display:inline-block;padding:1px 6px;border-radius:3px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.3px}
.opportunity-glow{box-shadow:0 0 12px rgba(0,230,160,.15);border-color:rgba(0,230,160,.25)}
.danger-glow{box-shadow:0 0 12px rgba(255,68,102,.15);border-color:rgba(255,68,102,.25)}
.danger-dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--red);margin-left:6px;animation:danger-pulse 1.2s ease-in-out infinite}
@keyframes danger-pulse{0%,100%{opacity:1}50%{opacity:.4}}
.copytrade-card{background:var(--card);border:1px solid var(--border);border-left:3px solid var(--purple);border-radius:var(--radius);padding:16px}
.copytrade-card h3{font-size:11px;text-transform:uppercase;letter-spacing:.5px;color:var(--purple);margin-bottom:8px;font-weight:700}
.offline-msg{color:var(--muted);font-size:12px;font-style:italic;padding:12px 0}
.chart-wrap{position:relative;height:250px}
.chart-wrap canvas{width:100%!important;height:100%!important}
.strat-row{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.strat-label{width:130px;font-size:11px;color:var(--text);text-align:right;overflow:hidden;text-overflow:ellipsis}
.strat-bar-track{flex:1;height:14px;background:var(--border);border-radius:4px;overflow:hidden}
.strat-bar-fill{height:100%;border-radius:4px;transition:width .4s ease;display:flex;align-items:center;padding-left:6px;font-size:10px;font-weight:700;color:#fff}
.strat-pnl{width:80px;font-size:11px;text-align:right;font-weight:600}
.health-item{padding:8px 10px;border-left:3px solid var(--border);margin-bottom:6px;font-size:11px;border-radius:0 4px 4px 0;background:rgba(255,255,255,.01)}
.health-item.sev-INFO{border-left-color:var(--blue)}
.health-item.sev-WARNING{border-left-color:var(--yellow)}
.health-item.sev-ALERT,.health-item.sev-ERROR{border-left-color:var(--red)}
.health-time{color:var(--muted);font-size:10px}.health-type{font-weight:700;margin-right:6px}
.pnl-pos{color:var(--green);font-weight:700}
.pnl-neg{color:var(--red);font-weight:700}
.empty{color:var(--muted);padding:20px;text-align:center;font-size:12px}
.section-title{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin:24px 0 12px 0}
.footer{text-align:center;color:var(--muted);font-size:10px;padding:24px 0 8px 0;border-top:1px solid var(--border);margin-top:24px}
@media(max-width:1280px){.grid-5{grid-template-columns:repeat(3,1fr)}.grid-3{grid-template-columns:1fr 1fr}.heatmap-grid{grid-template-columns:repeat(auto-fill,minmax(180px,1fr))}}
@media(max-width:900px){.grid-5{grid-template-columns:repeat(2,1fr)}.grid-2,.grid-3{grid-template-columns:1fr}.container{padding:12px}.metric{font-size:22px}.heatmap-grid{grid-template-columns:1fr 1fr}}
@media(max-width:540px){.grid-5{grid-template-columns:1fr}.heatmap-grid{grid-template-columns:1fr}html{font-size:12px}}
</style>
</head>
<body>
<div class="container">

<!-- Header -->
<div class="header">
    <h1>NunuIRL Trading Dashboard</h1>
    <div class="status">
        <span><span class="dot dot-green" id="health-dot"></span><span id="health-label">Connecting...</span></span>
        <span id="uptime-display">Uptime: --</span>
        <span><span class="refresh-pulse"></span><span id="last-refresh">--</span></span>
    </div>
</div>

<!-- KPI Cards -->
<div class="grid-5">
    <div class="card"><h3>Equity</h3><div class="metric blue" id="kpi-equity">--</div><div class="metric-sub" id="kpi-equity-change">--</div></div>
    <div class="card"><h3>Daily PnL</h3><div class="metric" id="kpi-pnl">$0.00</div><div class="metric-sub" id="kpi-pnl-detail">0 trades | $0.00 fees</div></div>
    <div class="card"><h3>Win Rate</h3><div class="metric" id="kpi-winrate">0%</div><div class="bar-track"><div class="bar-fill" id="wr-bar" style="width:0%;background:var(--green)"></div></div><div class="metric-sub" id="kpi-wl">0W / 0L</div></div>
    <div class="card"><h3>Open Positions</h3><div class="metric cyan" id="kpi-open-positions">0</div><div class="metric-sub" id="kpi-open-positions-sub">--</div></div>
    <div class="card"><h3>Unrealized PnL</h3><div class="metric" id="kpi-unrealized-pnl">$0.00</div><div class="metric-sub" id="kpi-unrealized-pnl-sub">across all positions</div></div>
</div>

<!-- Live Positions Hero -->
<div class="full-width">
    <div class="card-hero">
        <h3>Live Positions</h3>
        <div class="scroll-y">
            <table>
                <thead><tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Current</th><th>SL</th><th>TP1</th><th>TP2</th><th>Unrealized PnL</th><th>PnL%</th><th>Leverage</th><th>State</th><th>Hold Time</th><th>Profile</th></tr></thead>
                <tbody id="positions-body"><tr><td colspan="13" class="empty">No open positions</td></tr></tbody>
            </table>
        </div>
    </div>
</div>

<!-- Market Heatmap -->
<div class="full-width">
    <div class="card">
        <h3>Market Awareness</h3>
        <div class="heatmap-grid" id="heatmap-grid"><div class="empty" style="grid-column:1/-1;">Loading market data...</div></div>
    </div>
</div>

<!-- Copy Trade Intelligence -->
<div class="full-width">
    <div class="copytrade-card">
        <h3>Copy Trade Intelligence</h3>
        <div id="copytrade-content"><div class="offline-msg">LLM Intelligence Offline &mdash; Enable multi-agent system to activate</div></div>
    </div>
</div>

<!-- Rejected Signals / What If -->
<div class="full-width">
    <div class="card">
        <h3>Missed Signals / What If</h3>
        <div class="scroll-y">
            <table>
                <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Confidence</th><th>Strategy</th><th>Blocked By</th><th>Reason</th><th>What If PnL</th></tr></thead>
                <tbody id="rejections-body"><tr><td colspan="8" class="empty">No rejected signals</td></tr></tbody>
            </table>
        </div>
    </div>
</div>

<!-- Equity Curve + Recent Trades -->
<div class="grid-2">
    <div class="card"><h3>Equity Curve (30d)</h3><div class="chart-wrap"><canvas id="equity-chart"></canvas></div></div>
    <div class="card">
        <h3>Recent Trades (last 20)</h3>
        <div class="scroll-y" style="max-height:250px;">
            <table>
                <thead><tr><th>Time</th><th>Symbol</th><th>Side</th><th>Action</th><th>Price</th><th>PnL</th><th>Strategy</th></tr></thead>
                <tbody id="trades-body"><tr><td colspan="7" class="empty">Loading...</td></tr></tbody>
            </table>
        </div>
    </div>
</div>

<!-- Signal Performance -->
<div class="grid-2">
    <div class="card"><h3>Signal Performance by Strategy (7d)</h3><div class="scroll-y"><table><thead><tr><th>Strategy</th><th>Trades</th><th>Wins</th><th>Win Rate</th><th>PnL</th><th>Avg Score</th></tr></thead><tbody id="signal-strat-body"><tr><td colspan="6" class="empty">Loading...</td></tr></tbody></table></div></div>
    <div class="card"><h3>Signal Performance by Symbol (7d)</h3><div class="scroll-y"><table><thead><tr><th>Symbol</th><th>Trades</th><th>Wins</th><th>Win Rate</th><th>PnL</th></tr></thead><tbody id="signal-sym-body"><tr><td colspan="5" class="empty">Loading...</td></tr></tbody></table></div></div>
</div>

<!-- Strategy Breakdown -->
<div class="section-title">Strategy Breakdown (Today)</div>
<div class="card"><div id="strategy-bars"><div class="empty">No strategy data yet</div></div></div>

<!-- Health Status -->
<div class="section-title">Health Status (24h)</div>
<div class="grid-3">
    <div class="card"><h3>Bot Uptime</h3><div class="metric cyan" id="health-uptime">--</div><div class="metric-sub" id="health-started">--</div></div>
    <div class="card"><h3>Last Heartbeat</h3><div class="metric" id="health-heartbeat" style="font-size:18px;">--</div><div class="metric-sub" id="health-heartbeat-ago">--</div></div>
    <div class="card"><h3>Error Count (24h)</h3><div class="metric" id="health-errors">0</div><div class="metric-sub" id="health-warnings">0 warnings</div></div>
</div>
<div class="card" style="margin-bottom:20px;"><h3>Recent Health Events</h3><div class="scroll-y" id="health-events-list"><div class="empty">No health events</div></div></div>

<div class="footer">NunuIRL Trading Bot &mdash; Dashboard v3.0 &mdash; Positions 10s | Data 30s</div>
</div>

<script>
let equityChart = null;

function fmt$(v){if(v==null||isNaN(v))return'--';const sign=v>=0?'+':'';return sign+'$'+Math.abs(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}
function fmtAbs$(v){if(v==null||isNaN(v))return'--';return'$'+Math.abs(v).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}
function fmtPct(v){if(v==null||isNaN(v))return'--';return(v>=0?'+':'')+v.toFixed(2)+'%'}
function fmtTime(iso){if(!iso)return'--';try{return new Date(iso).toLocaleTimeString()}catch{return iso}}
function fmtDateTime(iso){if(!iso)return'--';try{const d=new Date(iso);return d.toLocaleDateString(undefined,{month:'short',day:'numeric'})+' '+d.toLocaleTimeString()}catch{return iso}}
function fmtDuration(s){if(!s||s<0)return'--';const d=Math.floor(s/86400),h=Math.floor((s%86400)/3600),m=Math.floor((s%3600)/60),sec=Math.floor(s%60);if(d>0)return d+'d '+h+'h '+m+'m';if(h>0)return h+'h '+m+'m '+sec+'s';if(m>0)return m+'m '+sec+'s';return sec+'s'}
function pnlColor(v){return v>=0?'var(--green)':'var(--red)'}
function pnlClass(v){return v>=0?'green':'red'}
function sidePill(side){const s=(side||'').toUpperCase();const isLong=s==='BUY'||s==='LONG';return'<span class="pill '+(isLong?'pill-long':'pill-short')+'">'+(isLong?'LONG':'SHORT')+'</span>'}

function buildEquityChart(eqData){
    const canvas=document.getElementById('equity-chart');
    if(!canvas||!eqData||eqData.length<2)return;
    const ctx=canvas.getContext('2d');
    const labels=eqData.map(d=>{try{return new Date(d.timestamp).toLocaleDateString(undefined,{month:'short',day:'numeric'})}catch{return''}});
    const values=eqData.map(d=>d.equity);
    const isUp=values[values.length-1]>=values[0];
    const lineColor=isUp?'#00e6a0':'#ff4466';
    const fillColor=isUp?'rgba(0,230,160,0.08)':'rgba(255,68,102,0.08)';
    if(equityChart){equityChart.data.labels=labels;equityChart.data.datasets[0].data=values;equityChart.data.datasets[0].borderColor=lineColor;equityChart.data.datasets[0].backgroundColor=fillColor;equityChart.update('none');return}
    equityChart=new Chart(ctx,{type:'line',data:{labels,datasets:[{label:'Equity',data:values,borderColor:lineColor,backgroundColor:fillColor,borderWidth:2,fill:true,tension:.3,pointRadius:0,pointHitRadius:10,pointHoverRadius:4,pointHoverBackgroundColor:lineColor}]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{display:false},tooltip:{backgroundColor:'#1a1a2e',borderColor:'#2a2a4a',borderWidth:1,titleFont:{family:'monospace',size:11},bodyFont:{family:'monospace',size:11},callbacks:{label:function(c){return'Equity: $'+c.parsed.y.toLocaleString(undefined,{minimumFractionDigits:2})}}}},scales:{x:{grid:{color:'rgba(28,28,48,0.5)',drawBorder:false},ticks:{color:'#5e5e80',font:{size:10,family:'monospace'},maxTicksLimit:10}},y:{grid:{color:'rgba(28,28,48,0.5)',drawBorder:false},ticks:{color:'#5e5e80',font:{size:10,family:'monospace'},callback:v=>'$'+v.toLocaleString()}}}}});
}

function renderStrategyBars(byStrategy){
    const container=document.getElementById('strategy-bars');
    if(!byStrategy||Object.keys(byStrategy).length===0){container.innerHTML='<div class="empty">No strategy data yet</div>';return}
    const entries=Object.entries(byStrategy).sort((a,b)=>b[1].pnl-a[1].pnl);
    const maxAbs=Math.max(...entries.map(([_,s])=>Math.abs(s.pnl)),1);
    container.innerHTML=entries.map(([name,s])=>{
        const wr=s.trades>0?(s.wins/s.trades):0;
        const barPct=Math.min((Math.abs(s.pnl)/maxAbs)*100,100);
        const barColor=s.pnl>=0?'var(--green)':'var(--red)';
        return'<div class="strat-row"><div class="strat-label">'+name+'</div><div class="strat-bar-track"><div class="strat-bar-fill" style="width:'+barPct+'%;background:'+barColor+';">'+(barPct>25?(wr*100).toFixed(0)+'% WR':'')+'</div></div><div class="strat-pnl" style="color:'+pnlColor(s.pnl)+'">'+fmt$(s.pnl)+'</div></div>';
    }).join('');
}

function renderHeatmap(marketData){
    const grid=document.getElementById('heatmap-grid');
    if(!grid)return;
    if(!marketData||marketData.length===0){grid.innerHTML='<div class="empty" style="grid-column:1/-1;">No market data available</div>';return}
    const regimeColors={trend:'var(--green)',range:'var(--yellow)',panic:'var(--red)',high_volatility:'#ff9100',low_liquidity:'var(--purple)',consolidation:'var(--blue)',news_dislocation:'var(--cyan)',unknown:'var(--muted)'};
    grid.innerHTML=marketData.map(m=>{
        const regime=(m.regime||'unknown').toLowerCase();
        const borderColor=regimeColors[regime]||regimeColors.unknown;
        const bias=(m.signal_bias||'neutral').toLowerCase();
        const conf=Math.max(0,Math.min(100,m.confidence||0));
        const danger=m.danger_level||0;
        const isOpp=bias==='bullish'&&conf>60;
        const isDanger=danger>60;
        let biasArrow,biasColor;
        if(bias==='bullish'){biasArrow='\u2191 Bullish';biasColor='var(--green)'}
        else if(bias==='bearish'){biasArrow='\u2193 Bearish';biasColor='var(--red)'}
        else{biasArrow='\u2014 Neutral';biasColor='var(--muted)'}
        const confColor=conf>70?'var(--green)':conf>40?'var(--yellow)':'var(--red)';
        let extra='';
        if(isDanger)extra+='<div style="color:var(--red);font-size:10px;margin-top:4px;">\u26a0 Danger: '+danger+'%</div>';
        if(m.recent_pnl!=null&&!isNaN(m.recent_pnl))extra+='<div style="color:'+pnlColor(m.recent_pnl)+';font-size:10px;margin-top:2px;">PnL: '+fmt$(m.recent_pnl)+'</div>';
        if(m.signal_count)extra+='<div style="color:var(--muted);font-size:10px;margin-top:2px;">'+m.signal_count+' signals</div>';
        return'<div class="heatmap-cell'+(isOpp?' opportunity-glow':'')+(isDanger?' danger-glow':'')+'" style="border-left-color:'+borderColor+';">'+
            '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;"><span class="sym-name">'+(m.symbol||'--')+'</span>'+(isDanger?'<span class="danger-dot"></span>':'')+'</div>'+
            '<div style="margin-bottom:6px;"><span class="regime-pill" style="background:'+borderColor+'22;color:'+borderColor+';">'+regime.toUpperCase()+'</span></div>'+
            '<div style="color:'+biasColor+';font-size:11px;margin-bottom:4px;">'+biasArrow+'</div>'+
            '<div style="font-size:10px;color:var(--muted);margin-bottom:2px;">Confidence: '+conf+'%</div>'+
            '<div style="background:var(--border);border-radius:3px;height:4px;overflow:hidden;"><div style="width:'+conf+'%;height:100%;background:'+confColor+';border-radius:3px;"></div></div>'+
            extra+'</div>';
    }).join('');
}

function renderRejections(rejections){
    const tbody=document.getElementById('rejections-body');
    if(!tbody)return;
    if(!rejections||rejections.length===0){tbody.innerHTML='<tr><td colspan="8" class="empty">No rejected signals</td></tr>';return}
    const hardGates=['circuit_breaker','liquidation','max_positions'];
    const softGates=['fee_drag','ev_floor','rr_floor','lev_ev_floor'];
    tbody.innerHTML=rejections.slice(0,50).map(r=>{
        const gate=(r.gate||'unknown').toLowerCase();
        let gateClass='gate-info';
        if(hardGates.includes(gate))gateClass='gate-hard';
        else if(softGates.includes(gate))gateClass='gate-soft';
        const cfPnl=r.counterfactual_pnl;
        const cfDisplay=(cfPnl!=null&&!isNaN(cfPnl))?'<span style="color:'+pnlColor(cfPnl)+';font-weight:600;">'+fmt$(cfPnl)+'</span>':'<span style="color:var(--muted);">--</span>';
        return'<tr><td>'+fmtDateTime(r.timestamp)+'</td><td><strong>'+(r.symbol||'--')+'</strong></td><td>'+sidePill(r.side)+'</td><td>'+(r.confidence!=null?r.confidence.toFixed(0)+'%':'--')+'</td><td style="color:var(--muted)">'+(r.strategy||'--')+'</td><td><span class="gate-pill '+gateClass+'">'+gate.toUpperCase()+'</span></td><td style="color:var(--muted);font-size:11px;max-width:160px;overflow:hidden;text-overflow:ellipsis;" title="'+((r.reason||'').replace(/"/g,'&quot;'))+'">'+(r.reason||'--')+'</td><td>'+cfDisplay+'</td></tr>';
    }).join('');
}

function renderCopyTrade(data){
    const container=document.getElementById('copytrade-content');
    if(!container)return;
    if(!data||!data.active){container.innerHTML='<div class="offline-msg">LLM Intelligence Offline &mdash; Enable multi-agent system (LLM_MULTI_AGENT=true) to activate</div>';return}
    let html='';
    if(data.recommendation){html+='<div style="background:var(--bg2);border-radius:6px;padding:12px;margin-bottom:10px;border-left:3px solid var(--purple);"><div style="color:var(--purple);font-size:10px;font-weight:700;margin-bottom:4px;">RECOMMENDATION</div><div style="color:var(--text);font-size:12px;">'+data.recommendation+'</div></div>'}
    if(data.insights&&data.insights.length>0){
        const agentColors={regime:'var(--blue)',trade:'var(--green)',risk:'#ff9100',critic:'var(--red)',learning:'var(--purple)',exit:'var(--yellow)',scout:'var(--cyan)'};
        data.insights.forEach(ins=>{
            const agent=(ins.agent||'unknown').toLowerCase();
            const color=agentColors[agent]||'var(--muted)';
            html+='<div style="background:var(--bg2);border-radius:6px;padding:10px;margin-bottom:6px;border-left:3px solid '+color+';"><div style="display:flex;justify-content:space-between;"><span style="color:'+color+';font-size:10px;font-weight:700;text-transform:uppercase;">'+(ins.agent||'Agent')+'</span><span style="color:var(--muted);font-size:10px;">'+fmtTime(ins.timestamp)+'</span></div><div style="color:var(--muted);font-size:11px;margin-top:4px;">'+(ins.summary||'--')+'</div></div>';
        });
    }
    container.innerHTML=html||'<div style="color:var(--muted);text-align:center;padding:15px;">Awaiting agent insights...</div>';
}

function renderPositions(positions){
    const tbody=document.getElementById('positions-body');
    if(!tbody)return;
    if(!positions||positions.length===0){
        tbody.innerHTML='<tr><td colspan="13" class="empty">No open positions</td></tr>';
        document.getElementById('kpi-open-positions').textContent='0';
        const uEl=document.getElementById('kpi-unrealized-pnl');uEl.textContent='$0.00';uEl.className='metric';
        return;
    }
    let totalPnl=0;
    const stateColors={OPEN:'var(--blue)',TP1_HIT:'var(--green)',TRAILING:'var(--yellow)',CLOSING:'#ff9100'};
    let html=positions.map(p=>{
        const uPnl=p.unrealized_pnl||0;totalPnl+=uPnl;
        const pnlPct=p.pnl_pct||0;
        const state=(p.state||'OPEN').toUpperCase();
        const stColor=stateColors[state]||'var(--muted)';
        return'<tr><td><strong>'+(p.symbol||'--')+'</strong></td><td>'+sidePill(p.side)+'</td><td>'+fmtAbs$(p.entry_price||p.entry)+'</td><td>'+fmtAbs$(p.current_price)+'</td><td>'+fmtAbs$(p.sl)+'</td><td>'+fmtAbs$(p.tp1)+'</td><td>'+fmtAbs$(p.tp2)+'</td><td class="'+(uPnl>=0?'pnl-pos':'pnl-neg')+'">'+fmt$(uPnl)+'</td><td style="color:'+pnlColor(pnlPct)+'">'+fmtPct(pnlPct)+'</td><td>'+(p.leverage||1)+'x</td><td><span style="color:'+stColor+';font-size:11px;font-weight:600;">'+state+'</span></td><td>'+fmtDuration(p.hold_time_s)+'</td><td style="color:var(--muted);font-size:11px;">'+(p.trade_profile||'--')+'</td></tr>';
    }).join('');
    html+='<tr style="border-top:2px solid var(--border);"><td colspan="7" style="text-align:right;font-weight:700;color:var(--muted);">Total Unrealized</td><td class="'+(totalPnl>=0?'pnl-pos':'pnl-neg')+'" style="font-size:14px;">'+fmt$(totalPnl)+'</td><td colspan="5"></td></tr>';
    tbody.innerHTML=html;
    document.getElementById('kpi-open-positions').textContent=positions.length;
    const uEl=document.getElementById('kpi-unrealized-pnl');uEl.textContent=fmt$(totalPnl);uEl.className='metric '+pnlClass(totalPnl);
}

async function loadAll(){
    try{
        const[dataRes,healthRes,marketRes,rejectionsRes]=await Promise.allSettled([
            fetch('/api/data'),fetch('/api/health'),fetch('/api/market'),fetch('/api/rejections')
        ]);
        let data=null,healthInfo=null,market=null,rejections=null;
        if(dataRes.status==='fulfilled'&&dataRes.value.ok)try{data=await dataRes.value.json()}catch{}
        if(healthRes.status==='fulfilled'&&healthRes.value.ok)try{healthInfo=await healthRes.value.json()}catch{}
        if(marketRes.status==='fulfilled'&&marketRes.value.ok)try{market=await marketRes.value.json()}catch{}
        if(rejectionsRes.status==='fulfilled'&&rejectionsRes.value.ok)try{rejections=await rejectionsRes.value.json()}catch{}

        if(data){
            const ds=data.daily_summary||{};
            const rt=data.recent_trades||[];
            const eq=data.equity_curve||[];
            const sp=data.signal_performance||{};
            const positions=data.positions||[];

            // KPIs
            const lastEq=eq.length>0?eq[eq.length-1]:{};
            const equity=lastEq.equity||0;
            document.getElementById('kpi-equity').textContent='$'+equity.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
            if(eq.length>=2){const prevEq=eq[0].equity||equity;const change=equity-prevEq;const changePct=prevEq>0?((change/prevEq)*100).toFixed(2):'0.00';const el=document.getElementById('kpi-equity-change');el.textContent=fmt$(change)+' ('+changePct+'% 30d)';el.style.color=pnlColor(change)}
            const pnl=ds.net_pnl||0;const pnlEl=document.getElementById('kpi-pnl');pnlEl.textContent=fmt$(pnl);pnlEl.className='metric '+pnlClass(pnl);
            document.getElementById('kpi-pnl-detail').textContent=(ds.total_trades||0)+' trades | $'+(ds.total_fees||0).toFixed(2)+' fees';
            const wr=(ds.win_rate||0)*100;const wrEl=document.getElementById('kpi-winrate');wrEl.textContent=wr.toFixed(1)+'%';wrEl.className='metric '+(wr>=50?'green':(wr>0?'red':''));
            document.getElementById('wr-bar').style.width=wr+'%';document.getElementById('wr-bar').style.background=wr>=50?'var(--green)':'var(--red)';
            document.getElementById('kpi-wl').textContent=(ds.wins||0)+'W / '+(ds.losses||0)+'L';

            renderPositions(positions);
            if(eq.length>=2)buildEquityChart(eq);

            // Signal Performance
            const byStrat=sp.by_strategy||{};const ssBody=document.getElementById('signal-strat-body');
            if(Object.keys(byStrat).length>0){ssBody.innerHTML=Object.entries(byStrat).sort((a,b)=>b[1].pnl-a[1].pnl).map(([name,s])=>'<tr><td><strong>'+name+'</strong></td><td>'+s.trades+'</td><td>'+(s.wins||0)+'</td><td><span class="pill '+(s.win_rate>=0.5?'pill-win':'pill-loss')+'">'+(s.win_rate*100).toFixed(1)+'%</span></td><td style="color:'+pnlColor(s.pnl)+';font-weight:600">'+fmt$(s.pnl)+'</td><td>'+(s.avg_score||0).toFixed(1)+'</td></tr>').join('')}
            const bySym=sp.by_symbol||{};const symBody=document.getElementById('signal-sym-body');
            if(Object.keys(bySym).length>0){symBody.innerHTML=Object.entries(bySym).sort((a,b)=>b[1].pnl-a[1].pnl).map(([sym,s])=>'<tr><td><strong>'+sym+'</strong></td><td>'+s.trades+'</td><td>'+(s.wins||0)+'</td><td><span class="pill '+(s.win_rate>=0.5?'pill-win':'pill-loss')+'">'+(s.win_rate*100).toFixed(1)+'%</span></td><td style="color:'+pnlColor(s.pnl)+';font-weight:600">'+fmt$(s.pnl)+'</td></tr>').join('')}

            renderStrategyBars(ds.by_strategy||{});

            // Recent Trades
            const tBody=document.getElementById('trades-body');
            if(rt.length>0){tBody.innerHTML=rt.map(t=>'<tr><td>'+fmtDateTime(t.timestamp)+'</td><td><strong>'+(t.symbol||'--')+'</strong></td><td>'+sidePill(t.side)+'</td><td><span class="pill pill-action">'+(t.action||'--')+'</span></td><td>$'+(t.price||0).toFixed(2)+'</td><td style="color:'+pnlColor(t.pnl||0)+';font-weight:600">'+fmt$(t.pnl||0)+'</td><td style="color:var(--muted)">'+(t.strategy||'')+'</td></tr>').join('')}

            // Copy trade
            if(data.copytrade)renderCopyTrade(data.copytrade);
        }

        if(healthInfo){
            const uptime=healthInfo.uptime_seconds||0;
            document.getElementById('health-uptime').textContent=fmtDuration(uptime);
            document.getElementById('health-started').textContent='Started: '+(healthInfo.started_at||'--');
            document.getElementById('health-heartbeat').textContent=healthInfo.last_heartbeat||'--';
            if(healthInfo.heartbeat_age_s!=null){const age=healthInfo.heartbeat_age_s;const ageEl=document.getElementById('health-heartbeat-ago');ageEl.textContent=fmtDuration(age)+' ago';ageEl.style.color=age>300?'var(--red)':(age>120?'var(--yellow)':'var(--muted)')}
            const errCount=healthInfo.error_count||0;const warnCount=healthInfo.warning_count||0;
            const errEl=document.getElementById('health-errors');errEl.textContent=errCount;errEl.className='metric '+(errCount>0?'red':'green');
            document.getElementById('health-warnings').textContent=warnCount+' warnings';
            document.getElementById('uptime-display').textContent='Uptime: '+fmtDuration(uptime);
            const dot=document.getElementById('health-dot');const label=document.getElementById('health-label');
            if(errCount>0){dot.className='dot dot-red';label.textContent=errCount+' error(s)'}
            else if(warnCount>0){dot.className='dot dot-yellow';label.textContent='Warnings'}
            else{dot.className='dot dot-green';label.textContent='Healthy'}
        }

        renderHeatmap(market);
        renderRejections(rejections);
        document.getElementById('last-refresh').textContent=new Date().toLocaleTimeString();
    }catch(err){
        console.error('Dashboard load error:',err);
        document.getElementById('health-dot').className='dot dot-red';
        document.getElementById('health-label').textContent='Connection error';
    }
}

async function refreshPositionsOnly(){try{const res=await fetch('/api/positions');if(res.ok){const positions=await res.json();renderPositions(positions)}}catch{}}

loadAll();
setInterval(loadAll,30000);
setInterval(refreshPositionsOnly,10000);
</script>
</body>
</html>"""


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
            "/":               self._serve_dashboard,
            "/dashboard":      self._serve_dashboard,
            "/api/data":       self._serve_api_data,
            "/api/equity":     self._serve_equity_data,
            "/api/positions":  self._serve_positions,
            "/api/health":     self._serve_health,
            "/api/market":     self._serve_market,
            "/api/rejections": self._serve_rejections,
            "/api/copytrade":  self._serve_copytrade,
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
