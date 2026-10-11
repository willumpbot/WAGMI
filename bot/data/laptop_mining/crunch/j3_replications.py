"""J3 -- out-of-sample recomputation of the LIVE scan-flag definitions and the chief Brier.

WHY THIS JOB WAS BLOCKED UNTIL NOW. A replication written against a guessed definition produces
numbers that look like replications and are not, and it produces them hourly, forever, with
nobody checking. So this job was deliberately absent until the server shipped the real
definitions. It now recomputes, on days the flag tests never saw, the conditions in
`server_exports/scanner.py` (the FLAGS dict and the flag block in `scan_coin`/`run`), the
stop-exceedance outcome in `funding_stop.py` (|next-day move| > 1.65 x em), and the chief Brier
as described for `chief.py`.

IT APPENDS OBSERVATIONS AND NOTHING ELSE. No verdict, no pass/fail, no "confirmed", no "failed".
Every row is a measurement with its n and its uncertainty. A human reads this on READ_DATE, or
earlier only to check whether a metric's MDE has fallen below the in-sample effect it is
replicating -- both numbers are printed every run. Writing a verdict hourly is how alpha gets
spent silently, and the one thing a replication must never do is announce itself before it has
the power to have come out the other way.

WHAT IT REFUSES TO MEASURE, and why each refusal is a refusal rather than a zero:

  - `funding_hot` / `funding_cold`: SOURCE-MISSING. Both need a funding rate per coin on the
    evaluation day. `funding_hist` in the panel store is truncated -- every coin holds exactly
    999 rows (the API page cap) and for 176 of 178 coins those rows END IN NOV 2025;
    `history/*_funding.csv` (40 coins) all end 2026-10-08 19:00; `ctx` begins 2026-10-10 22:42.
    So no out-of-sample day has a funding cross-section. A 2-coin "top quintile" is not the live
    flag, and reporting 0 flagged coin-days would read as "the flag never fired".
  - `above_20d_high`: STRUCTURAL-ZERO. The live flag is `markPx > max(high, last 20 closed
    days)`, evaluated intraday. This job evaluates at the day boundary, where the only price it
    has is close(D-1) -- which is inside day D-1's own high by definition. The flag can therefore
    NEVER fire here. n=0 would be an artifact of the reconstruction, not an observation, so it is
    declared instead of counted. It becomes replicable once `ctx.mark` has accrued an intraday
    mark series, which j1 started archiving on 2026-10-10.
  - `volume_surge`: the live numerator is `ctx.dayNtlVlm`, a rolling 24h figure of which the
    laptop holds under one day. This job substitutes candle USD volume for the numerator AND the
    denominator, which is internally consistent but IS NOT the live definition; the metric is
    named `volume_surge_candlevol` so it can never be read as the live flag, and a companion
    SOURCE-MISSING row records what the live version is waiting on.
  - the matched `funding_hot` stop-exceedance difference (+2.64pp in FUNDING_STOP.md): blocked by
    the same missing funding. What IS computable without funding is the panel's unconditional
    exceedance rate, so that accrues instead, labelled as the different quantity it is.

TWO DIVERGENCES BETWEEN THE LIVE AND THE TESTED DEFINITION, found by reading both files rather
than either write-up. They are recorded here because when funding data arrives they decide
whether the replication is of the live flag or of the published claim, and those are not the same
replication:
  1. THRESHOLD SIDE. Live `scanner.py` flags `funding_h > cut`, strictly above an interpolated
     80th percentile, with a comment that `>=` flagged ~85% of coins because most HL coins sit
     exactly at the default rate. The tested `funding_stop.py` used `val >= f.quantile(0.80)`.
     Inclusive vs strict on a mass point is not a rounding difference.
  2. FUNDING QUANTITY. Live reads the INSTANTANEOUS hourly rate out of the asset context. The
     test's `load_funding` SUMS the 24 hourly rates into a daily figure. Cross-sectional ranks
     differ between those two whenever funding moves within a day.
  Likewise the expected move: live `scanner.py` calls `volforecast.forecast()` (trained
  coefficients from volatility_forecast.json, with the 0.8 haircut above 3.9), while
  `funding_stop.py` hardcodes HAR betas (0, .35, .35, .30) with smearing 1.0 and no haircut. This
  job uses the LIVE em for the flag conditions and the TESTED em for the exceedance outcome, so
  each number is computed with the em that defines it.

ALSO MISSING, and it is the central caveat of the chief half: `server_exports/chief.py` IS NOT
PRESENT. The brief names it as the source of the Brier definition; the directory does not contain
it, and the only copy on this machine, `bot/tools/hivemind/chief.py`, contains no Brier code at
all (no match for "brier" or "p_up"). So the Brier here follows the definition as DESCRIBED --
p_up_24h against (close 24h later > price at call), mean (p-o)^2, baseline 0.25 -- which is
exactly the "re-derived from the write-up instead of the code" failure mode this project has
already paid for once. The implementation is therefore kept boringly literal, its two free
choices are written into the note of every row it produces, and `chief.py` is logged as
SOURCE-MISSING every run so the gap stays visible instead of aging into an assumption.

ONE DESIGN DECISION WAS MADE BY THIS JOB'S OWN PLACEBO, before any result was recorded. The
first version took each day's mean return over the flagged coins as the block statistic. Run on
in-sample days in a scratch harness, within-day label permutation rejected the null at 0.17-0.27
against a nominal 0.05 for every flag that fires on many coins a day -- because a flagged day's
mean return contains that whole day's market move, so the test was detecting market drift and
calling it the flag. The block statistic is therefore the WITHIN-DAY DIFFERENCE, flagged minus
unflagged on the same day, which is how `funding_stop.py` did it too (matched within-cell). The
flagged level is still recorded as description, labelled as such, and the placebo rate is
appended beside every figure so the calibration can be re-checked rather than trusted.

HOUSE RULES OBSERVED: no Claude tokens (plain python, stdlib + numpy); idempotent (every row is
INSERT OR REPLACE on the (asof, metric) primary key, so an hour's re-run or a double-scheduled
run rewrites identical values); a missing source is SOURCE-MISSING, never 0; every pooled figure
is written next to its EQUAL-WEIGHTED day-block mean, because clustering the variance by day
while averaging by event already produced one published false null in this project; and the
cluster-size/cluster-mean correlation is logged beside both, because when it is large the pooled
figure is the wrong number rather than merely a noisy one.
"""
import calendar
import io
import json
import math
import os
import sys
import time

