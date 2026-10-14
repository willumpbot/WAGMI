# Prereg forward trackers -- COUNTS ONLY, no statistics

_Written by `crunch/j2_trackers.py`. This file deliberately contains no test
statistic, no p-value and no direction. Each prereg committed to ONE interim look
at a stated n; computing the statistic every hour would spend that alpha silently.
A missing source is reported as SOURCE-MISSING, never as n=0._

_Updated 2026-10-14 11:21. Seal date 2026-10-11 (3 days ago)._

| prereg | unlock condition | running n | reached? | remaining |
|---|---|---|---|---|
| `OI` | n_days >= 106, interim at alpha=0.005 | **1** (1 day(s) on which a 24h OI change is computable, from 88.4 h of archive over 178 coins. The unit is DAYS, not coin-days: one day is one observation of the clustered quantity the prereg sizes) | not yet | 105 more |
| `IDEAS` | n resolved >= 87, interim at alpha=0.005 | **18** (18 of 23 ideas resolved (server stats.n=5 -- disagrees, worth a look)) | not yet | 69 more |
| `ADOPT` | both arms >= 44, interim at alpha=0.005 | **7** (adopt=18 adjust=0 skip=7 (6 ideas still inside their entry window; 3 decisions EXCLUDED as source_inferred)) | not yet | 37 more |

**Nothing in this table authorises a conclusion.** When a row reads *unlocked*, the
analysis is run once, by hand, against the sealed design -- and its result is
reported whichever way it comes out.
