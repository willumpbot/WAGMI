# WAGMI Co-Pilot — Confluence Campaign Results

**Run date:** 2026-08-06. **Status: EXECUTED — this is the deliverable.**
Methodology: `tools/copilot/CONFLUENCE_CAMPAIGN.md` (locked pre-registration-
style plan, Parts A-D). Engine: `tools/copilot/confluence_harness.py`
(selftest 5/5 re-verified immediately before this run, including the
200-noise→0-survivor anti-p-hacking proof). Runner:
`tools/copilot/confluence_campaign_run.py` (new, this run — encodes C1-C44
as `HypothesisSpec` objects and executes them through `run_campaign()`).
Raw output archived at
`confluence_campaign_results.json` (scratchpad; regenerate via the runner
if needed — not checked into the repo, contains no PII, purely derived
numbers).

**READ-ONLY.** No file under `data/` was written. No Discord. No live-bot
or paper-bot state touched.

---

## 1. Headline

| | |
|---|---|
| **Base hypotheses run** | **63** (covering all of C1-C44's feasible items, incl. owner-mandated liquidity-bucket variants — see §3 for exactly which C-numbers map to which run and which were deferred) |
| **FDR family size (`n_tested`)** | **133** (pooled + per-liquidity-bucket test entries with a computable p-value, out of 252 raw entries = 63 hypotheses × 4 (pooled/thin/mid/liquid)) |
| **Expected false positives at raw p<0.05** | **133 × 0.05 = 6.65** |
| **Train-fold BH-FDR survivors (q=0.05)** | **67** — see §4, this number is **not** the honest read (explained below) |
| **CONFIRMED candidates** (train-FDR survivor AND test-fold p<0.05 AND same sign AND test n≥20 AND no single-symbol dominance) | **0** |

**The honest bottom line up front: zero hypotheses in this campaign — across
confluence, regime-conditioning, multi-timeframe confirmation, derivatives
context, cross-sectional structure, or liquidity conditioning — survive
out-of-sample confirmation. This is a straight, uncushioned null result.**
It sits alongside, and is fully consistent with, `SIGNAL_SCORECARD.md`'s
existing verdict ("entry-signal panel: null across the board") and every
prior isolated-signal OOS test in this project (~23 of them). Confluence
and liquidity-conditioning do not rescue the dead isolated signals.

---

## 2. Why 67 "FDR survivors" is not 67 near-misses

67 of the 133 tests clear Benjamini-Hochberg on the **train fold alone** —
far more than the 6.65 expected by chance. This is **not** evidence of
real signal; walking through the data shows why:

- **Every single train-significant pooled hypothesis reversed sign or lost
  significance in the test fold.** Example (`C6_support_volsurge`, support
  bounce confirmed by a volume surge): train n=69, p=0.0003, net
  **+8.35%**; test n=27, p=0.64, net **−1.29%**. This pattern — strong,
  clean-looking train effect, near-zero-or-negative test effect — repeats
  across essentially every train survivor (`C7_pair_S1_S3`: train +1.70%
  p=0.0003 → test −1.38% p=0.39; `C29_marketwide_breadth_lt10`: train
  +0.66% p=0.0003 → test −1.09% p=0.65; `BASE_S1_oversold_for_C38`, the
  plain isolated oversold signal: train +0.60% p=0.008 → test −1.15%
  p=0.32). This is the textbook "died in the train era, doesn't
  replicate" pattern the campaign's A2/A4 machinery exists to catch.
- **Multicollinearity inflates the train-FDR-survivor count mechanically.**
  The C7 combinatorial sweep (31 of the 63 hypotheses) tests overlapping
  rule combinations over the *same* underlying oversold/dip trigger days
  (e.g. `S1∧S2`, `S1∧S2∧S3`, `S2∧S3∧S5` all fire on heavily-overlapping
  date sets). BH-FDR's guarantees weaken under this much positive
  dependence — a single real-or-spurious train-era drift in "buy the dip"
  days gets echoed as a dozen separately-"surviving" train p-values, not a
  dozen independent confirmations. This is exactly why the campaign's
  **primary bar is train-FDR AND independent test-fold confirmation**, not
  train-FDR alone — and on that primary bar, the number is 0, not 67.
- Well-powered pooled hypotheses only (both folds n≥20, 34 of the 63): 19
  clear train FDR, **0 confirm on test**.

## 3. What was run vs. deferred (honesty on scope)

**63 base hypotheses executed** (each expands to 4 FDR-family entries:
pooled + thin + mid + liquid bucket):

| Lens | C-numbers run | Count | Notes |
|---|---|---|---|
| 1 — Confluence | C1-C6, C8 (hand-picked) + C7 full combinatorial sweep (11 remaining pairs + 20 triples over {S1,S2,S3,S5,S6,S7}) | 38 | C7 is its own labeled, highest-multiple-comparisons sub-family, as the campaign doc requires |
| 2 — Regime | C9, C10, C11 (×2: BTC-above/below-50EMA), C12, C13, C14 (×2: breadth>50/≤50) | 9 | breadth_pct/BTC-above-50EMA are disclosed **proxies** (see §7); **C15 deferred** |
| 3 — Multi-timeframe | C17, C18 | 2 | run on its **own** split date (the 1h-covered sub-window, 2026-01-12→2026-08-01, per A2's own instruction) then pooled into the single combined FDR family; **C19, C20 deferred** |
| 4 — Derivatives | C21, C22, C23 (×2: OI-unwind / OI-buildup) | 4 | **all 4 returned n=0 events** (train_n=test_n=0) — the inventory's own pre-run warning ("essentially NO usable overlap window") was correct; **C24, C25 deferred** |
| 5 — Cross-sectional | C26, C27 (proxy), C29, C30 | 4 | C27 is a disclosed simplification (see §7); **C28 deferred** |
| 6 — Exit/risk-mechanics | — | 0 | **entire lens deferred** — needs `data/trades.csv`/paper-ledger history; `confluence_harness.py` is deliberately standalone/price-only (no `trades.csv`, no `core/` imports) per its own header. This matches the campaign doc's own Batch 6 instruction to treat it as separate infrastructure. C32-C36 need a different tool. |
| 7 — Liquidity (dedicated) | BASE_S1/S2/S6 (isolated-signal re-tests → C38/C39/C40's bucket breakdown), C41 (alt-only-universe re-slice), C42a/C42b (funding-crowding mirror) | 6 | **C37** = the harness's built-in `with_liquidity_buckets=True` companion protocol, applied to every hypothesis above (this *is* the verified engine's implementation of A6/C37, used as instructed). **C43 not built** (explicit alternative to C37 per campaign doc — "use one, not both"). **C44 deferred** |

**Deferred, with reasons (never silently dropped):**

| # | Reason |
|---|---|
| **C15** | Needs the actual, already-validated `is_falling_knife` logic from `core/quant_regime.py`. This harness is deliberately standalone (no `core/` imports) — a hand-built proxy would test a *different* rule than the validated gate, not a faithful sharpening of it. Deferred rather than faked. |
| **C19** | Its own definition ("1h HH/HL sustained ≥4h **after** the breakout bar") pushes the real decision timestamp 4h past the daily breakout close — a naive same-bar implementation would violate A1's entry-time-safety. Needs a re-anchored (shifted-entry) implementation not built here. |
| **C20** | `[POWER-LIMITED]` by the campaign's own text; explicitly "do not spend budget on it unless C17-C19 show something." They didn't (§4). Deferred by design, not oversight. |
| **C24** | Needs the raw signed `funding_rate` to detect a sign flip; the harness only exposes `funding_z` (a z-score), not the raw rate — cannot be reconstructed from the documented indicator set without a new loader. |
| **C25** | Cross-referenced to `liq_hypothesis_harness.py`'s H3 per the campaign doc itself — not independently scored, by design. |
| **C28** | Needs a 25×25 rolling correlation matrix + a cluster-boundary definition built and validated on TRAIN-only data — the campaign's own highest-implementation-risk item (Tier C). Deferred rather than rushed and unaudited. |
| **C31** | Canonical home is C23; cross-reference only per the campaign doc. |
| **C32-C36** | See Lens 6 row above — needs `trades.csv`, out of this harness's scope. |
| **C43** | Build-time alternative to C37; C37 (harness's built-in bucketing) was used instead, per the doc's explicit "not both" instruction. |
| **C44** | Same reason as C15 — needs `core/`'s real knife-gate/drawdown machinery. |

**Net: every hypothesis with data the inventory flagged as usable was
run; every hypothesis the inventory flagged thin/stale (Lens 4 derivatives,
most of Lens 3) was run anyway, exactly as instructed, and came back
either UNDERPOWERED (n=0, correctly excluded from the FDR family, not
silently dropped) or null.**

---

## 4. Confirmed survivors

**None. Zero entries — pooled or in any liquidity bucket — meet the
confirmation bar** (train-FDR survivor AND test-fold p<0.05 AND same sign
as train AND test n≥20 AND no single-symbol dominance ≥50%).

Nothing in §7 (candidates for pre-registration) follows from this section,
because there is nothing to list. Per the campaign's own Honesty Ceiling
(A7), this is reported straight, not softened.

### The closest near-misses (for transparency — **not candidates**)

Two results are worth naming explicitly because they are the least-bad
non-survivors, and because burying them would look like cherry-picking in
reverse:

- **`C29_marketwide_breadth_lt10`** (does the whole 30-symbol universe
  bounce, equal-weighted, when cross-sectional breadth<10% — a stricter
  cut than the already-refuted WASHED_OUT<20%): train n=1393, p=0.0003,
  net +0.66%; **era-stable** (pre-Feb-2026 net +0.60%, post-Feb-2026 net
  +0.64% — genuinely consistent across the era split, unlike almost
  everything else in this campaign); low dominance (3.8%, broad
  participation, not one coin). But its **test-fold n is only 30** (right
  at the power floor) and test net is **−1.09%** (p=0.65, wrong sign vs.
  train). The era-stability is real and interesting; the test-fold
  disconfirmation is also real, on a small sample. Net verdict: **does not
  confirm** — reported honestly as the single most era-consistent-looking
  non-survivor in the campaign, not as a discovery.
- **`C41_XSmomentum_altsonly_universe`** (top-quintile rel-strength within
  the 25-alt-only universe, majors excluded — the C41 internal re-slice):
  test-fold p=0.023 (nominally "significant") but train mean net is
  **−0.09%** and test mean net is **+0.25%** — both are ~0, and the signs
  differ, so it correctly fails the same-sign requirement. This is what
  economically-meaningless noise flipping across zero looks like when a
  huge sample (n≈1,400 pooled) gives a permutation test enough power to
  call a ~0.3% difference "significant" — a good illustration of why
  same-sign confirmation, not p-value alone, is the real bar.

---

## 5. The liquidity-ladder verdict (the owner's core thesis)

**Direct answer: no, this campaign does not find a directional signal that
edge strengthens as liquidity decreases. If anything, the weak signal
that exists points the other way, though it is too noisy to call
"refuted" either.**

- Of the 63 base hypotheses, **38 had enough episodes in ≥2 liquidity
  buckets (n≥20/bucket) to compute a monotonicity readout at all**; 25
  were too sparse in the bucket breakdown even where the pooled test was
  fine (bucket-splitting a modest pooled n three ways runs out of power
  fast — expected, disclosed, not hidden).
- Of those 38 readouts: **only 5 (13%) show a monotonically
  liquid→mid→thin *increasing* net edge** (`C5_relstrength_breakout`,
  `C7_triple_S5_S6_S7`, `C27proxy_topquintile_momentum_highdispersion`,
  `C30_laggard_rotation_breadth_gt70`, `BASE_S6_breakout_for_C40`) — and
  none of these five are confirmed survivors (§4), so "the edge grows
  toward thin" is being read off patterns that were never shown to be real
  edges in the first place.
- **Mean Pearson correlation** between liquidity-bucket rank
  (liquid=0→mid=1→thin=2) and net return, across all 38 usable readouts:
  **−0.25** (negative — mildly opposite the owner's thesis direction).
  14/38 (37%) positive vs. 24/38 (63%) negative.
- **The honest framing:** this campaign never found a real edge to begin
  with (§4), so the liquidity-ladder question is structurally being asked
  of noise, not of a signal. A −0.25 mean correlation across 38 small,
  independent (mostly 2-3-point) trend readouts is itself a weak,
  underpowered number — it should not be read as "liquidity conditioning
  is refuted" any more than the 5 monotonic hits should be read as
  support. **The fair statement is: this campaign finds no evidence
  either way that thinner names carry more edge, because it finds no edge
  anywhere to condition on liquidity in the first place.** The
  owner's thesis is untested by absence of a signal to test it on, not
  disproven.
- One data point worth flagging for future runs: the bucket-level
  breakdown (raw entries in `confluence_campaign_results.json`) shows the SAME train→test reversal pattern
  inside the thin bucket specifically that the pooled numbers show
  (e.g. `C6_support_volsurge::thin`: train n=29 p=0.0003 net **+9.07%** →
  test n=13, **UNDERPOWERED** (below MIN_N=20), net −3.22%) — even where
  train looks best in the thin bucket, the test-fold n collapses below the
  power floor before it can be checked. This is the concrete, mechanical
  reason the ladder thesis is hard to test on this corpus: splitting an
  already-modest edge three ways by liquidity, then again by train/test,
  runs out of independent episodes very fast on a 13-month/25-coin/
  daily-bar corpus. **More history (time, not more re-mining) is the
  actual fix**, consistent with `STATE.md`'s standing conclusion for this
  whole project.

---

## 6. Well-powered vs. underpowered split

| | Base hypotheses | Share |
|---|---|---|
| **Well-powered** (train n≥20 AND test n≥20, pooled) | 34 / 63 | 54% |
| **Underpowered** (at least one fold <20, incl. n=0) | 29 / 63 | 46% |

**Well-powered, by lens (both folds n≥20, out of the lens's total base
hypotheses):** Lens 1 (confluence) 18/38, Lens 2 (regime) 6/9, Lens 3
(multi-timeframe) **2/2 — fully powered, better than the campaign's own
`[POWER-LIMITED]` expectation**, Lens 4 (derivatives) **0/4**, Lens 5
(cross-sectional) 4/4, Lens 7 dedicated 4/6.

**Underpowered / thin, concretely:**
- **Lens 4 (derivatives) — 4/4 hypotheses returned exactly n=0 events**
  (`C21`, `C22`, `C23_unwind`, `C23_buildup`). This is not a bug: it
  reproduces the inventory report's own pre-run warning verbatim (majors'
  funding data overlaps majors' price cache for only ~5-6 weeks; meme
  funding/liq data has "essentially NO usable overlap window yet" with
  price). Nothing in Lens 4 is even reportable as a null — there were
  literally zero joint (oversold ∧ funding-extreme) or (oversold ∧
  liq-cascade) or (oversold ∧ OI-unwind/buildup) days in the loaded data.
- **Lens 1 overall: 20 of 38 hypotheses underpowered** — 19 of those are
  in the 31-item C7 combinatorial sweep (only 12/31 C7 items are
  well-powered), plus 1 of the 7 hand-picked hypotheses (`C2_triple_dip_
  uptrend`, train n=11). 10 of the 31 C7 items returned **exactly n=0** in
  both folds, mostly because `S6` (breakout, price above its own 20d
  high) and `S1`/`S2` (oversold/lower-BB) are close to mutually
  exclusive by construction — `S1∧S6`, `S2∧S6`, and every triple
  containing both, returned n=0. This is a logical consequence of the
  rule definitions, not a data gap.
- **`C11`/`C10`** (BTC-above/below-50EMA, WASHED_OUT/STORMY conditioning):
  underpowered in TRAIN specifically because the BTC price cache (needed
  to compute `btc_above_ema50`) only starts 2025-12-18 — nearly 6 months
  after the alts' price history begins — so most of the campaign's TRAIN
  fold (the first 60% of the 13-month span) has no BTC-trend read at all.
  This is the same majors'-cache-staleness gap the inventory already
  flagged, now visibly biting a specific hypothesis.
- **`C42a`/`C42b`** (funding-crowding): n=0/n=1 — same funding-coverage
  gap as Lens 4.

**Bottom line on power:** the fresh 25-alt daily price corpus (Lens 1, 2,
3, 5, and the price-only parts of Lens 7) is well-powered and gave this
campaign a fair, honest shot at finding something. The derivatives/meme
lens (Lens 4) could not be tested at all — not "tested and null," but
**zero joint episodes exist yet**, exactly as flagged going in.

---

## 7. Disclosed methodology deltas from CONFLUENCE_CAMPAIGN.md (read before trusting any number above)

Run exactly as instructed ("the plan + engine are built and verified;
your job is to RUN it"), with these disclosed, load-bearing choices:

1. **MIN_N=20, not `SIGNIFICANCE_N=30`.** The harness's own header
   documents this as a deliberate, disclosed deviation ("confluence
   day-bar triggers are structurally rarer events" than the tick-level
   harnesses n≥30 was set for) — used as-is, not tightened or loosened
   post-hoc.
2. **Single pre-committed primary horizon = 3 trading days**, fixed for
   every hypothesis before any result was read (matches
   `PREREGISTRATION.md`'s own `fwd_3d_pct` primary-horizon convention).
   Not re-tuned per hypothesis after peeking (A2).
3. **Liquidity buckets are the harness's own rolling-$-volume tercile of
   whichever universe is loaded** ("all" = 25 alts + 5 majors pooled),
   entry-time-safe, re-evaluated continuously (not monthly-snapshotted).
   This is a verified, working implementation of A6's LIQUID/MID/THIN
   concept, but is **not byte-identical** to the campaign doc's prose
   (which specifies LIQUID = majors-only, fixed, monthly-reevaluated
   MID/THIN within the 25-alt set only). In practice a very liquid alt
   can occasionally rank into the "liquid" tercile alongside/instead of a
   major, and vice versa — disclosed, not hidden, and unlikely to change
   the null headline given no bucket showed a confirmed edge regardless.
4. **`breadth_pct` / `btc_above_ema50` / `washed_out` / `stormy`** (Lens 2,
   C9-C11, C14, C29, C30) are **built here as proxies**, not imports of
   `weather.py::compute_market_weather` (which this standalone harness
   deliberately does not import) — computed causally from the harness's
   own `ema_trend_up` column, cross-sectionally, over the loaded universe.
   Same spirit as `weather.py`'s stated cutoffs, not a guaranteed
   numerical match.
5. **`high_dispersion_day`** (C27) is a **simplified proxy** for the
   dispersion-gated cross-sectional momentum book in the campaign doc —
   tests "is being in the top-quintile-momentum leg more profitable on
   high-dispersion days," not the full long-top/short-bottom XS book
   conditioned on dispersion. Labeled `C27proxy_...` throughout, never
   presented as the literal C27.
6. **BH-FDR is computed once, across the combined pooled family** (main
   `run_campaign()` output + the separately-split Lens 3 entries + the
   separately-universed C41 entry), by re-running the harness's own
   `benjamini_hochberg()` over every entry's train p-value together and
   replicating its exact confirm-logic — never two families, never a
   softer per-lens correction.

---

## 8. The bottom line

**Confluence, regime-conditioning, multi-timeframe confirmation, and
liquidity conditioning also do not surface a defensible edge on this
data.** Every dead isolated signal in `SIGNAL_SCORECARD.md` stays dead
when combined with a second, third, or fourth condition; the one lens
that could not be tested (derivatives/meme confluence) simply has no
joint episodes yet, not a tested-and-refuted result. The liquidity-ladder
thesis is untested-by-absence-of-signal, not refuted — the honest read is
that this 13-month/25-coin/daily-bar corpus does not have enough
independent episodes left, after OOS + FDR + liquidity-bucket +
train/test splitting, to answer that question cleanly either way.

**No candidate is being sent to `PREREGISTRATION.md`.** There is nothing
to pre-register — a `CONFIRMED` survivor is the only thing this campaign
was designed to hand off to forward validation (Part D), and there are
zero. Recommending a pre-registration off a train-FDR-survivor list (67)
or a near-miss (§4) would be exactly the p-hacking this campaign's own
methodology exists to prevent.

**What would actually move this forward, in priority order:**
1. **Time, not more re-mining** — this is the same conclusion
   `SIGNAL_SCORECARD.md` and `STATE.md` already reached; H1-H5 in
   `PREREGISTRATION.md` are still the only real path to a tested edge,
   because they test forward, uncontaminated data.
2. **Let Lens 4 (derivatives) actually accrue data** before concluding
   anything about funding/OI/liquidation-conditioned confluence — it
   returned zero joint episodes, not a null result, and the collectors
   are already running.
3. **If the liquidity-ladder thesis remains a priority**, the honest next
   step is not re-mining this corpus harder (bucket cuts run out of
   power fast on this many episodes) but the same "wait for more history"
   answer, potentially combined with widening the tradeable universe
   (more thin alts) rather than slicing the existing 25 more ways.

This campaign did its job: it took the owner's real, standing hypothesis
seriously, gave it a fair, rigorous, non-cherry-picked test across every
angle the plan specified, and came back honest. Zero confirmed survivors
is a valid, useful result — it closes off "maybe confluence was the
missing ingredient" as cleanly as a positive result would have opened it
up.
