"""Stage 1: stream raw logs -> compact per-decision rows with proposed side + no-lookahead forward outcomes.
Outputs graded_decisions.jsonl (one row per gradeable unit). Read-only on bot data. Streams every big file.

Price model (no lookahead):
  p0       = last observed price at or BEFORE decision ts (<=30 min stale)
  p(t0+h)  = first observed price at or AFTER t0+h (<=30 min stale)
  path     = finest HL candles whose bar START >= t0 (5m last ~17d, 15m last ~52d, else 1h)
Observations = HL candle opens/closes + funding_oi_history price + market_depth mid + SIGNAL_GENERATED entry.
"""
import json, os, re, bisect, datetime as dt, collections
import numpy as np

D = 'C:/Users/vince/WAGMI/bot/data'
OUT = os.path.dirname(os.path.abspath(__file__))
SYMS = ['BTC', 'ETH', 'SOL', 'HYPE', 'XRP', 'NEAR']
H = [3600, 4 * 3600, 12 * 3600]
HN = ['1h', '4h', '12h']
MAX_STALE = 1800


def iso(s):
    t = dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.timestamp()


# ---------- price observations ----------
obs = {s: [] for s in SYMS}
candles = {}
for s in SYMS:
    for iv, sec in (('1h', 3600), ('15m', 900), ('5m', 300)):
        rows = []
        with open(f'{OUT}/candles/{s}_{iv}.csv') as f:
            next(f)
            for ln in f:
                t, o, h, l, c, v = ln.split(',')
                t = int(t) / 1000
                o, h, l, c = float(o), float(h), float(l), float(c)
                rows.append((t, o, h, l, c))
                obs[s].append((t, o))
                obs[s].append((t + sec - 0.001, c))
        candles[(s, iv)] = np.array(rows)

C1 = {s: candles[(s, '1h')] for s in SYMS}


def valid_px(s, t, px):
    try:
        px = float(px)
    except Exception:
        return False
    a = C1[s]
    i = np.searchsorted(a[:, 0], t, side='right') - 1
    if i < 0:
        return False
    lo, hi = a[max(i - 1, 0):i + 2, 3].min(), a[max(i - 1, 0):i + 2, 2].max()
    return lo * 0.98 <= px <= hi * 1.02


sig = {s: [] for s in SYMS}
opened = {s: [] for s in SYMS}
for ln in open(f'{D}/funding_oi_history.jsonl', encoding='utf-8'):
    try:
        r = json.loads(ln)
    except Exception:
        continue
    s = r.get('symbol')
    if s in obs and r.get('price'):
        t = iso(r['timestamp'])
        if valid_px(s, t, r['price']):
            obs[s].append((t, float(r['price'])))
for ln in open(f'{D}/market_depth_history.jsonl', encoding='utf-8'):
    i = ln.find('"symbol":"')
    if i < 0:
        continue
    s = ln[i + 10:ln.find('"', i + 10)]
    if s not in obs:
        continue
    j = ln.find('"mid":')
    if j < 0:
        continue
    try:
        mid = float(ln[j + 6:ln.find(',', j)])
        t = iso(ln[7:ln.find('"', 7)])
        if valid_px(s, t, mid):
            obs[s].append((t, mid))
    except Exception:
        pass
for ln in open(f'{D}/trade_events.jsonl', encoding='utf-8'):
    if 'SIGNAL_GENERATED' not in ln and 'TRADE_OPENED' not in ln:
        continue
    try:
        r = json.loads(ln)
    except Exception:
        continue
    s = r.get('symbol')
    if s not in obs:
        continue
    t = iso(r['timestamp'])
    if r['event'] == 'SIGNAL_GENERATED':
        if not valid_px(s, t, r.get('entry')):
            continue  # test-fixture pollution (e.g. entry=100.0) in trade_events.jsonl
        sd = 'LONG' if r.get('side') in ('BUY', 'LONG') else 'SHORT'
        sig[s].append((t, sd, r.get('entry'), r.get('sl'), r.get('tp1'), r.get('num_agree'), r.get('confidence')))
        if r.get('entry'):
            obs[s].append((t, float(r['entry'])))

