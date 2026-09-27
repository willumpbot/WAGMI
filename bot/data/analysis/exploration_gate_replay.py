"""Throwaway: replay the conviction gate over recorded EXPLORATION ENTRY events.

For each historical EXPLORATION ENTRY (logged BEFORE the gate existed), recover the
structured conviction signal the gate keys on:
  - skip_conf  := nearest-preceding "[LLM-FIRST] Entry decision: skip ... conf=X"
  - win_prob   := nearest-preceding "[ENSEMBLE] <SYM> ... win_prob=Y" for same symbol
  - is_toxic / reg 0%WR := parsed from the SKIP thesis text (the WR/n/TOXIC the LLM cited)
Then run multi_strategy_main.exploration_conviction_ok and report decline vs keep.
"""
import os, re, glob, json, sys
from collections import defaultdict

sys.path.insert(0, r"C:\Users\vince\WAGMI\bot")
os.environ.setdefault("EXPLORATION_RESPECT_CONVICTION", "true")
from multi_strategy_main import exploration_conviction_ok

LOGDIR = r"C:\Users\vince\WAGMI\bot\logs"
CONV_THRESH = float(os.getenv("EXPLORATION_CONVICTION_MAX", "0.65"))
WP_FLOOR = float(os.getenv("EXPLORATION_MIN_WINPROB", "0.40"))

def load_lines():
    rows = []
    for fp in sorted(glob.glob(os.path.join(LOGDIR, "bot_2026062*.log"))):
        with open(fp, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    d = json.loads(ln)
                except Exception:
                    continue
                msg = d.get("msg", "")
                rows.append((d.get("ts", ""), msg))
    rows.sort(key=lambda r: r[0])
    return rows

rows = load_lines()

# index helpers
re_explore = re.compile(r"\[([0-9a-f]+)\]\[([A-Z]+)\] EXPLORATION ENTRY: skip")
re_entry = re.compile(r"\[LLM-FIRST\] Entry decision: skip .*?conf=([0-9.]+)")
re_ev = re.compile(r"\[ENSEMBLE\] ([A-Z]+) (?:BUY|SELL) rejected: negative EV .*?win_prob=([0-9.]+)")
re_wp = re.compile(r"\[ENSEMBLE\] ([A-Z]+) .*?win_prob=([0-9.]+)")
re_side_trade = re.compile(r"\[([0-9a-f]+)\]\[([A-Z]+)\] EXPLORATION ENTRY: skip→go .*lev=([0-9.]+)x")

# pre-extract per-index parsed info
def parse_thesis_flags(text):
    """Detect explicit 0% WR / TOXIC / lacks-edge conviction from the SKIP thesis."""
    t = text.lower()
    zero_wr = bool(re.search(r"0%\s*wr", t)) or "0% wr" in t
    toxic = "toxic" in t
    return zero_wr, toxic

results = []
n = len(rows)
for i, (ts, msg) in enumerate(rows):
    m = re_explore.search(msg)
    if not m:
        continue
    trace, sym = m.group(1), m.group(2)
    side = "LONG"
    sm = re.search(r"EXPLORATION ENTRY.*?(LONG|SHORT)", msg)
    # side not in entry log; infer from later TRADE line
    # walk back for skip_conf (entry decision) and win_prob; walk both dirs for thesis
    skip_conf = None
    win_prob = None
    for j in range(i - 1, max(0, i - 40), -1):
        mm = msg_j = rows[j][1]
        if skip_conf is None:
            em = re_entry.search(mm)
            if em:
                skip_conf = float(em.group(1))
        if win_prob is None:
            wm = re_wp.search(mm)
            if wm and wm.group(1) == sym:
                win_prob = float(wm.group(2))
        if skip_conf is not None and win_prob is not None:
            break
    # thesis flags: the EXPLORATION ENTRY line embeds the truncated thesis; also scan
    # nearby SKIP lines for the same trace/symbol for fuller WR/toxic citation
    blob = msg
    for j in range(max(0, i - 25), min(n, i + 3)):
        mj = rows[j][1]
        if (f"[{trace}][{sym}]" in mj) and ("SKIP" in mj or "TOXIC" in mj or "veto" in mj.lower()):
            blob += " || " + mj
    zero_wr, toxic = parse_thesis_flags(blob)
    # find side from subsequent LLM-FIRST TRADE line same trace+sym
    for j in range(i, min(n, i + 12)):
        mj = rows[j][1]
        ms = re.search(rf"\[{trace}\]\[{sym}\] LLM-FIRST TRADE: (LONG|SHORT)", mj)
        if ms:
            side = ms.group(1)
            break

    # Map recovered text-flags onto the gate's structured guard inputs.
    # The gate's structured -EV guard uses is_toxic and reg_wr==0/n>=5. The historical
    # logs don't print the raw regime-cell counters at the explore point, so we
    # reconstruct them from the same WR/TOXIC facts the LLM cited (structured intent).
    reg_wr = 0.0 if zero_wr else None
    reg_n = 8 if zero_wr else 0   # LLM cited n>=5 in every 0%-WR case observed
    is_toxic = toxic

    conviction_ok, uncertain, neg_ev = exploration_conviction_ok(
        skip_conf=skip_conf if skip_conf is not None else 0.0,
        win_prob=win_prob,
        is_toxic=is_toxic,
        reg_wr=reg_wr,
        reg_n=reg_n,
        respect=True,
        conv_thresh=CONV_THRESH,
        wp_floor=WP_FLOOR,
    )
    results.append(dict(ts=ts, trace=trace, sym=sym, side=side,
                        skip_conf=skip_conf, win_prob=win_prob,
                        zero_wr=zero_wr, toxic=is_toxic,
                        uncertain=uncertain, neg_ev=neg_ev,
                        decline=not conviction_ok))

print(f"Total EXPLORATION ENTRY events: {len(results)}\n")
hdr = f"{'ts':25} {'sym':4} {'side':5} {'skipconf':8} {'win_prob':8} {'0wr':4} {'tox':4} {'uncert':6} {'negEV':6} {'GATE':8}"
print(hdr)
print("-" * len(hdr))
dec = keep = 0
for r in results:
    g = "DECLINE" if r["decline"] else "KEEP"
    if r["decline"]:
        dec += 1
    else:
        keep += 1
    sc = f"{r['skip_conf']:.2f}" if r['skip_conf'] is not None else "NA"
    wp = f"{r['win_prob']:.2f}" if r['win_prob'] is not None else "NA"
    print(f"{r['ts'][:23]:25} {r['sym']:4} {r['side']:5} {sc:8} {wp:8} "
          f"{str(r['zero_wr']):4} {str(r['toxic']):4} {str(r['uncertain']):6} {str(r['neg_ev']):6} {g:8}")

print(f"\nDECLINE={dec}  KEEP={keep}  total={len(results)}")
# breakdown by side
from collections import Counter
c = Counter((r['side'], r['decline']) for r in results)
print("by side/decline:", dict(c))
# missing skip_conf
miss = [r for r in results if r['skip_conf'] is None]
print(f"events with no recovered skip_conf: {len(miss)}")
