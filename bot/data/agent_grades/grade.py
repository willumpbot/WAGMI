"""Stage 2: forward-grade every agent decision in graded_decisions.jsonl -> scorecard.json (+ console summary).

Conventions
  e_h  = signed forward return of the PROPOSED side over horizon h, in bps, minus 9 bps round-trip fee.
  Dedupe: one row per (symbol, side, agent decision, 1h bucket) - kills the 5-15 min re-polling of the same setup.
  CIs:    cluster bootstrap over (symbol, UTC day) clusters (2000 resamples) - handles overlapping windows.
  n_eff:  distinct (symbol, h-bucket) cells covered = non-overlapping effective sample size.
"""
import json, os, collections, datetime as dt
import numpy as np

OUT = os.path.dirname(os.path.abspath(__file__))
FEE = 9.0
RNG = np.random.default_rng(7)
HS = {'1h': 3600, '4h': 14400, '12h': 43200}
PRIMARY = '4h'
B = 2000

rows = [json.loads(l) for l in open(f'{OUT}/graded_decisions.jsonl', encoding='utf-8')]
P = sorted([r for r in rows if r['kind'] == 'pipeline'], key=lambda r: r['ts'])
X = sorted([r for r in rows if r['kind'] == 'exit'], key=lambda r: r['ts'])
del rows


def day(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime('%Y-%m-%d')


def month(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime('%Y-%m')


def sgn(side):
    return 1 if side == 'LONG' else (-1 if side == 'SHORT' else 0)


def boot_mean(vals, clus):
    """cluster bootstrap CI of the pooled mean."""
    vals = np.asarray(vals, float)
    if len(vals) < 5:
        return None, None
    cl = collections.defaultdict(list)
    for v, c in zip(vals, clus):
        cl[c].append(v)
    S = np.array([sum(v) for v in cl.values()])
    N = np.array([len(v) for v in cl.values()])
    k = len(S)
    idx = RNG.integers(0, k, size=(B, k))
    m = S[idx].sum(1) / np.maximum(N[idx].sum(1), 1)
    return round(float(np.percentile(m, 2.5)), 2), round(float(np.percentile(m, 97.5)), 2)


def boot_diff(a, ca, b, cb):
    """cluster-bootstrap CI of mean(a)-mean(b) (clusters resampled jointly by key)."""
    if len(a) < 5 or len(b) < 5:
        return None, None, None
    keys = sorted(set(ca) | set(cb))
    ki = {k: i for i, k in enumerate(keys)}
    Sa = np.zeros(len(keys)); Na = np.zeros(len(keys)); Sb = np.zeros(len(keys)); Nb = np.zeros(len(keys))
    for v, c in zip(a, ca):
        Sa[ki[c]] += v; Na[ki[c]] += 1
    for v, c in zip(b, cb):
        Sb[ki[c]] += v; Nb[ki[c]] += 1
    idx = RNG.integers(0, len(keys), size=(B, len(keys)))
    d = Sa[idx].sum(1) / np.maximum(Na[idx].sum(1), 1) - Sb[idx].sum(1) / np.maximum(Nb[idx].sum(1), 1)
    p = float(min((d <= 0).mean(), (d >= 0).mean()) * 2)
    return round(float(np.percentile(d, 2.5)), 2), round(float(np.percentile(d, 97.5)), 2), round(p, 4)


def auc(score, label):
    """P(score of positive > score of negative); ties 0.5."""
    s = np.asarray(score, float); y = np.asarray(label, bool)
    pos, neg = s[y], s[~y]
    if len(pos) < 5 or len(neg) < 5:
        return None
    order = np.argsort(np.r_[pos, neg], kind='mergesort')
    ranks = np.empty(len(order)); allv = np.r_[pos, neg][order]
    # average ranks for ties
    r = np.arange(1, len(allv) + 1, dtype=float)
    uniq, inv, cnt = np.unique(allv, return_inverse=True, return_counts=True)
    sums = np.bincount(inv, weights=r)
    ranks[order] = (sums / cnt)[inv]
    return round(float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))), 3)


def spearman(x, y):
    x = np.asarray(x, float); y = np.asarray(y, float)
    if len(x) < 10 or np.std(x) == 0:
        return None
    rx = np.argsort(np.argsort(x)); ry = np.argsort(np.argsort(y))
    return round(float(np.corrcoef(rx, ry)[0, 1]), 3)


