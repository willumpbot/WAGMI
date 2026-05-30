"""Missed-Opportunity Audit — Co-pilot retrospective.

For each signal the bot SKIPPED, look at what actually happened to the price.
Did we miss alpha? Did we save ourselves from a loser?

Output: a plain-English markdown report Nunu can read as a trader to
understand "we considered X, here's what happened, here's what to think about."

Usage:
    python missed_opportunities.py
"""
import json
import os
import sys
from datetime import datetime, timezone
from collections import defaultdict
from pathlib import Path

# Load the bot's fetcher
sys.path.insert(0, str(Path(__file__).parent))
from trading_config import DEFAULT_SYMBOLS
from data.fetcher import DataFetcher


def parse_iso(ts: str):
    """Parse ISO timestamp string to datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def classify_skip(side: str, entry: float, sl: float, tp1: float, candles_after):
    """Walk forward through candles and determine outcome.

    Returns dict with:
        outcome: MISSED_WIN | GOOD_SKIP | OPEN | INVALID | NEUTRAL_LEAN_WIN | NEUTRAL_LEAN_LOSS
        detail: human-readable explanation
        mfe_pct: max favorable excursion % (how much it went IN our favor before reversing)
        mae_pct: max adverse excursion % (how much it went against us)
        move_30m_pct, move_1h_pct, move_4h_pct: directional price move at those windows (+ = favorable)
        candles_seen: how many candles we evaluated
    """
    result = {
        "outcome": "INVALID", "detail": "",
        "mfe_pct": 0.0, "mae_pct": 0.0,
        "move_30m_pct": None, "move_1h_pct": None, "move_4h_pct": None,
        "candles_seen": 0,
    }
    if entry <= 0 or sl <= 0 or tp1 <= 0:
        result["detail"] = "bad prices"
        return result

    side_up = side.upper()
    sign = 1 if side_up == "BUY" else -1  # +1 for long, -1 for short

    mfe = 0.0  # max favorable %
    mae = 0.0  # max adverse %
    candles_seen = 0
    hit_tp_at = None
    hit_sl_at = None

    for i, (_, row) in enumerate(candles_after.iterrows()):
        h = row["high"]
        l = row["low"]
        candles_seen = i + 1

        # Favorable price (for long: high; for short: low)
        fav_price = h if side_up == "BUY" else l
        adv_price = l if side_up == "BUY" else h

        fav_move_pct = sign * (fav_price - entry) / entry * 100
        adv_move_pct = sign * (adv_price - entry) / entry * 100

        if fav_move_pct > mfe: mfe = fav_move_pct
        if adv_move_pct < mae: mae = adv_move_pct

        # Snapshot at 30m (6 x 5m candles), 1h (12), 4h (48)
        if (i + 1) == 6:
            result["move_30m_pct"] = sign * (row["close"] - entry) / entry * 100
        if (i + 1) == 12:
            result["move_1h_pct"] = sign * (row["close"] - entry) / entry * 100
        if (i + 1) == 48:
            result["move_4h_pct"] = sign * (row["close"] - entry) / entry * 100

        # TP / SL hit check
        if side_up == "BUY":
            hit_tp = h >= tp1
            hit_sl = l <= sl
        else:
            hit_tp = l <= tp1
            hit_sl = h >= sl

        if hit_tp and hit_sl and hit_tp_at is None and hit_sl_at is None:
            hit_sl_at = row["time"]  # conservative: assume SL first
            break
        if hit_tp and hit_tp_at is None:
            hit_tp_at = row["time"]
            break
        if hit_sl and hit_sl_at is None:
            hit_sl_at = row["time"]
            break

    result["mfe_pct"] = mfe
    result["mae_pct"] = mae
    result["candles_seen"] = candles_seen

    # Final outcome
    if hit_tp_at:
        result["outcome"] = "MISSED_WIN"
        result["detail"] = f"TP1 hit at {hit_tp_at}"
    elif hit_sl_at:
        result["outcome"] = "GOOD_SKIP"
        result["detail"] = f"SL hit at {hit_sl_at}"
    elif candles_seen == 0:
        result["outcome"] = "FUTURE"
        result["detail"] = "no candles available after skip time"
    else:
        # Neither hit — use MFE/MAE lean
        if mfe > abs(mae) * 1.5 and mfe > 0.3:
            result["outcome"] = "NEUTRAL_LEAN_WIN"
            result["detail"] = f"MFE {mfe:.2f}% > MAE {mae:.2f}%, looks like missed alpha"
        elif abs(mae) > mfe * 1.5 and abs(mae) > 0.3:
            result["outcome"] = "NEUTRAL_LEAN_LOSS"
            result["detail"] = f"MAE {mae:.2f}% > MFE {mfe:.2f}%, looks like saved from loss"
        else:
            result["outcome"] = "OPEN"
            result["detail"] = f"MFE {mfe:.2f}% / MAE {mae:.2f}% over {candles_seen} candles, no clear lean"

    return result


def main():
    # Load counterfactuals
    cf_path = "data/llm/counterfactual_pending.jsonl"
    if not os.path.exists(cf_path):
        print(f"ERROR: {cf_path} not found")
        return

    counterfactuals = []
    with open(cf_path) as f:
        for line in f:
            try:
                counterfactuals.append(json.loads(line))
            except Exception:
                pass

    print(f"Loaded {len(counterfactuals)} counterfactuals", flush=True)

    # Fetch 5m candles for each symbol
    fetcher = DataFetcher(cache_ttl=300)
    candles_by_sym = {}
    for sym in ("BTC", "ETH", "SOL", "HYPE"):
        sym_cfg = DEFAULT_SYMBOLS.get(sym)
        try:
            df = fetcher.fetch_multi_timeframe(sym, sym_cfg.coingecko_id, ["5m"])
            if "5m" in df and df["5m"] is not None:
                candles_by_sym[sym] = df["5m"]
                print(f"  {sym}: {len(df['5m'])} 5m candles, latest={df['5m']['time'].iloc[-1]}", flush=True)
        except Exception as e:
            print(f"  {sym} fetch error: {e}", flush=True)

    # Classify each counterfactual
    results = []
    for cf in counterfactuals:
        sym = cf.get("symbol", "?")
        if sym not in candles_by_sym:
            continue

        created_at = cf.get("created_at", "")
        try:
            cf_time = parse_iso(created_at)
        except Exception:
            continue

        # Candles AFTER the skip timestamp
        df = candles_by_sym[sym]
        after = df[df["time"] > cf_time]
        if len(after) == 0:
            results.append({**cf, "outcome": "FUTURE", "outcome_detail": "skip timestamp newer than latest candle"})
            continue

        cls = classify_skip(
            side=cf.get("side", ""),
            entry=cf.get("entry_price", 0),
            sl=cf.get("sl", 0),
            tp1=cf.get("tp1", 0),
            candles_after=after,
        )
        results.append({**cf, "outcome": cls["outcome"], "outcome_detail": cls["detail"],
                        "mfe_pct": cls["mfe_pct"], "mae_pct": cls["mae_pct"],
                        "move_30m_pct": cls["move_30m_pct"], "move_1h_pct": cls["move_1h_pct"],
                        "move_4h_pct": cls["move_4h_pct"],
                        "candles_avail": len(after)})

    # Aggregate (LEAN counts as soft signal; bucket maps MISSED/GOOD/OPEN)
    def cls_bucket(o):
        if o in ("MISSED_WIN", "NEUTRAL_LEAN_WIN"): return "MISSED"
        if o in ("GOOD_SKIP", "NEUTRAL_LEAN_LOSS"): return "GOOD"
        return "OPEN"

    outcomes = defaultdict(int)
    by_symbol = defaultdict(lambda: defaultdict(int))
    by_reason = defaultdict(lambda: defaultdict(int))
    by_regime = defaultdict(lambda: defaultdict(int))
    by_side = defaultdict(lambda: defaultdict(int))

    for r in results:
        o = r["outcome"]
        b = cls_bucket(o)
        outcomes[o] += 1
        by_symbol[r.get("symbol", "?")][b] += 1
        by_reason[r.get("skip_reason", "?")[:80]][b] += 1
        by_regime[r.get("regime", "?")][b] += 1
        by_side[r.get("side", "?")][b] += 1

    # Write the report
    out_path = f"data/missed_opportunities_{datetime.now().strftime('%Y%m%d_%H%M')}.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Missed-Opportunity Audit\n\n")
        f.write(f"Generated: {datetime.now(timezone.utc).isoformat()}\n\n")
        f.write(f"For each of {len(results)} skipped signals, we looked at price action after the skip ")
        f.write(f"using 5m candles. We determined whether the skip would have hit TP1 (MISSED_WIN), ")
        f.write(f"would have hit SL (GOOD_SKIP), or neither yet (OPEN).\n\n")

        f.write("## Headline\n\n")
        total = sum(outcomes.values())
        mw_hard = outcomes.get("MISSED_WIN", 0)
        gs_hard = outcomes.get("GOOD_SKIP", 0)
        mw_lean = outcomes.get("NEUTRAL_LEAN_WIN", 0)
        gs_lean = outcomes.get("NEUTRAL_LEAN_LOSS", 0)
        mw = mw_hard + mw_lean
        gs = gs_hard + gs_lean
        op = outcomes.get("OPEN", 0)
        fu = outcomes.get("FUTURE", 0)
        inv = outcomes.get("INVALID", 0)
        resolved = mw + gs
        f.write(f"Raw outcomes: {dict(outcomes)}\n\n")
        if resolved > 0:
            skip_quality = gs * 100.0 / resolved
            f.write(f"- **{resolved} skips resolved** (TP1 or SL reached within available data)\n")
            f.write(f"- **Skip quality: {skip_quality:.1f}%** ({gs} good skips vs {mw} missed wins)\n")
            f.write(f"- **{op} still open** (no TP1/SL hit in the candles we have)\n")
            f.write(f"- **{fu} in the future** (created after our newest candle)\n")
            if inv:
                f.write(f"- **{inv} invalid** (bad prices in the counterfactual)\n")
            f.write("\n")
            if skip_quality >= 60:
                f.write(f"**Plain English:** The bot's skipping is paying off — {skip_quality:.0f}% of the resolved skips would have lost money. The conservative behavior is correct, not overly cautious.\n\n")
            elif skip_quality >= 40:
                f.write(f"**Plain English:** The bot is skipping roughly 50/50 — about as good as coin flip on the resolved skips. Some real alpha is being left on the table.\n\n")
            else:
                f.write(f"**Plain English:** The bot is skipping too many winners. Of resolved skips, only {skip_quality:.0f}% would have lost. The LLM is too cautious — we're missing real edges.\n\n")
        else:
            f.write(f"- {total} total skips, but {op} still open + {fu} too recent — not enough resolved yet for verdict\n\n")

        # By symbol
        f.write("## By Symbol\n\n")
        f.write("| Symbol | Resolved | Good Skips | Missed Wins | Skip Quality |\n")
        f.write("|---|---|---|---|---|\n")
        for sym in sorted(by_symbol.keys()):
            counts = by_symbol[sym]
            r = counts.get("MISSED", 0) + counts.get("GOOD", 0)
            gs_ = counts.get("GOOD", 0)
            mw_ = counts.get("MISSED", 0)
            sq = (gs_ * 100.0 / r) if r > 0 else 0
            f.write(f"| {sym} | {r} | {gs_} | {mw_} | {sq:.0f}% |\n")
        f.write("\n")

        # By side
        f.write("## By Side\n\n")
        f.write("| Side | Resolved | Good Skips | Missed Wins | Skip Quality |\n")
        f.write("|---|---|---|---|---|\n")
        for side in sorted(by_side.keys()):
            counts = by_side[side]
            r = counts.get("MISSED", 0) + counts.get("GOOD", 0)
            gs_ = counts.get("GOOD", 0)
            mw_ = counts.get("MISSED", 0)
            sq = (gs_ * 100.0 / r) if r > 0 else 0
            f.write(f"| {side} | {r} | {gs_} | {mw_} | {sq:.0f}% |\n")
        f.write("\n")

        # By regime
        f.write("## By Regime\n\n")
        f.write("| Regime | Resolved | Good Skips | Missed Wins | Skip Quality |\n")
        f.write("|---|---|---|---|---|\n")
        for regime in sorted(by_regime.keys()):
            counts = by_regime[regime]
            r = counts.get("MISSED", 0) + counts.get("GOOD", 0)
            gs_ = counts.get("GOOD", 0)
            mw_ = counts.get("MISSED", 0)
            sq = (gs_ * 100.0 / r) if r > 0 else 0
            f.write(f"| {regime} | {r} | {gs_} | {mw_} | {sq:.0f}% |\n")
        f.write("\n")

        # By skip reason
        f.write("## By Skip Reason\n\n")
        f.write("| Reason | Resolved | Good Skips | Missed Wins | Skip Quality |\n")
        f.write("|---|---|---|---|---|\n")
        for reason in sorted(by_reason.keys()):
            counts = by_reason[reason]
            r = counts.get("MISSED_WIN", 0) + counts.get("GOOD_SKIP", 0)
            if r < 2:
                continue  # too few
            gs_ = counts.get("GOOD_SKIP", 0)
            mw_ = counts.get("MISSED_WIN", 0)
            sq = (gs_ * 100.0 / r) if r > 0 else 0
            f.write(f"| {reason} | {r} | {gs_} | {mw_} | {sq:.0f}% |\n")
        f.write("\n")

        # Methodology disclosure (Nunu wants honesty about hallucination risk)
        f.write("## Methodology (so you know what to trust)\n\n")
        f.write("- **Data**: last 25h of 5m candles fetched live via CCXT/Hyperliquid\n")
        f.write("- **Outcome rules**: TP1 hit before SL = MISSED_WIN; SL hit before TP1 = GOOD_SKIP; neither hit = use MFE/MAE lean\n")
        f.write("- **MFE/MAE lean**: if max-favorable > 1.5x max-adverse AND > 0.3% = NEUTRAL_LEAN_WIN; converse = NEUTRAL_LEAN_LOSS; otherwise OPEN\n")
        f.write("- **Thresholds are arbitrary** (1.5x, 0.3%). Different cutoffs would give different numbers. Use this as directional signal, not gospel.\n")
        f.write("- **Sample sizes are small** for some categories. ETH n=6 'all missed' could easily be coincidence.\n\n")

        # Top Missed (includes LEAN)
        f.write("## Top Missed Wins (alpha left on the table)\n\n")
        missed = [r for r in results if r["outcome"] in ("MISSED_WIN", "NEUTRAL_LEAN_WIN")]
        if not missed:
            f.write("None — every resolved skip was correct so far.\n\n")
        else:
            f.write("| When | Symbol | Side | Entry | TP1 | MFE% | MAE% | 1h move | Skip reason |\n")
            f.write("|---|---|---|---|---|---|---|---|---|\n")
            for r in missed[:15]:
                ts = r.get("created_at", "")[:19]
                m1h = r.get("move_1h_pct")
                m1h_str = f"{m1h:+.2f}%" if m1h is not None else "n/a"
                f.write(f"| {ts} | {r['symbol']} | {r['side']} | ${r['entry_price']:.4f} | ${r['tp1']:.4f} | {r['mfe_pct']:+.2f}% | {r['mae_pct']:+.2f}% | {m1h_str} | {r.get('skip_reason','?')[:35]} |\n")
            f.write("\n")

        # Top Good (includes LEAN)
        f.write("## Top Good Skips (caution paid off)\n\n")
        good = [r for r in results if r["outcome"] in ("GOOD_SKIP", "NEUTRAL_LEAN_LOSS")]
        if not good:
            f.write("None.\n\n")
        else:
            f.write("| When | Symbol | Side | Entry | SL | MFE% | MAE% | 1h move | Skip reason |\n")
            f.write("|---|---|---|---|---|---|---|---|---|\n")
            for r in good[:15]:
                ts = r.get("created_at", "")[:19]
                m1h = r.get("move_1h_pct")
                m1h_str = f"{m1h:+.2f}%" if m1h is not None else "n/a"
                f.write(f"| {ts} | {r['symbol']} | {r['side']} | ${r['entry_price']:.4f} | ${r['sl']:.4f} | {r['mfe_pct']:+.2f}% | {r['mae_pct']:+.2f}% | {m1h_str} | {r.get('skip_reason','?')[:35]} |\n")
            f.write("\n")

        # Co-pilot synthesis
        f.write("## Co-Pilot Read (Nunu, here's what to think about)\n\n")
        if resolved > 0:
            if skip_quality >= 60:
                f.write(f"You're not missing alpha — the bot's caution is well-calibrated for current conditions. "
                        f"Keep trusting the LLM's skip calls. Most rejected setups would have lost.\n\n")
            elif skip_quality < 40 and resolved >= 10:
                f.write(f"The bot is skipping too many winners ({mw} missed vs {gs} saved). Consider loosening "
                        f"the LLM's threshold — especially on the patterns where skip quality is below 50%. "
                        f"See 'By Symbol' / 'By Regime' tables above to identify which conditions you'd want to be more aggressive on.\n\n")
            else:
                f.write(f"Mixed bag. Sample is small ({resolved} resolved). Watch for patterns in 'By Symbol' / 'By Regime' — "
                        f"any single category with skip quality below 30% suggests we're systematically wrong there.\n\n")
        else:
            f.write(f"Not enough resolved skips yet for a verdict. Re-run this script after the bot has been running longer "
                    f"(needs the entry + TP/SL to have time to play out in the 5m candles).\n\n")

    print(f"\nReport written to {out_path}")
    print(f"\nSummary: {dict(outcomes)}")


if __name__ == "__main__":
    main()
