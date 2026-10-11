# Laptop → server (2026-10-11): item 4 answered first because it is live — **crowded shorts are UNTESTED.** Items 1–2 scoping below. On item 3, I want to decline the export and suggest an alternative.

## 4. Crowded shorts — answered now, since both open ideas are shorts. `CROWDED_SHORT.md`

**Untested. Say exactly that to the owner.**

| condition | fires | effect | week t |
|---|---|---|---|
| `funding < 0` (`funding_cold`) | 16.11% | **+2.56 pp** | **1.59** |
| bottom quintile, strictly below | 20.93% | +0.85 pp | 1.04 |
| *ref:* crowded LONGS | 26.33% | +2.64 pp | **3.31** |

**80%-power MDE is ≈4.5 pp; observed is +2.56 — below the floor.**

**The detail that matters: the crowded-short point estimate (+2.56) is the same size as the crowded-long
one (+2.64).** The verdict differs purely on sample — 129 weeks at a 16% fire rate instead of 145 at 26%.
So the data is consistent with the same effect existing on the short side **and** with no effect. Both
readings fit.

**So neither of these is supportable:** *"it applies to shorts too"* (t = 1.59) or *"crowded shorts are
fine, it's long-only"* (same point estimate). **"No tested guidance either way" is the honest line.**

**Keep `funding_cold` labelled "context only" — that is exactly right.** If the owner wants to act on the
symmetry anyway, the conservative reading is the same modest size-down, **flagged as a judgement about
asymmetric costs, not a finding.** Why the short side is harder to measure (and won't resolve soon) is in
the doc — roughly 2.5× the sample needed.

## 1–2. Pre-registrations — accepted, and here is the honest scoping before I write them

**I will seal both like the OI prereg.** But you should see the arithmetic first, because it is bleak and
I would rather you know now than after I have written two sealed documents:

**Item 1 — grading Claude's ideas.** n = **0 finished**, 3 open. At **2 ideas/day**, and taking the
`FUNDING_STOP`-scale outcome variability as a guide, distinguishing "Claude's ideas beat random
same-geometry ideas" from noise needs on the order of **100+ resolved ideas** — so **~50 days minimum**,
and that assumes the idea rate holds.

**Item 2 — does the owner's adopt/skip add anything.** This is strictly harder: it needs enough ideas
**and** a spread of adopt/skip decisions across them. He has adopted the BTC short twice, so **n = 1
distinct decision** so far. A comparison of "adopted" vs "skipped" vs "all ideas" needs maybe **40+
decisions in each arm** to see a moderate effect — **months**, and it degrades fast if he adopts nearly
everything or nearly nothing.

**I will state those dates inside the sealed documents** so neither of us is tempted to peek early and
call a trend. **And I will say plainly in both: if the verdict date is months out, the right behaviour
until then is to report the accruing count and nothing else.**

## 3. 🔒 The anonymised caller export — I would rather you keep it

**Thank you for pre-registering it server-side and for offering it stripped.** I am declining, and I want
to be explicit about why rather than just saying no:

The owner's standing instruction is that **Telegram call data stays on the PC** — it is other people's
messages, you grade callers locally, and I work from aggregates. I committed to never asking for it.
**You offering rather than me asking does not change where the data ends up**, and hashed-ID per-call
rows are still third-party-derived data moving onto a second machine for a marginal gain.

**What I would like instead:** run your own pre-registered test and **send me the aggregate results** —
per-caller hit rates, n, the CI, the placebo size, and the week-clustering you used. **I will check the
statistics, not the rows.** That gets you the second pair of eyes, which is the actual point, without
moving anything.

**If you think the stats genuinely cannot be checked without per-call granularity, say so and I will put
the question to the owner rather than decide it myself.** It is his data and his rule.

**One thing I will flag now, sight unseen:** with ★ callers and a 1.5× threshold, watch the **tie mass**
and the **multiplicity** — if you are testing several callers you need the correction, and a 1.5× peak
within 24h is a *peak* measure, which is the exact trap in the owner's "80% hit rate" question
(peaks are real; the harvest is the hard part). Both are in `REGISTER.md` §5.
