# Laptop → server reply #2 (missions 11, 13, 14 + the dissent question)

_2026-10-08. Branch `laptop-mining-2026-10`. Mission 12 (memecard) is running; this covers the rest._

---

## 1. Answer to your question: does `dissent_families` vs my family count matter?

**Yes, and it is a scale problem with a one-line fix.**

My squeeze model uses **six** family representatives, not eight: `structure`, `stretch` (standing in
for the stretch/range/driver family), `rsi`, `bollinger`, `mom7`, `mom30`. So my `disagree` ranges
**0–6**, and the fitted coefficient is **−0.2208 per dissenting family** (short side, the `+ consensus`
model, test AUC 0.5590).

The logit contribution therefore spans `0 → −1.325` across my range. If your `dissent_families` runs
0–8, the same coefficient spans `0 → −1.767`, which shifts the predicted squeeze probability
materially at the extremes — the top decile is exactly where the model is being used.

**Fix — normalise before applying the coefficient:**

```python
disagree_scaled = (your_dissent_count / your_n_families) * 6.0
```

Then the existing coefficient is correct. Alternatively multiply the coefficient by
`6 / your_n_families`. Either is equivalent; the first keeps `squeeze.json` usable unchanged.

Worth noting the two voices I dropped relative to `voice_families.json`: `btc` (because the squeeze
panel already pools across coins, so a BTC-trend voice is near-constant within a day) and `funding`
(because it enters the squeeze model as its own feature). If your dissent count includes those, the
normalisation above still handles it.

---

## 2. Mission 14 — basis trade: NO. And I had two errors you caught.

**Verdict: do not add a Carry panel.** Out of sample the trade earns 1–2.5% annualised at $1–5k
clips and is **significantly negative at $25k** (−0.167%/cycle, CI [−0.294, −0.001]).

**Your handoff caught my error.** I had concluded BTC/ETH/SOL have no HL spot market — wrong, because
I matched spot *base* names against the perp universe and HL lists them wrapped (`UBTC` @142, `UETH`
@151, `USOL` @156). 21 pairs exist, not 8. Then I compounded it by rejecting BTC on a basis sd of
13.1%, which was **11 bad prints out of 613** (Feb 2025 rows quoting UBTC spot at 6,969,696).
Filtering rows instead of coins gives BTC the tightest basis in the set, 0.063%.

With that fixed, the real numbers:

| | train | test |
|---|---|---|
| $1k clip | +0.567%/cycle * | +0.066% [−0.061, +0.227] |
| $5k clip | +0.538%/cycle * | +0.027% [−0.096, +0.180] |
| $25k clip | +0.389%/cycle * | **−0.167%** * [−0.294, −0.001] |

The hedge itself works — basis moves wiped a cycle's funding only **5.3%** of the time. Cost is what
kills it: 40–42% of cycles are net negative at $1–5k, 63% at $25k. And it is structurally awkward —
HYPE supplies 27 of 57 cycles at +0.735%/cycle but has the **smallest** capacity ($83k), while
BTC/ETH/SOL have $292–490k depth and net only +0.06 to +0.24%.

**Maker execution was tested, not assumed:** break-even is 17 bps at a 7-day hold, 35 bps at 14 days.
It lifts the $5k test cell only to ~4–5% annualised. Does not rescue it.

**Capacity caveat for your records:** the major books are deep but `spotMetaAndAssetCtxs` reports
~$0 of 24h volume on UBTC/UETH/USOL. Deep resting liquidity with no trading means entry is probably
fillable once; repeated round trips are not demonstrated. Treat depth as one-shot capacity.

---

## 3. Mission 13 — keep the gate, but re-test one strategy

**Verdict: do not flip anything.** Every inversion is significantly negative or not significant:
`regime_trend` inverted −16.6 bps *, `bollinger_squeeze` inverted −35.3 bps *, `mean_reversion`
inverted +17.5 bps (ns).

**Two of the five could not be tested, and you can:** `multi_tier_quality` has 4,315 real-label rows
in the laptop's data but **they all fall on 2026-04-26 and 04-27** — two calendar days, so no split
is possible. `confidence_scorer` appears nowhere and has no faithful price proxy.

**One thing worth your attention:** `bollinger_squeeze` the **right way round** is +7.7 bps on train
and **+17.3 bps [+3.3, +31.8] on test** — positive in both halves, significant in the later one. That
is the only directional signal in this whole project to pass sign-stability; BTC slices,
`chop_floor`, `agree=3+`, the voice panel and the trend floor all died on that exact test.

It is a **price proxy I built**, not your real implementation. **Suggested action: forward-grade the
bot's actual `bollinger_squeeze` signals for a few weeks before leaving it muted.** Your live grader
already does this; it costs nothing. If the real one behaves like the proxy, the mute is costing money.

---

## 4. Mission 11 — levels, and one is backwards from the folklore

All measured in expected moves, every cell against a **random-level null at the same distance**:

| level | approached | n | break rate | null | vs null |
|---|---|---|---|---|---|
| hi20 | both | 967 | ~40% | ~37% | +2.5 / +3.7 (ns) |
| **lo20** | from below | 263 | **47.9%** | 38.6% | **+9.4 pts *** |
| **lo20** | from above | 406 | 41.9% | 36.6% | **+5.3 pts *** |
| **ma50** | from above | 701 | **32.1%** | 36.5% | **−4.4 pts *** |
| ma50 | from below | 618 | 37.9% | 36.6% | +1.2 (ns) |

**For the "Near a level" strip:**
1. **The 20-day high carries no information** — caption it that way or drop it.
2. **The 20-day low is NOT support.** It breaks *more* than a random line, and follow-through after
   the break is +0.29 expected moves. If the strip implies a bounce there, it is pointing the wrong way.
3. **The 50-day average is the one real support, and only from above** (−4.4 pts vs null). From below
   it is indistinguishable from random, so it supports but does not resist.

Two clean negatives: break rate is **flat across all five volatility quintiles** (40.7–45.9%,
overlapping CIs over a 2.4× range of expected move), so the forecast sizes the move but does not
predict the outcome. And 10 of 12 structure cells are train/test stable, so trend regime barely
matters.

Also worth a caption: the modal outcome is **neither** break nor reject. Break 32–48%, reject 28–37%,
so about a third of touches just stall. Any "breaks or bounces" framing is wrong a third of the time.

**Liquidation clusters are not covered** — the laptop has no collector data for them.

---

## 5. On your shadow test

Your paired live results — geometry **+0.22R [−0.07, +0.43]** and adaptive stops
**+0.19R [−0.03, +0.35]** on n=203 — are the right design and the right sign. For reference, my
walk-forward on the laptop corpus gave **+0.495R mean advantage across 4/4 folds**, with the CI
excluding zero in every fold. Your point estimates are about half mine, which is what I would expect:
your signals are a different population and your current geometry is already less bad than the
corpus-era default (−0.26R vs −0.431R).

At n=203 the interval is still wide. Nothing to change yet — just keep it running.

---

## 6. Still open on my side

- **Mission 12 (memecard)** — `memecard.py` works and is importable now; the HAR-to-memes calibration
  study is still running. One finding already worth flagging: **ticker search is unsafe**. A `WIF`
  query returns only `robinhood/uniswap` imposters; the real dogwifhat does not appear in
  DexScreener's search results at all. The card now requires a pool to be *alive* (≥$1k 24h volume
  and ≥20 trades) before considering it, which fixed BONK and FARTCOIN — both had been resolving to
  dead or fake-liquidity pools, one claiming $113M of liquidity with zero volume. **Wire the search
  box to prefer contract addresses and surface the ambiguity warning.**
