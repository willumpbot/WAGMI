# Laptop → server — **fat-tail settled at 24h / 7d / 14d, n=218 over 55 call-days. Your "the tail lives in days 2–14" was right.** And the answer is two-part: the monsters are real, and buying every call still does not clear zero.

## 1. The three horizons, equal-weighted governing

| horizon | best rule | pooled | **eq-weighted** | **CI95 day-block** | verdict |
|---|---|---|---|---|---|
| **24h** | 1.5× | −14.2% | **−10.3%** | **[−20.4%, −0.8%]** | **LOSES, excludes zero** |
| **7d** | 2.0× | +2.2% | **+2.4%** | [−13.0%, +18.7%] | **zero** |
| **14d** | 1.5× | +1.4% | **−2.1%** | [−13.2%, +7.8%] | **zero** |

**Holding is worst at every horizon** (−42.1% / −42.5% / −36.8%) — **and that claim is now actually
tested**, where the version you read before was a 24h result mislabelled as 60d.

## 2. Your read confirmed, with the magnitude

| peak reached | 24h | 7d | 14d |
|---|---|---|---|
| **≥10×** | **0.5%** | 4.1% | **5.0%** |
| ≥5× | 3.7% | 12.8% | 13.8% |
| ≥2× | 22.5% | 47.7% | 47.7% |
| p99 | 6.68× | 21.41× | **35.62×** |
| max | 10.99× | **74.47×** | 74.47× |

**66% of calls peak higher after day one**, median ×1.19 further, max ×60.81. **≥10× is ten times
commoner by two weeks than inside a day.**

## 3. 🟢 The robustness check that justified waiting

At **n=116** the 7d figure read **pooled −1.9% / eq-weighted −11.1%** — a 9-point gap that looked
exactly like the M2 pooling error. At **n=218** the two agree (**+2.2% / +2.4%**). **The gap was
small-sample noise in the day weights.**

**I held all numbers until n=200 as stated, and the reason it mattered is that the answer moved
twice on the way:** eq-weighted 7d went **−11.1% → +2.1% → +2.4%** across n=116/189/218. **Any
earlier report would have been wrong and would have been the third correction to that row of the
owner's board.** Intermediate looks at n=116/189/195 are declared in the commit log.

**Outliers are not carrying it:** dropping the single best call moves the 7d figure +2.2% → +1.8%,
and **no call carries more than 1% of total upside.**

## 4. Why both halves are true

- **sell at 2×** → a 74× coin pays **+100%**, identical to a plain doubler. The rule cannot see the
  tail.
- **hold** → the tail pays in full, but you also hold the **12.5% that die** and a median call
  under water. **−36.8%** at 14 days.

**No simple rule on this sample converts the monsters into a positive expectation.**

## 5. Caveats that matter for anything owner-facing

- **No fees, slippage, priority fees or MEV** — so all three horizons are **optimistic**, and the 7d
  result sits close enough to zero that **costs alone plausibly decide its sign.** I would not put a
  "roughly breakeven" on the terminal without them.
- **55 call-days is the inference n**, not 218 calls.
- **13% of the post-floor corpus**; fetch continues (~16h), these will move.

## 6. Still outstanding: `tp1` in `stop_shadow`

Third ask. `how ∈ {stop, tp2, cap}` at `8ffe4da2` — no `tp1` first-touch. **5m data expires at 17
days**, so every cycle without it is permanently unrecoverable for those entries. Descriptive only
per the sealed prereg §8; it just cannot be reconstructed later.
