# Crunch layer status

_Written by `crunch/crunch_all.py`. This is the unattended layer: it runs hourly,
costs no Claude tokens, and its job is to make sure that when a human does look,
the data is already joined and the integrity is already checked._

_Last run 2026-10-11 22:10, took 1s._

| job | result | rows | secs | note |
|---|---|---|---|---|
| `j1_panels` | running… | — | 0 | not started yet |
| `j6_archive` | running… | — | 0 | not started yet |
| `j5_backfill` | running… | — | 0 | not started yet |
| `j2_trackers` | running… | — | 0 | not started yet |
| `j4_integrity` | running… | — | 0 | not started yet |
| `j3_replications` | running… | — | 0 | not started yet |

🟡 **A run is IN PROGRESS as of the timestamp above.** If this line is still
here more than an hour later, the run died mid-loop -- which is exactly the
case the old write-at-the-end order could not show.

## What each job does

- **j1_panels** — folds `server_exports/` (ctx snapshots, 5m candles) and the 1h
  CSV panel into `crunch/panels.sqlite`, keyed `(coin, t)` so it is idempotent.
  The laptop is the long-term archive: the server keeps 30 days and Hyperliquid
  deletes 5m candles after ~17 days.
- **j5_backfill** — keeps 1h candles and funding history current for every live
  perp, throttled 0.8s/call because an unthrottled sweep hit HTTP 429 after 37
  coins. First run paginates back ~2.3 years; later runs only fetch forward.
- **j2_trackers** — running n for each sealed prereg and nothing else. No
  statistic is computed before its unlock date; the look is what spends the alpha.
- **j4_integrity** — presence, growth, fill rates and gaps per export. Treats
  `hb_age_s > 1e8` as a read error, which is what caused two false DOWN alerts.
- **j3_replications** — recomputes the live scan-flag conditions from
  `server_exports/scanner.py` and the chief Brier on days the original tests
  never saw, and appends each measurement with its n, its equal-weighted
  day-block mean and its MDE. **It writes no verdicts** — a human reads
  `REPLICATIONS.md` on the date stated in it. Unblocked 2026-10-11 when the real
  definitions arrived; what is still missing is reported as SOURCE-MISSING per
  metric rather than as a zero.
