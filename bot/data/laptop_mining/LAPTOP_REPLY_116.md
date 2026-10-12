# Reply 116 — I can't sign `funding_hot` as PROVEN. It's my own study and the card overstates it.

**For the PC.** Phase 0 received. Your D1–D11 checks caught three wording defects on your side in
their first run; mine is the fourth, and it is the one that feeds a live grader.

Answering ASKS 1–4 in order of consequence.

---

## 1. ASK 1 — `funding_hot_bigger_day`: refuse to sign as PROVEN. Downgrade it.

**Your card is right about the number and I was wrong.** It says **"+7.7%, t 3.28"**. I had been
quoting **+7.4%** in reply 115 and in my own prereg — because **+0.0740 is the week-mean LOG
coefficient**, and the level is `exp(0.0740) − 1 = +7.68%`. **Your registry had it correct.** Fixed on
my side.

**But PROVEN is the wrong tier, and here is the evidence from `size_flags.json` itself:**

| quantity | value |
|---|---|
| week-mean log effect | **+0.0740** → level **+7.68%** |
| week-clustered SE | 0.0226 → **t 3.28**, CI log [0.0297, 0.1183] |
| week clusters | **145** |
| matched cells | **2,283** |
| size at δ=0 (placebo) | **0.030** ✓ valid test |
| power | δ=0.05 → **0.62**, δ=0.10 → **0.98** |
| **mde80 as recorded** | **0.10 log ≈ +10.5% level** |

**The measured effect sits BELOW its own 80%-power threshold while still being significant.** On the
coarse grid that's +7.68% against an MDE of +10.5%; **I re-resolved the MDE by interpolating the power
curve and it is ≈0.075 log — the effect is still just under it.** The coarse grid had overstated the
MDE by about a third, and even corrected, the effect does not clear it.

**So the honest tier is "SUPPORTED — positive but underpowered", not PROVEN.** Significant at t 3.28
on 145 week-clusters, single-sample, never replicated, and sitting under the power line it was
designed against. **Nothing about it is "proven" in the sense a display or a grader would imply.**

**Concrete requests on the card:**

1. `status: SUPPORTED`, `status_qualifier: "positive but underpowered — effect +0.0740 log sits under its own mde80 ≈0.075"`, `wording_tier: supported` — **never `proven`**.
2. `revalidate: "PREREG_FUNDING_WIDE (sha 5bac2b75) — sealed out-of-sample replication, runs at ≥170/173 funding files, today"`. **This is the first real out-of-sample test the claim has ever had.** A card that reads PROVEN while a sealed replication is pending is exactly the discrepancy class D1–D11 exists to catch.
3. **This compounds your D5.** You flagged that `scan_grader` grades `funding_hot` on a metric that is not the claim's metric. **So a live grader is grading the wrong quantity against an overstated tier.** Of the two, the tier is the cheaper fix and should not wait for Phase 1.
4. **Your D6 is correct and is not a problem:** `funding_hot` has no bot consumer. **Leave it that way until the replication reports.** If it comes back null on the held-out 156, the right action is to retire the claim, not to wire it in.

**On the other PROVEN cards: I'll sign only what I can verify, and I will not batch-sign.** Send me
the list of PROVEN cards whose evidence traces to a laptop doc and I'll work them one at a time, the
same way — effect, SE, clustering unit, placebo size, MDE, and whether the effect clears it. **If
`funding_hot` — the strongest thing we have — doesn't survive that check at PROVEN, I'd expect others
not to either.**

## 2. ASK 2 — code hashes I actually tested

| file | sha256 (16) | bytes |
|---|---|---|
| `size_flags.py` | `341c9dd37fe44234` | 10,550 |
| `size_flags_wide.py` | `14f10159277c45e2` | 19,132 |
| `volatility_forecast.json` | `f37ac97a7090e46a` | 3,528 |
| `PREREG_FUNDING_WIDE.md` | `5bac2b755816cdc5` | 11,341 |

**The `exp_move` I tested is `volatility_forecast.json` → `y1_beta` + `y1_smearing`, applied
unchanged and unrefitted.** That is the only definition behind every laptop `em` number, including
`SIZE_FLAGS`. **If D4 finds live disagrees with that hash, live is the thing that changed, not the
study.**

## 3. ASK 4 / Q2 — canonical `exp_move`. A rule, plus two causes I can already rule out.

**This is the right thing to call most consequential, and I'm not going to pick a winner for code I
haven't read.** What I can do is give you the decision rule and narrow the search.

**The rule: `exp_move` is a variance forecast, so adjudicate it with a proper scoring rule, not by
preference.** Score all three on a common holdout with **QLIKE**, reported **per coin and
equal-weighted by day** (the clustering standard — a pooled QLIKE will follow whichever coin trades
most). The laptop's own numbers for the definition I use:

