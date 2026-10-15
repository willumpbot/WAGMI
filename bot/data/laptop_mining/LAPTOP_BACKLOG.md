# Laptop standing backlog (owner 10-15: "our laptop can hold all the firepower ... I want it to be overused, if anything")

Rule: the laptop is never idle. When a mission finishes, take the next one here without waiting for the server.
Owner priorities and server requests in SERVER_REPLY.md jump the queue. Standing rules unchanged: size/risk/exit/timing,
not direction; bps net of fees; seal before confirmatory reads; coin + day clustering; ORIG17 vs held-out; exploratory
labelled as such; late_logged rows excluded from every prereg population.

## Standing (continuous, every day)
S1. **Per-trade dives.** server_exports/dive_requests.jsonl gets one row per owner trade when it fills and per new
    watchlist coin. For each: the coin's own base rates for this setup, volatility profile, funding carry over the hold,
    BTC link (beta + R^2), liquidation clusters near the stop / +1R, what the conditional-exit rules (M13) favour. Write
    results to DIVES/<plan_id or coin>.md and a one-line summary into dive_results.jsonl (server shows it in the case file).
    Every dive ALSO covers (owner 10-15: "deep diving into position, funding, wallets ... other angles"):
    - **positioning**: open interest level + 4h/24h/7d change, long/short skew where available, OI vs volume (crowding);
    - **funding**: trajectory over the hold (not just the latest print), own-history percentile, carry cost of the plan;
    - **wallets**: the ~60 profitable HL accounts (whales_latest.json / whales_log.jsonl) - net position on this coin,
      recent adds/cuts, and whether their past positioning on this coin preceded bigger moves (size, not direction);
    - **book**: 1% depth and spread at entry and now (can the stop actually fill?); liquidation clusters near stop/+1R;
    - **other angles** worth one line each when the data exists (cross-exchange basis, BTC/ETH regime, calls on it).
    **Anti-overanalysis rule** (owner: "overanalysis is always a thing"): every dive ends in AT MOST 3 lines -
    (1) what matters for THIS trade, (2) what would change the plan (pre-stated, observable), (3) confidence.
    Nothing in a dive moves an exit by itself: insight goes to the owner, alerts and post-mortems; rules stay as set.
S2. **Post-mortems.** For every closed owner trade (cases/<plan_id>.json 'closed'): what the open-time read said vs what
    happened, which exit style won and why in terms of the M13 features. Accumulate into a running owner-style ledger.
S3. **Integrity.** Keep crunch j1-j7 green; any export that looks wrong -> ask the same hour.

S4. **Angle discovery** (owner 10-15: "there are no projects that can be left behind other than ones we did not think of").
    Weekly: inventory every stream in server_exports + every closed/refuted claim, cross them, and list angles NOT yet
    mined (stream x question x horizon). Top 10 by (data available now x decision value) go straight into this backlog.
    The server ran the first pass on 10-15 (ANGLE_MAP_2026-10-15.md).

## M29 - OWNER'S OWN WALLETS (runs on the LAPTOP; owner 10-15: "the laptop can handle HEAVY LOADS")
You hold the addresses (owner relayed them to you). Starter code: tools/hivemind/owner_wallets.py (public Solana RPC +
HL userFillsByTime/userFunding; Axiom perps run on Hyperliquid, so the Axiom wallet should have an HL address - find
it). Run it on the laptop with addresses in a local, never-committed wallets.json; replace the public RPC with
anything faster you have. Build: every swap/fill -> round trips (entry, exit, hold, PnL in SOL and USD at the time,
fees). Most of these wallets lose money - that is the point: they are the owner's labels. Then (a) S2-style
post-mortems by pattern (entry timing vs the pool's run, hold length, exit vs peak, size vs liquidity), (b) place every
trade on the M28 map, (c) join with archive/pool_trades + call_snapshots: was he before/after callers and smart
wallets, (d) the 3 habits that cost him most in R, each with n and CI. Addresses never leave the laptop and never
appear in any committed file; reports refer to "wallet A/B/C".

## M28 - JUMPS THE QUEUE (owner 10-15: "run our own trading decisions on already-mined conditions ... it should be
## identical to live trading")
**Policy replay = a paper twin of how WE trade, run over every moment we have data for.**
Rules exactly as live: stop = K x exp_move known at that moment, the owner's runner exit (exit_style.play: half at +1R,
1-ATR point-in-time trail, 48h), 0.5% risk cap, 9 bps fees + funding carry, entry at the next 5m bar (no same-bar fill).
Inputs must be POINT-IN-TIME: (a) logged live = scan_log / voices / venue_funding / depth_all / dissent_log (since
~10-08, honest by construction); (b) candle-derived conditions (exp_move, ATR, funding history, liq clusters) recomputed
bar by bar on the 178-coin archive back years. Every condition we have mined (funding_hot, flags, voice agreement,
waking_up, BTC regime, events) becomes a column on every simulated trade.
Outputs: (1) per condition, expectancy in R and bps of OUR rules vs a RANDOM-ENTRY control on the same coins/times
(the control is mandatory - it separates "the rules work here" from "the market went up"); (2) which conditions our
exits/stops/sizing fail in; (3) the replayed twin of every real owner plan and bot trade, side by side with what
actually happened - any gap = a simulator bug, fix before reading anything else (twin must match live first).
Owner 10-15: "rules like that only give us limited thought processes" - so M28 does NOT start from stated rules. It
maps the WHOLE space (every coin, every point, both sides, every condition) and lets the outcomes surface where our
machinery works. Then (4) place every real owner decision (plans, calls, watchlist adds, mentions) on that map: what
do his picks share that the rest of the map doesn't, and do picks with that profile replay better than his others?
His instinct is the label; the map explains it without him writing a rule. Fishing guard: many conditions = false
finds, so discovery on the early half / ORIG17, confirmation only on the sealed held-out half.
Not replayable honestly: LLM decisions (Claude ideas, bot agents) on past dates - the model may remember what happened.
Those are graded forward only. Direction is still not the claim: both sides are simulated at every point; the read is
where our rules' size/stop/exit machinery earns or bleeds. Seal the confirmatory split (ORIG17 vs held-out coins,
pre/post 2026-06) before reading results.

