# Untapped-potential sweep — **three ingester defects found, and the ranking reordered after the owner correctly pointed out I was ranking novelty over power.**

_2026-10-13. Four agents characterised `liq_events`, `whales`, `depth` and the `ctx`/OI panel. Answering
the owner's "there's a lot we aren't even paying attention to, potential-wise… time is extremely on
our side."_

---

## 1. The headline: it was not unasked questions, it was unwired fields

**Three ingester defects, all mine, all found by characterising streams rather than studying them:**

| defect | cost | status |
|---|---|---|
| **`depth` kept 11 of ~30 exported fields** for 77 days | lost the 1% band, trade flow, OKX taker USD, **`basis_bps` and `long_short_account_ratio`** | **fixed**, 17 columns recovered from shards on disk |
| `whales` columns mislabelled | **any whale analysis would have inverted** | **fixed**, verified four ways |
| `ctx` oracle price collected and discarded | mark-vs-oracle basis unavailable, unrecoverable after rotation | **fixed** |

**The recovered positioning data is the single best untested asset in the project:**

| recovered column | rows | days | symbols | symbol-days |
|---|---|---|---|---|
| **`ls_acct_ratio`** (OKX long/short accounts) | 62,867 | **77** | 29 | **741** |
| `basis_bps` | 62,865 | 77 | 29 | 741 |
| `tk_bs_ratio`, `tk_buy_usd` (taker flow) | ~62,500 | 76–77 | 29 | ~740 |
| `imb_1` (1% book imbalance) | 62,886 | 77 | 30 | 742 |

**5 symbols have all 77 days** (BTC, ETH, HYPE, SOL, XRP); **12 have ≥40**; median **12 symbols/day**.

## 2. Cluster counts — the number that decides everything here

| stream | rows | **day-clusters** | verdict |
|---|---|---|---|
| **`depth` + recovered fields** | 62,913 | **77** | **best available; testable now** |
| `liq_events` | 71,816 | **46** | Bybit (cross-venue), 26 missing days, 10-08 break, counts confounded with uptime |
| `whales` | 21,495 | **4** | wait ~60–90 days |
| `ctx` / OI | 37,202 | **3** | wait; interim ~2027-01-24 |

**At 77 clusters the resolvable effect is roughly 40 bps**, by the same arithmetic that made three of
today's studies underpowered. **So the only questions worth sealing are ones whose honest prior
effect is large** — which in this project means **unsigned** (size, volatility, stop-breach), never
signed direction. `SIZE_FLAGS` is the sole finding that ever survived a red team here, and it is
unsigned (`funding_hot`, +7.4% on next-day |move|).

## 2b. 🔴 OWNER CORRECTION, and he is right — I ranked for novelty instead of power

**Owner: "we can also test our data on the extensive ohlcv and other data we've mined right? we
shouldn't be in any way limited."**

**Correct, and §2 under-sold it badly.** The deep panels are not 77-day limited:

| panel | **dates** | coins | coin-days |
|---|---|---|---|
| `candles_1h` | **210** | 178 — and **173 have ≥200 dates** | 36,779 |
| `funding_hist` | **367** | 178 | 63,138 |

**That is 3–5× the clusters of anything I ranked, on a near-complete balanced panel.** I anchored on
the new streams because the sweep asked for *untested* data, and treated "new" as "where the value
is". **Power beats novelty, and the deep panels win on power by a wide margin.**

**And the deep panel is far less tested than I implied.** `SIZE_FLAGS` tested four flags
(`funding_hot`, `volume_surge`, `vol_expanding`, `funding_cold`) on **17 clean perps / 19,853
coin-days**. The panel holds **173 coins with ≥200 dates** — a **10× larger cross-section** that has
never been used, plus `funding_hist.premium` (367 dates) which I have never touched at all.

**So the ranking below is reordered: deep-panel questions first.**


## 2c. 🔴 THIRD CORRECTION, mine: #1 as written is dead — SIZE_FLAGS already used the whole deep universe

**I checked instead of assuming, and the check killed my own top pick.**

| what I claimed | what is true |
|---|---|
| "173 coins vs 17 is a 10× cross-section upgrade" | the 173-coin panel is the **hourly** one at **210 dates**; SIZE_FLAGS ran on **160 week-clusters (~1,296 dates)** of DAILY history. **That is a 5.6× cluster DOWNGRADE, not an upgrade.** |
| "41 daily files vs 17 used = 2.4× headroom" | **the other 24 are `_spot` and `_wspot` series, not perps.** Distinct perps with deep daily history: ARB AVAX BTC DOGE ENA ETH HYPE LINK NEAR PUMP SOL SUI UNI VVV WLD XRP ZEC = **exactly 17** |

