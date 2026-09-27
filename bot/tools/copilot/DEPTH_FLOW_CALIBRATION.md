# Depth / Order-Flow Signal Calibration — RESULTS

**Question.** Does an order-book / taker-flow signal (L2 depth imbalance,
taker buy/sell ratio, long/short account ratio) carry any *forward* predictive
worth for price? This calibrates whether this co-pilot signal is a real hint or
noise, so the co-pilot's framing matches measured truth. It is **not** a hunt for
a directional entry edge. A clean null is the expected, acceptable outcome.

**Verdict (headline): NOISE.** No order-book/taker-flow signal shows forward
predictive worth that survives out-of-sample, and none clears the fee hurdle.

---

## Step 0 — Data-usability gate: **PASSED**

File inspected: `data/market_depth_history.jsonl` (20,782 lines, 18.7 MB, 0 bad JSON).
Sibling `data/funding_oi_history.jsonl` exists but was not needed (funding/OI context is
embedded in the depth records' `futures_ctx`).

Each record: `{ts, symbol, l2{mid, imbalance_0_1pct, imbalance_0_5pct, imbalance_1pct,
spread_bps, bid/ask_depth_*}, trades{buy_ratio, buy_vol, sell_vol}, futures_ctx{taker_buy_sell_ratio,
long_short_account_ratio, funding_rate, basis_bps, mark/index_price}}`.

**Per-symbol coverage** (cadence: clean **15-min**; 1 gap >60min, max 255min):

| symbol | rows | span | uniq days | usable |
|---|---|---|---|---|
| BTC | 3376 | 35.3d | 37 | ✅ |
| ETH | 3376 | 35.3d | 37 | ✅ |
| HYPE | 3376 | 35.3d | 37 | ✅ |
| SOL | 3376 | 35.3d | 37 | ✅ |
| XRP | 3376 | 35.3d | 37 | ✅ |
| FARTCOIN/PENGU/POPCAT/WIF/kBONK/kPEPE/kSHIB | ~501 | 5.2d | 6 | ✗ too short |
| AAVE/BNB/DOGE/KAITO/LIT/NEAR/ONDO/PUMP/UNI/XMR/ZEC | ≤40 | ≤0.4d | 1 | ✗ single day |

Collection started 2026-07-01. Five majors (BTC, ETH, HYPE, SOL, XRP) each have
~35 days at 15-min cadence with **99.8–100% numeric availability on every signal
field** — comfortably enough for a forward-window + dedup + chronological OOS split.
The remaining 18 symbols are recent single-day/6-day additions, unusable. Gate passes
on the five majors.

---

## Step 1 — Calibration (pre-registered, full moat)

**Pre-registration (committed before any forward return was computed):**
- Primary signal: `l2.imbalance_0_1pct` (near-touch book imbalance). Predicted **mild
  REVERSION over 1h, likely NOISE net of fees** — real book-continuation edge lives at
  tick scale; a 15-min snapshot of extreme touch imbalance is stale/absorbed/spoof-prone.
- Secondary (exploratory, Bonferroni-aware): `taker_buy_sell_ratio` → weak continuation;
  `long_short_account_ratio` → contrarian.
- Statistic: signed continuation return = `sign(signal − neutral) · forward_return`
  (neutral = 0 for imbalance, 1.0 for ratios). Positive ⇒ "follow" works; negative ⇒ "fade".
- Horizons: 1h (primary) and 4h. Extreme = per-symbol top/bottom 15% by |signal − neutral|,
  thresholds from TRAIN ONLY, applied to TEST.
- **Entry-time-safe**: signal at t uses only data ≤ t; outcome = mid at t+horizon, matched
  to the nearest snapshot within ±15min. Mid lives in the *same* record — no ledger join,
  so no close-time look-ahead (the bug that bit prior work is structurally impossible here).
- **Dedup**: per-symbol cooldown = horizon; counted forward windows never overlap.
- **OOS**: chronological per-symbol split, train = first 60% of time, test = last 40%.
- **Fees**: HL taker round-trip 9 bps applied to net framing.
- **Negative control**: up to 300 random non-overlapping timestamps/symbol, random assigned
  direction, unconditioned on the signal → expect ~0.

### Results (TEST = decisive; effect in bps of signed forward return)

| signal | horizon | n (test) | gross | **net (−9bps)** | t | hitrate | train t | control t |
|---|---|---|---|---|---|---|---|---|
| imbalance_0_1pct (primary) | 1h | 881 | +0.85 | **−8.15** | +0.55 | 49.1% | +0.84 | −0.15 |
| imbalance_0_1pct | 4h | 337 | −0.88 | **−9.88** | −0.20 | 47.8% | +0.28 | +1.07 |
| taker_buy_sell_ratio | 1h | 1085 | +0.14 | **−8.86** | +0.11 | 48.6% | −1.56 | +0.13 |
| taker_buy_sell_ratio | 4h | 369 | +5.50 | **−3.50** | +1.23 | 50.1% | −0.51 | −0.64 |
| long_short_account_ratio | 1h | 985 | +0.66 | **−8.34** | +0.51 | 50.1% | +2.63 | −1.11 |
| long_short_account_ratio | 4h | 264 | +1.40 | **−7.60** | +0.28 | 48.5% | +2.74 | −1.20 |

### Reading the table
- **No signal clears significance OOS.** Every pooled TEST |t| < 1.3 — statistically
  indistinguishable from the random-timestamp control (which sits at |t| < 1.2, gross
  within a few bps of zero, confirming the forward-return machinery is unbiased).
- **Net-of-fees is negative for all six cells.** Even the largest gross OOS effect
  (+5.5 bps, taker 4h) is less than the 9-bps round-trip fee.
- **The one thing that looked real died OOS — textbook refutation.**
  `long_short_account_ratio` printed train t = +2.63 (1h) and +2.74 (4h, gross +16.7 bps),
  which in-sample looks like a contrarian... no, *continuation* tilt. Out-of-sample it
  collapses to t = +0.51 and +0.28. Classic in-sample-only artifact.
- **Sign instability = noise.** `taker_buy_sell_ratio` flips from train t = −1.56 to
  test t = +0.11 at 1h. No stable direction.
- **No symbol/era robustness.** Per-symbol TEST results scatter both signs with |t| < 1.6
  each; the lone per-symbol pop (HYPE taker 1h, t = +2.41) has opposite-signed BTC/ETH
  siblings at the same horizon and a *negative* pooled train — a multiple-comparisons
  artifact across 5 symbols × 2 horizons × 3 signals, not an edge.

### Refute-yourself checks
- **Negative control** (random timestamps, stable n≈1300 at 1h): centered at zero, |t|<1.2 —
  the forward-return pipeline itself carries no bias; the null is a true null, not a broken test.
- **Not a single-symbol artifact**: signals fail across all five majors; no symbol holds.
- **Not a single-era artifact**: train (first 60%) and test (last 40%) disagree in sign/magnitude
  wherever train hinted at anything — the opposite of a persistent edge.

---

## Verdict

**NOISE.** Order-book depth imbalance, taker buy/sell ratio, and long/short account ratio
have **no forward predictive worth** at 1h or 4h that survives out-of-sample and
significance testing, and none clears the 9-bps fee hurdle. The primary hypothesis
(near-touch imbalance → 1h reversion) came back a clean null as pre-registered. This is a
successful measurement result: the co-pilot must **not** frame these order-flow readings as
directional hints — at best they are context/descriptive, not predictive.

**Co-pilot framing correction:** present depth/flow as *current-state context* ("book is
bid-heavy right now", "takers are lifting offers") — never as a forward edge or entry tilt.

---

## Reproduce

```bash
cd C:/Users/vince/WAGMI/bot
python tools/copilot/depth_flow_calibration.py --seed 12345
```

Deterministic (fixed seed governs only the negative control's random draws; the signal
statistics are fully deterministic). Code: `tools/copilot/depth_flow_calibration.py`.
Read-only on `data/market_depth_history.jsonl`; writes nothing outside `tools/copilot/`.
