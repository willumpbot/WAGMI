"""Fetch Hyperliquid 1h candles covering the laptop signal corpus (2026-02-11 -> 06-05).

The server's bot/data/agent_grades/fetch_candles.py starts at 2026-05-30 and
covers 6 symbols; this corpus needs Feb onward across 14. Same request shape,
same paging, same retry/backoff. Free public endpoint (allowed by house rules).

Cache -> bot/data/laptop_mining/candles/<SYM>_1h.csv  (t_ms,o,h,l,c,v)
NOT committed (raw multi-MB dumps stay local per the handoff).
"""
import json, os, time, urllib.request

# symbols with n>=13 in signal_corpus.jsonl, biggest first
SYMS = ['BTC', 'ETH', 'HYPE', 'SOL', 'PEPE', 'SEI', 'SUI', 'WIF',
        'DOGE', 'ONDO', 'ARB', 'XRP', 'LINK', 'AVAX']

START = 1770595200000   # 2026-02-09, two days before the first signal
END   = 1780963200000   # 2026-06-09, three days after the last
IV    = '1h'
STEP  = 3600_000

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'candles')
os.makedirs(OUT, exist_ok=True)


def get(coin, iv, s, e):
    body = json.dumps({"type": "candleSnapshot",
                       "req": {"coin": coin, "interval": iv,
                               "startTime": s, "endTime": e}}).encode()
    for k in range(4):
        try:
            req = urllib.request.Request('https://api.hyperliquid.xyz/info', data=body,
                                         headers={'Content-Type': 'application/json'})
            return json.loads(urllib.request.urlopen(req, timeout=30).read())
        except Exception:
            time.sleep(2 + k * 3)
    return []


for sym in SYMS:
    rows = {}
    cur = START
    page = STEP * 4000
    while cur < END:
        for c in get(sym, IV, cur, min(cur + page, END)) or []:
            rows[c['t']] = (c['o'], c['h'], c['l'], c['c'], c['v'])
        cur += page
        time.sleep(0.4)
    path = os.path.join(OUT, f'{sym}_{IV}.csv')
    with open(path, 'w') as f:
        f.write('t_ms,o,h,l,c,v\n')
        for t in sorted(rows):
            f.write(f"{t},{','.join(str(x) for x in rows[t])}\n")
    ks = sorted(rows)
    lo = time.strftime('%Y-%m-%d', time.gmtime(ks[0] / 1000)) if ks else '-'
    hi = time.strftime('%Y-%m-%d', time.gmtime(ks[-1] / 1000)) if ks else '-'
    print(f"{sym:<6} {len(rows):>5} candles  {lo} -> {hi}", flush=True)
