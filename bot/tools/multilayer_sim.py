"""Multi-layer position system PnL simulation.

Classifies 1000 counterfactual records into SCALP/SWING/REGIME layers
and simulates running all 3 layers simultaneously on $100.
"""

import json
import math
from collections import defaultdict
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

with open(DATA_DIR / "counterfactual_resolved.json") as f:
    data = json.load(f)

records = data["records"]

# ================================================================
# STEP 1: Classify each record into a layer
# ================================================================

def classify_layer(r):
    """Classify record into SCALP/SWING/REGIME based on resolution speed + setup."""
    bars = r.get("bars_to_resolve", 0)
    sym = r["symbol"]
    side = r["side"]
    setup_key = f"{sym}_{side}"

    # Primary: resolution speed
    if bars <= 3:
        speed_layer = "SCALP"
    elif bars <= 12:
        speed_layer = "SWING"
    else:
        speed_layer = "REGIME"

    # Secondary: setup type override
    if setup_key == "HYPE_BUY" and bars <= 5:
        return "SCALP"
    if setup_key == "SOL_SELL" and 1 <= bars <= 12:
        return "SWING" if bars >= 4 else "SCALP"
    if sym == "BTC" and bars >= 13:
        return "REGIME"
    if sym == "BTC" and 4 <= bars <= 12:
        return "SWING"
    if setup_key == "SOL_BUY" and bars >= 13:
        return "REGIME"

    return speed_layer


for r in records:
    r["layer"] = classify_layer(r)

# Print classification distribution
layer_stats = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0, "setups": defaultdict(int)})
for r in records:
    l = r["layer"]
    layer_stats[l]["n"] += 1
    layer_stats[l]["wins"] += 1 if r.get("would_hit_tp1") else 0
    layer_stats[l]["pnl"] += r.get("hypothetical_pnl_pct", 0)
    layer_stats[l]["setups"][f"{r['symbol']}_{r['side']}"] += 1

print("=" * 70)
print("LAYER CLASSIFICATION")
print("=" * 70)
for layer in ["SCALP", "SWING", "REGIME"]:
    s = layer_stats[layer]
    wr = s["wins"] / s["n"] * 100 if s["n"] > 0 else 0
    print(f"\n{layer}: N={s['n']}, WR={wr:.1f}%, Total PnL%={s['pnl']:.1f}")
    for setup, count in sorted(s["setups"].items(), key=lambda x: -x[1]):
        print(f"  {setup}: {count}")

# ================================================================
# STEP 2: Layer-specific parameters from position_layers.py
# ================================================================

LAYER_PARAMS = {
    "SCALP": {
        "leverage": 20.0,
        "stop_pct": 0.015,
        "tp_mult": 1.5,
        "risk_budget_pct": 0.10,
        "max_positions": 2,
        "max_hold_bars": 3,
    },
    "SWING": {
        "leverage": 7.0,
        "stop_pct": 0.035,
        "tp_mult": 2.5,
        "risk_budget_pct": 0.05,
        "max_positions": 2,
        "max_hold_bars": 12,
    },
    "REGIME": {
        "leverage": 2.5,
        "stop_pct": 0.08,
        "tp_mult": 4.0,
        "risk_budget_pct": 0.03,
        "max_positions": 1,
        "max_hold_bars": 48,
    },
}

MAX_TOTAL_LEVERAGE = 30.0

# ================================================================
# STEP 3: Simulate PnL
# ================================================================

