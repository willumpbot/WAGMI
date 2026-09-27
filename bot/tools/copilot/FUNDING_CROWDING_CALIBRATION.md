# Funding / OI "Crowding" Signal — Honest Calibration

**Question (not a directional-edge hunt):** does a funding-rate / open-interest
"crowding" state have predictive worth for FORWARD adverse price moves
(mean-reversion against the crowd)? Goal: make the co-pilot's framing of this
RISK signal match measured truth.

**Verdict: NOISE.** Do not surface funding/OI crowding as a reversion-risk signal.
The primary test is a clean OOS null; a post-hoc OI overlay grazed the p=0.05 floor
gross but failed net-of-fees and had a sub-50% hit rate. Not even a HINT.

---

## STEP 0 — Data-usability gate: **PASSED**

The collector `tools/funding_oi_collector.py` (Hyperliquid via ccxt, 15-min cadence)
writes **usable numeric time series** to:

- `data/funding_oi_history.jsonl` — 20,138 rows, 2026-06-06 → 2026-08-06.

Each row has numeric, timestamped, per-symbol fields:
`timestamp, symbol, funding_rate, open_interest, premium, volume_24h, price, oi_volume_ratio`.
Example: `{"timestamp":"2026-06-06T13:20:49","symbol":"BTC","funding_rate":-2.69e-06,"open_interest":2056252946.0,"premium":-0.0007,"price":60952.5,...}`

**Note on the memory warning** ("funding/OI collected but not numerically logged"):
that warning is **stale / refuted for this file**. `funding_rate`, `open_interest`
and `price` are all present and numeric (100% non-zero funding across every symbol).
Price is captured in the same file, so forward outcomes need no external OHLC fetch.

**Usable universe (>=37d of history at ~16-min median cadence):**

| symbol | rows | span | cadence |
|---|---|---|---|
| BTC, ETH, SOL, HYPE | ~3400 ea | 60.7 d | 16 min |
| XRP | 3267 | 37.5 d | 16 min |

Excluded (too short for forward-window + dedup + OOS split): memes POPCAT/WIF/
FARTCOIN/PENGU/kPEPE/kBONK/kSHIB (~5 d each) and rotating movers (≤0.4 d).

---

## STEP 1 — Calibration (pre-registered, full moat)

**Signal ("crowding"):** funding rate beyond a per-symbol quantile threshold.
`crowded-long = funding >= Q80`, `crowded-short = funding <= Q20`.
Thresholds computed on **TRAIN only**, applied to strictly-later **TEST**.

**Outcome:** forward return over N hours from the same collector's price series.
`fade_return = -sign(crowd) * forward_ret` — fade the crowd (short a crowded long,
long a crowded short). Positive ⇒ the crowd got hurt ⇒ signal has worth.

**Guards:**
- Entry-time-safe: threshold from past (train); outcome strictly forward t→t+N.
- Independence/dedup: after a trigger at t, suppress triggers until t+N ⇒
  **non-overlapping** forward windows (funding is highly autocorrelated).
- OOS: chronological 60/40 split @ 2026-07-21; TEST reported.
- Net-of-fees: HL ~9 bps round-trip subtracted for any P&L reading.
- Refutation: random-timestamp negative control (same episode count, real realized
  funding sign) + per-symbol + per-era (month) breakdown.
- Horizons: 8 h and 24 h.

### Primary result (TEST, OOS)

**8 h horizon (n = 228 independent episodes):**
- crowding fade: **+0.049% gross** (win 49.6%, t=+0.58, **p=0.561**), **−0.041% NET of fees**.
- **negative control (random): +0.040%** — statistically indistinguishable from the signal.
- No symbol significant (HYPE +0.37% p=0.20, XRP −0.19% p=0.27 — opposite signs, both noise).
- Both months null (Jul +0.040%, Aug +0.070%).

**24 h horizon (n = 75):**
- crowding fade: **+0.115% gross** (win 52.0%, t=+0.44, **p=0.660**), +0.025% net.
- **negative control: +0.284%** — the random baseline *outperforms* the signal. Decisive.
- Era-fragile: month flips sign (Jul +0.332% vs Aug −0.480%).

The signal ≈ random baseline; net-of-fees is ~zero-to-negative; nothing survives
significance. **Null.**

### Secondary (honors pre-registered "AND/OR OI"): crowding INTO rising OI

`funding extreme AND OI up >1% over trailing 4 h` (entry-time-safe OI momentum):
- 8 h (n=128): +0.112% gross **p=0.333**, +0.022% net — null.
- 24 h (n=58): +0.497% gross **p=0.050**, but **+0.407% net p=0.108 (fails)**,
  **win% 48.3% (< 50%)** — positive mean is a few tail moves, not a consistent tilt.

This lone gross p=0.050 is **not** an edge/hint: it (1) fails once fees are applied,
(2) has a sub-50% hit rate, (3) is n≈58, (4) is a **post-hoc overlay** added after
the primary null, across many looks (2 horizons × primary/control/side/symbol/era +
OI). Under any multiple-comparison honesty it is exactly the false positive you expect.

---

## Verdict

**NOISE — do not surface funding/OI crowding as a mean-reversion / adverse-move
risk signal.** Fading crowded funding on HL majors over 8–24 h earns ~0% gross,
loses net-of-fees at 8 h, and cannot be told apart from a random-timestamp baseline.

Root cause is honest and structural: HL major-perp funding sits near zero the vast
majority of the time, so "top-quantile funding" is a mild, non-extreme state with no
reliable reversion payload at these horizons in this 2-month, two-regime window.

**Co-pilot framing:** if crowding is mentioned at all, mark it explicitly as
*context, not a tradeable/risk signal* — measured predictive worth ≈ 0.

**What could change the answer (future, not now):** the meme/thin-book symbols —
where funding actually spikes to genuine extremes — have only ~5 d of history.
Re-run this exact test once they accumulate ≥30 d; extreme-funding names are the
only place a real crowding signal could plausibly live. The collector already logs
them numerically, so this is just a matter of forward time.

---

## Reproduce

```bash
cd C:/Users/vince/WAGMI/bot
C:/Users/vince/AppData/Local/Programs/Python/Python313/python.exe \
  tools/copilot/funding_crowding_calibration.py
```

- Code: `tools/copilot/funding_crowding_calibration.py` (read-only on
  `data/funding_oi_history.jsonl`; writes nothing to live state).
- Seed fixed (1729) so the negative control / bootstrap are deterministic.
- Pre-registered constants at top of file: `UNIVERSE, HORIZONS_H, Q_HI/Q_LO,
  TRAIN_FRAC, FEE_ROUNDTRIP`.
