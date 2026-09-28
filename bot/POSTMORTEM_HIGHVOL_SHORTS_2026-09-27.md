# Postmortem: shorting into 4h high-volatility (the NEAR −$8.70 case)

**2026-09-27.** Triggered by the owner's read of the recent NEAR SHORT loss:
"it should've been a long and our setup knew that." Checked against
`data/trade_ledger.csv` (287 closes). Small-file, read-only.

## The owner's instinct, tested — the setup KNEW, and was overridden

This claim went through two wrong versions before the tracer got it right; both are
left visible because the iteration is the point.
- v1 (wrong): "internally conflicted, confidence_scorer SELL vs multi_tier LONG" —
  I'd read a portfolio-wide *trigger* record from the wrong file (`decisions.jsonl`).
- v2 (under-corrected): "the pipeline unanimously agreed go/approve" — too generous.

**v3 (traced, accurate).** The full agent chain for pipeline `915b5357-057`
(`lineage_trace.py --trade-id f50c94986b5e`) shows the setup **explicitly flagged
this as a bad trade and was overridden:**

- **quant: SKIP / FLAT** (conf 0.1) — *"NEAR_SELL=0% historical, consolidation=17%
  regime WR vs 53% trending. Knowledge base explicit rule: avoid single-signal
  SHORTs in consolidation. EV negative... Stacking low-edge trade on a loss streak
  = portfolio destruction. FLAT."*
- **trade: go** (conf **0.35**) — *"No explicit graduated-rule veto or hard safety
  block, EV not < −2.0, so **overdrive default is go**. Confidence cut hard for
  4h/1h regime misalignment, redundant confluence, adverse BTC trend, poor
  consolidation WR, and known overconfidence bias."*
- **risk: size 0.3 / override reduce** — but still **leverage 3.0**.
- **critic: approve** — *"Vacc=0% (my vetoes are destroying value)... so no fresh
  counter-thesis adds value here."* The critic had **self-disabled**.

So the owner is right: the setup knew. The quant agent named the exact reasons not
to trade, and the trade agent cut confidence to 0.35 for the regime misalignment.
It opened anyway because **three override paths lined up**: (1) an "overdrive
default is go" rule that fires unless something *hard*-blocks; (2) the quant SKIP
is shadow-only / not wired to enforce (a known issue — "Quant shadow no
parser/counterfactual"); (3) the critic default-approves because its own veto
accuracy is 0%. Not a bad signal — a governance gap.

This is the highest-value thing the tracer surfaced, and it's a mechanism fix, not
just a regime guard: **a hard-cut confidence (0.35) plus an explicit quant SKIP
should not resolve to a 3x-leverage entry.** The aggregate regime pattern below is
the same lesson at the population level.

## What the ledger says

Overall by side (the general picture — "should've been a long" is NOT a blanket rule):

| side | n | net | WR |
|---|---|---|---|
| LONG | 114 | **−$795.59** | 36% |
| SHORT | 174 | **+$539.43** | 36% |

Shorts are historically the bot's profitable side; longs are the drain (consistent
with the long-drain finding in memory). So in general, shorting is *not* the error.

**The exception — a losing pocket inside the winning side:**

SHORT trades by 4h regime:

| regime_4h | n | net | WR |
|---|---|---|---|
| (blank) | 154 | +$644.84 | 38% |
| **high_volatility** | **11** | **−$103.26** | **9%** |
| consolidation | 8 | −$1.19 | 38% |
| trend | 1 | −$0.96 | 0% |

The `consolidation-1h + high_volatility-4h SHORT` setup specifically: **n=11,
−$103.26, 9% WR**, composed of NEAR (7), SOL (2), HYPE (2). NEAR is the worst
offender but it is **not** NEAR-alone — it's a regime×side pocket. Shorting into
4h high-volatility gets squeezed.

NEAR alone: SHORT n=7 −$89.66 (14% WR) vs LONG n=2 +$1.13 (50% WR).

## Honest verdict

- **The owner is right for THIS regime, not in general.** Shorts win overall;
  shorts *into 4h high-volatility* lose hard (9% WR). The NEAR short was in exactly
  that pocket, and the pipeline had a LONG signal it discarded.
- **This is a candidate forward-veto**: "don't short when regime_4h ==
  high_volatility" (or size it down). Mechanism is plausible (shorting into a
  vol spike = squeeze risk), and it spans 3 symbols, not one.

## Caveats (do not overclaim)

1. **n=11 is below the owner's n≥13 graduation gate.** Per standing policy
   (no hardcoded directional blocks; data-learned vetoes at n≥13), this is NOT
   yet actionable as a live block — it needs ~2 more instances. Log it, watch it.
2. **`regime_4h` is mostly BLANK** (154 of 174 shorts have no 4h label — the
   known measurement gap). So this pocket is n=11 out of only ~20 labeled shorts;
   the true size is unknown until regime_4h logging is fixed. **Fixing regime_4h
   population is the prerequisite** to trusting this at scale.
3. NEAR LONG n=2 is far too thin to call longs "good" on NEAR.

## Why this matters for the lineage work

This is the exact shape the decision-lineage tracer should surface automatically:
a trade taken into a regime where that side loses — *even with all agents in
agreement* (which is what makes it dangerous; nothing internal objected). If the
tracer had flagged "you are shorting into 4h high-vol, where this side is 9% WR"
at decision time, it's a legible, actionable warning — not hindsight.
