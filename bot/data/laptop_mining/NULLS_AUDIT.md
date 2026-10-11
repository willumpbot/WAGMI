# Audit of the two null docs (`CROSS_SECTIONAL.md`, `BASIS_TRADE.md`) — both decisions are right. ⚠️ But "nothing survived" is not the same as "nothing is there", and the project's 98-test tally rests on that confusion.

_2026-10-11. Completes the six never-reviewed docs. Audited with the lens inverted: for a null the
danger is not overconfidence in a finding, it is an **underpowered null read as proof of absence.**_

---

## 🔴 Bottom line

**Both documents reach the right practical decision, and I would not reverse either.** But neither
states what it could have detected, and in both cases the answer is *"only an enormous effect."* One
sentence in each would fix it — and the same gap undermines a claim the whole project leans on.

## `CROSS_SECTIONAL.md` — the decision is right, and for a reason that needs no statistics

**What is airtight, and the doc argues it itself:** at a 1-day hold a long-short basket pays four legs
— **0.36%/day** — and the shuffled-rank null lands at **−0.32 to −0.43%**, which *is* the fee drag. The
doc says so explicitly: *"five signals coming out significantly negative is simply fees showing
through."* **Correctly diagnosed. No daily spread among 11 large caps beats 36 bps reliably, so the
1-day version was dead on arithmetic.** That conclusion needs no power at all.

**Also valid and distinct:** at 5-day, four cells look strong in train (+0.96% to +1.30%, CIs excluding
zero) and **every one collapses in test.** That is evidence of *overfitting*, not a failure to detect —
a genuinely different and stronger argument.

**Methodologically this is one of the better docs here:** day-block bootstrap with the block matched to
the horizon, a shuffled-rank null that keeps the basket structure and destroys only the signal, and
market-neutral by construction so drift cancels.

### ⚠️ But the MDE is never stated, and it is enormous

Backing the standard error out of the published CIs:

| cell | test | MDE per period | **MDE annualised** |
|---|---|---|---|
| 1d mom7 | −0.300 | 0.325% | **119%** |
| 1d vol22 | −0.485 | 0.351% | **128%** |
| 5d rsi | +0.595 | 1.279% | **93%** |
| 5d stretch | +0.437 | 1.308% | **95%** |

**The test could only see edges of roughly 70–130% a year.** A realistic cross-sectional crypto edge is
perhaps 2–10 bps/day. **Invisible here by construction.**

### And two cells are economically large but statistically unresolved

| cell | test | per day | annualised | CI upper bound |
|---|---|---|---|---|
| **5d rsi** | +0.595 | +0.119% | **+43%/yr** | **+112%/yr** |
| **5d stretch** | +0.437 | +0.087% | **+32%/yr** | **+104%/yr** |

Calling these *"not significant"* is correct. **But they are not excluded either**, and the headline
*"zero are significantly positive"* invites reading them as zero. A 43%/yr point estimate that cannot be
resolved is a **reason to measure again with more data**, not a closed question. **These are the two
cells I would revisit first** if cross-sectional is ever reopened.

## `BASIS_TRADE.md` — right call, and the real argument is economic rather than statistical

**The test half has n = 15 cycles.** From the published CIs:

| clip | test net | CI95 | MDE/cycle | **MDE annualised** |
|---|---|---|---|---|
| $1k | +0.066% | [−0.061, +0.227] | 0.206% | **7.8%** |
| $5k | +0.027% | [−0.096, +0.180] | 0.197% | **7.3%** |
| $25k | −0.167% | [−0.294, **−0.001**] | 0.209% | **7.9%** |

**So "it earns 1–2.5% annualised" is not distinguishable from zero** — the test could not resolve
anything below ~7.8%/yr. *"The trade does not pay"* and *"we cannot tell whether it pays below 8%/yr"*
are different statements, and only the second is supported.

**⚠️ The `$25k` "significantly negative" cell should be softened.** Its CI upper bound is **−0.001%** —
a knife-edge rejection on **n = 15**, with **6 cells tested** (3 clips × 2 halves) and no multiplicity
correction. Bonferroni would not clear it. The *direction* is sound — costs rise with clip size, which
is mechanical — but "significantly negative" overstates a result that is one cycle from crossing zero.

**None of that changes the decision, because the decision does not rest on the statistics:** observed
carry is 1–2.5% annualised, costs scale with size, only 5 of 21 pairs were usable at all, and two were
rejected for books under $10k. **"Do not build a Carry panel" is right on economics.** I would just
state it that way rather than as a statistical refutation.

**Credit where due:** this doc already self-corrects a real error — it had rejected BTC, the *best*
asset in the set (basis sd 0.063%, deepest book), on a mis-computed 13.1% standard deviation from 11
rows, and says so plainly.

## 🔴 The meta-finding, which matters more than either doc

`CROSS_SECTIONAL.md` states the project's directional tally as **"~98 tests across four datasets with
nothing surviving"** — and that line has propagated into the project's framing.

**If the MDEs throughout are 90–128% annualised, that tally cannot mean "no directional edge exists."
It means "no edge larger than enormous exists."** Those are very different claims, and the second is
close to uninformative.

**This does not mean a directional edge is there.** It means the evidence is far weaker than the number
98 implies, and the honest version of the claim is:

> *"98 directional tests, none finding an edge large enough to clear detection floors that mostly sit
> above 90% annualised."*

**Recommended wording change wherever the tally appears**, including `COMMAND_CENTER.md`. A tally of
underpowered tests is a statement about the data available, not about the market.

## What I did not find

Neither doc has a test that could not fail, an uncontrolled confound, or a mis-specified null — the
three faults that killed findings in M9, M10 and M11. **The nulls are honestly derived. They are just
quieter than they sound.**

## Limits of this audit
- MDEs are **back-computed from the published CIs** (MDE ≈ 2.8/1.96 × half-width), which assumes those
  CIs are approximately symmetric and normal. For the bootstrap intervals here that is reasonable but
  not exact.
- Annualisation uses each doc's own stated horizon and capital convention, so it inherits any error there.
- No refit of either study.
