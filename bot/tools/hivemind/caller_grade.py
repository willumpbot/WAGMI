"""Grade Telegram meme-coin callers by what their called coins actually did afterwards.

Reads data/hivemind/tg/history_calls.jsonl (local, gitignored, other people's messages) and the
pre-registered method in data/hivemind/tg/CALLER_GRADE_PREREG.md. Prices come from the free
GeckoTerminal API (pool OHLCV, past 180 days only) with DexScreener used only to find the chain of 0x
addresses. Every API response is cached under data/hivemind/tg/price_cache/ so reruns are free and
reproducible (--offline never touches the network).

Writes (all under data/hivemind/tg/, never commit them):
  caller_calls_graded.jsonl  one row per graded/unpriceable first-call
  caller_grades.json         per chat base rates + per caller scores
  CALLER_GRADES.md           plain-language summary + ranked tables

Usage: python tools/hivemind/caller_grade.py [--chats syndicate,hitters,dtn] [--offline]
This file contains no chat data.
"""
import argparse
import hashlib
import json
import random
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

BOT = Path(__file__).resolve().parents[2]
TG = BOT / "data" / "hivemind" / "tg"
SRC = TG / "history_calls.jsonl"
CACHE = TG / "price_cache"
OUT_ROWS = TG / "caller_calls_graded.jsonl"
OUT_JSON = TG / "caller_grades.json"
OUT_MD = TG / "CALLER_GRADES.md"

AS_OF = int(datetime(2026, 10, 8, 22, 0, tzinfo=timezone.utc).timestamp())
WINDOW_LO = AS_OF - 178 * 86400
H7 = 7 * 86400
FEE_PCT = 3.0
MIN_N = 8
SAMPLE_CAP = 40
SAMPLE_SEED = 20261008
N_BOOT = 10000
GT = "https://api.geckoterminal.com/api/v2"
DS = "https://api.dexscreener.com/latest/dex/tokens/"
EVM_RE = re.compile(r"0x[0-9a-fA-F]{40}")
DS_TO_GT = {"ethereum": "eth", "bsc": "bsc", "base": "base", "arbitrum": "arbitrum", "polygon": "polygon_pos",
            "avalanche": "avax", "solana": "solana", "optimism": "optimism", "blast": "blast", "sonic": "sonic",
            "abstract": "abstract", "hyperevm": "hyperevm", "unichain": "unichain"}
CHATS = {"syndicate": "Syndicate 2.0", "hitters": "\U0001f48eDTN Hitters\U0001f48e",
         "dtn": "\U0001f48eDiamond Trencher Network\U0001f48e"}
SAMPLED = {"hitters", "dtn"}
PARTIAL = {"dtn"}

OFFLINE = False
_last = {"gt": 0.0, "ds": 0.0}
_gap = {"gt": 2.2, "ds": 0.3}   # adaptive: widened on 429, relaxed on success
_stats = Counter()


