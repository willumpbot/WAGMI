# CORRECTIONS — final. Nothing changes in the bot.

_2026-10-08. Branch `laptop-mining-2026-10`. Read this instead of any other document here._

---

## The answer

**I produced four recommendations today. Independent review killed all four.** Two were refutations
of this project's earlier work that turned out to be wrong, and two were my own new proposals that
did not survive clustering. The correct action on the live bot is **nothing**.

| # | my recommendation | verdict | why it failed |
|---|---|---|---|
| 1 | stop `×1 → ×2` | **HOLD** | the only surviving number is an algebraic identity, not a measurement |
| 2 | target `1.5R → 0.5R` | **DROP** | never tested at ×2; week-weighted it is **negative** |
| 3 | `volforecast.py` HAR → EWMA | **HOLD** | **I refuted the original against a baseline I invented** |
| 4 | `TIME_STOP_HOURS` unchanged | **this one holds** | every CI contains zero; 9/12 cells flip sign |

Review trail: red team `wj68xvlf8` (3 agents) reversed the geometry refutation; red team `wp73ppfxp`
(5 agents, 546k tokens) then cut down my replacement. Every fatal finding was re-derived by me before
acceptance (`verify_v3.py`).

---

## My two substantive errors

### A. The volatility swap — I built a straw man and beat it

I claimed the original compared HAR against a degenerate `|yesterday's move|` baseline, QLIKE 4.79,
and called the "22/22 folds" meaningless. **The original did no such thing.**

| my claim | verified truth |
|---|---|
| baseline was `naive1 = \|yesterday\|` | `walkforward_vol.py:50` → **`"naive5": ret.rolling(5).std()`**, scored at `:117` |
| naive QLIKE 4.79 vs HAR 0.52 — a 36× gap | `walkforward_vol.json` → **HAR 0.1565 vs naive 0.2781 — 1.78×** |
| evidence: `grep -o y1 ... → 0` | true, but **`grep -o y5 → 0` as well** — the JSON stores no horizon label, so the grep proves nothing |

I substituted the degenerate baseline myself, produced the blow-up, and attributed it to the original.
And "HAR earns nothing over EWMA" holds **only** under QLIKE-on-level, where I capped HAR at 22 days
while the EWMA recursed over 120 returns. Under **MSE-on-variance at y5 HAR beats EWMA 19/22
(p = 0.0008)**, and on the axis the live code actually uses — stop exceedance at a nominal 5% stop —
HAR is **6.30% vs EWMA's 7.25%**. My verdict gate could not fire either: it averaged 22 per-fold
t-statistics and compared the average to −1.96, when the true 5% critical value is −0.34 to −0.73.

**Keep HAR. The claim that survives is narrow:** the 1-day horizon genuinely was never
walk-forwarded, evidenced by the three `fit(tr,"y5")` call sites, not by the void grep.

### B. The stop change — a test that could not fail, inverted

The project's recurring failure mode showed up one more time, in the fix I introduced to prevent it:

- **The fee saving is arithmetic.** `feeR(m) = feeR(1)/m` exactly. It is positive on every trade on
  any data, **including a driftless random walk** — so "positive in all 14 weeks, t = +8.84" is a
  property of division, not evidence. My figures were also off base: the simulation's *mean* `feeR` is
  **0.1483R at ×1 / 0.0741R at ×2**; I had used the median stop width (0.1272/0.0636).
- **My synthetic control's zero arm could not fail.** `h0 = ds - ds.mean()` pins the sample mean to
  exactly zero, then the percentile CI is built around that same mean. 0 of 400 seeds reject.
- **`BIND_FLOOR = 0.50` chose the answer.** `sym_adv` is monotone in stop width, so the floor *is* the
  recommendation: ≤0.143 → ×8, 0.143–0.443 → ×4, 0.443–0.791 → ×2, >0.791 → **nothing qualifies.** And
  my stated reason for rejecting ×4 — *"the bracket never binds"* — **is false; it binds on 44.3%.**
- **The non-fee remainder is not significant** (+0.0445R, CI [−0.0308, +0.0935]), and a GBM placebo
  reproduces ~95% of the surface.

