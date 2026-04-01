"""Intraday seasonality analysis for HYPE, BTC, SOL."""
import pandas as pd
import numpy as np

symbols = ['HYPE', 'BTC', 'SOL']
data = {}
for sym in symbols:
    df = pd.read_csv(f'/tmp/seasonality_{sym}.csv')
    df['time'] = pd.to_datetime(df['time'], utc=True)
    df['hour'] = df['time'].dt.hour
    df['dow'] = df['time'].dt.dayofweek  # 0=Mon, 6=Sun
    df['return_pct'] = (df['close'] - df['open']) / df['open'] * 100
    df['range_pct'] = (df['high'] - df['low']) / df['open'] * 100
    # Forward 3h return (for BUY entry timing)
    df['fwd_3h'] = df['close'].shift(-3) / df['close'] * 100 - 100
    data[sym] = df

print('=' * 80)
print('DATA RANGES')
print('=' * 80)
for sym, df in data.items():
    print(f'{sym}: {df["time"].iloc[0]} to {df["time"].iloc[-1]} ({len(df)} candles)')

# 1. AVERAGE RETURN PER HOUR
print('\n' + '=' * 80)
print('1. AVERAGE HOURLY RETURN (%) - Which hours are consistently bullish/bearish?')
print('=' * 80)
for sym, df in data.items():
    hourly = df.groupby('hour')['return_pct'].agg(['mean', 'std', 'count'])
    hourly['win_rate'] = df.groupby('hour')['return_pct'].apply(lambda x: (x > 0).mean() * 100)
    hourly['t_stat'] = hourly['mean'] / (hourly['std'] / np.sqrt(hourly['count']))

    print(f'\n--- {sym} ---')
    print(f'{"Hour":>4} {"Mean%":>8} {"Std%":>8} {"WinRate":>8} {"t-stat":>8} {"N":>4}  Signal')
    for h in range(24):
        if h in hourly.index:
            r = hourly.loc[h]
            sig = ''
            if abs(r['t_stat']) > 1.65:
                sig = '*'
            if abs(r['t_stat']) > 1.96:
                sig = '**'
            if abs(r['t_stat']) > 2.58:
                sig = '***'
            direction = ''
            if r['mean'] > 0.05 and r['win_rate'] > 55:
                direction = 'BULL'
            elif r['mean'] < -0.05 and r['win_rate'] < 45:
                direction = 'BEAR'
            print(f'{h:4d} {r["mean"]:8.3f} {r["std"]:8.3f} {r["win_rate"]:7.1f}% {r["t_stat"]:8.2f} {int(r["count"]):4d}  {sig} {direction}')

# 2. VOLATILITY PER HOUR
print('\n' + '=' * 80)
print('2. VOLATILITY PER HOUR (range %) - Best hours for entries (biggest moves)')
print('=' * 80)
for sym, df in data.items():
    hourly_vol = df.groupby('hour')['range_pct'].agg(['mean', 'median'])
    avg_range = hourly_vol['mean'].mean()
    print(f'\n--- {sym} (avg range: {avg_range:.3f}%) ---')
    print(f'{"Hour":>4} {"MeanRange%":>10} {"vs_avg":>8}')
    for h in range(24):
        if h in hourly_vol.index:
            r = hourly_vol.loc[h]
            vs_avg = r['mean'] / avg_range * 100 - 100
            marker = ' <<< HIGH VOL' if vs_avg > 20 else (' <<< LOW VOL' if vs_avg < -20 else '')
            print(f'{h:4d} {r["mean"]:10.3f} {vs_avg:+7.1f}%{marker}')

# 3. VOLUME PER HOUR
print('\n' + '=' * 80)
print('3. VOLUME PER HOUR - Liquidity windows')
print('=' * 80)
for sym, df in data.items():
    hourly_vol = df.groupby('hour')['volume'].mean()
    avg_vol = hourly_vol.mean()
    print(f'\n--- {sym} ---')
    print(f'{"Hour":>4} {"AvgVol":>12} {"vs_avg":>8}')
    for h in range(24):
        if h in hourly_vol.index:
            v = hourly_vol[h]
            vs = v / avg_vol * 100 - 100
            marker = ' <<< HIGH' if vs > 30 else (' <<< LOW' if vs < -30 else '')
            print(f'{h:4d} {v:12.1f} {vs:+7.1f}%{marker}')

