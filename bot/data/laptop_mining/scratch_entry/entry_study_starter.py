import json,urllib.request,time,collections as C
H='https://api.hyperliquid.xyz/info'
def q(b):
    for i in range(4):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(H,json.dumps(b).encode(),{'Content-Type':'application/json'}),timeout=20))
        except Exception: time.sleep(2**i)
    return []
def candles(c,iv,a,b): return [(int(x['t']),float(x['o']),float(x['h']),float(x['l']),float(x['c'])) for x in q({"type":"candleSnapshot","req":{"coin":c,"interval":iv,"startTime":a,"endTime":b}})]
d=json.load(open(r'C:\Users\vince\WAGMI\bot\data\hivemind\ai_plans.json'));rows=d if isinstance(d,list) else next(v for v in d.values() if isinstance(v,list))
now=int(time.time()*1000)
def sim(bars,i0,side,e,s,t,hold_bars):
    # short-only logic generalised; returns R
    sg=1 if side=='LONG' else -1; R=abs(s-e)
    for b in bars[i0:i0+hold_bars]:
        _,o,h,l,c=b
        if (sg<0 and h>=s) or (sg>0 and l<=s): return -1.0
        if (sg<0 and l<=t) or (sg>0 and h>=t): return abs(t-e)/R
    if len(bars)<i0+hold_bars: return None   # still running
    return sg*(bars[i0+hold_bars-1][4]-e)/R
out=[]
for r in rows:
    ts=int(r['ts']*1000); coin=r['coin']; side=r['side']; e,s,t=r['entry'],r['stop'],r['target']; p0=r['price_at_plan']
    win=int(r.get('entry_window_h',24)*4); hold=int(r.get('max_hold_h',48)*4)
    bars=candles(coin,'15m',ts,ts+(win+hold)*900000+1)
    day=candles(coin,'1d',ts-21*86400000,ts)
    if len(bars)<4 or len(day)<10: continue
    lo20=min(x[3] for x in day[-20:]); hi20=max(x[2] for x in day[-20:])
    sg=1 if side=='LONG' else -1
    riskpct=abs(s-e)/e; rr=abs(t-e)/abs(s-e)
    # A) as written (limit)
    A=None; fillA=None
    for i,b in enumerate(bars[:win]):
        if (sg<0 and b[2]>=e) or (sg>0 and b[3]<=e): fillA=i;break
    if fillA is not None: A=sim(bars,fillA+1,side,e,s,t,hold)
    # B) market at plan time, same stop/target
    B=sim(bars,0,side,p0,s,t,hold) if (sg<0 and s>p0>t) or (sg>0 and s<p0<t) else None
    # C) break entry: sell-stop 0.2% beyond 20d low (buy-stop beyond high for longs); same risk % and R:R as plan
    lvl=lo20*0.998 if sg<0 else hi20*1.002; C_=None; fillC=None
    if (sg<0 and p0>lvl) or (sg>0 and p0<lvl):
        for i,b in enumerate(bars[:win]):
            if (sg<0 and b[3]<=lvl) or (sg>0 and b[2]>=lvl): fillC=i;break
        if fillC is not None:
            ce=lvl; cs=ce*(1-sg*riskpct); ct=ce*(1+sg*riskpct*rr)
            C_=sim(bars,fillC+1,side,ce,cs,ct,hold)
    out.append(dict(coin=coin,side=side,id=r['id'],bounce_pct=round((e/p0-1)*100,2),dist_lo20=round((p0/lo20-1)*100,2),A=A,filledA=fillA is not None,B=B,C=C_,filledC=fillC is not None))
json.dump(out,open(__file__.replace('.py','_out.json'),'w'),indent=0)
def st(k,f=lambda x:True):
    v=[o[k] for o in out if o[k] is not None and f(o)]
    return f"n={len(v)} sumR={sum(v):+.2f} avg={sum(v)/max(1,len(v)):+.2f} win={sum(x>0 for x in v)}"
print('plans',len(out),'| bounce filled',sum(o['filledA'] for o in out),'| break filled',sum(o['filledC'] for o in out))
print('A as-written  ',st('A'));print('B sell now    ',st('B'));print('C break-entry ',st('C'))
print('missed (A unfilled) -> sell-now would have:',st('B',lambda o:not o['filledA']))
print('missed (A unfilled) -> break would have:   ',st('C',lambda o:not o['filledA']))
print('near floor (<3% above 20d low):  A',st('A',lambda o:o['dist_lo20']<3),'| B',st('B',lambda o:o['dist_lo20']<3),'| C',st('C',lambda o:o['dist_lo20']<3))
print('fill rate by bounce asked:')
for lo,hi in((0,1.5),(1.5,2.5),(2.5,99)):
    g=[o for o in out if lo<=abs(o['bounce_pct'])<hi];print(f'  {lo}-{hi}%: {sum(o["filledA"] for o in g)}/{len(g)} filled')
for o in out:
    if o['coin']=='XRP': print(o)
