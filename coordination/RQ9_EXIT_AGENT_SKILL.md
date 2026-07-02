# RQ9 — Exit-Agent Skill Audit: does the LLM exit agent add dollars over mechanical exits?

**Date:** 2026-07-02 · **Standard:** THE_STANDARD.md v1.3 (denominators, era-splits, adversarial pass, fragility, small-n humility)
**Script:** `bot/tools/research/rq9_exit_agent_score.py` · **Artifacts:** `rq9_results.json`, `rq9_full_output.txt`, `rq9_candles_15m.json`
**Data:** `bot/data/logs/exit_decisions.jsonl` (610 records, Jun 1 – Jul 2), `exit_regret_scores.jsonl` (55), `trade_ledger.csv` (qty join). Price truth: HL candleSnapshot 15m (fetched fresh, Jun 1 – Jul 2, all 5 symbols, no gaps).

## VERDICT: WASH, leaning slightly negative — but the June "0/71" blanket-block is now over-calibrated for what the agent actually says in E3.

Net applied agent value @24h vs mechanical null (matched-qty, all applied actions): **−$346** — and that is carried by a single bad call (ETH close 2026-06-02, −$1,164 counterfactual). Remove it and the agent is +$800-ish. Nothing here survives fragility in either direction. The agent neither redeems nor damns itself in dollars; its *advisory accuracy* in the current era is real but small.

## Method (the null that matters)

- 599 LLM calls scored ([LLM-EXIT] prefix; 11 mechanical tightens excluded): **504 close** (74 applied / 430 blocked), **50 partial** (25/25), **45 tighten_sl** (41 applied).
- **NULL baseline = pure mechanical geometry**: from each decision timestamp, simulate the position's recorded SL/TP2 forward on 15m candles (SL-first if both touch in one candle); if neither hits by horizon, mark price at +6/12/24h. `close_value = −(hold outcome)`, so positive = closing beat holding. Tightens: simulate new-SL path vs old-SL path over 48h.
- Dollars via qty joined from `trade_ledger.csv` (matched 501/595 scored calls). Episode dedup: first call per (position, action) — the agent repeats "close" every ~3 min while blocked, so per-call n is inflated ~6× (430 calls → 72 episodes).
- **Instrumentation gap:** `hold` decisions are NOT logged (0 records). We can score what the agent said, never what it declined to say. Cannot compute a true hold-accuracy rate.

## Results by action (episodes unless noted)

### Full closes — APPLIED (n=74): a coin-flip, not a 0/71 disaster and not a skill
| Horizon | Correct (close beat hold) | Mean cf | $ (n=67 matched) |
|---|---|---|---|
| 6h | 38/74 (51%) | −0.24% | −$1,043 |
| 12h | 38/74 (51%) | −0.43% | −$1,057 |
| 24h | 42/74 (57%) | −0.23% (median **+0.60%**) | −$765 |

Fragility: without the single worst call (ETH SHORT closed 06-02 10:18 before a big favorable move), 24h sum flips to **+$399**; without the best, −$1,244. Era-split: E1 −$969, E2 **+$220**, E3 −$15 (n=19, ≈$0). **The historical "0/71, −$1503" measured realized PnL of cut trades, not the hold counterfactual — by counterfactual the closes were ~51-57% right and roughly a wash.** The block was built on the wrong denominator.

### Full closes — BLOCKED (n=72 episodes, 430 calls): the agent's advice was directionally GOOD, but blocking it cost little
- Per-episode 24h: **52/72 (72%) correct**, mean +0.54%, $ sum **+$860** (= what blocking cost).
- E3 (Jun 23 – Jul 2, the current bot): 81% correct per-call at 24h, 35/55 episodes at 6h — but **E3 dollar cost of the block is only +$146 over 38 matched episodes (~$4/episode)**, robust to removing the best (+$128). The big block-costs are two June HYPE LONG episodes (+$394, +$355) — remove the top two and the all-era figure collapses to +$112.
- Why so cheap despite high hit-rate: when blocked, the agent falls back to partials + SL-tightens on the same position (THESIS_AUDIT 07-01 case), so the effective exit was already half-agent-managed. The pure-mech null overstates the block's cost.