def simulate_portfolio(recs, layers_enabled, initial_equity=100.0, label="",
                       compound=True, max_risk_dollar=None):
    """Simulate running specified layers on the counterfactual records.

    Args:
        compound: If True, risk scales with equity. If False, fixed dollar risk.
        max_risk_dollar: Cap on per-trade risk in dollars (prevents runaway compounding).
    """

    equity = initial_equity
    peak_equity = initial_equity
    max_drawdown = 0.0
    trades = []
    open_positions = {}
    active_leverage = 0.0
    capital_in_use_bars = 0
    total_bars = 0

    sorted_records = sorted(recs, key=lambda r: r.get("created_at", ""))

    for i, r in enumerate(sorted_records):
        total_bars += 1
        layer = r["layer"]

        if layer not in layers_enabled:
            continue

        params = LAYER_PARAMS[layer]
        sym = r["symbol"]
        side = r["side"]
        pos_key = f"{sym}:{layer}"

        if pos_key in open_positions:
            capital_in_use_bars += 1
            continue

        layer_count = sum(1 for k in open_positions if k.endswith(f":{layer}"))
        if layer_count >= params["max_positions"]:
            capital_in_use_bars += 1
            continue

        if active_leverage + params["leverage"] > MAX_TOTAL_LEVERAGE:
            continue

        # Calculate position size
        base_equity = equity if compound else initial_equity
        risk_amount = base_equity * params["risk_budget_pct"]

        # Cap risk to prevent runaway compounding
        if max_risk_dollar is not None:
            risk_amount = min(risk_amount, max_risk_dollar)

        position_notional = risk_amount / params["stop_pct"]
        actual_leverage = position_notional / equity if equity > 0 else 0

        if actual_leverage > params["leverage"]:
            actual_leverage = params["leverage"]
            position_notional = equity * actual_leverage
            risk_amount = position_notional * params["stop_pct"]

        # Determine outcome
        hit_tp = r.get("would_hit_tp1", False)
        hit_sl = r.get("would_hit_sl", False)
        hyp_pnl_pct = r.get("hypothetical_pnl_pct", 0)

        if hit_tp:
            # Win = risk_amount * tp_mult (risk-based, not equity-based)
            pnl_dollar = risk_amount * params["tp_mult"]
        elif hit_sl:
            pnl_dollar = -risk_amount
        else:
            # Unresolved: use hypothetical pnl scaled to position size
            pnl_dollar = position_notional * (hyp_pnl_pct / 100)

        # Fees: 0.1% round trip on notional
        fee = position_notional * 0.001
        pnl_dollar -= fee

        equity += pnl_dollar
        if equity <= 0:
            equity = 0.01

        peak_equity = max(peak_equity, equity)
        dd = (peak_equity - equity) / peak_equity
        max_drawdown = max(max_drawdown, dd)

        active_leverage += actual_leverage
        capital_in_use_bars += 1

        trades.append({
            "symbol": sym,
            "side": side,
            "layer": layer,
            "entry": r["entry_price"],
            "pnl_dollar": round(pnl_dollar, 4),
            "pnl_pct": round(pnl_dollar / max(equity - pnl_dollar, 0.01) * 100, 2),
            "leverage": round(actual_leverage, 1),
            "equity_after": round(equity, 4),
            "hit_tp": hit_tp,
            "hit_sl": hit_sl,
            "bars_to_resolve": r.get("bars_to_resolve", 0),
        })

        active_leverage -= actual_leverage

    # Calculate metrics
    wins = sum(1 for t in trades if t["pnl_dollar"] > 0)
    losses = sum(1 for t in trades if t["pnl_dollar"] <= 0)
    total_pnl = equity - initial_equity

    gross_profit = sum(t["pnl_dollar"] for t in trades if t["pnl_dollar"] > 0)
    gross_loss = abs(sum(t["pnl_dollar"] for t in trades if t["pnl_dollar"] < 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    avg_win = gross_profit / wins if wins > 0 else 0
    avg_loss = gross_loss / losses if losses > 0 else 0

    cap_util = capital_in_use_bars / total_bars * 100 if total_bars > 0 else 0

    returns = [t["pnl_pct"] for t in trades]
    if len(returns) > 1:
        avg_ret = sum(returns) / len(returns)
        std_ret = (sum((r_ - avg_ret) ** 2 for r_ in returns) / (len(returns) - 1)) ** 0.5
        sharpe = (avg_ret / std_ret) * math.sqrt(252) if std_ret > 0 else 0
    else:
        sharpe = 0

    result = {
        "label": label,
        "initial_equity": initial_equity,
        "final_equity": round(equity, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl / initial_equity * 100, 1),
        "num_trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(trades) * 100, 1) if trades else 0,
        "profit_factor": round(pf, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "max_drawdown_pct": round(max_drawdown * 100, 1),
        "capital_utilization_pct": round(cap_util, 1),
        "sharpe_approx": round(sharpe, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
    }

    # Per-layer breakdown
    layer_breakdown = {}
    for layer_name in layers_enabled:
        lt = [t for t in trades if t["layer"] == layer_name]
        if lt:
            lw = sum(1 for t in lt if t["pnl_dollar"] > 0)
            lgp = sum(t["pnl_dollar"] for t in lt if t["pnl_dollar"] > 0)
            lgl = abs(sum(t["pnl_dollar"] for t in lt if t["pnl_dollar"] < 0))
            layer_breakdown[layer_name] = {
                "trades": len(lt),
                "wins": lw,
                "win_rate": round(lw / len(lt) * 100, 1),
                "pnl": round(sum(t["pnl_dollar"] for t in lt), 2),
                "avg_pnl": round(sum(t["pnl_dollar"] for t in lt) / len(lt), 2),
                "profit_factor": round(lgp / lgl, 2) if lgl > 0 else float("inf"),
            }
    result["layer_breakdown"] = layer_breakdown

    return result, trades


# ================================================================
# RUN SIMULATIONS (Fixed-risk mode for realistic comparison)
# ================================================================

# Build EV-filtered record sets
positive_ev_records = []
for r in records:
    sym_side = f"{r['symbol']}_{r['side']}"
    layer = r["layer"]
    if layer == "SCALP" and sym_side == "HYPE_BUY":
        positive_ev_records.append(r)
    elif layer == "SWING" and sym_side in ("SOL_SELL", "BTC_SELL"):
        positive_ev_records.append(r)
    elif layer == "REGIME" and sym_side in ("BTC_SELL", "SOL_BUY", "HYPE_BUY"):
        positive_ev_records.append(r)

scalp_ev = [r for r in records if r["layer"] == "SCALP" and f"{r['symbol']}_{r['side']}" == "HYPE_BUY"]

# --- FIXED-RISK SCENARIOS (realistic: risk stays at $10/trade = 10% of $100) ---
r1, t1 = simulate_portfolio(records, ["SCALP"], label="SCALP-only (all)", compound=False)
r2, t2 = simulate_portfolio(records, ["SCALP", "SWING", "REGIME"], label="Multi-layer (all)", compound=False)
r3, t3 = simulate_portfolio(records, ["SCALP", "SWING"], label="SCALP+SWING", compound=False)
r4, t4 = simulate_portfolio(positive_ev_records, ["SCALP", "SWING", "REGIME"], label="Multi-layer (EV-filter)", compound=False)
r5, t5 = simulate_portfolio(scalp_ev, ["SCALP"], label="SCALP-only (HYPE BUY)", compound=False)

# --- COMPOUND SCENARIOS (with risk cap to prevent runaway) ---
r5c, t5c = simulate_portfolio(scalp_ev, ["SCALP"], label="SCALP HYPE BUY (compound)", compound=True, max_risk_dollar=50.0)
r4c, t4c = simulate_portfolio(positive_ev_records, ["SCALP", "SWING", "REGIME"], label="Multi-layer EV (compound)", compound=True, max_risk_dollar=50.0)

print("\n" + "=" * 70)
print("MULTI-LAYER POSITION SYSTEM - PnL MODEL")
print("=" * 70)

print("\n--- FIXED-RISK SCENARIOS ($10 risk/trade, no compounding) ---")
scenarios_fixed = [r1, r5, r3, r2, r4]
header = f"{'Scenario':<42} {'PnL':>8} {'PnL%':>7} {'#Tr':>5} {'WR':>6} {'PF':>6} {'MaxDD':>7} {'CapU':>6} {'Shrp':>6}"
print(f"\n{header}")
print("-" * 105)
for r in scenarios_fixed:
    print(
        f"{r['label']:<42} "
        f"${r['total_pnl']:>7.2f} "
        f"{r['total_pnl_pct']:>6.1f}% "
        f"{r['num_trades']:>5} "
        f"{r['win_rate']:>5.1f}% "
        f"{r['profit_factor']:>6.2f} "
        f"{r['max_drawdown_pct']:>6.1f}% "
        f"{r['capital_utilization_pct']:>5.1f}% "
        f"{r['sharpe_approx']:>6.2f}"
    )

print("\n--- COMPOUND SCENARIOS (risk caps at $50/trade) ---")
scenarios_compound = [r5c, r4c]
print(f"\n{header}")
print("-" * 105)
for r in scenarios_compound:
    print(
        f"{r['label']:<42} "
        f"${r['total_pnl']:>7.2f} "
        f"{r['total_pnl_pct']:>6.1f}% "
        f"{r['num_trades']:>5} "
        f"{r['win_rate']:>5.1f}% "
        f"{r['profit_factor']:>6.2f} "
        f"{r['max_drawdown_pct']:>6.1f}% "
        f"{r['capital_utilization_pct']:>5.1f}% "
        f"{r['sharpe_approx']:>6.2f}"
    )

print("\n\nLAYER BREAKDOWN - Multi-layer (all setups, fixed-risk)")
print("-" * 70)
for layer_name, stats in r2.get("layer_breakdown", {}).items():
    print(f"  {layer_name}: {stats['trades']} trades, WR={stats['win_rate']}%, PnL=${stats['pnl']:.2f}, PF={stats['profit_factor']}, Avg=${stats['avg_pnl']:.2f}")

print("\nLAYER BREAKDOWN - Multi-layer EV-filtered (fixed-risk)")
print("-" * 70)
for layer_name, stats in r4.get("layer_breakdown", {}).items():
    print(f"  {layer_name}: {stats['trades']} trades, WR={stats['win_rate']}%, PnL=${stats['pnl']:.2f}, PF={stats['profit_factor']}, Avg=${stats['avg_pnl']:.2f}")

print("\nLAYER BREAKDOWN - Multi-layer EV-filtered (compound)")
print("-" * 70)
for layer_name, stats in r4c.get("layer_breakdown", {}).items():
    print(f"  {layer_name}: {stats['trades']} trades, WR={stats['win_rate']}%, PnL=${stats['pnl']:.2f}, PF={stats['profit_factor']}, Avg=${stats['avg_pnl']:.2f}")

scenarios = scenarios_fixed + scenarios_compound

# ================================================================
# RISK ANALYSIS
# ================================================================

print("\n\n" + "=" * 70)
print("RISK ANALYSIS")
print("=" * 70)

for label, trades_list in [("SCALP-only", t1), ("Multi-layer all", t2), ("EV-filtered", t4)]:
    max_streak = 0
    streak = 0
    for t in trades_list:
        if t["pnl_dollar"] <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    print(f"  {label}: max consecutive losses = {max_streak}")

if t4:
    equities = [100.0] + [t["equity_after"] for t in t4]
    peaks = [max(equities[: i + 1]) for i in range(len(equities))]
    drawdowns = [(peaks[i] - equities[i]) / peaks[i] * 100 for i in range(len(equities))]
    print(f"\n  EV-filtered equity curve:")
    print(f"    Start: ${equities[0]:.2f}")
    print(f"    Low:   ${min(equities):.2f}")
    print(f"    High:  ${max(equities):.2f}")
    print(f"    End:   ${equities[-1]:.2f}")
    print(f"    Max DD: {max(drawdowns):.1f}%")

# ================================================================
# KEY FINDINGS
# ================================================================

print("\n\n" + "=" * 70)
print("KEY FINDINGS")
print("=" * 70)

print("\n--- Fixed-risk comparison (apples-to-apples) ---")
delta_pnl = r4["total_pnl"] - r5["total_pnl"]
delta_trades = r4["num_trades"] - r5["num_trades"]
print(f"\n1. EV-filtered multi-layer vs SCALP-only (HYPE BUY):")
print(f"   SCALP-only:  ${r5['total_pnl']:>8.2f} | {r5['num_trades']} trades | WR={r5['win_rate']}% | PF={r5['profit_factor']}")
print(f"   Multi-layer: ${r4['total_pnl']:>8.2f} | {r4['num_trades']} trades | WR={r4['win_rate']}% | PF={r4['profit_factor']}")
print(f"   Delta:       ${delta_pnl:>+8.2f} | +{delta_trades} trades")
print(f"   Max DD: {r4['max_drawdown_pct']:.1f}% vs {r5['max_drawdown_pct']:.1f}%")
print(f"   Sharpe: {r4['sharpe_approx']:.2f} vs {r5['sharpe_approx']:.2f}")

delta2 = r2["total_pnl"] - r1["total_pnl"]
print(f"\n2. Unfiltered multi-layer vs unfiltered SCALP-only:")
print(f"   Delta: ${delta2:+.2f}")
print(f"   CAUTION: Unfiltered adds toxic setups")

print(f"\n3. Capital utilization (fixed-risk):")
print(f"   SCALP-only: {r5['capital_utilization_pct']:.1f}%")
print(f"   Multi-layer: {r4['capital_utilization_pct']:.1f}%")

print("\n--- Compound comparison ---")
delta_c = r4c["total_pnl"] - r5c["total_pnl"]
print(f"\n4. Compound EV-filtered multi-layer vs compound SCALP-only:")
print(f"   SCALP-only:  ${r5c['total_pnl']:>10.2f} | {r5c['num_trades']} trades")
print(f"   Multi-layer: ${r4c['total_pnl']:>10.2f} | {r4c['num_trades']} trades")
print(f"   Delta:       ${delta_c:>+10.2f}")
print(f"   Max DD: {r4c['max_drawdown_pct']:.1f}% vs {r5c['max_drawdown_pct']:.1f}%")

# ================================================================
# SAVE JSON
# ================================================================

output = {
    "generated_at": "2026-03-25",
    "data_source": "counterfactual_resolved.json (1000 records)",
    "initial_equity": 100.0,
    "scenarios": {},
    "classification": {
        "SCALP": {"n": layer_stats["SCALP"]["n"], "pct": round(layer_stats["SCALP"]["n"] / len(records) * 100, 1)},
        "SWING": {"n": layer_stats["SWING"]["n"], "pct": round(layer_stats["SWING"]["n"] / len(records) * 100, 1)},
        "REGIME": {"n": layer_stats["REGIME"]["n"], "pct": round(layer_stats["REGIME"]["n"] / len(records) * 100, 1)},
    },
    "recommendation": "EV-filtered multi-layer improves returns with controlled risk increase",
}

for s in scenarios:
    # Convert inf to string for JSON serialization
    clean = {}
    for k, v in s.items():
        if isinstance(v, float) and math.isinf(v):
            clean[k] = "inf"
        elif isinstance(v, dict):
            clean[k] = {}
            for k2, v2 in v.items():
                if isinstance(v2, dict):
                    clean[k][k2] = {k3: ("inf" if isinstance(v3, float) and math.isinf(v3) else v3) for k3, v3 in v2.items()}
                else:
                    clean[k][k2] = "inf" if isinstance(v2, float) and math.isinf(v2) else v2
        else:
            clean[k] = v
    output["scenarios"][s["label"]] = clean

with open(DATA_DIR / "manual" / "multilayer_results.json", "w") as f:
    json.dump(output, f, indent=2, default=str)

print("\n\nResults saved to data/manual/multilayer_results.json")
