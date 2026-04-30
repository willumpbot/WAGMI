"""Lightweight API server for the WAGMI web dashboard.

Reads directly from bot data files — no Postgres needed.
Serves the endpoints the Next.js frontend expects on port 8000.

Usage:
    cd bot && python api_server.py
    # Frontend: cd web && npm run dev  (connects to localhost:8000)
"""

import csv
import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from fastapi import FastAPI, Query, Request
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
except ImportError:
    print("pip install fastapi uvicorn")
    raise

try:
    import pandas as pd
except ImportError:  # pandas is a project dep; surface a clear error if missing
    pd = None  # type: ignore

BOT_ROOT = Path(__file__).resolve().parent
DATA = BOT_ROOT / "data"

app = FastAPI(title="WAGMI Dashboard API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _read_json(path: Path) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _read_jsonl(path: Path, limit: int = 200) -> list[dict]:
    out: list[dict] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        pass
    return out[-limit:] if limit else out


def _read_trades(limit: int = 50) -> list[dict]:
    path = DATA / "trades.csv"
    if not path.exists():
        return []
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append(row)
    except Exception:
        return []
    rows = rows[-limit:]
    result = []
    for r in rows:
        pnl = float(r.get("pnl", 0) or 0)
        result.append({
            "id": r.get("timestamp", ""),
            "timestamp": r.get("timestamp", ""),
            "symbol": r.get("symbol", ""),
            "side": r.get("side", ""),
            "entry": float(r.get("entry", 0) or 0),
            "exit": float(r.get("exit", 0) or 0),
            "pnl": pnl,
            "outcome": "WIN" if pnl > 0 else "LOSS",
            "confidence": float(r.get("confidence", 0) or 0),
            "leverage": float(r.get("leverage", 1) or 1),
            "strategy": r.get("strategy", "ensemble"),
            "regime": r.get("regime", ""),
            "state_path": r.get("state_path", ""),
            "entry_type": r.get("entry_type", ""),
            "fees": float(r.get("fees", 0) or 0),
        })
    return result


# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"ok": True, "ts": time.time()}


# ─── Trade History ───────────────────────────────────────────────────────────

@app.get("/v1/trades/history")
def trade_history(limit: int = Query(50)):
    trades = _read_trades(limit)
    total = len(list(csv.DictReader(open(DATA / "trades.csv", encoding="utf-8")))) if (DATA / "trades.csv").exists() else 0
    wins = sum(1 for t in trades if t["pnl"] > 0)
    losses = sum(1 for t in trades if t["pnl"] <= 0)
    total_pnl = sum(t["pnl"] for t in trades)
    return {
        "trades": trades,
        "total": total,
        "wins": wins,
        "losses": losses,
        "win_rate": wins / len(trades) * 100 if trades else 0,
        "total_pnl": total_pnl,
    }


# ─── Equity Curve ────────────────────────────────────────────────────────────

@app.get("/v1/trades/equity-curve")
def equity_curve(run: str = "latest"):
    trades = _read_trades(limit=0)
    if not trades:
        return {"points": []}

    equity_state = _read_json(DATA / "risk_equity_state.json")
    current_equity = equity_state.get("equity", 568.58)

    points = []
    running = current_equity - sum(t["pnl"] for t in trades)
    for t in trades:
        running += t["pnl"]
        points.append({
            "ts": t["timestamp"],
            "equity": round(running, 2),
            "pnl": t["pnl"],
            "symbol": t["symbol"],
        })
    return {"points": points}


# ─── Strategies ──────────────────────────────────────────────────────────────

@app.get("/v1/strategies")
def strategies():
    return {
        "strategies": [
            {"id": "ensemble", "name": "Ensemble (weighted-veto)", "status": "live", "description": "4 strategies voting through weighted-veto mode"},
            {"id": "regime_trend", "name": "Regime Trend", "status": "live", "description": "Regime-based trend following (1h+6h)"},
            {"id": "monte_carlo_zones", "name": "Monte Carlo Zones", "status": "live", "description": "MC support/resistance (daily)"},
            {"id": "confidence_scorer", "name": "Confidence Scorer", "status": "live", "description": "Multi-factor confidence scoring"},
            {"id": "multi_tier_quality", "name": "Multi-Tier Quality", "status": "live", "description": "MTF signal quality (5m+1h)"},
        ]
    }


# ─── LLM Market View ────────────────────────────────────────────────────────

@app.get("/v1/llm/market-view")
def llm_market_view():
    memory = _read_json(DATA / "llm" / "llm_memory.json")
    notes = memory.get("notes", [])
    regime_notes = [n for n in notes if "regime" in str(n.get("content", "")).lower()]
    latest = regime_notes[-1] if regime_notes else (notes[-1] if notes else {})
    return {
        "regime": latest.get("content", "No data")[:200] if latest else "LLM inactive",
        "updated": latest.get("timestamp", "") if latest else "",
        "notes_count": len(notes),
    }


# ─── LLM Feed ───────────────────────────────────────────────────────────────

@app.get("/v1/llm/feed")
def llm_feed(limit: int = Query(200)):
    decisions = _read_jsonl(DATA / "llm" / "decisions.jsonl", limit=limit)
    return {"decisions": decisions, "count": len(decisions)}


# ─── Open Positions ──────────────────────────────────────────────────────────

@app.get("/v1/positions")
def positions():
    state = _read_json(DATA / "position_state.json")
    pos_list = []
    for sym, pos in state.get("positions", {}).items():
        pos_list.append({
            "symbol": sym,
            "side": pos.get("side", ""),
            "entry": pos.get("entry", 0),
            "sl": pos.get("sl", 0),
            "tp1": pos.get("tp1", 0),
            "tp2": pos.get("tp2", 0),
            "state": pos.get("state", ""),
            "leverage": pos.get("leverage", 1),
            "qty": pos.get("qty", 0),
            "realized_pnl": pos.get("realized_pnl", 0),
            "open_time": pos.get("open_time", ""),
        })
    return {"positions": pos_list, "count": len(pos_list)}


# ─── Equity / Account ───────────────────────────────────────────────────────

@app.get("/v1/account")
def account():
    equity_state = _read_json(DATA / "risk_equity_state.json")
    return {
        "equity": equity_state.get("equity", 0),
        "peak_equity": equity_state.get("peak_equity", 0),
    }


# ─── Agents Overview ────────────────────────────────────────────────────────

@app.get("/v1/agents/overview")
def agents_overview():
    return {
        "agents": [
            {"name": "Regime", "model": "haiku", "role": "Market regime classification", "status": "dormant"},
            {"name": "Trade", "model": "sonnet", "role": "Directional thesis + go/skip/flip", "status": "dormant"},
            {"name": "Risk", "model": "haiku", "role": "Position sizing + risk flags", "status": "dormant"},
            {"name": "Critic", "model": "sonnet", "role": "Stress-test thesis + veto", "status": "dormant"},
            {"name": "Learning", "model": "haiku", "role": "Post-trade lessons + thesis accuracy", "status": "dormant"},
            {"name": "Exit", "model": "haiku", "role": "Open position reassessment", "status": "dormant"},
            {"name": "Scout", "model": "haiku", "role": "Idle-time watchlists + forecasts", "status": "dormant"},
            {"name": "Overseer", "model": "sonnet", "role": "System health + meta-decisions", "status": "dormant"},
            {"name": "Quant", "model": "haiku", "role": "Statistical edge validation", "status": "dormant"},
        ]
    }


@app.get("/v1/agents/team/calibration")
def agents_calibration():
    return {"calibration": [], "message": "LLM agents dormant — no calibration data yet"}


@app.get("/v1/agents/debate/history")
def agents_debate_history(limit: int = Query(10)):
    return {"debates": [], "message": "LLM agents dormant — no debates yet"}


# ─── Signal Funnel ───────────────────────────────────────────────────────────

@app.get("/v1/signals/funnel")
def signal_funnel(hours: float = Query(24)):
    cutoff = time.time() - hours * 3600
    outcomes = _read_jsonl(DATA / "logs" / "signal_outcomes.jsonl", limit=0)
    recent = [o for o in outcomes if o.get("ts", 0) >= cutoff]
    passed = sum(1 for o in recent if o.get("passed"))
    rejected = len(recent) - passed
    by_sym: dict[str, int] = {}
    for o in recent:
        sym = o.get("sym", "?")
        by_sym[sym] = by_sym.get(sym, 0) + 1
    return {
        "total": len(recent),
        "passed": passed,
        "rejected": rejected,
        "pass_rate": passed / len(recent) * 100 if recent else 0,
        "by_symbol": by_sym,
        "hours": hours,
    }


# ─── Sniper Signals ─────────────────────────────────────────────────────────

@app.get("/v1/sniper/recent")
def sniper_recent(limit: int = Query(20)):
    sigs = _read_jsonl(DATA / "manual" / "sniper_signals.jsonl", limit=limit)
    # Filter out test markers
    real = [s for s in sigs if s.get("strategies", []) not in [["a", "b", "c"], ["a", "b"]]]
    return {"signals": real[-limit:], "count": len(real)}


# ─── Summary (used by landing page) ─────────────────────────────────────────

@app.get("/v1/summary")
def summary():
    trades = _read_trades(limit=0)
    equity_state = _read_json(DATA / "risk_equity_state.json")
    pos_state = _read_json(DATA / "position_state.json")

    total = len(trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    total_pnl = sum(t["pnl"] for t in trades)
    n_pos = len(pos_state.get("positions", {}))

    # Today's PnL
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_pnl = sum(t["pnl"] for t in trades if today in t.get("timestamp", ""))
    today_trades = sum(1 for t in trades if today in t.get("timestamp", ""))

    return {
        "equity": equity_state.get("equity", 0),
        "peak_equity": equity_state.get("peak_equity", 0),
        "total_trades": total,
        "win_rate": wins / total * 100 if total else 0,
        "total_pnl": round(total_pnl, 2),
        "open_positions": n_pos,
        "today_pnl": round(today_pnl, 2),
        "today_trades": today_trades,
    }


# ─── Helpers for new endpoints ──────────────────────────────────────────────

def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


def _load_trades_df(path: Path):
    """Read trades.csv / backtest CSV into a pandas DataFrame. Returns None on failure."""
    if pd is None or not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        if df.empty:
            return None
        return df
    except Exception:
        return None


def _scrub_value(v: Any) -> Any:
    """Normalize a single value to something JSON-serializable."""
    # pandas/numpy NaN / inf — catches numpy floats too (they subclass float)
    try:
        if v is None:
            return None
        if isinstance(v, float):
            if math.isnan(v) or math.isinf(v):
                return None
            return v
        # pandas NaT / NaN sentinels + numpy scalar types
        if pd is not None:
            # pd.isna returns array for arrays, bool for scalars
            try:
                if pd.isna(v):
                    return None
            except (TypeError, ValueError):
                pass
        # Convert numpy scalars to native Python
        if hasattr(v, "item") and not isinstance(v, (str, bytes, dict, list, tuple)):
            try:
                return v.item()
            except Exception:
                return v
        return v
    except Exception:
        return None


def _scrub_records(records: list[dict]) -> list[dict]:
    """Replace NaN / inf / pandas-NaT values with None so FastAPI's JSON encoder doesn't choke."""
    return [{k: _scrub_value(v) for k, v in r.items()} for r in records]


def _sharpe_from_pnl(pnl_series) -> float:
    """Crude Sharpe approximation from per-trade PnL (assume daily independence)."""
    if pd is None or pnl_series is None or len(pnl_series) < 2:
        return 0.0
    try:
        mean = float(pnl_series.mean())
        std = float(pnl_series.std(ddof=1))
        if std == 0 or math.isnan(std):
            return 0.0
        # trade-level Sharpe (no annualization — trade frequency is irregular)
        return round(mean / std * math.sqrt(len(pnl_series)), 3)
    except Exception:
        return 0.0


def _max_drawdown(equity_series) -> float:
    """Return max drawdown as a positive percentage of peak equity."""
    if pd is None or equity_series is None or len(equity_series) == 0:
        return 0.0
    try:
        s = equity_series.astype(float)
        peaks = s.cummax()
        dd = (peaks - s) / peaks.replace(0, float("nan"))
        return round(float(dd.max()) * 100, 3) if not math.isnan(float(dd.max())) else 0.0
    except Exception:
        return 0.0


def _profit_factor(pnl_series) -> float:
    try:
        wins = pnl_series[pnl_series > 0].sum()
        losses = -pnl_series[pnl_series < 0].sum()
        if losses <= 0:
            return float("inf") if wins > 0 else 0.0
        return round(float(wins) / float(losses), 3)
    except Exception:
        return 0.0


# ─── Backtest Results ───────────────────────────────────────────────────────

@app.get("/v1/backtest/results")
def backtest_results(limit_trades: int = Query(500), limit_curve: int = Query(1000)):
    """Backtest trades + equity curve + summary stats.

    Sources:
      - bot/data/backtest_trades_30d.csv  (per-trade results)
      - bot/data/backtest_trades_30d_equity_curve.csv  (hourly equity snapshots)
    """
    if pd is None:
        return {"error": "pandas not installed"}

    trades_path = DATA / "backtest_trades_30d.csv"
    curve_path = DATA / "backtest_trades_30d_equity_curve.csv"

    tdf = _load_trades_df(trades_path)
    cdf = _load_trades_df(curve_path)

    if tdf is None and cdf is None:
        return {"error": "No backtest data files found"}

    trades: list[dict] = []
    summary: dict[str, Any] = {"wr": 0.0, "pf": 0.0, "net_pnl": 0.0, "max_dd": 0.0, "sharpe": 0.0, "n_trades": 0}

    if tdf is not None:
        if "pnl" in tdf.columns:
            tdf["pnl"] = pd.to_numeric(tdf["pnl"], errors="coerce").fillna(0.0)
        n = len(tdf)
        wins = int((tdf["pnl"] > 0).sum()) if "pnl" in tdf.columns else 0
        net = float(tdf["pnl"].sum()) if "pnl" in tdf.columns else 0.0
        summary.update({
            "n_trades": n,
            "wr": round(wins / n * 100, 2) if n else 0.0,
            "net_pnl": round(net, 2),
            "pf": _profit_factor(tdf["pnl"]) if "pnl" in tdf.columns else 0.0,
            "sharpe": _sharpe_from_pnl(tdf["pnl"]) if "pnl" in tdf.columns else 0.0,
        })
        # Trim and serialize trades
        tdf_out = tdf.tail(limit_trades).copy()
        trades = _scrub_records(tdf_out.to_dict(orient="records"))

    curve: list[dict] = []
    if cdf is not None and "equity" in cdf.columns:
        cdf["equity"] = pd.to_numeric(cdf["equity"], errors="coerce").ffill()
        summary["max_dd"] = _max_drawdown(cdf["equity"])
        # Downsample to limit_curve if needed
        if len(cdf) > limit_curve:
            step = max(1, len(cdf) // limit_curve)
            cdf = cdf.iloc[::step]
        curve = _scrub_records(cdf.to_dict(orient="records"))

    # Convert inf to a JSON-friendly string in summary
    if summary["pf"] == float("inf"):
        summary["pf"] = "inf"

    return {"trades": trades, "equity_curve": curve, "summary": summary}


# ─── Forensics Analysis ─────────────────────────────────────────────────────

@app.get("/v1/forensics/analysis")
def forensics_analysis(top_n: int = Query(10)):
    """Loss forensics — worst trades and loss clusters by (symbol, setup, regime).

    Sources:
      - bot/data/trades.csv  (live/paper trade history)
    """
    if pd is None:
        return {"error": "pandas not installed"}

    path = DATA / "trades.csv"
    df = _load_trades_df(path)
    if df is None:
        return {"error": "trades.csv not found or empty", "worst_trades": [], "loss_clusters": [], "total_losses": 0}

    if "pnl" not in df.columns:
        return {"error": "trades.csv missing pnl column", "worst_trades": [], "loss_clusters": [], "total_losses": 0}

    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    losses = df[df["pnl"] < 0].copy()
    total_losses = int(len(losses))

    # Worst N trades by PnL
    worst = losses.sort_values("pnl", ascending=True).head(top_n).copy()
    keep_cols = [c for c in [
        "timestamp", "symbol", "side", "entry", "exit", "pnl", "leverage",
        "confidence", "strategy", "entry_type", "regime", "state_path", "outcome",
    ] if c in worst.columns]
    worst_trades = _scrub_records(worst[keep_cols].to_dict(orient="records"))

    # Cluster losses by (symbol, entry_type/setup, regime)
    cluster_cols: list[str] = []
    for c in ("symbol", "entry_type", "regime"):
        if c in losses.columns:
            cluster_cols.append(c)
    loss_clusters: list[dict] = []
    if cluster_cols:
        grouped = losses.groupby(cluster_cols, dropna=False)["pnl"].agg(["count", "sum", "mean"]).reset_index()
        grouped = grouped.sort_values("sum", ascending=True).head(20)
        for row in _scrub_records(grouped.to_dict(orient="records")):
            loss_clusters.append({
                "key": {c: row.get(c) for c in cluster_cols},
                "count": int(row.get("count", 0) or 0),
                "total_loss": round(_safe_float(row.get("sum")), 2),
                "avg_loss": round(_safe_float(row.get("mean")), 2),
            })

    total_loss_pnl = round(float(losses["pnl"].sum()), 2) if total_losses else 0.0

    return {
        "worst_trades": worst_trades,
        "loss_clusters": loss_clusters,
        "total_losses": total_losses,
        "total_loss_pnl": total_loss_pnl,
    }


# ─── Copy / Sniper Status ──────────────────────────────────────────────────

@app.get("/v1/copy/status")
def copy_status():
    """Current sniper / copy-trade state.

    Sources:
      - bot/data/llm/mechanical_bot_state/  (empty if copy-trade dormant)
      - bot/data/manual/sniper_signals.jsonl
      - bot/data/manual/sim_status.json (mechanical simulator state)
      - bot/data/sessions/SNIPER_COUNTERFACTUAL_2026_04_15.md (headline stats)
    """
    state_dir = DATA / "llm" / "mechanical_bot_state"
    mem_dir = DATA / "llm" / "mechanical_bot_memory"
    sim_status_path = DATA / "manual" / "sim_status.json"
    pa_sim_path = DATA / "manual" / "pa_sim_status.json"
    sniper_path = DATA / "manual" / "sniper_signals.jsonl"

    has_live_state = any(state_dir.iterdir()) if state_dir.exists() else False
    has_memory = any(mem_dir.iterdir()) if mem_dir.exists() else False

    # Sim status (mechanical paper-sim — proxy for the copy-trade backbone)
    sim = _read_json(sim_status_path) if sim_status_path.exists() else {}
    pa_sim = _read_json(pa_sim_path) if pa_sim_path.exists() else {}

    # Count recent real sniper signals
    recent_sniper_count = 0
    latest_signal_ts: Optional[str] = None
    if sniper_path.exists():
        try:
            sigs = _read_jsonl(sniper_path, limit=200)
            real = [
                s for s in sigs
                if s.get("strategies", []) not in [["a", "b", "c"], ["a", "b"]]
            ]
            recent_sniper_count = len(real)
            if real:
                latest_signal_ts = real[-1].get("timestamp") or real[-1].get("ts")
        except Exception:
            pass

    if not has_live_state and not has_memory:
        return {
            "enabled": False,
            "reason": "Copy-trade / mechanical sniper auto-executor is dormant (SNIPER_AUTO_EXECUTE=false). Manual sniper signals still emitted.",
            "sim_status": sim,
            "pa_sim_status": pa_sim,
            "recent_sniper_signals": recent_sniper_count,
            "latest_signal_ts": latest_signal_ts,
            "counterfactual_summary": {
                "source_doc": "bot/data/sessions/SNIPER_COUNTERFACTUAL_2026_04_15.md",
                "sniper_wr_pct": 96.2,
                "premium_wr_pct": 69.0,
                "trades": 124,
                "best_leverage": "10x (per counterfactual)",
            },
        }

    return {
        "enabled": True,
        "state_dir": str(state_dir),
        "has_memory": has_memory,
        "sim_status": sim,
        "pa_sim_status": pa_sim,
        "recent_sniper_signals": recent_sniper_count,
        "latest_signal_ts": latest_signal_ts,
    }


# ─── Portfolio Allocation ──────────────────────────────────────────────────

@app.get("/v1/portfolio/allocation")
def portfolio_allocation():
    """Current portfolio allocation + correlation warnings.

    Sources:
      - bot/data/risk_equity_state.json
      - bot/data/position_state.json
      - bot/data/portfolio_risk/correlation_cache.json
    """
    equity_state = _read_json(DATA / "risk_equity_state.json")
    pos_state = _read_json(DATA / "position_state.json")
    corr = _read_json(DATA / "portfolio_risk" / "correlation_cache.json")

    equity = _safe_float(equity_state.get("equity"), 0.0)
    positions = pos_state.get("positions", {}) or {}

    by_symbol: dict[str, dict[str, Any]] = {}
    total_notional = 0.0
    total_margin = 0.0
    for sym, pos in positions.items():
        qty = _safe_float(pos.get("qty"))
        entry = _safe_float(pos.get("entry"))
        leverage = _safe_float(pos.get("leverage"), 1.0) or 1.0
        notional = abs(qty * entry)
        margin = notional / leverage if leverage else notional
        total_notional += notional
        total_margin += margin
        by_symbol[sym] = {
            "side": pos.get("side", ""),
            "notional_usd": round(notional, 2),
            "margin_usd": round(margin, 2),
            "leverage": leverage,
            "pct_of_equity": round(margin / equity * 100, 3) if equity else 0.0,
        }

    correlation_warnings: list[dict] = []
    symbols = corr.get("symbols", []) or []
    matrix = corr.get("matrix", []) or []
    held_symbols = [s for s in by_symbol.keys() if s in symbols]
    # Flag any pair of held positions whose correlation > 0.7
    for i, sa in enumerate(held_symbols):
        for sb in held_symbols[i + 1:]:
            try:
                ia = symbols.index(sa)
                ib = symbols.index(sb)
                rho = float(matrix[ia][ib])
                if abs(rho) >= 0.7:
                    correlation_warnings.append({
                        "pair": [sa, sb],
                        "correlation": round(rho, 3),
                        "message": f"High correlation ({rho:+.2f}) between concurrent positions",
                    })
            except Exception:
                continue

    total_exposure_pct = round(total_margin / equity * 100, 3) if equity else 0.0

    return {
        "equity": round(equity, 2),
        "by_symbol": by_symbol,
        "position_count": len(by_symbol),
        "total_notional_usd": round(total_notional, 2),
        "total_margin_usd": round(total_margin, 2),
        "total_exposure_pct": total_exposure_pct,
        "correlation_warnings": correlation_warnings,
        "correlation_symbols": symbols,
    }


# ─── Performance Metrics ────────────────────────────────────────────────────

@app.get("/v1/performance/metrics")
def performance_metrics():
    """Rolling 7d / 30d / lifetime performance metrics.

    Sources:
      - bot/data/trades.csv
      - bot/data/risk_equity_state.json (for current equity anchor)
    """
    if pd is None:
        return {"error": "pandas not installed"}

    path = DATA / "trades.csv"
    df = _load_trades_df(path)
    if df is None:
        return {"error": "trades.csv not found or empty"}

    if "pnl" not in df.columns:
        return {"error": "trades.csv missing pnl column"}

    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
    df["timestamp"] = pd.to_datetime(df.get("timestamp"), errors="coerce", utc=True)
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")

    now = pd.Timestamp.now(tz="UTC")

    def _window_metrics(sub) -> dict[str, Any]:
        n = len(sub)
        if n == 0:
            return {"trades": 0, "wr": 0.0, "pf": 0.0, "expectancy": 0.0, "net_pnl": 0.0, "sharpe": 0.0}
        wins = int((sub["pnl"] > 0).sum())
        net = float(sub["pnl"].sum())
        return {
            "trades": n,
            "wr": round(wins / n * 100, 2),
            "pf": _profit_factor(sub["pnl"]),
            "expectancy": round(float(sub["pnl"].mean()), 2),
            "net_pnl": round(net, 2),
            "sharpe": _sharpe_from_pnl(sub["pnl"]),
        }

    last_7d = df[df["timestamp"] >= now - pd.Timedelta(days=7)]
    last_30d = df[df["timestamp"] >= now - pd.Timedelta(days=30)]

    # Build a synthetic equity curve from ordered PnL to compute max DD
    equity_anchor = _safe_float(_read_json(DATA / "risk_equity_state.json").get("equity"), 0.0)
    cumulative = df["pnl"].cumsum()
    starting = equity_anchor - float(cumulative.iloc[-1]) if len(cumulative) else equity_anchor
    equity_series = starting + cumulative
    max_dd_pct = _max_drawdown(equity_series)

    # Avg trade duration if we have entry/exit timestamps — only timestamp is present here,
    # so estimate duration as delta between sequential trades (proxy).
    try:
        diffs = df["timestamp"].diff().dropna()
        avg_delta_hours = round(float(diffs.mean().total_seconds()) / 3600.0, 2) if len(diffs) else 0.0
    except Exception:
        avg_delta_hours = 0.0

    # Best / worst day (by summed PnL)
    by_day = df.groupby(df["timestamp"].dt.date)["pnl"].sum()
    best_day = worst_day = None
    if len(by_day):
        best_day = {"date": str(by_day.idxmax()), "pnl": round(float(by_day.max()), 2)}
        worst_day = {"date": str(by_day.idxmin()), "pnl": round(float(by_day.min()), 2)}

    return {
        "lifetime": _window_metrics(df),
        "last_30d": _window_metrics(last_30d),
        "last_7d": _window_metrics(last_7d),
        "max_drawdown_pct": max_dd_pct,
        "avg_inter_trade_hours": avg_delta_hours,
        "best_day": best_day,
        "worst_day": worst_day,
        "equity_now": round(equity_anchor, 2),
    }


# ─── Market Signals (lightweight TA snapshot) ───────────────────────────────

_SIGNALS_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}
_SIGNALS_TTL_S = 30.0


def _compute_signal_for_symbol(symbol: str) -> Optional[dict]:
    """Build a compact TA snapshot from the most recent trades.csv row + recent price.

    Returns None if there's no price context available.
    """
    try:
        trades = _read_trades(limit=500)
        rows = [t for t in trades if t.get("symbol") == symbol]
        if not rows:
            return None
        prices = [float(t.get("exit") or t.get("entry") or 0) for t in rows]
        prices = [p for p in prices if p > 0]
        if len(prices) < 5:
            return None
        closes = prices[-50:]
        last = closes[-1]

        def _sma(xs: list[float], n: int) -> float:
            if len(xs) < n:
                return sum(xs) / len(xs)
            return sum(xs[-n:]) / n

        sma20 = _sma(closes, 20)
        sma50 = _sma(closes, 50)

        diffs = [abs(closes[i] - closes[i - 1]) for i in range(1, len(closes))]
        atr14 = sum(diffs[-14:]) / max(len(diffs[-14:]), 1) if diffs else 0.0
        atr_pct = (atr14 / last * 100) if last else 0.0

        gains = [max(0.0, closes[i] - closes[i - 1]) for i in range(1, len(closes))][-14:]
        losses = [max(0.0, closes[i - 1] - closes[i]) for i in range(1, len(closes))][-14:]
        avg_g = sum(gains) / max(len(gains), 1)
        avg_l = sum(losses) / max(len(losses), 1)
        if avg_l == 0:
            rsi14 = 70.0 if avg_g > 0 else 50.0
        else:
            rs = avg_g / avg_l
            rsi14 = 100 - (100 / (1 + rs))

        score = 50
        if sma20 > sma50 and last > sma20:
            score += 20
        elif sma20 <= sma50 and last < sma20:
            score -= 20
        if rsi14 > 70:
            score -= 10
        if rsi14 < 30:
            score += 10
        score = max(0, min(100, score))

        if score >= 70:
            label = "Aggressive Accumulation"
        elif score >= 55:
            label = "Accumulation"
        elif score <= 30:
            label = "Aggressive Distribution"
        elif score <= 45:
            label = "Distribution"
        else:
            label = "Neutral"

        return {
            "symbol": symbol,
            "price": round(last, 6),
            "sma20": round(sma20, 6),
            "sma50": round(sma50, 6),
            "rsi14": round(rsi14, 2),
            "atr14": round(atr14, 6),
            "atr_pct": round(atr_pct, 3),
            "score": int(score),
            "label": label,
            "vol_spike": False,
            "zones": {
                "deepAccum": round(sma20 - 2.0 * atr14, 6),
                "accum": round(sma20 - 1.0 * atr14, 6),
                "distrib": round(sma20 + 1.0 * atr14, 6),
                "safeDistrib": round(sma20 + 2.0 * atr14, 6),
            },
        }
    except Exception:
        return None


@app.get("/v1/signals")
def signals():
    """Lightweight per-symbol market signal snapshot for the landing page."""
    now = time.time()
    if _SIGNALS_CACHE["payload"] and (now - _SIGNALS_CACHE["ts"]) < _SIGNALS_TTL_S:
        return _SIGNALS_CACHE["payload"]

    symbols = ["BTC", "ETH", "SOL", "HYPE"]
    sig_map: dict[str, Any] = {}
    errors: list[str] = []
    for sym in symbols:
        s = _compute_signal_for_symbol(sym)
        if s is not None:
            sig_map[sym] = s
        else:
            errors.append(f"no_data:{sym}")

    payload = {
        "signals": sig_map,
        "regime": "Neutral",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "errors": errors,
    }
    _SIGNALS_CACHE["ts"] = now
    _SIGNALS_CACHE["payload"] = payload
    return payload


# ─── OHLCV (synthetic fallback from trade history) ──────────────────────────

@app.get("/v1/ohlcv")
def ohlcv(symbol: str = Query(...), timeframe: str = Query("1h"), limit: int = Query(200)):
    """Return synthetic OHLCV candles from trades.csv entry/exit prices.

    Best-effort fallback — a real OHLCV feed would connect to CCXT.
    """
    trades = _read_trades(limit=0)
    rows = [t for t in trades if t.get("symbol") == symbol]
    if not rows:
        return {"symbol": symbol, "timeframe": timeframe, "candles": []}

    candles: list[dict] = []
    for t in rows[-limit:]:
        entry = float(t.get("entry") or 0)
        exit_p = float(t.get("exit") or 0)
        if entry <= 0 or exit_p <= 0:
            continue
        hi = max(entry, exit_p) * 1.003
        lo = min(entry, exit_p) * 0.997
        candles.append({
            "time": t.get("timestamp", ""),
            "open": entry,
            "high": round(hi, 6),
            "low": round(lo, 6),
            "close": exit_p,
            "volume": 0,
        })
    return {"symbol": symbol, "timeframe": timeframe, "candles": candles}


# ─── Activity Feed (trades + sniper alerts blended) ─────────────────────────

@app.get("/v1/activity/feed")
def activity_feed(limit: int = Query(50)):
    """Unified activity stream: recent trades + recent sniper alerts, newest first."""
    items: list[dict] = []

    for t in _read_trades(limit=max(limit, 50)):
        pnl_v = float(t.get("pnl", 0) or 0)
        items.append({
            "kind": "trade",
            "ts": t.get("timestamp", ""),
            "symbol": t.get("symbol", ""),
            "side": t.get("side", ""),
            "pnl": pnl_v,
            "outcome": t.get("outcome", ""),
            "strategy": t.get("strategy", ""),
            "label": (
                f"{t.get('symbol','?')} {t.get('side','?')} closed "
                f"{'WIN' if pnl_v > 0 else 'LOSS'} (${pnl_v:+.2f})"
            ),
        })

    sigs = _read_jsonl(DATA / "manual" / "sniper_signals.jsonl", limit=max(limit, 50))
    for s in sigs:
        if s.get("strategies") in (["a", "b", "c"], ["a", "b"]):
            continue
        items.append({
            "kind": "sniper_alert",
            "ts": s.get("timestamp", s.get("ts", "")),
            "symbol": s.get("symbol", ""),
            "side": s.get("side", ""),
            "tier": s.get("tier", ""),
            "label": f"{s.get('tier','?')} {s.get('symbol','?')} {s.get('side','?')} @ {s.get('entry','?')}",
        })

    # ISO-lexicographic sort works for UTC strings
    items.sort(key=lambda x: str(x.get("ts", "")), reverse=True)
    return {"feed": items[:limit], "count": len(items[:limit])}


# ─── Backtest Run Listing & Detail ──────────────────────────────────────────

def _list_backtest_runs() -> list[dict]:
    """Scan bot/data/ for all backtest_*.csv pairs and build a run list."""
    runs: list[dict] = []
    try:
        for p in DATA.glob("backtest_*.csv"):
            name = p.name
            if name.endswith("_equity_curve.csv"):
                continue
            stat = p.stat()
            run_id = p.stem
            days: Optional[int] = None
            for chunk in run_id.split("_"):
                if chunk.endswith("d") and chunk[:-1].isdigit():
                    days = int(chunk[:-1])
                    break

            total_ret = wr = n_tr = net_pnl = max_dd = pf = None
            if pd is not None:
                try:
                    df = pd.read_csv(p)
                    if "pnl" in df.columns and len(df):
                        df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce").fillna(0.0)
                        n_tr = int(len(df))
                        wins = int((df["pnl"] > 0).sum())
                        wr = round(wins / n_tr * 100, 2) if n_tr else 0.0
                        net_pnl = round(float(df["pnl"].sum()), 2)
                        pf_v = _profit_factor(df["pnl"])
                        pf = None if pf_v == float("inf") else pf_v
                    curve_path = p.with_name(p.stem + "_equity_curve.csv")
                    if curve_path.exists():
                        cdf = pd.read_csv(curve_path)
                        if "equity" in cdf.columns and len(cdf):
                            start = float(cdf["equity"].iloc[0])
                            end = float(cdf["equity"].iloc[-1])
                            if start > 0:
                                total_ret = round((end - start) / start * 100, 3)
                            max_dd = _max_drawdown(cdf["equity"])
                except Exception:
                    pass

            runs.append({
                "id": run_id,
                "file": str(p),
                "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                "size_bytes": stat.st_size,
                "symbols": [],
                "days": days,
                "total_return_pct": total_ret,
                "win_rate": wr,
                "total_trades": n_tr,
                "net_pnl": net_pnl,
                "max_drawdown_pct": max_dd,
                "profit_factor": pf,
            })
    except Exception:
        pass
    runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return runs


def _scrub_nans(rows: list[dict]) -> list[dict]:
    """Replace NaN/inf with None so FastAPI/JSON can serialize safely."""
    cleaned: list[dict] = []
    for row in rows:
        scrubbed: dict = {}
        for k, v in row.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                scrubbed[k] = None
            else:
                scrubbed[k] = v
        cleaned.append(scrubbed)
    return cleaned


def _load_backtest_detail(run_id: str) -> Optional[dict]:
    """Load full detail for a single backtest run by id (file stem)."""
    if pd is None:
        return None
    p = DATA / f"{run_id}.csv"
    if not p.exists():
        return None
    try:
        tdf = pd.read_csv(p)
    except Exception:
        return None

    curve_path = p.with_name(p.stem + "_equity_curve.csv")
    cdf = None
    if curve_path.exists():
        try:
            cdf = pd.read_csv(curve_path)
        except Exception:
            cdf = None

    if "pnl" in tdf.columns:
        tdf["pnl"] = pd.to_numeric(tdf["pnl"], errors="coerce").fillna(0.0)
    n = int(len(tdf)) if tdf is not None else 0
    wins_n = int((tdf["pnl"] > 0).sum()) if n and "pnl" in tdf.columns else 0
    losses_n = n - wins_n
    net = float(tdf["pnl"].sum()) if n and "pnl" in tdf.columns else 0.0
    pf_v = _profit_factor(tdf["pnl"]) if n and "pnl" in tdf.columns else 0.0
    pf = None if pf_v == float("inf") else pf_v

    total_ret = None
    final_eq = None
    max_dd = 0.0
    curve_rows: list[dict] = []
    if cdf is not None and "equity" in cdf.columns and len(cdf):
        start = float(cdf["equity"].iloc[0])
        end = float(cdf["equity"].iloc[-1])
        final_eq = round(end, 2)
        total_ret = round((end - start) / start * 100, 3) if start > 0 else None
        max_dd = _max_drawdown(cdf["equity"])
        cdf2 = cdf.where(pd.notna(cdf), None)
        curve_rows = _scrub_nans(cdf2.to_dict(orient="records"))

    tdf_clean = tdf.where(pd.notna(tdf), None) if n else tdf
    raw_trades: list[dict] = tdf_clean.to_dict(orient="records") if n else []
    trades_list = _scrub_nans(raw_trades)

    return {
        "config": {
            "symbols": [],
            "days": None,
            "starting_equity": 500.0,
            "risk_per_trade": 0.0,
            "ensemble_mode": "weighted_veto",
            "leverage_enabled": True,
            "trailing_stop_enabled": True,
        },
        "results": {
            "final_equity": final_eq if final_eq is not None else 0.0,
            "total_return_pct": total_ret if total_ret is not None else 0.0,
            "max_drawdown_pct": max_dd,
            "total_signals": n,
            "positions_opened": n,
            "total_trades": n,
            "wins": wins_n,
            "losses": losses_n,
            "win_rate": round(wins_n / n * 100, 2) if n else 0.0,
            "total_pnl": round(net, 2),
            "gross_pnl": round(net, 2),
            "total_fees": 0.0,
            "net_pnl": round(net, 2),
            "profit_factor": pf if pf is not None else 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
        },
        "trades": trades_list[:500],
        "equity_curve": curve_rows[:2000],
    }


@app.get("/v1/backtest/results/latest")
def backtest_results_latest():
    """Return the detail of the most recently-modified backtest run."""
    runs = _list_backtest_runs()
    if not runs:
        return {"error": "No backtest runs found"}
    latest = runs[0]
    detail = _load_backtest_detail(latest["id"])
    if detail is None:
        return {"error": f"Could not load {latest['id']}"}
    return detail


@app.get("/v1/backtest/results/{run_id}")
def backtest_results_detail(run_id: str):
    """Return detail of a specific backtest run."""
    detail = _load_backtest_detail(run_id)
    if detail is None:
        return {"error": f"Run '{run_id}' not found"}
    return detail


@app.get("/v1/backtest/runs")
def backtest_runs():
    """List all backtest runs (meta only) — newest first."""
    runs = _list_backtest_runs()
    return {"results": runs, "count": len(runs)}


# ─── Per-Agent Performance / Calibration (LLM dormant-safe) ─────────────────

@app.get("/v1/agents/{agent_name}/performance")
def agent_performance(agent_name: str):
    """Per-agent performance snapshot (empty when LLM dormant)."""
    log_path = DATA / "llm" / "agent_outputs.jsonl"
    if not log_path.exists():
        return {
            "agent": agent_name,
            "calls": 0,
            "accuracy": None,
            "avg_latency_ms": None,
            "message": "LLM agents dormant or no logged output",
            "history": [],
        }
    outputs = _read_jsonl(log_path, limit=500)
    mine = [o for o in outputs if str(o.get("agent", "")).lower() == agent_name.lower()]
    return {
        "agent": agent_name,
        "calls": len(mine),
        "accuracy": None,
        "avg_latency_ms": None,
        "history": mine[-50:],
    }


@app.get("/v1/agents/{agent_name}/calibration")
def agent_calibration(agent_name: str):
    """Per-agent calibration curve (empty when LLM dormant)."""
    ledger_path = DATA / "llm" / "calibration_ledger.json"
    if not ledger_path.exists():
        return {"agent": agent_name, "calibration": [], "message": "No calibration data yet"}
    data = _read_json(ledger_path)
    bucket = data.get(agent_name, []) if isinstance(data, dict) else []
    return {"agent": agent_name, "calibration": bucket}


# ─── Reasoning Feed (9-agent chains grouped by pipeline) ────────────────────

_AGENT_ORDER = [
    "regime", "trade", "risk", "critic",
    "learning", "exit", "scout", "overseer", "quant",
]

_AGENT_MODEL_CLASS = {
    "regime": "haiku",
    "trade": "sonnet",
    "risk": "haiku",
    "critic": "sonnet",
    "learning": "haiku",
    "exit": "haiku",
    "scout": "haiku",
    "overseer": "sonnet",
    "quant": "haiku",
}


def _classify_model(model_id: str) -> str:
    """Reduce a model id string to haiku/sonnet/opus."""
    m = (model_id or "").lower()
    if "opus" in m:
        return "opus"
    if "sonnet" in m:
        return "sonnet"
    if "haiku" in m:
        return "haiku"
    return "unknown"


@app.get("/v1/reasoning/feed")
def reasoning_feed(limit: int = Query(30), symbol: Optional[str] = Query(None)):
    """Return recent agent pipelines grouped by pipeline_id.

    Parses decisions.jsonl, buckets records by pipeline_id, orders agents in the
    canonical Regime -> Trade -> Risk -> Critic -> ... sequence.
    """
    path = DATA / "llm" / "decisions.jsonl"
    rows = _read_jsonl(path, limit=0)
    pipelines: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r.get("type") != "decision":
            continue
        pid = r.get("pipeline_id") or r.get("record_id") or ""
        if not pid:
            continue
        if symbol and r.get("symbol") and str(r.get("symbol")).upper() != symbol.upper():
            continue
        bucket = pipelines.setdefault(pid, {
            "pipeline_id": pid,
            "timestamp": r.get("timestamp"),
            "symbol": r.get("symbol") or "",
            "side": r.get("side") or "",
            "agents": [],
        })
        if not bucket["symbol"] and r.get("symbol"):
            bucket["symbol"] = r.get("symbol")
        if not bucket["side"] and r.get("side"):
            bucket["side"] = r.get("side")
        # Earliest timestamp wins
        ts = r.get("timestamp")
        if ts and (bucket["timestamp"] is None or ts < bucket["timestamp"]):
            bucket["timestamp"] = ts
        role = str(r.get("agent_role") or "").lower()
        bucket["agents"].append({
            "role": role,
            "decision": r.get("decision"),
            "confidence": r.get("confidence"),
            "reasoning_summary": r.get("reasoning_summary"),
            "model_used": r.get("model_used"),
            "model_class": _classify_model(str(r.get("model_used") or "")),
            "latency_ms": r.get("latency_ms"),
            "record_id": r.get("record_id"),
        })

    # Order agents inside each pipeline using canonical ordering
    order_index = {name: i for i, name in enumerate(_AGENT_ORDER)}
    for p in pipelines.values():
        p["agents"].sort(key=lambda a: order_index.get(a["role"], 99))

    # Sort pipelines by timestamp descending
    out = list(pipelines.values())
    out.sort(key=lambda p: p.get("timestamp") or 0, reverse=True)
    return {"pipelines": out[:limit], "count": len(out)}


@app.get("/v1/reasoning/pipeline/{pipeline_id}")
def reasoning_pipeline(pipeline_id: str):
    """Full reasoning chain for a single pipeline_id (all agent records)."""
    path = DATA / "llm" / "decisions.jsonl"
    rows = _read_jsonl(path, limit=0)
    matches = [r for r in rows if r.get("pipeline_id") == pipeline_id and r.get("type") == "decision"]
    order_index = {name: i for i, name in enumerate(_AGENT_ORDER)}
    matches.sort(key=lambda r: order_index.get(str(r.get("agent_role", "")).lower(), 99))
    if not matches:
        return {"pipeline_id": pipeline_id, "agents": [], "message": "No records found"}
    symbol = next((m.get("symbol") for m in matches if m.get("symbol")), "")
    side = next((m.get("side") for m in matches if m.get("side")), "")
    ts = min((m.get("timestamp") for m in matches if m.get("timestamp") is not None), default=None)
    return {
        "pipeline_id": pipeline_id,
        "symbol": symbol,
        "side": side,
        "timestamp": ts,
        "agents": [
            {
                "role": str(m.get("agent_role") or "").lower(),
                "decision": m.get("decision"),
                "confidence": m.get("confidence"),
                "reasoning_summary": m.get("reasoning_summary"),
                "model_used": m.get("model_used"),
                "model_class": _classify_model(str(m.get("model_used") or "")),
                "latency_ms": m.get("latency_ms"),
                "record_id": m.get("record_id"),
            }
            for m in matches
        ],
    }


# ─── Counterfactuals (resolved + stats) ─────────────────────────────────────

@app.get("/v1/counterfactuals/resolved")
def counterfactuals_resolved(
    limit: int = Query(200),
    symbol: Optional[str] = Query(None),
    reason: Optional[str] = Query(None),
    outcome: Optional[str] = Query(None),  # "win"|"loss"
):
    """Resolved counterfactual signals — signals skipped and what happened.

    Source: bot/data/llm/counterfactual_resolved.jsonl
    Dedupes by (symbol, side, created_at, entry_price) per MISSED_TRADES audit.
    """
    path = DATA / "llm" / "counterfactual_resolved.jsonl"
    raw = _read_jsonl(path, limit=0)

    seen: set[tuple] = set()
    clean: list[dict] = []
    for r in raw:
        # Drop synthetic test rows
        if r.get("strategy") == "test" or r.get("skip_reason") == "test_reason":
            continue
        key = (
            r.get("symbol"),
            r.get("side"),
            r.get("created_at"),
            r.get("entry_price"),
        )
        if key in seen:
            continue
        seen.add(key)
        clean.append(r)

    # Filters
    def _keep(r: dict) -> bool:
        if symbol and str(r.get("symbol", "")).upper() != symbol.upper():
            return False
        if reason and reason.lower() not in str(r.get("skip_reason", "")).lower():
            return False
        if outcome:
            pnl = _safe_float(r.get("hypothetical_pnl_pct"))
            if outcome.lower() == "win" and pnl <= 0:
                return False
            if outcome.lower() == "loss" and pnl > 0:
                return False
        return True

    filtered = [r for r in clean if _keep(r)]

    # Stats over filtered universe
    total = len(filtered)
    wins = sum(1 for r in filtered if _safe_float(r.get("hypothetical_pnl_pct")) > 0)
    losses = total - wins
    pnl_sum = sum(_safe_float(r.get("hypothetical_pnl_pct")) for r in filtered)
    avg_pnl = pnl_sum / total if total else 0.0

    # Top skip reasons
    from collections import Counter as _C
    gate_counts = _C(str(r.get("skip_reason") or "unknown") for r in filtered)
    worst_gate = {"reason": "", "count": 0, "missed_win_pct": 0.0}
    if gate_counts:
        # Find the gate that killed the most winners
        gate_wins: dict[str, int] = {}
        gate_total: dict[str, int] = {}
        for r in filtered:
            g = str(r.get("skip_reason") or "unknown")
            gate_total[g] = gate_total.get(g, 0) + 1
            if _safe_float(r.get("hypothetical_pnl_pct")) > 0:
                gate_wins[g] = gate_wins.get(g, 0) + 1
        # Rank by hypothetical winners blocked (min 20 samples)
        best: tuple[str, int, float] = ("", 0, 0.0)
        for g, wn in gate_wins.items():
            if gate_total[g] < 20:
                continue
            if wn > best[1]:
                best = (g, wn, wn / gate_total[g] * 100.0)
        if best[0]:
            worst_gate = {
                "reason": best[0],
                "count": best[1],
                "missed_win_pct": round(best[2], 1),
            }

    # Most recent first, trimmed
    filtered.sort(key=lambda r: str(r.get("resolved_at") or r.get("created_at") or ""), reverse=True)
    trimmed = filtered[:limit]

    # Serialize safely
    rows_out = _scrub_records(trimmed)

    return {
        "signals": rows_out,
        "count": len(rows_out),
        "total_resolved": total,
        "wins": wins,
        "losses": losses,
        "would_have_won_pct": round(wins / total * 100, 2) if total else 0.0,
        "hypothetical_total_pnl_pct": round(pnl_sum, 2),
        "avg_hypothetical_pnl_pct": round(avg_pnl, 3),
        "worst_gate": worst_gate,
        "top_reasons": [
            {"reason": k, "count": v}
            for k, v in gate_counts.most_common(10)
        ],
    }


# ─── Agent Health strip (24h freshness per agent) ───────────────────────────

@app.get("/v1/agents/health")
def agents_health(hours: float = Query(24)):
    """Per-agent health: fired_24h / stale / dead based on agent_performance.jsonl."""
    log_path = DATA / "llm" / "agent_performance.jsonl"
    rows = _read_jsonl(log_path, limit=0) if log_path.exists() else []

    now = datetime.now(timezone.utc)
    cutoff = now.timestamp() - hours * 3600

    per_agent: dict[str, dict[str, Any]] = {}
    for r in rows:
        agent = str(r.get("agent") or "").lower()
        if not agent:
            continue
        ts_raw = r.get("ts")
        ts: float = 0.0
        if isinstance(ts_raw, (int, float)):
            ts = float(ts_raw)
        elif isinstance(ts_raw, str):
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp()
            except Exception:
                ts = 0.0
        bucket = per_agent.setdefault(agent, {"total": 0, "recent": 0, "last_ts": 0.0})
        bucket["total"] += 1
        if ts > bucket["last_ts"]:
            bucket["last_ts"] = ts
        if ts >= cutoff:
            bucket["recent"] += 1

    # Build the full 9-agent roster
    agents_out: list[dict] = []
    for name in _AGENT_ORDER:
        data = per_agent.get(name, {"total": 0, "recent": 0, "last_ts": 0.0})
        if data["total"] == 0:
            status = "dead"
        elif data["recent"] > 0:
            status = "live"
        elif data["last_ts"] >= (now.timestamp() - 72 * 3600):
            status = "stale"
        else:
            status = "dead"
        agents_out.append({
            "name": name,
            "model_class": _AGENT_MODEL_CLASS.get(name, "haiku"),
            "total_calls": data["total"],
            "calls_24h": data["recent"],
            "last_ts": data["last_ts"] or None,
            "status": status,
        })

    return {
        "agents": agents_out,
        "hours": hours,
        "generated_at": now.isoformat(),
    }


# ─── Signal Funnel Cost Overlay ─────────────────────────────────────────────

@app.get("/v1/signals/funnel/cost")
def signal_funnel_cost(hours: float = Query(168)):
    """PnL-impact estimate per funnel stage.

    For each stage, we estimate the aggregate hypothetical PnL of signals
    that were killed at that stage, based on counterfactual_resolved.jsonl.

    Used by the SignalFunnel component's hover-to-reveal-cost overlay.
    """
    path = DATA / "llm" / "counterfactual_resolved.jsonl"
    raw = _read_jsonl(path, limit=0)

    cutoff_ts = (datetime.now(timezone.utc).timestamp() - hours * 3600)

    # Dedupe
    seen: set[tuple] = set()
    rows: list[dict] = []
    for r in raw:
        if r.get("strategy") == "test" or r.get("skip_reason") == "test_reason":
            continue
        key = (r.get("symbol"), r.get("side"), r.get("created_at"), r.get("entry_price"))
        if key in seen:
            continue
        seen.add(key)
        created = r.get("created_at")
        try:
            ts = datetime.fromisoformat(str(created).replace("Z", "+00:00")).timestamp() if created else 0.0
        except Exception:
            ts = 0.0
        if ts < cutoff_ts:
            continue
        rows.append(r)

    # Classify each skip_reason into a funnel stage
    stage_map: dict[str, str] = {}

    def _stage_for(reason: str) -> str:
        r = (reason or "").lower()
        if "valid" in r or "rr" in r or "stop_width" in r:
            return "validity"
        if any(k in r for k in ["circuit", "cb", "drawdown", "position_limit", "notional", "leverage", "duplicate", "anti_roundtrip", "liquidation"]):
            return "gates"
        if "veto" in r or "critic" in r or "llm" in r:
            return "llm"
        return "gates"

    stages = {"validity": {"blocked": 0, "hypo_pnl_pct": 0.0, "would_have_won": 0},
              "gates":    {"blocked": 0, "hypo_pnl_pct": 0.0, "would_have_won": 0},
              "llm":      {"blocked": 0, "hypo_pnl_pct": 0.0, "would_have_won": 0}}

    for r in rows:
        stage = _stage_for(str(r.get("skip_reason") or ""))
        stages[stage]["blocked"] += 1
        pnl = _safe_float(r.get("hypothetical_pnl_pct"))
        stages[stage]["hypo_pnl_pct"] += pnl
        if pnl > 0:
            stages[stage]["would_have_won"] += 1

    for s in stages.values():
        s["hypo_pnl_pct"] = round(s["hypo_pnl_pct"], 2)

    return {
        "hours": hours,
        "stages": stages,
        "total_rows": len(rows),
    }


# ─── Decision Trail per Trade ───────────────────────────────────────────────

@app.get("/v1/trade/{trade_id}/trail")
def trade_trail(trade_id: str):
    """Best-effort decision trail for a single trade.

    Matches a trade (timestamp id) against decisions.jsonl via nearest-timestamp
    + symbol. Returns the full agent chain and any Learning agent lessons.
    """
    trades = _read_trades(limit=0)
    trade = next((t for t in trades if t.get("id") == trade_id or t.get("timestamp") == trade_id), None)
    if not trade:
        return {"error": "Trade not found", "trail": []}

    # Parse trade timestamp
    try:
        t_ts = datetime.fromisoformat(trade["timestamp"].replace("Z", "+00:00")).timestamp()
    except Exception:
        t_ts = 0.0

    sym = (trade.get("symbol") or "").upper()
    decisions = _read_jsonl(DATA / "llm" / "decisions.jsonl", limit=0)
    decisions = [d for d in decisions if d.get("type") == "decision"]

    # Score each pipeline by time proximity + symbol match (prefer same sym within 2h)
    best_pid: Optional[str] = None
    best_delta = float("inf")
    for d in decisions:
        d_sym = str(d.get("symbol") or "").upper()
        if d_sym and sym and d_sym != sym:
            continue
        d_ts = float(d.get("timestamp") or 0)
        if t_ts <= 0 or d_ts <= 0:
            continue
        # pipeline time is entry-side — tolerate trades up to 4h later
        delta = abs(t_ts - d_ts)
        if delta < best_delta:
            best_delta = delta
            best_pid = d.get("pipeline_id")

    agents: list[dict] = []
    lesson: Optional[str] = None
    if best_pid:
        trail = reasoning_pipeline(best_pid)
        agents = trail.get("agents", []) if isinstance(trail, dict) else []

    # Try to find a Learning-agent lesson for this trade — scan llm_memory.json notes
    try:
        mem = _read_json(DATA / "llm" / "llm_memory.json")
        notes = mem.get("notes", []) if isinstance(mem, dict) else []
        ts_prefix = str(trade.get("timestamp") or "")[:10]  # YYYY-MM-DD
        for n in reversed(notes):
            content = str(n.get("content") or "")
            if ts_prefix and ts_prefix in content and sym in content.upper():
                lesson = content[:500]
                break
    except Exception:
        lesson = None

    return {
        "trade": trade,
        "pipeline_id": best_pid,
        "time_delta_sec": round(best_delta, 1) if best_pid else None,
        "agents": agents,
        "lesson": lesson,
    }


# ─── Live Quant Analyst thesis ─────────────────────────────────────────────

THESIS_ROOT = BOT_ROOT.parent / "web" / "public" / "thesis"


@app.get("/v1/thesis/list")
def thesis_list():
    """List all symbols with a current thesis + their last-updated timestamps."""
    if not THESIS_ROOT.exists():
        return {"symbols": [], "root": str(THESIS_ROOT)}
    rows = []
    for sym_dir in sorted(THESIS_ROOT.iterdir()):
        if not sym_dir.is_dir():
            continue
        thesis_path = sym_dir / "thesis.json"
        if not thesis_path.exists():
            continue
        try:
            data = json.loads(thesis_path.read_text(encoding="utf-8"))
            rows.append({
                "symbol": data.get("symbol", sym_dir.name.upper()),
                "price": data.get("price"),
                "updated_at": data.get("updated_at"),
                "regime_label": (data.get("committee") or {}).get("regime", {}).get("regime_label"),
                "action": (data.get("committee") or {}).get("trade", {}).get("action"),
                "confidence": (data.get("committee") or {}).get("trade", {}).get("confidence"),
                "vote": (data.get("committee") or {}).get("critic", {}).get("vote"),
                "charts": [p.name for p in sorted(sym_dir.glob("*.png"))],
            })
        except Exception as e:
            rows.append({"symbol": sym_dir.name.upper(), "error": str(e)})
    return {"symbols": rows, "ts": time.time()}


@app.get("/v1/thesis/{symbol}")
def thesis_for(symbol: str):
    """Full thesis payload for one symbol."""
    sym = symbol.lower()
    path = THESIS_ROOT / sym / "thesis.json"
    if not path.exists():
        return {"error": f"no thesis for {symbol.upper()}"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data["charts"] = [
            f"/thesis/{sym}/{p.name}"
            for p in sorted((THESIS_ROOT / sym).glob("*.png"))
        ]
        return data
    except Exception as e:
        return {"error": str(e)}


@app.post("/v1/thesis/{symbol}/thread")
def thesis_thread(symbol: str):
    """Generate a Twitter/X thread from the current thesis using Claude CLI."""
    from fastapi.responses import JSONResponse
    sym = symbol.upper()
    path = THESIS_ROOT / symbol.lower() / "thesis.json"
    if not path.exists():
        return JSONResponse({"error": f"no thesis for {sym}"}, status_code=404)
    try:
        thesis = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    c = thesis.get("committee", {})
    regime = c.get("regime", {})
    trade = c.get("trade", {})
    critic = c.get("critic", {})
    risk = c.get("risk", {})
    price = thesis.get("price", 0)
    updated = thesis.get("updated_at", "")

    prompt = f"""Write a 5-tweet X/Twitter thread about this live quant analysis.

SYMBOL: {sym} @ ${price:,.2f}
REGIME: {regime.get('regime_label','?')} ({regime.get('confidence',0)}% confidence) bias={regime.get('bias','?')}
TRADE: action={trade.get('action','?')} conf={trade.get('confidence',0)}%
  Entry: ${trade.get('entry_low',0):,.0f}-${trade.get('entry_high',0):,.0f}
  Stop: ${trade.get('stop',0):,.0f}  T1: ${trade.get('target1',0):,.0f}  R:R={trade.get('rr_t1',0):.2f}
CRITIC: vote={critic.get('vote','?')}
RISK: size={risk.get('size_multiplier','?')}x leverage={risk.get('leverage','?')}x

Regime narrative: {regime.get('narrative','')[:200]}
Trade narrative: {trade.get('narrative','')[:200]}
Critic narrative: {critic.get('narrative','')[:150]}

Instructions:
- Tweet 1: Hook — current {sym} price + regime label + one-line thesis
- Tweet 2: The trade setup (entry/stop/target/R:R) in plain numbers
- Tweet 3: What the Critic agent said (the main risk)
- Tweet 4: Sizing/risk from the Risk agent + conviction count
- Tweet 5: The bigger picture — what this means for crypto market right now
- Start each tweet with a number (1/5, 2/5, etc.)
- No hashtag spam. Max 2 hashtags total across all 5 tweets.
- Sound like a quant, not a shill. Cite the methodology (Bonferroni-cleared factors, committee of 4 agents).
- Keep each tweet under 280 characters.
"""

    try:
        sys.path.insert(0, str(BOT_ROOT))
        from llm.claude_cli_client import call_agent, available as cli_available
        if not cli_available():
            return {"error": "Claude CLI not available"}
        resp = call_agent(prompt, system_prompt="You are a quant trader writing a Twitter thread. Be precise and credible.", model="sonnet", max_budget_usd=0.10, timeout=90)
        if not resp.ok:
            return {"error": resp.error}
        tweets = []
        for line in resp.text.strip().split("\n"):
            line = line.strip()
            if line and (line[0].isdigit() or line.startswith("**")):
                tweets.append(line.lstrip("*").strip())
        return {"symbol": sym, "thread": tweets, "raw": resp.text, "cost_usd": resp.cost_usd}
    except Exception as e:
        return {"error": str(e)}


@app.get("/v1/thesis/accuracy")
def thesis_accuracy():
    """Return thesis tracker accuracy summary."""
    try:
        sys.path.insert(0, str(BOT_ROOT))
        from tools.thesis_tracker import summary as _summary
        return _summary()
    except Exception as e:
        return {"error": str(e)}


# ─── Ask-the-Agents (Q&A for /live co-pilot) ────────────────────────────────

# Per-agent system prompts for ad-hoc Q&A. These are simplified versions of
# the full trading agent prompts — they keep each agent's "voice" and concerns
# but expect prose responses suitable for an interactive chat.
_ASK_AGENT_SYSTEMS = {
    "trade": (
        "You are the Trade Agent for the WAGMI bot — an action-oriented "
        "directional thinker. You answer questions about trade setups: entry "
        "timing, side, conviction, and reasoning. Be direct, use specific "
        "price levels when possible, and cite the data the operator gave you. "
        "Keep responses under 4 short paragraphs. No JSON, no markdown — "
        "just plain conversational prose."
    ),
    "critic": (
        "You are the Critic Agent for the WAGMI bot — the structured-pessimist. "
        "Your job is to surface counter-theses and risks: what could go wrong, "
        "what's missing, what might invalidate the thesis. Always provide a "
        "concrete counter-thesis, not just hedging language. Cite the data the "
        "operator gave you. Keep responses under 4 short paragraphs. No JSON, "
        "no markdown — just plain conversational prose."
    ),
    "risk": (
        "You are the Risk Agent for the WAGMI bot. You answer questions about "
        "position sizing, leverage, drawdown, and portfolio risk. Be specific "
        "with numbers when the operator gives bankroll/equity context. "
        "Use percent-of-equity framings. Keep responses under 4 short paragraphs. "
        "No JSON, no markdown — just plain conversational prose."
    ),
    "regime": (
        "You are the Regime Agent for the WAGMI bot. You answer questions about "
        "the market state: is it trending, ranging, panic, illiquid? What "
        "regime transitions look like. What strategies fit each regime. "
        "Keep responses under 4 short paragraphs. No JSON, no markdown — "
        "just plain conversational prose."
    ),
    "all": (
        "You are the WAGMI multi-agent system answering an operator question "
        "with one synthesized response. Combine perspectives from the Trade "
        "Agent (directional thinker), Critic (counter-thesis specialist), "
        "Risk Agent (sizing), and Regime Agent (market state). Lead with the "
        "most important angle for the question asked. Cite data the operator "
        "gave you. Keep response under 5 short paragraphs. No JSON, no markdown."
    ),
}

_ASK_VALID_AGENTS = set(_ASK_AGENT_SYSTEMS.keys())

# Simple per-client rate limit for /v1/agents/ask: token bucket. Not auth-aware
# yet — keys on client IP. Defaults: 5 questions / minute, 20 / hour. Burnable
# via env if running multi-user. In-memory only — resets on restart.
_ASK_RATE_BUCKET: dict[str, dict[str, float]] = {}

def _ask_rate_check(client_id: str) -> Optional[str]:
    """Returns None if allowed, else an error string explaining the limit."""
    now = time.time()
    bucket = _ASK_RATE_BUCKET.setdefault(client_id, {"min_window": now, "min_count": 0, "hr_window": now, "hr_count": 0})
    # Per-minute window
    if now - bucket["min_window"] >= 60:
        bucket["min_window"] = now
        bucket["min_count"] = 0
    if bucket["min_count"] >= 5:
        return f"rate limit: 5 questions/minute (try in {int(60 - (now - bucket['min_window']))}s)"
    # Per-hour window
    if now - bucket["hr_window"] >= 3600:
        bucket["hr_window"] = now
        bucket["hr_count"] = 0
    if bucket["hr_count"] >= 20:
        return f"rate limit: 20 questions/hour (try in {int((3600 - (now - bucket['hr_window'])) / 60)}min)"
    bucket["min_count"] += 1
    bucket["hr_count"] += 1
    return None


def _build_ask_context_block(context: dict) -> str:
    """Render the context dict into a compact, agent-friendly prose block."""
    if not context:
        return ""
    lines = []
    sym = context.get("symbol")
    if sym:
        lines.append(f"Symbol: {sym}")
    if context.get("side"):
        lines.append(f"Position side: {context['side']}")
    if context.get("entry") is not None:
        lines.append(f"Entry: {context['entry']}")
    if context.get("current_price") is not None:
        lines.append(f"Current price: {context['current_price']}")
    if context.get("regime"):
        lines.append(f"Regime: {context['regime']}")
    if context.get("mode") == "replay" and context.get("replay_timestamp"):
        lines.append(
            f"(Note: replay mode — context is as of {context['replay_timestamp']})"
        )
    if not lines:
        return ""
    return "Operator context:\n" + "\n".join(f"  • {ln}" for ln in lines)


def _enrich_ask_context(context: dict) -> dict:
    """Merge runtime context (current price, signals, position) into the
    user-supplied context block. Anything the operator already provided wins.
    """
    sym = (context.get("symbol") or "").upper()
    enriched = dict(context)
    if not sym:
        return enriched
    # Pull current signal (best-effort)
    try:
        signals_path = DATA / "signals.json"
        if signals_path.exists():
            sig_blob = _read_json(signals_path) or {}
            sig = (sig_blob.get("signals") or {}).get(sym) or {}
            enriched.setdefault("regime", sig.get("regime"))
            enriched.setdefault("current_price", sig.get("price"))
    except Exception:
        pass
    # Pull current position (best-effort)
    try:
        pstate = DATA / "position_state.json"
        if pstate.exists():
            pblob = _read_json(pstate) or {}
            for sym_key, pos in (pblob.get("positions") or {}).items():
                if (sym_key or "").upper() == sym:
                    enriched.setdefault("side", pos.get("side"))
                    enriched.setdefault("entry", pos.get("entry"))
                    break
    except Exception:
        pass
    return enriched


@app.post("/v1/agents/ask")
def ask_agents(payload: dict, request: Request):
    """Ad-hoc Q&A endpoint for the /live co-pilot's Ask-the-Agents panel.

    Body:
      {
        "agent":   "trade" | "risk" | "critic" | "regime" | "all",
        "question": "user question",
        "context":  { "symbol": "BTC", "side": "LONG", "entry": 60000, ... }
      }

    Returns:
      { "responses": [ { "agent": str, "text": str, "model": str, "cost_usd": float } ],
        "elapsed_ms": int }

    Cost guardrails:
      - Default model: Sonnet
      - Max budget per call: $0.05 (CLI enforces)
      - Output truncated to ~400 tokens via the prompt itself
      - Question text capped at 600 chars (rejects longer)
    """
    from fastapi.responses import JSONResponse

    target = (payload.get("agent") or "all").lower().strip()
    question = (payload.get("question") or "").strip()
    context = payload.get("context") or {}

    if target not in _ASK_VALID_AGENTS:
        return JSONResponse(
            {"error": f"unknown agent '{target}'", "valid": sorted(_ASK_VALID_AGENTS)},
            status_code=400,
        )
    if not question:
        return JSONResponse({"error": "question is required"}, status_code=400)
    if len(question) > 600:
        return JSONResponse(
            {"error": "question exceeds 600 chars"}, status_code=400
        )

    # Rate limit per client IP (5/min, 20/hr). Replace with auth-aware quotas
    # once the auth layer lands.
    client_id = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
    rate_err = _ask_rate_check(client_id)
    if rate_err:
        return JSONResponse({"error": rate_err}, status_code=429)

    try:
        sys.path.insert(0, str(BOT_ROOT))
        from llm.claude_cli_client import call_agent, available as cli_available
    except Exception as e:
        return JSONResponse(
            {"error": f"LLM client unavailable: {e}"}, status_code=503
        )

    if not cli_available():
        return JSONResponse(
            {"error": "Claude CLI not available on this host"}, status_code=503
        )

    enriched = _enrich_ask_context(context)
    context_block = _build_ask_context_block(enriched)
    user_prompt = f"{context_block}\n\nOperator's question:\n{question}".strip()

    # When target is "all", we still make ONE call (synthesized response) to
    # control cost. Frontend can render it as one bubble.
    targets = [target]

    start = time.time()
    responses = []
    total_cost = 0.0
    for agent_name in targets:
        system = _ASK_AGENT_SYSTEMS[agent_name]
        try:
            resp = call_agent(
                user_prompt=user_prompt,
                system_prompt=system,
                model="sonnet",
                max_budget_usd=0.05,
                timeout=60,
                allow_tools=False,
            )
            if resp.ok:
                responses.append({
                    "agent": agent_name,
                    "text": (resp.text or "").strip(),
                    "model": resp.model or "sonnet",
                    "cost_usd": float(resp.cost_usd or 0.0),
                })
                total_cost += float(resp.cost_usd or 0.0)
            else:
                responses.append({
                    "agent": agent_name,
                    "text": f"[error: {resp.error or 'unknown'}]",
                    "model": resp.model or "sonnet",
                    "cost_usd": 0.0,
                })
        except Exception as e:
            responses.append({
                "agent": agent_name,
                "text": f"[exception: {e}]",
                "model": "sonnet",
                "cost_usd": 0.0,
            })

    return {
        "responses": responses,
        "elapsed_ms": int((time.time() - start) * 1000),
        "total_cost_usd": round(total_cost, 6),
    }


if __name__ == "__main__":
    print(f"WAGMI Dashboard API starting on http://localhost:8000")
    print(f"Data dir: {DATA}")
    print(f"Thesis dir: {THESIS_ROOT}")
    uvicorn.run(app, host="0.0.0.0", port=8000)
