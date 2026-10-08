"""Mission 12: a risk card for the coins people send the owner.

    from bot.data.laptop_mining.memecard import card
    card("WIF")                       # ticker
    card("0x...")                     # contract address
    card("So11111111111111111111111111111111111111112")

Returns liquidity, 24h volume, pair age, realised volatility, drawdown from ATH,
estimated slippage for $100 / $500 / $2,000, and a position cap that keeps
slippage under 2%.

Free sources only: DexScreener for pair data, GeckoTerminal for OHLCV.

SLIPPAGE MODEL, stated so it can be checked. For a constant-product pool with
total USD liquidity L, each side holds ~L/2, and a trade of size S moves price by
roughly S/(L/2) = 2S/L. So:

    slippage_fraction ~= 2 * S / L
    cap for 2% slippage:  S_max = 0.02 * L / 2 = L / 100

That is a v2-style approximation. Concentrated-liquidity pools (Uniswap v3,
Orca whirlpools) can be far better *inside* their active range and far worse
outside it, so treat the number as an order of magnitude, not a quote.
"""
import json, math, time, urllib.request, urllib.parse

DS = "https://api.dexscreener.com/latest/dex"
GT = "https://api.geckoterminal.com/api/v2"
UA = {"User-Agent": "wagmi-research/1.0"}
SLIP_CAP_PCT = 2.0
CLIPS = (100, 500, 2000)

# Calibration correction for the HAR volatility model on DEX memes.
# Set by the study in MEMECARD.md; 1.0 means no correction.
MEME_VOL_MULTIPLIER = 1.0


def _get(url, tries=3):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            return json.loads(urllib.request.urlopen(req, timeout=25).read())
        except Exception as e:
            if k == tries - 1:
                return {"__err__": str(e)}
            time.sleep(1.5 * (k + 1))
    return {"__err__": "unreachable"}


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _score(p, query):
    """Rank candidate pairs. Liquidity ALONE is not safe.

    Testing the first version: a 'WIF' search returned a robinhood/uniswap
    imposter with $80k liquidity instead of dogwifhat; 'BONK' returned a dead
    pool with $1.7M liquidity and $185 of daily volume; 'FARTCOIN' returned a
    pool claiming $113M liquidity with ZERO volume. Picking the deepest pair
    selects imposters and fake liquidity -- precisely what this card exists to
    protect against.

    So require the pool to be ALIVE (volume and transactions), and prefer an
    exact symbol match.
    """
    liq = _num((p.get("liquidity") or {}).get("usd"))
    v24 = _num((p.get("volume") or {}).get("h24"))
    tx = (p.get("txns") or {}).get("h24") or {}
    ntx = _num(tx.get("buys")) + _num(tx.get("sells"))
    sym = str((p.get("baseToken") or {}).get("symbol") or "").upper()
    exact = sym == query.strip().upper()
    if liq <= 0:
        return -1, liq, v24, ntx, exact
    # a pool with no trading is unusable no matter how deep it claims to be
    if v24 < 1_000 or ntx < 20:
        return -1, liq, v24, ntx, exact
    # geometric blend so neither deep-but-dead nor busy-but-thin wins alone
    s = math.sqrt(liq * min(v24, liq * 50))
    if exact:
        s *= 3.0
    return s, liq, v24, ntx, exact


