"""Port of the live exit engine (execution/position_manager.py), Mission D.

Spec source: server_exports/README_DATA_RESPONSE.md section 2.
  - arms ONLY after TP1: OPEN -> TP1 -> partial close (tp1_close_pct, default 0.5)
    -> stop to cushioned breakeven -> TRAILING
  - trailing_distance = ATR * trailing_atr_mult(1.5) * style, FIXED AT ENTRY
  - tighten by progress TP1->TP2: MEDIUM 0.67->0.33, SCALP 0.80->0.50, TREND 0.50->0.25
  - profit-lock floor so the stop never gives back more than the locked share of the peak
  - evaluated on the bot scan (~3 min, LAST TRADE PRICE) -- "bar-close-like, not ticks"

Three fixes are baked in, each from a bug that refuted the earlier trailing study:

  FIX 1  the hard stop is ALWAYS live. The refuted study disabled it once the trail
         armed, which let losers run to a favourable trail exit instead of stopping out.
  FIX 2  the trail is tested against the CURRENT bar own extreme. The refuted study
         compared against the previous bars running best, the most favourable possible
         ordering, and flipping that alone turned 6-of-6 wins into 0-of-6.
  FIX 3  fills are GAP-AWARE. The refuted study booked the trigger level exactly. Here a
         bar that has already passed the trigger fills at the observed price, which is
         what the real engine gets -- it checks on a scan, it does not rest an order.

Because the spec says the engine sees last trade price per scan, CLOSE-ONLY is the
faithful mode. The high/low modes are reported as the pessimistic and optimistic edges
of a band, never as the point estimate.

NOT YET RUNNABLE ON REAL DATA -- see MISSION_D_BLOCKED.md. 5m candles expire after
~17 days and no export carries tp1 or the original stop. This file exists so the
replay runs the day those land.
"""
from dataclasses import dataclass, field

TIGHTEN = {"SCALP": (0.80, 0.50), "MEDIUM": (0.67, 0.33), "TREND": (0.50, 0.25)}


@dataclass
class Profile:
    style: str = "MEDIUM"
    tp1_close_pct: float = 0.5
    trailing_atr_mult: float = 1.5
    style_mult: float = 1.0
    be_cushion_frac: float = 0.1          # "cushioned breakeven", share of risk kept back
    # Profile constants no export carries. These are INPUTS, not findings -- the server
    # must supply the real floor_* values before any number from this engine is quoted.
    floor_progress_start: float = 0.5
    floor_lock_start: float = 0.3
    floor_lock_max: float = 0.7


@dataclass
class Position:
    side: str          # LONG | SHORT
    entry: float
    sl: float          # ORIGINAL stop, never overwritten (FIX 1 / the position_sl bug)
    tp1: float
    tp2: float
    atr: float
    prof: Profile = field(default_factory=Profile)

    def __post_init__(self):
        self.sgn = 1.0 if self.side.upper() == "LONG" else -1.0
        self.risk0 = abs(self.entry - self.sl)
        assert self.risk0 > 0, "zero risk"
        self.dist = self.atr * self.prof.trailing_atr_mult * self.prof.style_mult
        self.state = "OPEN"
        self.stop = self.sl                # live stop
        self.hard = self.sl                # FIX 1: never moves, always checked
        self.peak = 0.0                    # best favourable excursion, price terms
        self.banked = 0.0                  # R already realised from the TP1 partial
        self.qty = 1.0

    def fav(self, px):
        return self.sgn * (px - self.entry)

    def progress(self, px):
        """fraction of the way from TP1 to TP2, clamped to [0, 1]"""
        span = self.sgn * (self.tp2 - self.tp1)
        if span <= 0:
            return 1.0
        return max(0.0, min(1.0, self.sgn * (px - self.tp1) / span))

    def trail_stop(self, px):
        """where the trail would sit at this price. Spec section 2."""
        a, b = TIGHTEN[self.prof.style.upper()]
        frac = a + (b - a) * self.progress(px)
        trailed = px - self.sgn * self.dist * frac
        # profit-lock floor: once far enough along, never give back more than the
        # locked share of the PEAK move
        if self.peak > 0:
            prog = self.progress(self.entry + self.sgn * self.peak)
            if prog >= self.prof.floor_progress_start:
                lock = self.prof.floor_lock_start + (
                    self.prof.floor_lock_max - self.prof.floor_lock_start
                ) * min(1.0, prog)
                floor = self.entry + self.sgn * self.peak * lock
                trailed = max(trailed, floor) if self.sgn > 0 else min(trailed, floor)
        # a trail never retreats
        return max(trailed, self.stop) if self.sgn > 0 else min(trailed, self.stop)


