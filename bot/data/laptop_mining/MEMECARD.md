# Mission 12 — risk card for the coins people send the owner

_2026-10-08. `memecard.py` (importable), plus a calibration study on 23 DEX pools / 3,586 predictions.
Data: `meme_calibration.json`. Sources: DexScreener (pairs), GeckoTerminal (OHLCV). Free endpoints only._

---

## Headline

**The card is built and importable. The important finding is not the volatility maths — it is that
looking a token up by its ticker is actively dangerous, and the first version of this card fell for
exactly the traps it exists to catch.**

The volatility model transferred better than expected: the HAR forecast fitted on Hyperliquid majors
is already roughly calibrated on DEX memes (ratio 0.92×), so **no correction factor is shipped.**

---

## 1. What the card returns

```python
from bot.data.laptop_mining.memecard import card
card("EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm")   # contract address — definitive
card("BONK")                                            # ticker — ambiguous, warns
```

liquidity · 24h volume · volume/liquidity · pair age · price change · txn counts · market cap / FDV ·
daily / 7d / 30d realised volatility · drawdown from ATH · **slippage for $100 / $500 / $2,000** ·
**position cap for 2% slippage** · expected 1-day move · suggested stop · risk flags · other matching pairs.

### Slippage and the size cap
For a constant-product pool with total USD liquidity `L`, each side holds ~`L/2`, so a trade of size
`S` moves price by roughly `2S/L`:

```
slippage ≈ 2S / L          cap for 2% slippage:  S_max = L / 100
```

**So the position cap is simply liquidity ÷ 100.** $80k pool → $800 max. $6M pool → $60k max. This is
a v2-style approximation; concentrated-liquidity pools (Uniswap v3, Orca) are better inside their
active range and worse outside it, so treat it as an order of magnitude, not a quote.

### Live examples
| token | resolved | liquidity | 24h vol | age | daily vol | from ATH | **max size (2% slip)** |
|---|---|---|---|---|---|---|---|
| $WIF *(by address)* | solana/raydium | $6.03M | $540k | 1053d | 4.61% | −17.7% | **$60,274** |
| PEPE | ethereum/uniswap | $28.7M | $1.33M | 1273d | 4.43% | −23.3% | **$286,562** |
| Fartcoin | solana/raydium | $7.88M | $1.31M | 721d | 5.78% | −42.7% | **$78,773** |
| Bonk | solana/orca | $377k | $461k | 1383d | 4.69% | −57.5% | **$3,768** |

---

## 2. The finding that matters: ticker lookup is unsafe

The first version ranked candidate pairs by **liquidity alone**. Testing it on four well-known tokens,
it got three of them wrong — and each failure was a different trap:

| query | what it resolved to | why that is wrong |
|---|---|---|
| **WIF** | `robinhood/uniswap`, $80k liquidity, 63 days old | an **imposter**. Real dogwifhat has $6M on Solana and is 1,053 days old. |
| **BONK** | $1.7M liquidity, **$185** of 24h volume, 0.25% daily vol | a **dead pool**. Deep on paper, untradeable, and the stale price made it look calm. |
| **FARTCOIN** | **$113M liquidity with $0 volume**, 0% drawdown, 15d history | **fake liquidity**. The single most dangerous possible output. |

A risk card that tells you a scam pool is deep and calm is worse than no card. The fix:

1. **A pool must be alive** — ≥ $1,000 of 24h volume **and** ≥ 20 transactions, or it is not
   considered at all, however deep it claims to be.
2. **Score on liquidity *and* turnover**, geometrically, so neither deep-but-dead nor busy-but-thin
   wins alone.
3. **Prefer exact symbol matches** (×3 weight).
4. **Return the rejected pools** under `rejected_pairs` with the reason, and the runners-up under
   `other_pairs`, so ambiguity is visible rather than hidden.

That fixed BONK and FARTCOIN — both now resolve to the real Solana pools with sane volatility and
genuine drawdowns.

