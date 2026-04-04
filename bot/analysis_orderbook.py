"""Order book imbalance study - is it predictive on Hyperliquid?"""
import ccxt
import time
import json
import math
from datetime import datetime, timezone

exchange = ccxt.hyperliquid()

snapshots = []
symbols = ['BTC', 'SOL', 'HYPE', 'ETH']
print(f'Starting 20 snapshots over ~10 minutes...')
print(f'Start: {datetime.now(timezone.utc).strftime("%H:%M:%S")} UTC')

for i in range(20):
    for sym_name in symbols:
        sym = f'{sym_name}/USDC:USDC'
        try:
            book = exchange.fetch_order_book(sym, limit=50)
            ticker = exchange.fetch_ticker(sym)

            bids = book['bids']
            asks = book['asks']
            mid = (bids[0][0] + asks[0][0]) / 2
            spread = (asks[0][0] - bids[0][0]) / mid * 100

            # Top 5 levels (tight)
            bid5 = sum(b[0]*b[1] for b in bids[:5])
            ask5 = sum(a[0]*a[1] for a in asks[:5])
            imb5 = (bid5 - ask5) / (bid5 + ask5) if (bid5+ask5) > 0 else 0

            # Top 10 levels
            bid10 = sum(b[0]*b[1] for b in bids[:10])
            ask10 = sum(a[0]*a[1] for a in asks[:10])
            imb10 = (bid10 - ask10) / (bid10 + ask10) if (bid10+ask10) > 0 else 0

            # All levels
            bid_all = sum(b[0]*b[1] for b in bids)
            ask_all = sum(a[0]*a[1] for a in asks)
            imb_all = (bid_all - ask_all) / (bid_all + ask_all) if (bid_all+ask_all) > 0 else 0

            snapshots.append({
                'snap': i,
                'time': datetime.now(timezone.utc).isoformat(),
                'symbol': sym_name,
                'price': ticker['last'],
                'mid': mid,
                'spread': spread,
                'imb5': imb5,
                'imb10': imb10,
                'imb_all': imb_all,
                'bid5': bid5,
                'ask5': ask5,
                'bid_all': bid_all,
                'ask_all': ask_all,
            })
        except Exception as e:
            print(f'  Error {sym_name}: {e}')

    if i % 5 == 0:
        print(f'  Snapshot {i+1}/20 at {datetime.now(timezone.utc).strftime("%H:%M:%S")}')
    if i < 19:
        time.sleep(30)

print(f'End: {datetime.now(timezone.utc).strftime("%H:%M:%S")} UTC')
print(f'Total snapshots: {len(snapshots)}')
print()

# Save raw data
with open('data/orderbook_study.json', 'w') as f:
    json.dump(snapshots, f, indent=2)

# ANALYSIS
print('='*80)
print('ORDER BOOK IMBALANCE PREDICTIVE ANALYSIS')
print('='*80)

