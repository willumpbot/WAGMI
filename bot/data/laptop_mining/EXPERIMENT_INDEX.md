# What was tried, and what happened (mission 2)

_Compiled 2026-10-08 from the surviving project memory: 154 memory files (2026-03-22 → 10-04)
and 2,272 prompts in `~/.claude/history.jsonl`. **Source caveat:** the handoff asks for
`~/.claude/projects/*/*.jsonl` transcripts. Those are **gone** — 0 files survive except today's
session. The memory layer is a distillation written at the time, so it records what each session
*claimed*, which for this question is close to ideal: a claims ledger._

---

## Headline

**Every edge this project ever claimed was refuted by forward data. Every bug it ever fixed was
real. The archive is a 3-month record of in-sample numbers that did not survive contact with the
future — and it ends, on 2026-04-30, with a live account liquidated at −$2,186 by a configuration
that had backtested at 75% win rate and delivered 27%.**

The pattern repeats so cleanly it is effectively a law of this codebase:

> big in-sample number → deploy → forward data contradicts it → "root cause identified" →
> new fix → repeat.

What survived was never an edge. It was always a **mechanical bug fix** — wrong stop multiplier,
wrong Kelly, 100× fee error, win-rate thresholds centred on the wrong baseline. Those held.
The alpha claims did not, not once.

This is the strongest possible independent justification for the server's current discipline
(forward-grading only, n ≥ 13, CI must exclude 0, "say plainly when there's no edge"). That
discipline was bought at a price of at least $2,186 plus three months.

---

## The refutation ledger

Claims that were tested later and failed. Dates are when the claim was made.

| Date | Claim | What actually happened |
|---|---|---|
| 03-22 | "HYPE BUY 88.6% WR edge"; PF 1.81 → 3.30 | HYPE became the single worst symbol. By 04-28 the curator logged HYPE_SHORT −$5,592; by 04-29 HYPE lost $5,983 over 341 trades. The server's Oct scorecard lists HYPE GOs at −41 bps. |
| 03-25 | "HYPE_BUY validated at 94% WR (49 trades) against real OHLCV" | Same. Never reproduced forward. |
| 03-29 | "Bot running at 25% of Kelly-optimal leverage" → raise it | **Reversed in 2 days.** 03-31: "FULL_KELLY_LEV was 19.5x when actual Kelly = 7.8x. Every trade was 2–3x overleveraged, triggering CB cascade." |
| 04-03 | "90–100% confidence is ANTI-predictive (22.7% WR). 85–90% is the sweet spot (74.7% WR)" | The server's Oct grading: trade-agent confidence AUC **0.486**, Spearman −0.045 — uninformative, not inverted-with-a-sweet-spot. The 2026-04 structure was noise. |
| 04-05 | "BTC alone with simulated LLM agents: $500→$976, Sharpe 2.54, 10:1 payoff. Adding other symbols only hurts" | Simulated agents. Never reproduced with real ones. |
| 04-05 | "BB is the only profitable strategy. Solo BB > 2-agree" | Superseded repeatedly; by 04-29 solo-strategy relaxation was proven harmful (below). |
| 04-28 | "100% WR on 6 trades over year proves gates are too aggressive" | **n = 6.** The server's current rule — flag anything n < 13 — exists because of reasoning like this. |
| 04-28 | "Data-driven mechanical gates → +$3.2k swing (−$1.3k to +$2k)" | Contradicted the *same day* by the n=6 claim above, which argued the opposite direction. Both shipped. |
| 04-29 | "Solo gate relaxation: regime_trend +504% alpha, monte_carlo_zones +150%" — deployed | **Refuted the same day:** "Post-deployment 60-day backtest revealed gate relaxation was HARMFUL. 802 trades, −$3,836 net P&L." Reverted to symbol-specific gating. |
| 04-30 | Phase 3.2 autonomous deployment, backtest target 75% WR | **"Catastrophically failed. 205 trades at 27% WR. Account liquidated (−$2,186)."** |
| 05-07 | TIME_STOP reduced 2h → 1h to unblock 95.6% signal blockage | July's swarm later concluded the opposite — TIME_STOP should go 2h → **48h**. The desktop has since kept it at 2. Three directions, no resolution. |
| 06-09 | "First OOS-validated profitable alpha: SELL at ADX>60 + wide stop" | Became July's swarm input. The desktop's Sept/Oct ledger analysis **rejected** the associated confidence-floor change: conf<55 was profitable (+$0.29/tr, n=12) while conf 55–80 lost −$117.69 (n=79). |
| 07-19 | Swarm: raise ENSEMBLE_CONFIDENCE_FLOOR 55 → 80 | Rejected by the desktop on live-ledger arithmetic; the 55 default was a **dormant silent gate** (runtime floor was 20 all along). |

