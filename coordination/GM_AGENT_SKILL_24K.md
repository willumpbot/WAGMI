# GM_AGENT_SKILL_24K — per-agent skill attribution from 24.4k agent calls
Date: 2026-07-02 (desktop). Standard: THE_STANDARD.md v1.3 (denominators, era-split, adversarial pass, week-1 test).
Script: `bot/tools/research/gm_agent_skill_24k.py` (reproducible; prints full JSON). READ-ONLY on bot code; recommendations only.

## Dataset & ground truth
- `bot/data/llm/agent_performance.jsonl`: 24,433 decision records, 2026-05-30 17:25 → 2026-07-02 02:48 UTC.
- Roles: exit 4,730 | trade 3,644 | regime 3,644 | quant 3,634 | risk 3,601 | critic 3,594 | overseer 888 | scout 472 | learning 226.
- Ground truth: HL 1h candles (BTC/ETH/SOL/HYPE/XRP, cached `gm_candles_1h.json`, full period, no gaps — avoids the funding_oi 536h hole), `trade_ledger.csv` (157 trades), `counterfactual_resolved.jsonl` (39,368 parsed; 14 corrupt lines skipped).
- Eras: **wk1** = May30–Jun5 (crash week), **mid** = Jun5–~Jun20, **late** = ~Jun20–Jul2.

## Honest match-rates and method caveats (read first)
- **Side inference for trade "go" calls: 33.7% coverage (198/587), and it is era-biased** — wk1 57% sided, mid 35%, late 9% (15/163). Late-era trade-go numbers are near-worthless n. Cause: `reasoning_summary` truncated at ~200 chars; side words often absent. This is a logging hole, not an analysis choice.
- Skip→counterfactual match (same symbol, ±10 min): **87.1%** (2,661/3,057). Go→ledger match (±1h): only **15.7%** (92/587) — most "go" decisions did not become ledger trades (gates downstream).
- Scoring is directional price return at +4h/+24h, not dollar PnL (no fees/stops). Candle alignment uses the bar containing the call timestamp (up to 1h slack). Exit-agent rows are serially correlated (many calls per position) — n overstates independence.
- **Confidence logging is broken for 7/9 roles**: scout, quant, risk, critic, overseer, exit, learning all log a constant 0.5 (stdev 0.000). Only regime and trade emit real confidence. The fleet's calibration instrument mostly doesn't exist.

## Per-agent skill table

| Agent | n | Model (main) | Measured signal | Era-split verdict | Verdict |
|---|---|---|---|---|---|
| **Regime** | 3,644 | Haiku (94%) | Trend-direction calls hit **58.5%** @4h (n=641, +4.0bps); beats mechanical vol/trend classifier (47.5%, n=688, −11.2bps) | **Survives**: hit .648 wk1 / .538 mid / .592 late; mech collapses to .358 mid | **KEEP** — best value/token in fleet |
| **Trade (skips)** | 3,057 | Sonnet | Skipped setups would have averaged **−0.18%** (n=2,661, would-win 44.7%) | **Survives**: mid −0.27% (n=1,451), late −0.39% (n=862); wk1 skips cost money (+0.69%, n=348) | **KEEP** — skip filter is real, post-wk1 |
| **Trade (gos)** | 587 | Sonnet | @4h **−8bps** (n=198, sided only); ledger-matched gos: WR 39%, −$30.3 net (n=92) | **Week-1 artifact**: wk1 +21bps/+192bps(24h); mid −33/−145; late −39 (n=15). Fragility: wk1 24h +192→+174 after dropping best 3 — the era, not one trade, is the artifact | **FIX** — entry timing shows no skill outside crash week |
| **Critic** | 3,594 | Sonnet (80%) | Challenges 6.6% (238). Headline looks good: vetoed gos +9.8bps vs approved +63bps @24h | **Artifact**: wk1 vetoed +120 vs approved +274 (right ordering); **mid vetoed −79 vs approved −196 — it vetoed the less-bad and approved the worse** (n=63/41); late n=9 | **FIX or SHADOW** — no reliable value over Trade alone; small-n humility applies |
| **Quant** | 3,634 | **Opus (75%, 2,721 calls)** | "+75bps 24h short edge" headline | **Pure week-1 artifact**: short calls wk1 +311bps/87% WR (crash shorts, n=253); mid −22bps (n=526); late −1bps (n=115). @4h mid −4, late −45bps. quality=noise tag has **zero separating power**: \|4h move\| 106.5bps (neutral, n=2,340) vs 104.5bps (directional, n=1,127). Confidence constant 0.5 | **MUTE / demote from Opus** — most expensive agent, no surviving signal (confirms Quant Brain suspicion) |
| **Risk** | 3,601 | Haiku (94%) | 86% of calls emit `size=0,override=skip` — echoing an upstream skip. On gos: sized-0 −24bps vs sized>0 −0.7bps (n=46/151) | Weak positive gating, small n | **KEEP (cheap) + trim**: don't call it when trade=skip → saves ~75% of calls |
| **Exit (closes)** | 2,780 | Haiku | Post-full-close the position would have made only +3.3bps @4h (n=2,749) — closes leave ~nothing on table | Survives: wk1 +7 / mid −6 / late +5bps | **KEEP** |
| **Exit (holds)** | 1,035 | Haiku | Held positions went **−25bps** @4h (n=1,020) | Bad 2/3 eras: wk1 −37, late −40, mid +22 | **FIX** — hold is the weak call; partial_close remainder −86bps @24h too |
| **Scout** | 472 | Haiku | All 472 = "monitor", confidence constant 0.5, watchlist prose — nothing falsifiable logged | n/a | **MUTE or FIX logging** — pure token cost as instrumented (28k latency-sec) |
| **Overseer** | 888 | Sonnet | 785/888 decisions = "unknown" (unparseable) | n/a | **FIX logging or MUTE** — unscoreable |
| **Learning** | 226 | Haiku | 219/226 = "unknown" | n/a | **FIX logging** |