So the honest version: requiring a bracket that resolves most trades leaves **nothing actionable**.
That is what the floor concealed.

---

## What actually survived the whole day

| finding | status | doc |
|---|---|---|
| **v2's refutation of the geometry work was itself wrong** — its null computed `(geometry) − (direction)`, so it read ~0 whenever the two matched, which they do. Verified to 5.6e-17 | **stands** | `GEOMETRY_V3.md` |
| **Tightening the stop below current is harmful** — −0.13R to −0.20R at ×0.5, CIs clear of zero | **stands** | `GEOMETRY_V3.md` |
| **Target-only changes at the current stop are null** | **stands** | `GEOMETRY_V3.md` |
| **No time stop in 4–72h beats having none** — every CI contains zero, 9/12 cells flip sign, synthetic control detects from 0.05R | **stands**, unreviewed | `EXITS_V2.md` |
| **The Squeeze column works, but it measures overbought/oversold, not "agreement"** — `disagree` adds −0.0024/−0.0012, permutation p 0.965/0.890; no definition of dissent adds anything | **stands**, unreviewed | `SQUEEZE_V2.md` |
| **The tie-rule assumption was wrong (39.1%, not 100%) but biased against our conclusions** | stands — though it has **no effect** on the cells it was cited to defend (0 of 15,663 trades) | `TIE_RULE.md` |
| **`ENSEMBLE_CONFIDENCE_FLOOR` is a backtest-only knob; live floor is adaptive, [20,80], starts 30** | stands | `CONFIG_AUDIT.md` |
| **`volforecast.py` stage-2 had test-set leakage** (gain 0.06%, p = 0.746) | stands — delete stage-2, keep stage-1 HAR | `RETRACTION.md` §6 |

**Two of these are worth something practically:** don't tighten the stop, and relabel the Squeeze
column. Neither is an edge. No directional edge was found anywhere today.

---

## The lesson, now three times over

Every failure in this project — including both of my corrections — is **a test that could not fail.**

| round | the test that couldn't fail |
|---|---|
| v1 | validated on data that had already chosen the answer |
| v2 | a null computing `(geometry) − (direction)`, zero whenever the two match |
| **v3 (mine)** | a zero-injection arm that pins the mean to zero; and a headline that was an algebraic identity |
| **vol v2 (mine)** | a baseline I substituted myself, then refuted |

**Adding a synthetic control was the right instinct and I implemented it wrongly** — pinning the
sample mean to zero and then testing that mean is circular. The correct form resamples or simulates
*new* data under the null, which is what the reviewer's GBM placebo did.

**Three rules going forward, each earned today:**
1. **Put the equal-weighted block mean next to every pooled figure.** Having the right clustering
   standard is not the same as applying it to the number you act on.
2. **Before refuting prior work, read the baseline it actually used.** Do not re-derive it from the
   write-up's description.
3. **Ask whether a positive result could ever have come out negative.** A quantity that is positive by
   construction will be positive in all 14 weeks and will have an arbitrarily large t as n grows.

---

## Still open

- **`ADX_MIN_TRENDING`** (`bot/trading_config.py:263`, now 10.0) is the only July-swarm knob that is
  both live and never examined. Highest-value remaining target.
- **`bot/data/trade_ledger.csv` does not exist on this machine** and the adaptive-floor argument rests
  on it. Needs the desktop's copy.
- **`SAFE_LEVERAGE.md`, `BASIS_TRADE.md`, `CROSS_SECTIONAL.md`, `LEVELS.md`, `MEMECARD.md`,
  `FUNDING_CARRY.md` were never reviewed.** Unknown, not clean.
- **`EXITS_V2.md` and `SQUEEZE_V2.md` are unreviewed.** Given today's record, treat as provisional.
- **The ladder/meme question is blocked on data, not method.** `call_tracker.py` is ready and needs
  `{ts, chat, caller, ca, chain}` at `bot/data/hivemind/tg/calls.jsonl`, times to the second, and raw
  text to separate fresh calls from re-posts. ~30 calls with caller IDs runs the pre-registered
  `P(peak ≥ k)` table.
- **The `−0.2174%, t = −10.0` drift figure** remains unreproducible. Do not quote it.
