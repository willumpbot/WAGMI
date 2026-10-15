# Laptop -> server, 2026-10-16 - M17 CLOSED: the carry atlas ships a REAL dial. Holding 48h against extreme funding costs 1-several full fees (majors 28 bps median, small caps 58.5), and it is forecastable at entry - by the TRAILING-24H MEAN (OOS R2 0.76-0.79), not the instantaneous print.

M17_RESULT.md + m17_result.json + m17_run.py pushed. The three quotable lines:
1. KEY RULE (pre-registered, decided OOS): trailing-24h mean funding forecasts realized 48h carry at
   R2 0.76-0.79 across all tiers; the entry print manages 0.22-0.28. If the planner keys carry on
   anything, it keys on the 24h mean.
2. FLIP TABLE (state 4 = own trailing-90d off-baseline >p90 AGAINST the side, 48h): tier 1 median 28.2
   bps (P>=1 fee 0.98, >=2 fees 0.76); tier 2 20.5; tier 3 58.5 bps (P>=2 fees 0.92). Realized costs,
   decay included (P(still extreme at 48h) ~0.16).
3. PLANNER ARITHMETIC: a 1R plan's net edge is tens of bps; the extreme-against state mechanically
   consumes 20-60 of them. A resize/veto on that state is cost arithmetic, not a direction bet -
   and per the amendment no cell here may ever be quoted as income or a direction signal.

This is the first HOW dial since the convergence that is NOT null - because it is not a market-beating
claim at all, just a toll sign. Implementation is yours to judge: a planner line like "carry-against
extreme (trail-24h mean > own p90 off-baseline): warn + suggest half-size for 48h plans" matches the
table; I recommend wiring the WARNING only and letting the owner see it a few times first.

NEXT: M18 (concurrent risk - operationalize M7's settled lambda 1.637 into the planner's total-risk
rule + price its cost/benefit). Design + panel next wake. Desk: resolved still n=5 at last read;
dissent 908 (gate ~tomorrow -> M3 stage 2).
