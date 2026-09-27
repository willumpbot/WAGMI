# Micro-Cap HISTORY Harness — Results

**Run date:** 2026-08-06 · **Harness:** `tools/copilot/microcap_history_harness.py`
· **Universe:** the 12 clean coins in `data/microcap/universe_testable.json`
(`wash_heavy == false`, i.e. Jupiter `organic_score >= 40`).

> **`[SLIPPAGE-NAIVE UPPER BOUND]`** — every number below is an upper bound on
> **already-survived** coins. Price fields never reflect a real fill: a
> close-price "buy" on a thin pool assumes a $200–$1,000 order walks straight
> through at close, and the per-liquidity DEX round-trip cost
> (`MICROCAP_CAMPAIGN.md` A1d) is applied *on top* of that already-optimistic
> assumption, so even the **net** number is optimistic. These 12 coins are
> alive today; the dead clones that would drag every mean down were never in
> the file (survivorship). This is **HISTORY track = ORIGIN / UNVALIDATED**
> (A2): a survivor here would be a lead for a FORWARD re-test, never an edge,
> never a trade, never shipped near the live bot. `[LIQUIDITY-AT-TIME
> UNVERIFIED]` (no reserve history — cost bucket keyed to a single
> current-state snapshot). `[MEV/PRIORITY-FEE UNMODELED]`.

---

## Bottom line (honest)

**0 hypotheses survived.** Across the 7 HISTORY-testable hypotheses
(M1, M4, M7, M19, M21, M22, M23), expanded to **15 scored train tests × 3
horizons = 21 family entries** (of which 15 had enough independent episodes
to earn a p-value), **not one** cleared Benjamini-Hochberg FDR (q=0.10) on the
in-sample TRAIN split *and* independently reproduced at p<0.05 with the same
sign on the held-out TEST split. This is a **clean null**, and on this venue
that is the *expected, correct* result: a handful of survivorship-selected
established meme coins with ~6 months of daily bars each is exactly the setting
where "almost anything looks like a pattern on a small sample," and the
harness's job is to refuse to manufacture one. The negative-control selftest
confirms the machinery returns **0 confirmed survivors on 360 pure-noise
tests** — so the null here is a real null, not a broken harness.

The one recurring *near*-miss is instructive and is an **era artifact, not a
signal**: at the 7-day horizon, several long hypotheses (M19-long, M21, M22)
show elevated TEST-slice net returns (M21 test p=0.011, M19-long/M22 test
p≈0.05) — but their **TRAIN p-values are all insignificant (0.38–0.78)**, so
they fail the FDR-on-train gate. Read plainly: the recent (post-2026-05-07)
half of the window was a meme-up-era in which *being long anything* paid, and
that broad beta shows up only in the second era. It is not a conditional edge —
the permutation baseline (each coin's own non-event bars) drifts up in that era
too, which is why the pervasive positive 7-day drift is insignificant against
its own baseline in-sample.

---

## Methodology (the moat — every item load-bearing)

- **Entry-time-safe:** a bar-`t` signal uses only data through bar `t`'s close;
  the outcome is a strictly-forward return `close[t] → close[t+k]`
  (k ∈ {1, 3, 7} days). Trailing baselines that must not see the current bar
  use `.shift(1)` first (turnover z-score, realized vol).
- **Net-of-cost:** the `MICROCAP_CAMPAIGN.md` A1d per-liquidity round-trip
  table, keyed to each coin's current-state liquidity snapshot (midpoints:
  27.5 bps at POPCAT-scale ≥$2M, 52.5 bps $1–2M, 112.5 bps $200k–1M, 200 bps
  $50–200k, 325 bps <$50k). Both gross and net reported so the cost drag is
  visible.
- **OOS-decisive:** a single calendar cutoff (2026-05-07, the midpoint of the
  combined observed range) for *all* coins — not a per-coin percentile (A3),
  because staggered launches would leave some coins with days of TEST.
- **FDR:** Benjamini-Hochberg at q=0.10 across the whole family, Bonferroni
  reported alongside (companion α=0.0033).
