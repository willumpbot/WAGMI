# H5 (liq session-timing) and H4 (OI-buildup → forward risk) — null-robustness re-test

**Run 2026-09-27 (evening).** Same treatment as `H3_NULL_ROBUSTNESS_RESULTS.md`.
Scratch scripts (`h5_retest.py`, `h5_extra.py`, `h4_retest.py`) live in the session
scratchpad, not the repo; H4 imports the harness's own loader/feature/window/test
functions unchanged, H5 re-implements the episode rule (counts reproduce the harness's
gap sweep to within the file's growth). Read-only; no locked constant touched.

Data note that affects every number below: both files grew after the 08:14 daily
readout (liq 43,398 → 44,485 events; OI 360 → 373 independent windows). More
importantly, the liquidation feed has **33 calendar days with data inside a 58-day
span** — a 24-day outage (2026-08-12 → 09-06, the box move) and a 2-day gap
(09-15 → 09-18). "57-day collection" in earlier write-ups is span, not coverage.

## Headline

- **H5 is fragile → treated as refuted.** The US-session excess exists only at the
  locked 300 s gap, is a liquidation-*intensity* (partial-fill chop) effect, and turns
  into a US *deficit* once episodes are grouped at ≥30 min. The busiest session and top
  symbol both change at every gap. Nothing here is a liq-specific timing signal.
- **H4 is not supported as pre-registered.** The cascade metric (`tail_freq`) is null in
  every cell; `vol_ratio` survives in exactly one of three vol terciles. That one cell
  passes several honest corrections but is a knife-edge Holm pass, has ~26 effective
  clusters, is built entirely from symbols that individually fail the n≥30 gate, and
  measures *vol persistence*, not a spike. It is a candidate for forward data, not a
  finding.

---

## Part A — H5: session timing

### Why the harness print overstates it

The flat clock-hour share is a reasonable null for a *timing* question, so the problem
here is different from H3. The harness bootstraps **episodes as i.i.d.**, but episodes
cluster within days (that is H3). Resampling calendar days instead gives a design effect
of **5–7× on the variance** at gap 300 s, i.e. the harness CIs are ~2.3–2.7× too narrow.
Even before any of that, the 08:14 print's "EU SIG" became n.s. with ten more hours of
data (EU 34.7% → 34.5%, CI lower bound sitting on 33.3%).

### Result A1 — the gap sweep (session share ÷ clock share; verdict i.i.d. | day-block)

| gap | n_eps | Asia | EU | US | Off | peak 14–15 UTC | busiest (ratio) | top symbol |
|---|---|---|---|---|---|---|---|---|
| **300 s** (locked) | 6365 | 0.92 SIG− \| n.s. | 1.03 n.s. | **1.11 SIG+ \| SIG+** | 0.97 | **1.27 SIG+ \| SIG+** | US | BTC 22% |
| 900 s | 4020 | 0.98 | 1.01 | 1.00 n.s. | 1.02 | 1.01 n.s. | Off | SOL 18% |
| 1800 s | 2621 | 1.03 | 1.00 | **0.94 SIG− \| SIG−** | 1.07 | 0.90 n.s. | Off | FARTCOIN 16% |
| 3600 s | 1430 | 1.10 SIG+ \| n.s. | 0.99 | **0.91 SIG− \| SIG−** | 1.07 | 0.85 n.s. | Asia | PENGU 14% |

Session share by episode *midpoint* instead of start, and a symbol-balanced share (mean
of per-symbol shares, n≥30 symbols only), move these by ≤1.5 pp — the flip is not a
start-time or BTC-weighting artifact.

### Result A2 — how fragile the rankings are

Day-block bootstrap probability that each session is the busiest (by ratio):

| gap | Asia | EU | US | Off |
|---|---|---|---|---|
| 300 s | 0% | 10% | **84%** | 6% |
| 900 s | 10% | 31% | 18% | 42% |
| 1800 s | 28% | 8% | **0%** | 64% |
| 3600 s | 59% | 4% | **0%** | 37% |

Per-symbol busiest session at 300 s: US for BTC/SOL/FARTCOIN/kPEPE/PENGU, EU for the
other four. At 1800 s six of nine symbols say Off; at 3600 s BTC's busiest is Off at a
1.46 ratio and SOL's is Asia at 1.33. No symbol keeps the same busiest session across
the sweep.

### Result A3 — what the 300 s excess actually is

At the raw-event level (gap 0) the picture is extreme: EU carries 50.7% of events
(1.52× clock), US 43.2% (1.29×), hours 14–15 UTC alone 16.0% (1.92×), and notional
follows the same shape. At the cascade-onset level (gap 3600) the same hours are
*under*-represented. Events per 1 h-gap cascade: median 3 in every session, but p90 =
66 in EU vs 26 in US/28 in Asia. So the US/EU tilt is **more liquidation prints per
cascade during the London/NY overlap** — the known OHLC vol-seasonality that H5 was
supposed to be compared *against*, restated through partial-fill chop — and the number
of distinct cascade onsets per clock hour is flat-to-Asia-heavy (Asia 65/h, Off 63/h,
EU 59/h, US 54/h).

### Verdict — H5

1. **Refuted as a liquidation-specific timing finding.** The only cell that survives a
   day-block null is the locked-gap US/14–15 UTC excess, and it inverts at ≥1800 s.
   A finding whose sign depends on the episode gap is measuring the gap rule.
2. What survives is not new: liquidation *volume* peaks with the known 14–15 UTC vol
   peak. The co-pilot already knows that from `session_vol_test.py`.
3. The harness's episode-level bootstrap should not be read as a CI for H5; its
   effective n is ~1/6 of the printed n at the locked gap.

---

## Part B — H4: OI buildup → forward risk (24 h, independent windows)

### Confirmation of the latest daily readout (08:14 block, `daily.log` l.15256–15458)

Re-running the harness functions on tonight's file reproduces the readout's shape
(numbers moved with 13 new windows):

| metric | naive spread (p) | low-vol | mid-vol | high-vol |
|---|---|---|---|---|
| `vol_ratio` 08:14 | +0.122 (p=0.036) | +0.196 n.s. (0.108) | −0.006 n.s. | **+0.139 (p=0.0088)** |
| `vol_ratio` tonight | +0.129 (p=0.024) | +0.199 n.s. (0.090) | −0.007 n.s. | **+0.162 (p=0.0048)** |
| `tail_freq` 08:14 | +0.009 n.s. | n.s. | n.s. | +0.040 n.s. (0.274) |
| `tail_freq` tonight | +0.014 n.s. | n.s. | n.s. | +0.049 n.s. (0.175) |

Confirmed: **2 of 3 terciles n.s. on the central metric; the cascade metric n.s.
everywhere.** All three terciles clear n≥30 on both sides, so this is not a power gap.

### Honest corrections applied to the one surviving cell (high-vol × `vol_ratio`)

- **Multiple comparisons.** Six controlled cells. Holm threshold for the smallest p is
  0.0083: the cell **failed** it this morning (0.0088) and **passes** tonight (0.0048).
  A verdict that flips on one day of accrual is not settled either way.
- **Composition.** The high tercile contains **no BTC window and only 1 ETH / 2 SOL
  (unwind side)**; buildup = HYPE 6, PENGU 6, kBONK 5, FARTCOIN 4, kSHIB 4, XRP 3,
  POPCAT 3, WIF 3, PURR 3, kPEPE 2. The pooled cell is assembled from symbols the
  harness itself lists as "needs 14 more" (or 22 more) windows. Per-symbol spreads
  are 8 positive / 2 negative at n of 2–10 each — descriptive only.
- **Effective sample.** 39 + 42 windows sit on only **26 distinct calendar dates**
  (15 buildup dates, 21 unwind dates); majors share exact 24 h boundaries. Date-cluster
  bootstrap 95% CI on the spread: [+0.026, +0.256], P(≤0)=0.013 — survives, but on 26
  clusters.
- **Within-date vs between-date.** Permutation p: global shuffle 0.0025, **within-date
  shuffle 0.072 (n.s.)**. Much of the effect is "which days had buildups", not "which
  symbols were in buildup on a given day".
- **Finer vol control.** OLS `vol_ratio ~ log(trailing_vol) + buildup`: high-tercile
  coefficient +0.158, date-cluster CI [+0.021, +0.269]; pooled +0.102, CI
  [−0.003, +0.201] (touches zero). Quintile spreads are +0.10, +0.09, **−0.06**, +0.13,
  +0.19 — not monotone.
- **Leakage check (in H4's favour).** Within the high tercile buildup and unwind have
  near-identical trailing vol (0.00616 vs 0.00641), so it is not mean-reversion
  masquerading as an OI effect. Rank test also positive (MW z=+2.28, p=0.023).
- **Stale-label placebo.** Labelling each window with the *previous* window's state
  keeps 62% of the naive spread (+0.080 of +0.129 — OI state is that persistent) but
  the high-tercile spread collapses to +0.007. The high-vol cell is at least
  timing-specific, not a slow regime label.
- **What it measures.** Both sides have `vol_ratio` < 1 (0.98 vs 0.82); only 44% of
  buildup windows and 19% of unwind windows see forward vol above trailing. Absolute
  forward vol 0.0060 vs 0.0050. The residual is "**after a high-vol day, vol fades
  less when OI was building**" — persistence, not the elevated-cascade-risk claim in
  the pre-registration, and the tail metric that *would* capture cascades is null
  (22.6% vs 17.8%, p=0.17).

### Verdict — H4

1. **As pre-registered ("OI buildup flags elevated forward cascade risk"): not
   supported.** Cascade metric null in 3/3 terciles; central metric null in 2/3.
2. **One residual cell is real enough not to discard and too thin to use:** high-vol
   tercile, `vol_ratio` only, ~26 effective clusters, memes/HYPE only, borderline Holm,
   n.s. within-date. Its honest description is a hypothesis for the next 60–90 days of
   forward data, restricted to "vol persistence after high-vol days with rising OI".
3. **No OI-specific signal exists for BTC/ETH/SOL in this test** — they barely enter
   the surviving cell at all.

---

## Recommended follow-up

- H5: stop reading the harness's per-session verdicts. If a session panel is kept,
  print the gap sweep *with* verdicts (it is currently descriptive only) and use a
  day-block CI. Do not build any session-timing feature on liquidations.
- H4: freeze the high-vol × `vol_ratio` cell as a named forward hypothesis with its own
  n≥30-*dates* gate and a Holm-corrected bar; re-read at 60–90 days. Do not feed OI
  state into any cascade-risk or sizing logic on the strength of this cell.
- Both harnesses: add coverage-days (not span) to the header — 33 data-days changes
  how every "57-day" claim in this folder should be read.
