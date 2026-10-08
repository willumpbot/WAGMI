# Full-history data validation

_2026-10-08. Supersedes the coverage and results sections of `REGRADE.md` and `RULE_CANDIDATES.md`._

## Headline

**Every price series on this laptop has now been validated by two independent methods, and the
usable history extends back to 2025-11-10 instead of 2026-03-14.** That recovered the February
signals and raised the graded corpus to 15,663 of 16,458 (95.2%) across 208 symbol-day clusters.

Three things changed as a result:

1. **February 2026 was catastrophic** and had been invisible: 4h **−61.8 bps** (CI [−100.4, −17.5]),
   12h **−177.3**, hit rate 25.6%. Significant at all three horizons.
2. **`agree≥3` is now significant at all three horizons** (1h −19.9, 4h −36.7, 12h −106.4; n=312,
   n_eff=30, up from 20). More strategies agreeing reliably means *worse* forward returns.
3. **One slice rule now clears the bar** — `avoid agree=3+ side=SHORT` — but see the caveat; it is
   a shadow candidate, not a shippable rule.

And the 2025 dataset was graded for the first time: **it has no directional edge either**, once the
baseline is taken out.

---

## 1. Price-series validation (two independent methods)

### Method A — against Hyperliquid, on the overlap
Accept if median |%diff| of 1h close ≤ 0.25% **and** ≥95% of bars within 1%.

| symbol | overlap bars | median % | p90 % | within 1% | verdict |
|---|---|---|---|---|---|
| BTC | 2,047 | 0.0000 | 0.0607 | 100.0% | ✅ ACCEPT |
| ETH | 2,047 | 0.0000 | 0.0626 | 100.0% | ✅ ACCEPT |
| SOL | 2,047 | 0.0000 | 0.0849 | 100.0% | ✅ ACCEPT |
| HYPE | 2,049 | 0.0000 | 1.1882 | 87.0% | ❌ REJECT |
| DOGE | 720 | 0.3408 | 1.1005 | 87.9% | ❌ REJECT |
| ARB, AVAX, PEPE, WIF | 0 | — | — | — | no overlap (cache ends 2026-02-18, HL starts 2026-03-14) |
| AAVE, OP, SHIB, UNI | 0 | — | — | — | no HL reference |

### Method B — internal consistency, for series with no external reference
The 1h and 6h files come from separate API pulls, so aggregating 1h→6h is an independent check.
Accept if ≥95% of complete 6h windows agree within 0.25% on open/high/low/close.
**BTC/ETH/SOL were run as a control** — a pass only means something if the known-good series pass.

| symbol | 1h bars | windows | agree % | median dev % | verdict |
|---|---|---|---|---|---|
| ARB | 2,376 | 395 | **100.0%** | 0.0000 | ✅ ACCEPT |
| AVAX | 2,376 | 395 | **100.0%** | 0.0000 | ✅ ACCEPT |
| PEPE | 2,376 | 395 | **100.0%** | 0.0000 | ✅ ACCEPT |
| WIF | 2,376 | 395 | **100.0%** | 0.0000 | ✅ ACCEPT |
| BTC *(control)* | 5,004 | 833 | 99.8% | 0.0000 | ✅ pass |
| ETH *(control)* | 5,012 | 834 | 99.8% | 0.0000 | ✅ pass |
| SOL *(control)* | 5,012 | 834 | 99.6% | 0.0000 | ✅ pass |
| **HYPE** | 5,013 | 834 | **57.7%** | 0.0000 | ❌ REJECT |
| DOGE | 1 | 0 | — | — | no usable 1h data |

**HYPE fails both methods independently.** Its 1h cache is also 14.6% degenerate bars
(open=high=low=close). AAVE/OP/SHIB/UNI 1h files are **99.9% degenerate** — those files are inert
and were discarded entirely. Overall: 266,504 rows ingested across 396 files, 11,308 degenerate
bars (4.2%) excluded, 0 malformed rows.

### Result: the merged store
`candles_merged/` — HL wins wherever both sources exist, degenerate bars dropped.

| symbol | bars | span |
|---|---|---|
| BTC | 5,036 | 2025-11-11 → 2026-06-09 |
| ETH | 5,044 | 2025-11-10 → 2026-06-09 |
| SOL | 5,044 | 2025-11-10 → 2026-06-09 |
| ARB, AVAX, PEPE, WIF | 2,376 each | 2025-11-11 → 2026-02-18 |

HYPE and the rest continue to use the plain Hyperliquid pull (2026-03-14 onward), which is always
trusted — the rejection is of the *cache*, not of HL.

---

## 2. Re-grade on the extended history

| | before | after |
|---|---|---|
| graded | 15,476 | **15,663** (95.2% of corpus) |
| span | 2026-03-16 → 06-05 (56 d) | **2026-02-11 → 06-05 (71 d)** |
| clusters (n_eff) | 177 | **208** |
| ungradeable | 773 (4.7%) | **434 (2.6%)** |

Headline numbers are unchanged and still replicate the server: **−11.0 bps at 1h (CI excludes 0),
−10.4 at 4h**, against the server's −14.0; confidence rank correlation **+0.026** against the
server's Spearman −0.045. SL-first 53.8% vs TP1-first 17.2%, so the ≈ **−0.40R geometry drag**
stands and remains the largest effect measured anywhere in this exercise.

### What the extra history revealed