- **Pseudoreplication:** consecutive same-coin triggers within 1 day collapse
  to one independent episode before any N/p. Same-day serial-launch collapse
  (A3 rule #2) is N/A — these are established coins, not a launch cohort.
- **n≥30 floor:** no p-value is computed below 30 independent episodes;
  under-powered buckets are labelled, never given a p.
- **Refute-yourself:** `--selftest` plants a genuine edge (recovered &
  confirmed), rejects a train-only edge via the OOS split, verifies BH
  mechanics, and — the load-bearing check — runs 120 shuffled-noise
  hypotheses × 3 horizons and asserts ~0 confirmed survivors (**got 0**).
- **Era-artifact-aware & tail-aware:** worst single-episode net return (A4.7
  rug check) and single-coin-dominance flag (A5.2) printed per hypothesis.

---

## Per-hypothesis results

`trN/teN` = independent episodes (train/test); `trP/teP` = permutation p on NET
returns vs the coin's own matched baseline; `net`/`gr` = mean net / gross
forward return; `worst` = worst single episode (rug check). FDR/BONF/CONFIRMED
flags empty ⇒ did not clear.

| hypothesis@horizon | trN | trP | tr_net | teN | teP | te_net | worst | verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| M19 turnover-spike LONG @1d | 43 | 0.656 | +0.15% | 45 | 0.665 | +0.13% | −25.5% | — |
| M19 turnover-spike LONG @3d | 43 | 0.400 | −1.72% | 40 | 0.460 | −1.10% | −27.3% | — |
| M19 turnover-spike LONG @7d | 43 | 0.381 | +3.28% | 37 | 0.051 | +16.90% | −30.6% | — (train n.s.) |
| M19 turnover-spike SHORT @1d | 43 | 0.602 | −1.66% | 45 | 0.548 | −1.80% | −107.6% | — |
| M19 turnover-spike SHORT @3d | 43 | 0.426 | +0.21% | 40 | 0.502 | −0.49% | −210.8% | — |
| M19 turnover-spike SHORT @7d | 43 | 0.366 | −4.80% | 37 | 0.051 | −18.48% | −632.3% | — (short tail catastrophic) |
| M21 rel-strength top-quintile LONG @1d | 169 | 0.337 | +0.28% | 178 | 0.222 | +0.25% | −31.9% | — |
| M21 rel-strength top-quintile LONG @3d | 169 | 0.578 | +0.04% | 174 | 0.912 | +0.74% | −45.9% | — |
| M21 rel-strength top-quintile LONG @7d | 169 | 0.621 | +1.94% | 167 | 0.011 | +14.12% | −55.4% | — (train n.s.; TEST-era only) |
| M22 high meme-breadth LONG @1d | 331 | 0.457 | +0.18% | 228 | 0.719 | −0.21% | −22.1% | — |
| M22 high meme-breadth LONG @3d | 331 | 0.467 | +2.11% | 216 | 0.830 | +1.66% | −35.4% | — |
| M22 high meme-breadth LONG @7d | 331 | 0.780 | +5.71% | 216 | 0.055 | +9.37% | −49.5% | — (train n.s.; TEST-era only) |
| M23 cluster-laggard LONG @1d | 21 | — | −1.64% | 39 | 0.239 | −1.21% | −23.5% | UNDERPWR + single-coin-dom |
| M23 cluster-laggard LONG @3d | 21 | — | −0.22% | 39 | 0.441 | +1.72% | −30.3% | UNDERPWR + single-coin-dom |
| M23 cluster-laggard LONG @7d | 21 | — | +3.49% | 35 | 0.127 | −3.72% | −39.2% | UNDERPWR + single-coin-dom |
| M1 age 90–180d LONG @1/3/7d | 10 | — | +1.8/+0.5/−1.9% | 0 | — | n/a | — | UNDERPWR + single-coin-dom |
| M1 age 180d+ LONG @1d | 489 | 0.106 | +0.74% | 542 | 0.364 | −0.32% | −31.9% | — |
| M1 age 180d+ LONG @3d | 489 | 0.410 | +2.44% | 530 | 0.478 | +0.93% | −34.9% | — |
| M1 age 180d+ LONG @7d | 489 | 0.783 | +5.83% | 506 | 0.775 | +4.14% | −55.4% | — |

**FDR family:** n_tested = 15, expected false positives @q=0.10 = 1.50,
FDR survivors = **0**, Bonferroni survivors = **0**, **CONFIRMED = 0**.

---

## Per-hypothesis notes

- **M19 (turnover spike, vol/liq z≥2):** null both directions. The short side's
  worst-episode net of −632% at 7d is the rug/tail-loss check screaming: a
  turnover spike on a thin survivor is *followed* by more upside as often as
  down, and shorting it into a mania candle is unbounded-loss territory.
  `[LIQUIDITY-AT-TIME UNVERIFIED]` (denominator = static liquidity).
- **M21 (cross-sectional meme-peer rotation):** null in-sample. The 7d TEST
  significance with an insignificant TRAIN is the era artifact described above.
- **M22 (meme-breadth regime, operationalized as long-in-high-breadth):** null.
  Positive 3d/7d net means are broad up-era beta, not a conditioned edge
  (train n.s.).
- **M23 (correlated-cluster laggard convergence):** **UNDERPOWERED** — only 21
  train episodes and single-coin-dominated; no p computed. Cluster membership
  used a full-sample correlation matrix (a disclosed, near-static structural
  look-ahead); the laggard *trigger* itself is entry-time-safe. Not a survivor.
- **M1 (age-bucket forward return):** the honest A1e finding is stark — **every
  age bucket younger than 90 days has zero HISTORY data**, because the GT OHLCV
  window is ~180 days and these coins are all older than that at the window's
  start (POPCAT 2.5 yr, jellyjelly 553 d, etc.). Only `90–180d` (19 bars, one
  coin — KITTY) and `180d+` (2,071 bars) exist. So M1's early-life buckets —
  the highest-signal part of the hypothesis — are structurally **not testable
  on HISTORY** (they belong to the FORWARD track), and the testable `180d+`
  bucket is null. `[LIQUIDITY-AT-TIME UNVERIFIED]` for <14d buckets is moot:
  there is no data there at all.

---

## Hypotheses reported descriptively (not scored — stated why)

- **M4 (volatility-vs-age calibration):** by design a calibration study, not a
  directional edge, so it is **not in the FDR family**. Result: median realized
  14-day vol is ~6.0% and median single-bar wick range ~9.4% for the `180d+`
  bucket (n=1,983 bars, 12 coins); the `90–180d` bucket (n=11, one coin) is too
  thin to set a floor. The intended output — an age floor below which any
  signal is noise — **cannot be produced from HISTORY** because the sub-90-day
  buckets have no data (see M1). The age floor is a FORWARD-track deliverable.
- **M7 (liquidity-to-FDV ratio):** **structurally UNDERPOWERED** — the ratio is
  one static number per coin, so the independent N is the number of *coins*
  (≤12, and 3 have no FDV on file), never the autocorrelated daily bars. That
  is below the n≥30 floor by construction, so **no p-value is computed** (A3).
  Descriptively there is no monotonic relationship between liq/FDV and forward
  7-day net return (e.g. lowest-ratio CARDS +8.4% vs mid-ratio pippin −6.0%),
  and the KITTY row (+87% mean fwd7) is a young/early-life survivor outlier
  that underlines why this is descriptive-only.

---

## Refute-yourself (A4) status

- **A4.6 WASH-DRIVEN:** the organic-vs-raw re-run needs Jupiter organic-volume
  *history*, which does not exist (FORWARD-only). Mitigation, disclosed as
  weaker than the forward re-run: the universe was pre-filtered to
  `organic_score >= 40` *before* any test, so the whole population already
  cleared the only wash instrument available on this track.
- **A4.7 RUG/TAIL-LOSS:** worst single-episode net printed per hypothesis
  (see table). Tails are large and negative everywhere — the venue's
  categorical tail risk, with no survivor showing a benign tail.
- **A5.2 SINGLE-COIN DOMINANCE:** flagged on M23 and M1/90–180d; with so few
  independent names a dominated result is disqualifying, not merely caveated.

## Reproduce

```
# from C:\Users\vince\WAGMI\bot
"C:/Users/vince/AppData/Local/Programs/Python/Python313/python.exe" tools/copilot/microcap_history_harness.py --selftest
"C:/Users/vince/AppData/Local/Programs/Python/Python313/python.exe" tools/copilot/microcap_history_harness.py --run
"C:/Users/vince/AppData/Local/Programs/Python/Python313/python.exe" tools/copilot/microcap_history_harness.py --inventory
```