import numpy as np

from common import MINING, REPO, db, init_schema, log, record_run

HERE = os.path.dirname(os.path.abspath(__file__))
EXP = os.path.join(MINING, "server_exports")
OUT = os.path.join(HERE, "REPLICATIONS.md")

# The flag tests (SCANNER_FLAGS_V2, SIZE_FLAGS, FUNDING_STOP) were all built on daily candle
# history through 2026-10-08, so the first OUTCOME day none of them could have seen is 10-09.
# Days on or before the boundary are counted and withheld, never silently dropped.
OOS_START_DAY = "2026-10-09"

# Backstop date for a human read. The REAL gate is the MDE printed each run falling below the
# in-sample effect being replicated; this date exists so that gate has a calendar deadline
# instead of waiting on someone to remember. ~60 accrued day-blocks at one block per day.
READ_DATE = "2026-12-10"

TOP_N = 60               # scanner.py scans the top 60 perps by 24h volume
MIN_DAYS = 60            # scanner.py: `if not raw or len(raw) < 60: return None`
BARS_PER_DAY = 24        # a UTC day is only "closed" here with all 24 hourly bars present
LOOKBACK_CONTIG = 23     # rv22 and the 20d range need an unbroken run behind the evaluation day
K_STOP = 1.65            # funding_stop.py K_VERDICT -- the established stop distance
BRIER_BASELINE = 0.25    # a coin flip, the stated reference for p_up_24h
MIN_XSEC = 20            # fewer coins than this is not a cross-section, it is a handful
Z80 = 2.802              # two-sided alpha=0.05 at 80% power
HIVEMIND = os.path.join(REPO, "bot", "tools", "hivemind")

# funding_stop.py: HAR betas and smearing hardcoded there, "as used by size_flags.py".
# NOT volforecast's trained coefficients -- see the divergence note in the docstring.
TESTED_HAR_B = (0.0, 0.35, 0.35, 0.30)
TESTED_HAR_S = 1.0
EPS = 1e-9

# Flags computed purely from closed daily candles: an EXACT recomputation of the live condition.
FLAGS_EXACT = ("squeeze", "vol_expanding")
# Flags whose live condition compares an INTRADAY markPx; here the day-boundary close stands in.
FLAGS_CLOSE_PROXY = ("ma50_pullback", "on_20d_low")
# Declared non-observations. See the docstring -- these cannot fire in a boundary reconstruction.
FLAGS_STRUCTURAL_ZERO = ("above_20d_high",)
# Live input absent from the laptop entirely.
FLAGS_SOURCE_MISSING = ("funding_hot", "funding_cold")
# Live input substituted; named apart so it cannot be mistaken for the live flag.
FLAGS_PROXY_INPUT = ("volume_surge_candlevol",)

ALL_REPLICATED = FLAGS_EXACT + FLAGS_CLOSE_PROXY + FLAGS_PROXY_INPUT

DEVIATION = {
    "squeeze": "EXACT: closed daily candles + the live em only, no price input",
    "vol_expanding": "EXACT: rv5/rv22 from closed daily closes only",
    "ma50_pullback": "DEVIATION: px = close(D-1) stands in for the live intraday markPx",
    "on_20d_low": "DEVIATION: px = close(D-1) stands in for the live intraday markPx, and the "
                  "`lo20 <= px` half of the live condition is vacuous at the close",
    "volume_surge_candlevol": "PROXY: candle USD volume for both terms; live uses ctx.dayNtlVlm",
}


def _ema(v, n):
    """Transcribed from scanner.py, seeding on the first value rather than on a mean."""
    k, e, out = 2 / (n + 1), None, []
    for x in v:
        e = x if e is None else x * k + e * (1 - k)
        out.append(e)
    return out


def _sd(xs):
    xs = [x for x in xs if x == x]
    if len(xs) < 2:
        return float("nan")
    m = sum(xs) / len(xs)
    return (sum((v - m) ** 2 for v in xs) / (len(xs) - 1)) ** 0.5


def day_str(dnum):
    return time.strftime("%Y-%m-%d", time.gmtime(dnum * 86400))


def day_num(s):
    """UTC day index. timegm, not mktime -- the panel is keyed on UTC and the laptop is not."""
    y, m, d = (int(x) for x in s.split("-"))
    return calendar.timegm((y, m, d, 0, 0, 0)) // 86400


def load_volforecast():
    """The LIVE expected move: scanner.py calls volforecast.forecast(closes) with no stage-2
    inputs, so this must call it the same way -- stage 1 plus the 0.8 haircut above 3.9.

    _coef() re-reads volatility_forecast.json on EVERY call, which is fine for a 60-coin scan and
    not fine for 176 coins x a growing OOS window, so the coefficients are read once and memoised.
    The file is static training output; this changes no number, only the file-handle count.
    """
    if HIVEMIND not in sys.path:
        sys.path.insert(0, HIVEMIND)
    try:
        import volforecast
    except Exception as e:
        return None, "SOURCE-MISSING: volforecast.py not importable (%s)" % str(e)[:80]
    try:
        coef = volforecast._coef()
    except Exception as e:
        return None, "SOURCE-MISSING: volatility_forecast.json unreadable (%s)" % str(e)[:80]
    volforecast._coef = lambda _c=coef: _c
    return volforecast, ("live em = volforecast.forecast(closes), stage 1 + the 0.8 haircut "
                         "at >= 3.9, exactly as scanner.py calls it")