for sym_name in symbols:
    sym_snaps = [s for s in snapshots if s['symbol'] == sym_name]
    print(f'\n--- {sym_name} ({len(sym_snaps)} snapshots) ---')

    # Price range
    prices = [s['price'] for s in sym_snaps]
    price_range = (max(prices) - min(prices)) / min(prices) * 100
    print(f'Price range: ${min(prices):.2f} - ${max(prices):.2f} ({price_range:.4f}%)')
    avg_spread = sum(s["spread"] for s in sym_snaps) / len(sym_snaps)
    print(f'Avg spread: {avg_spread:.4f}%')

    # Imbalance stability
    imbs = [s['imb5'] for s in sym_snaps]
    mean_imb = sum(imbs) / len(imbs)
    std_imb = math.sqrt(sum((x - mean_imb)**2 for x in imbs) / len(imbs))
    print(f'Imb5 range: {min(imbs):+.3f} to {max(imbs):+.3f}, mean={mean_imb:+.3f}, std={std_imb:.3f}')

    # Sign changes (stability)
    sign_changes = sum(1 for j in range(1, len(imbs)) if (imbs[j] > 0) != (imbs[j-1] > 0))
    print(f'Imbalance sign flips: {sign_changes}/{len(imbs)-1} ({sign_changes/(len(imbs)-1)*100:.0f}%)')

    # Predictive accuracy at each depth
    for depth_key in ['imb5', 'imb10', 'imb_all']:
        correct = 0
        wrong = 0
        neutral = 0
        profit_if_follow = 0.0

        for j in range(len(sym_snaps)-1):
            curr = sym_snaps[j]
            next_s = sym_snaps[j+1]
            price_chg = (next_s['price'] - curr['price']) / curr['price'] * 100
            imb = curr[depth_key]

            if abs(price_chg) < 0.001:  # negligible move
                neutral += 1
                continue

            if (imb > 0 and price_chg > 0) or (imb < 0 and price_chg < 0):
                correct += 1
                profit_if_follow += abs(price_chg)
            else:
                wrong += 1
                profit_if_follow -= abs(price_chg)

        total = correct + wrong
        acc = correct/total*100 if total > 0 else 0
        print(f'  {depth_key}: {correct}/{total} correct ({acc:.0f}%) | net_edge={profit_if_follow:+.4f}%')

    # Detailed log for imb5
    print(f'  Detailed (imb5 -> next 30s price change):')
    for j in range(len(sym_snaps)-1):
        curr = sym_snaps[j]
        next_s = sym_snaps[j+1]
        price_chg = (next_s['price'] - curr['price']) / curr['price'] * 100
        imb = curr['imb5']
        tag = 'HIT' if (imb > 0 and price_chg > 0) or (imb < 0 and price_chg < 0) else 'MISS'
        if abs(price_chg) < 0.001:
            tag = 'FLAT'
        print(f'    snap{j:02d} imb={imb:+.3f} -> {price_chg:+.5f}% [{tag}]')

print()
print('='*80)
print('CROSS-SYMBOL IMBALANCE CORRELATION')
print('='*80)
for i in range(20):
    snap_group = [s for s in snapshots if s['snap'] == i]
    parts = []
    for s in snap_group:
        parts.append(f'{s["symbol"]}={s["imb5"]:+.3f}')
    print(f'  snap{i:02d}: {"  ".join(parts)}')

# Summary stats
print()
print('='*80)
print('SUMMARY: DEPTH COMPARISON')
print('='*80)
for sym_name in symbols:
    sym_snaps = [s for s in snapshots if s['symbol'] == sym_name]
    print(f'\n{sym_name}:')
    print(f'  Avg bid5 $: ${sum(s["bid5"] for s in sym_snaps)/len(sym_snaps):,.0f}')
    print(f'  Avg ask5 $: ${sum(s["ask5"] for s in sym_snaps)/len(sym_snaps):,.0f}')
    print(f'  Avg bid_all $: ${sum(s["bid_all"] for s in sym_snaps)/len(sym_snaps):,.0f}')
    print(f'  Avg ask_all $: ${sum(s["ask_all"] for s in sym_snaps)/len(sym_snaps):,.0f}')

# Strong imbalance filter analysis
print()
print('='*80)
print('STRONG IMBALANCE FILTER (|imb| > 0.2)')
print('='*80)
for sym_name in symbols:
    sym_snaps = [s for s in snapshots if s['symbol'] == sym_name]
    correct = 0
    wrong = 0
    for j in range(len(sym_snaps)-1):
        curr = sym_snaps[j]
        next_s = sym_snaps[j+1]
        price_chg = (next_s['price'] - curr['price']) / curr['price'] * 100
        imb = curr['imb5']
        if abs(imb) < 0.2:
            continue
        if abs(price_chg) < 0.001:
            continue
        if (imb > 0 and price_chg > 0) or (imb < 0 and price_chg < 0):
            correct += 1
        else:
            wrong += 1
    total = correct + wrong
    if total > 0:
        print(f'  {sym_name}: {correct}/{total} ({correct/total*100:.0f}%) when |imb|>0.2')
    else:
        print(f'  {sym_name}: no strong imbalance signals')
