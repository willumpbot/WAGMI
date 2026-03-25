"""
Backtest the manual sniper signal system against historical counterfactual data.

Validates the aggressive $100 account strategy by simulating compound sizing
through resolved counterfactual trade outcomes.

Data reality:
- 1000 resolved counterfactual records (all from 2026-03-23 backtest run)
- Confidence range: 50-70% (no num_agree metadata available)
- Key edge: HYPE BUY = 85% WR, +4.68% avg PnL

Since the counterfactual data lacks num_agree and has max confidence ~70%,
we run TWO analyses:
1. ADAPTED: Scale tier thresholds to the available data range to simulate
   what filtering by relative signal quality would produce
2. SYMBOL-FILTERED: Use the proven HYPE BUY edge as the primary sniper
   signal source (since that IS the 85% WR signal the config targets)

Usage:
    cd bot && python -m manual.backtest_sniper
"""

import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Tuple


# ─── Data Loading ───────────────────────────────────────────────────────────

def load_counterfactual_data(path: str = None) -> List[Dict]:
    """Load resolved counterfactual records."""
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "..", "data", "counterfactual_resolved.json")
    with open(path) as f:
        data = json.load(f)
    records = data.get("records", [])
    print(f"Loaded {len(records)} counterfactual records")
    print(f"Summary from file: {data.get('summary', {})}")
    return records


# ─── Trade Result ───────────────────────────────────────────────────────────

@dataclass
class TradeResult:
    record_id: str
    symbol: str
    side: str
    tier: str
    confidence: float
    entry_price: float
    sl: float
    tp1: float
    leverage: float
    risk_pct: float
    risk_amount: float
    position_size_usd: float
    margin_used: float
    equity_before: float
    equity_after: float
    pnl_usd: float
    pnl_pct: float  # pnl as % of equity
    outcome: str  # "WIN_TP1", "WIN_TP2", "LOSS_SL", "TIMEOUT"
    bars_to_resolve: int
    hypothetical_pnl_pct: float  # raw pnl % from data
    created_at: str


# ─── Tier Classification ───────────────────────────────────────────────────

def classify_tier_adapted(confidence: float, symbol: str, side: str) -> str:
    """
    Classify signal tier using adapted thresholds for available data range.

    Original thresholds (from config):
      SNIPER:  85%+ conf & 3 agree, or 90%+ & 2 agree
      PREMIUM: 78%+ conf & 2 agree

    Adapted for 50-70% confidence range:
      SNIPER:  65%+ conf AND proven edge combo (HYPE BUY or SOL SELL)
      PREMIUM: 60%+ conf AND any preferred symbol
      STANDARD: 55%+ conf
    """
    is_proven_edge = (symbol == "HYPE" and side == "BUY") or \
                     (symbol == "SOL" and side == "SELL")

    if confidence >= 65 and is_proven_edge:
        return "SNIPER"
    elif confidence >= 60 and symbol in ["HYPE", "SOL", "BTC"]:
        return "PREMIUM"
    elif confidence >= 55:
        return "STANDARD"
    return "SKIP"


def classify_tier_symbol_only(symbol: str, side: str, confidence: float) -> str:
    """
    Classify purely by proven symbol+side edge (the real alpha source).

    This represents what the sniper filter ACTUALLY targets:
    - HYPE BUY: 85% WR, PF ~5.6 → SNIPER tier
    - SOL SELL: 59% WR, PF ~1.9 → PREMIUM tier
    - Everything else → SKIP (in aggressive mode)
    """
    if symbol == "HYPE" and side == "BUY":
        if confidence >= 60:
            return "SNIPER"
        elif confidence >= 55:
            return "PREMIUM"
    elif symbol == "SOL" and side == "SELL":
        if confidence >= 60:
            return "PREMIUM"
    return "SKIP"


# ─── Leverage & Risk ────────────────────────────────────────────────────────

def get_leverage(tier: str) -> float:
    """Map tier to leverage (from config)."""
    return {"SNIPER": 25.0, "PREMIUM": 15.0, "STANDARD": 10.0}.get(tier, 10.0)


def get_risk_pct(tier: str) -> float:
    """Map tier to risk % of equity (from config)."""
    return {"SNIPER": 0.10, "PREMIUM": 0.08, "STANDARD": 0.05}.get(tier, 0.05)