def summarize(items, h=PRIMARY, key='e'):
    """items: list of dicts with ts, sym, and value under key (dict of horizon->val)."""
    v = [(it[key][h], it) for it in items if it[key].get(h) is not None]
    if not v:
        return {'n': 0}
    vals = [x[0] for x in v]
    cl = [(x[1]['sym'], day(x[1]['ts'])) for x in v]
    lo, hi = boot_mean(vals, cl)
    neff = len({(x[1]['sym'], int(x[1]['ts'] // HS[h])) for x in v})
    out = {'n': len(vals), 'n_eff': neff, 'mean_bps': round(float(np.mean(vals)), 2), 'ci95': [lo, hi],
           'hit': round(float(np.mean(np.array(vals) > 0)), 3), 'median_bps': round(float(np.median(vals)), 2)}
    if neff < 30:
        out['flag'] = 'n_eff<30'
    return out


def dedupe(items, keyf):
    seen = set(); out = []
    for it in items:
        k = keyf(it)
        if k in seen:
            continue
        seen.add(k); out.append(it)
    return out


R = {'meta': {}, 'baselines': {}, 'trade': {}, 'critic': {}, 'risk': {}, 'quant': {}, 'regime': {}, 'exit': {}, 'models': {}}
R['meta'] = {'pipelines_graded': len(P), 'exit_rows_graded': len(X), 'fee_bps': FEE, 'primary_horizon': PRIMARY,
             'date_range': [day(P[0]['ts']), day(P[-1]['ts'])],
             'dedupe': '(sym, side, agent decision, 1h bucket)', 'ci': 'cluster bootstrap over (sym, UTC day), 2000 resamples'}

# ---------- build per-pipeline items ----------
items = []
for r in P:
    side = r.get('prop_side')
    if not side:
        continue
    s = sgn(side)
    e = {h: (None if r.get('r' + h) is None else s * r['r' + h] - FEE) for h in HS}
    raw = {h: r.get('r' + h) for h in HS}
    items.append({**r, 'e': e, 'raw': raw})
R['meta']['pipelines_with_side'] = len(items)
R['meta']['side_source'] = dict(collections.Counter(it['side_src'] for it in items))

# ---------- baselines ----------
base_all = dedupe(items, lambda it: (it['sym'], it['prop_side'], int(it['ts'] // 3600)))
R['baselines']['take_every_signal'] = {h: summarize(base_all, h) for h in HS}
R['baselines']['always_skip'] = {'mean_bps': 0.0, 'note': 'skipping earns 0 by definition'}
# random side: mean of signed return with random sign = ~ -fee; compute empirically
rs = [{'sym': it['sym'], 'ts': it['ts'], 'e': {h: (None if it['raw'][h] is None else RNG.choice([-1, 1]) * it['raw'][h] - FEE) for h in HS}} for it in base_all]
R['baselines']['random_side'] = {h: summarize(rs, h) for h in HS}
R['baselines']['take_every_signal_by_month'] = {m: summarize([it for it in base_all if month(it['ts']) == m]) for m in sorted({month(i['ts']) for i in base_all})}
R['baselines']['sltp_take_every_signal'] = dict(collections.Counter(it.get('sltp') for it in base_all if it.get('sltp')))


# ---------- TRADE agent ----------
def tdec(it):
    d = it.get('trade', {}).get('dec')
    return 'go' if d in ('go',) else ('skip' if d in ('skip', 'flat') else d)


T = dedupe([it for it in items if 'trade' in it and tdec(it) in ('go', 'skip')], lambda it: (it['sym'], it['prop_side'], tdec(it), int(it['ts'] // 3600)))
go = [it for it in T if tdec(it) == 'go']; sk = [it for it in T if tdec(it) == 'skip']


def discrim(A, Bset, h=PRIMARY):
    a = [(x['e'][h], (x['sym'], day(x['ts']))) for x in A if x['e'][h] is not None]
    b = [(x['e'][h], (x['sym'], day(x['ts']))) for x in Bset if x['e'][h] is not None]
    if not a or not b:
        return None
    lo, hi, p = boot_diff([x[0] for x in a], [x[1] for x in a], [x[0] for x in b], [x[1] for x in b])
    return {'diff_bps': round(float(np.mean([x[0] for x in a]) - np.mean([x[0] for x in b])), 2), 'ci95': [lo, hi], 'p_boot': p,
            'nA': len(a), 'nB': len(b)}


def sltp_rates(L):
    c = collections.Counter(x.get('sltp') for x in L if x.get('sltp'))
    n = sum(c.values())
    return {'n': n, 'tp_first': round(c['TP'] / n, 3) if n else None, 'sl_first': round(c['SL'] / n, 3) if n else None}


R['trade']['go'] = {h: summarize(go, h) for h in HS}
R['trade']['skip_proposed_side'] = {h: summarize(sk, h) for h in HS}
R['trade']['go_minus_skip'] = {h: discrim(go, sk, h) for h in HS}
R['trade']['sltp'] = {'go': sltp_rates(go), 'skip': sltp_rates(sk)}
# conf calibration (trade conf = go-conviction)
cb = [(0, .2), (.2, .3), (.3, .4), (.4, .5), (.5, .6), (.6, .7), (.7, 1.01)]


def calib(L, conf_of, h=PRIMARY, buckets=cb):
    out = []
    for lo, hi in buckets:
        sub = [x for x in L if conf_of(x) is not None and lo <= conf_of(x) < hi]
        sm = summarize(sub, h)
        sm['bucket'] = f'{lo:.1f}-{min(hi, 1):.1f}'
        out.append(sm)
    v = [(conf_of(x), x['e'][h]) for x in L if conf_of(x) is not None and x['e'][h] is not None]
    return {'buckets': out, 'spearman_conf_vs_e': spearman([a for a, b in v], [b for a, b in v]),
            'auc_conf_predicts_e_pos': auc([a for a, b in v], [b > 0 for a, b in v]), 'n': len(v)}


R['trade']['confidence_all'] = calib(T, lambda x: x['trade']['conf'])
R['trade']['confidence_within_go'] = calib(go, lambda x: x['trade']['conf'], buckets=[(0, .5), (.5, .6), (.6, .7), (.7, .8), (.8, 1.01)])
for dim, f in (('by_model', lambda x: x['trade']['model']), ('by_month', lambda x: month(x['ts'])), ('by_symbol', lambda x: x['sym']),
               ('by_regime_label', lambda x: x.get('regime', {}).get('dec')), ('by_side', lambda x: x['prop_side'])):
    out = {}
    for k in sorted({f(x) for x in T}, key=str):
        g = [x for x in go if f(x) == k]; s_ = [x for x in sk if f(x) == k]
        out[str(k)] = {'go': summarize(g), 'skip': summarize(s_), 'go_minus_skip': discrim(g, s_)}
    R['trade'][dim] = out
# skip value in money terms: per $1000 notional per skipped signal
ske = [x['e'][PRIMARY] for x in sk if x['e'][PRIMARY] is not None]
R['trade']['skip_money'] = {'skipped_setups_dedup': len(ske), 'sum_bps': round(float(np.sum(ske)), 1),
                            'usd_if_each_taken_at_1000_notional': round(float(np.sum(ske)) / 1e4 * 1000, 2),
                            'share_skips_that_would_have_won_after_fees': round(float(np.mean(np.array(ske) > 0)), 3)}

# ---------- CRITIC ----------
C = dedupe([it for it in items if 'critic' in it and 'trade' in it and tdec(it) in ('go', 'skip') and not it['critic'].get('fallback')],
           lambda it: (it['sym'], it['prop_side'], tdec(it), it['critic']['dec'], int(it['ts'] // 3600)))
for td in ('go', 'skip'):
    a = [x for x in C if tdec(x) == td and x['critic']['dec'] == 'approve']
    c = [x for x in C if tdec(x) == td and x['critic']['dec'] == 'challenge']
    R['critic'][f'trade_{td}'] = {'approve': summarize(a), 'challenge': summarize(c), 'challenge_minus_approve': discrim(c, a)}
# implied take = (go&approve) or (skip&challenge)
take = [x for x in C if (tdec(x) == 'go') == (x['critic']['dec'] == 'approve')]
notake = [x for x in C if (tdec(x) == 'go') != (x['critic']['dec'] == 'approve')]
R['critic']['implied_take_minus_notake'] = discrim(take, notake)
R['critic']['by_model'] = {}
for m in sorted({x['critic']['model'] for x in C}):
    gm = [x for x in C if x['critic']['model'] == m]
    tk = [x for x in gm if (tdec(x) == 'go') == (x['critic']['dec'] == 'approve')]
    nt = [x for x in gm if (tdec(x) == 'go') != (x['critic']['dec'] == 'approve')]
    R['critic']['by_model'][m] = {'n': len(gm), 'challenge_rate': round(float(np.mean([x['critic']['dec'] == 'challenge' for x in gm])), 3),
                                  'implied_take_minus_notake': discrim(tk, nt)}
R['critic']['confidence_distinct_values'] = dict(collections.Counter(round(x['critic']['conf'], 2) for x in C).most_common(6))


# ---------- RISK ----------
def rsize(it):
    d = it.get('risk', {}).get('dec', '')
    try:
        sz = float(d.split('size=')[1].split(',')[0])
    except Exception:
        return None, None
    ov = d.split('override=')[1] if 'override=' in d else None
    return sz, ov


Rk = []
for it in items:
    if 'risk' not in it or it['risk'].get('fixture'):
        continue
    sz, ov = rsize(it)
    if sz is None:
        continue
    it = dict(it); it['_sz'] = sz; it['_take'] = sz > 0 and ov != 'skip'
    Rk.append(it)
Rk = dedupe(Rk, lambda it: (it['sym'], it['prop_side'], it['_take'], int(it['ts'] // 3600)))
rt = [x for x in Rk if x['_take']]; rn = [x for x in Rk if not x['_take']]
R['risk']['take'] = summarize(rt); R['risk']['block'] = summarize(rn); R['risk']['take_minus_block'] = discrim(rt, rn)
R['risk']['size_vs_e_within_take'] = calib(rt, lambda x: x['_sz'], buckets=[(0, .35), (.35, .6), (.6, 1.0), (1.0, 5)])
R['risk']['risk_take_given_trade_go'] = {'n_go': sum(1 for x in Rk if tdec(x) == 'go'), 'risk_take_rate': round(float(np.mean([x['_take'] for x in Rk if tdec(x) == 'go'] or [0])), 3)}
g_rt = [x for x in Rk if tdec(x) == 'go' and x['_take']]; g_rn = [x for x in Rk if tdec(x) == 'go' and not x['_take']]
R['risk']['within_trade_go_take_minus_block'] = discrim(g_rt, g_rn)
R['risk']['confidence_note'] = 'risk confidence is constant 0.5 on all records -> uninformative by construction'


# ---------- QUANT ----------
def qdir(it):
    d = it.get('quant', {}).get('dec', '')
    if d.startswith('ev=long'):
        return 'LONG'
    if d.startswith('ev=short'):
        return 'SHORT'
    if 'neutral' in d:
        return 'NEUTRAL'
    return None


def qqual(it):
    d = it.get('quant', {}).get('dec', '')
    for q in ('clean', 'marginal', 'noise'):
        if 'quality=' + q in d:
            return q
    return None


Q = [it for it in items if 'quant' in it and not it['quant'].get('fixture')]
Qd = dedupe([x for x in Q if qdir(x) in ('LONG', 'SHORT')], lambda it: (it['sym'], qdir(it), int(it['ts'] // 3600)))
qitems = [{'sym': x['sym'], 'ts': x['ts'], 'conf': x['quant']['conf'], 'model': x['quant']['model'], 'dir': qdir(x),
           'e': {h: (None if x['raw'][h] is None else sgn(qdir(x)) * x['raw'][h] - FEE) for h in HS},
           'g': {h: (None if x['raw'][h] is None else sgn(qdir(x)) * x['raw'][h]) for h in HS}} for x in Qd]
R['quant']['directional_calls_net'] = {h: summarize(qitems, h) for h in HS}
R['quant']['directional_calls_gross'] = {h: summarize(qitems, h, key='g') for h in HS}
R['quant']['by_dir'] = {d: summarize([q for q in qitems if q['dir'] == d], key='g') for d in ('LONG', 'SHORT')}
# baseline: same timestamps, direction = always SHORT (period was net-bearish?) and always LONG
R['quant']['baseline_always_short_gross_same_times'] = summarize([{**q, 'g': {h: (None if q['g'][h] is None else -sgn(q['dir']) * q['g'][h]) for h in HS}} for q in qitems], key='g')
R['quant']['baseline_always_long_gross_same_times'] = summarize([{**q, 'g': {h: (None if q['g'][h] is None else sgn(q['dir']) * q['g'][h]) for h in HS}} for q in qitems], key='g')
R['quant']['confidence'] = calib(qitems, lambda x: x['conf'], buckets=[(0, .3), (.3, .5), (.5, .6), (.6, 1.01)])
R['quant']['by_model'] = {m: summarize([q for q in qitems if q['model'] == m], key='g') for m in sorted({q['model'] for q in qitems})}
Qq = dedupe([x for x in Q if qqual(x)], lambda it: (it['sym'], it['prop_side'], qqual(it), int(it['ts'] // 3600)))
R['quant']['quality_vs_proposed_side_e'] = {q: summarize([x for x in Qq if qqual(x) == q]) for q in ('clean', 'marginal', 'noise')}
R['quant']['decision_mix'] = dict(collections.Counter(qdir(x) for x in Q))

# ---------- REGIME ----------
G = [it for it in P if 'regime' in it and not it['regime'].get('fixture') and it.get('er12') is not None and it.get('r12h') is not None]
G = dedupe(G, lambda it: (it['sym'], it['regime']['dec'], int(it['ts'] // 3600)))
med_er = {s: float(np.median([g['er12'] for g in G if g['sym'] == s])) for s in {g['sym'] for g in G}}
p75_rv = {s: float(np.percentile([g['rv12'] for g in G if g['sym'] == s], 75)) for s in {g['sym'] for g in G}}
TRENDY = {'trend', 'trending_bull', 'trending_bear'}
RANGY = {'range', 'consolidation'}


def regime_correct(lbl, g):
    if lbl == 'trending_bull':
        return g['r12h'] > 0
    if lbl == 'trending_bear':
        return g['r12h'] < 0
    if lbl == 'trend':
        return g['er12'] > med_er[g['sym']]
    if lbl in RANGY:
        return g['er12'] <= med_er[g['sym']]
    if lbl == 'high_volatility':
        return g['rv12'] > p75_rv[g['sym']]
    return None


lab = collections.defaultdict(list)
for g in G:
    lab[g['regime']['dec']].append(g)
reg = {}
for l, L in sorted(lab.items(), key=lambda kv: -len(kv[1])):
    corr = [regime_correct(l, g) for g in L]
    corr = [c for c in corr if c is not None]
    neff = len({(g['sym'], int(g['ts'] // 43200)) for g in L})
    reg[l] = {'n': len(L), 'n_eff_12h': neff, 'mean_er12': round(float(np.mean([g['er12'] for g in L])), 3),
              'mean_rv12_bps': round(float(np.mean([g['rv12'] for g in L])), 1), 'mean_r12_bps': round(float(np.mean([g['r12h'] for g in L])), 1),
              'p_up12': round(float(np.mean([g['r12h'] > 0 for g in L])), 3), 'accuracy': round(float(np.mean(corr)), 3) if corr else None}
    if neff < 30:
        reg[l]['flag'] = 'n_eff<30'
R['regime']['by_label'] = reg
# permutation baseline: shuffle labels within symbol, recompute overall accuracy
gl = [g for g in G if regime_correct(g['regime']['dec'], g) is not None]
acc_real = float(np.mean([regime_correct(g['regime']['dec'], g) for g in gl]))
perm = []
bysym = collections.defaultdict(list)
for i, g in enumerate(gl):
    bysym[g['sym']].append(i)
labels = np.array([g['regime']['dec'] for g in gl], dtype=object)
for _ in range(300):
    pl = labels.copy()
    for s, ix in bysym.items():
        pl[ix] = RNG.permutation(labels[ix])
    perm.append(np.mean([regime_correct(pl[i], gl[i]) for i in range(len(gl))]))
R['regime']['overall_accuracy'] = round(acc_real, 3)
R['regime']['shuffled_label_baseline'] = {'mean': round(float(np.mean(perm)), 3), 'p95': round(float(np.percentile(perm, 95)), 3),
                                          'p_value': round(float(np.mean(np.array(perm) >= acc_real)), 4)}
tr = [g['er12'] for g in G if g['regime']['dec'] in TRENDY]; rg = [g['er12'] for g in G if g['regime']['dec'] in RANGY]
R['regime']['auc_trendlabel_vs_realized_efficiency'] = auc(tr + rg, [True] * len(tr) + [False] * len(rg))
bull = [g for g in G if g['regime']['dec'] == 'trending_bull']; bear = [g for g in G if g['regime']['dec'] == 'trending_bear']
R['regime']['bull_minus_bear_r12_bps'] = round(float(np.mean([g['r12h'] for g in bull]) - np.mean([g['r12h'] for g in bear])), 1) if bull and bear else None
bb = boot_diff([g['r12h'] for g in bull], [(g['sym'], day(g['ts'])) for g in bull], [g['r12h'] for g in bear], [(g['sym'], day(g['ts'])) for g in bear])
R['regime']['bull_minus_bear_ci95_p'] = bb
# confidence calibration
cr = [(g['regime']['conf'], regime_correct(g['regime']['dec'], g)) for g in gl]
R['regime']['confidence'] = {'auc_conf_predicts_correct': auc([a for a, b in cr], [b for a, b in cr]),
                             'buckets': [{'bucket': f'{lo}-{hi}', 'n': len(s), 'accuracy': round(float(np.mean(s)), 3) if s else None}
                                         for lo, hi in ((0, .6), (.6, .7), (.7, .8), (.8, 1.01))
                                         for s in [[b for a, b in cr if lo <= a < hi]]]}
R['regime']['by_model'] = {}
for m in sorted({g['regime']['model'] for g in gl} | {'technical_fallback'}):
    if m == 'technical_fallback':
        sub = [g for g in gl if g['regime'].get('fallback')]
    else:
        sub = [g for g in gl if g['regime']['model'] == m and not g['regime'].get('fallback')]
    if sub:
        R['regime']['by_model'][m] = {'n': len(sub), 'accuracy': round(float(np.mean([regime_correct(g['regime']['dec'], g) for g in sub])), 3),
                                      'months': sorted({month(g['ts']) for g in sub})}

# ---------- EXIT ----------
# position clusters: same sym+side, consecutive exit evals < 3h apart
pos_id = {}; last = {}; cid = 0
for x in X:
    k = (x['sym'], x['pos_side'])
    if k not in last or x['ts'] - last[k] > 3 * 3600:
        cid += 1; pos_id[k] = cid
    last[k] = x['ts']; x['pos'] = pos_id[k]
EX = dedupe(X, lambda x: (x['pos'], x['dec'], int(x['ts'] // 3600)))
eitems = [{'sym': x['sym'], 'ts': x['ts'], 'dec': x['dec'], 'pos': x['pos'],
           'e': {h: (None if x.get('r' + h) is None else sgn(x['pos_side']) * x['r' + h]) for h in HS}} for x in EX]
R['exit']['note'] = "value = position-side forward return AFTER the exit decision (gross bps). Good exit agent: low after full_close, high after hold."
R['exit']['positions_clustered'] = len({x['pos'] for x in X})
for d in ('hold', 'tighten_sl', 'partial_close', 'full_close'):
    sub = [x for x in eitems if x['dec'] == d]
    R['exit'][d] = {h: summarize(sub, h) for h in HS}
    for h in HS:
        if R['exit'][d][h].get('n'):
            R['exit'][d][h]['n_positions'] = len({x['pos'] for x in sub})
for h in HS:
    hold = [x for x in eitems if x['dec'] == 'hold' and x['e'][h] is not None]
    cls = [x for x in eitems if x['dec'] == 'full_close' and x['e'][h] is not None]
    R['exit'][f'hold_minus_close_{h}'] = discrim([{**x, 'e': x['e']} for x in hold], [{**x, 'e': x['e']} for x in cls], h)
R['exit']['full_close_correct_rate_4h'] = round(float(np.mean([x['e']['4h'] <= 0 for x in eitems if x['dec'] == 'full_close' and x['e']['4h'] is not None])), 3)
R['exit']['confidence_note'] = 'exit confidence is constant 0.5 -> uninformative'

# ---------- MODEL comparisons within overlapping months ----------
mc = {}
for m in sorted({month(x['ts']) for x in T}):
    for mod in sorted({x['trade']['model'] for x in T}):
        g = [x for x in go if month(x['ts']) == m and x['trade']['model'] == mod]
        s_ = [x for x in sk if month(x['ts']) == m and x['trade']['model'] == mod]
        if len(g) + len(s_) >= 20:
            mc[f'trade|{m}|{mod}'] = {'go': summarize(g), 'skip': summarize(s_), 'go_minus_skip': discrim(g, s_)}
R['models']['trade_by_month_model'] = mc

json.dump(R, open(f'{OUT}/scorecard.json', 'w'), indent=1, default=str)


def fmt(s):
    if not s or not s.get('n'):
        return 'n=0'
    return f"n={s['n']} neff={s['n_eff']} mean={s['mean_bps']:+.1f}bps ci={s['ci95']} hit={s['hit']}" + (' [n<30]' if s.get('flag') else '')


print('BASE take-every-signal', {h: fmt(v) for h, v in R['baselines']['take_every_signal'].items()})
print('BASE random side', fmt(R['baselines']['random_side']['4h']))
print('TRADE go', fmt(R['trade']['go']['4h'])); print('TRADE skip', fmt(R['trade']['skip_proposed_side']['4h']))
print('TRADE go-skip', R['trade']['go_minus_skip']); print('TRADE sltp', R['trade']['sltp'])
print('TRADE conf', R['trade']['confidence_all']['spearman_conf_vs_e'], R['trade']['confidence_all']['auc_conf_predicts_e_pos'])
for b in R['trade']['confidence_all']['buckets']: print('   ', b.get('bucket'), fmt(b))
print('TRADE conf within go', R['trade']['confidence_within_go']['spearman_conf_vs_e'], R['trade']['confidence_within_go']['auc_conf_predicts_e_pos'])
for k, v in R['trade']['by_model'].items(): print('  model', k, 'go', fmt(v['go']), '| skip', fmt(v['skip']), '|', v['go_minus_skip'])
for k, v in R['trade']['by_month'].items(): print('  month', k, 'go', fmt(v['go']), '| skip', fmt(v['skip']), '|', v['go_minus_skip'])
for k, v in R['trade']['by_regime_label'].items(): print('  reg', k, 'go', fmt(v['go']), '| skip', fmt(v['skip']))
for k, v in R['trade']['by_side'].items(): print('  side', k, 'go', fmt(v['go']), '| skip', fmt(v['skip']), '|', v['go_minus_skip'])
for k, v in R['trade']['by_symbol'].items(): print('  sym', k, 'go', fmt(v['go']), '| skip', fmt(v['skip']))
print('SKIP money', R['trade']['skip_money'])
print('CRITIC', json.dumps({k: R['critic'][k] for k in R['critic'] if k != 'by_model'}, default=str)[:1500]); print('CRITIC by model', R['critic']['by_model'])
print('RISK take', fmt(R['risk']['take']), 'block', fmt(R['risk']['block']), R['risk']['take_minus_block'], R['risk']['within_trade_go_take_minus_block'], R['risk']['risk_take_given_trade_go'])
print('QUANT net', {h: fmt(v) for h, v in R['quant']['directional_calls_net'].items()}); print('QUANT gross', {h: fmt(v) for h, v in R['quant']['directional_calls_gross'].items()})
print('QUANT by dir', {k: fmt(v) for k, v in R['quant']['by_dir'].items()}, 'mix', R['quant']['decision_mix'])
print('QUANT conf', R['quant']['confidence']['spearman_conf_vs_e'], R['quant']['confidence']['auc_conf_predicts_e_pos'], 'by model', {k: fmt(v) for k, v in R['quant']['by_model'].items()})
print('QUANT quality', {k: fmt(v) for k, v in R['quant']['quality_vs_proposed_side_e'].items()})
print('REGIME', json.dumps({k: v for k, v in R['regime'].items()}, default=str))
print('EXIT', json.dumps({k: R['exit'][k] for k in R['exit'] if k.startswith('hold_minus') or k in ('full_close_correct_rate_4h', 'positions_clustered')}, default=str))
for d in ('hold', 'tighten_sl', 'partial_close', 'full_close'): print('  exit', d, {h: fmt(v) for h, v in R['exit'][d].items()})
for k, v in mc.items(): print('  MC', k, 'go', fmt(v['go']), '| skip', fmt(v['skip']), '|', v['go_minus_skip'])
