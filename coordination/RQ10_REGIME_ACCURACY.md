# RQ10 — Regime-Label Accuracy Audit
Date: 2026-07-02 | Standard: THE_STANDARD.md v1.3 | Script: `bot/tools/research/rq10_regime_accuracy.py` | Raw output: `bot/tools/research/rq10_results.json`

## Question
The Regime agent is the only agent with era-stable skill (GM_AGENT_SKILL_24K) and its label gates everything downstream. Are its labels actually accurate? Where does it misclassify? Would a mechanical classifier do better?

## Data & method
- **Labels**: 3,696 Regime-agent decisions from `bot/data/llm/agent_performance.jsonl` (agent_role=regime), per-symbol (BTC 1,528 / SOL 811 / ETH 676 / HYPE 643 / XRP 37), 2026-05-30 → 2026-07-02. 32 empty-symbol records excluded.
- **Price truth**: fresh HL candleSnapshot 1h candles, 2026-05-10 → now, all 5 symbols (cache: `rq10_candles_1h.json`). No funding_oi dependency (hole irrelevant).
- **Mechanical nowcast** (data up to last closed bar only, no lookahead): ATR%-percentile ≥ 0.90 (trailing 14d) → high_vol; else ADX(14) ≥ 25 → trending (direction by DI+/DI−); else ranging.
- **Realized (hindsight) regime** over next 24h: forward realized-vol in symbol's top decile → high_vol; else efficiency ratio ≥ 0.35 → trending (sign of net move = direction); else ranging. Sensitivity run at ER 0.25/0.45.
- **Coarse mapping**: {trend, trending_bull, trending_bear}→trending; {range, consolidation, low_liquidity}→ranging; {high_volatility, panic}→high_vol.
- n joined = 3,696; n with full 24h forward window = 3,414. Realized base rates: ranging 71.1%, trending 16.0%, high_vol 12.9%.

## Finding 1 — Agent and mechanical classifier agree only 51% of the time
Coarse agreement 50.8% (era1 41.6%, era2 62.7%). Biggest split: agent says "ranging" while mech says "trending" (924/3,696). They are measuring different things; the agent leans hard on 4h range width (per its reasoning strings), not ADX.

## Finding 2 — Raw accuracy vs realized: agent 60.0%, mech 52.2%, **always-say-ranging 71.1%**
Both classifiers LOSE to the constant baseline on raw accuracy, in both eras (era1: agent .568 / mech .446 / const .675; era2: .630 / .592 / .745) and at every ER threshold tested. Raw accuracy here is a base-rate-hugging contest and the agent partially wins it by saying ranging/consolidation 72% of the time.

## Finding 3 — Per-class truth: the agent's "trending" label is ANTI-predictive; it is blind to high_vol
| class | agent precision | agent recall | mech precision | mech recall | base rate |
|---|---|---|---|---|---|
| trending | **.127** (n_pred 778) | .181 | .160 (n_pred 1,245) | .364 | .160 |
| ranging | .770 | .785 | .792 | .531 | .711 |
| high_vol | .276 | **.102** | **.542** | **.667** | .129 |

- When the agent says trending, realized trending follows 12.7% of the time — BELOW the 16% base rate. 679 of its 778 trending calls were wrong (436→ranging, 243→high_vol).
- The mechanical ATR-percentile crushes the agent on high_vol: recall 67% vs 10%, precision 54% vs 28%. The agent flags high_volatility only 163 times against 441 realized instances.
- Balanced accuracy (mean per-class recall): **mech .521 > agent .356** > always-ranging .333. The agent's raw-accuracy "win" over mech is entirely base-rate hugging.
- Top misclassifications (fine): consolidation→realized-trending 247, trending_bear→ranging 240, trending_bear→high_vol 201, range→trending 168.

