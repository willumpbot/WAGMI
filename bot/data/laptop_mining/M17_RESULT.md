# M17 - the carry atlas: holding 48h against extreme funding costs 1-several full fees, and it IS forecastable at entry - from the trailing-24h mean, not the instantaneous print. COST ONLY; nothing here is a direction signal.

_2026-10-16. m17_run.py to M17_AMENDMENT_1 (d0456175). DESCRIPTIVE; honesty gates per the amendment
(AT-BASELINE state space over a 59.9%-median-clamped panel; pre-registered tier-level key rule;
30-day floors with POOLED flags; quotable cells = the lines below ONLY)._

## 1. The key rule (pre-registered, decided out-of-sample)
Realized 48h carry is forecast by the TRAILING-24H MEAN funding with OOS R2 0.79 / 0.79 / 0.76
(tiers 1/2/3) vs 0.28 / 0.28 / 0.22 for the entry-time print. **Carry is forecastable at entry;
the regime mean is the key.** (The instantaneous print is noise around it - consistent with extreme
states decaying inside a hold: P(still extreme after 48h) median 0.16.)

## 2. The flip table (state 4 = own trailing-90d off-baseline >p90, AGAINST the position; 48h hold)
| tier | median cost | IQR | P(cost >= 1 fee, 9bps) | P(>= 2 fees) | n hours |
|---|---|---|---|---|---|
| 1 (top-20 majors) | 28.2 bps | 18.7-39.3 | 0.98 | 0.76 | 416 |
| 2 (mid-60) | 20.5 bps | 13.1-31.8 | 0.94 | 0.59 | 285 |
| 3 (rest) | **58.5 bps** | 30.4-92.7 | 0.99 | **0.92** | 652 |

These are REALIZED costs (decay included). Per-coin cells pass the 30-day floor on only 4 coins -
extreme states are rare per coin; the tier POOLED cells carry the table (flagged per the amendment).

## 3. What the planner may do with it (cost arithmetic, not a signal)
A 1R plan's whole net edge is tens of bps. When the trailing-24h funding mean sits in the extreme
state AGAINST the plan's side, 48h of carry mechanically consumes ~20-30 bps (majors/mids) to ~60 bps
(small caps) of it - with near-certainty of at least one full fee. Resizing or vetoing on that state
is justified arithmetic. The symmetric carry-FOR magnitudes exist in the atlas as symmetry displays
only; per the amendment they carry no threshold or earns-you language, and this table says nothing
about which direction wins - that question is CLOSED (M28, noise-compatible).

## Limits
Pooled-tier cells dominate (per-coin extreme-state data is thin); trailing-90d conventions throughout;
one venue's funding; the live snapshot (current open plans vs their thresholds) ships separately with
the harsher-of sf rule and a timestamp, never as a panel-wide screen.
