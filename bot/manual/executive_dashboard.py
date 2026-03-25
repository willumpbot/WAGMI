"""
Executive Dashboard — One-screen view of the sniper system.

Pulls together all key metrics from research data.
Run: cd bot && python -m manual.executive_dashboard

Designed to be the FIRST thing the user sees when they wake up.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict


def load_json(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except:
        try:
            with open(path) as f:
                return json.load(f)
        except:
            return default


def load_jsonl(path, since_ts=0):
    records = []
    if not os.path.exists(path):
        return records
    with open(path) as f:
        for line in f:
            if line.strip():
                try:
                    rec = json.loads(line)
                    if since_ts and rec.get('ts', 0) < since_ts:
                        continue
                    records.append(rec)
                except:
                    pass
    return records


def main():
    now = datetime.now(timezone.utc)
    since_12h = (now - timedelta(hours=12)).timestamp()

    print("=" * 70)
    print("   WAGMI SNIPER SYSTEM - EXECUTIVE DASHBOARD")
    print(f"   {now.strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)

    # 1. Signal Activity
    print("\n--- SIGNAL ACTIVITY (last 12h) ---")
    outcomes = load_jsonl("data/logs/signal_outcomes.jsonl", since_12h)
    recent_sniper = load_jsonl("data/manual/sniper_signals.jsonl")

    by_setup = Counter(f"{s['sym']}_{s['side']}" for s in outcomes)
    print(f"Total signals: {len(outcomes)}")
    for setup, count in by_setup.most_common():
        print(f"  {setup}: {count}")

    hype_buys = [s for s in outcomes if s['sym'] == 'HYPE' and s['side'] == 'BUY']
    print(f"\nHYPE BUY (our edge):")
    print(f"  Signals: {len(hype_buys)}")
    if hype_buys:
        avg_conf = sum(s['conf'] for s in hype_buys) / len(hype_buys)
        avg_chop = sum(s.get('meta', {}).get('chop_score_smoothed', 0) for s in hype_buys) / len(hype_buys)
        print(f"  Avg confidence: {avg_conf:.0f}%")
        print(f"  Avg chop: {avg_chop:.3f}")
        passes = sum(1 for s in hype_buys if s.get('meta', {}).get('chop_score_smoothed', 0) <= 0.4)
        print(f"  Pass new filter: {passes}/{len(hype_buys)} ({passes/max(len(hype_buys),1)*100:.0f}%)")

    # 2. Win Rate Summary
    print("\n--- WIN RATE ESTIMATES ---")
    print("  Source          | HYPE BUY WR | SOL SELL WR")
    print("  ----------------+-------------+-----------")
    print("  Counterfactual  | 85.1%       | 58.7%     ")
    print("  PA Simulator    | 71.4%       | N/A       ")
    print("  Planning (safe) | 64.3%       | 55.0%     ")
    print("  * Use planning WR for all projections")

    # 3. Key Findings
    print("\n--- KEY FINDINGS (from overnight research) ---")
    print("  1. HYPE BUY at $39+ = 0% WR (all 14 losers at high prices)")
    print("  2. Fast resolution (1-3 bars) = 91.2% WR vs medium (4-8) = 0%")
    print("  3. Lower confidence = HIGHER WR (conf 56-58% = 92.2% WR best)")
    print("  4. Signals come in bursts of ~32. Enter on 2nd-3rd, not 1st")
    print("  5. Current 10% risk is near-optimal (0% ruin all scenarios)")

    # 4. Risk Summary
    print("\n--- RISK PROJECTIONS ($100 account) ---")
    mc = load_json("data/manual/realistic_mc_with_costs.json", {})
    if mc and 'results' in mc:
        print("  Scenario              | Median 90d | Days to $1K | Ruin")
        print("  ----------------------+------------+-------------+-----")
        for label, data in mc['results'].items():
            short_label = label[:22]
            d1k = data.get('days_1000', 'N/A')
            print(f"  {short_label:<22} | ${data['median']:>8,.0f} | {d1k:>9}d  | {data['ruin']}%")

    # 5. Current Risk Zone
    print("\n--- CURRENT RISK ASSESSMENT ---")
    if hype_buys:
        # Infer current HYPE price from recent sniper signals
        sniper_hype = [s for s in recent_sniper if s.get('symbol') == 'HYPE']
        if sniper_hype:
            latest_price = sniper_hype[-1].get('entry', 0)
            if latest_price >= 39:
                print(f"  HYPE price: ~${latest_price:.0f} -- DANGER ZONE (0% WR above $39 in CF data)")
                print("  RECOMMENDATION: Wait for a dip before entering HYPE BUY")
            elif latest_price >= 37:
                print(f"  HYPE price: ~${latest_price:.0f} -- CAUTION (55% WR at $37-39)")
                print("  RECOMMENDATION: Enter with reduced size")
            else:
                print(f"  HYPE price: ~${latest_price:.0f} -- GREEN ZONE (100% WR below $37)")
                print("  RECOMMENDATION: Full size on next burst")

    # 6. Dedup Status
    print("\n--- SYSTEM HEALTH ---")
    if recent_sniper:
        total = len(recent_sniper)
        unique = len(set(s.get('timestamp', '')[:16] for s in recent_sniper))
        dup_rate = (1 - unique / max(total, 1)) * 100
        print(f"  Sniper signals logged: {total}")
        print(f"  Unique (per-minute): {unique}")
        print(f"  Duplicate rate: {dup_rate:.0f}% {'-- NEEDS BOT RESTART' if dup_rate > 50 else ''}")

    # 7. What to Read
    print("\n--- REPORTS TO READ ---")
    print("  1. data/manual/OVERNIGHT_SUMMARY.md  -- Start here")
    print("  2. data/manual/MORNING_BRIEFING.md    -- Overnight signal activity")
    print("  3. data/manual/SNIPER_LEARNINGS.md    -- All findings")
    print("  4. data/manual/EDGE_DISCOVERY.md      -- WR reconciliation")
    print("  5. data/manual/DIP_BUY_ANALYSIS.md    -- Dip-buy patterns")
    print("  6. data/manual/RISK_OPTIMIZATION.md   -- Risk & Kelly analysis")

    # 8. Action Items
    print("\n--- ACTION ITEMS ---")
    print("  [ ] Restart bot to fix sniper signal dedup (91% duplicates)")
    print("  [ ] Consider adding 3-hour time-stop to HYPE BUY trades")
    print("  [ ] Update playbook WR from 85% to 64-71%")
    print("  [ ] Be cautious with HYPE BUY at current price level ($40)")
    print("  [ ] Run: python -m manual.overnight_report for fresh briefing")

    print("\n" + "=" * 70)
    print("   End of Dashboard")
    print("=" * 70)


if __name__ == "__main__":
    main()