def tested_em(rets):
    """funding_stop.py's expected move, used ONLY for the exceedance outcome that it defines."""
    rv1, rv5, rv22 = abs(rets[-1]), _sd(rets[-5:]), _sd(rets[-22:])
    if not (rv22 > 0 and rv5 > 0):
        return None
    b = TESTED_HAR_B
    z = (b[0] + b[1] * math.log(rv1 + EPS) + b[2] * math.log(rv5 + EPS)
         + b[3] * math.log(rv22 + EPS))
    em = math.exp(z) * TESTED_HAR_S
    return em if em > 0 else None


def load_daily_panel(conn):
    """Closed UTC days per coin, folded up from the 1h panel.

    A day counts as closed only with all 24 hourly bars. Partial days are counted and reported,
    because a half-day looks exactly like a quiet day once it has been aggregated.
    """
    panel, partial = {}, 0
    cur = conn.execute("SELECT coin,t,h,l,c,v FROM candles_1h ORDER BY coin,t")
    for coin, t, h, l, c, v in cur:
        if c is None:
            continue
        d = t // 86_400_000
        days = panel.setdefault(coin, {})
        row = days.get(d)
        if row is None:
            days[d] = row = {"n": 0, "h": h, "l": l, "c": c, "vusd": 0.0}
        row["n"] += 1
        if h is not None and (row["h"] is None or h > row["h"]):
            row["h"] = h
        if l is not None and (row["l"] is None or l < row["l"]):
            row["l"] = l
        row["c"] = c                      # ordered by t, so the last bar wins
        row["vusd"] += (v or 0.0) * c
    out = {}
    for coin, days in panel.items():
        partial += sum(1 for r in days.values() if r["n"] != BARS_PER_DAY)
        ks = sorted(k for k, r in days.items()
                    if r["n"] == BARS_PER_DAY and None not in (r["h"], r["l"], r["c"]))
        if len(ks) < MIN_DAYS + 1:
            continue
        out[coin] = {"d": ks,
                     "h": [days[k]["h"] for k in ks],
                     "l": [days[k]["l"] for k in ks],
                     "c": [days[k]["c"] for k in ks],
                     "vusd": [days[k]["vusd"] for k in ks]}
    return out, partial


def funding_coverage(conn, dnums):
    """Can a funding CROSS-SECTION be formed on each evaluation day?

    Returns {daynum: (n_coins, source)}. The live flag needs the instantaneous rate per coin at
    the moment of the scan, so this looks for the latest rate at or before the day boundary.
    Reported per day so that the moment ctx has accrued enough coins, funding_hot begins
    replicating with no code change -- and until then every day states why not.
    """
    cov = {}
    for dn in dnums:
        ms = dn * 86_400_000
        n_ctx = conn.execute("SELECT COUNT(DISTINCT coin) FROM ctx WHERE t <= ? AND t > ?",
                             (ms, ms - 6 * 3_600_000)).fetchone()[0]
        n_fh = conn.execute("SELECT COUNT(DISTINCT coin) FROM funding_hist "
                            "WHERE t <= ? AND t > ?",
                            (ms, ms - 6 * 3_600_000)).fetchone()[0]
        if n_ctx >= MIN_XSEC:
            cov[dn] = (n_ctx, "ctx")
        elif n_fh >= MIN_XSEC:
            cov[dn] = (n_fh, "funding_hist")
        else:
            cov[dn] = (max(n_ctx, n_fh), "SOURCE-MISSING")
    return cov


def observe_day(panel, dn, vf):
    """Recompute every replicable flag for evaluation day `dn`, out of sample.

    Inputs are closed days STRICTLY BEFORE dn; the outcome is day dn's own close-to-close return.
    Nothing from day dn enters a flag condition, which is the only thing that makes this out of
    sample rather than a very confident description of the past.
    """
    cands, skipped = [], {"short_history": 0, "gap": 0, "no_em": 0}
    for coin, h in panel.items():
        ks = h["d"]
        try:
            i = ks.index(dn)
        except ValueError:
            continue
        if i < MIN_DAYS:
            skipped["short_history"] += 1
            continue
        if ks[i - 1] != dn - 1:
            skipped["gap"] += 1            # no contiguous D-1, so no honest 1-day return
            continue
        if ks[i - LOOKBACK_CONTIG] != dn - LOOKBACK_CONTIG:
            skipped["gap"] += 1            # broken 23-day run behind D
            continue
        closes, highs = h["c"][:i], h["h"][:i]
        lows, vusd = h["l"][:i], h["vusd"][:i]
        fc = vf.forecast(closes) or {}
        em = fc.get("next_day_move_pct")
        if not em:
            skipped["no_em"] += 1
            continue
        px = closes[-1]                    # DEVIATION: live uses the intraday markPx
        e50 = _ema(closes, 50)
        hi20, lo20 = max(highs[-20:]), min(lows[-20:])
        d50 = (px / e50[-1] - 1) * 100
        range_moves = (hi20 / lo20 - 1) * 100 / em if lo20 > 0 else None
        flags = []
        if 0 <= d50 <= 0.5 * em:
            flags.append("ma50_pullback")
        if lo20 <= px and (px / lo20 - 1) * 100 <= 0.5 * em:
            flags.append("on_20d_low")
        if range_moves is not None and range_moves < 4:
            flags.append("squeeze")
        if fc.get("rv5") and fc.get("rv22") and fc["rv5"] > 1.4 * fc["rv22"]:
            flags.append("vol_expanding")
        avg20 = sum(vusd[-20:]) / len(vusd[-20:]) if vusd[-20:] else 0
        vol_ratio = (vusd[-1] / avg20) if avg20 else None
        if vol_ratio and vol_ratio > 2.5:
            flags.append("volume_surge_candlevol")
        rets = [(closes[j] / closes[j - 1] - 1) * 100 for j in range(1, len(closes))]
        em_t = tested_em(rets) if len(rets) >= 22 else None
        ret = (h["c"][i] / px - 1) * 100
        cands.append({"coin": coin, "flags": flags, "ret": ret, "em": em, "em_tested": em_t,
                      "vusd": vusd[-1],
                      "exceed": (abs(ret) > K_STOP * em_t) if em_t else None})
    # scanner.py scans only the TOP_N perps by 24h volume, so the replication must too, or it is
    # measuring a flag on a universe the flag never ran on.
    cands.sort(key=lambda r: -r["vusd"])
    return cands[:TOP_N], skipped


