"""Throwaway: join recorded EXPLORATION ENTRY events -> gate decision -> closed-trade PnL."""
import json, glob, re, csv, os, sys, datetime
sys.path.insert(0, r"C:\Users\vince\WAGMI\bot")
os.environ["EXPLORATION_RESPECT_CONVICTION"] = "true"
from multi_strategy_main import exploration_conviction_ok

LOGDIR = r"C:\Users\vince\WAGMI\bot\logs"
rows = []
for fp in sorted(glob.glob(os.path.join(LOGDIR, "bot_2026062*.log"))):
    for ln in open(fp, encoding="utf-8"):
        d = json.loads(ln)
        rows.append((d["ts"], d["msg"]))
rows.sort()

re_ex = re.compile(r"\[([0-9a-f]+)\]\[([A-Z]+)\] EXPLORATION ENTRY")
re_en = re.compile(r"Entry decision: skip .*conf=([0-9.]+)")
re_tr = re.compile(r"LLM-FIRST TRADE: (LONG|SHORT) qty=[0-9.]+ @ \$([0-9.]+)")

events = []
for i, (ts, m) in enumerate(rows):
    g = re_ex.search(m)
    if not g:
        continue
    trace, sym = g.group(1), g.group(2)
    sc = None
    for j in range(i - 1, max(0, i - 30), -1):
        e = re_en.search(rows[j][1])
        if e:
            sc = float(e.group(1))
            break
    side, entry_px = "?", None
    for j in range(i, min(len(rows), i + 12)):
        if f"[{trace}][{sym}]" in rows[j][1]:
            s = re_tr.search(rows[j][1])
            if s:
                side, entry_px = s.group(1), float(s.group(2))
                break
    blob = m
    for j in range(max(0, i - 25), min(len(rows), i + 3)):
        if f"[{trace}][{sym}]" in rows[j][1]:
            blob += " " + rows[j][1]
    t = blob.lower()
    zero = "0% wr" in t or "0%wr" in t
    tox = "toxic" in t
    reg_wr = 0.0 if zero else None
    reg_n = 8 if zero else 0
    ok, unc, neg = exploration_conviction_ok(
        skip_conf=sc or 0.0, win_prob=None, is_toxic=tox,
        reg_wr=reg_wr, reg_n=reg_n, respect=True, conv_thresh=0.65, wp_floor=0.40)
    events.append(dict(ts=ts, sym=sym, side=side, entry_px=entry_px, sc=sc,
                       zero=zero, tox=tox, decline=not ok))

# load exploration-tagged closed trades
trades = []
for row in csv.DictReader(open(r"C:\Users\vince\WAGMI\bot\data\trades.csv")):
    er = (row.get("entry_reasons") or "") + (row.get("primary_driver") or "")
    if "EXPLORATION" in er.upper():
        trades.append(dict(ts=row["timestamp"], sym=row["symbol"], side=row["side"],
                           entry=float(row["entry"]), pnl=float(row["pnl"]), out=row["outcome"]))

used = set()
print(f"{'ts':20}{'sym':5}{'side':6}{'sc':6}{'0wr':5}{'tox':5}{'GATE':9}{'pnl':>9} outcome")
dec_pnl = keep_pnl = 0.0
dec = keep = matched = 0
for ev in events:
    cands = [(i, tr) for i, tr in enumerate(trades)
             if i not in used and tr["sym"] == ev["sym"] and tr["side"] == ev["side"]]
    if ev["entry_px"]:
        cands = [(i, tr) for i, tr in cands
                 if abs(tr["entry"] - ev["entry_px"]) / ev["entry_px"] < 0.02]
    if ev["entry_px"]:
        cands = [(i, tr) for i, tr in cands
                 if abs(tr["entry"] - ev["entry_px"]) / ev["entry_px"] < 0.005]
    cands = [(i, tr) for i, tr in cands if tr["ts"][:19] >= ev["ts"][:19]]
    cands.sort(key=lambda it: it[1]["ts"])
    pnl, outc = None, ""
    if cands:
        idx, tr = cands[0]
        used.add(idx)
        pnl, outc = tr["pnl"], tr["out"]
        matched += 1
    g = "DECLINE" if ev["decline"] else "KEEP"
    if ev["decline"]:
        dec += 1
        dec_pnl += (pnl or 0)
    else:
        keep += 1
        keep_pnl += (pnl or 0)
    scs = f"{ev['sc']:.2f}" if ev["sc"] is not None else "NA"
    print(f"{ev['ts'][:19]:20}{ev['sym']:5}{ev['side']:6}{scs:6}"
          f"{str(ev['zero'])[0]:5}{str(ev['tox'])[0]:5}{g:9}"
          f"{(pnl if pnl is not None else 0):9.2f} {outc}")

print()
print(f"DECLINE n={dec} pnl={dec_pnl:+.2f}   KEEP n={keep} pnl={keep_pnl:+.2f}   "
      f"matched={matched}/{len(trades)}")
print(f"unmatched trades (closed but not joined): "
      f"{[ (i,trades[i]['sym'],trades[i]['side'],trades[i]['pnl']) for i in range(len(trades)) if i not in used]}")
