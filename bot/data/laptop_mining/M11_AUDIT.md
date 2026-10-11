# Audit of Mission 11 (`LEVELS.md`) — the design is good. ⚠️ The cluster unit binds nothing, and two of the three findings do not survive multiplicity.

_2026-10-11. First review this doc has ever had. No refit — this audits the stated inference._

---

## What this doc got right, said first because it is most of the doc

- **Random-date pseudo-levels at the same distance** as the real level. That is the correct null and it
  is the single best methodological choice in this folder.
- **A block bootstrap**, not a textbook formula (`levels.py:158`).
- **Train/test split** at 2025-06-01.
- **Everything in expected daily moves**, so a touch means the same on BTC and a meme.
- **It states that the modal outcome is neither** — 28–37% of touches do nothing — which kills the
  "it breaks or it bounces" framing honestly and without being asked.

This is a better-built study than Mission 9. The two problems below are specific.

## ⚠️ Problem 1 — the bootstrap clusters on `(sym, day)`, which holds ~1 touch

**I initially wrote that these were plain binomial CIs. That was wrong about the mechanism** — the
script does block-bootstrap. The issue is the cluster *unit*.

A touch is `|price − level| ≤ 0.5 em` **for one coin on one day**, so each `(sym, day)` key contains
about **one** observation. Resampling clusters of size 1 is arithmetically the same as resampling
touches. The evidence is direct: **their bootstrap CIs match a plain binomial CI to within 0.5 pp on
every cell I checked**, which only happens when cluster size ≈ 1.

| cell | n | binomial CI | published CI |
|---|---|---|---|
| lo20 from below | 263 | [41.9, 53.9] | [41.8, 54.4] |
| lo20 from above | 406 | [37.1, 46.7] | [37.2, 46.8] |
| ma50 from above | 701 | [28.6, 35.6] | [28.8, 35.8] |
| hi20 from below | 548 | [36.4, 44.6] | [36.7, 44.5] |

**The correlation that matters is left uncontrolled, in two directions:**

1. **Across coins on the same day.** One market move puts many of the 11 coins at a 20-day low
   simultaneously, and their outcomes then share that move. **The right cluster is `day`.**
2. **Within a coin across consecutive days.** A downtrend produces a *run* of touches whose outcomes
   share one trend. Each currently lands in its own cluster.

At 11 coins, a day-level cluster gives design effect `1 + 10ρ`:

| ρ across coins | design effect | CIs widen by |
|---|---|---|
| 0.2 | 3.0 | 1.73× |
| 0.4 | 5.0 | 2.24× |
| 0.6 | 7.0 | 2.65× |

For price levels ρ is plausibly at the higher end — the M10 audit measured 0.33 for *funding*, and
price moves co-move harder than funding does.

## ⚠️ Problem 2 — six cells were tested and none was adjusted for it

3 levels × 2 approaches = **6 tests**. Bonferroni at 0.05 two-sided needs **|z| > 2.64**.

| cell | effect | z as published | 6-test Bonferroni | z at day-cluster deff = 3 |
|---|---|---|---|---|
| **lo20 from below** | **+9.4** | **3.05** | **clears** | 1.76 |
| lo20 from above | +5.3 | 2.16 | **fails** | 1.25 |
| **ma50 from above** | **−4.4** | **2.50** | **fails** | 1.44 |

**As published, only `lo20` from below clears the bar. At a day-level design effect of 3 — modest for
11 correlated coins — none of the three remain significant.**

## 🔴 The consequence that matters operationally

The doc's headline is *"Two of the three flagged levels carry real information… The 50-day average IS
support when approached from above — the only level that holds better than chance."*

**That ma50 claim is the weakest of the three at |z| = 2.50, it fails a 6-test correction, and it is the
one feeding a terminal change.** `COMMAND_CENTER.md` records that `levels.py` "validated the **simple**
50-day average while the scanner flags the **EMA** (a real bug)" — so a config change is resting on the
least robust cell in the table.

**I am not saying the ma50 effect is absent.** −4.4 points in the direction folklore predicts, on n=701,
is a reasonable prior. I am saying **it is not established at the confidence the doc asserts**, and
"the only level that holds better than chance" overstates a cell that does not survive its own table's
multiplicity.

## 🔧 What to do

1. **Re-bootstrap clustering on `day`**, not `(sym, day)`. One-line change to `boot_rate`'s key. That
   alone gives the honest CIs.
2. **State the 6-test correction** and relabel accordingly. On current numbers that leaves
   **`lo20` from below as the only candidate finding** and demotes the other two to "suggestive".
3. **The SMA-vs-EMA terminal fix is still probably right** — but justify it on the grounds that the
   scanner should flag the level that was *tested*, not on "the 50-day average is proven support."
   Those are different claims and only the first is safe.
4. **Keep the random-level null design unchanged.** It is the best thing here.

## What survives regardless

- **`hi20` is noise.** The CI covers the null both ways, and widening it only reinforces that. The
  honest caption remains "no edge here."
- **A third of touches do nothing.** That is a descriptive fact about 2,955 touches, not an inference.
- **`lo20` breaking more than random** is the largest effect in the table and the only one to clear
  multiplicity as published. Direction — *a 20-day low is not a bounce level* — is the finding I would
  keep, with the magnitude held loosely.

## Limits of this audit
- **No refit.** ρ across coins for level touches is *assumed*, not measured; `levels.json` stores
  summaries rather than per-touch rows, so I could not compute the design effect directly. The 1.73–2.65×
  widening is therefore indicative. **Measuring it requires only re-keying the existing bootstrap**, which
  is recommendation 1.
- Bonferroni is conservative; a less blunt correction would be kinder to the ma50 cell. The point stands
  that *no* correction was applied.
- I did not re-examine the touch/break/reject definitions, which look sound.
