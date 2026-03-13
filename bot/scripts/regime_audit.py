"""
Regime Detector Accuracy Audit — Validates regime classification quality.

Compares predicted regime labels against actual subsequent price behavior:
  - "trend" → Was there a directional move > 2%?
  - "range"/"consolidation" → Was ATR compressed, no clear direction?
  - "high_volatility" → Was realized vol elevated?

Usage:
    python scripts/regime_audit.py --symbol BTC --days 30
"""

import argparse
import logging
import os
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional

import pandas as pd

# Add parent dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger("bot.scripts.regime_audit")


def classify_actual_regime(df: pd.DataFrame, start_idx: int, forward_bars: int = 12) -> str:
    """Classify the ACTUAL regime from forward price behavior.

    Looks forward_bars (default 12 = 12h on 1h candles) from start_idx
    and classifies based on realized behavior.
    """
    end_idx = min(start_idx + forward_bars, len(df) - 1)
    if end_idx <= start_idx:
        return "unknown"

    segment = df.iloc[start_idx:end_idx + 1]
    if len(segment) < 3:
        return "unknown"

    close = segment["close"]
    returns = close.pct_change().dropna()

    if len(returns) < 2:
        return "unknown"

    # Metrics
    total_move = abs((close.iloc[-1] - close.iloc[0]) / close.iloc[0])
    vol = float(returns.std())
    directional = float(returns.mean())

    # Classification rules
    if vol > 0.03:  # >3% std = high vol
        return "high_volatility"
    elif total_move > 0.02 and abs(directional) > 0.002:  # >2% directional move
        return "trend"
    elif total_move < 0.01 and vol < 0.01:  # <1% move, low vol
        return "consolidation"
    elif vol < 0.015:
        return "range"
    else:
        return "trend" if total_move > 0.015 else "range"


def compute_predicted_regime(df: pd.DataFrame, idx: int) -> str:
    """Compute regime prediction using the same logic as the main bot.

    Mirrors the regime classification in multi_strategy_main.py.
    """
    if idx < 20:
        return "unknown"

    segment = df.iloc[max(0, idx - 20):idx + 1]
    returns = segment["close"].pct_change().tail(20)

    if len(returns) < 5:
        return "unknown"

    vol = float(returns.std() * 100)
    trend_strength = abs(float(returns.tail(10).mean() * 1000)) if len(returns) >= 10 else 0

    if vol > 5:
        return "high_volatility"
    elif trend_strength > 2 and vol > 1.5:
        return "trend"
    elif vol < 1.0:
        return "range"
    elif trend_strength > 1:
        return "trend"
    else:
        return "consolidation"


def run_regime_audit(
    df: pd.DataFrame,
    forward_bars: int = 12,
) -> Dict[str, Any]:
    """Run the full regime audit on OHLCV data.

    Args:
        df: DataFrame with OHLCV columns (must have 'close', 'high', 'low').
        forward_bars: How far ahead to look for "actual" regime classification.

    Returns:
        Audit results with accuracy per regime, confusion matrix, and recommendations.
    """
    if len(df) < forward_bars + 20:
        return {"error": f"Need at least {forward_bars + 20} candles, have {len(df)}"}

    predictions = []
    confusion: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    regime_counts: Dict[str, int] = defaultdict(int)

    for idx in range(20, len(df) - forward_bars):
        predicted = compute_predicted_regime(df, idx)
        actual = classify_actual_regime(df, idx, forward_bars)

        if predicted == "unknown" or actual == "unknown":
            continue

        predictions.append({"predicted": predicted, "actual": actual})
        confusion[predicted][actual] += 1
        regime_counts[predicted] += 1

    if not predictions:
        return {"error": "No valid predictions generated"}

    # Accuracy per predicted regime
    accuracy = {}
    for regime in sorted(regime_counts.keys()):
        correct = confusion[regime].get(regime, 0)
        total = regime_counts[regime]
        accuracy[regime] = {
            "correct": correct,
            "total": total,
            "accuracy": round(correct / total * 100, 1) if total > 0 else 0,
        }

    # Overall accuracy
    total_correct = sum(confusion[r].get(r, 0) for r in regime_counts)
    total_predictions = len(predictions)
    overall_accuracy = round(total_correct / total_predictions * 100, 1) if total_predictions > 0 else 0

    # Distribution
    distribution = {r: round(c / total_predictions * 100, 1) for r, c in regime_counts.items()}

    # Transition accuracy
    transitions = 0
    correct_transitions = 0
    prev_pred = None
    for p in predictions:
        if prev_pred is not None and p["predicted"] != prev_pred:
            transitions += 1
            if p["predicted"] == p["actual"]:
                correct_transitions += 1
        prev_pred = p["predicted"]
    transition_accuracy = round(correct_transitions / transitions * 100, 1) if transitions > 0 else 0

    # Recommendations
    recommendations = []
    for regime, data in accuracy.items():
        if data["accuracy"] < 50 and data["total"] >= 10:
            recommendations.append(
                f"'{regime}' regime has low accuracy ({data['accuracy']}%) — "
                f"consider adjusting thresholds or merging with similar regime"
            )
    if overall_accuracy < 60:
        recommendations.append(
            f"Overall accuracy is {overall_accuracy}% — regime detector needs tuning"
        )
    if not recommendations:
        recommendations.append("Regime detector performing within acceptable parameters")

    return {
        "overall_accuracy": overall_accuracy,
        "total_predictions": total_predictions,
        "accuracy_per_regime": accuracy,
        "distribution": distribution,
        "confusion_matrix": {k: dict(v) for k, v in confusion.items()},
        "transition_accuracy": transition_accuracy,
        "transitions_detected": transitions,
        "recommendations": recommendations,
    }


