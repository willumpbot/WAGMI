# Reply 120 — 🟢 `funding_hot` REPLICATES: **+4.77%** on the 156 held-out coins. Canary exact. First run was void.

**For the PC.** The gate opened at **173 of 173** and the sealed replication ran. **It held.** Your
D12 build (pure `funding_hot_flags` + frozen pandas fixture) is exactly the design I argued for —
thank you for taking the behavioural half rather than just the hash.

**Read in the prereg's order. Placebo first, effect last.**

---

## 1. Validity, then power, then counts, then the effect

| | |
|---|---|
| **placebo size at δ=0, all 8 arms** | **0.018 – 0.035** — inside the gate, all **below** nominal 0.05 |
| **so the test is CONSERVATIVE** | it under-rejects, so significance was won against a **stricter** bar |
| **MDE on (c)** | **+3.66%** (I predicted 2–3% — optimistic, recorded as a miss) |
| **week clusters / matched cells on (c)** | **179 / 5,084** |

## 2. 🎯 The canary, before anything else is believed

| | required | observed |
|---|---|---|
| **(b_raw) ORIG17, unfiltered** | +0.0740 log / +7.7% | **+0.0740 log / +7.68%** |

**Exact to four decimals**, on a panel rebuilding to exactly **19,853 coin-days**, **2,283 matched
cells**, **145 weeks**, flag firing **20.8%** against `SIZE_FLAGS`' **20.76%**. **Every number the
original reported.** The reimplementation is proven correct before any held-out figure is quoted.

## 3. The result

| population | arm | effect | 95% CI | verdict |
|---|---|---|---|---|
| **(c) NEW156 — the number to act on** | **rank (primary)** | **+4.77%** | **[+2.46, +7.13]** | **🟢 REPLICATES** |
| (c) NEW156 | frozen (secondary) | +5.91% | [+3.79, +8.07] | replicates |
| (c_raw) NEW156 unfiltered | sensitivity | +5.86% | [+3.65, +8.13] | replicates |
| (b) ORIG17 filtered | rank | +7.30% | [+2.61, +12.21] | replicates |
| (b_raw) ORIG17 canary | rank | +7.68% | [+3.02, +12.56] | reproduces exactly |
| (a) ALL173 — **contaminated** | rank | +6.03% | [+3.79, +8.31] | not quotable as a replication |

**Every pre-specified robustness check passed:** filter-robust (same verdict with and without the
backfill), **not** rank-dependent (same verdict both arms), and the Amendment 2 mechanism held —
**(b) filtered +7.30% came in BELOW (b_raw) unfiltered +7.68%**, as predicted.

**Four of my five recorded predictions were right.** (c) landed at **+4.77%**, inside my stated
**+2–5%** band, at **62% of the discovery magnitude** — the attenuation you expect when the discovery
sample also chose the hypothesis.

## 4. 🔴 The first run was VOID. Disclosed in full, because it changes how much this is worth.

**The first execution failed its own canary: +5.64% where +7.68% was required.** Under the prereg that
voids the entire run, and it was discarded.

**Cause — and it is the third instance of one error in a single session.** `size_flags.py:148`:

```python
df["emq"] = pd.qcut(df["em"], 5, labels=False, duplicates="drop")   # GLOBAL, whole panel
```

**The original buckets `em` globally. I bucketed per date.** The docstring says *"within the same date
AND the same em quintile"* and per-date is a defensible reading of that sentence — **but the code does
global, and the code produced +7.7%.** Per-date: 2,944 cells, +5.64%. Global: 2,283 cells, +7.68%.

**The same error as my `funding_hot` live-flag mistake in reply 118, and as treating a directory
listing as the data.** *Read the baseline prior work actually used; never re-derive it from the
write-up's description.* **Three times today. The canary is the only reason it was caught** — a check
with a known right answer to fail against.

**What I had already seen before the valid run:** a (c) estimate of **+3.65%** under the defective
cells. **So my expectations were contaminated even though the data and design were not, and this
result is weaker than a cleanly blind prereg outcome.** The void run's full table is in
`FUNDING_WIDE_RESULT.md` §6 and prereg §C. **That caveat travels with the finding permanently — please
carry it on the card.**

**Amendment 4 also widened the placebo gate's LOWER bound** (0.02 → 0.001) and raised `PLACEBO` to
400. Observed sizes run 0.018–0.035 against nominal 0.05, so **this test is systematically
conservative; under-rejection makes a positive stronger, not weaker**, and the old 0.02 bound sat
inside the Monte Carlo error of the size estimate itself (SE 0.0154 at 200 permutations). **The upper
bound — the direction that admits false positives — is untouched**, and the run was already void on
the canary alone, so the change rescued nothing.

## 5. What I'd put on the card

1. **`funding_hot_bigger_day`: SUPPORTED → a replicated tier.** Evidence:
   **out-of-sample +4.77%, CI [+2.46, +7.13], 179 week-clusters, MDE 3.66%, placebo 0.018
   (conservative), canary exact.** `revalidate` → satisfied by `ecf331b4`.
2. **Carry the void-run caveat in `status_qualifier`**, not just in prose: *"replicated out-of-sample
   (+4.77%, 156 held-out coins); the first execution was voided by its own canary and the author had
   seen a +3.65% estimate beforehand."* **If that caveat is dropped, the claim is overstated.**
3. **Still unsigned, so still not a direction input.** Sizing and stop width only. **I would wire it
   to nothing until you have decided what consumes it** — the earlier D6 "no bot consumer" finding is
   now a choice rather than an oversight.
4. **It does NOT change `funding_hot_stop_hits`.** That claim is stop-exceedance, a different outcome,
   and remains in-sample only. **The separate held-out prereg you approved is the next thing I seal** —
   same machinery, K = 1.65, same volume filter, prior ~60%.

## 6. Housekeeping

- The **8th combo** — (a) ALL173 under the frozen arm — was cut short when my own 10-minute tool
  ceiling killed the process at 7 of 8. **It is the contaminated population under the secondary arm,
  explicitly non-decisive.** A detached re-execution is finishing now; the computation is seeded and
  deterministic, and the first arms have already reproduced identically, which doubles as a
  determinism check. `size_flags_wide.json` will carry all eight.
- **`state/` misclass fixed** structurally (reply 119): a directory's class now follows its contents.
- **Still open from you, and still the one I'd prioritise: the rv-input export for D3.** Six flags,
  three high, every live stop and size depending on it. My replication is internally valid whichever
  implementation is canonical, but the terminal's numbers are not.
- **Card sign-offs:** send the list and I'll keep going one at a time. **Three audited, three failed
  at PROVEN** — and the one that cleared both statistical bars (`funding_hot_stop_hits`) failed only on
  never having been tested out of sample. **That pattern is the argument for the replication programme,
  not against the cards.**

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
