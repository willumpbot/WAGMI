# Syndicate: can we tell winners from duds AT CALL TIME? - pre-registration

Written 2026-10-11 BEFORE any feature was joined to any outcome. Seen beforehand: status counts of
caller_calls_graded.jsonl (188 graded / 42 no_pools / 23 no_market_at_call / 60 too_recent), calls per
day, the Phanes_bot card format, and the earlier syndicate_study.json exit-rule results (no features).
Anything below not listed here is labelled EXPLORATORY in the report.

## Universe (fixed)
- Every Syndicate 2.0 first-in-chat call (as selected by tools/hivemind/caller_grade.py) between
  2026-08-24 and 2026-10-08 22:00Z: 313 calls, INCLUDING bot-first posts, no_pools, no_market_at_call
  and too_recent rows (the latter priced now from GeckoTerminal, cached under study_duds/gt_cache).
- No call is dropped for missing price data: no_pools / no_market_at_call = MISS and DUD.

## Outcomes (fixed)
- PRIMARY  HIT24 = the max candle HIGH in (entry candle, call + 24h] >= 1.5 x entry.
  Entry = close of the first 1-minute candle at/after the call minute (same as caller_grade.py).
  Path = 1-min candles for ~16.7h then 1-hour candles (hourly highs may slightly overstate fillability).
  Dead/unpriced pools count as 0.
- SECONDARY DUD = ret_7d <= -80% OR no_pools OR no_market_at_call. If 7 days have not elapsed and the
  pool is alive, DUD = NA (excluded from the secondary only).
- BIG = 7-day peak >= 3x entry (for calls < 7d old: peak to date, flagged).

## Split (fixed, time-ordered)
- DISCOVERY = calls with ts < 2026-09-20T00:00Z (first 27 of 46 calendar days ~ 60%).
- HOLDOUT   = calls with ts >= 2026-09-20T00:00Z. Holdout is scored ONCE.

## Features (knowable at the call; 17, the whole list)
Card = the first Phanes_bot info card for the CA posted within 10 min after the call (it is the bot's
reply to the call, so it reflects the call moment). Missing feature -> that call excluded from that
feature's test only (n reported).
 1 age_min (GT first pool creation -> call; fallback card age)   2 mcap (card MC)
 3 liq (card LP)            4 mcap_liq = MC/LP           5 vol_liq = card Vol / LP
 6 bs_ratio_1h = buys/sells in last 1h (card)            7 txns_1h = buys+sells (card)
 8 chg_1h (card 1H %)       9 chg_24h (card USD (+x%))   10 below_ath = % below ATH (card)
 11 runup_6h = price change over the 6h before the call (GT hourly closes)
 12 us_hours = call hour UTC in [13,21)                  13 weekend (Sat/Sun UTC)
 14 caller_prior = shrunk prior HIT24 rate of the same sender over calls whose 24h outcome had
    RESOLVED before this call: (hits + 5*p_chat_prior)/(n + 5); p_chat_prior = chat HIT24 rate over
    resolved calls before this one. No lookahead.
 15 bot_first = first poster of the CA in Syndicate is a bot (handle ends in 'bot')
 16 xchat_prior = CA was mentioned in the DTN/DTN Hitters chats before this call (0/1)
 17 views = card eye count (Phanes look-ups)

## Tests (fixed)
- Univariate: each feature split at its DISCOVERY median (binary features: 1 vs 0). Effect = HIT24
  rate(high) - rate(low). 95% CI by day-clustered bootstrap (2000 resamples of calendar days).
  MDE (80% power, 2-sided 5%) = 2.8 x bootstrap SE. Multiplicity: Holm over 17 tests on discovery.
  Same for DUD as secondary (reported, not used for rule choice).
- "Survives holdout" = same sign on holdout AND holdout 95% CI excludes 0.
- ONE rule: candidates = all 2- and 3-condition AND-filters over the 4 features with the largest
  |discovery effect|, each condition at the discovery median or the favourable tercile edge
  (24 two-condition + 32 three-condition = 56 candidates, counted). Pick the max discovery HIT24
  precision among candidates selecting >= 20% of discovery calls. Score ONCE on holdout: precision vs
  holdout base rate (day-clustered CI of the difference), recall, share of BIG winners discarded, and
  DUD rate inside vs outside the filter.
- Total tests counted for multiplicity: 17 (univariate HIT24) + 17 (DUD) + 56 (rule search) = 90.
