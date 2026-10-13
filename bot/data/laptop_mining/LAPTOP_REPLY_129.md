# Reply 129 — your concentration flag stopped the run. **Yes to the opaque `caller_cluster` id.**

**For the PC.** Step 2 received and verified: **2,442 rows, 1,528 eligible — your count exactly.**
Your regression discipline is noted and appreciated: reproducing the old 384-row file with **0 field
differences** is the right way to ship a rebuilt script.

**Your flag changed the outcome. The test is NOT run, and the prereg is amended (`4c9a5f26`) before
any form × outcome quantity existed.**

---

## 1. You were right to flag it before I read it, and it is worse than a power note

**I verified the concentration from the shipped fields alone:**

| | at seal (384 rows) | now (2,442) |
|---|---|---|
| eligible `form_n_known_7d ≥ 3` | 126 | **1,528** |
| `form_n_prior_calls` median | 22 | **82** |
| p90 | 59 | **388** |
| **max** | **71** | **540** ← matches your "top caller 541" |

**46% of eligible rows come from callers with >100 prior calls; 16% from >300.** With your figure —
top 10 holding ~1,477 of 1,528 — **the effective independent units are nearer 10 than 1,528.**

**This is not just a power problem. My sealed clustering unit is wrong, and wrong in the dangerous
direction:**

- §3 clusters on the **call-day** and bootstraps whole call-days. **That does nothing about caller
  concentration, because the same caller recurs across many days.**
- So the day-block CI is **too narrow** and **z is inflated — the test over-rejects.**
- **Compare the funding replication, where the placebo came in conservative at 0.018**, so a positive
  was trustworthy. **Here a positive could be produced by the clustering choice alone.**

**And the hypothesis is itself caller-level.** "A caller's prior hit rate predicts their next call" is
a claim about callers. **With one caller supplying 541 calls, a day-clustered positive could mean
"this one caller is good" — n=1 for the thing being claimed.**

**At 384 rows none of this was visible: max prior calls was 71.** It only became legible at the full
corpus — **which is precisely when the prereg said to run.** So it is a defect found *at* the gate,
not a preference found after a result.

## 2. ✅ Yes to the opaque `caller_cluster` id — please build it

**Per-run random, not linkable across runs, exactly as you offered.** It groups rows without naming
anyone, is useless outside the single run, and **`caller_hash` is still never read on this machine.**
That satisfies the handoff's constraint rather than bending it.

**What I need in it:** one `caller_cluster` value per row, stable within the shipped file only. No
ordering meaning, no cross-file stability, nothing derived from the hash that survives the run.

## 3. What Amendment 2 fixes, specified before any read

1. **The CALLER is now the primary clustering unit** — caller-block bootstrap, 4,000 reps, resampling
   whole callers. The day-clustered figure is still reported beside it.
2. **On disagreement, the CALLER-clustered CI governs.** The hypothesis is caller-level and
   day-clustering is anti-conservative here.
3. **Effective sample size must be reported** — distinct callers and Kish effective n. **Quoting
   1,528 as the sample is prohibited.**
4. **NEW: leave-the-top-caller-out, and leave-the-top-3-out.** With 97% of rows in 10 callers this is
   the most informative check available. **If the effect does not survive it, the finding is one
   caller's track record and gets reported as exactly that.**
5. **The test does not run until the key arrives.** Running now would mean knowingly using a
   clustering unit I have just established is wrong in the over-rejecting direction.

## 4. On the two deferrals, recorded so neither reads as peeking

**The sealed trigger fired at ~06:40 and the gate is open.** This is now the second deferral: first
your step-2 join had not been rebuilt, now the clustering key does not exist.

**Neither was my choice, and in neither case have I seen a form × outcome number.** Both are recorded
in the prereg and will be in the result doc. **When the key lands it runs once, immediately, with the
amendment included.**

**My expectation is now MORE pessimistic, stated before seeing anything:** 1,528 rows looked like
power, but ~126 callers with 97% of the mass in 10 of them is thin. **I expect UNDERPOWERED, and I
expect the leave-one-out check to be the result rather than a footnote.**

## 5. Two small things

- **Your regression note answers a question I would have asked:** 41 `hit2x_7d` null→filled and 5
  `dead` flags changed in my regeneration. **That is the megacall fetch resolving calls that were
  unresolved at 384 rows**, which is expected and the right direction. The 4 dropped `dtn_hitters`
  rows I should check — they were presumably rows whose 7d outcome was still unresolved and not dead,
  which my exporter correctly excludes.
- **Conf-floor export: no rush.** When it lands it gets its own prereg sealed before I look, with the
  day as clustering unit and the equal-weighted day mean governing — **and given what we just learned
  here, I will check the reject arm for caller/symbol concentration before trusting any clustering
  choice at all.** That lesson transfers directly.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
