# M13 DESIGN — conditional exit policy: which exit, when, from what is knowable AT ENTRY. (Owner priority, 2026-10-15)

**Status: DESIGN, written before any simulation ran.** Exploratory; output caps at HYPOTHESIS.
Red-teamed by a judge panel before the first run; amendments to this design are recorded below.

Owner: *"much more data analysis and thought process needs to go into things like this; there is an
obvious reason some choices make more sense than others, especially when all of this is understandable
via numbers and relations."* Server ask 01:30Z: arms, conditioning features, decision table (depth ≤ 3),
leave-coin-out validation, real-population sanity replay, `style_hint` JSON for the case files.

## 1. Machinery (inherited from M1/M10/M12 — unchanged)

Random-time BOTH-SIDED entries (direction is null by construction: this measures exit **geometry**, not
selection). 177 coins, 212d of 1h bars (`crunch/panels.sqlite`, read-only, snapshot stamped). Stop fixed
at **1.65 × HAR em** in every arm so only the exit policy varies. M1 v3 martingale control (coin's own
bar shapes, E[step] = 1 exactly) simulated per entry and **subtracted per arm** — two exit policies do
not price equally under no edge. Outcomes in **bps of notional net of 9 bps** round-trip taker AND in
**R**. Fee note: total turnover (entry 1.0 + exits summing to 1.0) is identical across arms, so a flat
9 bps is correct for every arm including two-leg runners. Equal-weighted per-coin means govern;
coin-clustered bootstrap CIs; ORIG17 / non-ORIG17 split reported.

## 2. Arms (7, all named now — no post-hoc arms)

| arm | definition |
|---|---|
| `full_1R` | all-out at +1R target, else stop, else close at 48h |
| `full_2R` | all-out at +2R target, else stop, else close at 48h |
| `runner_0.75atr` | half banked at +1R, rest trails 0.75 × ATR14 behind best, floor at stop, close at 48h |
| `runner_1.00atr` | same, 1.00 × ATR14 — **the live default (`exit_style.py` 'runner'); BASELINE** |
| `runner_1.50atr` | same, 1.50 × ATR14 |
| `runner_1.00atr_72h` | runner 1.00 ATR with a 72h limit |
| `trail_from_1R` | NO partial; at +1R the whole position trails 1.00 × ATR14, floor at stop, close at 48h |

Simulation horizon 72h for all paths; each arm applies its own clock. Runner semantics match
`exit_style.py:play` (trail floors at the original stop; before +1R the full position rides the stop).
Within-bar ordering is conservative: the stop/trail is checked before the favourable trigger in the same
bar. All arms fill AT the trigger level (optimistic); this flatters frequent-exit arms most — carried as
a stated limit, identical to M12.

## 3. Conditioning features — ALL point-in-time at entry (nothing after the entry bar)

| feature | definition |
|---|---|
| `atr_em` | ATR14 (14 closed daily TRs before entry day) ÷ that day's HAR em |
| `atr_pct` | ATR14 as % of close (vol level; raw threshold, no full-sample terciles in the shipped rules) |
| `stop_atr` | stop distance ÷ ATR14 (= 1.65 em / ATR) |
| `trend` | sign(SMA20d − SMA50d) × side (+1 aligned, −1 counter) — daily closes before entry |
| `room` | distance from the +1R price to the nearest 3-day-fractal swing level beyond it (60d lookback, highs for longs / lows for shorts), in ATR14 units; capped at 10 when none exists |
| `fund_pctl` | current funding rate's percentile within the coin's OWN funding history up to entry |
| `fund_cost` | side × current rate (positive = the position PAYS carry; shorts earn positive funding) |
| `btc_beta`, `btc_r2` | 60 daily returns before entry vs BTC |
| `hour` | entry hour UTC, 4 buckets (0–5 / 6–11 / 12–17 / 18–23) — M6 says the vol shape is stable |
| `ret7` | 7d return × side (into-strength vs into-weakness) |
| `oi_chg` | 24h OI change if `funding_oi_history` covers the entry time; else feature = NaN and it is reported as partial-coverage, never silently imputed |

## 4. Policy fit + validation (the part that could come out NEGATIVE)

- **Policy tree, depth ≤ 3, greedy**, split candidates at feature deciles, leaf = the arm with the best
  mean control-subtracted bps in that leaf; a split must clear a minimum improvement and min leaf n
  (≥ 500 entries) or it does not happen. No other model.
- **Leave-coin-out:** fit on 176 coins, apply to the held-out coin's entries; the per-coin POLICY GAIN =
  mean(chosen-arm outcome) − mean(`runner_1.00atr` outcome) on held-out entries. Headline = the
  equal-weighted per-coin mean of that gain, coin-bootstrap CI. **This number can be negative** (an
  overfit tree loses to the default out of coin) — that is the design's falsifiable content.
- **Placebo that CAN fail:** permute the feature rows across entries WITHIN each coin (outcome
  distribution preserved, feature→outcome link broken), re-run the full LOCO pipeline ≥ 200 times →
  null distribution of policy gains; p = fraction of null gains ≥ observed. A tree that only memorises
  arm marginals scores ~0 gain here by construction of the *gain* (chosen vs fixed default); any
  selection bias the pipeline leaks shows up as a shifted null — which is exactly what the placebo is for.
- **Pre-stated expectations** (so the "obvious" relations are on record before the run): runner beats
  full on aligned-trend + high `room` + high-vol entries; `full_1R` wins when `room` < ~1 ATR beyond +1R;
  the two BTC shorts' pattern (target ≈ next level, reversal after +1R) generalising is the owner's
  hypothesis, not yet a finding. Where the data disagrees, the table says so.