# 4. BEST ENTRY HOURS
print('\n' + '=' * 80)
print('4. BEST BUY ENTRY HOURS - Forward 3h return from each hour')
print('=' * 80)
for sym, df in data.items():
    sub = df.dropna(subset=['fwd_3h'])
    fwd = sub.groupby('hour')['fwd_3h'].agg(['mean', 'std', 'count'])
    fwd['win_rate'] = sub.groupby('hour')['fwd_3h'].apply(lambda x: (x > 0).mean() * 100)
    print(f'\n--- {sym} (ranked best to worst) ---')
    print(f'{"Hour":>4} {"Fwd3h%":>8} {"WinRate":>8} {"N":>4}  Note')
    ranked = fwd.sort_values('mean', ascending=False)
    for h in ranked.index:
        r = fwd.loc[h]
        note = ''
        if r['mean'] > 0.1 and r['win_rate'] > 55:
            note = '<-- BEST BUY WINDOW'
        if r['mean'] < -0.1 and r['win_rate'] < 45:
            note = '<-- AVOID BUYING'
        print(f'{h:4d} {r["mean"]:8.3f} {r["win_rate"]:7.1f}% {int(r["count"]):4d}  {note}')

# 5. MEAN REVERSION HOURS
print('\n' + '=' * 80)
print('5. MEAN REVERSION HOURS - Hours where price tends to reverse (good for exits)')
print('=' * 80)
for sym, df in data.items():
    df['next_return'] = df['return_pct'].shift(-1)
    df['reversal'] = ((df['return_pct'] > 0) & (df['next_return'] < 0)) | \
                     ((df['return_pct'] < 0) & (df['next_return'] > 0))
    rev = df.groupby('hour')['reversal'].mean() * 100
    print(f'\n--- {sym} ---')
    print(f'{"Hour":>4} {"Reversal%":>10}  Note')
    for h in range(24):
        if h in rev.index:
            note = '<-- HIGH REVERSAL (take profits here)' if rev[h] > 55 else ''
            print(f'{h:4d} {rev[h]:9.1f}%  {note}')

# 6. DAY OF WEEK EFFECT
print('\n' + '=' * 80)
print('6. DAY OF WEEK EFFECT')
print('=' * 80)
dow_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
for sym, df in data.items():
    daily = df.groupby('dow')['return_pct'].agg(['mean', 'std', 'count'])
    daily['win_rate'] = df.groupby('dow')['return_pct'].apply(lambda x: (x > 0).mean() * 100)
    daily['cumul'] = daily['mean'] * daily['count']
    print(f'\n--- {sym} ---')
    print(f'{"Day":>4} {"Mean%":>8} {"WinRate":>8} {"TotalRet%":>10} {"N":>5}')
    for d in range(7):
        if d in daily.index:
            r = daily.loc[d]
            note = ''
            if r['mean'] == daily['mean'].max():
                note = ' <-- BEST'
            elif r['mean'] == daily['mean'].min():
                note = ' <-- WORST'
            print(f'{dow_names[d]:>4} {r["mean"]:8.4f} {r["win_rate"]:7.1f}% {r["cumul"]:10.3f} {int(r["count"]):5d}{note}')

# 7. SESSION TRANSITION EFFECTS
print('\n' + '=' * 80)
print('7. SESSION TRANSITION EFFECTS')
print('=' * 80)
sessions = {
    'Asia Open (00:00 UTC)': [23, 0, 1],
    'Europe Open (08:00 UTC)': [7, 8, 9],
    'US Open (14:00 UTC)': [13, 14, 15],
    'US Close (21:00 UTC)': [20, 21, 22],
}