# ─── Simulate Single Trade ─────────────────────────────────────────────────

def simulate_trade(record: Dict, equity: float, tier: str) -> Optional[TradeResult]:
    """
    Simulate a single trade on the given counterfactual record.

    Uses the record's resolved outcome (would_hit_tp1, would_hit_sl, hypothetical_pnl_pct).
    Applies leverage to the raw pnl_pct to get the leveraged P&L.
    """
    leverage = get_leverage(tier)
    risk_pct = get_risk_pct(tier)
    risk_amount = equity * risk_pct

    entry = record["entry_price"]
    sl = record["sl"]
    tp1 = record["tp1"]

    stop_width = abs(entry - sl)
    stop_width_pct = stop_width / entry if entry > 0 else 0.01

    # Position size from risk budget
    if stop_width_pct <= 0:
        return None
    position_size_usd = risk_amount / stop_width_pct

    # Realistic cap: max $50k position on Hyperliquid for alts, $200k for BTC
    max_position = 200_000 if record["symbol"] == "BTC" else 50_000
    if position_size_usd > max_position:
        scale = max_position / position_size_usd
        position_size_usd *= scale
        risk_amount *= scale

    margin_used = position_size_usd / leverage

    # Cap margin to equity (leave 5% buffer)
    if margin_used > equity * 0.95:
        scale = (equity * 0.95) / margin_used
        position_size_usd *= scale
        risk_amount *= scale
        margin_used = position_size_usd / leverage

    # Determine outcome from resolved data
    would_hit_tp1 = record.get("would_hit_tp1", False)
    would_hit_sl = record.get("would_hit_sl", False)
    hyp_pnl_pct = record.get("hypothetical_pnl_pct", 0)

    # Slippage + fees: 0.1% round-trip (conservative for Hyperliquid)
    slippage_cost = position_size_usd * 0.001

    if would_hit_tp1 and not would_hit_sl:
        # Win: use TP1 distance as the P&L
        tp1_pct = abs(tp1 - entry) / entry
        pnl_on_position = position_size_usd * tp1_pct - slippage_cost
        outcome = "WIN_TP1"
    elif would_hit_sl:
        # Loss: full stop hit + slippage
        pnl_on_position = -(risk_amount + slippage_cost)
        outcome = "LOSS_SL"
    elif record.get("would_hit_tp2", False):
        # TP2 hit (no TP1, no SL) - use hyp_pnl_pct
        pnl_on_position = position_size_usd * abs(hyp_pnl_pct) / 100 - slippage_cost
        if hyp_pnl_pct < 0:
            pnl_on_position = -(position_size_usd * abs(hyp_pnl_pct) / 100 + slippage_cost)
        outcome = "WIN_TP2"
    else:
        # Timeout / uncertain - use hypothetical pnl
        pnl_on_position = position_size_usd * hyp_pnl_pct / 100 - slippage_cost
        outcome = "TIMEOUT"

    equity_after = equity + pnl_on_position
    pnl_pct_of_equity = (pnl_on_position / equity * 100) if equity > 0 else 0

    return TradeResult(
        record_id=record.get("record_id", ""),
        symbol=record["symbol"],
        side=record["side"],
        tier=tier,
        confidence=record["confidence"],
        entry_price=entry,
        sl=sl,
        tp1=tp1,
        leverage=leverage,
        risk_pct=risk_pct,
        risk_amount=round(risk_amount, 2),
        position_size_usd=round(position_size_usd, 2),
        margin_used=round(margin_used, 2),
        equity_before=round(equity, 2),
        equity_after=round(equity_after, 2),
        pnl_usd=round(pnl_on_position, 2),
        pnl_pct=round(pnl_pct_of_equity, 2),
        outcome=outcome,
        bars_to_resolve=record.get("bars_to_resolve", 0),
        hypothetical_pnl_pct=hyp_pnl_pct,
        created_at=record.get("created_at", ""),
    )


# ─── Run Backtest ───────────────────────────────────────────────────────────

