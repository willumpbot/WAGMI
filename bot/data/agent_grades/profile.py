import json, collections, datetime as dt
f='C:/Users/vince/WAGMI/bot/data/llm/agent_performance.jsonl'
types=collections.Counter(); roles=collections.Counter(); dec=collections.defaultdict(collections.Counter)
syms=collections.Counter(); models=collections.defaultdict(collections.Counter); days=collections.Counter()
tmin=1e20;tmax=0; keys=collections.Counter(); side=collections.defaultdict(collections.Counter); conf=collections.defaultdict(collections.Counter)
pip=collections.Counter(); bad=0; other_types_sample={}
for line in open(f,encoding='utf-8'):
    try:r=json.loads(line)
    except: bad+=1; continue
    t=r.get('type'); types[t]+=1
    for k in r: keys[(t,k)]+=1
    if t!='decision':
        other_types_sample.setdefault(t,line[:600]); continue
    ro=r.get('agent_role'); roles[ro]+=1; dec[ro][str(r.get('decision'))[:30]]+=1
    syms[r.get('symbol')]+=1; ts=r.get('timestamp',0); tmin=min(tmin,ts); tmax=max(tmax,ts)
    d=dt.datetime.utcfromtimestamp(ts); models[d.strftime('%Y-%m')][(ro,r.get('model_used'))]+=1
    days[d.strftime('%Y-%m-%d')]+=1; side[ro][r.get('side')]+=1; conf[ro][round(float(r.get('confidence') or 0),1)]+=1
    pip[str(r.get('pipeline_id')).split('_')[0]]+=1
print('bad',bad,types); print(keys)
print('roles',roles); 
for ro in dec: print(ro, dec[ro].most_common(15)); print('  side',side[ro].most_common(6)); print('  conf',sorted(conf[ro].items()))
print('syms',syms.most_common(40))
print(dt.datetime.utcfromtimestamp(tmin),dt.datetime.utcfromtimestamp(tmax))
for m in sorted(models): print(m, sorted(models[m].items()))
print('pip prefixes',pip.most_common(20))
print('days',len(days)); print(sorted(days.items()))
for t,s in other_types_sample.items(): print(t,s)
