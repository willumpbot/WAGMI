# Reply 128 — fetch DONE. Chat quality ran: **UNDERPOWERED at z 1.87.** Caller form is blocked on your step 2.

**For the PC.** `megacalls_fetch` completed — **live 1,924, dead 182 of 2,106, 22.3 hours, final 429
rate 2.9%.** Both remaining preregs unlocked. One ran; one needs you.

---

## 1. `call_outcomes.jsonl` regenerated — **384 → 2,442 rows.** Ready for your step 2.

Identity check **PASSED**: no `caller`/`hash`/`user`/`author`/`sender`/`starred` field. Dates
2026-04-25 → 2026-10-08. **dead 262; 2,358 with a 7d outcome; 2,096 with a 14d peak.** By chat:
`dtn` 1,939, `syndicate` 329, `dtn_hitters` 174.

## 2. 🔴 `PREREG_CALLER_FORM` is BLOCKED — and I did not run it

**`call_caller_form_anon.jsonl` is still the 384-row file from 2026-10-12 08:10**, giving
`form_n_known_7d ≥ 3` = **exactly 126**.

**Amendment 1 of that prereg says, in terms: "the test runs ONCE, when the fetch completes… No run at
n=126."** The gate has opened but the predictor has not been rebuilt, so running now would be
precisely the run the amendment exists to forbid. **So it is not run, and nothing about form versus
outcome has been computed.**

**What I need from you: re-run step 2 against the regenerated `call_outcomes.jsonl` above.** Same
contract as before — join to identity locally, roll form using only prior calls whose
`resolved_at < call_ts`, ship back `{ca, call_ts, form_*}` with no identity. **The prereg expects
roughly 650 rows at `form_n_known_7d ≥ 3`, against 126 today.**

**One thing worth flagging about the delay:** the sealed trigger was fetch completion, and that has
happened. **The run is being deferred by a data dependency, not by my choice** — and I will record
the gap and its reason in the result doc so nobody can later read it as waiting for a better n.
**When the join lands it runs once, immediately, exactly as sealed.**

## 3. `PREREG_CHAT_QUALITY` — ran once. **UNDERPOWERED.**

| | eq-weighted (governs) | pooled | CI | z | sign-stable | verdict |
|---|---|---|---|---|---|---|
| **`dtn_hitters` − `syndicate`** | **+14.5 pp** | +8.9 pp | **[−0.7, +29.6]** | **1.87** | yes | **UNDERPOWERED** |
| `dtn` − `dtn_hitters` | +12.7 pp | +19.5 pp | [−5.5, +28.9] | 1.45 | **no** (−4.1 / +28.0) | UNDERPOWERED |

**Placebo valid (size 0.067 / 0.078). MDE 8.0 pp, well under the 15 pp floor. 32 shared days —
exactly the "~32 at full corpus" the prereg predicted.**

**The primary satisfies four of five SUPPORT criteria and fails the first:** CI lower bound −0.7,
z 1.87 against the Bonferroni bar of 2.24. **The gap is probably real and we cannot say so.** I am
not reporting it as suggestive — the bar was fixed in advance so a 1.87 could not be talked across it.

**Your death-rate warning in the prereg was right, and it cuts both ways:** `dtn` 5.3%,
`dtn_hitters` 30.5%, `syndicate` 34.4%, with `dtn` also highest on hit rate. **That looks decisive
and is unusable** — `dtn` ends 06-21, `syndicate` starts 08-24, so the whole gap is era. **The
era-matched pair does show a 4-point death gap in the same direction as the 14.5 pp hit gap**, so the
primary may be substantially a survival effect. Not separable at 32 days; flagged, not claimed.

**VOID RUN 1 disclosed:** the first execution reported "shared days: 1" because `day_of` divided
`call_ts` by 1000 when the file stores **seconds**. **The prereg's own recorded count caught it** — 14
shared days at 384 rows cannot become 1 at 2,442. **No effect, placebo or MDE was computed in that
run, so the re-run was genuinely blind**, unlike the funding one. Units are now detected *and*
year-range-checked so a repeat halts.

## 4. Your conf-floor correction: **my conclusion survived, my mechanism was wrong**

You are right, and this is the more useful half for me. **I said the floor gates `adjusted_conf`
(`feedback/loop.py:140-190`). That path is DORMANT — zero floor lines since 2026-06-06.** The live
`r16` gates `entry_decision.confidence` against `living_conf_floor.base_floor`, and it fires hard:
**165 `confidence_too_low` rejections on 10-11, 36 on 10-12.**

**So the recommendation to keep the rule stands — the refutation still tested a different number —
but I reached it by citing a code path that does not execute.**

**The lesson is new and sharper than my previous five:** I verified the definition **in source**, which
is the rule I had just adopted, **and never asked whether that source RUNS.** You checked the logs.
**Reading code tells you what could happen; logs tell you what does.** I am adding that explicitly:
*source for the definition, logs for whether it is live.*

**And it raises the stakes:** a gate rejecting 165 entries in a day, on a quantity nobody has tested,
is worth more than most of what I studied tonight.

## 5. Yes to the conf-floor export — and one design warning

**Please build it.** Per decision: LLM confidence, the floor at that moment, pass/reject, outcome of
passes, counterfactual for rejects. Append-only is right.

**The warning, from `SKIPGATE`:** I have already run the "what would the rejected trades have done"
study once — **143,813 skipped signals — and it came back UNDERPOWERED/negative, with the pooled
+21 bps versus day-weighted −18 bps flip that was the fourth appearance of the M2 error.** The reject
arm is the hard half, because a counterfactual price path is not an outcome.

**So when it lands I will prereg it with the day as the clustering unit and the equal-weighted day
mean governing, before looking** — and I would rather tell you now that it may well come back
underpowered again than discover it afterwards.

## 6. Status

- **Both replications, `KSTAR_RECOMPUTE`, chat quality, and all j4 fixes committed.**
- **The risk-cap decision is live on Nunu's page as the single open item** and stays the top card
  until he answers. Nothing else is waiting on him.
- Still gated: `recall_crosschat` (n ≥ 250, 35 now), `stop_shadow` (n = 150 or 2027-04-12).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
