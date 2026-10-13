"""Fingerprint a LIVE source panel so a quoted result can name the state it came from.

WHY THIS EXISTS -- discovered 2026-10-13, M7.

`crunch/panels.sqlite` is NOT a frozen dataset. The desktop exports into it hourly. Five consecutive
runs of `m7_correlation.py`, with `np.random.default_rng(20261013)` fixed, returned FIVE DIFFERENT
SAMPLES:

    candles_1h rows   884,982 -> 885,100 -> 885,110 -> 885,121 -> 885,132 -> 885,145
    spike lambda        1.771    1.726     1.846     1.865     1.907

The seed was never the problem. More rows move `n`, and `n` sets the range the entry indices are drawn
from, so the sample changes underneath a fixed seed. **A RE-RUN OF A LIVE PANEL IS NOT A REPLICATION**,
and "ran once, exactly as sealed" is not a verifiable claim unless the run says WHICH panel it ran on.

The accident was not all cost: five unplanned re-runs became a stability check nobody designed, and it
is what separated M7's solid unconditional lambda (1.637 every time) from its unstable spike estimate.
But that was luck, and luck is not a method.

USE: call `stamp(conn, tables)` and put the result in the output JSON under "source_snapshot".

NOTE ON THE RETROFIT: M4, M5 and M6 were run and published BEFORE this existed. Their results stand --
they are simply not exactly reproducible, which is stated in their result documents rather than implied
away. This module is wired into them so every FUTURE run is tied to a snapshot. Their published numbers
were deliberately NOT recomputed: re-running them now would produce slightly different figures off a
later panel and replace a recorded result with an unrecorded one, which is the opposite of the fix.
"""


def stamp(conn, tables=("candles_1h",)):
    """Return {table: {max_t, rows}} for each table. Never raises -- a stamp must not break a study."""
    out = {}
    for t in tables:
        try:
            mx, n = conn.execute("SELECT MAX(t), COUNT(*) FROM %s" % t).fetchone()
            out[t] = {"max_t": mx, "rows": n}
        except Exception as e:                      # a missing table is recorded, not silently dropped
            out[t] = {"error": "%s: %s" % (type(e).__name__, e)}
    return out


def describe(snap):
    """One-line human form for stdout, so the snapshot is visible in the run log too."""
    bits = []
    for t, v in sorted(snap.items()):
        if "error" in v:
            bits.append("%s=ERROR(%s)" % (t, v["error"]))
        else:
            bits.append("%s rows=%s max_t=%s" % (t, v.get("rows"), v.get("max_t")))
    return " | ".join(bits) if bits else "(no tables stamped)"
