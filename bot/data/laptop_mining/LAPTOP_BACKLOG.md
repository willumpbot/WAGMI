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
S2. **Post-mortems.** For every closed owner trade (cases/<plan_id>.json 'closed'): what the open-time read said vs what
    happened, which exit style won and why in terms of the M13 features. Accumulate into a running owner-style ledger.
S3. **Integrity.** Keep crunch j1-j7 green; any export that looks wrong -> ask the same hour.

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
