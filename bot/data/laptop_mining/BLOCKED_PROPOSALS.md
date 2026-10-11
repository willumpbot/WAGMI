> # 🔧 The anomaly I flagged was a real grader bug. Window was 4h, not 12h. Verdict unchanged; my *mechanism* was misnamed.
>
> The server confirmed (`82eb3151`): `live_grader` resolved every row at **4h+10m**, so `r12h` was always
> None and `up12`/`dn12`/`sltp` were computed on **~4h of path** — the "12" labels were wrong. **And the
> resolve-rate gap I flagged has a cause: long proposals carry wider stops, so they rarely resolve inside
> 4h.** 3.3% vs 32.8% explained. Side mapping is correct. Fixed going forward at 12h15m, with `sl_bps` /
> `tp_bps` now on each row — **existing rows still have neither (0/1048), so the expectancy-in-R
> calculation still cannot be done.**
>
> **Correcting myself on the mechanism.** I wrote "a rising two-day window stops out shorts — that is
> drift." Right direction, wrong quantity: **net drift over 4h is only 2.6 bps**, trivial against any
> plausible stop. The mechanism is **excursion asymmetry** — up-moves averaged **99.1 bps** against
> down-moves **55.9 bps**, a **1.77×** ratio — and SL/TP hits depend on *excursions*, not net return. For
> short proposals the adverse excursion ran **1.83×** the favourable one, which is the right shape for the
> observed 6.4:1. **The conclusion is unaffected; the sentence explaining it was imprecise.**
>
> **"Stay flat by decision asymmetry" was accepted by the server and shown to the owner.**

# Is any blocked proposal worth taking? **The data cannot say — and the number that looks like proof is drift.**

_2026-10-11. Answering the server's suggested mission. `agent_grades_resolved.jsonl`, 1,048 `ic_muted`
dropped proposals. Scoped power-first as asked._

---

## 🔴 Answer in three lines

1. **The honest verdict is "stay mostly flat"** — but **not** because blocked proposals were shown to lose.
2. **Because nothing here is evidence *for* unblocking**, and the one figure that looks like evidence
   *against* is explained by two days of market drift.
3. **What would settle it: ~8 weeks of the same resolution data, plus each proposal's SL/TP distances.**

## The figure that looks damning

| outcome | n |
|---|---|
| hit **SL** first | **221** |
| hit **TP** first | **33** |
| neither within 12 bars | 794 |

**6.7 stops for every target.** Breakeven would need a target worth **>6.7R**; the bot's geometry is about
8% / 1.78% ≈ **4.5R**. Read naively: clearly negative, don't unblock.

## ⚠️ Why I will not report it that way

**96% of all resolved outcomes are SHORT proposals, in a window that rose.**

| side | proposals | resolved | resolve rate | SL | TP |
|---|---|---|---|---|---|
| LONG | 304 | 10 | **3.3%** | 10 | **0** |
| SHORT | 744 | 244 | **32.8%** | 211 | 33 |

A rising two-day window stops out shorts. **That is drift producing the ratio, not an absence of edge** —
the same mechanism that voided the test in `LONG_SIDE.md` update 2, and I am not walking into it twice.
The LONG arm cannot rescue the comparison either: 10 resolved outcomes is nothing.

**The window is 2.0 days and 1 ISO week.** There is no second block to cluster on, so there is no
inference to be had — only description.

## 🔧 A data anomaly worth the server's attention

**Long proposals resolve at 3.3%; shorts at 32.8% — a 10× gap — while their excursions are nearly
identical** (LONG up12 106.2 / dn12 63.6 bps; SHORT 96.2 / 52.7). Similar price movement, wildly different
rates of touching a level. So either **long SL/TP levels are set far wider**, or **the resolver handles the
sides differently.** One of those is a config fact worth knowing and the other is a bug. It also rhymes
with the (now-closed) long-side puzzle, so it may be the same root.

## The slice screen — reported as a screen, because that is all it is

22 slices had ≥15 resolved outcomes. Best three by stop:target ratio:

| slice | resolved | SL | TP | SL:TP | target needed to break even |
|---|---|---|---|---|---|
| `btc4h=against` | 147 | 15 | 12 | **1.2** | >1.2R |
| `sym=XRP` | 169 | 22 | 11 | 2.0 | >2.0R |
| `sym=HYPE` | 176 | 51 | 14 | 3.6 | >3.6R |

`btc4h=against` is the only slice whose ratio sits below the bot's ~4.5R geometry. **It rests on 27
outcomes, chosen as the best of 22 slices, inside a single week.** Against a Bonferroni-style bar over 22
slices that is a lottery ticket. **I am not proposing it as a filter**, and I would hold the same view if
it had come out twice as good.

Four slices — `session=late`, `sym=BTC`, `sym=NEAR`, `session=asia` — recorded **zero** TP hits across 155
resolved outcomes. That is suggestive of genuinely dead conditions, and it is the one pattern I would check
first when more weeks exist.

## Trader rules — one number each
1. **Staying flat is the right default**, because there is **no** evidence for unblocking — 0 of 22 slices
   clears a credible bar.
2. **Do not believe the 6.7:1.** 96% of it is short proposals in a rising two-day window.
3. **~8 weeks** of this resolution data would make the question answerable. 2 days cannot.

## Limits
- **2.0 days, 1 ISO week, no clustering possible.** Everything above is descriptive.
- `sltp` records **which level was hit first, not how far away it was**, so a hit-ratio cannot be converted
  into an expectancy in R without the distances. The 4.5R comparison uses the *traded* book's typical
  geometry as a stand-in, which may not match these proposals — especially given the resolve-rate anomaly.
- `r12h` is missing on **all 1,048** dropped rows, so the 794 unresolved proposals contribute nothing. If
  they drift favourably the true picture is better than the resolved subset implies; if adversely, worse.
  **The resolved subset is not a random sample of the proposals.**
- The 135 `pipeline` rows were unusable: `sltp` is absent on 132, and `quant` rates **all 135** as
  `ev=neutral,quality=noise`.
