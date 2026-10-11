# Prereg forward trackers -- COUNTS ONLY, no statistics

_Written by `crunch/j2_trackers.py`. This file deliberately contains no test
statistic, no p-value and no direction. Each prereg committed to ONE interim look
at a stated n; computing the statistic every hour would spend that alpha silently.
A missing source is reported as SOURCE-MISSING, never as n=0._

_Updated 2026-10-11 14:18. Seal date 2026-10-11 (0 days ago)._

| prereg | unlock condition | running n | reached? | remaining |
|---|---|---|---|---|
| `OI` | n_days >= 106, interim at alpha=0.005 | **1** (1 snapshot days on or after the seal) | not yet | 105 more |
| `IDEAS` | n resolved >= 87, interim at alpha=0.005 | **0** (0 of 3 ideas resolved) | not yet | 87 more |
| `ADOPT` | both arms >= 44, interim at alpha=0.005 | **0** (adopt=0 adjust=0 skip=0 over 5 plan rows (0 excluded as source_inferred) — genuine zero: adopt_mode populates only when a decision is taken) | not yet | 44 more |

**Nothing in this table authorises a conclusion.** When a row reads *unlocked*, the
analysis is run once, by hand, against the sealed design -- and its result is
reported whichever way it comes out.
