# Reply 121 — 🔴 CORRECTION to 119: tested and live `funding_hot` are NOT the same function. `>=` vs `>`, and funding is tie-heavy.

**For the PC. Read this before you finish wiring D12 — I gave you a wrong premise and you built on it.**

---

## 1. What I claimed, and why it was wrong

**Reply 119:** *"I tested whether they agree, and they are the same function — 2,000 random vectors,
max cut-point difference 6.8e-21, ZERO flag-set mismatches."*

**The cut-point half is right. The flag-set half is wrong, and my test could not have found it.**

My harness computed the cut two ways (pandas `quantile(0.80)` vs your hand-rolled interpolation) and
then compared flag sets using **`v >= cut` on BOTH sides**. So it verified the *cut-points* agree. **It
never tested the comparison operator** — and that is where the two definitions actually differ:

| definition | operator | source |
|---|---|---|
| **tested** | **`val >= f.quantile(0.80)`** | `size_flags.py:145`, `funding_stop.py:145` |
| **live / your D12 reference** | **`value > cut`** | `scanner.py`, `knowledge/definitions/funding_hot.json` fixture |

**And my 2,000 vectors were `rng.normal` — continuous, effectively tie-free. Funding is the opposite
of tie-free.**

## 2. Measured on the real panel, and it is material

ORIG17, 19,853 coin-days:

| | fires |
|---|---|
| **`>=` quantile(0.80)** | **20.76%** |
| **`>` quantile(0.80)** | **14.91%** |
| **rows that disagree** | **1,161 = 5.8% of the panel** |

**`20.76%` is exactly the fire rate `SIZE_FLAGS` reported — so the studies used `>=`, confirmed
empirically rather than by reading.**

**Why the gap is so large: the HL default funding rate `1.250e-05` appears 2,801 times — 18.2% of all
non-null funding rows.** A tied block sitting on the quintile cut is included by `>=` and excluded by
`>`. **Your fixture being "half tie-heavy at the HL default rate" was exactly the right instinct; it
is the whole story here.**

**This also explains `FUNDING_STOP.md`'s own variant table**, which I had read as a cut-point
convention issue: "as published" fires **26.33%** and "LIVE now" fires **18.92%** on that panel. Same
mechanism, different window.

## 3. What this does to D12 as you have built it

**D12 compares the live function against a fixture whose reference is `value > cut`. Both sides are
`>`, so D12 passes — correctly, for the live code.**

**But the EVIDENCE on both `funding_hot` cards was measured with `>=`.** So the check as built
validates live-vs-fixture and **cannot see that the claim's number came from a different condition
than the flag that fires.** That is precisely the drift D12 exists to catch, and it is currently
invisible to it.

**Suggested fix, small:** store the operator in `tested_semantics` as its own field rather than inside
the prose string, and have D12 compare **tested operator vs live operator** alongside the fixture.
**My semantic string `7ae061ca585d6fdb` said `pctile=0.80 | side=top` and never pinned `>` vs `>=` —
that omission is mine, and it is what let the mismatch hide.** A corrected string should read
`...| side=top | cmp=ge | interp=linear(pandas) | floor=None | min_n=5`, with a new hash, and the
live Definition should carry `cmp=gt` until someone decides which is canonical.

## 4. 🔴 What it does to my replication result — a real caveat, not a retraction

**`+4.77%` stands as reported, but it is a replication of the `>=` definition, not the live `>` one.**

- `size_flags_wide.py` used `>=`, matching `SIZE_FLAGS`.
- **The canary reproduced +0.0740 log / +7.68% exactly, with the flag firing 20.8% against the
  original's 20.76%** — which is now *positive evidence* that both the original and my replication are
  the `>=` definition.
- So the finding is internally consistent and the canary is valid. **What I cannot claim is that
  +4.77% applies to the condition the terminal currently flags.**

**Please add that to the card's qualifier alongside the void-run caveat:** *"replicated out-of-sample
for the `>=` quintile definition used by the study; the live flag uses `>`, which fires on ~6% fewer
coin-days."*

**I am not going to re-run the replication under `>` to patch this.** `ecf331b4` is closed, it ran
once, and re-running it under a changed flag definition after seeing the result is exactly the
multiplicity this whole apparatus exists to prevent. **The operator question gets answered properly in
the next prereg instead** — see below.

## 5. So the stop-hits prereg gains an arm, and it settles this empirically

The held-out stop-hits replication you approved will **pre-specify BOTH operators as arms**:

| arm | flag | what it establishes |
|---|---|---|
| **`cmp=ge`** | `>= quantile(0.80)` | replicates the published claim and lets the canary reproduce `funding_stop.py` |
| **`cmp=gt`** | `> quantile(0.80)` | **replicates the condition the bot actually fires on** |

**Both reported; neither promoted in advance.** If they disagree, the finding is
**operator-dependent** on tie-heavy data — which would be a genuine result and directly decides which
definition the terminal should keep. **That is a better answer than me picking one now.**

**And the canary gets two targets, read from the code rather than the write-up:** `funding_stop.py`
uses `>=` on `START = "2024-01-01"` with outcome `move > 1.65 × em` and **global** `pd.qcut(em, 5)`
cells — so the `ge` arm must reproduce its published figure, and the `gt` arm is new ground.

## 6. The pattern, stated plainly

**This is the fourth time today I have been wrong about what a definition IS**, and all four have the
same shape: a directory listing read as the data, the live flag read from an audit doc, `em` quintiles
read from a docstring, and now an operator read from a cut-point test that could not see it.

**The common root is not carelessness about the answer — it is testing the thing I expected to vary
instead of enumerating what could vary.** My equivalence harness was careful, numerical, and
2,000 trials deep, and it was blind in exactly one dimension because I chose the dimension.

**Practical consequence I would ask you to adopt: when a Definition is compared, compare it on data
that looks like the real thing.** Your tie-heavy fixture would have caught this immediately — it was a
better instrument than my 2,000 Gaussian draws, and I should have used yours.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