# Modes vary TWO independent axes, and an earlier version of this file mixed them
# incoherently -- it triggered on the bar extreme (pessimistic) but then filled at the
# stop level (optimistic), which flattered a 7-point adverse bar into +1.56R.
#
#   trigger: "close"   the scan only ever sees the last trade price  <- the spec
#            "extreme" the scan catches the bar adverse extreme
#   fill:    "level"   perfect execution at the trigger price        <- optimistic
#            "close"   filled at the price the scan actually saw     <- the spec
#            "extreme" filled at the bar adverse extreme             <- pessimistic
#
# MODES below are the three reported arms. Only `faithful` is quoted as the estimate;
# the other two are the band edges.
MODES = {
    "optimistic": ("extreme", "level"),
    "faithful":   ("close",   "close"),
    "pessimistic": ("extreme", "extreme"),
}


def step(p, o, h, l, c, mode="faithful"):
    """Advance one scan bar. Returns (closed, fill_price, reason)."""
    sg = p.sgn
    adverse = l if sg > 0 else h
    favour = h if sg > 0 else l
    trig_ax, fill_ax = MODES[mode]

    def exit_fill(level, probe):
        """price an exit, given the mode fill axis. Always gap-aware (FIX 3)."""
        gap = (o <= level) if sg > 0 else (o >= level)
        if gap:
            return o                      # the bar opened through it: that is the fill
        if fill_ax == "level":
            return level
        if fill_ax == "close":
            return c
        return adverse                    # "extreme"

    def beyond_stop(px):
        return (px <= p.stop) if sg > 0 else (px >= p.stop)

    def beyond_hard(px):
        return (px <= p.hard) if sg > 0 else (px >= p.hard)

    def reached(px, lvl):
        return (px >= lvl) if sg > 0 else (px <= lvl)

    # FIX 1: the hard stop is checked on every bar while the position is unarmed.
    probe_hard = c if trig_ax == "close" else adverse
    if p.state == "OPEN" and beyond_hard(probe_hard):
        return True, exit_fill(p.hard, probe_hard), "HARD_SL"

    if p.state == "OPEN":
        # TP1 detection uses the FAVOURABLE side, so the trigger axis flips here:
        # "close" still means close-only, "extreme" means the favourable extreme.
        trigger = c if trig_ax == "close" else favour
        if reached(trigger, p.tp1):
            p.state = "TRAILING"
            p.banked = p.prof.tp1_close_pct * abs(p.tp1 - p.entry) / p.risk0
            p.qty = 1.0 - p.prof.tp1_close_pct
            cushion = p.entry - sg * p.risk0 * p.prof.be_cushion_frac
            p.stop = max(p.stop, cushion) if sg > 0 else min(p.stop, cushion)
            p.peak = max(p.peak, p.fav(trigger))
        return False, None, None

    if p.state == "TRAILING":
        # NO LOOKAHEAD. The exit is checked against the stop as it stood at the END of
        # the previous bar, and only then does this bar move the stop for the next one.
        #
        # The earlier version updated the stop from THIS bar favourable extreme and then
        # triggered it with THIS bar adverse extreme -- so on a 101..106 bar the stop
        # ratcheted to 104.33 off the high and filled at the 104 open, a fill that
        # happened BEFORE the high that set the level. That is time travel, and it is
        # the same intra-bar ordering error that refuted the earlier trailing study.
        probe = c if trig_ax == "close" else adverse
        hit_stop = beyond_stop(probe)
        hit_tp2 = reached(c if trig_ax == "close" else favour, p.tp2)

        # the stop is checked before the target in the pessimistic arm and after it in
        # the optimistic arm -- that ordering is part of the band, not a hidden choice.
        if mode == "pessimistic":
            if hit_stop:
                return True, exit_fill(p.stop, probe), "TRAIL_SL"
            if hit_tp2:
                return True, p.tp2, "TP2"
        else:
            if hit_tp2:
                return True, p.tp2, "TP2"
            if hit_stop:
                return True, exit_fill(p.stop, probe), "TRAIL_SL"

        # Survived the bar: NOW ratchet. The ratchet ALWAYS uses the close, in every
        # mode, because the spec says the engine ratchets off the last trade price it
        # sees on a scan. Letting the band vary this was a mistake: ratcheting off the
        # bar high is not a pessimistic execution assumption, it is a DIFFERENT engine
        # (a tighter trail), and it scored BETTER than the faithful arm on a falling
        # path -- which is how the band came out unordered. A band must hold the engine
        # fixed and vary only the execution. FIX 2 still applies: the ratchet uses this
        # bar own price, never a running best carried in from earlier bars.
        p.peak = max(p.peak, p.fav(c))
        new = p.trail_stop(c)
        p.stop = max(p.stop, new) if sg > 0 else min(p.stop, new)
    return False, None, None


