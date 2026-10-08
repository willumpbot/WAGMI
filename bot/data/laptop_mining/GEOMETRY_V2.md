# Geometry, corrected — there was never a geometry finding


> ⏳ **PENDING RED-TEAM REVIEW.** Two independent reviewers are attacking this *negative* from
> opposite angles — one testing whether the side-flip null is too strong (if it is, v1 may have been
> partly right), one testing whether the `tp 1.0R` residual is being dismissed on an underpowered
> null. Treat the conclusions as provisional until `GEOMETRY_V2_REVIEW` lands. The retraction of v1
> stands regardless; it was verified independently.

_2026-10-08. Supersedes `GEOMETRY.md`, `sweep_geometry.py`, `sweep_oos.py`,
`geometry_walkforward.py`. 15,663 signals, 71 days, 14 ISO weeks.
Script: `geometry_v2.py`. Data: `geometry_v2.json`. Context: `RETRACTION.md`._

---

## Headline

**My own corrected analysis confirms the refutation. Widening the stop never repaired a geometry
parameter — it removed a losing signal stream's ability to hurt you. Zero of 24 cells survive a
side-flip null.**

The mechanism is now measured rather than argued, and it is simple: `real − flipped` isolates purely
directional damage, because geometry, fees, bars, tie rule and horizon are identical on both sides.

| stop width | real R | side-flipped R | **real − flipped** |
|---|---|---|---|
| ×0.5 | −0.4585 | −0.1628 | −0.2957 |
| **×1.0 (the bot's setting)** | **−0.3477** | −0.0105 | **−0.3372** |
| ×2.0 | −0.2000 | +0.0057 | −0.2058 |
| ×4.0 | −0.0432 | −0.0874 | +0.0443 |
| ×8.0 | −0.0050 | −0.0464 | +0.0414 |
| ×12.0 | +0.0005 | −0.0253 | +0.0258 |
| ×32.0 | +0.0002 | −0.0095 | **+0.0097** |

At the bot's stop width the signals' wrongness costs **−0.34R**. At a 32× stop it costs **+0.01R** —
nothing. And note where both columns converge: **real +0.0002, flipped −0.0095.** With a stop that
wide nothing ever stops out, so you collect the 48-hour drift, which is zero either way. That is the
plateau the original document mistook for a repaired system.

## The decisive test

| cell | real vs default | side-flipped vs default | verdict |
|---|---|---|---|
| 8.0\|0.5 | **+0.3623** [+0.042, +0.692] | **+0.0042** [−0.288, +0.325] | directional, not geometric |
| 12.0\|0.5 | +0.3603 [+0.041, +0.665] | **−0.0062** [−0.307, +0.317] | directional |
| 12.0\|1.0 | +0.3482 [+0.026, +0.660] | **−0.0147** [−0.313, +0.335] | directional |
| 20.0\|0.5 | +0.3482 [+0.035, +0.650] | **−0.0041** [−0.298, +0.335] | directional |
| 32.0\|0.5 | +0.3479 [+0.047, +0.641] | **+0.0010** [−0.290, +0.361] | directional |

Every wide-stop advantage is ~**+0.35R on real signals and ~0.00R on flipped ones.** If this were a
geometry effect it would appear in both columns, because the geometry is identical. It appears in
neither the flipped column nor, therefore, in reality.

---

## What changed from the original, and what each fix cost

| fix | effect |
|---|---|
| **Entry lookahead removed** — entry is now the *open of the first bar strictly after* the signal, and the stop distance is the bot's own `|entry_sig − sl_sig|`, never re-derived from a later price | the default moves **−0.4308R → −0.3477R**; the lookahead was worth ~0.083R, 19% of the original headline |
| **Side-flip null added** | the headline finding dies |
| **All cells printed** | revealed the cheap alternative the original hid (below) |
| **ISO-week bootstrap blocks** instead of (symbol, day) | intervals widen as expected |
| **Calendar folds** instead of signal-day slices | only **2** honest folds fit in 14 weeks, not 4 |
| **Grid extended to ×32** so argmax can be interior | fold 1 still picks the grid edge; the surface is monotone by construction |

### The walk-forward now has two folds and one of them inverts
| fold | n | weeks | picked | real advantage | **null advantage** |
|---|---|---|---|---|---|
| 2026-04-08 → 04-29 | 5,997 | 4 | 32.0\|0.5 (grid edge) | +0.4499 | −0.1274 |
| 2026-04-29 → 05-20 | 4,438 | 3 | 8.0\|0.5 (interior) | +0.1346 | **+0.4007** |

In the second fold **the null beats the real signals** (+0.4007 vs +0.1346). The original "4/4 folds
confirmed" was four restatements of a monotone surface across nested training windows, on folds that
included a 4-data-day window straddling a 23-day hole.

---

## The one residual, and why it is also not a finding

The cells the original hid show that **keeping the existing stop and changing only the target** does
something measurable:

| configuration | R | vs default | CI95 |
|---|---|---|---|
| stop ×1.0, tp **1.0R** | −0.2808 | **+0.0669** | **[+0.0046, +0.1275]** |
| stop ×1.0, tp 0.5R | −0.2178 | +0.1299 | [−0.0145, +0.2728] |
| stop ×1.0, tp 1.5R *(default)* | −0.3477 | — | — |

The `tp 1.0R` cell is the **only** cell in the whole surface with a tight interval excluding zero, and
it needs no position-size change, no 17% stop, and no new infrastructure.

**But it fails the same null.** On side-flipped signals the same change is worth **−0.0055R** —
nothing. The reason is the same mechanism read from the other end: with a stream that loses, taking a
small profit quickly beats reaching for a larger one. For a stream that *wins* you would want the far
target. So "near targets are better" is another restatement of "the signals lose money."

**Conclusion: the entire geometry surface is one fact wearing twenty-four hats.** The fact is that the
signal stream loses money directionally (−0.2174% per 48h, t = −10.0). Stop width sets the gearing on
that loss and target distance sets how early you escape it. Neither is a discovery.

---

## Trader rules

1. **Do not run a 1× stop with a 1.5R target on a stream with no edge** — it costs **−0.35R** per
   setup, and ~0.34R of that is leverage on being wrong, not a parameter error.
2. **If you must trade this stream, a 1.0R target at the existing stop is the cheapest improvement**
   — **+0.067R**, CI excluding zero, nothing else changes. It is damage control, not edge.
3. **A stop wide enough never to trigger earns exactly zero** — +0.0002R. That is the ceiling of
   everything in this document, and it is the honest valuation of the signal stream.

## Method notes
- Entry: open of the first bar strictly after the signal; rejected if that bar starts more than 1h
  later. Stop distance: the signal's own `|entry − sl|`.
- Side-flip null: identical geometry, fees, bars, tie rule and horizon; only the side is inverted.
- Fees 9 bps per leg, charged in R as `2 × 9bps × entry / distance`.
- Bootstrap: 2,000 draws resampling whole ISO weeks (14 available).
- Conservative tie rule retained (a bar spanning both levels counts as a stop). **Still unresolved:**
  1h bars cannot see intrabar order, so this remains an assumption. 15m and 5m candles are being
  fetched for the Sep–Oct window where Hyperliquid serves them, which is the only period where it can
  be measured — and it is the window the server's live shadow test already covers.
