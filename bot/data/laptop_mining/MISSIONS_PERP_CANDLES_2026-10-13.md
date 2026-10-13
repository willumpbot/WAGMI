# Laptop missions — perp candle mining (2026-10-13, owner away all day)

Owner (10-13): "set our laptop up to do intensive candle data mining for our leverage/perp trading ... extremely long,
hard, challenging data processes to obtain and understand information we may not have fully pathed through yet."

## Ground rules (same as always, restated so nothing drifts)
- Direction is not the target. ~98 direction tests and 8,340 graded rounds say no. Every mission below is about
  **size, risk, stops, exits, and timing of magnitude** — the places where we HAVE found real, replicated effects.
- Unit: **bps of notional net of fees** (9 bps round-trip taker unless stated) — never dollars, never R alone.
- Every confirmatory read is **sealed first** (prereg SHA, read-not-before), clustered by **day** (and by **coin** where
  coins dominate), placebo/no-edge control that can fail, MDE stated before reading. Use the same discovery / held-out
  coin split as PREREG_FUNDING_WIDE (ORIG17 vs NEW156) so every finding gets a built-in replication.
- Exploratory sweeps are fine and encouraged — label them EXPLORATORY and do not let them reach a card above HYPOTHESIS.
- Candles: HL 5m/1h/1d across all ~178 perps (your j5 backfill + server_exports/candles_5m). Exclude n==0 backfill bars
  for anything volume-based; real HL trading starts 2023-02-26 for BTC/ETH.
- Long jobs: resumable, checkpointed, one heavy process at a time, log progress to crunch/STATUS so the server can see
  liveness. If a mission's data isn't on your disk, put the request in your reply and move to the next mission.

## Queue (in order; each is hours of work)

**M1 — Exit-policy library on perps (the owner's open "who manages the exit" question, answered with candles).**
Random-time entries on all 178 coins, BOTH sides (direction is null, so this isolates the mechanical cost/benefit of
each exit rule), stops sized off the fitted HAR exp_move (K = 1.0..3.0). Exit rules: fixed target 0.5-3R; time stops
4-72h; partial at 1R + runner with trail (ATR / chandelier / HAR-scaled) — the owner's "take some, hold some toward the
runners"; breakeven moves (refuted once — re-test on perps with fees); hands-off to the plan's own stop/target.
Report expectancy, P(ruin-ish), max adverse excursion, and fee drag per rule; then apply the top rules to the bot's
REAL entries (trade_events / ledger) and to owner plans (owner_fills / plans.json). Deliverable: a ranked exit table
+ a sealed prereg for the 1-2 survivors. Answers: does "Profits only" beat "bot manages" beyond the n=1 BTC short?

**M2 — "Profits only" counterfactual across every executed trade (owner asked 10-12).**
For every bot trade and owner-plan execution, replay the alternative exit modes (profits_only / hands_off /
bot_manages-as-happened) on 5m bars from the actual fill. Paired by trade, in bps; day-clustered. Pure data mining,
then feed the result into M1's prereg as the live-population check.

**M3 — Joint HAR refit (fixes D3 at the root).** One fit producing stage-1 betas + stage-2 coefficients + ONE matching
smearing, using only inputs that exist live (realized funding as live sees it, the live dissent definition, closed bars
only). Walk-forward by month, QLIKE vs the current model and vs naive; deliver coefficients + calibration deciles so
the 0.8 top-quintile haircut can be retired or re-estimated. This becomes the canonical exp_move.

**M4 — funding_hot sizing with an ECONOMIC objective (K* follow-up).** On held-out coins: widen-the-stop vs
size-down vs both, judged on expectancy and drawdown per unit risk (not exceedance parity). Prereg first.

**M5 — Tail / cascade risk for leverage.** P(|1h move| > 3x expected) conditional on liq bursts, OI change, funding
extremes, depth thinning, BTC shocks. Output: a recalibrated safe-leverage table (rolling, fat-tail aware) and which
conditions should cut leverage. Magnitude only.

**M6 — Intraday magnitude seasonality.** Hour-of-day / weekday / funding-hour (00/08/16 UTC) |return| profiles per
coin; does stop-hit probability depend on entry hour holding exp_move fixed? (stop placement + entry timing, not
direction). EXPLORATORY first, prereg only what survives the held-out coins.

**M7 — Correlation spikes as portfolio risk.** When cross-coin correlation jumps, how much more often do two same-side
positions stop together? Sizing rule for concurrent positions.

**M8 (low priority) — the July "0.60 floor killed proceeds" claim.** Server note 10-13 says it was very likely
metabrain-only. Confirm or refute from the July decisions.jsonl gate records if you have them; otherwise ask.

## What the server will do meanwhile
- Keep exports flowing hourly (candles_5m for the 6 bot coins, conf_floor, funding/OI, depth, liq, ledgers).
- Watch the newly enabled risk clamp (RISK_CAP_HARD_CLAMP=true, LIVING_EDGE_MULT_CAP=1.0 live since 2026-10-13 17:35Z)
  and report every [RISK-CLAMP] / [RISK-CLAMP-BLIND] / RISK-CLAMP-SKIP line.
- Answer data requests the same wake they arrive.
