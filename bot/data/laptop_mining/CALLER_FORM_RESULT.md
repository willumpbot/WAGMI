# Caller form — **UNDERPOWERED.** And the sign flips depending on how you weight callers.

**`PREREG_CALLER_FORM_2026-10-12`, sha `4c9a5f26` (sealed `60e17310` + Amendments 1 and 2), run
ONCE.** Read in the prereg's order: placebo → MDE → counts → only then the effect.

**Recorded expectation: "UNDERPOWERED with a small positive", strengthened in Amendment 2 E to "the
leave-one-out check will probably BE the result." Both landed.**

---

## 1. Is the test valid? — placebo

**Form-shuffle within call-day cells, 2,000 draws: size 0.033.** Inside [0.02, 0.09], so the test is
correctly sized and everything below means what it says.

## 2. MDE

**8.0 pp**, against the pre-committed 15 pp floor. **So power was not the disqualifier** — the test
could have detected an 8-point effect and there isn't one.

## 3. Counts, and the effective sample

| | |
|---|---|
| raw eligible human rows | **1,478** — *prohibited by Amendment 2 as "the sample size"* |
| distinct caller clusters | **54** |
| **Kish effective n** | **7.5** |
| largest cluster | **424 rows = 29% of eligible** |
| top 3 clusters | 424, 258, 142 |
| call-days | 101 |

**1,478 rows are 7.5 effective units.** Every number below has to be read against that, which is the
whole reason Amendment 2 exists.

*(1,528 eligible rows in the server's file; 50 did not join to a resolved outcome and were dropped.)*

## 4. 🔴 The result — and the sign depends on the weighting

| estimator | effect |
|---|---|
| pooled | **+2.4 pp** |
| equal-weighted over **call-days** | **+2.7 pp** |
| **equal-weighted over CALLERS** | **−9.1 pp** |
| **CALLER-clustered CI (GOVERNS)** | **[−3.1, +12.0], z 0.62** |
| day-clustered CI (secondary) | [−2.9, +8.0], z 0.85 |

**VERDICT: UNDERPOWERED.** The governing CI spans zero, z is 0.62 against a 2.24 bar, and the point
estimate (+2.4 pp) sits below the 8.0 pp MDE — "positive but below MDE", which the prereg explicitly
classes as UNDERPOWERED.

**🔴 The finding that matters more than the verdict: +2.4 / +2.7 / −9.1.** Pooling and day-weighting
give a small positive; **weighting callers equally gives a NEGATIVE nine points.**

**Without Amendment 2 this document would have reported "+2.7 pp, a small positive, underpowered" and
nobody would have seen the −9.1.** The sealed design clustered on the call-day, which cannot see
caller concentration because one caller spans many days.

**This is the M2 error again** — the pooled figure follows the largest unit, and the equal-weighted
figure answers the question actually asked. **It is now the most frequently recurring defect in this
project, and the server's concentration flag is the only reason it was caught this time.**

## 5. The structure underneath — large callers positive, small callers negative

| check | result |
|---|---|
| drop the top 1 caller | **+7.4 pp, z 2.11** (1,054 rows left) |
| drop the top 3 callers | **+9.1 pp, z 1.91** (654 rows left) |

**Dropping the dominant caller RAISES the effect and nearly reaches significance.** So the top caller
is **diluting** a positive, not creating one — the opposite of what I expected when I wrote the
leave-one-out check.

**Reconciling that with the −9.1 pp caller-mean:** leave-top-out recomputes a *pooled* figure, which
is then dominated by the next-largest callers. The caller-mean weights all 40 two-armed clusters
equally and **the many small callers skew negative.**

**So the honest structure is: a few high-volume callers show a positive form effect; the long tail of
low-volume callers does not, and may run the other way.** With 7.5 effective units there is no way to
tell whether that is real heterogeneity or noise. **It is a hypothesis for a future test with more
callers, not a finding.**

## 6. Sign stability — technically "yes", substantively weak

| half | effect |
|---|---|
| first | **+0.2 pp** (1,256 rows) |
| second | **+17.7 pp** (222 rows) |

**Both positive, so the sealed criterion passes — and I am not going to let it stand unqualified.**
+0.2 pp is indistinguishable from zero, and the halves are split at the median call-DAY, which here
puts **1,256 rows in the first and 222 in the second** because call volume is heavily front-loaded.
**A criterion satisfied by +0.2 versus +17.7 on a 6:1 row imbalance is not telling us much.**

## 7. Chat-only placebo — clean

**Replacing form with the caller's chat gives +0.7 pp, z 0.14.** **So this is NOT a chat-quality
effect wearing a caller label** — the one placebo that could have unmasked the whole thing as
mislabelled, and it comes back empty.

## 8. 🔴 Deviation under §9 — the time-reversal placebo was NOT run

**§7's second placebo requires recomputing each call's form from SUBSEQUENT outcomes. That needs a
server-side identity join I do not have and did not request in time.**

**Its effect on the number: none.** The pre-committed rule, written into the script before the run,
was that if the result came out **positive and powered** the script would HALT without claiming
SUPPORT and the reversed-form join would be requested — because SUPPORT requires all three placebos.
**The result is UNDERPOWERED, so the missing placebo cannot change the verdict.**

**If this question is ever re-run, the reversed-form join must be requested up front.**

## 9. Two deferrals, recorded so neither reads as peeking

**The sealed trigger — fetch completion — fired 2026-10-13 ~06:40.** The run then waited twice:

1. **the server's step-2 join had not been rebuilt** for the 2,442-row corpus (it was still the
   384-row file giving exactly the n=126 Amendment 1 forbids);
2. **the opaque `caller_cluster` key did not exist**, without which the corrected clustering unit was
   unavailable.

**Neither was my choice, and no form × outcome quantity was computed before this run.** Both are
recorded in the prereg itself.

## 10. Scoring the expectation

| predicted in advance | outcome |
|---|---|
| **UNDERPOWERED** | ✅ |
| a **small positive** point estimate | ✅ +2.4 pp pooled — though the caller-mean is −9.1 |
| **"the leave-one-out check will probably BE the result"** | ✅ it is the most informative row in the document |
| MDE would exceed the 15 pp floor | ❌ **8.0 pp.** Fourth time tonight my power pessimism was wrong in the same direction |

## 11. What this does and does not say

**Does NOT say:** callers have no skill. **It says 7.5 effective callers cannot resolve it**, and that
the answer changes sign with the weighting, which is what "we don't know" looks like when written
honestly.

**Does say, firmly:** **nothing here justifies acting on caller form.** §9 of the prereg already ruled
out a trading recommendation even on SUPPORT, on cost grounds — a $500 ticket exceeds 24% round trip
on the median pool. **With an underpowered and sign-unstable result, that holds with far more room to
spare.**

**What would settle it: more callers, not more calls.** The corpus is complete; 1,478 rows bought
nothing that 54 clusters could not. **A future version needs breadth across callers, and the server's
`caller_cluster` id makes that measurable without ever naming anyone.**

## Limits
- **Kish effective n 7.5.** Never quote 1,478 as the sample.
- Dead rows count as outcome FALSE and were never dropped.
- `form_n_known_7d ≥ 3` as sealed; the `≥ 5` sensitivity cut was pre-approved but is moot at this power.
- Bot rows carry null form by construction, so the bot/human split of §5 has an empty bot arm — reported, not hidden.
- Time-reversal placebo not run (§8).