def _best_pair(query):
    """Resolve a ticker or address to the best LIVE pair, with ambiguity flagged."""
    q = query.strip()
    looks_like_address = len(q) > 25 and " " not in q
    urls = ([f"{DS}/tokens/{urllib.parse.quote(q)}"] if looks_like_address else []) + \
           [f"{DS}/search?q={urllib.parse.quote(q)}"]
    cands = []
    for u in urls:
        d = _get(u)
        if "__err__" in d:
            continue
        for p in (d.get("pairs") or []):
            s, liq, v24, ntx, exact = _score(p, q)
            cands.append({"p": p, "score": s, "liq": liq, "v24": v24,
                          "ntx": ntx, "exact": exact})
        if cands:
            break
    if not cands:
        return None, []
    alive = [c for c in cands if c["score"] > 0]
    rejected = [{"symbol": (c["p"].get("baseToken") or {}).get("symbol"),
                 "chain": c["p"].get("chainId"), "liquidity_usd": round(c["liq"]),
                 "volume_24h_usd": round(c["v24"]), "txns_24h": int(c["ntx"]),
                 "why": "no real trading (vol < $1k or < 20 txns) — possible fake liquidity"}
                for c in cands if c["score"] <= 0 and c["liq"] > 50_000]
    if not alive:
        return None, rejected
    alive.sort(key=lambda c: -c["score"])
    others = [{"symbol": (c["p"].get("baseToken") or {}).get("symbol"),
               "chain": c["p"].get("chainId"), "dex": c["p"].get("dexId"),
               "liquidity_usd": round(c["liq"]), "volume_24h_usd": round(c["v24"])}
              for c in alive[1:6]]
    return alive[0]["p"], rejected + others


