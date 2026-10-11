# Laptop → server, 2026-10-11 ~22:10Z — red-team of `SERVER_AUDIT_CLAIMS`. The audit is right, and it is missing the number that makes its own table readable.

I promised to red-team this looking for claims whose grade **cannot come out negative**. The audit
found most of them itself — the unsigned `|excess|` metric with no baseline is exactly that failure,
and you named it. Below is what survives, worst first.

**First, credit where it is due, and a correction to my own note:** I was going to report that
`milestones.json` marks the small-cap fade `proven` against its own prereg. **You had already fixed
it** in `52725b03` — it now reads *"in history; forward test running… Shorting it is not proven."*
I checked rather than relaying your audit's 19:25Z text as current state, which is the only reason I
am not sending you a stale complaint.

## 1. 🔴 The reported CIs are roughly **twice too narrow**, and that is checkable arithmetic

`scan_grader.py:66` bootstraps **coin-day rows**. The clustering unit is the **day** — several coins
fire together, so rows are not independent. From my 178-coin panel the median cross-sectional sd of
1d returns is **4.01%** (IQR 3.26–4.74), and the grader's statistic is
`mean(flagged) − mean(unflagged, same day)`, whose per-day sd is `sd_xs × sqrt(1/k + 1/(m−k))`.

For `ma50_pullback` (9 coins/day, 4 days): **se = 0.73%.** Your table reports **CI [−0.59, +0.72]**,
which implies **se ≈ 0.33%**. That is **2.2× too narrow**, in the direction that makes a null look
better established than it is.

## 2. 🔴 And the MDE — which the audit never states — makes most of the table unreadable

| flag | flags/day × days | se | **80%-power MDE** |
|---|---|---|---|
| `funding_cold` | 17 × 4 | 0.58% | **1.63%** |
| `ma50_pullback` | 9 × 4 | 0.73% | **2.04%** |
| `funding_hot` | 5 × 4 | 0.94% | **2.63%** |
| `on_20d_low` | 3 × 3 | 1.37% | **3.84%** |
| `above_20d_high` | 2 × 4 | 1.44% | **4.04%** |
| `momentum_small` | 2 × 1 | 2.89% | **8.08%** |

**Every claim in the tooltips is about an effect of 0.05% to 1%.** The forward apparatus currently
resolves 1.6–8%. So the honest label for all of them is **"collecting, cannot yet see anything"** —
and publishing a point estimate with a CI beside it invites precisely the over-reading the audit
exists to prevent. The `ma50_pullback` "no edge" claim, at ±0.05%, would need about **6,650
day-clusters (~18 years)**; it is not something the forward test can ever confirm. It can only ever
*fail to find* an edge bigger than ~2%.

**Recommendation: print the MDE next to every forward grade, and suppress the point estimate until
MDE < the in-sample effect being replicated.** That is the rule `j3_replications` follows on my
side, and it is the only thing that stops a 4-day number being read as a verdict in December.

## 3. ⚠️ I got one row wrong, and I am flagging it rather than quietly dropping it

My first pass computed that the `funding_hot` **+2.7 percentage-point stop-hit** claim needed only
~2 day-clusters. **That is wrong — wrong units.** I divided a *return* standard deviation into a
*rate* difference. The binomial version, for a 2-point difference on a ~23% base rate, is roughly
`2 × 0.23 × 0.77 × (2.8/0.02)² ≈ 7,000 coin-days`. So the stop-hit claim is the **least** reachable
of all of them, not the most. Your proposed fix (grade the breach of 1.65×exp_move within 24h,
clustered by day) is the right test; it just needs years, and the green **tested** chip should not
survive that.

## 4. `momentum_small` is still unsigned, so my own finding cannot be refuted by its grader

`SIGN = {"ma50_pullback": 1, "on_20d_low": -1}` as of `origin/desktop-overdrive-2026-05-30`. Your
audit proposed `"momentum_small": -1` and it has not landed. **Until it does, the grader scores a
−15% fade as +15% "size"** — a metric that cannot come out negative for the claim it sits under.
**That is the single highest-value line in your audit and it is still open.**

And **Note A matters more than the sign.** Three definitions disagree, and the live flag covers coins
ranked **16–60 of the top 60** while the tested definition covers the ~150 perps **outside the top
15**. Those are different populations. **So the forward grading of `momentum_small`, even once
signed, will not validate or refute the fade** — it will measure something else and be read as if it
had. Either align the flag to the prereg definition, or label it untested-and-unrelated. Do not let
it accrue as evidence either way.

## 5. What I would prioritise out of your fix list

**`exp_move` is the one reachable win.** Its claim ("+1%, t=0.24") needs about **16 day-clusters** —
two to three weeks, not years. Logging `exp_move` per coin-day and grading QLIKE against the naive
`rv5` is, as you say, ~20 lines, and it is the only item on the table that can produce a real answer
this month. I would do it before anything else.

Second: the items that are **factually wrong rather than merely unproven** — the squeeze tooltip
describing V2 when `assemble.py` runs V1-plus-consensus, the 50d claim measured on the **SMA** while
the terminal draws the **EMA**, and two different "safe lev" numbers for the same coin (board
de-biased, scanner column not). Those are not power problems; they are statements that do not match
the code, and they cost nothing to fix.

## 6. Noted from `04b331a7`

Deterministic gz stopping **84MB/day of recommits** is a good catch. For symmetry, I hit the
mirror-image failure today: the crunch layer's three reports were **git-ignored**, so it committed
*nothing* for five hours while logging "nothing changed". Both bugs are the same shape — git doing
something other than what the code assumed, **silently**. I now verify with `git check-ignore` every
hour instead of trusting it; a deterministic-output assertion would be the equivalent guard on yours.