# Two-sided 0.975 and one-sided 0.80 t quantiles by df, so the detection floor is honest in the
# small-block regime this job will live in for its first two months -- which is exactly when
# somebody is most likely to peek. The normal approximation (2.802) understates the floor badly
# there: at 6 blocks the true multiplier is 3.49, so a normal-based MDE would advertise 25% more
# power than exists. Both tables converge on the normal, which is used beyond df 30.
_T975 = (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179,
         2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064,
         2.060, 2.056, 2.052, 2.048, 2.045, 2.042)
_T80 = (1.376, 1.061, 0.978, 0.941, 0.920, 0.906, 0.896, 0.889, 0.883, 0.879, 0.876, 0.873,
        0.870, 0.868, 0.866, 0.865, 0.863, 0.862, 0.861, 0.860, 0.859, 0.858, 0.858, 0.857,
        0.856, 0.856, 0.855, 0.855, 0.854, 0.854)


def tcrit(nb):
    """(two-sided 0.05 critical value, 80%-power multiplier) for nb day-blocks."""
    df = nb - 1
    if df < 1:
        return float("nan"), float("nan")
    if df > 30:
        return 1.960, Z80
    return _T975[df - 1], _T975[df - 1] + _T80[df - 1]


def block_stats(blocks):
    """blocks: list of (n_i, mean_i), one per day. Returns the pooled figure, the EQUAL-WEIGHTED
    block figure, and the diagnostics the house standard requires beside them.

    The pooled figure weights by events, the block figure weights by day. When cluster size and
    cluster mean are correlated these are DIFFERENT NUMBERS and the pooled one is wrong, not
    merely noisy -- which is why size_mean_corr is reported next to them, not in a footnote.
    """
    blocks = [(n, m) for n, m in blocks if n > 0 and m == m]
    if not blocks:
        return None
    means = np.array([m for _, m in blocks], float)
    ns = np.array([n for n, _ in blocks], float)
    nb = len(blocks)
    sd = float(means.std(ddof=1)) if nb > 2 else float("nan")
    se = sd / math.sqrt(nb) if sd == sd else float("nan")
    corr = float("nan")
    if nb > 2 and ns.std() > 0 and means.std() > 0:
        corr = float(np.corrcoef(ns, means)[0, 1])
    t95, mult = tcrit(nb)
    return {"n_events": int(ns.sum()), "n_blocks": nb,
            "pooled": float((ns * means).sum() / ns.sum()),
            "block": float(means.mean()), "se": se, "tcrit": t95,
            "mde": mult * se if se == se else float("nan"),
            "size_mean_corr": corr}


def day_diff(rows, flag):
    """The within-day statistic: mean return of the flagged coins MINUS mean return of the
    unflagged coins scanned the same day. Returns (k, diff) or None.

    WHY THE DIFFERENCE AND NOT THE LEVEL. The level -- the mean return of the flagged coins on a
    day -- contains that whole day's market move, because the coins all move together. Averaged
    across days it therefore estimates the market's drift plus whatever the flag does, and a
    t-test on it rejects whenever the market drifted. THIS JOB'S OWN PLACEBO CAUGHT THAT: tested
    on the level, within-day label permutation rejected at 0.17-0.27 against a nominal 0.05 for
    the flags that fire on many coins a day. Differencing against the same day's unflagged coins
    cancels the market move, which is also how `funding_stop.py` did it (matched within-cell).
    The level is still reported, as description, but the difference is the number to act on.
    """
    f = [r["ret"] for r in rows if flag in r["flags"]]
    u = [r["ret"] for r in rows if flag not in r["flags"]]
    if not f or not u:
        return None
    return len(f), float(np.mean(f)) - float(np.mean(u))


def placebo_within_day(day_rows, flag, reps=300, seed=20261011):
    """Permute the flag label WITHIN each day, keeping that day's flagged count fixed, recompute
    the within-day difference, and ask how often the day-block t exceeds 1.96 under the null.

    THIS PLACEBO CAN FAIL, AND IT HAS. Labels are reshuffled against real, unpinned returns -- no
    sample mean is forced to zero and then tested for being zero -- so a mis-specified block
    statistic shows up as a rejection rate well above 0.05. That is exactly how the level-based
    version of this job was caught and replaced (see day_diff). A rate near 0.05 is the only
    thing that licenses reading the t beside it.
    """
    rng = np.random.default_rng(seed)
    days = [(dn, rows) for dn, rows in day_rows
            if 0 < sum(1 for r in rows if flag in r["flags"]) < len(rows)]
    if len(days) < 3:
        return None, ("SOURCE-INSUFFICIENT: %d usable day-blocks, needs 3 before a rejection "
                      "rate means anything" % len(days))
    hits = 0
    for _ in range(reps):
        bl = []
        for _dn, rows in days:
            k = sum(1 for r in rows if flag in r["flags"])
            rets = np.array([r["ret"] for r in rows], float)
            pick = rng.choice(len(rets), size=k, replace=False)
            mask = np.zeros(len(rets), bool)
            mask[pick] = True
            bl.append((k, float(rets[mask].mean() - rets[~mask].mean())))
        s = block_stats(bl)
        # the SAME critical value the MDE assumes, so the placebo tests the test that is
        # actually being reported rather than a more liberal cousin of it
        if (s and s["se"] == s["se"] and s["se"] > 0
                and abs(s["block"] / s["se"]) > s["tcrit"]):
            hits += 1
    return hits / float(reps), ("%d reps, within-day label permutation of the DIFFERENCE, "
                                "nominal 0.05, %d blocks" % (reps, len(days)))