### Partials (n=25 applied / 25 blocked)
- Applied: 15/25 (60%) correct at 24h, $ +$29. A wash with extra fee drag (~0.045%/side not netted here — would eat most of it).
- Blocked partials "96% correct" is an artifact: 25 calls = **2 positions** (18 XRP, 7 ETH bursts, Jun 30 – Jul 1). n=2. Dismissed per small-n humility.

### SL-tightens (n=41 applied): the one genuinely defensible skill, still fragile
- Classes: **27 protective / 11 wash / 3 premature**. Episode mean **+0.64%** vs old-SL null.
- $ sum +$390, but without the single best (HYPE 06-03, +$267) → **+$123**; single worst premature (SOL SHORT 06-04, hard-block-driven tighten) cost −$349 alone.
- Era-split: E1 +0.39% (n=15), E2 −0.52% (n=5), **E3 +1.05% (n=21, 18/21 protective, 0 premature)**. E3 tightens are the agent's best current behavior — but n=21 with one month of range regime; do not graduate (n<15 per era on clean split of E2).

### Corroboration from the existing regret scorer
`exit_regret_scores.jsonl`: 26/33 mechanical SL closes "recovered" within 4h, mean regret +0.61%. The mechanical null itself exits badly in this chop — consistent with the agent's blocked close/exit advice grading well against it without that meaning much in dollars.

## Where specifically (episodes, 24h)
- **Winners vs losers:** on positions in profit at decision time, close advice 61% correct, +$1,430 — but −$479 of that is one HYPE call; +$951 without it. On losers: 69% correct but **−$1,306 in dollars** (right often, catastrophically wrong when wrong). The agent is better at taking profit than at cutting losses — the opposite of what the block assumes.
- **Reason buckets:** `thesis_invalidated` is the best signal (63% @24h, +$993); `regime_mismatch` decent (76%, +$481); `panic_regime` 0/2 −$360 and `time_stop` −$547 are the money-losers. The agent's stat-laden reasons ("X% WR n=Y") — `historical_stats` bucket — are a coin flip (60%/48%/60%), consistent with the Quant-Brain-suspect finding that injected WR stats are noise.

## Adversarial self-check (what would kill this)
1. **Sign conventions audited** (positive = agent's action beats null) — spot-checked 3 records by hand against candles.
2. Blocked-close value assumes pure-mech continuation; actual positions got agent partials/tightens → true block cost is **below** the +$146 E3 estimate. Strengthens "wash".
3. Applied-close counterfactual truncates at 24h; 20 calls unresolved at 24h (data edge). Median (+0.60%) vs mean (−0.23%) gap shows fat-tailed single-trade dominance — the defining feature of this whole dataset.
4. Fees/slippage not modeled; would shave partials and add ~0.05% to every applied close's cost. Direction: more negative, still within wash.
5. Every headline number fails the remove-best-trade test except E3 blocked-close cost (+$146→+$128) and E3 tighten protectiveness (18/21) — the only two claims allowed to survive, both small.

## Recommendations (evidence-grade, not shipped — bot code is read-only for this agent)
1. **Log `hold` decisions** in exit_decisions.jsonl — the biggest measurement hole; the agent cannot be scored on its most frequent output. Week-1 artifact: hold-accuracy table.
2. Keep the full-close block **for losers**, open it **for in-profit positions with `thesis_invalidated`/`regime_mismatch` reasons** — that cell is where advice graded 72-81% and the block costs real (if small) money. Flag-gated, watch 15-20 closes.
3. Keep tightens as-is (E3: 18/21 protective, 0 premature).
4. Strip injected WR stats from exit prompts or fix their provenance (§3b) — `historical_stats`-reasoned calls are a coin flip.
5. Re-run this scorer after ~30 new episodes; every surviving claim here is n≤38.

**Killed hypothesis logged as a win:** "The exit agent's holds/partials/tightens redeem the 0/71 closes" — NO in dollars (net −$346 @24h, wash after fragility). Also killed: "the 0/71 proves the agent destroys value" — the counterfactual says its closes were ~55% right and ~$0; the 0/71 was a realized-PnL denominator error.
