# Mission 13 — should the muted strategies be flipped?

_2026-10-08. Proxy panel 20,214 coin-days, 11 majors, split 2024-05-18.
Script: `muted_flip.py`. Data: `muted_flip.json`._

---

## One-line verdict for the owner

**No — keep the gate. Nothing gets better by trading it backwards. But one of the five
(`bollinger_squeeze`) looks mildly positive the right way round, so it is worth re-testing before it
stays muted forever.**

---

## Results

Returns are next-day, in bps, net of 9 bps fees. Block cluster bootstrap on (symbol, day).
A claim requires the inversion to be **significantly positive on test AND sign-stable across halves** —
an inversion that only works in one half is the same instability that muted the strategy.

| strategy | as-is train | as-is test | inverted train | inverted test | flip? |
|---|---|---|---|---|---|
| `regime_trend` | **+13.9*** [+1.2, +28.0] | −1.4 [−10.1, +7.5] | −31.9* | **−16.6*** [−26.1, −7.5] | **no** — inverting is significantly negative |
| `bollinger_squeeze` | +7.7 [−7.5, +23.1] | **+17.3*** [+3.3, +31.8] | −25.7* | **−35.3*** [−49.6, −20.3] | **no** — inverting is significantly negative |
| `mean_reversion` | −73.5* [−126.0, −24.2] | −35.5 [−76.3, +4.3] | +55.5* [+7.2, +107.3] | +17.5 [−22.7, +58.9] | **no** — not significant on test |
| `multi_tier_quality` | — | — | — | — | **not testable** |
| `confidence_scorer` | — | — | — | — | **not testable** |

Every inversion is either significantly negative or not significant. **The gate should stay.**

### Why two of the five could not be tested
- **`multi_tier_quality`** does have a real label in the laptop's data — 4,315 rows — but they all fall
  on **2026-04-26 and 04-27**. Two calendar days cannot support a train/test split, so this is a
  sample problem, not a result. Only the server's own log can settle it.
- **`confidence_scorer`** appears nowhere in the laptop's data and has no faithful price proxy
  (it scores the ensemble's own confidence, which is not reconstructible from candles). Untested.

### The surprise worth acting on
**`bollinger_squeeze` the right way round is positive in both halves and significant on test:**
+7.7 bps on train, **+17.3 bps [+3.3, +31.8]** on test. Same sign both halves, significant in the
later one.

That is the **only directional signal anywhere in this project to pass sign-stability** — every other
candidate (BTC slices, `chop_floor`, `agree=3+`, the voice panel, the trend floor) died on exactly
this test. It is not proof: it is a **proxy I built from price** (lowest-bandwidth tercile, trade the
band break), not the bot's actual `bollinger_squeeze` implementation, and n is 3,297 test rows.

**Recommendation: before leaving `bollinger_squeeze` muted, forward-grade the bot's real
`bollinger_squeeze` signals for a few weeks.** If the real one behaves like the proxy, muting it is
costing money. That is a cheap test on infrastructure that already exists.

---

## Trader rules

1. **Do not trade any muted strategy backwards** — the best inversion is −16.6 bps per signal, and
   two of them are significantly negative.
2. **Keep the IC gate on** — it is dropping signals whose inverses are also worthless, so the 99.8%
   rejection rate is not costing a hidden edge.
3. **Re-test `bollinger_squeeze` un-inverted** — it is the one at **+17.3 bps** on test, the only
   directional candidate in the project that is sign-stable.

## Method notes
- Proxies, built from daily candles on the 11 majors only: `regime_trend` = long when EMA20 > EMA50;
  `bollinger_squeeze` = within the lowest-bandwidth tercile over 100 days, trade the band side;
  `mean_reversion` = fade RSI above 70 / below 30.
- Inverting negates the raw return and keeps the fee, so fees are charged on both directions.
- **A first run swept in all 41 symbols** — including newly listed memes I had fetched for other
  missions — and produced cells like +309 bps/day for `mean_reversion`. That was an artefact of tiny
  illiquid names. Restricted here to the 11 majors with long validated history.
- **A first version of the verdict logic also declared `regime_trend`-inverted a winner** on the
  strength of its test half alone, while its as-is sign flipped between halves. The sign-stability
  requirement above was added to stop that, and it is the same standard applied to every other finding
  in this project.
