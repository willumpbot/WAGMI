# M29 stage 2 — wallet A's three costliest habits, with n and day-block bootstrap CIs

_2026-10-15. 262 round trips rebuilt by position-walking the 1,108 API fills (totals re-match the
7-cent-reconciled baseline exactly: net −$1,746.70 = pnl −$726.29 − fees $1,020.41). 24 trading days.
**R is undefined for this account — no stop order ever existed — so costs are in $ and % of the bleed;
that absence is habit #0.** Descriptive analytics on the owner's own data; no sealed population._

## The shape of the loss: U-curve in hold time (the headline)

| hold | n | net | mean/trip | fees |
|---|---|---|---|---|
| **< 10 min** | **107** | **−$989** | −$9.24 | $418 |
| 10–60 min | 87 | −$108 | −$1.24 | $355 |
| **1–6 h** | **44** | **+$3** | **+$0.07** | $181 |
| **> 6 h** | **24** | **−$653** | **−$27.21** | $66 |

**Both tails lose; the middle breaks even.** The sub-10-minute scalps are death by a thousand fees;
the >6h holds are the unmanaged disasters (the −$253 ASTER, −$249 ETH class — positions with no stop
riding into cascades). The 1–6h band — trades long enough to breathe, short enough to still be watched
— is the only segment that didn't bleed.

## The three costliest habits, ranked

1. **Sub-10-minute scalping** — n=107 trips, −$989 (57% of the account's loss), carrying $418 of fees.
   Fee total across all trips: $1,020, 95% day-boot CI [$523, $1,637] = **58% of the entire loss**.
2. **Unmanaged long holds** — n=24 trips over 6h, −$653, worst per-trip bleed (−$27). Every one rode
   without a stop; this is where the liquidations and panic closes live.
3. **Red-day escalation** — on losing days he traded **11.5 trips/day vs 8.6 on green days** (+34%,
   n=19 red / 5 green days), and the worst 3 days carry **57% of the total loss**.

**Honest revision of my own earlier framing:** the ≤10-min opposite-side flips (n=43) netted −$166 but
averaged −$3.86/trip vs −$7.22 for non-flips — flipping was NOT a distinctively costly habit per trip;
it was part of the scalping churn, not a separate disease. Also: the API's `dir` strings mark only 1
trip as a liquidation (−$43) vs 9 liquidation events in the UI history — the venue labels them
differently across surfaces; the UI count stands for the event narrative, the per-trip accounting above
is complete either way.

## Map labels: not placeable — stated, not fudged
Wallet A's HL history (2025-09 → 2026-02) **predates the M28 map's 212-day panel (≈2026-03 → 10)
entirely**: 0 of 262 trips land on a map moment. Placing these labels needs the panel extended back a
year — noted for whenever a longer panel is built; not improvised here.

---
**What matters:** the loss is two habits, not twenty — scalps under 10 minutes (fees) and stop-less
holds over 6 hours (disasters); the middle of his own trading was already breakeven, and he escalates
on red days.
**What would change things:** the bot's rules already ban all three structurally; for the owner's own
manual trading the one-line version is "nothing under an hour, nothing without a stop, half-size on a
red day."
**Confidence:** high — totals reconcile to the cent with the chain; CIs are day-blocked; the flip
revision and the liq-label discrepancy are stated rather than smoothed.
