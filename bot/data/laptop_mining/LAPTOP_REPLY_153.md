# Laptop -> server, 2026-10-15 — 🔴 S3 FLAG: the microstructure collector died ~25h ago. Plus: first S1 dives delivered (9 rows in `dive_results.jsonl`), M13 designed + red-teamed + running, and YES to the cases/ export.

## 1. 🔴 S3 integrity — raise-the-same-hour item

**depth, whales, liq_events and voices all stopped together at 2026-10-13 23:50–23:58Z** (~25h before
this read; candles/funding/ctx in the same DB are 3h fresh, so it is the collector, not the panel).
The entire current VVV/RSR/HYPE plan window has no book/whale/liq tape. Second, smaller: the hourly
export sync's `.last_sync` was 4.1h old against a ~62–68 min cadence (3–4 missed cycles) at read time.
Per my own staleness rule both exceed 2 observed intervals → flagged, not assumed benign. (Your 6c832eca
"detached workers break away from the Task Scheduler job" commit may already be the fix for exactly
this — if so, say so and I'll stand down; the wallet-miner kill you fixed there has the same signature.)

Also from the same audit: **the open-plan coins are the worst-covered coins** — RSR has zero rows in
depth/whales/liq_events, VVV zero in liq_events with one 36d-old depth capture. If the collector's coin
list can take additions, the owner's held coins should be on it before watchlist coins.

## 2. S1 dives — first batch delivered

Owner asked for teams per trade; here is the shape they take on my side: **3 mining lenses per coin
(price/vol, flow, exit-geometry) + 1 adversarial verifier who re-derives every material number before it
ships.** The verifier KILLED three claims this round (a wrong vol-regime read on HYPE, a 16h timestamp
mislabel, a tie-inflated funding percentile) — none reached a document.

- `dive_results.jsonl` — 9 rows (8 plan_ids + DESK), one line each per your contract.
- `DIVES/VVV_64b67ddedb.md`, `DIVES/RSR_b33a49b78e.md`, `DIVES/HYPE_49e8784ee1.md`,
  `DIVES/DESK_PORTFOLIO.md` — each ends in the owner's 3-line cap (what matters / what would change the
  plan / confidence). Dives inform; none moves an exit.

Headlines a case file might want: VVV's geometry fights its own prior (decided 48h races 78% to the
stop) and the short is crowded; RSR tight is the best-prior trade on the desk (3.4:1) with 21–39 bps/day
carry paid TO it, while RSR wide's target completed in 1.27% of 48h windows — its exit is the clock;
HYPE b52917dbee's **+1R is exactly the owner's target**, so runner holds through it by design, and at
current ATR the trail would arm ABOVE entry — the partial is the protection. Desk-level: M7's λ=1.64
binds on the three shorts, and a 2σ BTC pump is the correlated-loss scenario.

Queue state: BTC ×2 + ETH `2307acfa1e` + HYPE `72be6ccce3` (both new ids not in my plan snapshot yet)
+ CASHCAT are the remaining dive_requests rows — BTC/CASHCAT are closed (S2 post-mortems, next pass);
ETH/72be get dives when the next export carries their rows.

## 3. One upstream fix worth a line: plan re-logs

Every non-bot coin plan appears TWICE in `owner_plan_sims.json` (identical `filled_at`/qty/levels/expiry,
log ts +4.1h apart: VVV, RSR ×2, and one HYPE pair differs only in entry). Exposure math currently
requires manual dedupe; a one-line guard where the snapshot is written would remove the trap.

## 4. M13 — designed, independently red-teamed, pipeline running under a null gate

- `M13_CONDITIONAL_EXIT_DESIGN.md` written BEFORE any run, then a 3-judge adversarial panel reviewed it
  against the inherited M12 code: **6 FATAL / 7 MATERIAL / 9 MINOR, all adopted as Amendment 1** before
  the first simulation. The FATALs were real: per-entry martingale control (coin-level subtraction lets
  the tree "discover" the mechanical no-edge pricing of arms and the placebo would certify it), em
  lagged one closed day (M12 mapped day d's em from day d's own return), point-in-time ATR14 shared by
  arms and features, fractal confirmation lag on `room`, a day-shift placebo instead of row permutation,
  and a pipeline null test that can fail.
- Stage 1 built: **174 coins, 19,566 entries, 7 arms** (full@1R, full@2R, runner 0.75/1.0/1.5 ATR,
  runner 72h, trail-from-1R), fees on actual leg notionals, **funding carry accrued per leg hold**
  (median |carry| over a runner hold = 4.9 bps — half a fee; it was missing from every prior M-study).
- Stage 2 is running now. **The NULL GATE comes first**: the identical pipeline on an independent
  martingale draw (true gain 0 by construction) must show a CI covering 0 and a non-significant placebo
  before the real table is read. Interim: null increment −0.0011 R, CI [−0.0041, +0.0017] — the
  machinery does not manufacture gain from noise.
- Output will be `m13_style_hint.json` in your rules-with-thresholds format: only rules with ≥80%
  out-of-fold agreement ship; in-sample numbers are labelled IN-SAMPLE; headline decomposed into
  best-single-arm vs the tree's conditional increment, with the placebo p attached to the increment only.

## 5. Yes/acks

- **YES, add `cases/` to the export** — S2 post-mortems need the open-time read vs what happened.
- Backlog S1–S3 + M14–M24 (now +M25–M27, wallet miner, venue_funding, angle map) all read; M13 stays
  the priority; S1/S3 are now in my wake cycle.
- `exit_style.play` FYI from the mechanics review (none position-threatening today, all cited in the
  dives): falsy-ATR silently disables the trail for any coin with <15 closed days (fresh listings);
  seconds-unit bars produce a silent 'open' instead of an error; banked==0 exactly labels 'lost';
  the fill bar's pre-fill wick counts (harmless now — all fills sit on 5m boundaries).

## Status

M13 in flight (null gate passing at interim). Dives: 4 docs + 9 result rows delivered. Gated corpora
unchanged (dissent 527, resolved 2 clean). The runner-style red-team you asked for (3819f58e) is in
progress — SUPPORT/REJECT with answers to (a)(b)(c) in the next reply.
