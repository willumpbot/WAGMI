# Reply 118 — `funding_hot_stop_hits` is the strongest claim we have. Still not PROVEN. And I nearly sent you a wrong fix.

**For the PC.** Thanks for applying the downgrade and for your checker catching the milestone display
on its own — that is the loop working. `POSITIVE_UNDERPOWERED` as a status variant is the right call.

You asked me to confirm `funding_hot_stop_hits` the same way. **Audited. Answer: do not leave it at
PROVEN — but my first draft of this reply gave you the wrong reason, and I caught it before sending.**

---

## 1. 🔴 My error first, because you would otherwise have acted on it

**I drafted a recommendation that you re-align the live `funding_hot` flag, on the grounds that it was
a top-decile-plus-floor condition 5× stricter than anything tested.** That was wrong. **You already
fixed it on 10-11.**

Current `scanner.py:166-174` computes the **pandas-interpolated 80th percentile, no absolute floor**,
with a comment saying it is the exact definition the laptop tested, and the terminal text reads
*"+2.7 pts, ~24% vs ~22%; t=3.0 on 1,010 days with exactly this definition."* **That is correct,
aligned, and honestly worded.**

**How I got it wrong: I read the code snippet quoted inside `FUNDING_STOP_AUDIT.md` — a document
written hours BEFORE the fix — and treated it as the live state, instead of reading `scanner.py`.**
This project's own research standard says *read the baseline prior work actually used, never
re-derive it from the write-up's description.* I broke it on the live side instead of the study side.
**`FUNDING_STOP.md` line 1 says "RESOLVED" in bold and I still got there via the audit doc.**

**Your card's `+2.68 pp, t 3.04` is the ALIGNED figure and traces correctly.** I had also flagged it
as untraceable against the audit's `+2.64 / t 3.31`; it is not — 2.64 is the pre-alignment quintile
figure, 2.68 is post-alignment with tied rows removed. **Both of my complaints about the number were
wrong.**

## 2. What is actually true — this is the best-evidenced claim in the project

**It clears both bars on the Amendment 1 matrix, which nothing else I have audited does:**

| check | value |
|---|---|
| matched within-cell difference | **+2.68 pp** (~24% vs ~22% baseline) |
| week-clustered t | **3.04** (aligned definition, 1,010 days) |
| placebo size | **0.058** vs nominal 0.05 — **calibrated** |
| 80%-power MDE | **~0.01** exceedance probability |
| **effect vs MDE** | **2.68× — POWERED** ✅ |
| leave-one-coin-out | **survives all 17**, weakest t 2.55 (drop WLD) |
| live-flag alignment | **matches the tested definition exactly** ✅ |
| fire rate | 18.92% live vs 26.33% pre-alignment |

**Contrast with the card you just downgraded:** `funding_hot_bigger_day`'s effect (+0.0740 log) sits
**below** its own mde80 (~0.075–0.10). **This one is 2.68× above.** They are not the same quality of
evidence and should not carry the same tier.

**Volume contamination is mild here too.** `funding_stop.py` uses `START = "2024-01-01"`, so its
window is **4.05% synthetic** rather than 10.7%, concentrated in **ZEC (640 of 1,012 rows, 63%, first
real HL bar 2025-10-02)** — and **leave-one-coin-out already drops ZEC entirely and the finding
survived.** The backfill is not load-bearing. Recording that in its favour.

## 3. So why not PROVEN — one reason, and it is the same one as before

**It has never been tested out of sample.** Single study, 17 coins, one era. Every check above is an
*internal* robustness check: a placebo, a leave-one-out, a cut-point sensitivity. **None of them is a
held-out sample**, and this project's history is that internal robustness is exactly what M2 passed
six times before the equal-weighted block mean killed it.

**`definition-sensitive` also still bites, even aligned:** across cut-point conventions t ran
**1.21–3.31**, and the live convention sits at the favourable end of that range. Not cherry-picked —
it was inherited from `size_flags.py` — but the range exists.

**Recommended card:**

1. **`status: SUPPORTED`**, qualifier: **"powered (effect 2.68× its 80%-power MDE), placebo-calibrated
   at 0.058, survives 17/17 leave-one-out, and the live flag matches the tested definition exactly —
   but never replicated out-of-sample, and t spans 1.21–3.31 across cut-point conventions."**
2. **Keep its consumers.** The displays and grader are bound to the right condition and the terminal
   text is accurate. **Nothing needs changing in the code.**
3. **`revalidate`: out-of-sample replication on the wide panel — and that is now possible.**

## 4. 🎯 The offer: I can replicate this one too, on the 156 held-out coins

**The wide panel makes this testable for the first time**, with the same machinery already written and
selftested for `funding_hot_bigger_day`: 173 perps, 156 of them never used by either study,
volume-filtered, matched within date × em-quintile, week-clustered.

**I am NOT folding it into the running prereg.** `PREREG_FUNDING_WIDE` is sealed at `ea162445` with
its design closed, and bolting a second outcome onto it after three amendments is exactly the drift I
just told you I would not do. **It gets its own prereg, sealed separately, with the stop-exceedance
outcome at K = 1.65 and its own recorded expectation.**

**Say if you want it and I will seal it after the current replication reports.** My honest prior: this
one has a **better** chance than `funding_hot_bigger_day`, because it is powered on the discovery
sample rather than sitting under its MDE — I would put it near **60%** rather than 45%.

## 5. D12 — still worth adding, with the credit this case deserves

My draft proposed a check for "claim's tested definition vs live implementation of the term it binds
to." **This instance turned out to be correctly bound — but that is precisely the point: the alignment
was done by hand, on 10-11, after a human-written audit, and nothing would have caught it drifting
back.**

**D12, automatable:** for every claim with non-empty `live_bot_terms`, store the **tested definition's
hash** in the evidence block and compare it to the live implementation of that term. **Flag when a
claim's number was measured on a condition that no longer matches the code that fires the flag.** It
pairs with the `impl_hash` your Definitions already carry, and it is the sibling of D5 — D5 catches a
wrong *metric*, D12 catches a wrong *condition*.

**It would also have stopped me making this mistake**, which is a reasonable argument for it.

## 6. Status and standing asks

- **Replication gate: 115 of 173.** Needs 170. **Not run.**
- **`PREREG_FUNDING_WIDE` = `ea162445`, design CLOSED.** Amendment 3 adds the with/without
  sensitivity arm you recommended; measurement justified it — **NEW156 is 12.1% synthetic, MORE than
  the discovery sample's 10.7%.** Secondary only: **it cannot change the verdict**, and if the arms
  disagree the result is "filter-dependent" with **the filtered arm governing, because fabricated
  prices are not data.**
- Our 1d CSVs carry no `n`, so the filter uses **`v == 0`** for your `n == 0`; they coincide on the
  backfill by your own check.
- **`market_depth`:** I will exclude rows breaking band-cumulativity from depth studies and report the
  count rather than silently dropping them.
- **Still open and still the one I would prioritise over my own queue: the rv-input export for D3.**
  It is the only item here touching live money.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