## Missions (in order, after M13)
M13. Conditional exit policy - which exit wins given what is knowable at entry (in flight).
M14. **Re-entry after a runner exits.** Owner asked "did we ever re-enter?". When a trail or time limit ends a runner
     while the move continues, does re-entering on a pullback (to the trail level / 20-EMA / prior breakout) pay vs
     staying out? Conditional on the same features as M13.
M15. **Stop placement vs liquidation clusters.** Stops just beyond the nearest cluster vs at it vs inside: stop-hit rate
     and expectancy on majors and high-vol coins (the hivemind already carries liquidation magnets per coin).
M16. **Limit-entry adverse selection.** Owner plans use limit entries at levels. Do filled limits underperform the
     same setup entered at market (fills happen when price is moving against the idea)? By distance of the limit from
     price in ATR.
M17. **Funding carry on holds.** Expected funding cost/credit over 24-72h by coin, side and funding regime; when carry
     alone flips a 1R plan's expectancy.
M18. **Concurrent positions (M7).** Correlation spikes -> how often same-side positions stop together; a concurrent-risk
     rule for the planner (total risk across correlated open plans).
M19. **Claude-idea features.** As ideas resolve: which idea features (setup, confidence, leverage_why, voices with/against,
     distance to levels) separate winners - interim only at the sealed n.
M20. **Voice agreement as a SIZE/stop input.** With full voice sets now on held coins: does voices-with-you minus
     against predict adverse excursion (MAE) or stop-hit probability (not direction)?
M21. **Expected-move refit (M3 follow-up).** Once dissent_log.jsonl has ~2 weeks, refit stage-2 with live-consistent
     inputs and retire the 0.8 haircut if the refit is calibrated.
M22. **Bot learning unfreeze (P1).** Shadow living gates in R/bps with recency weights (SERVER_EXPLORE A design).
M23. **Telegram calls at scale.** More callers (the caller test died at ~8 effective callers): which chats/callers to
     add, and the call-to-peak profile of calls that later did >= 2x.
M24. **Time-of-day for owner plans.** Entry-hour effects on owner plans and Claude ideas specifically (M6 used random entries).
M25. **Perp wallet mining (1,200 wallets).** server_exports/archive/wallets (hourly positions >= $5k: 1,000 skilled by
     all-time PnL + 200 random CONTROL, cohort files daily). Grade every wallet forward like a voice (did its adds/cuts
     precede bigger moves / its own PnL?); persistence of skill out of sample; cohorts by style (turnover, leverage,
     hold time, coin focus); skill-weighted net positioning per coin as a SIZE/risk input; crowding of skilled wallets
     near liquidation prices. Control group mandatory for every claim (skill vs "big wallets look smart in hindsight").
M26. **Solana thin-pool + wallet mining (calls).** server_exports/archive/pool_trades: every wallet that traded a called
     pool in the ~24h before the call and at +1h/+6h (GeckoTerminal trades, public). Questions: wallets repeatedly
     early (pre-call) in calls that later ran >= 2x (smart wallets) vs a control of random wallets in the same pools;
     pre-call accumulation patterns (buy clustering, new wallets, bundles) vs outcome; does a known smart wallet's buy
     predict continuation better than the call itself (forward-graded); pool microstructure at the call (reserve, buy/
     sell imbalance, holder count) vs outcome. Caller identities never leave the PC - if per-caller front-running needs
     testing, ask and the server ships an opaque per-run caller_cluster only.
M27. **Angle map sprint (ANGLE_MAP_2026-10-15.md section 3, the top 25).** Work the NOW and BACKFILL rows first, in the
     map's order: #3 funding premium/persistence, #6 LLM targets vs exp_move, #7 co-pilot forward ledger (due now),
     #24 near-miss reversion prereg (sealed 08-05, unread), #8 time-to-stop hazard, #9 level overshoot, #10 HAR error by
     listing age/liquidity, #20 owner stop/risk audit, #22 exit agent on owner plans, #23 ungraded mechanical gates;
     then backfills #1 events, #2 Deribit IV/skew, #4/#5 cross-venue funding + OI history. Same rules as every mission
     (seal before confirmatory reads, size/risk not direction, bps net of fees, day + coin clustering).
     New server collectors for the COLLECT rows: archive/venue_funding (HL/Binance/Bybit funding per hour + HL OI-cap
     list, every 15 min: #4 live and #19). Newly exported (5b): signal_value_tracker, trade_reflections, veto_tracker,
     calibration_observations, nearmiss_reversion_log, copilot_alerts.log, voice_grades, accumulation_log,
     owner_plan_reviews, owner_watchlist, watch_log, state_transitions.csv.

