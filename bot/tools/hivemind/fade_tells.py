"""fade_tells.py - EXPLORATORY / INSIGHT-ONLY classifier for the give-back alert (PC ask 03252033).
Given a filled position that just reached +0.5R, label it FADE_PRONE vs RUN_LIKELY from what is knowable
AT the +0.5R bar (strictly pre-peak). This ANNOTATES the alert to inform the owner's manual
Trim/Close/Hold; it is NOT an auto-rule and writes NO gate. The signal is real+directional but MODEST
(discovery clean composite +0.070, below the strict 0.05 substantive floor on the lower bound) and is
pending a FORWARD confirmation (M32C_FADE_PREREG v2). Treat the label as a lean, not a verdict.

Frozen definitions (M32C_FADE_PREREG v2 seal):
  velocity   = number of 1h bars from entry to the first +0.5R touch (b05).
  clean_surge= volume at the bar BEFORE the +0.5R cross / mean 1h volume over the 72 bars before entry.
               (EXCLUDES the crossing bar, which is partly the move itself.)
  FADE_PRONE = (clean_surge <= 0.6907) AND (velocity >= 9 bars).   # quiet AND slow
  RUN_LIKELY = otherwise.
Discovery base P(FADE)=0.642; FADE_PRONE ~0.70, RUN_LIKELY ~0.63 (clean composite gap +0.070).
"""
S_STAR = 0.6907     # discovery median of clean_surge (frozen)
VEL_STAR = 9.0      # discovery median of bars-to-+0.5R (frozen)
BASE_FADE = 0.642


def classify(velocity_bars, vol_prev_bar, vol_mean_72_before_entry):
    """Returns (label, lean_note). All inputs knowable AT the +0.5R bar; no look-ahead.
    velocity_bars: bars from entry to the first +0.5R touch.
    vol_prev_bar:  1h volume of the bar BEFORE the +0.5R cross (exclude the crossing bar).
    vol_mean_72_before_entry: mean 1h volume over the 72 bars before entry (the surge baseline).
    """
    if velocity_bars is None or vol_mean_72_before_entry in (None, 0):
        return "UNKNOWN", "insufficient pre-peak data; no lean"
    clean_surge = float(vol_prev_bar) / float(vol_mean_72_before_entry)
    fade_prone = (clean_surge <= S_STAR) and (float(velocity_bars) >= VEL_STAR)
    if fade_prone:
        return "FADE_PRONE", ("quiet & slow +0.5R (surge %.2f<=%.2f, %d>=%d bars): historically fades "
                              "~70%% - consider trimming/laddering. INSIGHT ONLY, pending forward confirm."
                              % (clean_surge, S_STAR, int(velocity_bars), int(VEL_STAR)))
    return "RUN_LIKELY", ("impulsive +0.5R (surge %.2f or fast %d bars): historically fades less (~63%%) "
                          "- consider giving room. INSIGHT ONLY, pending forward confirm." % (clean_surge, int(velocity_bars)))
