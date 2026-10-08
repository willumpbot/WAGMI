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


VOLERR = BOT / "data" / "laptop_mining" / "vol_error.json"
TOP20_CUT = 3.66   # top-20% boundary of stage-2 predictions on the laptop's test set (VOL_ERROR.md deciles 8|9)


def stage2(pred1_raw, disagree6, funding_day_pct, btc_rv5):
    """VOL_ERROR.md: error-model correction of the raw next-day forecast + top-quintile-only haircut.
    Replaces the old 'x0.8 when high' patch, which under-predicted on average (mean bias -0.39 pts)."""
    e = json.loads(VOLERR.read_text(encoding="utf-8"))
    c = e["stage2_coef"]   # [intercept, disagree, funding, log btc_rv5]
    adj = math.exp(c[0] + c[1] * disagree6 + c[2] * funding_day_pct + c[3] * math.log(btc_rv5 + EPS))
    pred2 = pred1_raw * adj * e["stage2_smearing"]
    return pred2 * 0.8 if pred2 >= TOP20_CUT else pred2


def forecast(closes, disagree6=None, funding_day_pct=None, btc_rv5=None):
    """closes: closed daily closes, oldest first (>= 23). Returns dict of % figures, or None.
    With disagree6/funding/btc_rv5 the next-day figure uses the stage-2 error model (VOL_ERROR.md)."""
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
        if tgt == "y1" and None not in (disagree6, funding_day_pct, btc_rv5):
            try:
                e = json.loads(VOLERR.read_text(encoding="utf-8"))
                raw1 = math.exp(z) * e["stage1_smearing"]
                pred = stage2(raw1, disagree6, funding_day_pct, btc_rv5)
                out["model"] = "HAR + stage-2 error model (VOL_ERROR.md)"
                out["next_day_move_pct"] = round(pred, 2)
                continue
            except Exception:
                pass
        if cut and pred >= cut:
            pred *= 0.8   # fallback calibration when stage-2 inputs are missing
        out["next_day_move_pct" if tgt == "y1" else "next_5d_vol_pct"] = round(pred, 2)
    out.setdefault("model", "HAR (stage 1)")
    return out
