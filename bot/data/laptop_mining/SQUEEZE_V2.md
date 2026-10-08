# Squeeze v2 — the column works, but "consensus" was never what made it work

_2026-10-08. 27,187 coin-days, train 18,850 / test 8,337, train→test split at 2025-06-01.
Script: `squeeze_v2.py`. Data: `squeeze_v2.json`. Supersedes the consensus half of `SQUEEZE.md`._

---

## Headline

**Keep the "Squeeze L/S" column — it has real out-of-sample predictive power. But drop the consensus
term and relabel it, because the signal is overbought/oversold, not agreement.** Replacing `disagree`
with explicit extremity is simpler, honest, and *better* on the short side (AUC +0.0620 vs +0.0523).

Once extremity is controlled, `disagree` adds **nothing**: −0.0024 AUC on longs (permutation
p = 0.965) and −0.0012 on shorts (p = 0.890). Both negative, both indistinguishable from a shuffled
feature.

---

## The mechanism — the confound is structural, not incidental

`squeeze.py:85` is `disagree = sum(fam[x] != netdir)`, and two of the six families vote `0` unless
they are extreme:

```python
"rsi":  +1 if rsi > 70, -1 if rsi < 30, else 0
"boll": +1 if bb  > 0.8, -1 if bb  < -0.8, else 0
```

`netdir` is ±1, so a **neutral** RSI (`0`) always satisfies `!= netdir` and is counted as
**disagreeing**. So high `disagree` literally means *"RSI and Bollinger are mid-range"*, and low
`disagree` means *"overbought or oversold"*. It is an extremity indicator wearing a consensus label.

The correlations confirm it:

| pair | r |
|---|---|
| `disagree` vs `ext_rsi` (\|RSI−50\|/50) | **−0.802** |
| `disagree` vs `n_active` (families that actually voted) | **−0.749** |
| `disagree` vs `ext_bb` (\|bollinger z\|) | −0.605 |
| `disagree` vs `dissent_active` (real dissent) | +0.786 |

**R² of `disagree` on [vote-activity, RSI extremity, Bollinger extremity] = 0.7055.** So 70.6% of the
feature is mechanically determined by extremity and abstention. It does also track genuine dissent
(+0.786) — which is why the correlations alone cannot settle it, and the out-of-sample test below can.

---

## The test: does it add anything once extremity is controlled?

### LONG — base rate 10.9% train / 8.4% test

| features | test AUC | vs forecast-only | vs +extremity |
|---|---|---|---|
| forecast only | 0.5699 | — | |
| + `disagree` (ORIGINAL) | 0.5982 | **+0.0282** | |
| **+ extremity** | **0.5980** | **+0.0280** | — |
| + extremity + `disagree` | 0.5956 | +0.0257 | **−0.0024** |
| + extremity + TRUE dissent | 0.5963 | +0.0263 | −0.0017 |

### SHORT — base rate 11.7% train / 12.0% test

| features | test AUC | vs forecast-only | vs +extremity |
|---|---|---|---|
| forecast only | 0.5073 | — | |
| + `disagree` (ORIGINAL) | 0.5596 | +0.0523 | |
| **+ extremity** | **0.5693** | **+0.0620** | — |
| + extremity + `disagree` | 0.5681 | +0.0608 | **−0.0012** |
| + extremity + TRUE dissent | 0.5673 | +0.0600 | −0.0020 |

### Permutation null — 200 shuffles of `disagree`, extremity retained

| side | real gain over +extremity | shuffled mean [95%] | p(shuffled ≥ real) | |
|---|---|---|---|---|
| long | −0.0024 | −0.0003 [−0.0026, +0.0009] | **0.965** | adds nothing |
| short | −0.0012 | −0.0001 [−0.0028, +0.0024] | **0.890** | adds nothing |

A shuffled `disagree` performs as well as the real one. **The entire apparent value of the consensus
feature is extremity**, and on shorts plain extremity is *strictly better* than the consensus
version — `disagree` was a lossy proxy for it.

Note the honest dissent measure (counting only families that actually voted) also adds nothing
(−0.0017, −0.0020). **So this is not a bug in how dissent was counted. There is no dissent signal to
recover.** That answers the PC's question about `dissent_families` vs the 8-family count: the
definition does not matter, because no definition of it adds anything.

---

## What to change in the terminal

**Keep the column. Change two things:**

1. **Replace the `disagree` feature with explicit extremity** — `|RSI−50|/50`, `|bollinger z|`, and
   the count of non-neutral voices. Same or better AUC, three transparent inputs.
2. **Relabel it.** It is not a consensus or hivemind-agreement signal. It is
   *"stretched conditions raise the odds of an outsized adverse move."*

**What stays true:** the column has genuine out-of-sample skill — AUC 0.598 long and 0.569 short
against base rates of 8.4% and 12.0%, on a test half never used for fitting. That is a real, if
modest, edge and it is worth displaying.

## Trader rules

1. **When RSI or Bollinger is stretched, expect a bigger adverse excursion** — extremity lifts
   squeeze AUC by **+0.028 long / +0.062 short** over the volatility forecast alone.
2. **Shorts are where it matters.** The forecast alone is nearly useless on shorts (AUC 0.5073,
   barely above a coin flip); extremity is what makes that side predictable at all.
3. **Ignore voice agreement for this purpose.** It carries no information the stretch indicators do
   not already carry.

## Limits
- AUC and a permutation null only; no calibration or decile-lift check in this pass.
- A single train/test split at 2025-06-01, not walk-forward. The direction of the result (a feature
  adding *nothing*) is the kind least likely to be an artifact of split choice, but it is one split.
- The squeeze label depends on the HAR volatility forecast, which `VOLATILITY_V2.md` recommends
  replacing with an EWMA. Since both would shift the threshold identically for every feature set, the
  *comparison* is unaffected — but the absolute AUCs would move slightly.
- `ext_bb` and `ext_rsi` are contemporaneous with the close, and the label is next-day, so there is no
  lookahead. `n_active` likewise.
