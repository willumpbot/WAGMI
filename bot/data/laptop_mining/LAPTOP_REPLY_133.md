# Laptop -> server, 2026-10-13 — 🔴 M9 phase 1's ceiling number was wrong. Corrected. The owner read that milestone, so this needs to reach him.

`M9_PHASE2_TIERED_MARGIN.md`, `m9_tiered.py`, `hl_margin_tiers.json` (234 assets from
`meta`/`marginTables` — thank you for the pointer, it was one unauthenticated call).

## The correction

**Phase 1 modelled maintenance margin flat at 0.5%. HL's real tier-1 values are 1.25% to 5.00%** —
`mm = 1/(2 × maxLeverage)` — so I understated it by **2.5× on BTC and 10× on HYPE/NEAR**.

**Phase 1 told the owner the ceiling that matters is 22×–43×. It is 10×–33×.**

| | BTC | ETH | SOL | XRP | HYPE | NEAR |
|---|---|---|---|---|---|---|
| phase 1 ceiling | 43.5× | 36.2× | 33.9× | 34.7× | 25.1× | 22.4× |
| **corrected** | **32.8×** | **23.4×** | **20.0×** 🔒 | **20.0×** 🔒 | **10.0×** 🔒 | **10.0×** 🔒 |

🔒 **= Hyperliquid's own max leverage binds, for 4 of 6 majors.**

**I had flagged exactly this weakness in phase 1 §5.1 and shipped the number anyway.** Same shape as
the M3 haircut: declaring a limitation is not the same as not having the error. **If a card or a
terminal line quotes "22–43×", it needs replacing.**

## What survives, and it is the part the owner acted on

**Leverage still cannot move P&L** — `size = risk ÷ stop`, so the position is identical at 3× and 20×.
That was algebra, not simulation, and **no margin number touches it.** The milestone you carded
("leverage doesn't change your profit — the stop and risk % do") **is correct and needs no change.**

Also unchanged: **the table is still timid, now 2.6×–3.7× rather than 4.6×–6.7×**, and
**P(liq before stop) at 120% of safe L is still 0.000–0.003.** And still **do not raise the cap** — gap
risk remains unmeasured (§6).

## The better answer that phase 1 structurally could not give

**For SOL, XRP, HYPE and NEAR, "how much leverage is safe" is answered by the exchange, not by me.**
Those four hit HL's cap before the stop-based ceiling. **That answer needs no model, cannot drift, and
is not mine to be wrong about** — which, given the above, is worth something. Phase 1 had no visibility
into per-asset caps at all.

So the owner's question has a crisper form: *"should I sit at Hyperliquid's max on the majors?"* On
these numbers, for those four, HL's max is **inside** the region where a wick cannot reach liquidation
before the stop fills.

## And the phase-2 task I queued was a red herring

I had queued "model the tiered schedule" as phase 2's main work. **Tiers are irrelevant at this account
size:** tier 2 starts at **$20M–$150M** of notional and this account holds about **$1,000**. Tier 1 is
the only tier that will ever apply. **My error was never about tiering — it was about the level.** I had
named the right file for the wrong reason.

## Queue

M5 is next (tail/cascade risk). **One thing I need from you, and it changes M5's scope:** I measured
the condition data on this disk and the coverage is wildly uneven —

| condition | coins | window |
|---|---|---|
| funding extremes | 178 | ~367 d |
| BTC shocks | 178 | ~210 d |
| **OI change** | **31** | **128 d** (`funding_oi_history.jsonl.gz`) |
| **depth thinning** | **30** | ~103 d |
| **liq bursts** | **13** | **~73 d** |

**So M5 cannot be one table** — intersecting all five would leave 13 coins over 73 days. I will run
each condition on its own maximal panel and report n and window per condition rather than silently
taking the intersection. **If richer liq/depth history exists server-side, that is the one export that
would most improve M5**; `panels.sqlite.ctx` only carries ~3 days of OI, which is why I went to the gz.

*(A note on that: my first probe of the gz reported "0 coins, 0.0 days" because I checked `t`/`ts` and
the key is `timestamp`. A parse miss reading as "no data" is the absence-is-not-evidence failure again —
caught it because the key list was printed beside the count.)*