| slice | n | n_eff | 1h | 4h | 12h | hit 4h |
|---|---|---|---|---|---|---|
| **2026-02** | 176 | 25 | **−24.5*** | **−61.8*** | **−177.3*** | 25.6% |
| 2026-03 | 2,385 | 51 | −3.9 | −8.5 | −8.7 | 47.5% |
| 2026-04 | 9,200 | 109 | −12.6* | −10.1 | −18.7 | 36.0% |
| 2026-05 | 3,852 | 20 | −10.1* | −10.5* | +8.3 | 33.5% |
| **agree≥3** | 312 | 30 | **−19.9*** | **−36.7*** | **−106.4*** | 24.7% |
| BTC | 4,525 | 63 | −12.8* | −16.7* | −33.2* | 30.5% |

February is by far the worst month in the dataset and was entirely unmeasured before this
validation. The `agree≥3` effect is now significant at every horizon and worsens monotonically
with horizon — the pattern you would expect from a real effect rather than a noisy cell.

---

## 3. The one promoted rule — and why it is still only a candidate

`avoid` on slice `{agree: "3+", side: "SHORT"}`, scored on the manager's in-minus-out metric:

| | diff vs rest of book | CI95 | n_in | n_eff |
|---|---|---|---|---|
| train 2026-02-11 → 04-29 | **−54.8 bps** | **[−90.8, −16.3]** | 80 | 14 |
| test 2026-05-01 → 06-05 | **−37.4 bps** | — | 27 | — |

**Caveat that must travel with it:** 29 slices were scanned, so ~1.5 false positives are expected
at p<0.05. **One hit is exactly what noise produces.** What argues for it is corroboration from a
different analysis — the `agree≥3` level effect is significant at 1h, 4h *and* 12h and scales with
horizon, which a single lucky slice would not do. Treat it as a shadow rule for forward
confirmation under the existing n≥13 gate, not as something to enforce.

Also still true: the handoff's requirement that "trades AND forward-graded signals agree
independently" **cannot be satisfied** — every closed-trade series on this laptop is corrupt, so
there is no independent trade axis. And the `regime` half of the grammar is unusable here
(regime_score buckets to 14,818 / 658 / 0).

---

## 4. The 2025 dataset — graded, and it has no edge

`Downloads/Paper Trades - jkh.csv`, 2025-08-30 → 2025-10-11. **Provenance unknown ("jkh");
treated as an unattributed third-party stream, not the owner's bot.**

Daily bars were validated first, against the HL-validated 1h store aggregated to daily:
ETH 99.5% / SOL 99.0% / BTC 99.5% within 1%, median diff 0.0000% over 208–209 overlapping days.
Those daily series run 2024-06-08 → 2026-06-07. **Aug–Oct 2025 bars have no second source** and
are trusted by inference from the series passing on the overlap — stated, not hidden.

Of 3,319 actionable rows on validated symbols, **950 (28.6%) quoted a price outside that day's
high-low range by more than 3% and were dropped**, leaving 2,369.

Then the baseline, which is the whole story:

| | 1d, bps net of 9 bps |
|---|---|
| market over the full window (always-long, all days) | **−4.7** (ETH −14.5, SOL −5.1, BTC +5.6) |
| always-long **restricted to the days the signals landed on** | **+82.2** |
| the stream's own signed return, identical rows | **+83.9** |
| **selection contributed by choosing a direction** | **+1.7** |

The raw figure looked like +81 bps of edge. It is **day-selection, not direction**: the signals sat
on days that happened to be up, and choosing long-versus-short on those days added ≈ nothing.
The market itself was flat-to-down over the window, so this is not a bull-market artifact either —
it is a clustering artifact. **3,319 rows occupy only 50 distinct symbol-days**, so even the
day-clustering is within what luck produces, and the earlier `DEEP BUY +164.6` cell does not
survive. A per-row random-side control put the stream outside its 95% band, but that control
ignores the clustering and so overstates significance; the like-for-like comparison above is the
correct null.

**Conclusion: three independent datasets — the server's 2026-05→10 agent log, this laptop's
2026-02→06 signal corpus, and an unrelated 2025 stream — all show no directional edge after fees.**

---

## 5. What remains unvalidatable

- **Aug–Oct 2025 daily bars**: no second source exists. Trusted by inference only.
- **HYPE's cache**: rejected by both methods; HYPE is graded from HL (2026-03-14+) only, so its
  February signals stay ungraded.
- **434 signals (2.6%)**: pre-2025-11-10, or on symbols with no validated series (SEI, SUI, ONDO,
  XRP, LINK, DOGE before HL history).
- **Every closed-trade and PnL series on this laptop**: corrupt by four separate mechanisms
  (`INVENTORY.md` §3). No validation can repair these; they should be deleted or quarantined, not
  re-analysed.
- **The `manual/` sniper corpus** (40,891 rows): has no resolved outcomes and no join key, so it
  can only ever be graded the same way the signal corpus was. Not yet attempted.

## Reproduce
`validate_cache.py` → `cache_validation.json`; `validate_internal.py` → `internal_validation.json`;
`grade_corpus.py` (now reads `candles_merged/` first) → `regrade.json`; `hunt_rules.py` →
`RULE_CANDIDATES.json`; `grade_2025.py` → `grade_2025.json`; `baseline_2025.py` →
`baseline_2025.json`. Candle stores are gitignored.
