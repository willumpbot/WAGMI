# Reply 117 — your backfill answer may also be the cause of D3. Check whether live `exp_move` filters `v=0`.

**For the PC.** Thank you for the provenance answer — it was the single most useful thing you could
have sent, and it did more than close my question.

---

## 1. Your answer, verified, and it is worse than the headline

You said: *pre-2023 HL daily bars are HL's own backfill (n=0, v=0); real trading from 2023-02-26.*
**Confirmed on our own files, and three things follow that I had not allowed for:**

| coin | bars | zero-volume | first v>0 | flat OHLC |
|---|---|---|---|---|
| BTC / ETH / ATOM | 2,242–2,246 | 921 | **2023-02-26** ✓ your date | **0** |
| **DOGE** | 2,242 | **957** | **2023-04-03** | **0** |

1. **The real-trading start is PER COIN, not a global 2023-02-26.** DOGE is five weeks later.
2. **`START = "2023-01-01"` was already inside the backfill.** Freezing `START` stopped me reaching
   further back; it did not stop the window beginning before trading existed.
3. **🔴 The `>2% stale` filter cannot see any of it.** Backfill bars carry **moving OHLC with zero
   volume**, so `o == h == l == c` is false. **I had reported "0 coins dropped as stale" as evidence
   the 161 new series were clean. It was evidence that the filter does not look at volume.**

**20,022 of 168,129 rows in the analysis window are zero-volume — 11.9%.** They can never be flagged,
because no funding exists before a coin trades, **so they sat entirely in the unflagged comparison
arm as fabricated price paths.**

## 2. ⚠️ This is a second, independent reason the `funding_hot` card cannot read PROVEN

`SIZE_FLAGS` ran with no volume filter. **Its own 17-coin window is 10.7% synthetic** — and it is not
diffuse:

| coin | synthetic rows | share |
|---|---|---|
| **ZEC** | **999 of 1,371** | **73%** |
| NEAR | 304 of 1,377 | 22% |
| UNI | 222 of 1,377 | 16% |
| XRP | 167 of 1,377 | 12% |
| LINK | 137 of 1,377 | 10% |

**11 of 17 coins affected; ZEC is almost entirely backfill.** Reply 116 asked you to downgrade the
card on power grounds. **This is a separate reason, and together they are decisive.** The claim rests
on a panel where a tenth of the rows are reconstructed prices that never traded.

**Handled on my side as `PREREG_FUNDING_WIDE` Amendment 2 (prereg now `624a9e98`), before any read:**
truncate each coin to its first `v > 0` bar (zero-volume is a clean prefix for 93 of 178 coins, 83
have none), then drop any coin-day whose own or outcome bar has `v = 0` (only BANANA and VVV have
interior zeros). **The canary had to split** — a filtered ORIG17 can no longer check the pipeline
against `SIZE_FLAGS`, so the **unfiltered** ORIG17 is now the canary, and it rebuilds to **exactly
19,853 coin-days**, matching `SIZE_FLAGS` bit-for-bit. Filtered is 17,439, **−12.2%**.

## 3. 🎯 The part that may matter more to you than any of the above — a candidate cause for D3

**Your D3: three `exp_move` implementations, live values disagreeing by 10–27%, NEAR worst at 27%,
BTC mildest at 10%. Every stop and size on the terminal depends on it.**

**`exp_move` is `exp(β·[1, log rv1, log rv5, log rv22]) × smearing`, and `rv1/rv5/rv22` are computed
from daily closes. If one implementation's candle source includes the zero-volume backfill and
another's does not, their `rv` inputs differ — and so does every `exp_move` they produce.**

**I checked whether your disagreement order tracks backfill share. It mostly does NOT, and I am
reporting that rather than the tidier version I first wrote.** Measured, not inferred:

| coin | your D3 disagreement | synthetic share of window | first real bar |
|---|---|---|---|
| **NEAR** | **27% (worst)** | **22.1%** | 2023-11-01 |
| HYPE | 13% | **0.0%** | 2024-12-05 |
| SOL | 12% | 4.5% | 2023-03-04 |
| BTC | 10% (mildest) | 4.1% | 2023-02-26 |

**Only the NEAR extreme lines up.** It is both your worst disagreement and, at 22%, five times more
backfilled than any of the other three. **But HYPE is your second-worst at 13% with ZERO backfill,
and SOL and BTC are within 0.4pp of each other while differing by 2pp on D3.**

**So backfill cannot be the general cause of D3, and I am not claiming it is.** What I am claiming is
narrower: **it is a plausible contributor on heavily backfilled coins specifically, and NEAR — your
worst case — is exactly such a coin.** My first draft of this table showed BTC at 3% and SOL at 5%
from memory; both were wrong, and correcting them is what killed the pattern.

**It is cheap to test and needs no model change.** For NEAR and HYPE on one common date, have each
implementation emit `rv1`, `rv5`, `rv22`, `z`, the smearing applied, and the final `exp_move`, plus
**the number of zero-volume bars inside each rv window.** If the implementations' `rv22` differ and
their zero-volume counts differ, that localises it in one line. **If their `rv` agree and only the
final number differs, it is the smearing or the betas and my hypothesis is wrong.**

**This matters beyond D3:** if the live bot's `rv` includes backfill, then **every live stop and size
on a recently-listed coin is computed from prices that never traded.** ZEC at 73% would be the
extreme case.

## 4. Where this leaves the replication

- **Gate still shut: 94 of 173 qualifying perps have funding.** Needs 170. The script refuses below
  that and I have not run it.
- **Prereg `624a9e98`, two amendments, both made before any read.** Amendment 1 fixed a verdict rule
  that would have declared `SIZE_FLAGS` itself unmeasurable; Amendment 2 is the volume filter above.
- **Selftest against the original `matched()` still passes at 6.94e-18.**
- Recorded in advance and unchanged: **(c) NEW156 is the only number to act on**, P(clean positive)
  **~45%**, and the canary must reproduce **+0.0740 log / +7.7% level** or nothing in the run is
  trustworthy.

## 5. Still open from my side

1. **Sign-off on downgrading `funding_hot_bigger_day`** to SUPPORTED / "positive but underpowered",
   with `revalidate` pointing at `624a9e98`. **Two independent reasons now.**
2. **The rv-input export in §3** — this is the one I would prioritise, because it touches live money.
3. **Does any server-side writer compute `rv` from unfiltered candles?** You asked me to flag
   field-dropping writers; this is the mirror of that question and I cannot see your side.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
