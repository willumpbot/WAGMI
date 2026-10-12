# Syndicate: can we tell winners from duds at call time?

PREREG.md sha256 `1c07304cadd1ce2e89c3183ee903ff0f5c1ea76a7ef76f7abac48bef6ab27d4b` (written before any feature was joined to an
outcome). Code: build.py, analyze.py (pre-registered), explore.py (EXPLORATORY, owner request). Local only.
Written by server Claude from the study agent's returned report (the agent could not write files), 2026-10-12.

## 1. Plain answer
- **Winners: no, not reliably.** Nothing knowable at the moment of a call picks out the coins that go 1.5x within a day.
  Patterns that look strong in the first 4 weeks all vanish in the last 3 weeks.
- **Duds: partly.** Small, thin coins die far more often: under ~$100K mcap or ~$15K liquidity at the call went to
  ~zero (or had no tradable market) ~70% of the time vs ~35% for bigger coins. Held up in the later weeks.
- But small coins win the 24h 1.5x race just as often (later weeks), and every filter threw away most 3x+ winners.
  The money sits in a handful of calls (top 5% = ~60% of all upside): HOW you trade (fast take-profit) matters more
  than WHICH call you pick.

## Data
313 Syndicate first-calls 2026-08-24 -> 10-08; n = 300 used (13 unpriced = our fetch failed, excluded as unknown).
Dead coins kept (45 no pool, 35 no trade in 1h) = MISS and DUD. Discovery 166 (before 09-20), holdout 134.
Base rates: HIT24 (1.5x on highs within 24h) 39.7% (laptop ~38%); DUD (7d <= -80% or dead) 59.4%; BIG (7d peak >= 3x) 18.3%.
Call-time stats from the Phanes bot card (278/300, median lag ~1 s).

## 2. Results
HIT24, 17 features: only "24h change > +94%" passes Holm on discovery (p 0.02); fails holdout (+0.10 [-0.12,+0.27]).
Nothing survives holdout. Holdout MDEs 0.2-0.4: a ~10-point effect could hide; a large stable edge is ruled out.

DUD survivors (one factor: coin size/maturity, not four findings):
| feature (high half) | discovery | holdout |
|---|---|---|
| older (age_min) | -0.26 [-0.42,-0.10] | -0.26 [-0.47,-0.08] |
| bigger mcap | -0.33 [-0.49,-0.19] | -0.26 [-0.39,-0.13] |
| deeper liquidity | -0.40 [-0.55,-0.25] | -0.29 [-0.43,-0.16] |
| higher mcap/liq | -0.29 [-0.44,-0.13] | -0.26 [-0.42,-0.10] |
Part mechanical: very thin coins often have no trade in the first hour (counted as dud).

## 3. The one rule: FAILS
"mcap/liq > 6.47 AND within 37.7% of ATH" (best of 38): discovery 72% vs 38% base; holdout 55% vs 42%, lift +0.13
[-0.13,+0.33], recall 20%, threw away 21 of 29 (72%) of 3x+ winners. 72 tries total.

## Exploratory (not pre-registered)
(a) Caller form (last 5 known outcomes, no lookahead): hot (3+/5) 49% vs cold (0-1/5) 36%, +13 pts [-5,+35]. No
mean reversion; weak hint of persistence, unproven. Hot form does not reduce duds. CALLER_15X_PREREG forward test decides.
(b) Upside concentration: top 5% of calls = 60% of 7d peak upside (one coin 15%). Buy-and-hold 7d: mean -40%/call,
-74% without the top 5%; top 5% = 96% of positive hold returns. Holding is a lottery ticket on 1 coin in 20.
Liquidity terciles (exploratory): <$8K HIT24 27% DUD 72%; $8-20K 39%/79%; >$20K 52%/32%.

## 4. Limits
Small n (300 calls, 46 days); 13 unpriced holdout calls; HIT24 is on wicks (optimistic for fills); entry = call minute;
Phanes fields parsed from 300-char truncated text (holders not tested); one chat, one regime; live card_at_call was
almost always empty (fixed going forward by call_snapshot.py). caller hash is pseudonymous to anyone holding the chat.
