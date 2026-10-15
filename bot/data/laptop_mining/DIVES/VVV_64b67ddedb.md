# DIVE — VVV SHORT 22.30 / stop 24.20 / target 19.80 (plans `64b67ddedb` + re-log `206de2bb8d`)

_2026-10-15. Per-trade team: price/vol + flow + exit-geometry miners, every material number
independently re-derived by an adversarial verifier before it appears here. Snapshot: candles_1h
MAX(t) 2026-10-14T22:00Z; plans as_of 1792023073; flow tables end 2026-10-13 ~23:5xZ (≈22h stale —
see the S3 integrity flag in reply 153). R figures pre-fee per the engine's own convention._

## State (verified)
- r = **−0.487 at the export mark** (23.2255); −0.383 at the ~2h-staler last 1h close. The gap is pure
  mark timing — the exporter's formula `(mark−entry)/risk` reproduces exactly.
- **+1R (20.40) never printed** (engine-relevant MFE since fill +0.102R) → **no half banked, no trail
  armed; FULL size rides the 24.20 stop** (`exit_style.py:46,53`).
- MAE −0.778R: the high 23.778 (Oct 14 20:20Z) came **within 1.9% of the stop**.
- From the live mark the stop is **+4.20% / 0.37 ATR** away; +1R is −12.17% / 1.09 ATR.
- Clock: both rows expire 1792101300 — **~21.7h left**; at timeout the full position closes at the
  then-current price.
- The second row `206de2bb8d` is a **re-log** (identical `filled_at`, qty, levels, expiry; log ts +4.1h)
  — one position, not two.

## The coin's own prior (212d, every-4h starts, per-day equal-weighted beside pooled; n=1258 starts/210 days)
- A stop-size UP move (8.52%) completes within 48h **44.8%** of the time; a target-size DOWN move
  (11.21%) only **13.5%**.
- First-touch race: **stop-first 44.4% vs target-first 12.5%** (eqw; decided races go 78% to the stop)
  vs the ~43% decided-win-rate the implied 1.32 R:R needs. **Geometry fights the coin's own prior.**
- Vol: ATR14 2.62 (11.4% of price), ~80th pctile of its own history, falling ~24% vs 14d ago.
- Hour shape (stable per M6): 13–17 UTC carries the widest ranges — roughly two consecutive top-hour
  ranges of adverse movement reach the stop; one full 13–17Z window remains before expiry.

## Flow (verified; all ≈22h stale)
- Funding: +3.0 bps/day EARNED by this short, but tie-inflated percentile (54.7% of all hours sit at the
  +1.25e-5 baseline — the honest read is "at baseline, unremarkable"), and softening ~20% pooled / ~28%
  per-day vs the prior 30d. VVV is on the structurally-hot mute list.
- **Whales net SHORT −$3.6M (6 short / 2 long) and deepening; perp premium 86th pctile → the short side
  is crowded** while price is already +4.2% against entry.
- liq_events has ZERO VVV coverage — squeeze bursts are invisible to this desk. Coverage gap, not calm.

## What the engine will do
Nothing before one of: stop touch (full −1R), a −11.4% move to +1R (bank half, trail arms at
20.40+2.62=23.03), or the 21.7h clock (full close at market). Per M10 this is NOT a winner being
held — the 48h backstop is doing exactly its designed job on a loser.

---
**What matters:** stop 0.37 ATR away after a 0.78R adverse excursion, decided base-rate races 78% to
the stop, and the short side is crowded (whales −$3.6M, premium 86th pct) with squeeze bursts invisible.
**What would change the plan:** nothing mechanical — the 48h clock resolves it in ~22h; dives inform,
they never move an exit.
**Confidence:** high on state/geometry (verifier-reproduced exactly); medium on flow (22h stale, no liq
coverage).