## The four questions, answered
1. **Does the Critic's veto add value over the Trade agent alone?** Not demonstrably. Its apparent selectivity (vetoed +9.8 vs approved +63bps @24h) is wk1-driven; in mid era its ordering was inverted (vetoed −79 vs approved −196). n per era is 52/63/9 — below graduation threshold either way, but there is no evidence to keep paying Sonnet for the veto as-is.
2. **Is the Regime label better than a mechanical classifier?** Yes — the one clear positive. 58.5% vs 47.5% directional hit @4h; the mech baseline dies mid-era (.358) while the LLM holds ≥.538 in all three eras and both directions (bear-late .543 n=162, bull-late .824 n=34; bull-wk1 n=5 unmeasurable).
3. **Does ANY agent's confidence correlate with being right?** No. Only 2/9 roles emit non-constant confidence and both are inverted: Trade go conf↔4h return corr −0.17 (hi-conf −29bps vs lo-conf +15bps, n=103/95); Regime hi-conf hit .535 vs lo-conf .638 (n=329/312). The inversion seen elsewhere reproduces here. The other 7 roles log constant 0.5 — fix the instrument before drawing more conclusions.
4. **Which agents are pure token cost?** Quant (75% Opus, 2,721 Opus calls, no surviving signal, noise-tag useless), Scout (constant output, unscoreable), Overseer (88% unparseable), Learning (97% unparseable). Risk is 86% redundant calls but cheap.

## Recommendations (no code changed)
1. **Quant: route off Opus immediately; shadow-mode its EV direction** until it shows post-wk1 signal. Biggest cost lever in the fleet.
2. **Critic: shadow its vetoes** (log would-have-blocked, enforce nothing) per §2b until n≥15 post-wk1 with correct ordering.
3. **Fix decision/confidence logging** for scout/overseer/learning/exit/quant/risk/critic (constant 0.5 + "unknown" decisions = unscoreable agents). Measurement first, per mandate.
4. **Trade agent: keep the skip, distrust the go-confidence** (inverted). Stop truncating `reasoning_summary` or log an explicit `side` field on trade/critic records — 66% of gos are unscoreable today.
5. **Exit agent: keep full_close, audit the hold prompt** — holds precede −25bps @4h in 2/3 eras.
6. **Regime agent is the keeper** — cheapest strong signal; consider feeding its trend call more weight than quant's EV direction.

## Killed hypotheses (log as wins)
- "Quant's short EV calls have edge" — killed by week-1 test (wk1 +311bps → mid −22, late −1).
- "Trade agent's go entries have timing skill" — killed (positive only wk1; fragility-checked).
- "Critic veto reliably filters bad trades" — not supported; ordering inverted mid-era.
- "quality=noise marks low-opportunity moments" — killed (no |move| separation, 106.5 vs 104.5bps).