# ---------------------------------------------------------------- cached HTTP
def _get(url, kind):
    """GET json with a disk cache. Deterministic answers (200/404/401) are cached; 429/5xx are retried."""
    key = hashlib.sha1(url.encode()).hexdigest()
    path = CACHE / f"{key}.json"
    if path.exists():
        _stats["cache_hit"] += 1
        return json.loads(path.read_text(encoding="utf-8"))
    if OFFLINE:
        _stats["offline_miss"] += 1
        return {"_status": "offline_miss"}
    for attempt in range(12):
        wait = _last[kind] + _gap[kind] - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[kind] = time.time()
        _stats["net_" + kind] += 1
        req = urllib.request.Request(url, headers={"User-Agent": "caller-grade/1.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = json.loads(r.read().decode("utf-8"))
                body["_status"] = 200
                _gap[kind] = max(2.2 if kind == "gt" else 0.3, _gap[kind] - 0.25)
        except urllib.error.HTTPError as e:
            if e.code in (404, 401, 400, 422):
                body = {"_status": e.code}
            else:
                if e.code == 429:
                    _stats["429"] += 1
                    _gap[kind] = min(_gap[kind] + 1.0, 8.0)
                    time.sleep(min(10 * (attempt + 1), 60))
                else:
                    time.sleep(5 * (attempt + 1))
                continue
        except Exception:
            time.sleep(5 * (attempt + 1))
            continue
        body["_url"] = url
        path.write_text(json.dumps(body), encoding="utf-8")
        return body
    return {"_status": "api_error"}


def _ts(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() if iso else None


def token_pools(net, ca):
    d = _get(f"{GT}/networks/{net}/tokens/{ca}/pools?page=1", "gt")
    if d.get("_status") != 200:
        return d.get("_status"), []
    out = []
    for p in d.get("data", []):
        a = p["attributes"]
        out.append({"address": a["address"], "created": _ts(a.get("pool_created_at")),
                    "reserve": float(a.get("reserve_in_usd") or 0),
                    "dex": (p.get("relationships", {}).get("dex", {}).get("data") or {}).get("id", "")})
    return 200, out


def pool_base_token(net, addr):
    d = _get(f"{GT}/networks/{net}/pools/{addr}", "gt")
    if d.get("_status") != 200:
        return None
    try:
        return d["data"]["relationships"]["base_token"]["data"]["id"].split("_", 1)[1]
    except Exception:
        return None


def ohlcv(net, pool, tf, before, limit, ca):
    d = _get(f"{GT}/networks/{net}/pools/{pool}/ohlcv/{tf}?aggregate=1&limit={limit}"
             f"&before_timestamp={int(before)}&token={ca}&currency=usd", "gt")
    if d.get("_status") != 200:
        return None
    rows = d.get("data", {}).get("attributes", {}).get("ohlcv_list", []) or []
    return sorted(([float(x) for x in r] for r in rows), key=lambda r: r[0])


def resolve_network(ca):
    if not EVM_RE.fullmatch(ca):
        return ["solana"]
    d = _get(DS + ca, "ds")
    nets = []
    for p in (d.get("pairs") or []):
        n = DS_TO_GT.get(p.get("chainId"), p.get("chainId"))
        if n and n not in nets:
            nets.append(n)
    return nets or ["eth", "base", "bsc"]


# ---------------------------------------------------------------- grading one call
def _merge(lists):
    best = {}
    for lst in lists:
        for c in lst or []:
            if c[0] not in best or c[5] > best[c[0]][5]:
                best[c[0]] = c
    return [best[k] for k in sorted(best)]


def realistic(path, entry):
    """50% off at 2x, stop 0.5x on whatever is left, else exit at the 7-day close; minus fees. In %."""
    stop, tp = 0.5 * entry, 2.0 * entry
    held, cash, tp_done = 1.0, 0.0, False
    for t, o, h, l, c, v in path:
        if held <= 0:
            break
        if not tp_done:
            if o >= tp:
                cash += 0.5 * o / entry
                held, tp_done = 0.5, True
                if l <= stop:
                    cash += held * stop / entry
                    held = 0.0
            elif l <= stop:
                cash += held * min(stop, o) / entry
                held = 0.0
            elif h >= tp:
                cash += 0.5 * tp / entry
                held, tp_done = 0.5, True
        elif l <= stop:
            cash += held * min(stop, o) / entry
            held = 0.0
    if held > 0:
        last = path[-1][4] if path else entry
        cash += held * last / entry
    return (cash - 1.0) * 100.0 - FEE_PCT


def grade_call(r):
    ts = r["ts"]
    base = {k: r[k] for k in ("chat", "sender_id", "sender", "ca", "ts", "msg_id")}
    if ts < WINDOW_LO:
        return {**base, "status": "unpriceable", "reason": "outside_free_history"}
    if ts > AS_OF - H7:
        return {**base, "status": "too_recent"}
    net, pools, ca = None, [], r["ca"]
    for n in resolve_network(ca):
        st, pools = token_pools(n, ca)
        if st == 200 and pools:
            net = n
            break
        if st == "api_error":
            return {**base, "status": "unpriceable", "reason": "api_error"}
    if not pools:  # maybe a pair/pool address from a chart link
        for n in resolve_network(ca):
            tok = pool_base_token(n, ca)
            if tok:
                st, pools = token_pools(n, tok)
                if st == 200 and pools:
                    net, ca = n, tok
                    break
    if not pools:
        return {**base, "status": "unpriceable", "reason": "no_pools"}
    base["token"] = ca
    created = [p["created"] for p in pools if p["created"]]
    age_min = (ts - min(created)) / 60 if created else None
    existed = [p for p in pools if p["created"] and p["created"] <= ts]
    if existed:
        chosen = [max(existed, key=lambda p: p["reserve"])]
        pump = [p for p in existed if p["dex"].startswith("pump-fun")]
        later = [p for p in pools if p["created"] and ts < p["created"] <= ts + H7 and not p["dex"].startswith("pump-fun")]
        if pump and later:
            chosen = [pump[0], max(later, key=lambda p: p["reserve"])]
        elif pump and chosen[0] is not pump[0] and chosen[0]["reserve"] < 1:
            chosen = [pump[0]]
    else:
        chosen = [min(pools, key=lambda p: p["created"] or 9e18)]
    call_min = int(ts // 60 * 60)
    m_before = call_min + 1000 * 60
    end = ts + H7
    mins, hours = [], []
    for p in chosen:
        m = ohlcv(net, p["address"], "minute", m_before, 1000, ca)
        h = ohlcv(net, p["address"], "hour", int(end // 3600 * 3600 + 3600), 200, ca)
        if m is None and h is None:
            return {**base, "status": "unpriceable", "reason": "api_error"}
        mins.append(m or [])
        hours.append(h or [])
    mins, hours = _merge(mins), _merge(hours)
    after = [c for c in mins if c[0] >= call_min]
    if not after or after[0][0] - ts > 3600:
        return {**base, "status": "unpriceable", "reason": "no_market_at_call", "age_min": age_min}
    entry_c = after[0]
    entry = entry_c[4]
    if entry <= 0:
        return {**base, "status": "unpriceable", "reason": "no_market_at_call", "age_min": age_min}
    h0 = m_before // 3600 * 3600
    path = [c for c in after[1:] if c[0] < min(m_before, end)] + [c for c in hours if h0 <= c[0] < end]

    def price_at(hz):
        px = entry
        for c in path:
            if c[0] < ts + hz:
                px = c[4]
            else:
                break
        return px

    peak_mult, peak_i = 1.0, -1
    for i, c in enumerate(path):
        if c[2] / entry > peak_mult:
            peak_mult, peak_i = c[2] / entry, i
    dd = min([c[3] for c in path[:peak_i + 1]] + [entry]) / entry - 1 if peak_i >= 0 else 0.0
    return {**base, "status": "graded", "net": net, "pools": [p["address"] for p in chosen],
            "age_min": age_min, "entry": entry, "entry_lag_s": entry_c[0] - call_min,
            "ret_1h": (price_at(3600) / entry - 1) * 100, "ret_24h": (price_at(86400) / entry - 1) * 100,
            "ret_7d": (price_at(H7) / entry - 1) * 100, "peak_mult": peak_mult,
            "max_dd_before_peak": dd * 100, "hit": peak_mult >= 2.0, "realistic": realistic(path, entry)}


# ---------------------------------------------------------------- statistics
def boot_ci(v, fn, seed=7):
    v = np.asarray(v, dtype=float)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(v), size=(N_BOOT, len(v)))
    s = fn(v[idx], axis=1)
    return [float(np.percentile(s, 2.5)), float(np.percentile(s, 97.5))]


def null_test(caller_rows, chat_rows, seed=11):
    rng = np.random.default_rng(seed)
    draws = []
    for r in caller_rows:
        wk = datetime.fromtimestamp(r["ts"], timezone.utc).isocalendar()[:2]
        cands = [x["realistic"] for x in chat_rows if x["sender_id"] != r["sender_id"]
                 and datetime.fromtimestamp(x["ts"], timezone.utc).isocalendar()[:2] == wk]
        if not cands:
            cands = [x["realistic"] for x in chat_rows if x["sender_id"] != r["sender_id"]
                     and abs(x["ts"] - r["ts"]) <= 14 * 86400]
        if not cands:   # nothing within +/-14 d: the 20 nearest-in-time calls by other senders
            near = sorted((x for x in chat_rows if x["sender_id"] != r["sender_id"]), key=lambda x: abs(x["ts"] - r["ts"]))
            cands = [x["realistic"] for x in near[:20]]
        if not cands:
            return None
        draws.append(rng.choice(np.asarray(cands), size=N_BOOT))
    m = np.vstack(draws)
    obs = np.array([r["realistic"] for r in caller_rows])
    nmed, nmean = np.median(m, axis=0), m.mean(axis=0)
    return {"null_median_of_medians": float(np.median(nmed)), "null_mean_of_means": float(np.mean(nmean)),
            "p_null_median": float((nmed >= np.median(obs)).mean()), "p_null_mean": float((nmean >= obs.mean()).mean())}


def age_bucket(a):
    if a is None:
        return "unknown"
    return "<1h" if a < 60 else "1-24h" if a < 1440 else "1-7d" if a < 10080 else ">7d"


AGE_ORDER = ["<1h", "1-24h", "1-7d", ">7d", "unknown"]
HOUR_ORDER = ["00-06", "06-12", "12-18", "18-24"]


def hour_bucket(ts):
    return HOUR_ORDER[datetime.fromtimestamp(ts, timezone.utc).hour // 6]


def summarize(rows):
    v = [r["realistic"] for r in rows]
    if not v:
        return {"n": 0}
    return {"n": len(v), "hit_rate": float(np.mean([r["hit"] for r in rows])),
            "median_realistic": float(np.median(v)), "mean_realistic": float(np.mean(v)),
            "median_ci": boot_ci(v, np.median) if len(v) >= 3 else None,
            "mean_ci": boot_ci(v, np.mean) if len(v) >= 3 else None,
            "median_peak_mult": float(np.median([r["peak_mult"] for r in rows])),
            "median_ret_1h": float(np.median([r["ret_1h"] for r in rows])),
            "median_ret_24h": float(np.median([r["ret_24h"] for r in rows])),
            "median_ret_7d": float(np.median([r["ret_7d"] for r in rows])),
            "share_stopped_or_worse": float(np.mean([x <= -50 for x in v])),
            # EXPLORATORY (not pre-registered): how much of the mean is one coin?
            "mean_without_best_call_EXPLORATORY": float(np.mean(sorted(v)[:-1])) if len(v) > 1 else None}


def by_bucket(rows, keyfn, order):
    out = {}
    for b in order:
        sub = [r for r in rows if keyfn(r) == b]
        if sub:
            out[b] = {"n": len(sub), "median_realistic": float(np.median([r["realistic"] for r in sub])),
                      "hit_rate": float(np.mean([r["hit"] for r in sub]))}
    return out


def is_bot(sender):
    return str(sender).lower().rstrip().endswith("bot")


# ---------------------------------------------------------------- driver
def select_calls(rows, key):
    chat = CHATS[key]
    firsts, seen = [], set()
    for r in sorted((r for r in rows if r["chat"] == chat and r["first_in_chat"]), key=lambda r: r["ts"]):
        k = r["ca"].lower() if EVM_RE.fullmatch(r["ca"]) else r["ca"]   # EVM addresses are case-insensitive
        if k not in seen:
            seen.add(k)
            firsts.append(r)
    if key not in SAMPLED:
        return firsts, False
    by = defaultdict(list)
    for r in firsts:
        by[r["sender_id"]].append(r)
    rng = random.Random(SAMPLE_SEED)
    keep, sampled = [], False
    for sid in sorted(by, key=str):
        elig = [r for r in by[sid] if WINDOW_LO <= r["ts"] <= AS_OF - H7]
        other = [r for r in by[sid] if r not in elig]
        if len(elig) > SAMPLE_CAP:
            elig = rng.sample(elig, SAMPLE_CAP)
            sampled = True
        keep += elig + other
    return sorted(keep, key=lambda r: r["ts"]), sampled


def run_chat(rows, key, fout):
    calls, sampled = select_calls(rows, key)
    graded_rows, seen_tokens, t0 = [], set(), time.time()
    for i, r in enumerate(calls):
        g = grade_call(r)
        if g["status"] == "graded":
            if g["token"] in seen_tokens:   # pool-address alias of a token already called earlier
                continue
            seen_tokens.add(g["token"])
        graded_rows.append(g)
        fout.write(json.dumps(g) + "\n")
        if (i + 1) % 10 == 0:
            print(f"  [{key}] {i + 1}/{len(calls)}  net_gt={_stats['net_gt']} cache={_stats['cache_hit']} 429s={_stats['429']} gap={_gap['gt']:.1f} "
                  f"{time.time() - t0:.0f}s", flush=True)
    g = [r for r in graded_rows if r["status"] == "graded"]
    status = Counter(r["status"] if r["status"] != "unpriceable" else "unpriceable:" + r["reason"] for r in graded_rows)
    chat = {"chat": CHATS[key], "partial_export": key in PARTIAL, "sampled_max_per_caller": SAMPLE_CAP if sampled else None,
            "first_calls_considered": len(graded_rows), "status_counts": dict(status),
            "base_all": summarize(g), "base_humans": summarize([r for r in g if not is_bot(r["sender"])]),
            "by_token_age": by_bucket(g, lambda r: age_bucket(r.get("age_min")), AGE_ORDER),
            "by_hour_utc": by_bucket(g, lambda r: hour_bucket(r["ts"]), HOUR_ORDER), "callers": []}
    base_med = chat["base_all"].get("median_realistic", 0.0)
    base_mean = chat["base_all"].get("mean_realistic", 0.0)
    by = defaultdict(list)
    for r in graded_rows:
        by[r["sender_id"]].append(r)
    for sid, rs in by.items():
        gr = [r for r in rs if r["status"] == "graded"]
        c = {"sender_id": sid, "handle": rs[0]["sender"], "is_bot": is_bot(rs[0]["sender"]),
             "first_calls": len(rs), "unpriceable": sum(r["status"] == "unpriceable" for r in rs),
             "too_recent": sum(r["status"] == "too_recent" for r in rs), **summarize(gr)}
        c["ranked"] = c["n"] >= MIN_N and not c["is_bot"]
        if c["n"]:
            c["vs_base_median"] = c["median_realistic"] - base_med
            c["vs_base_mean"] = c["mean_realistic"] - base_mean
            ages = Counter(age_bucket(r.get("age_min")) for r in gr)
            c["token_age_profile"] = {b: ages[b] / len(gr) for b in AGE_ORDER if ages[b]}
            c["median_age_min"] = float(np.median([r["age_min"] for r in gr if r.get("age_min") is not None] or [np.nan]))
            c["realistic_by_age"] = by_bucket(gr, lambda r: age_bucket(r.get("age_min")), AGE_ORDER)
        if c["n"] >= MIN_N:
            c["null"] = null_test(gr, g)
        chat["callers"].append(c)
    chat["callers"].sort(key=lambda c: (not c.get("ranked"), -(c.get("median_realistic") or -1e9)))
    ranked = [c for c in chat["callers"] if c["ranked"]]
    chat["n_ranked"] = len(ranked)
    chat["n_beat_null_median_p05"] = sum(1 for c in ranked if c.get("null") and c["null"]["p_null_median"] < 0.05)
    chat["expected_lucky_passes"] = round(0.05 * len(ranked), 2)
    return chat


def pct(x, d=0):
    return "-" if x is None else f"{x:+.{d}f}%"


def headline(ch):
    b = ch["base_all"]
    if not b.get("n"):
        return "No calls could be graded."
    ranked = [c for c in ch["callers"] if c["ranked"]]
    winners = [c for c in ranked if c.get("null") and c["null"]["p_null_median"] < 0.05
               and c.get("median_ci") and c["median_ci"][0] > 0]
    beat = [c for c in ranked if c.get("null") and c["null"]["p_null_median"] < 0.05]
    s = [f"{b['n']} calls could be priced. A typical call (median) returned {pct(b['median_realistic'])} after "
         f"the realistic plan (half off at 2x, stop at -50%, 3% fees); {b['hit_rate'] * 100:.0f}% of calls "
         f"touched 2x at some point within 7 days."]
    if not ranked:
        s.append(f"Nobody has {MIN_N}+ graded calls, so nobody can be ranked yet.")
    elif winners:
        s.append(f"{len(winners)} of {len(ranked)} ranked callers beat random same-week calls from this chat AND "
                 f"have a typical result above zero even at the low end of the 95% range: "
                 + ", ".join(f"{c['handle']} (n={c['n']})" for c in winners) + ".")
    elif beat:
        s.append(f"{len(beat)} of {len(ranked)} ranked callers beat random same-week calls (p<0.05), but none is "
                 f"reliably profitable on their own after fees (their 95% range still includes losing). "
                 f"With {len(ranked)} callers tested, about {ch['expected_lucky_passes']} would pass by luck alone.")
    else:
        s.append(f"No ranked caller ({len(ranked)} with {MIN_N}+ calls) beats random calls drawn from the same chat in "
                 f"the same week. Differences between callers here look like luck.")
    if ranked:
        top = max(ranked, key=lambda c: c["mean_realistic"])
        wo = top.get("mean_without_best_call_EXPLORATORY")
        if wo is not None and top["mean_realistic"] > 0 > wo:
            s.append(f"The best AVERAGE ({top['handle']}, {pct(top['mean_realistic'])}) is one lucky coin: "
                     f"without their single best call it is {pct(wo)}.")
    st = ch["status_counts"]
    unp = sum(v for k, v in st.items() if k.startswith("unpriceable"))
    s.append(f"{unp} of {ch['first_calls_considered']} first-calls were unpriceable and {st.get('too_recent', 0)} are "
             f"too recent (<7 days old) to grade.")
    return " ".join(s)


def write_md(result):
    L = ["# Caller grades - who in the TG groups actually calls winners?", "",
         f"As of {datetime.fromtimestamp(AS_OF, timezone.utc):%Y-%m-%d %H:%M} UTC. Method fixed in advance: "
         "CALLER_GRADE_PREREG.md. Local only, never commit.", "",
         "**How to read the score.** For each coin a person was FIRST to post, we pretend you bought within about a minute "
         "of the post, sold half at 2x, kept a stop at -50%, and sold the rest after 7 days, minus 3% fees. "
         "\"Typical\" = median (the middle call), which a single 50x moonshot cannot distort. "
         "\"Beats random?\" compares the person to random coins other people posted in the same chat the same week. "
         "Because the plan ends most coins at either -53% (stopped out) or +22% (half sold at 2x, the rest stopped), "
         "the typical result is usually one of those two numbers.", ""]
    syn = result["chats"].get("syndicate")
    if syn and syn["base_all"].get("n"):
        b = syn["base_all"]
        ranked = [c for c in syn["callers"] if c["ranked"]]
        good = [c for c in ranked if c.get("null") and c["null"]["p_null_median"] < 0.05
                and c.get("median_ci") and c["median_ci"][0] > 0]
        L += ["## Headline", "",
              ("**Is anyone in Syndicate actually good, after fees and luck? "
               + ("Yes: " + ", ".join(c["handle"] for c in good) + ".**" if good else "Not that the data can show.**")),
              f"Blindly following every Syndicate call with the realistic plan loses: the typical call ends "
              f"{pct(b['median_realistic'])} (stopped out) and the average is {pct(b['mean_realistic'])}, even though "
              f"{b['hit_rate'] * 100:.0f}% of coins briefly touch 2x - most pump fast and bleed out (typical coin is "
              f"{pct(b['median_ret_24h'])} after 24h and {pct(b['median_ret_7d'])} after 7 days). "
              f"Only {len(ranked)} people have the {MIN_N}+ priced calls needed to be ranked, and "
              + (f"{len(good)} beat random coins other members posted the same week. " if good else
                 "none of them does better than random coins other members posted the same week. ")
              + ("Any positive average is carried by a single huge coin. "
                 if any(c["mean_realistic"] > 0 > (c.get("mean_without_best_call_EXPLORATORY") or 0) for c in ranked) else "")
              + (f"Small samples ({min(c['n'] for c in ranked)}-{max(c['n'] for c in ranked)} calls each) mean "
                 if ranked else "Small samples mean ")
              + f"a real but modest edge could still be hiding - this says "
              f"\"no proof of skill yet\", not \"proven useless\".", ""]
    for key, ch in result["chats"].items():
        flag = " (PARTIAL export)" if ch["partial_export"] else ""
        samp = f" Sample: at most {ch['sampled_max_per_caller']} random calls per caller (seed fixed)." \
            if ch["sampled_max_per_caller"] else ""
        L += [f"## {ch['chat']}{flag}", "", "**Answer:** " + headline(ch) + samp, ""]
        b, bh = ch["base_all"], ch["base_humans"]
        if b.get("n"):
            L += [f"Chat base rate: n={b['n']}, typical {pct(b['median_realistic'])} "
                  f"(95% range {pct(b['median_ci'][0])} to {pct(b['median_ci'][1])}), average {pct(b['mean_realistic'])}, "
                  f"2x hit rate {b['hit_rate'] * 100:.0f}%, stopped out or worse {b['share_stopped_or_worse'] * 100:.0f}%. "
                  f"Humans only: n={bh.get('n', 0)}, typical {pct(bh.get('median_realistic'))}.", ""]
            L += ["| Rank | Caller | Graded n | Unpriceable | 2x hit | Typical (median) | 95% range | Average (mean) | "
                  "Average without their best call* | vs chat | Beats random? (p) | Mostly calls tokens aged |",
                  "|---|---|---|---|---|---|---|---|---|---|---|---|"]
            for i, c in enumerate([c for c in ch["callers"] if c["ranked"]], 1):
                nl = c.get("null") or {}
                p = nl.get("p_null_median")
                verdict = "-" if p is None else ("YES" if p < 0.05 else "no") + f" ({p:.2f})"
                prof = max(c["token_age_profile"].items(), key=lambda kv: kv[1])
                L.append(f"| {i} | {c['handle']} | {c['n']} | {c['unpriceable']} | {c['hit_rate'] * 100:.0f}% | "
                         f"{pct(c['median_realistic'])} | {pct(c['median_ci'][0])} to {pct(c['median_ci'][1])} | "
                         f"{pct(c['mean_realistic'])} | {pct(c['mean_without_best_call_EXPLORATORY'])} | "
                         f"{pct(c['vs_base_median'])} | {verdict} | "
                         f"{prof[0]} ({prof[1] * 100:.0f}%) |")
            L += ["", "*EXPLORATORY column, not pre-registered: shows when an average is carried by one lucky coin. "
                  "\"Beats random?\" uses the typical (median) result; a tie with random counts as NOT beating it."]
            small = [c for c in ch["callers"] if not c["ranked"]]
            if small:
                L += ["", f"Not ranked (bots, or fewer than {MIN_N} graded calls): " + ", ".join(
                    f"{c['handle']} n={c.get('n', 0)}" for c in small[:40]) + (" ..." if len(small) > 40 else "")]
            L += ["", "Token age at the call (whole chat):", "",
                  "| Age | n | Typical | 2x hit |", "|---|---|---|---|"]
            for k, v in ch["by_token_age"].items():
                L.append(f"| {k} | {v['n']} | {pct(v['median_realistic'])} | {v['hit_rate'] * 100:.0f}% |")
            L += ["", "Time of day of the call (UTC):", "", "| Hours | n | Typical | 2x hit |", "|---|---|---|---|"]
            for k, v in ch["by_hour_utc"].items():
                L.append(f"| {k} | {v['n']} | {pct(v['median_realistic'])} | {v['hit_rate'] * 100:.0f}% |")
        L += ["", "Status of first-calls: " + ", ".join(f"{k}={v}" for k, v in sorted(ch["status_counts"].items())), ""]
    if "dtn" not in result["chats"]:
        L += ["## 💎Diamond Trencher Network💎 (PARTIAL export)", "",
              "Not graded in this run: the free price API is shared with the always-on microcap collector on this PC, "
              "which leaves ~5 requests/min; the pre-registered 40-per-caller sample (~970 calls) would take ~8 hours. "
              "Run `python tools/hivemind/caller_grade.py --chats dtn` to add it (cached, resumable).", ""]
    L += ["## Caveats", "",
          "- Free price history only reaches back 180 days; older calls are counted as unpriceable, not dropped.",
          "- Highs/lows are 1-minute candles for the first ~16h and 1-hour candles after; a wick to 2x may not be "
          "fillable in size, so hit rate and the realistic plan are, if anything, optimistic.",
          "- Stop fills assume you get out at -50% unless the candle opened lower; a one-trade rug inside a candle "
          "would really fill lower. Again optimistic.",
          "- Credit goes only to whoever posted a coin FIRST in that chat; reposts and shills of already-posted coins "
          "are ignored.", "- Means are shown but meme returns are fat-tailed: trust the typical (median) column and "
          "its 95% range.", ""]
    OUT_MD.write_text("\n".join(L), encoding="utf-8")


def main():
    global OFFLINE
    ap = argparse.ArgumentParser()
    ap.add_argument("--chats", default="syndicate,hitters,dtn")
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    OFFLINE = a.offline
    CACHE.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(l) for l in open(SRC, encoding="utf-8")]
    result = {"as_of": AS_OF, "prereg": "CALLER_GRADE_PREREG.md", "chats": {}}
    if OUT_JSON.exists():   # keep chats graded in earlier runs that are not re-run now
        try:
            result["chats"] = json.loads(OUT_JSON.read_text(encoding="utf-8")).get("chats", {})
        except Exception:
            pass
    keys = [k.strip() for k in a.chats.split(",") if k.strip()]
    old = [l for l in open(OUT_ROWS, encoding="utf-8")] if OUT_ROWS.exists() else []
    old = [l for l in old if json.loads(l)["chat"] not in {CHATS[k] for k in keys}]
    with open(OUT_ROWS, "w", encoding="utf-8") as fout:
        fout.writelines(old)
        for k in keys:
            print(f"grading {k} ...", flush=True)
            result["chats"][k] = run_chat(rows, k, fout)
            result["chats"] = {kk: result["chats"][kk] for kk in CHATS if kk in result["chats"]}
            OUT_JSON.write_text(json.dumps(result, indent=1, default=str), encoding="utf-8")
            write_md(result)
            fout.flush()
    print("done", dict(_stats), flush=True)


if __name__ == "__main__":
    main()
