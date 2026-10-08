# CORRECTIONS — the five refuted findings, re-run. One page.

_2026-10-08. Read this instead of the five original documents. Branch `laptop-mining-2026-10`._

---

## What happened, in three sentences

A six-agent red team refuted all five findings this project had produced. I re-ran every one with the
defect fixed. **One of the refutations was itself wrong** — a second red team found the null used to
kill the geometry finding was algebraically incapable of detecting it — so that finding is half
reinstated.

---

## The scoreboard

| # | original claim | v1 verdict | **after re-running** | action | doc |
|---|---|---|---|---|---|
| 1 | stop/target geometry worth +0.35R | REFUTED | **half real.** +0.1745R direction-free (71% fee drag) + +0.1734R directional (unvalidated). Best *binding* cell is **×2 / 0.5R, +0.1187R**, CI [+0.0395, +0.1661] | **SHIP ×2 / 0.5R** | `GEOMETRY_V3.md` |
| 2 | HAR beats naive 22/22 folds | REFUTED | **confirmed refuted.** Vol *is* forecastable (9× better than naive) but HAR ties a one-line EWMA: 7/22 at y1, 11/22 at y5 | **swap HAR → EWMA** | `VOLATILITY_V2.md` |
| 3 | low dissent predicts a ~5% day | REFUTED | **confirmed refuted** — and constructively. The column has real skill (AUC 0.598/0.569) but it is **extremity**, not consensus; `disagree` adds −0.0024/−0.0012, permutation p 0.965/0.890 | **keep column, drop consensus term, relabel** | `SQUEEZE_V2.md` |
| 4 | early time stops cost −0.116R | REFUTED | **confirmed refuted** by a second route. With a horizon long enough to fire and a bracket that binds, every CI contains zero and 9/12 cells flip sign | **HOLD — no change** | `EXITS_V2.md` |
| 5 | removing the ×0.80 patch cuts QLIKE 4.0% | REFUTED | **moot.** The stage-2 correction sat on HAR's residuals; #2 removes HAR. Red team already measured the honest gain at 0.06%, p = 0.746 | **delete stage-2 with the HAR swap** | `RETRACTION.md` §6 |
| — | tie-rule assumption (not a claim, an assumption) | — | **was wrong — 39.1% stop-first, not 100% — but it biased *against* our conclusions,** so it rescued nothing and makes #1 slightly understated | note it, no action | `TIE_RULE.md` |

**Net: 1 finding half-survives as a cost effect, 1 simplifies the system, 1 keeps its column under a
truthful label, 2 are dead.** No directional edge survived anywhere.

---

## What to actually change

| # | change | worth | confidence |
|---|---|---|---|
| 1 | bot stop `×1 → ×2`, target `1.5R → 0.5R` | **+0.1187R/trade** | high — it's a fee saving, needs nothing predicted |
| 2 | `volforecast.py`: HAR → EWMA (λ on train, grid 0.88–0.97) | 0 accuracy, −3 parameters | high |
| 3 | Squeeze column: `disagree` → `\|RSI−50\|/50`, `\|bb z\|`, `n_active`; relabel | +0.0097 AUC on shorts | high |
| 4 | `TIME_STOP_HOURS` | **do nothing** | high |
| 5 | delete `volforecast.py` stage-2 | removes a leak | high |

**Do not ship:** the ×8–×32 stop (the bracket never binds there — 15 of 24 cells are saturated), the
"keep the stop, change the target" alternative (`1.0|0.5` CI [−0.0431, +0.1087], null), or any
agreement→size logic.

---

## The one root cause

Every failure, including my own reversal, was **a test that could not fail.**

| round | the test that couldn't fail |
|---|---|
| v1 | validated on data that had already chosen the answer (feature selection and thresholds read off the test set) |
| v2 | a null computing `(geometry) − (direction)`, which reads ~0 whenever the two are equal — as they are here. It killed a *known-real* 0.148R effect in synthetic control |

**The fix, now standard in every script:** before a null is allowed to kill a finding, build an
exact-zero-effect dataset, confirm no false positive, then **inject a known-real effect of the
expected size and prove the test detects it.** Report the smallest detectable effect alongside every
null result.

It is already paying for itself. `geometry_v3` detects from 0.08R; `exits_v2` from 0.05R — and v1's
claimed exit effects were 0.09–0.12R, comfortably inside that floor, so their absence is now
*evidence of absence* rather than a failure to look.

---

## Still open

- **Review status.** Geometry v3 and volatility v2 went to a 2-reviewer red team (`wp73ppfxp`);
  verdict pending at the time of writing. Exits v2 and squeeze v2 are **unreviewed** — treat as
  provisional.
- **The 48h drift figure** (`−0.2174%, t = −10.0, "robust"`) is still unreproducible from the script
  that supposedly produced it, and fails week-clustering (t = −1.02). **Do not quote it.** Re-derive
  or delete.
- **`SAFE_LEVERAGE.md`, `BASIS_TRADE.md`, `CROSS_SECTIONAL.md`, `LEVELS.md`, `MEMECARD.md`,
  `FUNDING_CARRY.md` were never reviewed.** Status unknown, not clean. The three *negative* results
  among them (basis, cross-sectional, funding carry) are the least likely to be wrong, since a null
  does not benefit from the biases found here.
- **The ladder/meme question is blocked on data, not method.** Three sampling attempts
  (195–228 pools each, only 28–38 with two weeks of history) failed because public pool listings are
  almost all brand-new. `call_tracker.py` is ladder-aware and waiting on the PC's TG scanner feed:
  it needs `{ts, chat, caller, ca, chain}` at `bot/data/hivemind/tg/calls.jsonl`, call times to the
  second, and raw text to separate fresh calls from re-posts. ~30 calls with caller IDs is enough for
  the pre-registered `P(peak ≥ k)` table.
