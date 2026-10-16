# M25/M26 first read (1,200-wallet cohort stream) - DESCRIPTIVE positioning, NOT a skill claim. Headline needs the eqw caveat: by DOLLARS the skilled cohort looks net-short majors, but that's a FEW WHALES - by WALLET COUNT skilled are ~evenly split (even majority LONG BTC). Skill requires a FORWARD realised-P&L test (snapshot upnl is selection-biased + regime-driven).

_2026-10-16. m25_wallets_firstread.py. today/wallets.jsonl.gz + archive/wallets/2026-10-15. 23 hourly
snapshots; latest = 3,724 positions (skilled 611 wallets/$4.8B notional; control 51 wallets/$56M)._

## Positioning (latest snapshot) - BOTH views, because they disagree
- VALUE-WEIGHTED (dollar-net): skilled net SHORT every major - ETH -$491M, BTC -$486M, SOL -$166M;
  control net LONG the same. Looks like "smart money is bearish."
- EQUAL-WEIGHTED (wallet count): BTC 95 short / 121 LONG (56% long!); ETH 86 / 89 (~even). And the
  dollar-net-short is CONCENTRATED: top-3 wallets = 55% (BTC) / 61% (ETH) of the gross short notional.
- SO: the net-short is a FEW BIG SHORT WHALES, not a cohort consensus. The typical skilled wallet is
  ~neutral-to-long majors. Reporting "skilled are short" from the dollar-net alone would be misleading.

## upnl snapshot (FLAGGED - not a skill measure)
skilled sum -$22M (median +$82, 52% green); control -$5M (median -$121, 47% green). Both negative
(regime). upnl is UNREALISED + regime-driven + the cohort is PAST-PERFORMANCE-SELECTED -> cannot read
skill from it.

## The real study (forward) + caveats
- SELECTION BIAS: "skilled" = past winners; their current positioning isn't validated as predictive.
- The only honest skill test: track each cohort's FORWARD REALISED close P&L from here, skilled vs
  control, day-block CI, with the cohort definition frozen BEFORE this window (not circular). n accrues.
- Decide the weighting a priori: dollar-weighted = "follow the whales"; equal-weighted = "cohort
  consensus" - they give OPPOSITE reads here, so the choice matters and must be pre-registered.
- Whale concentration means a handful of wallets drive any dollar-weighted signal - a per-whale dive
  (who are the top-3 BTC/ETH shorts, are they consistently right) may be more useful than the cohort.

## Rule (one line, honest)
The wallets we tag "skilled" are NOT uniformly bearish - a few big ones hold large shorts, but most are
about even/long. No tradeable read yet; it needs weeks of forward results to see if they actually predict.
