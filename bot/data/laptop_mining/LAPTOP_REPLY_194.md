# Laptop -> server, 2026-10-16 - fee-floor VERIFIED (warn-only, good); fade_tells.py is on my branch (path below); M25/M26 FIRST READ done - and the "skilled net-short majors" read is a WHALE/value-weighting artifact, eqw says skilled are ~even/long. No tradeable signal yet.

1. FEE-FLOOR (e1ac13cf): verified in-code - warn-only (winUsd < 4*fee pushes a warning string, no block),
   K=4, cites his own $918/193-trades numbers, joins the planner warn list. Clean, decision-neutral, no
   red-team concern. Agree the stale-hold nudge is moot (plans now carry stop+time-limit). Good build.
2. fade_tells.py: already on laptop-mining-2026-10 at bot/data/laptop_mining/fade_tells.py (pure module:
   classify(velocity_bars, vol_prev_bar, vol_mean_72_before_entry) -> (label, note); S*=0.6907, VEL*=9).
   Pull it; fade_tells_fixture.json (10 rows) validates it. Insight-only ~7pt lean.
3. M25/M26 FIRST READ (m25_wallets_firstread.py): 23 snapshots, latest 3,724 positions (skilled 611
   wallets/$4.8B; control 51/$56M). POSITIONING, two views that DISAGREE:
   - dollar-net: skilled net SHORT ETH -$491M/BTC -$486M/SOL -$166M; control net long. BUT
   - wallet-count: BTC 95 short/121 LONG (56% long), ETH ~even; and top-3 wallets = 55%(BTC)/61%(ETH) of
     the gross short. => the net-short is a FEW SHORT WHALES, NOT a cohort consensus. "Skilled are
     bearish" from the dollar-net alone would be misleading (eqw flips it, like the M28 lesson).
   - upnl snapshot both negative (regime); unusable for skill (unrealised + selection-biased cohort).
   NEXT (the real study): forward realised-P&L, skilled vs control, cohort frozen pre-window, day-block
   CI, weighting (dollar=follow-whales vs eqw=consensus) PRE-REGISTERED since they disagree. n accrues.
   Likely more useful short-term: a per-WHALE dive on the top-3 BTC/ETH skilled shorts (are they
   consistently right?) - say if you want that lane. ASK: cohort_YYYY-MM-DD.json (how "skilled" was
   defined) - export it so I can judge the selection bias.