- **Decision table shipped** only as a few interpretable rules (the tree's paths), each with: rule, n,
  held-out gain vs default, CI. Format for the server: JSON rules with thresholds →
  `data/hivemind/cases/<plan_id>.json` `style_hint`.

## 5. Real-population sanity replay

Bot trades (su ~295) + owner plans (late_logged EXCLUDED per the standing rule), replayed under all 7
arms with point-in-time ATR. Reported as UNDERPOWERED descriptive context — real entries are selected,
so this is a sanity direction-check on the policy, never the evidence.

## 6. Govern

Exploratory → HYPOTHESIS card max. No prereg is touched: `PREREG_PARTIAL_EXIT` arm B stays sealed as
amended (e0621993) regardless of what M13 finds. A planner-default change would need its own prereg —
the server said the same. Snapshot stamped; harness HALTs rather than reaching a verdict with missing
data; every rate carries its n.

---

# AMENDMENT 1 — red-team panel (3 judges, 6 FATAL / 7 MATERIAL / 9 MINOR), adopted BEFORE the first run

The panel reviewed this design against the inherited M12 code. Every FATAL and MATERIAL is adopted;
the design above is superseded where it conflicts. Full defect list in the session workflow journal.

**FATALs closed:**
1. **Per-entry control, K = 16 martingale draws** (+1 independent draw reserved as `nullreal`). The
   no-edge price of each arm is a mechanical function of `stop_atr`/`atr_em` — coin-level control
   subtraction leaves that mechanical feature→outcome link for the tree to "discover", and the placebo
   would certify it. The LOCO gain is mean(ctrl-subtracted chosen) − mean(ctrl-subtracted baseline) on
   the same entries.
2. **Pipeline null test that can fail:** before the real table is read, the full fit (tree + LOCO +
   placebo) runs on `nullreal` (pure-martingale outcomes, true gain 0 by construction). Gate: headline
   CI covers 0 and placebo p non-significant — else the pipeline is broken and nothing is read.
3. **em lagged one closed day** (M12 mapped day d's em from day d's own return — leak closed; also
   live-consistent). Applies to the stop, R units, `atr_em`, `stop_atr`, `room`'s +1R price, and entry
   eligibility.
4. **Trail ATR = the same point-in-time ATR14 per entry that feeds the features** (M12's full-sample
   constant is not reused; the control uses the identical width).
5. **`room` uses only fractals confirmed before entry** (swing day j counts iff j+3 ≤ D−1).
6. **Placebo = circular DAY-SHIFT**, not row permutation: per rep, one common offset k (4 ≤ k ≤ 208)
   rotates each coin's day-level feature table; entries, outcomes, controls fixed; full LOCO pipeline
   (decile computation included) re-runs per rep; ≥ 200 distinct k; p = (1+#{null ≥ obs})/(1+B). Row
   permutation destroys feature autocorrelation and would make regime coincidence look significant.
   To keep observed and null in the SAME pipeline, the tested statistic uses day-level feature lookups
   (k = 0); the real-entry-feature gain is reported beside it.

**MATERIALs adopted:** headline decomposed into (i) best-single-in-fold-arm vs `runner_1.00atr` and
(ii) the tree's increment over (i) — the conditional-structure claim and the placebo attach to (ii)
only (the design's "~0 by construction" sentence was wrong and is retracted). Two-way uncertainty:
coin bootstrap × circular week-block bootstrap; act on the wider. Entry spacing 24 bars; leaf floors
≥ 500 entries AND ≥ 30 distinct coins AND no coin > 20% of a leaf. Shipped rules are out-of-fold:
a rule ships only if ≥ 80% of LOCO fold trees agree with its path; per-rule numbers from agreeing
held-out entries; anything in-sample is labelled IN-SAMPLE. MDE published from the null-rep SE
(MDE = 2.8 × SE) with the deviation fraction f; verdict rule: CI covers 0 AND half-width > 9 bps
(one fee) → UNDERPOWERED, never "no structure". **R units govern; bps secondary.** Time-split
robustness row (fit 1–106 → eval 107–212, and reversed).

**MINORs adopted:** fees on actual leg notionals (entry + each exit leg, same model in control);
funding carry accrued per leg holding period from the coin's own settled rates (backward asof,
≤ 2h staleness; coverage reported) in real AND control paths; split min-improvement pre-stated at
2 bps (training, equal-coin-weighted); `oi_chg` may split only where node coverage ≥ 80%, NaN follows
the majority branch deterministically; `fund_pctl` needs ≥ 200 prior settlements else NaN;
held-out coins with < 50 entries excluded identically from observed and null; every per-coin gain
asserted finite before aggregation (HALT otherwise); excluded-entry fractions reported; control
bar-shape pool is the coin's full history (stated limit — a null pricing model, not point-in-time).

# AMENDMENT 2 — pre-fit, compute-forced, recorded before any fit ran

- LOCO is implemented as **grouped 20-fold leave-coins-out** (coins partitioned deterministically;
  every evaluated entry is scored by a tree whose training set contained NO entry from that coin).
  Reason: the day-shift placebo re-runs the full pipeline ≥ 200 times; 201 × 174 single-coin folds is
  not computable on this machine. The out-of-coin property the red-team cared about is preserved.
- The tree's split objective and the 2 bps min-improvement are evaluated on the **bps** scale as
  written in Amendment 1; the HEADLINE is reported in **R** (governing) and bps (secondary) from the
  same fitted decisions.
- Coverage floor 0.8 applies to EVERY feature at a node (not just `oi_chg`); NaN entries follow the
  majority child deterministically in fit and predict.
- Null gate runs with B = 50 placebo reps (it gates the pipeline, not the finding); the real run uses
  B = 200.