**So `SIZE_FLAGS` used 100% of the deep-history perp universe.** There is no untapped breadth *or*
depth in the daily panel. **"Re-run it on the full panel" has no fuller panel to run on.**

**Three framing errors in a row on this one ranking**, and worth recording as a pattern rather than
three mistakes: I kept asserting a power claim and then checking it. The order should be reversed —
**count the clusters first, rank second.**

**What actually survives as a question:** *does `funding_hot` generalise from the 17 deep perps to the
178-coin hourly universe?* The 161 extra coins are smaller, newer alts where the effect may well
differ — that is a real generalisation test. **But it is 210 dates / ~30 weeks against SIZE_FLAGS'
160 weeks**, so it is a breadth test at reduced depth, and it must be labelled that way. **It cannot
overturn SIZE_FLAGS; at best it extends it, at worst it is underpowered.**

## 3. Ranked candidates — value ÷ effort, with power honesty

| # | question | why it ranks here | clusters |
|---|---|---|---|
| **1** | **Does `funding_hot` GENERALISE from the 17 deep perps to the 178-coin hourly universe?** | **Reframed per §2c — a breadth test at reduced depth, NOT a power upgrade.** The 161 extra coins are smaller, newer alts where the effect may differ. Cannot overturn SIZE_FLAGS (30 weeks vs its 160); at best extends it | **210** |
| **2** | **Does `funding_hist.premium` (basis) predict next-day \|move\| beyond HAR + funding_hot?** | **367 dates, 63,138 coin-days, and I have never touched this column.** Deepest series we own. Carry/positioning, so not a repackaged HAR input | **367** |
| **3** | **Does funding PERSISTENCE (consecutive hours extreme) beat funding LEVEL?** | `funding_hot` is a level. Persistence is a different quantity on the same deep panel, and the natural next question after #1 | 367 |
| **4** | **Does OKX long/short account ratio predict next-day \|move\| beyond HAR + funding_hot?** | **Positioning, not price** — HAR cannot contain it by construction, avoiding the trap that killed `vol_expanding`. Genuinely new. **But 77 days against 210–367 above** | **77** |
| 5 | Does 1% book imbalance add to the same model? | same panel, free, and it is **the band the server's own idea generator already uses** — so it gets graded forward either way | 77 |
| 6 | Does OKX taker buy/sell flow predict next-day \|move\|? | genuinely new, but flow and volatility are mechanically coupled through the same prints — **needs a "could this have come out negative" answer before it is worth a seal** | 77 |
| 7 | Is `basis_bps` redundant with `funding_hist.premium`? | **a redundancy check, not a prediction** — cheap, and it decides whether #1–3 need basis as a control or can ignore it. **Do this before #3.** | 77 vs 367 |
| 8 | Do Bybit liquidation bursts predict next-day HL spread/depth deterioration? | the one `liq_events` question with a clean 46/46 join, and it targets **execution cost** rather than direction | 46 |
| — | whale net positioning, OI change | **do not seal.** 4 and 3 clusters. Revisit ~December | 4, 3 |

## 4. What gets sealed, revised

**Nothing is sealed in this commit.** The reorder changes which question deserves the first prereg,
and sealing the 77-day one while a 210-date version of the same shape sits unwritten would be exactly
the novelty-over-power error again. **#1 (funding_hot on the full panel) gets the first prereg**,
because re-validating the project's only surviving positive on 10× the cross-section is worth more
than any new predictor.

_Superseded text follows: the original plan sealed the positioning question first._

**#1 was to be sealed in the same commit as this document**, before any predictor-outcome quantity was
computed. Its shape deliberately copies `SIZE_FLAGS` — the only design here that ever produced a
surviving positive — and it carries the three guards today taught:

- **unsigned outcome** (next-day |move| ÷ `exp_move`), so a direction claim cannot sneak in;
- **HAR and `funding_hot` as explicit controls**, because `vol_expanding` died from being a
  repackaged HAR input;
- **a no-edge control whose median is subtracted, not just inspected** — the `placebo_could_fail`
  boolean would have passed E2, E2b and X2.

## 5. What the sweep says about the owner's premise

**He is right that time is the asset, and right that we were not paying attention — but the gap was
plumbing, not imagination.** Four streams, ~195,000 archived rows, and the binding constraint on
every one of them is **independent days**: 77, 46, 4, 3. No amount of analysis creates those.

**But the owner's correction in §2b is the more important half:** the deep panels carry **210 and 367
dates**, so "limited" was my framing error, not a property of the data. **The thin streams are
limited; the OHLCV and funding panels are not**, and the first prereg belongs there. **The highest-value action remains what it was in
reply 102: make sure every collector is running, complete, and correctly labelled** — because three
of the four streams were silently degraded and nobody would have noticed from a dashboard.
