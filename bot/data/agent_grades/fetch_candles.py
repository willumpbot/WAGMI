"""Fetch Hyperliquid public candles for graded symbols; cache to candles/<SYM>_<iv>.csv (t_ms,o,h,l,c,v)."""
import json, os, time, urllib.request, sys
SYMS=['BTC','ETH','SOL','HYPE','XRP','NEAR']
START=int((1780161905-86400*2)*1000)  # 2 days before first decision
END=int(time.time()*1000)
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'candles')
os.makedirs(OUT,exist_ok=True)
STEP={'1h':3600_000,'15m':900_000,'5m':300_000}
def get(coin,iv,s,e):
    body=json.dumps({"type":"candleSnapshot","req":{"coin":coin,"interval":iv,"startTime":s,"endTime":e}}).encode()
    for k in range(4):
        try:
            req=urllib.request.Request('https://api.hyperliquid.xyz/info',data=body,headers={'Content-Type':'application/json'})
            return json.loads(urllib.request.urlopen(req,timeout=30).read())
        except Exception as ex:
            time.sleep(2+k*3)
    return []
for iv in sys.argv[1:] or ['1h','15m','5m']:
    for s in SYMS:
        rows={}; cur=START; step=STEP[iv]*4000
        while cur<END:
            d=get(s,iv,cur,min(cur+step,END))
            for c in d: rows[c['t']]=(c['o'],c['h'],c['l'],c['c'],c['v'])
            cur+=step; time.sleep(0.4)
        with open(os.path.join(OUT,f'{s}_{iv}.csv'),'w') as f:
            f.write('t_ms,o,h,l,c,v\n')
            for t in sorted(rows): f.write(f"{t},{','.join(rows[t])}\n")
        ks=sorted(rows); print(s,iv,len(rows), time.strftime('%Y-%m-%d %H:%M',time.gmtime(ks[0]/1000)) if ks else None, time.strftime('%Y-%m-%d',time.gmtime(ks[-1]/1000)) if ks else None, flush=True)