for sym, df in data.items():
    print(f'\n--- {sym} ---')
    for session_name, hours in sessions.items():
        session_df = df[df['hour'].isin(hours)]
        mean_ret = session_df['return_pct'].mean()
        mean_range = session_df['range_pct'].mean()
        win_rate = (session_df['return_pct'] > 0).mean() * 100
        vol = session_df['volume'].mean()
        avg_vol = df['volume'].mean()
        vol_ratio = vol / avg_vol * 100

        print(f'  {session_name}:')
        print(f'    Return: {mean_ret:+.4f}%  WinRate: {win_rate:.1f}%  Range: {mean_range:.3f}%  Vol: {vol_ratio:.0f}% of avg')

# ACTIONABLE EDGES SUMMARY
print('\n' + '=' * 80)
print('ACTIONABLE EDGES SUMMARY')
print('=' * 80)
for sym, df in data.items():
    hourly = df.groupby('hour')['return_pct'].agg(['mean', 'count'])
    hourly['win_rate'] = df.groupby('hour')['return_pct'].apply(lambda x: (x > 0).mean() * 100)

    bull_hours = hourly[(hourly['win_rate'] > 55) & (hourly['mean'] > 0.02)].sort_values('mean', ascending=False)
    bear_hours = hourly[(hourly['win_rate'] < 45) & (hourly['mean'] < -0.02)].sort_values('mean')

    print(f'\n--- {sym} ---')
    if not bull_hours.empty:
        print(f'  BULLISH hours (>55% WR, positive mean):')
        for h in bull_hours.index[:5]:
            r = bull_hours.loc[h]
            print(f'    Hour {h:02d} UTC: mean={r["mean"]:+.3f}%, WR={r["win_rate"]:.1f}%, N={int(r["count"])}')
    else:
        print(f'  No consistently bullish hours found')

    if not bear_hours.empty:
        print(f'  BEARISH hours (<45% WR, negative mean):')
        for h in bear_hours.index[:5]:
            r = bear_hours.loc[h]
            print(f'    Hour {h:02d} UTC: mean={r["mean"]:+.3f}%, WR={r["win_rate"]:.1f}%, N={int(r["count"])}')
    else:
        print(f'  No consistently bearish hours found')

# CROSS-ASSET CORRELATION BY HOUR
print('\n' + '=' * 80)
print('CROSS-ASSET HOURLY CORRELATION')
print('=' * 80)
# Merge by time
merged = data['BTC'][['time', 'hour', 'return_pct']].rename(columns={'return_pct': 'BTC_ret'})
for sym in ['SOL', 'HYPE']:
    tmp = data[sym][['time', 'return_pct']].rename(columns={'return_pct': f'{sym}_ret'})
    merged = merged.merge(tmp, on='time', how='inner')

print(f'\nOverall correlation (N={len(merged)}):')
print(f'  BTC-SOL:  {merged["BTC_ret"].corr(merged["SOL_ret"]):.3f}')
print(f'  BTC-HYPE: {merged["BTC_ret"].corr(merged["HYPE_ret"]):.3f}')
print(f'  SOL-HYPE: {merged["SOL_ret"].corr(merged["HYPE_ret"]):.3f}')

print(f'\nCorrelation by hour (look for decorrelation = diversification opportunity):')
print(f'{"Hour":>4} {"BTC-SOL":>8} {"BTC-HYPE":>9} {"SOL-HYPE":>9}')
for h in range(24):
    sub = merged[merged['hour'] == h]
    if len(sub) > 5:
        c1 = sub['BTC_ret'].corr(sub['SOL_ret'])
        c2 = sub['BTC_ret'].corr(sub['HYPE_ret'])
        c3 = sub['SOL_ret'].corr(sub['HYPE_ret'])
        note = ''
        if c2 < 0.3 or c3 < 0.3:
            note = ' <-- LOW CORR (diversify here)'
        print(f'{h:4d} {c1:8.3f} {c2:9.3f} {c3:9.3f}{note}')
