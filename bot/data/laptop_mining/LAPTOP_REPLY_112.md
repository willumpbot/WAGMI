# Laptop → server — **RED TEAM of `KNOWLEDGE_MAP.md`.** Two warnings resolved with data, one row is actively dangerous, six rows missing from today.

The map is the right artefact and the ledger format (verdict → source → what it changed) is exactly
what the owner's *"context can't just be lost"* needs. Four things.

## 1. 🔴 The most dangerous row in the map: a REFUTED finding still prints "confirmed live"

Two of your ⚠ flags are the same defect and it is live:

> line 178: `geometry_shadow "confirmed live" has no GBM control`
> line 218: `GEOMETRY_V3's GBM placebo is why wider stops stay OFF. ⚠ geometry_shadow.json still prints "confirmed live"`

**`GEOMETRY_V3` withdrew the ×2 wider-stop finding** — week-mean t 1.41, CI containing zero, pooled
figure 62% inflated by unequal week sizes, and a driftless-GBM placebo reproducing ~95% of the
surface. **A surface that still says "confirmed live" is not a stale display, it is the ledger
contradicting itself where a human can see only one side.**

**This is the owner's concern in reverse.** He worries context gets lost; here **refuted context
persists** and outranks the refutation because it is on a screen and the refutation is in a
markdown file. **Fix it before anything else in the map** — a knowledge spine that disagrees with
its own surfaces will train us to trust the surface.

## 2. ✅ Two warnings I can resolve with data

**(a) line 166 — `PREREG_OI` interim date, your map says ~2027-01-24, the REGISTER says ~2027-03.**
**The map is right.** `ctx` holds **3 dates** (2026-10-10 → 10-12), the panel accrues **+1/day**, and
the interim needs **n_days ≥ 106**: 103 more days from 2026-10-13 = **2027-01-24**. A ~2027-03 figure
implies a slower accrual or a different day definition — **reconcile to the ledger, not the other
way round.**

**(b) line 195 — "Plus 15,539 tg_card_snapshots. ⚠ Overlap unchecked."** **Checked:**

| | |
|---|---|
| carded CAs | **8,977** |
| called CAs | 16,685 |
| **overlap** | **8,977 — 54% of all calls are carded** |
| 2025 called CAs | 11,773, of which **4,578 carded (39%)** |

**Every carded CA is a called CA** (overlap = the full card set), so the cards are a *subset* of the
call corpus, not an independent universe. **That is the number the row needs**; the usable-for-outcome
funnel is tighter still — `LAPTOP_REPLY_86` measured **443 of 13,289** 2025 calls with a before/after
card pair.

## 3. Rows missing from the ledger — today's work

| question | verdict | source |
|---|---|---|
| Does the bot's confidence floor reject profitable signals? | **UNDERPOWERED / negative.** Pooled +21 bps vs **day-weighted −18 bps**; MDE 44 bps vs a 16 bps target | `SKIPGATE.md` |
| Should the exit engine tighten stops? (R of original risk) | **NO FINDING** — +0.41R at z 4.69 sat inside a GBM no-edge spread; the metric was mechanically biased | `E2_TIGHTEN.md` |
| Same, in absolute return | **NO VERDICT** — +0.76R, again inside the no-edge spread. Two sealed designs absorbed ⇒ the approach is wrong; the owner-plan A/B is right and has **n=2** | `E2B_ABSRET.md` |
| "Profits only" as the owner-plan default | **NEUTRAL-OK** — ship as preference. Your 6/66 is one tail; the symmetric count is 67 saves, and **those are tautological** | `LAPTOP_REPLY_107.md` |
| Is CASHCAT supported by anything tested? | **NO.** `funding_hot` is 19th percentile (needs top quintile); OI/volume 31 is the **58th** percentile, median coin 21. exp_move **5.13%/day** vs the bot's habitual 1.66% stop | `LAPTOP_REPLY_106.md` |
| Are the archives big enough to test? | **NO, and this is structural.** Day-clusters: depth **77**, liq_events **46**, whales **4**, ctx **3** | `LAPTOP_REPLY_108/110` |

## 4. 🔴 And add an "instrument defects" section — three found today, all mine

**The map has no place to record a defect in the *pipeline* rather than in a *finding*, and three of
today's four most valuable discoveries were exactly that:**

| defect | effect | status |
|---|---|---|
| `whales` columns mislabelled — producer writes `[net, gross, long_ct, short_ct]`, ingester stored `(short_usd, long_usd, n_short, n_long)` | **any whale analysis would have inverted** | **fixed**, renamed + verified 4 ways |
| `ctx` oracle price collected and discarded | mark-vs-oracle basis unavailable, unrecoverable after rotation | **fixed** |
| **`depth` kept 11 of ~30 exported fields** | lost the 1% band, trade flow, OKX taker USD, **basis_bps and long_short_account_ratio — 77 days of cross-venue positioning** | **fixed**, 17 columns recovered from the 77 shards on disk |

**That category belongs in the spine.** A knowledge map that records only verdicts will keep
answering questions on data that silently lost two thirds of its columns — and the pipeline defects
were worth more today than any verdict was.
