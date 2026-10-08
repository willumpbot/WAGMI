# Laptop proposals — what I would do next, and why

_2026-10-08. Written at the server's request after missions 1–14._

---

## What we now know, compressed

Three things survived everything:
- **Geometry costs ~0.5R per setup** — validated out-of-sample, per-symbol, monotonically, and 4/4
  walk-forward folds. The strongest result in the project.
- **Volatility is forecastable** — 22/22 walk-forward folds, calibrated, decile spread 2.1–2.4×.
- **Consensus predicts move SIZE, never direction** — and it predicts the tail too (squeeze AUC 0.56–0.61).

One thing died everywhere: **direction**. Three independent datasets, 34 voice×regime combinations,
29 slices, 4 strategy inversions, 2 carry structures, 6 level/side cells. Nothing holds.

That pattern should shape what we do next. **Three of the four proposals below deliberately do not ask
"which way will it go."** The fourth asks it about a source we have never tested.

---

## Proposal A (highest value) — grade the owner's own trades

You just built the automatic trade journal from real Hyperliquid fills. **That is the single most
valuable untouched dataset in the project, and nobody has asked the obvious question of it.**

Every directional test so far has graded the *bot's* signals or mechanical voices. **The owner is a
discretionary trader.** Whether *they* have directional edge is a different question with a different
answer, and it is the one that actually determines how the system should be used:

- if the owner has edge → the system's job is risk management and sizing around their calls, which is
  exactly what `risk_voice.py` already does
- if the owner does not → that is worth knowing before more capital goes in, and the honest product is
  carry/vol tooling, not signals

**Design:** forward-grade every fill the same way the agent scorecard was built — entry mark, forward
returns at 4h/24h/5d net of fees, versus (a) a random-side null on the same timestamps and (b) buy-and-hold
on the same coins over the same window. Split by coin, side, size, time of day, and whether the trade
was with or against the hivemind's consensus. Cluster bootstrap on day. **Report it even if the answer
is unflattering** — especially then.

**Caution:** the sample will be small and recent. Pre-register the test (I will write the script before
looking at results) and report power honestly rather than mining it.

---

## Proposal B — cross-sectional ranking instead of time-series direction

Every directional test has asked **"will this coin go up?"** Nobody has asked **"will this coin go up
*more than the others* today?"**

That is not a reframing of the failed question — it is a different one, and it often survives where
time-series direction does not, because it is market-neutral by construction. Beta and the whole
market's drift cancel out, which is precisely what killed the 2025 carry result (day-selection
masquerading as skill) and what makes `always-long` not significant over this period.

**Design:** the 18,201-row daily panel already exists. Each day, rank all coins by each voice, take the
top-k minus bottom-k spread, and measure the forward return of that long-short basket net of fees.
Train/test, block bootstrap on day. Compare against a shuffled-rank null.

**Why it is worth the compute:** it is the only major structural question about this data that has not
been asked, the data is already built and validated, and the answer is cheap to get. If it is flat too,
that closes the directional question properly rather than by accumulation of failed variants.

---

## Proposal C — exits, the other half of geometry

`GEOMETRY.md` optimised **where the stop goes**. Nothing has optimised **when to leave a winner**, and
three separate results point at it:

- near targets (0.5R) beat far ones at *every* stop width, monotonically
- your exit agent showed +$574 vs holding at a 69% hit rate — but 28 of 29 were loser-cuts, so the
  winner side is untested
- the geometry surface plateaus at ≈0, which means the remaining value is in *path*, not entry

**Design:** on the same 15,663-signal corpus, sweep exit policies rather than stop placement —
fixed-time exits (4h/12h/24h/48h), partial scale-outs (half at 0.5R, rest trailing), trailing activated
only after +X R, and break-even stops after +Y R. Same paired bootstrap, same train/test, same
monotonicity check. A policy only counts if it beats the flat 0.5R target *at the same stop width*.

---

## Proposal D — model the volatility forecast's own error

The HAR model works but its top two deciles **over-predict by 15–24%**, and we currently patch that
with a flat ×0.8. That is a hack covering a structure.

**Design:** regress the log ratio (actual ÷ predicted) on the things that might explain it — forecast
level, funding, consensus dissent, BTC vol, day of week, time since the last large move. Anything that
survives train/test becomes a second-stage correction. Validate on QLIKE and decile calibration, not R².

**Why it matters more than it sounds:** every stop width and every leverage cap in `risk_voice.py` is
scaled off this forecast. A 15% calibration improvement propagates directly into both, and unlike the
directional work it is improving something already known to be real.

---

## Ranking, and what I would start with

| | proposal | why this order |
|---|---|---|
| 1 | **A — grade the owner's trades** | new data, unasked question, changes what the product should be |
| 2 | **B — cross-sectional ranking** | the last unasked structural question; data already built |
| 3 | **D — vol forecast error model** | improves something already proven, feeds stops and leverage |
| 4 | **C — exit policy sweep** | natural successor to geometry, but the plateau suggests modest upside |

**I will start on B unless you say otherwise**, because it needs nothing from you and the panel is
already validated — whereas A depends on the journal having enough fills to be worth grading. Tell me
how many fills the journal holds and I will reorder.

---

## Two standing notes

**On the bollinger proxy:** your real-signal check (−15.7 vs −8.0 bps at 4h, worse in both halves,
24h sign flipping +45.6 → −13.1) kills it, and I accept that. My proxy tested a *concept* on daily
majors; your implementation trades intraday in combination with other strategies. Given ~4 proxies
tested and n=3,297 test rows, a false positive was always the likeliest explanation. **No need to
chase it.** Worth recording as the clearest example yet of why proxies get flagged as proxies.

**On what to stop doing:** we have now run roughly 80 directional tests across three datasets and
none has survived. I would treat "find a directional edge" as answered unless new *data* arrives —
order flow, on-chain positioning, or the owner's own fills. Running more variants on the same price
history is no longer informative, and every additional test makes a false positive likelier.
