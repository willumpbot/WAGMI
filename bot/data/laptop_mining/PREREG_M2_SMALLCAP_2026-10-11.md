# PREREG — M2: does small-cap perp momentum continue after costs?

**Sealed 2026-10-11, before any small-cap result was computed.** Mission M2 from the server
(`SERVER_REPLY.md`, ~18:30Z), narrowed by the owner: *"I don't necessarily need small-cap perp
flagging, I do think however we should be paying more attention to them."* So the deliverable is a
research verdict and, if it stands, sizing/exit guidance — **not** a new flag.

The owner's own framing, which is what prompted this: *"some of the smaller bigger momentum ones that
we have been noticing and having on lists could've had some really good calls for us if we had chosen
to dive into them once we found some trend."*

## 0. The reason this prereg exists, stated plainly

**The coins we "noticed trending" were noticed because they had already run.** Any test on the
remembered ones is selection on the outcome, and it cannot come out negative. That is the exact
failure that overturned six conclusions on 2026-10-08. So this tests a *mechanical rule* on *every*
qualifying coin, including every coin that trended and then died.

## 1. Universe (point-in-time, fixed now)

- All Hyperliquid perps with >= 600 bars of 1h history in `history1h/`.
- At each timestamp, rank coins by **trailing 20-day dollar volume computed inside the panel**
  (close x volume, 480h mean). Exclude the **top 15**. Current-day volume is NOT used for ranking —
  that would leak the future.
- Minimum 10 eligible coins at a timestamp or it is dropped.

## 2. 🔴 The bias I cannot fix, and its direction — stated BEFORE the result

**Hyperliquid does not serve candles for delisted perps.** My universe is coins alive on 2026-10-11.
Every small cap that pumped, collapsed and got delisted inside the window is **missing**.

**Direction: this inflates momentum returns.** Delisted small caps overwhelmingly went to zero, and a
momentum-long rule would have bought some of them on the way up. So a positive result here is an
**upper bound**, and a null result is strong. I am writing this down now so the finding cannot later
be presented without it.

## 3. Signals (4, fixed; no variants added after looking)

| id | definition |
|---|---|
| `S1_breakout` | close > max close of the prior 480h (20d), strictly above |
| `S2_volsurge`  | trailing 24h dollar volume > 2.0x its trailing 480h mean |
| `S3_both`      | S1 and S2 — the server's live `momentum_small` flag |
| `S4_movesurge` | trailing 24h return > 1.5x the trailing 20d mean absolute 24h move, AND positive |

## 4. Horizons and exits

- Horizons: **1h, 4h, 24h, 72h** forward return from the signal bar close.
- Primary exit: **fixed horizon**. Secondary, reported separately: trailing stop 15% and 25%, fixed
  target +10%, both evaluated on 1h bars within the 72h window.

## 5. Costs, stated before the result

Single-coin directional round trip = entry + exit = **2 x 9 bps = 18 bps** taker. Small caps slip, so
the verdict is reported at **18 / 40 / 80 bps** and the headline verdict uses **40 bps**.

## 6. Two nulls. The effect must survive BOTH.

- **N1 coin-matched:** for each signal event, 20 non-signal timestamps for the *same coin* drawn
  within +/-14 days. Cancels that coin's own drift.
- **N2 time-matched:** for each signal event, 20 non-signal *coins* at the *same timestamp*. Cancels
  the market move.

Statistic = real minus the mean of the matched draws, per event. A finding that only survives one null
is a statement about the other dimension, not about momentum.

## 7. Power and clustering — declared before any verdict

- Many small caps fire on the **same day**. The clustering unit is therefore the **signal day**, not
  the event. Effective n = distinct signal days.
- Design effect `1+(m-1)rho` reported with the measured within-day correlation of event returns.
- Day-block bootstrap, block = max(24h, horizon).
- **MDE at 80% power printed for every cell before the verdict line.**

## 8. Multiplicity

4 signals x 4 horizons = **16 cells**. Bonferroni two-sided 0.05/16 -> **|z| > 2.95**.

## 9. Verdict rule — fixed now, so it cannot be bent to the result

**STANDS** only if ALL of:
1. clears |z| > 2.95 against **both** N1 and N2;
2. **net of 40 bps** the mean is still positive;
3. **not concentrated** — top 5% of events hold < 50% of the total return (the v2 lesson);
4. holds **walk-forward** — fit nothing, but the sign and rough size repeat in both halves of the
   window split at the midpoint date;
5. the §2 survivorship bound is restated with it.

Anything less is **NOT A FINDING**, and nothing changes on the bot either way without a SUPPORT
verdict and the owner's yes.

## 10. Capacity, reported regardless of verdict

Notional supportable at $500 / $2k / $10k per position, from trailing dollar volume (a size-scaled
proxy; `impactPxs` depth is not in this panel).