def chief_brier(conn):
    """Brier for p_up_24h as DESCRIBED (chief.py is absent -- see the module docstring).

    Two free choices, both written into every row's note because neither can be checked against
    the code that is supposed to define them:
      - the call-time price is the record's own `price` field, not an interpolated candle close;
      - "close 1 day later" is the last 1h close at or before ts+24h, within a 6h window.
    """
    out = []
    p = os.path.join(EXP, "chief_calls.jsonl")
    if not os.path.exists(p):
        return [("chief.brier_24h.n_resolved", None, None,
                 "SOURCE-MISSING: chief_calls.jsonl absent")]
    rows = []
    try:
        for line in io.open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("p_up_24h") is not None:
                rows.append(r)
    except OSError as e:
        return [("chief.brier_24h.n_resolved", None, None,
                 "SOURCE-UNREADABLE: %s" % str(e)[:80])]
    if not rows:
        return [("chief.brier_24h.n_calls_with_p", 0, None,
                 "chief_calls.jsonl parsed but NO row carries p_up_24h. That is a schema state, "
                 "not a Brier of zero, and not evidence about the forecaster")]

    raw = [float(r["p_up_24h"]) for r in rows]
    scale = 100.0 if max(raw) > 1.0 else 1.0
    ps = [v / scale for v in raw]
    out.append(("chief.brier_24h.n_calls_with_p", len(rows), None,
                "p_up_24h arrives as %s (observed range %g..%g) and is divided by %g to a "
                "probability. The scale is DETECTED, not assumed: read at face value a percent "
                "would make every Brier ~2300."
                % ("integer percent" if scale == 100 else "a unit probability",
                   min(raw), max(raw), scale)))
    out.append(("chief.brier_24h.baseline", len(rows), BRIER_BASELINE,
                "the stated coin-flip reference, recorded so this log is self-contained"))

    # STRUCTURAL CEILING. (p-o)^2 = 0.25 + d^2 + s*d with d = p-0.5 and s = +-1, so the best
    # attainable Brier is 0.25 - (mean|d| - mean d^2). This is the most important number in the
    # chief half: it is how far from a coin flip these probabilities could POSSIBLY land, and it
    # is computable from the forecasts alone, before a single outcome exists. If it is tiny, a
    # Brier near 0.25 is a property of the forecast's spread, not evidence about skill.
    d = np.array([x - 0.5 for x in ps], float)
    attainable = float(np.abs(d).mean() - (d ** 2).mean())
    out.append(("chief.brier_24h.attainable_skill", len(rows), round(attainable, 5),
                "CEILING: the largest possible improvement on 0.25 given the observed spread of "
                "p (max |p-0.5| = %.3f). Best attainable Brier is %.5f; a perfectly ordered "
                "forecaster could not beat it. Read any Brier against this, not against 0.25 "
                "alone." % (float(np.abs(d).max()), BRIER_BASELINE - attainable)))

    newest = conn.execute("SELECT MAX(t) FROM candles_1h").fetchone()[0] or 0
    matured = resolved = 0
    per_day = {}
    for r, pv in zip(rows, ps):
        ts = float(r["ts"])
        tgt = int((ts + 86_400) * 1000)
        if tgt > newest:
            continue
        matured += 1
        q = conn.execute("SELECT c FROM candles_1h WHERE coin=? AND t<=? AND t>? "
                         "ORDER BY t DESC LIMIT 1",
                         (r.get("symbol"), tgt, tgt - 6 * 3_600_000)).fetchone()
        base = r.get("price")
        if not q or not base:
            continue
        resolved += 1
        o = 1.0 if q[0] > float(base) else 0.0
        per_day.setdefault(time.strftime("%Y-%m-%d", time.gmtime(ts)), []).append((pv - o) ** 2)

    if matured and not resolved:
        out.append(("chief.brier_24h.n_resolved", 0, None,
                    "SOURCE-MISSING: %d calls have matured past +24h but no candle inside the 6h "
                    "window, or no call price, was available to resolve them. Not a Brier of "
                    "zero -- a loss of visibility." % matured))
        return out
    if not matured:
        nxt = min(float(r["ts"]) for r in rows) + 86_400
        out.append(("chief.brier_24h.n_resolved", 0, None,
                    "GENUINE ZERO of resolvable pairs, not SOURCE-MISSING: both inputs are "
                    "readable and all %d p_up_24h calls were made within the last 24h, so none "
                    "has matured. Earliest resolves %sZ. Separately, 0 of the calls carrying the "
                    "server's own ret_1d also carry p_up_24h, so the server cannot resolve them "
                    "either -- consistent with chief_scorecard.json reporting brier_24h n=0."
                    % (len(rows), time.strftime("%Y-%m-%d %H:%M", time.gmtime(nxt)))))
        return out

    blocks = [(len(v), float(np.mean(v))) for v in per_day.values()]
    s = block_stats(blocks)
    base = ("p from the record /%g; outcome = the 1h close at/before ts+24h > the call's own "
            "`price`; chief.py ABSENT so neither choice is verified against code" % scale)
    out.append(("chief.brier_24h.pooled", s["n_events"], round(s["pooled"], 5),
                "event-weighted. " + base))
    out.append(("chief.brier_24h.blockmean", s["n_blocks"], round(s["block"], 5),
                "EQUAL-WEIGHTED by call day -- the figure to act on, since calls arrive in "
                "batches of ~6 coins that share one market. " + base))
    out.append(("chief.brier_24h.vs_baseline_blockmean", s["n_blocks"],
                round(s["block"] - BRIER_BASELINE, 5),
                "negative = better than a coin flip. Compare the magnitude against "
                "attainable_skill before reading anything into the sign."))
    out.append(("chief.brier_24h.mde", s["n_blocks"],
                None if s["mde"] != s["mde"] else round(s["mde"], 5),
                "DETECTION FLOOR: 80%% power, two-sided 0.05, on %d call-day blocks%s"
                % (s["n_blocks"], "" if s["mde"] == s["mde"] else
                   " -- UNDEFINED, a between-block sd needs 3 blocks")))
    out.append(("chief.brier_24h.size_mean_corr", s["n_blocks"],
                None if s["size_mean_corr"] != s["size_mean_corr"] else
                round(s["size_mean_corr"], 4),
                "corr(block n, block mean). Large = the pooled figure is wrong, not just noisy"))
    return out