## Finding 4 — The agent's real skill is DIRECTION, not regime class (reconciles the goldmine)
When the agent commits to trending_bull/bear, forward 24h sign matches 54.0% (n=611). Mechanical DI-direction: **40.2%** (n=1,245) — anti-predictive in this chop-heavy sample. This reproduces GM_AGENT_SKILL_24K (58.5% @4h vs mech 47.5%, mech collapses mid-era). The goldmine is real but it is a *direction* signal; the regime *class* label around it is weak.

## Finding 5 — Confidence is inverted (again)
conf < 0.7: 65.7% accurate (n=2,603) | 0.7–0.8: 46.3% (n=624) | **conf ≥ 0.8: 27.3%** (n=187). Confound: high conf co-occurs with trending/high_vol calls (low base rates) — but as a calibration instrument it is worse than useless. Matches the fleet-wide inversion in GM_AGENT_SKILL_24K.

## Finding 6 — Does misclassification correlate with losing trades? NO (and the reverse is fragile)
Trade ledger n=158 (small-n humility applies throughout):
- Agent regime-label CORRECT at entry (vs realized): n=52, −$723. Agent WRONG: n=96, +$782. Sign is the *opposite* of the hypothesis — but +$782 contains a single +$1,010 winner; fragile, not a claim.
- Agent-mech agree at entry: n=44, −$547 | disagree: n=114, +$592. Same fragility.
- **The one robust trade-level fact**: trades entered under an agent "ranging/consolidation" label: n=69, WR 21.7%, **−$1,001** — negative in BOTH eras (era1 −$901/25, era2 −$100/44) and survives removing the single worst trade (−$778). By contrast "trending"-labeled trades (+$811, n=42) FAIL both checks: minus best trade → −$199; era2 → −$312. Do not celebrate the trending bucket.
- Verdict on the hypothesis: regime-label accuracy at entry is not the P&L driver at n=158. The losses live in label-said-ranging entries regardless of whether the label was right.

## Finding 7 — Cheapest upgrade, tested: hybrid = mech high_vol override + ADX<20 demotion of trending calls
Keep the agent, but (a) hard-override to high_vol when ATR%-percentile ≥ 0.90, (b) demote agent "trending" to ranging when ADX(14) < 20:
- Accuracy vs realized: agent .600 → **hybrid .652** (mech alone .522). Era-stable: era1 .568→.607, era2 .630→.694. Zero new data feeds, ~20 lines against candles already collected.
- Would mech ALONE do better? Mixed: better balanced accuracy (.52 vs .36) and high_vol detection, but much worse direction (40% vs 54%) and worse raw accuracy. **Replacement: no. Hybrid: yes.**

## Adversarial self-check
- Hindsight-truth definition is contestable: at ER 0.25 agent/mech tie (.492/.491); at 0.45 agent leads (.662/.531). Agent≥mech and both<const-baseline hold at all thresholds; Finding 3's high_vol gap is threshold-independent (ATR-percentile is near-definitionally aligned, disclosed).
- Realized labeler shares the ATR-percentile family with the mech nowcast for high_vol — biases Finding 3's high_vol row in mech's favor; does NOT touch the trending-precision result (ER-based).
- No lookahead: nowcast uses last CLOSED bar; hindsight rows without a full 24h forward window dropped (282).
- Per-symbol: agent>mech everywhere except XRP (n=16, ignore). BTC is the agent's worst (.484 vs const .655, n=1,456).
- Label-time join is exact (hour-bucket); ledger entry ts reconstructed as close_ts − hold_hours.

## Verdict
The Regime agent is a **decent direction oracle wrapped in a poor regime classifier**: its "trending" class label is below base rate (12.7% precision), it misses 90% of high-vol regimes, and its confidence is inverted. It still beats the mechanical classifier on raw accuracy and direction, so keep it — but gate nothing on its class label alone. Cheapest upgrade (validated, era-stable, +5.2pts): mechanical ATR-percentile high_vol override + ADX<20 trending demotion, injected per THE_STANDARD §3b as raw stats into the regime prompt or applied as a post-label overlay. Also: stop surfacing regime-agent confidence ≥0.8 as a positive anywhere downstream.