import csv as _csv
for row in _csv.DictReader(open(f'{D}/trade_ledger.csv', encoding='utf-8')):
    s = row['symbol']
    if s not in opened:
        continue
    try:
        t_open = float(row['timestamp']) - float(row['hold_hours'] or 0) * 3600
    except Exception:
        continue
    opened[s].append((t_open, row['side'], row['entry_price']))

OT, OP = {}, {}
for s in SYMS:
    obs[s].sort()
    OT[s] = np.array([x[0] for x in obs[s]])
    OP[s] = np.array([x[1] for x in obs[s]])
    sig[s].sort()
    opened[s].sort()
SIGT = {s: [x[0] for x in sig[s]] for s in SYMS}
OPT = {s: [x[0] for x in opened[s]] for s in SYMS}
print('obs', {s: len(obs[s]) for s in SYMS}, 'sig', {s: len(sig[s]) for s in SYMS}, flush=True)
del obs


def p_at_or_before(s, t):
    i = np.searchsorted(OT[s], t, side='right') - 1
    if i < 0 or t - OT[s][i] > MAX_STALE:
        return None
    return float(OP[s][i])


def p_at_or_after(s, t):
    i = np.searchsorted(OT[s], t, side='left')
    if i >= len(OT[s]) or OT[s][i] - t > MAX_STALE:
        return None
    return float(OP[s][i])


def path(s, t0, t1):
    for iv in ('5m', '15m', '1h'):
        a = candles[(s, iv)]
        if len(a) and a[0, 0] <= t0:
            i = np.searchsorted(a[:, 0], t0, side='left')
            j = np.searchsorted(a[:, 0], t1, side='left')
            return a[i:j, 2], a[i:j, 3], iv
    return None, None, None


def fwd(s, t0):
    p0 = p_at_or_before(s, t0)
    if p0 is None:
        return None
    out = {'p0': p0}
    for h, n in zip(H, HN):
        p = p_at_or_after(s, t0 + h)
        out['r' + n] = None if p is None else round((p / p0 - 1) * 1e4, 2)
    hi, lo, iv = path(s, t0, t0 + 12 * 3600)
    if hi is not None and len(hi):
        out['up12'] = round((hi.max() / p0 - 1) * 1e4, 1)
        out['dn12'] = round((1 - lo.min() / p0) * 1e4, 1)
        out['path_iv'] = iv
    a = candles[(s, '1h')]
    i = np.searchsorted(a[:, 0], t0, side='left')
    c = a[i:i + 12, 4]
    if len(c) >= 8:
        rets = np.diff(np.log(np.r_[p0, c]))
        out['er12'] = round(float(abs(rets.sum()) / max(np.abs(rets).sum(), 1e-12)), 3)
        out['rv12'] = round(float(np.sqrt((rets ** 2).sum()) * 1e4), 1)
        out['range12'] = round(float((a[i:i + 12, 2].max() / a[i:i + 12, 3].min() - 1) * 1e4), 1)
    return out


def sltp(s, t0, side, sl, tp):
    """first touch of SL vs TP1 within 24h on bars starting after t0; both in same bar -> SL (conservative)."""
    try:
        sl, tp = float(sl), float(tp)
    except Exception:
        return None
    hi, lo, iv = path(s, t0, t0 + 24 * 3600)
    if hi is None or not len(hi):
        return None
    for h, l in zip(hi, lo):
        if side == 'LONG':
            hs, ht = l <= sl, h >= tp
        else:
            hs, ht = h >= sl, l <= tp
        if hs:
            return 'SL'
        if ht:
            return 'TP'
    return 'NONE'


SIDE_RE = re.compile(r'\b(BUY|SELL|LONG|SHORT)\b')


def text_side(txt, sym):
    m = re.search(re.escape(sym) + r'[ ._]?(BUY|SELL|LONG|SHORT)\b', txt)
    if m:
        g = m.group(1)
    else:
        c = collections.Counter(SIDE_RE.findall(txt[:300]))
        if not c:
            return None
        g = c.most_common(1)[0][0]
    return 'LONG' if g in ('BUY', 'LONG') else 'SHORT'


