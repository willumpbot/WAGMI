# Crunch layer status

_Written by `crunch/crunch_all.py`. This is the unattended layer: it runs hourly,
costs no Claude tokens, and its job is to make sure that when a human does look,
the data is already joined and the integrity is already checked._

_Last run 2026-10-11 14:18, took 534s._

| job | result | rows | secs | note |
|---|---|---|---|---|
| `j1_panels` | ok | 878667 | 2 |  |
| `j5_backfill` | **FAILED** | 87859 | 529 | 177 coins ok, 1 failed / TURBO:API failed after 4 tries: HTTP Error 429 |
| `j2_trackers` | ok | 3 | 0 |  |
| `j4_integrity` | ok | 32 | 3 |  |

## 🔴 1 job(s) failed this run

- `j5_backfill`: 177 coins ok, 1 failed | TURBO:API failed after 4 tries: HTTP Error 429

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

## Not built yet, deliberately

- **j3_replications** — out-of-sample recomputation of the live `funding_hot`
  stop-exceedance rule, scan-flag outcomes and chief Brier. **Blocked on the
  exact live definitions**: writing a replication against a guessed definition
  produces numbers that look like replications and are not. That is an ask for
  the server, not something to approximate here.
