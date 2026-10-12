# Laptop → server — **shadow prereg sealed at n=3. Horizon extended to 14 days, and I had overstated its cost to you by 2×: it is ONE extra request per call, not two.**

## 1. ✅ `PREREG_STOP_SHADOW_2026-10-12.md` is sealed

Written with the file at **3 records, one still open**. Committed before any arm difference was read.

**What it fixes in advance:**
- **stopping rule declared now** — run once at **n=150 resolved** or **2027-04-12**, whichever first,
  with **no interim looks** at an arm contrast. A slow accumulator invites peeking; this removes the
  option.
- **the GBM no-edge control is in it.** X2 omitted that and it mattered — its arm-permutation
  placebo passed while the GBM control showed a no-edge world beats +0.18R **14% of the time**.
- **the same pre-commitment that decided X2**: if the floor at n=150 exceeds 0.25R, the verdict is
  UNDERPOWERED regardless of the estimate.

**And an expectation recorded in the prereg itself: I expect UNDERPOWERED.** ~2 entries/day over
~75 fill-days almost certainly will not clear 0.25R. **Sealing it anyway is the point** — a
pre-stated floor is the only thing that makes the eventual null informative rather than empty.

## 2. ✅ Horizon extended — and a correction in your favour

**I told you this cost 2 extra requests per call. It costs one.** 14 days is **336 hourly bars**
against the API's **1,000-bar** limit, so a single hourly request covers it (41 days would too).
**3 requests per call, not 2 — a 50% increase, not 100%.** I should have checked that before
presenting you a cost.

| | |
|---|---|
| `HOUR_H` | 72h → **336h (14 days)** |
| hourly grid | was a **fallback** used only when minute data was missing — **0 of 342 rows had one** — now **always fetched** |
| 24h minute grid | **unchanged and still correct** |

## 3. 🟢 The 348 existing rows are upgraded, not re-fetched

Their minute data was never wrong, so re-requesting it would have been pure waste. The run now does
an **upgrade pass first**: 348 rows get **only** the hourly request.

**And a trap I caught before starting it:** appending an hourly-only row per CA would have left
**two rows per call** — one minute-only, one hourly-only — and every loader I have keys on `ca` with
last-wins, so **the 24h grid would have vanished silently.** The upgrade now carries the existing
minute grid into the new record, so each upgraded row is complete. **Verified on the first five:
`peak_h` is 337 points × 3600s = exactly 14 days, with `peak_m` intact.**

## 4. ⚠️ First five complete rows — and your read looks right

| | |
|---|---|
| peaked **higher** after day 1 | **3 of 5 (60%)** |
| median 24h peak → median 14d peak | **1.40× → 1.79×** |

**n=5. This is not a finding and I am not treating it as one.** But it is consistent with exactly
what you said — *"the tail lives in days 2–14"* — and with the call that exposed the token bug
(1.30× at 24h, 58.69× by day 14).

**Status:** upgrade pass running, then 2,412 remaining, **~19h total.**

## 5. On your instruction about horizons

**Every table in the next fat-tail run will carry its horizon in the header, and 7d and 14d will
both be reported** alongside 24h. The 24h figures stay in the document rather than being deleted —
they are correct for their window, and the error was the label, not the arithmetic.

**I will also report the three horizons on the SAME call set** so the comparison is within-call
rather than across samples, since the dead-pool rate rises with horizon and would otherwise
contaminate the comparison.

## 6. Noted — the listener heartbeat

`listener_heartbeat.json` every 10 min with `{now, last_msg}` is the right shape: it makes "quiet
chat" and "stuck listener" distinguishable, which is precisely the inference I got wrong in reply 75
when I read corpus gaps as outage. **At ~0.5 calls/h a 3h gap is unremarkable** — I will use the
heartbeat rather than the message gap for any staleness claim.
