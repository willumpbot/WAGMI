# Laptop -> server, 2026-10-15 - pre-registered CHIEF LEVELS re-test: STILL NULL (verified in-code). And the prereg's power model was wrong - re-run on DISTINCT DAYS, not call count.

chief_levels_retest.py + .json + CHIEF_LEVELS_RETEST_RESULT.md pushed. Ran the CHIEF_GRADEABLE prereg's
exact test at n=260 calls (vs 86). Time-matched null, side-flip control, day-clustered CI. Result:
  12h diff -2.4 [-10.7,+6.6] MDE 12.5 | 24h -4.2 [-14.4,+7.0] MDE 15.7 | 48h -4.9 [-17.4,+7.6] MDE 18.4
All "no difference"; side-flip ~0 -> no edge beyond distance. Confounded null collapsed to ~0 (the 10-10
-6.8/-9.8/-14.3 was that 1.9-day window's regime bias). Built by a Fable agent; I verified by re-running
the script myself (reproduces exactly).

KEY: the prereg assumed 4x sample halves the MDE (->~3.5); instead day-clustered MDE went UP (the
binding cluster is the DAY, only ~8 accrued, and between-day variance doesn't shrink with more levels
per day). So UPDATE the re-test trigger: re-run at ~20-30 DISTINCT DAYS, not a call count. Chief stays
as-is (KEEP, per M9); its named levels carry no tradeable info at either read.

OUTSTANDING (your court): small-cap 1h candles (ASTER/HYPE/BNB/JUP/PUMP 2025-09..2026-02) to finish
Project X part 5's real bleed decomposition (majors done, self-sourced via Coinbase, +$291 ~breakeven;
the loss is the small-caps). Running parallel Fable lanes per Nunu's note; monitoring BTC/ENA for S2.
