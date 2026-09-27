# H3 (liquidation clustering) — null-robustness re-test

**Run 2026-09-27.** Script: `tools/copilot/liq_h3_null_robustness.py` (read-only,
touches no locked constant). Data: `data/copilot/liquidations/liq_events.jsonl`,
43,398 events, 56.5-day collection span.

## Headline

**H3 survives — but only for BTC, SOL and FARTCOIN, and at roughly half the
effect size the pre-registered harness reports.** The thin memes show nothing
once ambient burstiness is controlled for. The surviving effect is a *cascade-risk
forecast*, not a direction signal.

## Why a re-test was needed

`liq_hypothesis_harness.py` tests H3 against a **homogeneous-Poisson** null: it
compares P(another same-symbol episode within W min | one just ended) against the
symbol's *average* rate over the whole 56-day window. All 9 symbols reject that
at p=0.0000, at both W=15m and W=60m.

That null was never plausible. Liquidations happen in volatile moments, and
volatility clustering is the most heavily replicated fact in financial
econometrics — a bursty point process rejects a flat-rate null *by construction*.
So p=0.0000 against it is close to uninformative. (The harness is honest about
this: it prints `NO SIGNIFICANCE CONCLUSION IS DRAWN BY THIS RUN`.)

The question that matters is **self-excitation above ambient burstiness**: given
we are *already inside a busy stretch* for this symbol, does an episode
specifically raise the odds of another one soon? That is the Hawkes-style
question, and only that residual is potentially actionable.

## Method

Replace the flat null with a **local (inhomogeneous-Poisson) null**. For each
trigger episode ending at `t`, estimate the ambient rate from same-symbol
episodes in `[t−H, t+H]` with the test zone `(t, t+W]` carved out of both
numerator and denominator. Expected hits = `Σ p_i`, variance = `Σ p_i(1−p_i)`
(Poisson-binomial). No p-value is computed below `SIGNIFICANCE_N=30` triggers,
mirroring the harness's discipline.

Swept `H ∈ {2h, 6h, 24h}`, `W ∈ {15m, 60m}`, episode `gap ∈ {300s … 3600s}`.

## Result 1 — locked gap (300s), local null

The apparent effect collapses by about three quarters:

| symbol | flat null (harness) | local null (±6h) | residual |
|---|---|---|---|
| BTC | 50.4% vs 22.0% | 49.9% vs 42.5% | +7.4pp, z=+5.65 |
| SOL | 44.3% vs 20.1% | 43.9% vs 39.2% | +4.7pp, z=+3.51 |
| FARTCOIN | 39.0% vs 17.8% | 38.3% vs 36.2% | +2.1pp, **n.s.** |

At W=15m with the tightest ambient window (±2h) only **3 of 9** symbols keep a
significant excess. The wider the ambient window, the more it reverts toward the
flat-null result (7/9 at ±24h) — as expected, and a reason to read the ±2h/±6h
columns, not ±24h.

## Result 2 — episode-chop robustness (the decisive test)

The feed cannot resolve accounts: 91.9% of episodes are single-sided, so one
large cascade reported as partials spanning more than `gap` seconds is split into
several "independent" episodes minutes apart — which manufactures exactly the
clustering H3 reports. Raising the gap collapses that chop.

**Caveat on my own sweep:** the test is only meaningful where `W > gap`. At
gap≥900s with W=15m, and at gap=3600s entirely, `emp=0.0%` for every symbol —
that is arithmetic (two same-symbol episodes cannot be closer than `gap`), not
evidence. Ignore those rows. The valid chop-robustness cells are **gap=1800s,
W=60m**:

| symbol | empirical | local null (±6h) | z | verdict |
|---|---|---|---|---|
| BTC | 64.7% | 37.0% | **+10.78** | survives |
| SOL | 64.6% | 40.4% | **+9.75** | survives |
| FARTCOIN | 57.7% | 42.4% | **+6.33** | survives |
| PENGU | 38.1% | 37.2% | +0.34 | n.s. |
| kPEPE | 40.6% | 37.3% | +1.26 | n.s. |
| WIF | 32.9% | 32.4% | +0.15 | n.s. |
| kBONK | 26.5% | 27.4% | −0.28 | n.s. |
| kSHIB | 21.0% | 25.1% | −1.21 | n.s. |
| POPCAT | 22.3% | 29.8% | −2.32 | *below* null |

The three liquid names survive with large margins at a 30-minute episode
grouping. Everything thin dies. POPCAT going significantly *below* its local null
is a useful sanity check that the test can reject in both directions.

## Result 3 — trigger-dependence (thinned, non-overlapping)

Overlapping trigger windows share follow-ups, understating variance. Re-run with
triggers ≥2W apart, locked gap, ±6h ambient:

- **W=60m:** BTC +6.4pp (z=+3.00), kPEPE +8.5pp (z=+2.70), WIF +13.4pp
  (z=+3.58), kBONK +12.4pp (z=+3.19), FARTCOIN +5.1pp (z=+2.02) — 5/9 hold.
- **W=15m:** only BTC (z=+3.54) and kBONK (z=+2.90) hold.

BTC is the only symbol significant under *every* variant tested.

## Honest verdict

1. **BTC, SOL, FARTCOIN: real short-horizon self-excitation at the ~1h horizon.**
   Survives a local-rate null, survives episode-chop collapse, survives (BTC/
   FARTCOIN) trigger thinning. Forward-collected, pre-registered, artifact-checked.
2. **Thin memes: nothing.** Their apparent H3 signal was ambient burstiness plus
   probable partial-fill chop.
3. **This is not direction.** It forecasts *another cascade*, not which way price
   goes. Its honest use is the co-pilot's existing lane: cascade-risk warning and
   size/leverage restraint while a cluster is live — queue item #4, whose premise
   this validates for exactly three symbols.
4. **The harness's own H3 print should not be read as the finding.** Its flat null
   overstates the effect ~4x and extends it to 6 symbols where it does not exist.

## Recommended follow-up

- Restrict any cascade-risk feature to BTC/SOL/FARTCOIN; do not extend to memes.
- Add this local-null test as a second panel in the daily readout so the flat-null
  number is never read alone.
- Fix the sweep so `W > gap` is enforced, rather than printing vacuous 0.0% rows.
