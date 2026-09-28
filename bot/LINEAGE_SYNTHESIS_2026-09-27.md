# Decision-Lineage — synthesis (3-agent Fable swarm, 2026-09-27)

Goal the owner set: **trace every trade back to its "butterfly" — the first
domino that led to it.** Three read-only Fable agents scoped it while he slept.
Bottom line: **it's buildable now, and the permanent fix is small.** Details in
`LINEAGE_JOIN_GAP.md`, `LINEAGE_SUBSTRATE.md`, `tools/copilot/H4_H5_RETEST_RESULTS.md`.

## Verdict: yes, and here's the shape

**A tracer works TODAY via a fuzzy join** — measured 30/30 on recent closes: every
close matches exactly one trade-agent decision 24–36s before entry
(`LINEAGE_JOIN_GAP.md` §3). So we can render "why did this trade happen" for real
trades right now, without touching the running bot.

**The permanent fix is 7 additive, metadata-only steps** (`LINEAGE_JOIN_GAP.md` §2):
stamp the `pipeline_id` the bot already mints (`coordinator.py:1676`) through
`EntryDecision → entry_reasons → ledger`, and add `position_id`/`pipeline_id` to the
trade-event logs. Then a trade joins to its full 5-agent decision chain by exact key.
Stage for the next planned restart — do not restart for it.

**The single highest-leverage line-fix:** `signal_metadata` is *built* by
`coordinator._build_entry_snapshot` (`coordinator.py:2293-2335` — side, regime_1h/4h,
num_agree, stop_width_pct, is_toxic, setup_verdict, regime_wr) but **never written to
the log** (0/3,322 records). Persisting it makes the causal fields directly readable
per decision instead of reconstructed. Few lines (`LINEAGE_SUBSTRATE.md` §3.2).

## The causal chain we can already show (per decision)

trigger (first domino) → regime verdict → per-symbol strategy votes + confluence →
80-char thesis/outlook → gate/veto outcome → (on entry) confidence-vs-floor → the
self-performance/lessons context the LLM saw. **First-domino catalog:** since August
it's ~99% "lead-lag signal" or "cross-market divergence" — the bot essentially only
wakes up for those two triggers now (`LINEAGE_SUBSTRATE.md` §2).

## Corrections to the record (the moat working)

- **My earlier "couldn't find the NEAR decision" was a wrong-file error.** The
  decision existed in `agent_performance.jsonl` (the per-symbol entry log), not
  `decisions.jsonl` (trigger-path, portfolio-wide, no symbol/id). Three consumers
  make this same mistake, including the website reasoning feed.
- **My high-vol-shorts postmortem over-claimed** "the setup was internally conflicted
  / knew it should be a long." The real NEAR entry decision was unanimous go/approve.
  Corrected in `POSTMORTEM_HIGHVOL_SHORTS_2026-09-27.md`: the owner's instinct is
  supported by the **aggregate regime pattern**, not by that trade's decision.
- **Memory figures corrected by measurement:** under-logging is ~2.5x (not "~6x");
  `position_id` is 15.3% of ledger rows / 0% of trade_events (not "0/150k" everywhere).
- **Coverage ≠ span:** the liquidation feed has only **33 calendar days of data in a
  58-day span** (24-day box-move outage Aug 12→Sep 6). Every "56–57 day collection"
  claim — including the H3 doc — should read as span. H3's episode counts are real, but
  the doc needs this caveat.

## Two live bugs surfaced (separate from the tracer)

1. **Website reasoning feed is dead:** `api_server.py:1207/1262/1552`
   (`/v1/reasoning/feed`, `/v1/trade/{id}/trail`) filter for `pipeline_id`/`type`
   keys that exist only in `agent_performance.jsonl` but read `decisions.jsonl` →
   returns zero pipelines. Repointing the file (fix step S7) fixes it.
2. **Agent scoring is unfed:** `performance_tracker.score_trade(pipeline_id, outcome)`
   has no live caller, so per-agent accuracy never accrues regardless of the join.

## Honest state of the hypotheses after tonight

- **H3 (liq clustering): still the one real finding** — survives a local-rate null for
  **BTC / SOL / FARTCOIN**, dies for thin memes. Add the coverage-days caveat; the
  clustering result doesn't need continuous calendar coverage, but the "days" framing
  overstated. Cascade-risk (defensive), not direction.
- **H4 (OI buildup → cascade): NOT supported as pre-registered.** Cascade metric null
  in all terciles; one knife-edge vol-persistence cell on memes only. Forward hypothesis
  at best; do **not** feed OI state into any sizing/cascade logic on it.
- **H5 (session timing): refuted.** The US-session excess only exists at the locked gap
  and inverts at wider gaps — it's known vol-seasonality via partial-fill chop.

## Recommended order when the owner returns to the bot

1. Build the **stopgap lineage tracer** (fuzzy join, read-only) — visible value now,
   zero risk to the live bot. Turns any trade into its cause chain on demand.
2. Stage the **7-step `pipeline_id` stamp** + **`signal_metadata` persistence** for the
   next restart — makes the trace exact and permanent.
3. Fix the two live bugs (reasoning feed file, score_trade caller) — cheap, and the
   first one restores a website feature.
4. Only then revisit edge questions. H4/H5 are closed; H3 cascade-risk for the three
   liquid names is the one forward build with evidence.