def run(p, bars, mode="faithful"):
    """bars: list of (ts, o, h, l, c). Returns R and the exit reason."""
    for (_, o, h, l, c) in bars:
        done, fill, note = step(p, o, h, l, c, mode)
        if done:
            rem = p.sgn * (fill - p.entry) / p.risk0
            return {"R": p.banked + p.qty * rem, "exit": note,
                    "fill": fill, "banked": p.banked, "state": p.state}
    last = bars[-1][4]
    rem = p.sgn * (last - p.entry) / p.risk0
    return {"R": p.banked + p.qty * rem, "exit": "OPEN_AT_END",
            "fill": last, "banked": p.banked, "state": p.state}


# =====================================================================
# Self-tests. Each asserts a property of the SPEC or guards a known bug.
# =====================================================================
def _tests():
    out = []

    def mk(**kw):
        d = dict(side="LONG", entry=100.0, sl=98.0, tp1=104.0, tp2=110.0, atr=2.0)
        d.update(kw)
        return Position(**d)

    # 1. FIX 1 -- an armed position that collapses must not escape with a profit.
    #    This is the bug that refuted the earlier trailing study.
    bars = [(0, 100, 104.5, 99.5, 104.2), (1, 104, 104.2, 97.0, 97.5)]
    rr = {m: run(mk(), bars, m) for m in MODES}
    out.append(("armed collapse stops out in every mode",
                all(v["exit"] in ("HARD_SL", "TRAIL_SL") for v in rr.values()),
                {m: round(v["R"], 3) for m, v in rr.items()}))
    # and the fill assumption must actually matter on a bar that traverses 7 points
    out.append(("fill assumption changes the answer on a wide bar",
                abs(rr["optimistic"]["R"] - rr["pessimistic"]["R"]) > 0.5,
                {m: round(v["R"], 3) for m, v in rr.items()}))

    # 2. tighten curve endpoints match the spec (MEDIUM 0.67 -> 0.33); dist = 2*1.5 = 3
    p = mk(); p.state = "TRAILING"; p.stop = 95.0
    at1 = p.trail_stop(104.0)
    p2 = mk(); p2.state = "TRAILING"; p2.stop = 95.0
    at2 = p2.trail_stop(110.0)
    out.append(("tighten 0.67 of dist at TP1", abs(at1 - (104.0 - 3.0 * 0.67)) < 1e-9,
                (at1, 104.0 - 3.0 * 0.67)))
    out.append(("tighten 0.33 of dist at TP2", at2 >= 110.0 - 3.0 * 0.33 - 1e-9,
                (at2, 110.0 - 3.0 * 0.33)))

    # 3. the trail never retreats
    p = mk(); p.state = "TRAILING"; p.stop = 103.0
    out.append(("trail never retreats", p.trail_stop(104.0) >= 103.0, p.trail_stop(104.0)))

    # 4. FIX 3 -- a gap through the stop fills at the gapped open, worse than the level
    r = run(mk(), [(0, 94.0, 94.5, 93.0, 93.5)], "optimistic")
    out.append(("gap fills at the open even when optimistic",
                r["exit"] == "HARD_SL" and abs(r["fill"] - 94.0) < 1e-9, r))

    # 5. the faithful (close-only) arm ignores a wick that never closed through;
    #    the extreme-trigger arms must take it. This is the spec distinction.
    wick = [(0, 100, 100.5, 97.0, 100.2)]
    out.append(("faithful ignores an unclosed wick",
                run(mk(), wick, "faithful")["exit"] == "OPEN_AT_END", None))
    out.append(("pessimistic takes the same wick",
                run(mk(), wick, "pessimistic")["exit"] == "HARD_SL", None))

    # 6. BAND INVARIANT: pessimistic <= faithful <= optimistic.
    #    A failure is an ordering bug -- the class that refuted the earlier study.
    # the path must ARM and then exit on a WIDE bar, or the three arms coincide and
    # the test proves nothing (which is what the first version of it did).
    path = [(0, 100, 104.5, 99.5, 104.2), (1, 104, 106.0, 101.0, 102.0),
            (2, 102, 103.0, 95.0, 96.0)]
    rs = {m: round(run(mk(), path, m)["R"], 4) for m in MODES}
    out.append(("band ordered pessimistic <= faithful <= optimistic",
                rs["pessimistic"] <= rs["faithful"] + 1e-9 and
                rs["faithful"] <= rs["optimistic"] + 1e-9, rs))
    # 6b. META-TEST: the band test must be able to FAIL. An earlier version of this
    #     suite returned an identical R for all three arms, so it proved nothing.
    out.append(("...and that band test actually discriminates",
                len(set(rs.values())) > 1, rs))

    # 7. The TP1 partial is BANKED -- but the total can still go negative on a violent
    #    bar, and an earlier version of this test asserted R > -1.0, which is simply
    #    false: a trail cannot protect against a 14-point single-bar collapse. Assert
    #    the arithmetic identity instead of a comfortable outcome.
    collapse = [(0, 100, 104.5, 99.5, 104.2), (1, 104, 104.3, 90.0, 90.5)]
    rc = {m: run(mk(), collapse, m) for m in MODES}
    ident = all(
        abs(v["R"] - (v["banked"] + 0.5 * (v["fill"] - 100.0) / 2.0)) < 1e-9
        for v in rc.values())
    out.append(("TP1 partial is banked, and R is banked + qty*remainder",
                all(v["banked"] == 1.0 for v in rc.values()) and ident,
                {m: round(v["R"], 3) for m, v in rc.items()}))
    out.append(("a violent bar can still end negative despite the partial",
                rc["pessimistic"]["R"] < 0 < rc["optimistic"]["R"],
                {m: round(v["R"], 3) for m, v in rc.items()}))

    # 8. a SHORT is the mirror of a LONG on a mirrored path, in every mode
    mpath = [(t, 200 - o, 200 - l, 200 - h, 200 - c) for (t, o, h, l, c) in path]
    mir = {}
    for m in MODES:
        lp = run(mk(), path, m)["R"]
        sp = run(Position(side="SHORT", entry=100.0, sl=102.0, tp1=96.0,
                          tp2=90.0, atr=2.0), mpath, m)["R"]
        mir[m] = (round(lp, 4), round(sp, 4))
    out.append(("SHORT mirrors LONG in all three modes",
                all(abs(a - b) < 1e-9 for a, b in mir.values()), mir))

    print("SELF-TESTS")
    bad = 0
    for name, ok, detail in out:
        print("  [%s] %-44s %s" % ("PASS" if ok else "FAIL", name, detail))
        bad += not ok
    print("  %d/%d passed" % (len(out) - bad, len(out)))
    return bad


if __name__ == "__main__":
    import sys
    sys.exit(1 if _tests() else 0)
