"""Next-day and next-5-day volatility forecast (laptop mission 7, HAR-RV in logs).

Coefficients and smearing factors come from bot/data/laptop_mining/volatility_forecast.json (trained before
2025-06-01, tested after; beats naive persistence out of sample: next-day |move| corr 0.25 vs 0.17, 5-day vol
corr 0.37 vs 0.27, both with positive R2 where persistence is negative). Inputs use closed daily candles only:
  rv1 = |last daily return| %, rv5 = stdev of last 5 daily returns %, rv22 = stdev of last 22.
Top-decile forecasts over-predicted by ~20% on test, so they are shaded down (VOLATILITY.md).
"""
import json
import math
from pathlib import Path

BOT = Path(__file__).resolve().parents[2]
COEF = BOT / "data" / "laptop_mining" / "volatility_forecast.json"
EPS = 1e-8


def _coef():
    return json.loads(COEF.read_text(encoding="utf-8"))


def forecast(closes):
    """closes: closed daily closes, oldest first (>= 23). Returns dict of % figures, or None."""
    if len(closes) < 23:
        return None
    rets = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))]

    def sd(x):
        m = sum(x) / len(x)
        return (sum((v - m) ** 2 for v in x) / (len(x) - 1)) ** 0.5

    rv1, rv5, rv22 = abs(rets[-1]), sd(rets[-5:]), sd(rets[-22:])
    c = _coef()
    out = {"rv1": round(rv1, 2), "rv5": round(rv5, 2), "rv22": round(rv22, 2)}
    for tgt, cut in (("y1", 3.9), ("y5", None)):
        b = c[f"{tgt}_beta"]
        z = b[0] + b[1] * math.log(rv1 + EPS) + b[2] * math.log(rv5 + EPS) + b[3] * math.log(rv22 + EPS)
        pred = math.exp(z) * c[f"{tgt}_smearing"]
        if cut and pred >= cut:
            pred *= 0.8   # calibration: top two deciles over-predicted ~20% on test
        out["next_day_move_pct" if tgt == "y1" else "next_5d_vol_pct"] = round(pred, 2)
    return out