def format_audit_report(result: Dict[str, Any]) -> str:
    """Format audit results as human-readable text."""
    if "error" in result:
        return f"AUDIT ERROR: {result['error']}"

    lines = [
        "=" * 60,
        "  REGIME DETECTOR ACCURACY AUDIT",
        "=" * 60,
        f"  Overall Accuracy: {result['overall_accuracy']}%",
        f"  Total Predictions: {result['total_predictions']}",
        f"  Transition Accuracy: {result['transition_accuracy']}% ({result['transitions_detected']} transitions)",
        "",
        "  ACCURACY PER REGIME",
        "  " + "-" * 50,
    ]

    for regime, data in sorted(result.get("accuracy_per_regime", {}).items()):
        pct = result.get("distribution", {}).get(regime, 0)
        lines.append(
            f"  {regime:<20s} {data['accuracy']:5.1f}% accuracy  "
            f"({data['correct']}/{data['total']})  [{pct:.1f}% of time]"
        )

    lines.extend(["", "  CONFUSION MATRIX (predicted → actual)", "  " + "-" * 50])
    cm = result.get("confusion_matrix", {})
    all_regimes = sorted(set(k for row in cm.values() for k in row) | set(cm.keys()))
    header = f"  {'predicted':<15s}" + "".join(f" {r[:8]:>8s}" for r in all_regimes)
    lines.append(header)
    for pred in all_regimes:
        row = f"  {pred:<15s}"
        for actual in all_regimes:
            count = cm.get(pred, {}).get(actual, 0)
            row += f" {count:>8d}"
        lines.append(row)

    lines.extend(["", "  RECOMMENDATIONS", "  " + "-" * 50])
    for i, rec in enumerate(result.get("recommendations", []), 1):
        lines.append(f"  {i}. {rec}")

    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Regime Detector Accuracy Audit")
    parser.add_argument("--symbol", default="BTC", help="Symbol to audit")
    parser.add_argument("--days", type=int, default=30, help="Days of data")
    parser.add_argument("--timeframe", default="1h", help="Candle timeframe")
    parser.add_argument("--forward-bars", type=int, default=12, help="Bars to look ahead")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    try:
        from data.fetcher import DataFetcher
        fetcher = DataFetcher()
        df = fetcher.fetch_ohlcv(args.symbol, args.timeframe, limit=args.days * 24)
    except Exception as e:
        print(f"Could not fetch data: {e}")
        print("Loading from CSV fallback...")
        csv_path = f"data/cache/{args.symbol}_{args.timeframe}_{args.days}d.csv"
        if os.path.exists(csv_path):
            df = pd.read_csv(csv_path)
        else:
            print(f"No data available for {args.symbol}")
            sys.exit(1)

    result = run_regime_audit(df, forward_bars=args.forward_bars)
    print(format_audit_report(result))


if __name__ == "__main__":
    main()