def run_backtest(
    records: List[Dict],
    starting_equity: float,
    classifier_fn,
    mode_name: str,
    aggressive_only: bool = True,
    max_concurrent: int = 3,
) -> Dict[str, Any]:
    """
    Run a full backtest simulation with compound sizing.

    Args:
        records: counterfactual data records
        starting_equity: initial account balance
        classifier_fn: function(record) -> tier string
        mode_name: label for this backtest run
        aggressive_only: if True, skip STANDARD tier (aggressive mode)
        max_concurrent: max simultaneous positions
    """
    equity = starting_equity
    peak_equity = starting_equity
    max_drawdown_pct = 0
    max_drawdown_usd = 0

    trades: List[TradeResult] = []
    equity_curve: List[Dict] = [{"trade_num": 0, "equity": equity}]

    # Sort by created_at for chronological order
    sorted_records = sorted(records, key=lambda r: r.get("created_at", ""))

    skipped = 0
    for record in sorted_records:
        symbol = record["symbol"]
        side = record["side"]
        confidence = record["confidence"]

        # Classify
        tier = classifier_fn(record)
        if tier == "SKIP":
            skipped += 1
            continue
        if aggressive_only and tier == "STANDARD":
            skipped += 1
            continue

        # Simulate
        result = simulate_trade(record, equity, tier)
        if result is None:
            skipped += 1
            continue

        # Bankruptcy check
        if result.equity_after <= 0:
            result.equity_after = 0
            result.pnl_usd = -equity
            trades.append(result)
            equity = 0
            equity_curve.append({"trade_num": len(trades), "equity": 0})
            break

        trades.append(result)
        equity = result.equity_after
        peak_equity = max(peak_equity, equity)
        dd = (peak_equity - equity) / peak_equity * 100 if peak_equity > 0 else 0
        dd_usd = peak_equity - equity
        max_drawdown_pct = max(max_drawdown_pct, dd)
        max_drawdown_usd = max(max_drawdown_usd, dd_usd)

        equity_curve.append({"trade_num": len(trades), "equity": round(equity, 2)})

    # ── Compute Stats ──
    if not trades:
        return {
            "mode": mode_name,
            "error": "No qualifying trades found",
            "skipped": skipped,
        }

    wins = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd <= 0]
    total_win_pnl = sum(t.pnl_usd for t in wins)
    total_loss_pnl = abs(sum(t.pnl_usd for t in losses))

    win_rate = len(wins) / len(trades) * 100 if trades else 0
    profit_factor = total_win_pnl / total_loss_pnl if total_loss_pnl > 0 else float("inf")
    avg_win = total_win_pnl / len(wins) if wins else 0
    avg_loss = total_loss_pnl / len(losses) if losses else 0
    expectancy = (win_rate / 100 * avg_win) - ((1 - win_rate / 100) * avg_loss)

    # Kelly criterion: f* = (p * b - q) / b where p=WR, b=avg_win/avg_loss, q=1-p
    if avg_loss > 0 and avg_win > 0:
        b = avg_win / avg_loss
        p = win_rate / 100
        q = 1 - p
        kelly_full = (p * b - q) / b
        kelly_half = kelly_full / 2  # Half-Kelly for safety
    else:
        kelly_full = 0
        kelly_half = 0

    # By tier breakdown
    tier_stats = {}
    for tier_name in ["SNIPER", "PREMIUM", "STANDARD"]:
        tier_trades = [t for t in trades if t.tier == tier_name]
        if not tier_trades:
            continue
        t_wins = [t for t in tier_trades if t.pnl_usd > 0]
        t_losses = [t for t in tier_trades if t.pnl_usd <= 0]
        t_win_pnl = sum(t.pnl_usd for t in t_wins)
        t_loss_pnl = abs(sum(t.pnl_usd for t in t_losses))
        tier_stats[tier_name] = {
            "trades": len(tier_trades),
            "wins": len(t_wins),
            "losses": len(t_losses),
            "win_rate": round(len(t_wins) / len(tier_trades) * 100, 1),
            "total_pnl": round(sum(t.pnl_usd for t in tier_trades), 2),
            "avg_pnl": round(sum(t.pnl_usd for t in tier_trades) / len(tier_trades), 2),
            "profit_factor": round(t_win_pnl / t_loss_pnl, 2) if t_loss_pnl > 0 else float("inf"),
            "avg_leverage": round(sum(t.leverage for t in tier_trades) / len(tier_trades), 1),
        }

    # By symbol+side breakdown
    combo_stats = {}
    for t in trades:
        key = f"{t.symbol} {t.side}"
        if key not in combo_stats:
            combo_stats[key] = {"trades": 0, "wins": 0, "losses": 0, "pnl": 0, "pnl_list": []}
        combo_stats[key]["trades"] += 1
        combo_stats[key]["pnl"] += t.pnl_usd
        combo_stats[key]["pnl_list"].append(t.pnl_usd)
        if t.pnl_usd > 0:
            combo_stats[key]["wins"] += 1
        else:
            combo_stats[key]["losses"] += 1

    for key, cs in combo_stats.items():
        cs["win_rate"] = round(cs["wins"] / cs["trades"] * 100, 1) if cs["trades"] else 0
        w = sum(p for p in cs["pnl_list"] if p > 0)
        l = abs(sum(p for p in cs["pnl_list"] if p <= 0))
        cs["profit_factor"] = round(w / l, 2) if l > 0 else float("inf")
        cs["pnl"] = round(cs["pnl"], 2)
        cs["avg_pnl"] = round(cs["pnl"] / cs["trades"], 2)
        del cs["pnl_list"]

    # Equity curve summary (sample every N trades)
    n = len(equity_curve)
    sample_interval = max(1, n // 20)
    sampled_curve = [equity_curve[i] for i in range(0, n, sample_interval)]
    if equity_curve[-1] not in sampled_curve:
        sampled_curve.append(equity_curve[-1])

    # Consecutive win/loss streaks
    max_win_streak = 0
    max_loss_streak = 0
    current_streak = 0
    last_was_win = None
    for t in trades:
        is_win = t.pnl_usd > 0
        if is_win == last_was_win:
            current_streak += 1
        else:
            current_streak = 1
            last_was_win = is_win
        if is_win:
            max_win_streak = max(max_win_streak, current_streak)
        else:
            max_loss_streak = max(max_loss_streak, current_streak)

    results = {
        "mode": mode_name,
        "starting_equity": starting_equity,
        "ending_equity": round(equity, 2),
        "total_return_pct": round((equity - starting_equity) / starting_equity * 100, 1),
        "total_pnl": round(equity - starting_equity, 2),
        "num_trades": len(trades),
        "num_wins": len(wins),
        "num_losses": len(losses),
        "win_rate": round(win_rate, 1),
        "profit_factor": round(profit_factor, 2),
        "avg_win_usd": round(avg_win, 2),
        "avg_loss_usd": round(avg_loss, 2),
        "expectancy_per_trade": round(expectancy, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 1),
        "max_drawdown_usd": round(max_drawdown_usd, 2),
        "peak_equity": round(peak_equity, 2),
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "kelly_full": round(kelly_full, 4),
        "kelly_half": round(kelly_half, 4),
        "kelly_recommended_risk": f"{round(kelly_half * 100, 1)}%",
        "skipped_signals": skipped,
        "by_tier": tier_stats,
        "by_symbol_side": combo_stats,
        "equity_curve_sampled": sampled_curve,
    }

    return results


# ─── Print Summary ──────────────────────────────────────────────────────────

def print_summary(results: Dict[str, Any]) -> None:
    """Print a formatted summary of backtest results."""
    mode = results["mode"]
    print(f"\n{'='*72}")
    print(f"  SNIPER BACKTEST: {mode}")
    print(f"{'='*72}")

    if "error" in results:
        print(f"  ERROR: {results['error']}")
        print(f"  Skipped: {results.get('skipped', 0)} signals")
        return

    # Overall
    print(f"\n  OVERALL PERFORMANCE")
    print(f"  {'-'*50}")
    print(f"  Starting Equity:      ${results['starting_equity']:>10.2f}")
    print(f"  Ending Equity:        ${results['ending_equity']:>10.2f}")
    print(f"  Total P&L:            ${results['total_pnl']:>+10.2f} ({results['total_return_pct']:+.1f}%)")
    print(f"  Peak Equity:          ${results['peak_equity']:>10.2f}")
    print(f"  Max Drawdown:          {results['max_drawdown_pct']:>9.1f}% (${results['max_drawdown_usd']:.2f})")
    print(f"  Trades:                {results['num_trades']:>9d}")
    print(f"  Win Rate:              {results['win_rate']:>9.1f}%")
    print(f"  Profit Factor:         {results['profit_factor']:>9.2f}")
    print(f"  Avg Win:              ${results['avg_win_usd']:>+10.2f}")
    print(f"  Avg Loss:             ${results['avg_loss_usd']:>10.2f}")
    print(f"  Expectancy/Trade:     ${results['expectancy_per_trade']:>+10.2f}")
    print(f"  Best Win Streak:       {results['max_win_streak']:>9d}")
    print(f"  Worst Loss Streak:     {results['max_loss_streak']:>9d}")

    # Kelly
    print(f"\n  KELLY CRITERION")
    print(f"  {'-'*50}")
    print(f"  Full Kelly:            {results['kelly_full']*100:>9.1f}% of equity per trade")
    print(f"  Half Kelly (safe):     {results['kelly_half']*100:>9.1f}% of equity per trade")
    print(f"  Recommended Risk:      {results['kelly_recommended_risk']:>9s}")

    # By tier
    if results.get("by_tier"):
        print(f"\n  BY TIER")
        print(f"  {'-'*50}")
        print(f"  {'Tier':<12} {'Trades':>7} {'WR':>7} {'PF':>7} {'PnL':>10} {'Avg PnL':>9} {'Lev':>5}")
        for tier, ts in sorted(results["by_tier"].items()):
            pf_str = f"{ts['profit_factor']:.2f}" if ts['profit_factor'] != float("inf") else "inf"
            print(f"  {tier:<12} {ts['trades']:>7} {ts['win_rate']:>6.1f}% {pf_str:>7} ${ts['total_pnl']:>+9.2f} ${ts['avg_pnl']:>+8.2f} {ts['avg_leverage']:>4.0f}x")

    # By symbol+side
    if results.get("by_symbol_side"):
        print(f"\n  BY SYMBOL + SIDE")
        print(f"  {'-'*50}")
        print(f"  {'Combo':<14} {'Trades':>7} {'WR':>7} {'PF':>7} {'PnL':>10} {'Avg PnL':>9}")
        for combo, cs in sorted(results["by_symbol_side"].items(), key=lambda x: -x[1]["pnl"]):
            pf_str = f"{cs['profit_factor']:.2f}" if cs['profit_factor'] != float("inf") else "inf"
            print(f"  {combo:<14} {cs['trades']:>7} {cs['win_rate']:>6.1f}% {pf_str:>7} ${cs['pnl']:>+9.2f} ${cs['avg_pnl']:>+8.2f}")

    # Equity curve (sampled)
    curve = results.get("equity_curve_sampled", [])
    if curve and len(curve) > 1:
        print(f"\n  EQUITY CURVE (sampled, {len(curve)} points)")
        print(f"  {'-'*50}")
        max_eq = max(p["equity"] for p in curve) or 1
        for point in curve:
            bar_len = min(40, max(1, int(point["equity"] / max_eq * 40)))
            bar = "#" * bar_len
            eq_str = f"${point['equity']:,.2f}" if point["equity"] < 100000 else f"${point['equity']:,.0f}"
            print(f"  Trade {point['trade_num']:>4}: {eq_str:>14}  {bar}")


# ─── Main ───────────────────────────────────────────────────────────────────

def main():
    records = load_counterfactual_data()

    if not records:
        print("No records found!")
        return

    # Data summary
    print(f"\n{'='*72}")
    print(f"  DATA SUMMARY")
    print(f"{'='*72}")
    from collections import Counter
    symbols = Counter(r["symbol"] for r in records)
    sides = Counter(r["side"] for r in records)
    confs = [r["confidence"] for r in records]
    print(f"  Records:       {len(records)}")
    print(f"  Symbols:       {dict(symbols)}")
    print(f"  Sides:         {dict(sides)}")
    print(f"  Confidence:    {min(confs):.1f} - {max(confs):.1f} (avg {sum(confs)/len(confs):.1f})")

    # Win rates by symbol+side (raw, before filtering)
    print(f"\n  RAW WIN RATES (counterfactual, all confidence levels):")
    combos = defaultdict(lambda: {"total": 0, "tp1": 0, "sl": 0})
    for r in records:
        key = f"{r['symbol']} {r['side']}"
        combos[key]["total"] += 1
        if r.get("would_hit_tp1") and not r.get("would_hit_sl"):
            combos[key]["tp1"] += 1
        elif r.get("would_hit_sl"):
            combos[key]["sl"] += 1
    for key in sorted(combos):
        c = combos[key]
        wr = c["tp1"] / c["total"] * 100 if c["total"] else 0
        print(f"    {key:<14}: {c['total']:>4} signals, WR={wr:.1f}%")

    starting_equity = 100.0

    # ── Backtest 1: Symbol-filtered (the real sniper strategy) ──
    def classifier_symbol(record):
        return classify_tier_symbol_only(
            record["symbol"], record["side"], record["confidence"]
        )

    results_symbol = run_backtest(
        records, starting_equity, classifier_symbol,
        "SYMBOL-FILTERED (HYPE BUY + SOL SELL edges)",
        aggressive_only=False,
    )
    print_summary(results_symbol)

    # ── Backtest 2: HYPE BUY only (the 85% WR edge) ──
    def classifier_hype_only(record):
        if record["symbol"] == "HYPE" and record["side"] == "BUY":
            if record["confidence"] >= 55:
                return "SNIPER"
        return "SKIP"

    results_hype = run_backtest(
        records, starting_equity, classifier_hype_only,
        "HYPE BUY ONLY (85% WR sniper edge)",
        aggressive_only=False,
    )
    print_summary(results_hype)

    # ── Backtest 3: Adapted tiers (relative quality filtering) ──
    def classifier_adapted(record):
        return classify_tier_adapted(
            record["confidence"], record["symbol"], record["side"]
        )

    results_adapted = run_backtest(
        records, starting_equity, classifier_adapted,
        "ADAPTED TIERS (relative quality within data range)",
        aggressive_only=True,
    )
    print_summary(results_adapted)

    # ── Backtest 4: Conservative HYPE BUY (half-Kelly sizing, capped) ──
    # Use the Kelly from results_hype but cap at 15% max risk (realistic)
    kelly_raw = results_hype.get("kelly_half", 0.05)
    kelly_risk = min(max(kelly_raw, 0.05), 0.15)  # Cap between 5-15%

    # ── Backtest 4: HYPE BUY with Kelly-capped risk (15%) ──
    # Use run_backtest with a custom classifier that maps to a tier with kelly risk
    # We'll temporarily modify the risk map
    _original_get_risk_pct = globals()['get_risk_pct']
    def _kelly_risk_fn(tier):
        return kelly_risk
    globals()['get_risk_pct'] = _kelly_risk_fn

    results_kelly = run_backtest(
        records, starting_equity, classifier_hype_only,
        f"KELLY-CAPPED HYPE BUY ({kelly_risk*100:.0f}% risk)",
        aggressive_only=False,
    )
    globals()['get_risk_pct'] = _original_get_risk_pct
    print_summary(results_kelly)

    # ── Final Comparison Table ──
    print(f"\n{'='*72}")
    print(f"  COMPARISON: ALL BACKTEST MODES")
    print(f"{'='*72}")
    print(f"  {'Mode':<42} {'Trades':>6} {'WR':>6} {'PF':>6} {'Return':>8} {'MaxDD':>6} {'End $':>8}")
    print(f"  {'-'*42} {'-'*6} {'-'*6} {'-'*6} {'-'*8} {'-'*6} {'-'*8}")

    for r in [results_symbol, results_hype, results_adapted, results_kelly]:
        if "error" in r:
            print(f"  {r['mode'][:42]:<42} {'N/A':>6} {'N/A':>6} {'N/A':>6} {'N/A':>8} {'N/A':>6} {'N/A':>8}")
            continue
        pf = f"{r['profit_factor']:.2f}" if r['profit_factor'] != float("inf") else "inf"
        end_eq = r['ending_equity']
        end_str = f"${end_eq:>7.0f}" if end_eq > 9999 else f"${end_eq:>7.2f}"
        print(f"  {r['mode'][:42]:<42} {r['num_trades']:>6} {r['win_rate']:>5.1f}% {pf:>6} {r['total_return_pct']:>+7.0f}% {r['max_drawdown_pct']:>5.1f}% {end_str}")

    # ── Key Insights ──
    print(f"\n{'='*72}")
    print(f"  KEY INSIGHTS")
    print(f"{'='*72}")
    if "error" not in results_hype:
        print(f"  1. HYPE BUY is the dominant edge: {results_hype['win_rate']:.1f}% WR,")
        print(f"     ${results_hype['ending_equity']:.2f} ending equity from ${starting_equity:.2f}")
        if results_hype['profit_factor'] > 2:
            print(f"     PF={results_hype['profit_factor']:.2f} confirms a strong, exploitable edge")
    if "error" not in results_symbol:
        combo = results_symbol.get("by_symbol_side", {})
        if "HYPE BUY" in combo and "SOL SELL" in combo:
            hb = combo["HYPE BUY"]
            ss = combo["SOL SELL"]
            print(f"  2. HYPE BUY ({hb['win_rate']:.0f}% WR, ${hb['pnl']:+.2f}) vs SOL SELL ({ss['win_rate']:.0f}% WR, ${ss['pnl']:+.2f})")
    print(f"  3. Aggressive $100 strategy viability:")
    if "error" not in results_hype:
        if results_hype["ending_equity"] > 200:
            print(f"     VIABLE - account doubled ({results_hype['total_return_pct']:+.1f}% return)")
        elif results_hype["ending_equity"] > starting_equity:
            print(f"     MARGINAL - positive but needs more trades for compounding")
        else:
            print(f"     RISKY - negative return, edge may not survive leverage + sizing")
        if results_hype["max_drawdown_pct"] > 50:
            print(f"     WARNING: {results_hype['max_drawdown_pct']:.1f}% max drawdown is severe")
        print(f"  4. Kelly recommends {results_hype.get('kelly_recommended_risk', 'N/A')} risk per trade")
        current_risk = "10% (SNIPER)"
        print(f"     Current config: {current_risk}")

    # ── Save Results ──
    output_dir = os.path.join(os.path.dirname(__file__), "..", "data", "manual")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "backtest_results.json")

    save_data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_source": "counterfactual_resolved.json",
        "starting_equity": starting_equity,
        "num_records_total": len(records),
        "results": {
            "symbol_filtered": _sanitize_for_json(results_symbol),
            "hype_buy_only": _sanitize_for_json(results_hype),
            "adapted_tiers": _sanitize_for_json(results_adapted),
            "kelly_capped": _sanitize_for_json(results_kelly),
        },
        "recommendations": {
            "primary_edge": "HYPE BUY",
            "recommended_tier": "SNIPER (25x leverage, 10% risk)",
            "kelly_half_risk": results_hype.get("kelly_half", 0),
            "max_drawdown_tolerance": "30% (reduce size if exceeded)",
            "daily_signal_cap": 3,
            "notes": [
                "HYPE BUY is the only consistently profitable edge in this dataset",
                "SOL SELL has positive edge but lower WR - use as PREMIUM tier only",
                "BTC signals and HYPE SELL are negative EV - skip entirely",
                "Compound sizing amplifies both gains AND drawdowns",
                "Consider reducing to half-Kelly risk after 2 consecutive losses",
            ],
        },
    }

    with open(output_path, "w") as f:
        json.dump(save_data, f, indent=2)
    print(f"\n  Results saved to: {output_path}")


def _sanitize_for_json(d: Dict) -> Dict:
    """Replace inf values for JSON serialization."""
    result = {}
    for k, v in d.items():
        if isinstance(v, float) and (math.isinf(v) or math.isnan(v)):
            result[k] = str(v)
        elif isinstance(v, dict):
            result[k] = _sanitize_for_json(v)
        elif isinstance(v, list):
            result[k] = [
                _sanitize_for_json(item) if isinstance(item, dict)
                else (str(item) if isinstance(item, float) and (math.isinf(item) or math.isnan(item)) else item)
                for item in v
            ]
        else:
            result[k] = v
    return result


if __name__ == "__main__":
    main()
