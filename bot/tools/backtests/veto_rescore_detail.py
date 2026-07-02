import json, csv, statistics

res = json.load(open(r"C:\Users\vince\WAGMI\bot\tools\backtests\veto_rescore_results.json"))
rules = {r["rule_id"]: r for r in res["rules"]}
key = ["hype_long_veto_v1", "sol_long_veto_v1", "night_session_block_v1",
       "conf_floor_70_v1", "hype_short_veto_v1", "btc_short_conf70_80_penalize_v1",
       "rule_1781693230_22", "rule_1781080478_16", "rule_1781720035_27",
       "rule_1781025758_12", "rule_1781878466_32", "rule_1781693230_24"]
for k in key:
    r = rules[k]
    print("=== %s [%s] eps=%s" % (k, r["action"], r.get("cf_episodes")))
    for fk, v in r.get("fortnights", {}).items():
        print("   %s: saved=%.1f missed=%.1f net=%.1f%% ($%.0f) L/W=%d/%d" %
              (fk, v["saved_pct"], v["missed_pct"], v["net_pct"], v["net_usd"],
               v["losers"], v["winners"]))
    print("   actual: n=%s pnl=$%s" % (r.get("actual_trades_matched"), r.get("actual_trades_pnl_usd")))

fees_pct, notionals = [], []
for row in csv.DictReader(open(r"C:\Users\vince\WAGMI\bot\data\trades.csv", encoding="utf-8")):
    try:
        entry = float(row["entry"]); exit_ = float(row["exit"])
        pnl = float(row["pnl"]); fee = float(row["fees"])
    except Exception:
        continue
    move = abs(exit_ - entry) / entry if entry else 0
    if move > 1e-6 and abs(pnl) > 0:
        n = abs(pnl) / move
        if 50 < n < 1e6:
            notionals.append(n); fees_pct.append(fee / n * 100)
print("n trades w/ notional:", len(notionals),
      "median notional $%.0f" % statistics.median(notionals),
      "mean $%.0f" % statistics.mean(notionals))
print("median fee pct of notional: %.3f%%  mean %.3f%%" %
      (statistics.median(fees_pct), statistics.mean(fees_pct)))

med = statistics.median(notionals)
print()
for k in ["hype_long_veto_v1", "sol_long_veto_v1", "night_session_block_v1",
          "hype_short_veto_v1", "conf_floor_70_v1"]:
    r = rules[k]
    cf_usd = r["episode"]["net_usd"]
    act = r["actual_trades_pnl_usd"]
    eps = r["cf_episodes"]
    fee_credit = eps * 0.10 / 100 * med
    print("%s: cf_net=$%.0f  blocked_actual_credit=$%.0f  fee_credit~$%.0f  COMBINED~$%.0f" %
          (k, cf_usd, -act, fee_credit, cf_usd - act + fee_credit))
