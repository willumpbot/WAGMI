"""Cross-venue funding + HL open-interest-cap snapshot, every 15-min cycle (angle map 10-15 #4 and #19).

Neither is backfillable: HL's predictedFundings shows HL / Binance / Bybit next funding side by side only NOW, and
perpsAtOpenInterestCap lists the coins at maximum crowding only NOW. One row per cycle to
data/hivemind/venue_funding.jsonl: {ts, oi_cap: [coins], f: {coin: {"hl": r, "bin": r, "bybit": r}}} with every rate
converted to PER HOUR so venues with 1h / 4h / 8h intervals compare directly. Public read-only data.
"""
import json
import time
from pathlib import Path

import hl

OUT = Path(__file__).resolve().parents[2] / "data" / "hivemind" / "venue_funding.jsonl"
VENUE = {"HlPerp": "hl", "BinPerp": "bin", "BybitPerp": "bybit"}


def run():
    f = {}
    for coin, venues in hl.post({"type": "predictedFundings"}, ttl=60) or []:
        row = {}
        for v, d in venues or []:
            if v in VENUE and d and d.get("fundingRate") is not None:
                row[VENUE[v]] = round(float(d["fundingRate"]) / float(d.get("fundingIntervalHours") or 1), 9)
        if row:
            f[coin] = row
    try:
        cap = hl.post({"type": "perpsAtOpenInterestCap"}, ttl=60) or []
    except Exception:
        cap = None
    rec = {"ts": round(time.time()), "oi_cap": cap, "f": f}
    with open(OUT, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
    return {"coins": len(f), "oi_cap": len(cap or [])}


if __name__ == "__main__":
    print(run())
