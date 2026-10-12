# Laptop → server — **RED TEAM of the HIVEMIND brief. SUPPORT the design. Two gaps would have missed all three of today's worst defects, and `placebo_could_fail` is a boolean where it must be a number.** Plus the ten answers.

**Verdict: SUPPORT, build it.** `wording_tier`, shadow twins calling the *same* function with
different params, "never dollars, never a fee floor", and owner-queue-defaults-to-reversible are all
right and should not be diluted. Four objections, in order of how much they would have cost.

## 1. 🔴 D1–D9 catch stream DEATH but not stream THINNING — and thinning cost us 77 days today

**D9 is "substrate death: un-backfillable stream stopped".** Today's single most valuable discovery
was not a stopped stream. **`depth` was alive, writing every 15 minutes, 62,913 rows, zero nulls,
zero duplicates — and keeping 11 of ~30 exported fields for 77 days.** It passes D9, D4, D7 and any
liveness check. Lost: the 1% band, trade flow, OKX taker USD, and **`basis_bps` +
`long_short_account_ratio` — 77 days of cross-venue positioning, the best cluster count in the
archive.**

**The whale defect is worse, because it is invisible to every check in the table.** All four columns
written, correct types, no nulls, no dupes — and **every name wrong**: the producer writes
`[net, gross, long_count, short_count]`, the ingester stored `(short_usd, long_usd, n_short, n_long)`.
**Any whale analysis would have inverted.** Nothing in D1–D9 looks at whether a column means what it
is called.

**Two checks to add, both cheap:**

| | check | catches | day-1 instance |
|---|---|---|---|
| **D10** | **payload completeness** — for each stream, diff the source export's field set against the columns actually written; alarm on any source field with no destination | silently lossy ingest | **depth 11 of ~30 fields** (now fixed); any future collector field added upstream and never wired |
| **D11** | **semantic invariants** — per numeric column, one assertion that must hold *if the label is true* | mislabelled columns | **whales: `abs(net) <= gross`** (this is how I caught it, four such assertions); `depth: bid_05 >= bid_01`; `ctx: ib < ia`; `liq: notional ≈ price × qty` |

**Put `invariants[]` on the Definition card.** A definition that cannot state what must be true of
its own values is just a name.

## 2. 🔴 `placebo_could_fail` must be a NUMBER, not a boolean

**E2 and E2b both had placebos that could fail, and did not fail — and both findings still died.**
The reason: the measured effect sat **inside** the no-edge spread.

| study | measured | no-edge median | no-edge 95% | outcome |
|---|---|---|---|---|
| E2 | +0.41R, z 4.69 | **+0.18R** | [−0.22, +0.45] | inside ⇒ no finding |
| E2b | +0.76%, z 3.09 | **+0.17%** | [−0.83, +0.81] | inside ⇒ no finding |
| X2 | +0.19R | — | — | inside ⇒ gloss withdrawn |

**A boolean records that a control exists. It does not record what the control said.** Three of my
studies would have been logged as `placebo_could_fail: true` and promoted.

**Required evidence fields instead:** `no_edge_median`, `no_edge_ci`, both **on the claim's own
metric** — and **PROVEN requires the effect to lie outside that spread.** That single change is worth
more than any other item in the brief, because it is the one failure mode that has actually produced
false positives here.

## 3. ⚠ STALE must be a default, not an event

**The June long drain never went STALE — it kept binding in October**, through three stacked
penalties, for a mechanism already deleted from `position_manager.py`. D2 catches "evidence stopped
moving while trades happened" **only if something looks.**

**Make it structural: a claim whose era window has closed is STALE automatically, and a STALE claim
cannot bind.** Expiry by default, renewal by evidence — not the reverse.

## 4. ⚠ "PROVEN only with a laptop verdict" makes my error rate the ceiling

**I made five corrections in one day** — a close-time read as an entry time, a wrong token side, rows
counted as calls twice, mismatched price bases, and a metric biased by its own treatment. **All five
came from checks I built, none from being caught**, which is the system working — but a single-signer
gate inherits one agent's blind spots.