# ---------- stream agent_performance ----------
pipes = collections.defaultdict(dict)
singles = []
seen_rid = set()
dup = 0
for ln in open(f'{D}/llm/agent_performance.jsonl', encoding='utf-8'):
    r = json.loads(ln)
    if r['record_id'] in seen_rid:
        dup += 1
        continue
    seen_rid.add(r['record_id'])
    ro = r['agent_role']
    slim = {'ts': r['timestamp'], 'sym': r['symbol'], 'side': r['side'], 'dec': r['decision'], 'conf': r['confidence'],
            'csrc': r.get('confidence_source'), 'model': r['model_used'], 'txt': r['reasoning_summary'][:500],
            'lat': r.get('latency_ms') or 0}
    slim['fixture'] = slim['lat'] < 1000 and not slim['txt'].startswith('technical_fallback')
    slim['fallback'] = slim['txt'].startswith('technical_fallback') or 'critic_fallback' in slim['txt']
    if ro in ('trade', 'critic', 'risk', 'quant', 'regime'):
        pipes[r['pipeline_id']][ro] = slim
    elif ro == 'exit':
        singles.append((r['pipeline_id'], slim))
print('dup record_ids', dup, 'pipelines', len(pipes), 'exit', len(singles), flush=True)

fo = open(f'{OUT}/graded_decisions.jsonl', 'w', encoding='utf-8')
stats = collections.Counter()
for pid, m in pipes.items():
    s = next(iter(m.values()))['sym']
    t0 = max(x['ts'] for x in m.values())
    if s not in SYMS:
        stats['nosym'] += 1
        continue
    nfix = sum(1 for x in m.values() if x['fixture'])
    if nfix >= 1 and (m.get('trade', {}).get('fixture') or nfix >= 2):
        stats['fixture_pipeline_dropped'] += 1
        continue
    i = bisect.bisect_right(SIGT[s], t0) - 1
    sg = sig[s][i] if (i >= 0 and t0 - SIGT[s][i] <= 900) else None
    txts = ' '.join(m.get(k, {}).get('txt', '') for k in ('trade', 'critic', 'risk'))
    tside = text_side(txts, s)
    side = sg[1] if sg else tside
    src = 'signal' if sg else ('text' if tside else None)
    if sg and tside:
        stats['sig_text_agree' if sg[1] == tside else 'sig_text_disagree'] += 1
    tr = m.get('trade', {})
    oside = None
    if tr.get('dec') in ('go', 'flip'):
        j = bisect.bisect_left(OPT[s], t0 - 60)
        if j < len(OPT[s]) and OPT[s][j] - t0 <= 900:
            oside = opened[s][j][1]
    f = fwd(s, t0)
    if f is None:
        stats['noprice'] += 1
        continue
    row = {'kind': 'pipeline', 'pid': pid, 'ts': t0, 'sym': s, 'prop_side': side, 'side_src': src,
           'opened_side': oside, 'sig_agree': sg[5] if sg else None, 'sig_conf': sg[6] if sg else None,
           'sig_age': round(t0 - sg[0]) if sg else None, **f}
    if sg:
        row['sltp'] = sltp(s, t0, sg[1], sg[3], sg[4])
        try:
            row['sl_bps'] = round(abs(float(sg[3]) / float(sg[2]) - 1) * 1e4, 1)
        except Exception:
            pass
    for ro, x in m.items():
        row[ro] = {'dec': x['dec'], 'conf': x['conf'], 'model': x['model'], 'csrc': x['csrc'],
                   'fallback': x['fallback'], 'fixture': x['fixture']}
    row['trade_txt_side'] = tside
    fo.write(json.dumps(row) + '\n')
    stats['pipe_rows'] += 1
for pid, x in singles:
    s = x['sym']
    if s not in SYMS:
        continue
    if x['fixture']:
        stats['exit_fixture'] += 1
        continue
    f = fwd(s, x['ts'])
    if f is None:
        stats['exit_noprice'] += 1
        continue
    fo.write(json.dumps({'kind': 'exit', 'pid': pid, 'ts': x['ts'], 'sym': s, 'pos_side': x['side'], 'dec': x['dec'],
                         'model': x['model'], 'conf': x['conf'], **f}) + '\n')
    stats['exit_rows'] += 1
fo.close()
print(stats)