def build(conn):
    """Collect every observation. Returns (rows, meta) where each row is
    (asof_or_None, metric, n, value, note); asof None means "stamp with the run date".

    Reads only. main() does the writing, so a scratch harness can move OOS_START_DAY and exercise
    the summary and placebo paths without touching the table.
    """
    rows = []

    def add(metric, n, val, note, asof=None):
        rows.append((asof, metric, n, val, note))

    vf, vf_note = load_volforecast()
    oos0 = day_num(OOS_START_DAY)

    panel, partial = load_daily_panel(conn)
    if not panel:
        add("meta.panel", None, None,
            "SOURCE-MISSING: candles_1h holds no coin with %d closed 24-bar days" % MIN_DAYS)
        return rows, {"oos_days": 0}
    all_days = sorted({d for h in panel.values() for d in h["d"]})
    day_set = set(all_days)
    evald = [d for d in all_days if d >= oos0 and (d - 1) in day_set]
    withheld = [d for d in all_days if d < oos0]

    add("meta.oos_boundary", len(withheld), None,
        "OOS outcome days start %s. %d earlier closed days are WITHHELD as in-sample for the "
        "flag tests (all built on history through 2026-10-08) -- counted here so the small n "
        "below reads as a deliberate exclusion, not as missing data."
        % (OOS_START_DAY, len(withheld)))
    add("meta.panel", len(panel), float(partial),
        "%d coins with >=%d closed 24-bar days; %d partial days excluded; universe capped at the "
        "top %d by candle USD volume (live caps at the top %d by ctx.dayNtlVlm -- a stated "
        "deviation)" % (len(panel), MIN_DAYS, partial, TOP_N, TOP_N))
    add("meta.em", None, None, vf_note)
    if vf is None:
        return rows, {"oos_days": 0}

    if not evald:
        add("meta.oos_days", 0, None,
            "GENUINE ZERO of evaluable OOS days: the panel's newest closed day is %s, before the "
            "OOS boundary %s" % (day_str(all_days[-1]), OOS_START_DAY))
        return rows, {"oos_days": 0}

    fcov = funding_coverage(conn, evald)
    day_rows, skip_tot, uni = [], {}, []
    for dn in evald:
        cands, skipped = observe_day(panel, dn, vf)
        for k, v in skipped.items():
            skip_tot[k] = skip_tot.get(k, 0) + v
        uni.append(len(cands))
        day_rows.append((dn, cands))

    add("meta.oos_days", len(evald), None,
        "evaluated %s .. %s; scanned universe %d..%d coins/day; coin-days skipped: %s"
        % (day_str(evald[0]), day_str(evald[-1]), min(uni), max(uni),
           ", ".join("%s=%d" % kv for kv in sorted(skip_tot.items())) or "none"))

    # ---- per-flag observations -------------------------------------------------------------
    for flag in ALL_REPLICATED:
        blocks_lvl, blocks_dif = [], []
        for dn, cands in day_rows:
            sel = [r["ret"] for r in cands if flag in r["flags"]]
            if not sel:
                add("scan.%s.day.diff_ret_pct" % flag, 0, None,
                    "flag fired on none of the %d coins scanned on %s. A real non-firing: every "
                    "input was present." % (len(cands), day_str(dn)), asof=day_str(dn))
                continue
            m = float(np.mean(sel))
            blocks_lvl.append((len(sel), m))
            d = day_diff(cands, flag)
            if d is None:
                add("scan.%s.day.diff_ret_pct" % flag, len(sel), None,
                    "flag fired on ALL %d coins scanned on %s, so there is no same-day unflagged "
                    "comparison group and no difference to compute -- not a difference of zero."
                    % (len(cands), day_str(dn)), asof=day_str(dn))
                continue
            add("scan.%s.day.diff_ret_pct" % flag, d[0], round(d[1], 4),
                "within-day: mean next-day %% of the %d flagged coins minus the %d unflagged "
                "coins scanned the same day (flagged level was %+.4f%%). %s"
                % (d[0], len(cands) - d[0], m, DEVIATION[flag]), asof=day_str(dn))
            blocks_dif.append(d)

        sl, s = block_stats(blocks_lvl), block_stats(blocks_dif)
        if not s:
            add("scan.%s.cum.blockmean_diff_pct" % flag, 0, None,
                "no day-block in the OOS window produced a flagged-vs-unflagged comparison, so "
                "there is nothing to average. %s" % DEVIATION[flag])
            continue
        if sl:
            add("scan.%s.cum.level_pooled_pct" % flag, sl["n_events"], round(sl["pooled"], 4),
                "DESCRIPTION ONLY, not the number to act on: event-weighted mean return of the "
                "flagged coins, which contains the whole market move of every day it spans. "
                "Equal-weighted by day it is %+.4f%% -- the gap between those two is the "
                "clustering trap, printed here rather than hidden."
                % sl["block"])
        add("scan.%s.cum.pooled_diff_pct" % flag, s["n_events"], round(s["pooled"], 4),
            "event-weighted (by flagged coin-days) within-day difference over %d coin-days. %s"
            % (s["n_events"], DEVIATION[flag]))
        add("scan.%s.cum.blockmean_diff_pct" % flag, s["n_blocks"], round(s["block"], 4),
            "EQUAL-WEIGHTED over %d day-blocks -- THE FIGURE TO ACT ON, printed beside the "
            "pooled one above. %s" % (s["n_blocks"], DEVIATION[flag]))
        add("scan.%s.cum.mde_diff_pct" % flag, s["n_blocks"],
            None if s["mde"] != s["mde"] else round(s["mde"], 4),
            "DETECTION FLOOR, STATED BEFORE ANY READING: 80%% power, two-sided 0.05, clustered on "
            "%d day-blocks%s" % (s["n_blocks"], "" if s["mde"] == s["mde"] else
                                 " -- UNDEFINED until 3 blocks exist. Until then no reading of "
                                 "the means above is distinguishable from noise, either way."))
        add("scan.%s.cum.size_mean_corr" % flag, s["n_blocks"],
            None if s["size_mean_corr"] != s["size_mean_corr"] else round(s["size_mean_corr"], 4),
            "corr(day n, day difference) over %d blocks%s" % (
                s["n_blocks"],
                ". If this is large, the pooled figure is the WRONG number rather than merely "
                "the imprecise one" if s["size_mean_corr"] == s["size_mean_corr"] else
                " -- UNDEFINED: every block has the same n, so pooled and block mean coincide "
                "by construction"))
        pl, pnote = placebo_within_day(day_rows, flag)
        add("scan.%s.cum.placebo_reject_rate" % flag, s["n_blocks"],
            None if pl is None else round(pl, 4),
            "%s. This is the test's REALIZED SIZE, and it is what licenses reading the figures "
            "above. The placebo CAN fail and has: run on the flagged LEVEL it rejected at "
            "0.17-0.27, which is what forced the switch to the within-day difference. HOW TO "
            "READ IT: at 0.05 the MDE above is as advertised; above 0.05 the MDE is optimistic "
            "by roughly the ratio (a realized 0.10 means treat the floor as about %s), and a "
            "rate far above indicts the figures rather than merely widening them."
            % (pnote, "undefined until the MDE exists" if s["mde"] != s["mde"]
               else "%.2f" % (s["mde"] * 1.4)))

    # ---- declared non-observations ---------------------------------------------------------
    for flag in FLAGS_STRUCTURAL_ZERO:
        add("scan.%s.status" % flag, None, None,
            "STRUCTURAL-ZERO, NOT an observation: the live condition is markPx > max(high) over a "
            "window that INCLUDES the evaluation day's predecessor, and this job's only price is "
            "that predecessor's close, which cannot exceed its own high. The flag can never fire "
            "here, so no n is reported -- an n of 0 would be an artifact of the reconstruction. "
            "Becomes replicable once ctx.mark has an intraday series (archived since 2026-10-10).")
    cov_txt = "; ".join("%s: %d coins via %s" % (day_str(d), fcov[d][0], fcov[d][1])
                        for d in evald[:5])
    for flag in FLAGS_SOURCE_MISSING:
        add("scan.%s.status" % flag, None, None,
            "SOURCE-MISSING: needs a funding cross-section of >=%d coins on the evaluation day. "
            "funding_hist holds 999 rows/coin (the API page cap) ending Nov 2025 for 176 of 178 "
            "coins; history/*_funding.csv (40 coins) all end 2026-10-08 19:00; ctx begins "
            "2026-10-10 22:42. Coverage actually found -- %s" % (MIN_XSEC, cov_txt))
    add("scan.volume_surge.status", None, None,
        "SOURCE-MISSING for the LIVE definition: its numerator is ctx.dayNtlVlm, a rolling 24h "
        "figure of which the laptop holds under one day. What accrues instead is "
        "`volume_surge_candlevol`, a candle-volume proxy, named apart on purpose so the two can "
        "never be read as the same flag.")

    # ---- stop exceedance --------------------------------------------------------------------
    eblocks = []
    for dn, cands in day_rows:
        ex = [1.0 if r["exceed"] else 0.0 for r in cands if r["exceed"] is not None]
        if ex:
            eblocks.append((len(ex), float(np.mean(ex))))
    s = block_stats(eblocks)
    if not s:
        add("stop.panel_exceedance_rate.blockmean", 0, None,
            "SOURCE-MISSING: no coin-day in the OOS window had a computable tested em")
    else:
        shared = ("|next-day close-to-close move| > %.2f x em, em from funding_stop.py's "
                  "hardcoded HAR, NOT the live volforecast em. ALL scanned coins: the in-sample "
                  "21.72%% reference was the UNFLAGGED rate within date x em-quintile cells on 17 "
                  "clean perps, a different population, so this is a companion figure and not "
                  "that number." % K_STOP)
        add("stop.panel_exceedance_rate.pooled", s["n_events"], round(s["pooled"], 5),
            "event-weighted. " + shared)
        add("stop.panel_exceedance_rate.blockmean", s["n_blocks"], round(s["block"], 5),
            "EQUAL-WEIGHTED by day -- the figure to act on. " + shared)
        add("stop.panel_exceedance_rate.mde", s["n_blocks"],
            None if s["mde"] != s["mde"] else round(s["mde"], 5),
            "DETECTION FLOOR on the day-clustered rate, 80%% power, two-sided 0.05%s"
            % ("" if s["mde"] == s["mde"] else " -- UNDEFINED, needs 3 day-blocks"))
        add("stop.panel_exceedance_rate.size_mean_corr", s["n_blocks"],
            None if s["size_mean_corr"] != s["size_mean_corr"] else round(s["size_mean_corr"], 4),
            "corr(day n, day rate) over %d blocks%s" % (
                s["n_blocks"],
                "" if s["size_mean_corr"] == s["size_mean_corr"] else
                " -- UNDEFINED, and benignly so: the scanned universe is a fixed top-%d every "
                "day, so every block has identical n and the pooled and equal-weighted figures "
                "above coincide by construction rather than by luck" % TOP_N))
    add("stop.funding_hot_matched_diff_pp.status", None, None,
        "SOURCE-MISSING: the +2.64pp matched difference needs funding_hot, which needs the "
        "funding cross-section recorded above. Nothing is appended for it, and its absence is "
        "not a difference of zero.")
    add("stop.definition_divergence", None, None,
        "RECORDED FOR WHEN FUNDING ARRIVES: live scanner.py flags funding > p80 (STRICT, "
        "interpolated) on the INSTANTANEOUS hourly rate across the top 60 by volume; tested "
        "funding_stop.py used >= pandas quantile(0.80) on the DAY-SUMMED rate across 17 clean "
        "perps. Inclusive-vs-strict on a mass point, and instantaneous-vs-daily-sum, are "
        "different flags. Replicating the live flag and replicating the published claim are two "
        "different jobs, and this job will have to be told which one is wanted.")

    # ---- chief ------------------------------------------------------------------------------
    add("chief.definition_source.status", None, None,
        "SOURCE-MISSING: server_exports/chief.py is NOT in the export. The only copy on this "
        "machine (bot/tools/hivemind/chief.py) contains no match for 'brier' or 'p_up', so the "
        "Brier below follows the definition as DESCRIBED, not as coded. Its two free choices -- "
        "the call's own `price` as the base, and the 1h close at/before ts+24h as the outcome -- "
        "are repeated in each row's note and remain unverified.")
    for metric, n, val, note in chief_brier(conn):
        add(metric, n, val, note)

    return rows, {"oos_days": len(evald)}