def _ohlcv(chain, pool, limit=200):
    net = {"ethereum": "eth", "bsc": "bsc", "solana": "solana", "base": "base",
           "arbitrum": "arbitrum", "polygon": "polygon_pos", "avalanche": "avax",
           "hyperliquid": "hyperliquid"}.get(chain, chain)
    d = _get(f"{GT}/networks/{net}/pools/{pool}/ohlcv/day?limit={limit}")
    if "__err__" in d:
        return []
    lst = ((d.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
    # API returns newest-first; flip to chronological
    return list(reversed(lst))


def _vol_and_drawdown(ohlcv):
    closes = [float(r[4]) for r in ohlcv if r and len(r) >= 5 and r[4]]
    if len(closes) < 5:
        return None
    rets = [(closes[i] / closes[i - 1] - 1) * 100
            for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(rets) < 4:
        return None
    m = sum(rets) / len(rets)
    sd = math.sqrt(sum((x - m) ** 2 for x in rets) / (len(rets) - 1))
    ath = max(closes)
    dd = (closes[-1] / ath - 1) * 100 if ath > 0 else None
    # realised vol over the last 7 and 30 days
    def sdof(xs):
        if len(xs) < 3:
            return None
        mm = sum(xs) / len(xs)
        return math.sqrt(sum((x - mm) ** 2 for x in xs) / (len(xs) - 1))
    return {"days": len(closes), "daily_vol_pct": round(sd, 2),
            "vol_7d_pct": (round(sdof(rets[-7:]), 2) if sdof(rets[-7:]) else None),
            "vol_30d_pct": (round(sdof(rets[-30:]), 2) if sdof(rets[-30:]) else None),
            "drawdown_from_ath_pct": round(dd, 2) if dd is not None else None,
            "ath": ath, "last": closes[-1]}


def card(query):
    """Risk card for a ticker or contract address. Never raises."""
    out = {"query": query, "ok": False, "notes": []}
    p, others = _best_pair(query)
    if not p:
        out["notes"].append("no LIVE pair found (a pool needs >= $1k 24h volume and "
                            ">= 20 trades to be usable)")
        if others:
            out["rejected_pairs"] = others
            out["notes"].append(f"{len(others)} deep-but-untraded pool(s) were rejected; "
                                "high liquidity with no volume is the signature of a trap")
        return out
    out["other_pairs"] = others
    liq = float(((p.get("liquidity") or {}).get("usd") or 0) or 0)
    v24 = float(((p.get("volume") or {}).get("h24") or 0) or 0)
    created = p.get("pairCreatedAt")
    age_days = round((time.time() * 1000 - created) / 86_400_000, 1) if created else None
    base = p.get("baseToken") or {}

    slip = {}
    for c in CLIPS:
        slip[f"${c}"] = round(100.0 * (2.0 * c / liq), 3) if liq > 0 else None
    cap = round(liq / 100.0, 2) if liq > 0 else 0.0

    out.update({
        "ok": True,
        "symbol": base.get("symbol"), "name": base.get("name"),
        "address": base.get("address"),
        "chain": p.get("chainId"), "dex": p.get("dexId"),
        "pair_address": p.get("pairAddress"), "url": p.get("url"),
        "price_usd": p.get("priceUsd"),
        "liquidity_usd": round(liq, 2),
        "volume_24h_usd": round(v24, 2),
        "volume_to_liquidity": round(v24 / liq, 2) if liq > 0 else None,
        "pair_age_days": age_days,
        "price_change": p.get("priceChange"),
        "txns_24h": (p.get("txns") or {}).get("h24"),
        "market_cap": p.get("marketCap"), "fdv": p.get("fdv"),
        "slippage_pct": slip,
        "position_cap_usd_for_2pct_slip": cap,
    })

    hist = _ohlcv(p.get("chainId"), p.get("pairAddress"))
    vd = _vol_and_drawdown(hist)
    if vd:
        out["history"] = vd
        if vd.get("daily_vol_pct"):
            out["expected_move_1d_pct"] = round(vd["daily_vol_pct"] * MEME_VOL_MULTIPLIER, 2)
            out["suggested_stop_pct"] = round(2.0 * vd["daily_vol_pct"] * MEME_VOL_MULTIPLIER, 2)
    else:
        out["notes"].append("no usable OHLCV history; volatility and drawdown unavailable")

    flags = []
    if age_days is not None and age_days < 7:
        flags.append(f"pair is only {age_days}d old")
    if liq < 50_000:
        flags.append(f"thin liquidity (${liq:,.0f}); a $2,000 clip moves price "
                     f"{slip.get('$2000')}%")
    if liq > 0 and v24 / liq > 10:
        flags.append(f"volume is {v24/liq:.0f}x liquidity — churn, likely bots")
    if vd and vd.get("drawdown_from_ath_pct") is not None and vd["drawdown_from_ath_pct"] < -90:
        flags.append(f"down {abs(vd['drawdown_from_ath_pct']):.0f}% from its all-time high")
    if vd and vd.get("daily_vol_pct") and vd["daily_vol_pct"] > 25:
        flags.append(f"daily volatility {vd['daily_vol_pct']:.0f}% — a 2-sigma day is "
                     f"{2*vd['daily_vol_pct']:.0f}%")
    out["risk_flags"] = flags
    out["notes"].append("slippage is a v2 constant-product approximation (2S/L); "
                        "concentrated-liquidity pools differ")
    out["notes"].append("no directional view: nothing here predicts price")
    if not str(query).strip().lower().startswith("0x") and len(str(query).strip()) < 25:
        out["notes"].append("TICKER SEARCH IS AMBIGUOUS -- tickers are not unique and imposters "
                            "are common. Paste the CONTRACT ADDRESS for a definitive answer; "
                            "see other_pairs for what else matched.")
    return out


def _fmt(c):
    if not c.get("ok"):
        return f"  {c['query']}: {'; '.join(c.get('notes') or ['not found'])}"
    h = c.get("history") or {}
    L = [f"  {c.get('symbol')} ({c.get('chain')}/{c.get('dex')})  ${c.get('price_usd')}",
         f"    liquidity ${c['liquidity_usd']:,.0f}   vol24 ${c['volume_24h_usd']:,.0f}"
         f"   v/l {c.get('volume_to_liquidity')}   age {c.get('pair_age_days')}d",
         f"    slippage: " + "  ".join(f"{k} {v}%" for k, v in (c.get('slippage_pct') or {}).items()),
         f"    MAX SIZE for 2% slip: ${c['position_cap_usd_for_2pct_slip']:,.0f}"]
    if h:
        L.append(f"    daily vol {h.get('daily_vol_pct')}%  7d {h.get('vol_7d_pct')}%  "
                 f"30d {h.get('vol_30d_pct')}%  drawdown from ATH {h.get('drawdown_from_ath_pct')}%  "
                 f"({h.get('days')}d history)")
    if c.get("suggested_stop_pct"):
        L.append(f"    suggested stop {c['suggested_stop_pct']}%  (2x expected move)")
    for f in (c.get("risk_flags") or []):
        L.append(f"    [!] {f}")
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    qs = sys.argv[1:] or ["WIF", "BONK", "PEPE", "FARTCOIN"]
    for q in qs:
        print(_fmt(card(q)))
        print()
