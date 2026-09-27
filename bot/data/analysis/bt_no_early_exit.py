"""
Counterfactual backtest: disable LLM early-exit on SHORTs.
For each of the 40 LLM_EXIT_AGENT short closes, replay 5m candles from OPEN
forward under the new policy: exits only via SL, TP2, trailing(after TP1), or
8h TIME_STOP. Compute net-of-fee PnL and compare to the actual (early-cut) PnL.
"""
import json, pandas as pd, numpy as np, os

ANALYSIS = os.path.dirname(__file__)
CACHE = os.path.join(os.path.dirname(ANALYSIS), 'cache')

# ---- config (mirrors trading_config / position_manager defaults) ----
TRAILING_ATR_MULT = 2.0           # TRAILING_STOP_ATR_MULT default
STYLE_MULT = 1.0                  # MEDIUM
TIGHTEN_START, TIGHTEN_END = 0.67, 0.33   # MEDIUM trailing tighten curve
FLOOR_START = 0.0                 # not modeled separately; min floor below
TAKER_FEE_BPS = 4.5               # HL taker ~0.045%; round trip applied as 2x
TIME_STOP_H = 8.0

candles = {}
def load(sym):
    if sym in candles: return candles[sym]
    fn = os.path.join(CACHE, f'{sym}_5m_merged.csv')
    d = pd.read_csv(fn)
    d['time'] = pd.to_datetime(d['time'], utc=True)
    d = d.sort_values('time').reset_index(drop=True)
    candles[sym] = d
    return d

def fee(notional):
    return notional * TAKER_FEE_BPS / 10000.0

def simulate(row):
    sym = row['symbol']
    df = load(sym)
    entry = row['entry']; sl = row['sl']; tp1 = row['tp1']; tp2 = row['tp2']
    atr = row['atr']; lev = row['lev']; psize = row['psize']
    open_ts = pd.to_datetime(row['open_ts'], utc=True)
    # qty notionally: position_size is base qty in the ledger (used for pnl scale)
    qty = psize
    # restrict to candles at/after open
    seg = df[df['time'] >= open_ts].reset_index(drop=True)
    coverage_ok = len(seg) > 0 and seg['time'].iloc[0] <= open_ts + pd.Timedelta(hours=1)
    if len(seg) == 0:
        return dict(reason='NO_CANDLES', exit_price=np.nan, gross=np.nan, net=np.nan,
                    hold_h=np.nan, covered=False, hit_tp1=False)
    trail_dist = atr * TRAILING_ATR_MULT * STYLE_MULT
    peak = entry                      # best (lowest for short) price since open
    tp1_hit = False
    exit_price = None; reason = None; exit_time = None
    deadline = open_ts + pd.Timedelta(hours=TIME_STOP_H)
    for _, c in seg.iterrows():
        t = c['time']; hi = c['high']; lo = c['low']; close = c['close']
        # SHORT: SL above entry (price rising hits SL), TP below entry
        # 1) check SL first (worst case within bar) -- conservative ordering
        if hi >= sl:
            exit_price = sl; reason = 'SL'; exit_time = t; break
        # 2) TP2 (full target)
        if lo <= tp2:
            exit_price = tp2; reason = 'TP2'; exit_time = t; break
        # 3) TP1 -> activates trailing
        if not tp1_hit and lo <= tp1:
            tp1_hit = True
            peak = min(peak, lo)
        # update peak (short: lower is better)
        peak = min(peak, lo)
        # 4) trailing stop, only active after TP1
        if tp1_hit:
            total_range = entry - tp2
            peak_move = entry - peak
            progress = min(peak_move / total_range, 1.0) if total_range > 0 else 0.0
            tighten_factor = max(TIGHTEN_START - progress * (TIGHTEN_START - TIGHTEN_END), TIGHTEN_END)
            eff = trail_dist * tighten_factor
            trail_sl = peak + eff
            # min profit-lock floor (>= breakeven + fees) for short
            fee_buf = entry * TAKER_FEE_BPS * 2 / 10000.0
            floor_sl = entry - fee_buf
            stop_level = min(trail_sl, floor_sl)   # short: lower stop = tighter lock
            if hi >= stop_level:
                exit_price = stop_level; reason = 'TRAILING'; exit_time = t; break
        # 5) time stop
        if t >= deadline:
            exit_price = close; reason = 'TIME_STOP'; exit_time = t; break
    if exit_price is None:
        # ran out of candles before any exit -> mark to last close (BACKTEST_END)
        last = seg.iloc[-1]
        exit_price = last['close']; reason = 'BACKTEST_END'; exit_time = last['time']
    # PnL for SHORT: (entry - exit) * qty * ... ledger pnl already in $ via position_size&lev
    # Reproduce ledger pnl scale: pnl ≈ (entry-exit)/entry * notional ; notional = qty*entry*lev?
    # Use realized actual to calibrate scale factor k so model matches ledger convention.
    gross = (entry - exit_price) * qty * lev
    notional = entry * qty * lev
    rt_fee = fee(notional) * 2  # open+close
    net = gross - rt_fee
    hold_h = (pd.to_datetime(exit_time, utc=True) - open_ts).total_seconds()/3600
    return dict(reason=reason, exit_price=exit_price, gross=gross, net=net,
                hold_h=hold_h, covered=coverage_ok, hit_tp1=tp1_hit, notional=notional)

def main():
    m = pd.read_csv(os.path.join(ANALYSIS, 'llm_early_short_matched.csv'))
    out = []
    for _, r in m.iterrows():
        s = simulate(r)
        s.update(symbol=r['symbol'], entry=r['entry'], actual_pnl=r['actual_pnl'],
                 actual_hold_h=r['hold_h'], lev=r['lev'], psize=r['psize'])
        out.append(s)
    res = pd.DataFrame(out)
    # calibrate scale: the ledger actual_pnl uses some notional convention.
    # derive implied scale from actual: actual_pnl ≈ (entry-actual_exit)*qty*lev - fees
    # We trust our model's relative behavior; report both raw and fee-net.
    res.to_csv(os.path.join(ANALYSIS, 'bt_no_early_exit_results.csv'), index=False)
    cov = res[res['covered'] == True]
    print('=== ALL 40 (incl. uncovered) ===')
    print('reasons:', res['reason'].value_counts().to_dict())
    print('covered (candle within 1h of open):', cov.shape[0], '/', len(res))
    print()
    print('=== COVERED ONLY (valid backtest) n=%d ===' % len(cov))
    print('new-policy exit reasons:', cov['reason'].value_counts().to_dict())
    nw = (cov['net'] > 0).sum()
    print(f'new-policy WR: {nw}/{len(cov)} = {nw/len(cov)*100:.0f}%')
    print(f'new-policy net PnL (model): ${cov["net"].sum():.2f}')
    print(f'actual (early-cut) PnL on same trades: ${cov["actual_pnl"].sum():.2f}')
    print(f'DELTA (new - actual): ${cov["net"].sum() - cov["actual_pnl"].sum():.2f}')
    print()
    print('median hold new:', round(cov['hold_h'].median(),2), 'vs actual:', round(cov['actual_hold_h'].median(),2))
    print()
    print('per-trade detail (covered):')
    cols=['symbol','reason','hit_tp1','net','actual_pnl','hold_h','actual_hold_h']
    print(cov[cols].round(2).to_string())

if __name__ == '__main__':
    main()