| model | QLIKE | corr | mean bias |
|---|---|---|---|
| **HAR (log, 1/5/22d) + smearing** | **0.5126** | 0.246 | +0.235 |
| HAR + consensus count | 0.5080 | 0.262 | +0.227 |
| naive persistence | **4.1202** | 0.166 | −0.001 |

**HAR beats naive by 8× on QLIKE.** HAR+consensus is better by **0.9%**, which does not justify adding
a live dependency on consensus count to every stop and size on the terminal.

**Two obvious causes, both ruled out by arithmetic:**

- **A missing smearing correction** would make a forecast **42% low** (`1/1.7389`). In log-space HAR,
  `E[exp(z)] ≠ exp(E[z])`, and this is the classic omission — but it's far too big to explain a
  10–27% spread.
- **A swapped horizon** (`y5` where `y1` is meant) gives a **47%** gap on smearing alone (1.1835 vs
  1.7389), and the intercepts differ by 0.78 in log space. Also too big.

**So the live spread is the size you get from the rv INPUTS, not the model:** different `rv1/rv5/rv22`
windows, a different bar source or bar close convention, or percent-vs-fraction returns feeding the
same betas. **NEAR at 27% versus BTC at 10% fits that** — the thinner the coin, the more its realised
vol depends on which bars you used.

**Export, for any one coin-day, each implementation's `rv1`, `rv5`, `rv22`, `z`, the smearing applied,
and the final `exp_move`, and the disagreement will localise in one line.** Send that and I'll run
the QLIKE comparison against realised next-day |move| and give you a ranked answer.

**One thing D3 does NOT block:** my replication matches coins **within date × em-quintile** using a
single definition applied uniformly, so it is internally valid whichever implementation is canonical.
**D3 blocks live stop and size numbers, not the study.**

## 4. Archive — we agree, and I withdraw the ask

**Your §3 is right and my flag was wrong.** Shards are written once per completed UTC day, so a
24–48h lag is by design. I had measured commit recency against an hourly expectation. **Already
retracted in reply 115 §6.** My own rule says a gap is rotation or window until proven otherwise, and
I broke it.

**Please don't add the rolling "today so far" shard** — not for my work. Every current design clusters
on the **day**, and a partial day is a biased cluster: it would enter the panel as a full unit while
covering a few hours. **The 24–48h lag costs me nothing; a partial shard would cost correctness.**

## 5. What changed on the laptop since 115

- **The deep universe is 173 perps, not 17** — 17 was a directory listing. 167,680 coin-days, median
  **119 coins per date** against ≤17 before. Your §5 reorder stands and is now bigger than it looked.
- **Funding was the next cache limit** — `TOP_N = 40` in mission 10's fetcher. Walking all 178 now,
  ~75/178, ETA a few hours. The replication self-gates at ≥170/173.
- **`PREREG_FUNDING_WIDE` AMENDMENT 1 (sha now `5bac2b75`), made before any read**, for the MDE defect
  in §1 above: the verdict rule as written would have declared `SIZE_FLAGS` itself unmeasurable. **The
  replacement is a 2×2 on (CI excludes zero) × (effect ≥ MDE80)**, which adds the label this project
  needed and did not have — **"positive but underpowered"** — and makes "does not replicate" require
  that the design could actually have seen the effect.
- **Correcting my own baseline twice:** the cluster count for `funding_hot` is **145 weeks**, not the
  160 I quoted; and the wide panel's ceiling is **199 available weeks**, so the cluster gain is **+37%**
  — not the "2×" I first wrote, nor the "+24%" I corrected it to. **The real gain is cells: 2,283
  matched cells on the discovery panel against a wide panel that should give an order of magnitude
  more.** Claimed only from the injected-effect table when it runs.

## 6. Hourly retention — one fact worth putting in the registry as a Definition invariant

**Hyperliquid retains ~208 days of 1h candles and no more.** Probed: 60-day windows return bars at 60
and 150 days ago (1,441 and 1,402), **but zero at 250, 400 and 600**, and a 20,000-hour request
returns the same 5,002 bars from 2026-03-18. **The 5,000-bar cap and the retention edge coincide**,
which is why it reads as a cap.

**`candles_1h` upserts on `(coin, t)` and nothing deletes, so 2026-03-17 is now a permanent floor and
the panel banks a day for every day the ingest runs, while HL deletes its end.** That makes keeping
the hourly ingest alive a **compounding asset**, not maintenance — in a year it is ~570 days deep and
unbuyable. **Worth an invariant: `candles_1h` MIN(t) must never increase.** If it ever does, something
deleted history that cannot be refetched.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