**Independent corroboration from this laptop's own data (mission 1):** the counterfactual
gate families come out at `confidence_floor` −0.017 [−0.174, +0.140] and `trend_adj_floor`
−0.010 [−0.315, +0.300] — both no-signal, on a period two months earlier. The confidence
floor never had an edge at any point in this project's history.

---

## What actually held up

All of these are **bugs**, not edges. This is the project's real yield.

| Date | Fix | Why it was real |
|---|---|---|
| 03-31 | Kelly leverage 19.5x → 7.8x | Arithmetic error; every position was 2–3× oversized. |
| 04-05 | `sl_atr` profile was 0.55x while strategies set 2.0x | Stops sat inside the noise band. Called "the #1 mechanical loss cause". |
| 04-11/12 | **Win-rate thresholds centred on 50% for a 35%-WR system**, across 12 files | Every feedback loop was scoring a profitable-but-low-WR system as failing, and suppressing exactly the behaviour it should reinforce. The single best structural insight in the archive. |
| 04-12 | Only 79 of 1,298 signals (6%) reached the LLM; 18 pre-LLM quality filters | Architectural, verifiable, not a performance claim. |
| 04-20 | ML snap model overfit to sin/cos hour features — emitted 0.002 for every input in two UTC bands | Caught by inspection, not by backtest. |
| 04-25 | 61 runaway processes; added locking + clean entry point | Operational. |
| 05-06 | "All 3 automated execution paths disabled by config" | The bot had not been trading at all. |
| 05-13 | **100× inflation bug in `fee_drag`** (`ensemble.py:2631`) | Every fee-aware decision before this date was computed on numbers 100× wrong. |
| 06-08 | "Prior session numbers were buggy" — corrected baseline to −18% / 32% WR | An explicit retraction of the earlier optimistic baselines. |

Note the dependency: the 05-13 fee bug means **every edge claim made before 2026-05-13 was
computed with a 100× fee error.** That alone invalidates the March–April alpha ledger, independent
of everything else.

---

## Three structural failure modes worth naming

1. **In-sample reasoning with no forward test.** Not one claim above was gated on forward data
   before deployment. The server's live-grader + n≥13 rule is the fix, and it is the right one.

2. **Same-day self-contradiction.** 03-29 vs 03-31 on leverage; 04-28's two opposite gate
   conclusions; 04-29 deploy-and-refute. Sessions did not read the previous session's result
   before overwriting it. 104 of the 154 memory files are from April alone — the churn is visible
   in the file count.

3. **"Root cause identified" as a terminal state.** The archive contains at least a dozen
   CRITICAL-FIX / root-cause-found entries (04-26 ×5, 04-27 ×4, 04-28 ×6). A root cause that is
   identified but not forward-verified is a hypothesis. Almost none were re-tested.

---

## What to do with this

- **Nothing in the March–June alpha ledger should be reused as evidence.** It is pre-fee-fix,
  pre-baseline-correction, and in-sample. Treat the whole corpus as hypothesis generation only.
- **The 16,458-signal corpus from mission 1 is the exception** — it records proposals, not
  outcomes, so it is untouched by the fee bug, the fill bug and the fixture flooding. Grade it
  forward against real candles and it becomes genuinely new evidence for Feb–May 2026.
- **Re-test the one structural insight that was never properly validated:** the 35%-vs-50%
  win-rate baseline mismatch (04-11). If any feedback system still scores on a 50% centre, it is
  still suppressing edge today. That is cheap to check and was never confirmed forward.

## Reproduce
`bot/data/laptop_mining/mine_memory.py` → `memory_index.json` (154 records), `prompt_history.json`
(2,272 prompts). Prompt volume by month: Mar 489, Apr 1,276, May 209, Jun 246, Jul 40, Oct 12.