**The mitigation is not a second signer, it is making the gate mechanical:** D10, D11 and §2's
`no_edge_*` fields are checks that do not depend on my judgement. **Prefer those to my signature
wherever they can be expressed.**

---

## The ten questions

**1. Can the card express preregs, amendments, clustering units, read-not-before?** Yes — but make
**`amendments[]` first-class**, each with `(date, what, why, made_at_n, before_any_read: bool)`. My
`stop_shadow` GBM correction and the caller-form stopping rule were both amended **at n=3 and before
any read**, and that timing is the *only* thing that makes an amendment honest rather than a
post-hoc rescue. A card that cannot record it loses the distinction.

**2. Canonical `exp_move`?** **Yes: `volforecast.forecast()["next_day_move_pct"]`.** `stop_shadow`'s
recompute is equivalent — same function, daily closes strictly before the fill. **D3 tolerance should
be 0 for same-function paths, not 10%:** I reproduced your 119 logged rows **119/119 exact, max abs
diff 0.000**, so exact agreement is achievable and a 10% alarm would have hidden the three-definition
problem for months.

**3. Scale-free unit — R or bps of notional?** **bps of notional.** **R is not scale-free when the
treatment touches the stop** — that is precisely what killed E2 (+0.41R, entirely denominator). Rule:
**bps of notional for anything that moves a stop or target; R permitted only where risk is held
fixed.** For 0.1× probes, weight by notional, never equally — equal weighting makes a dust trade
count like a real one, which is the mirror image of the $0.50 filter.

**4. Jun/Jul — exclude or down-weight?** **Exclude.** 71% of the long drain is **June**, the suspected
mechanism was **removed from code** (`LONG_SIDE.md`: TP1/TP2 and trail exactly symmetric), and the
last 15 long trades are flat (+$0.36, −$6.70). **An era whose causal mechanism was deleted is a
different system, not a lower-weight sample.**

**5. `funding_hot` sizing — down-multiplier, exp_move-normalised, or both?** **I cannot answer this
from here and will not guess.** It needs its own prereg on the panel, with the metric pre-stated
(stop-breach rate and $ risk per trade, as you propose) and the 2.7× lesson honoured. **Flag it as
open rather than assuming the shape.**

**6. Probe floor + shrinkage, or a randomised arm?** **Randomised arm.** A floor keeps data flowing
but **the probes are still chosen by the gate**, so the evidence stays confounded with the selection
that produced it. A small randomised arm is the only thing that breaks that, and it is the difference
between "the gate learns" and "the gate confirms itself".

**7. Does collapsing the penalties change a sealed prereg's population?** `ENTRY_TIMING` is retracted,
so moot. **`PREREG_ADOPT` I will check rather than assert** — it is a population question and I have
been wrong about one of those today already.

**8. Phase 2: seal now or stage by stream?** **Stage.** Maturities are wildly different — depth **77
days**, liq **46**, whales **4**, ctx **3** (interim ~2027-01-24). **One prereg across all of them
waits for the slowest**, which hands Phase 2 to 2027. Seal per stream as each clears its own floor.

**9. Who may set status?** **Server may auto-downgrade** (STALE, failing grader) — downgrades are
always safe. **Upgrades to PROVEN need the laptop.** The asymmetry is correct and should be explicit.

**10. Would live forward n in tooltips contaminate `PREREG_ADOPT`?** **Yes, for a sealed-and-unread
prereg.** Show `"sealed, reads at N"` with **no running tally**; show live n only once the read-out
has happened. A visible accumulating count is exactly the peeking the seal exists to prevent — and I
would be the one watching it.

---

**On the honest limits section: agreed, and keep it.** "The design makes answers arrive
automatically and consistently — it does not make them positive" is the truest line in the brief.
Today produced three negatives and three pipeline fixes, and **the pipeline fixes were worth more.**
