import csv,glob,io,os,json,numpy as np
TOP_EXCLUDE=15; WIN=480; HORIZONS=(1,4,24,72); MATCH_H=336
MIN_BARS=600; MIN_ELIGIBLE=10
rng=np.random.default_rng(20261011)

def roll_mean_prior(x,w):
    out=np.full(len(x),np.nan); cs=np.concatenate([[0.0],np.cumsum(np.nan_to_num(x))])
    out[w+1:]= (cs[w+1:len(x)]-cs[1:len(x)-w])/w
    return out
def roll_sum(x,w):
    out=np.full(len(x),np.nan); cs=np.concatenate([[0.0],np.cumsum(np.nan_to_num(x))])
    out[w-1:]=cs[w:len(x)+1]-cs[0:len(x)+1-w]
    return out
def roll_max_prior(x,w):
    out=np.full(len(x),np.nan)
    if len(x)>w:
        from numpy.lib.stride_tricks import sliding_window_view
        sw=sliding_window_view(x,w).max(axis=1)   # sw[j]=max(x[j:j+w])
        out[w+1:]=sw[1:len(x)-w]
    return out

def load(d='history1h'):
    coins={}
    for p in sorted(glob.glob(os.path.join(d,'*_1h.csv'))):
        sym=os.path.basename(p).replace('_1h.csv','')
        t,c,v=[],[],[]
        with io.open(p,encoding='utf-8') as f:
            rd=csv.reader(f); next(rd,None)
            for r in rd:
                try: t.append(int(r[0])); c.append(float(r[4])); v.append(float(r[5]))
                except (ValueError,IndexError): continue
        if len(t)<MIN_BARS: continue
        o=np.argsort(np.asarray(t))
        coins[sym]={'t':np.asarray(t)[o],'c':np.asarray(c)[o],'v':np.asarray(v)[o]}
    return coins

def build(coins, nanfix=False):
    for sym,d in coins.items():
        c,v=d['c'],d['v']; dv=c*v
        d['dv20']=roll_mean_prior(dv,WIN)
        dv24=roll_sum(dv,24); d['dollar_vol_24h']=dv24
        base24=roll_mean_prior(dv24,WIN)
        hi=roll_max_prior(c,WIN)
        ret24=np.full(len(c),np.nan); ret24[24:]=c[24:]/c[:-24]-1.0
        expmove=roll_mean_prior(np.abs(ret24),WIN)
        bad=np.isnan(hi)|np.isnan(base24)|np.isnan(expmove)|np.isnan(dv24)
        if nanfix:   # exclude bars whose trailing window was contaminated by NaN->0
            n=len(c); i=np.arange(n)
            bad=bad|(i<WIN+24+1)
        with np.errstate(invalid='ignore'):
            s1=c>hi; s2=dv24>2.0*base24; s4=(ret24>1.5*expmove)&(ret24>0)
        d['S1_breakout']=np.where(bad,False,s1)
        d['S2_volsurge']=np.where(bad,False,s2)
        d['S4_movesurge']=np.where(bad,False,s4)
        d['S3_both']=d['S1_breakout']&d['S2_volsurge']
        for h in HORIZONS:
            f=np.full(len(c),np.nan); f[:-h]=(c[h:]/c[:-h]-1.0)*100.0
            d['fwd%d'%h]=f
        d['any']=d['S1_breakout']|d['S2_volsurge']|d['S4_movesurge']
        d['bad']=bad
    return coins

def eligibility(coins):
    idx={}
    for sym,d in coins.items():
        for i,t in enumerate(d['t']): idx.setdefault(int(t),[]).append((sym,i))
    elig={}
    for t,members in idx.items():
        vs=[(s,i,coins[s]['dv20'][i]) for s,i in members]
        vs=[x for x in vs if x[2]==x[2]]
        if len(vs)<MIN_ELIGIBLE+TOP_EXCLUDE: continue
        vs.sort(key=lambda x:-x[2])
        elig[t]=[(s,i) for s,i,_ in vs[TOP_EXCLUDE:]]
    return elig

def fresh_mask(sig,gap):
    """first firing of a run: no sig True in the prior `gap` bars"""
    n=len(sig); prev=np.zeros(n,bool)
    for k in range(1,gap+1):
        prev[k:]|=sig[:-k]
    return sig&(~prev)

def collect(coins,elig,sig,h,fresh=0,fullpool=True,excl_overlap=0,ndraw=20):
    key='fwd%d'%h
    pool={}
    for t,mem in elig.items():
        pool[t]=[(s,i) for s,i in mem if not coins[s]['any'][i] and coins[s][key][i]==coins[s][key][i]]
    # precompute n2 pool mean per timestamp (full pool)
    n2full={}
    for t,pl in pool.items():
        if len(pl)>=5: n2full[t]=float(np.mean([coins[s][key][i] for s,i in pl]))
    sigm={}
    for s,d in coins.items():
        m=d[sig]
        sigm[s]=fresh_mask(m,fresh) if fresh else m
    ev=[]
    for t,mem in elig.items():
        pl=pool.get(t,[])
        if len(pl)<5: continue
        for s,i in mem:
            d=coins[s]
            if not sigm[s][i] or d[key][i]!=d[key][i]: continue
            lo=max(0,i-MATCH_H); hi2=min(len(d['t']),i+MATCH_H+1)
            ok=(~d['any'][lo:hi2])&(~np.isnan(d[key][lo:hi2]))
            cand=np.flatnonzero(ok)+lo
            if excl_overlap:
                cand=cand[np.abs(cand-i)>excl_overlap]
            if len(cand)<5: continue
            if fullpool:
                n1=float(np.mean(d[key][cand]))
                n2=n2full[t]
            else:
                n1=float(np.mean(d[key][rng.choice(cand,min(ndraw,len(cand)),replace=False)]))
                pick=rng.choice(len(pl),min(ndraw,len(pl)),replace=False)
                n2=float(np.mean([coins[pl[j][0]][key][pl[j][1]] for j in pick]))
            ev.append({'t':int(t),'sym':s,'real':float(d[key][i]),'n1':n1,'n2':n2})
    return ev

def day_blocks(ev,field):
    days={}
    for e in ev: days.setdefault(int(e['t']//86_400_000),[]).append(e['real']-e[field])
    return days

def boot(days,iters=2000,eqw=False,seed=7):
    r=np.random.default_rng(seed)
    keys=list(days)
    if len(keys)<12: return (np.nan,)*4
    arrs=[np.asarray(days[k]) for k in keys]
    if eqw:
        pt=float(np.mean([a.mean() for a in arrs]))
    else:
        pt=float(np.concatenate(arrs).mean())
    n=len(keys); ms=np.empty(iters)
    for b in range(iters):
        pick=r.integers(0,n,n)
        if eqw: ms[b]=np.mean([arrs[j].mean() for j in pick])
        else:   ms[b]=np.concatenate([arrs[j] for j in pick]).mean()
    ms.sort()
    lo=float(ms[int(.025*iters)]); hi=float(ms[int(.975*iters)])
    return pt,lo,hi,(hi-lo)/3.92
