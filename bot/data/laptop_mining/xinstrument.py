"""Do the Telegram card ATHs and the pool price paths measure the same thing? Free cross-check.

WHY. Two findings in this project died to instrument error rather than to data: the entry-timing
study measured momentum at the trade's close believing it was the entry, and the megacalls pool rule
picked post-migration survivors. Both were arithmetic-correct on the wrong input. Here two fully
independent instruments happen to cover the same 2026 calls -- regex-parsed Telegram card text from
the chats' own info bots, and GeckoTerminal pool OHLCV -- so they can be made to check each other
at zero API cost, BEFORE any verdict rests on either.

THE SUBTLETY THAT DECIDES WHETHER THE COMPARISON IS EVEN VALID. The two quantities are not the same
by construction:

    path:  peak_m             = max(price after the call) / price at the call
    cards: ath_later/ath_call = peak mcap ever, as of a later card
                              / peak mcap ever, as of a card at the call

`ath` is peak since LAUNCH, so when a coin is called BELOW its all-time high, ath_at_call already
carries that older, higher peak and the card ratio UNDERSTATES what happened after the call -- it
can read 1.00 while the price doubled, simply because the new high never exceeded the old one.

So the instruments can only be compared where the coin was AT its high when it was called
(ath_at_call ~= mcap_at_call). That subset is the validation set; everything else is expected to
disagree in a known direction, and reporting the pooled correlation over both would blame the
instruments for a difference that is definitional. Both are reported separately below.

HORIZONS MUST MATCH. A card follow-up 3 days after the call and a 60-day path peak are different
quantities. Each pair is compared at the card's own horizon, by indexing the hourly path at the same
elapsed time.

ASSUMES CONSTANT SUPPLY, which is what makes mcap ratios comparable to price ratios. Flagged rather
than hidden: a token burn or mint between the two cards breaks it, and that is a real possibility on
this asset class.
"""
import collections
import datetime
import gzip
import io
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
CARDS = os.path.join(HERE, "server_exports", "tg_card_snapshots_anon.jsonl.gz")
CALLS = os.path.join(HERE, "server_exports", "tg_calls_history_anon.jsonl.gz")
PATHS = os.path.join(HERE, "megacalls_paths.jsonl")
WIN = 6 * 3600            # "at the call" tolerance, both sides
AT_HIGH = 1.05            # ath_at_call within 5% of mcap_at_call == called at its high


def sane(v):
    return isinstance(v, (int, float)) and 1000.0 <= v <= 1e10


def load():
    cards = collections.defaultdict(list)
    for line in gzip.open(CARDS, "rt", encoding="utf-8"):
        if not line.strip():
            continue
        d = json.loads(line)
        if sane(d.get("mcap")):
            cards[d["ca"]].append(d)
    for k in cards:
        cards[k].sort(key=lambda c: c["ts"])

    paths = {}
    for line in io.open(PATHS, encoding="utf-8"):
        if not line.strip():
            continue
        d = json.loads(line)
        p = d.get("peak_m")
        if isinstance(p, list) and p:
            paths[d["ca"]] = d

    calls = [json.loads(l) for l in gzip.open(CALLS, "rt", encoding="utf-8") if l.strip()]
    return cards, paths, calls


def main():
    cards, paths, calls = load()
    print("cards on %d CAs | priced paths on %d CAs | calls %d"
          % (len(cards), len(paths), len(calls)))

    pairs, skip = [], collections.Counter()
    for c in calls:
        ca, t = c["ca"], float(c["call_ts"])
        pa = paths.get(ca)
        if not pa:
            skip["no fetched price path"] += 1
            continue
        cs = cards.get(ca)
        if not cs:
            skip["no cards"] += 1
            continue
        at = [x for x in cs if abs(x["ts"] - t) <= WIN and sane(x.get("ath"))]
        later = [x for x in cs if x["ts"] > t + WIN and sane(x.get("ath"))]
        if not at or not later:
            skip["no card pair straddling the call"] += 1
            continue
        a0 = max(x["ath"] for x in at)
        m0 = max(x["mcap"] for x in at)
        nxt = max(later, key=lambda x: x["ts"])
        hours = int((nxt["ts"] - t) / 3600.0)
        if hours < 1:
            skip["follow-up under an hour"] += 1
            continue
        series = pa["peak_m"]
        if hours >= len(series):
            # the card looks further ahead than the path reaches -- comparing them would pit a
            # longer window against a shorter one and call the difference an error
            skip["card horizon beyond the 60d path"] += 1
            continue
        pairs.append({
            "ca": ca, "chat": c.get("chat"), "hours": hours,
            "card": nxt["ath"] / a0,
            "path": series[hours],
            "at_high": a0 <= m0 * AT_HIGH,
            "disc": a0 / m0,
        })

    print("\n%-34s %6s" % ("pairing outcome", "n"))
    for k, v in skip.most_common():
        print("   %-32s %6d" % (k, v))
    print("   %-32s %6d" % ("COMPARABLE PAIRS", len(pairs)))
    if not pairs:
        print("\nNothing to compare yet -- the pull is still filling. Re-run as it grows.")
        return

    def report(name, sub):
        if len(sub) < 3:
            print("\n%s: n=%d, too few to characterise" % (name, len(sub)))
            return
        rel = [(p["card"] - p["path"]) / p["path"] for p in sub]
        rel.sort()
        agree = sum(1 for p in sub if abs(p["card"] - p["path"]) <= 0.10 * p["path"])
        card_hi = sum(1 for p in sub if p["card"] > p["path"] * 1.10)
        path_hi = sum(1 for p in sub if p["path"] > p["card"] * 1.10)
        print("\n%s  n=%d" % (name, len(sub)))
        print("   within 10%% of each other: %d (%.0f%%)" % (agree, 100.0 * agree / len(sub)))
        print("   card higher by >10%%:      %d (%.0f%%)" % (card_hi, 100.0 * card_hi / len(sub)))
        print("   path higher by >10%%:      %d (%.0f%%)" % (path_hi, 100.0 * path_hi / len(sub)))
        print("   (card-path)/path: p10 %+.2f  median %+.2f  p90 %+.2f"
              % (rel[int(.1 * len(rel))], statistics.median(rel), rel[int(.9 * len(rel))]))
        print("   median card %.2fx vs median path %.2fx"
              % (statistics.median([p["card"] for p in sub]),
                 statistics.median([p["path"] for p in sub])))

    hi = [p for p in pairs if p["at_high"]]
    lo = [p for p in pairs if not p["at_high"]]
    report("VALIDATION SET -- called at its all-time high, so the two measure the same thing", hi)
    report("EXPECTED-DISAGREEMENT SET -- called below its ATH, card ratio must understate", lo)
    if lo:
        d = sorted(p["disc"] for p in lo)
        print("   their ath_at_call/mcap_at_call: median %.2fx (how far below the high they were)"
              % statistics.median(d))
        und = sum(1 for p in lo if p["card"] < p["path"])
        print("   card < path, the predicted direction: %d of %d (%.0f%%)"
              % (und, len(lo), 100.0 * und / len(lo)))

    h = sorted(p["hours"] for p in pairs)
    print("\nhorizons compared: median %dh, p90 %dh" % (h[len(h) // 2], h[int(.9 * len(h))]))
    print("by chat:", dict(collections.Counter(p["chat"] for p in pairs).most_common()))


if __name__ == "__main__":
    main()