**WIF still cannot be resolved by ticker, and that is not a scoring problem:** the real dogwifhat does
not appear in DexScreener's search results for "WIF" at all. Only the two robinhood imposters do. No
ranking rule can pick an option that is not in the list.

**So the card warns on every ticker query and asks for the contract address.** For the terminal's
search box: **prefer addresses, and surface the warning plus `other_pairs` whenever a ticker is used.**

---

## 3. Does the HAR volatility model transfer to memes?

HAR coefficients fitted on 10 Hyperliquid majors (`VOLATILITY.md`), applied unchanged to DEX memes.
23 pools with ≥60 days of daily OHLCV, 3,586 one-day-ahead predictions.

| | value |
|---|---|
| mean predicted move | 3.053% |
| mean actual move | 2.883% |
| **mean actual ÷ predicted** | **0.917×** |
| median ratio | 0.589× |
| correlation(predicted, actual) | 0.232 |
| mean-matching correction | **0.944×** |

### Calibration by predicted decile
| decile | n | predicted | actual | ratio |
|---|---|---|---|---|
| 1 | 358 | 0.171% | 0.070% | **0.409** |
| 2 | 359 | 1.112% | 1.258% | 1.131 |
| 3–9 | 2,510 | 1.86–4.41% | 1.74–3.97% | 0.895–1.115 |
| 10 | 359 | 8.595% | 7.933% | 0.923 |

**Deciles 2–10 calibrate within ±13%.** That is better transfer than I expected from a model fitted on
BTC/ETH/SOL and applied to Solana memecoins. Decile 1 over-predicts badly (0.41×), but that bucket is
stale near-zero-movement pools and is not a trading case.

By liquidity, the over-prediction grows with depth: < $100k → 1.001×, $100k–$1M → 0.966×, ≥ $1M → 0.870×.

### Why no correction factor is shipped
The mission expected under-prediction and asked for a correction. I measured the opposite, and
**applying the measured 0.944× would be the wrong call**, because:

- **n = 23 pools, not the ~100 asked for.** GeckoTerminal's current listings are overwhelmingly
  brand-new pools; only 23 of ~400 sampled had 60+ days of history.
- **Survivorship bias is one-sided and large.** Tokens that rugged hard enough to be delisted cannot
  be sampled at all, and those are precisely the most volatile. So the true ratio is higher than 0.917.
- **The failure modes are asymmetric.** Over-warning costs a missed trade; under-warning costs the
  position. A multiplier below 1.0 makes the card under-warn on exactly the tokens most likely to
  blow up.

`MEME_VOL_MULTIPLIER = 1.0`. The measured value and reasoning are in `meme_calibration.json` if anyone
wants to revisit it with a bigger sample.

Also note the **correlation is only 0.232**, against 0.246–0.375 on majors. The model gets the *level*
about right but ranks memes less well, so use it for sizing, not for picking between tokens.

---

## Trader rules

1. **Never size above liquidity ÷ 100.** That is the 2%-slippage cap — $800 in an $80k pool, $60k in a
   $6M pool.
2. **Paste the contract address, never the ticker.** A "WIF" search returns only imposters; the real
   token is not in the results at all.
3. **Walk away from any pool with under $1,000 of daily volume**, no matter how deep it looks — $113M
   of liquidity with zero volume is a trap, not an opportunity.

## Method notes
- Volatility is the standard deviation of daily closes from GeckoTerminal; drawdown is from the ATH of
  the retrieved window (up to 200 days), not an all-time ATH.
- Risk flags fire on: pair age < 7 days, liquidity < $50k, volume > 10× liquidity (churn/bots),
  drawdown > 90%, daily volatility > 25%.
- `card()` never raises; failures come back as `ok: False` with the reason in `notes`.
- Pools were sampled across solana / eth / base / bsc, 5 pages each, deliberately including
  low-liquidity ones.