def write_md(rows, meta):
    ev = meta.get("oos_days", 0)
    lines = [
        "# Replications -- OBSERVATIONS ONLY, no verdicts",
        "",
        "_Written by `crunch/j3_replications.py` every hour. It recomputes the live scan-flag",
        "definitions and the chief Brier on days the original tests never saw, and appends what",
        "it measures to the `replications` table in `panels.sqlite`. **It never concludes",
        "anything.** There is no verdict column here and there will not be one._",
        "",
        "_Do not read this for a verdict before **%s**, or earlier only to check whether a" % READ_DATE,
        "metric's MDE has fallen below the in-sample effect it is replicating. Both numbers are",
        "printed below, every run. A replication read before it could have come out the other",
        "way is not a replication._",
        "",
        "_Updated %s. %d out-of-sample day-block(s) evaluated since %s._" % (
            time.strftime("%Y-%m-%d %H:%M"), ev, OOS_START_DAY),
        "",
        "## What accrued",
        "",
        "| asof | metric | n | value | note |",
        "|---|---|---|---|---|",
    ]
    for asof, metric, n, val, note in rows:
        lines.append("| %s | `%s` | %s | %s | %s |" % (
            asof or "run", metric, "—" if n is None else n,
            "—" if val is None else ("%g" % val), (note or "").replace("|", "/")))
    lines += [
        "",
        "## The refusals, restated",
        "",
        "Each of these is a **refusal, not a zero**. A missing input reported as 0 reads as 'the",
        "flag never fired' or 'the forecaster has no skill', and this project has already",
        "published one false null that way.",
        "",
        "- `funding_hot`, `funding_cold`, and the matched +2.64pp stop difference -- no funding",
        "  cross-section exists on any out-of-sample day. Stated per day in the table above.",
        "- `above_20d_high` -- cannot fire in a day-boundary reconstruction. Declared, not counted.",
        "- `volume_surge` -- the live input is `ctx.dayNtlVlm`; the proxy accrues under a",
        "  different metric name so the two can never be confused.",
        "- the chief Brier definition -- `server_exports/chief.py` is absent, so the Brier is",
        "  implemented from prose and says so in every row it writes.",
        "",
        "## What would unblock what",
        "",
        "- a funding rate per coin per day, or ~20 more days of `ctx` accrual, turns on",
        "  `funding_hot`, `funding_cold` and the matched stop difference;",
        "- `server_exports/chief.py` turns the Brier from prose-derived into code-verified;",
        "- `ctx.mark` accrual turns `above_20d_high` from a structural zero into an observation.",
        "",
    ]
    io.open(OUT, "w", encoding="utf-8").write("\n".join(lines))


