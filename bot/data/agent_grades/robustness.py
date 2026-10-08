"""Robustness checks for the only positive-looking cell: risk agent take-vs-block WITHIN trade=go."""
import json, collections, numpy as np, importlib.util, sys, io, contextlib
spec = importlib.util.spec_from_file_location('g', 'grade.py'); g = importlib.util.module_from_spec(spec)
with contextlib.redirect_stdout(io.StringIO()): spec.loader.exec_module(g)
Rk = g.Rk; tdec = g.tdec
G = [x for x in Rk if tdec(x) == 'go']
out = {}
for h in g.HS:
    out['all_' + h] = g.discrim([x for x in G if x['_take']], [x for x in G if not x['_take']], h)
for dim, f in (('month', lambda x: g.month(x['ts'])), ('side', lambda x: x['prop_side']), ('sym', lambda x: x['sym']), ('risk_model', lambda x: x['risk']['model']), ('critic', lambda x: x.get('critic', {}).get('dec'))):
    for k in sorted({f(x) for x in G}, key=str):
        sub = [x for x in G if f(x) == k]
        out[f'{dim}={k}'] = g.discrim([x for x in sub if x['_take']], [x for x in sub if not x['_take']])
# what does a real pipeline (trade go AND risk take AND critic approve) look like = the "full desk yes"
full = [x for x in G if x['_take'] and x.get('critic', {}).get('dec') == 'approve']
out['full_desk_yes_4h'] = g.summarize(full)
out['n_tests_note'] = 'about 60 go/skip-style comparisons are run across roles/slices; expect ~3 at p<0.05 by chance'
json.dump(out, open('robustness.json', 'w'), indent=1, default=str)
for k, v in out.items(): print(k, v)
# trade agent: restrict to signal-joined sides only (exclude text-parsed side)
T2 = [x for x in g.T if x['side_src'] == 'signal']
o2 = {h: g.discrim([x for x in T2 if g.tdec(x) == 'go'], [x for x in T2 if g.tdec(x) == 'skip'], h) for h in g.HS}
o2['go_4h'] = g.summarize([x for x in T2 if g.tdec(x) == 'go']); o2['skip_4h'] = g.summarize([x for x in T2 if g.tdec(x) == 'skip'])
print('trade signal-side-only', o2)
out['trade_go_minus_skip_signal_side_only'] = o2
json.dump(out, open('robustness.json', 'w'), indent=1, default=str)