def main():
    t0 = time.time()
    init_schema()
    conn = db()
    n = 0
    try:
        rows, meta = build(conn)
        run_day = time.strftime("%Y-%m-%d", time.gmtime())
        # Idempotent: (asof, metric) is the primary key, so an hourly re-run or a
        # double-scheduled run rewrites identical values instead of stacking duplicates.
        # Per-day observations carry their own evaluation day as asof; running figures carry
        # the run date, so the running estimate itself becomes a time series.
        payload = [(asof or run_day, metric, nn, val, (note or "")[:1500])
                   for asof, metric, nn, val, note in rows]
        with conn:
            conn.executemany("INSERT OR REPLACE INTO replications (asof,metric,n,value,note) "
                             "VALUES (?,?,?,?,?)", payload)
        n = len(payload)
        write_md(rows, meta)
        miss = sum(1 for r in rows if r[4] and "SOURCE-MISSING" in r[4])
        log("j3", "%d observations appended, %d SOURCE-MISSING, %d OOS day-blocks, 0 verdicts"
            % (n, miss, meta.get("oos_days", 0)))
        record_run("j3_replications", True, n, time.time() - t0,
                   "%d obs, %d source-missing, %d oos day-blocks, no verdicts"
                   % (n, miss, meta.get("oos_days", 0)))
    except Exception as e:
        record_run("j3_replications", False, n, time.time() - t0, str(e)[:300])
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
