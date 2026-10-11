# Small-cap momentum: the raw returns really are good (+0.95% in 24h). **All of it is drift you could have had from any small cap on any day.** Zero of 16 cells survive.

_2026-10-11. `smallcap_momentum.py`. 169 Hyperliquid perps, 4,520 hourly timestamps, ~151 eligible
coins per hour after excluding the top 15 by trailing volume. Design sealed in
`PREREG_M2_SMALLCAP_2026-10-11.md` (SHA-256 `91c39ce7…`) and **committed in `2d132ff7` before this
ran.** Mission M2._

**Prompted by the owner, verbatim:** *"some of the smaller bigger momentum ones that we have been
noticing and having on lists couldve had some really good calls for us if we have chosen to dive into
them once we found some trend."*

---

## 1. 🟢 The intuition is not stupid — the gross numbers back it up

**This is the important part, and it is why the feeling is so convincing.** Buy a small cap the hour
it breaks its 20-day high on a volume surge, hold 24 hours:

| signal | horizon | **gross return** |
|---|---|---|
| `S3_both` (breakout + volume) | 24h | **+0.95%** |
| `S4_movesurge` | 72h | **+1.19%** |
| `S4_movesurge` | 24h | **+0.84%** |
| `S1_breakout` | 24h | **+0.79%** |

**Those are real averages over 4,500–81,000 events.** If you had been watching a list of small caps
and buying the ones that broke out, you would have seen winners. The memory is accurate.

## 2. 🔴 And then both matched nulls take all of it

The sealed design required the effect to beat **two** baselines. Neither was close:

| signal | hz | gross | **vs the same coin on its own non-signal days** | z | **vs other small caps that same hour** | z |
|---|---|---|---|---|---|---|
| `S3_both` | 24h | +0.95% | **+0.09%** | 0.08 | **−0.05%** | −0.08 |
| `S4_movesurge` | 24h | +0.84% | +0.39% | 0.84 | +0.04% | 0.28 |
| `S1_breakout` | 24h | +0.79% | −0.00% | −0.00 | +0.07% | 0.19 |
| `S2_volsurge` | 24h | +0.25% | −0.28% | −0.75 | −0.12% | −0.72 |

**Read the `S3_both` row.** The breakout earned +0.95%. Buying **that same coin on a random
non-breakout day** earned +0.86% of it. Buying **a random other small cap at the same hour** earned
all of it. The breakout contributed **nine basis points, with a z of 0.08.**

**So the +0.95% is drift, not signal.** Small caps rose over this window and rose together. Any rule
that puts you in them collects that; the rule itself adds nothing.

## 3. 💡 The number that explains why this felt proven: **design effect 123.7**

`S4_movesurge` at 72h has **80,014 events.** That sounds unanswerable. It is not:

| | |
|---|---|
| events | **80,014** |
| distinct signal **days** | **186** |
| mean events per day | **430** |
| within-day correlation of outcomes | **ρ = 0.29** |
| **design effect `1+(m−1)ρ`** | **123.7** |
| **effective independent observations** | **~650** |

**When 430 small caps fire on the same day, that is close to one observation, not 430.** They all rise
and fall together. So 80,000 events carry the weight of a few hundred, the MDE is **214 bps**, and
nothing in the table could have been resolved at the size it actually is.

**This is the mechanism behind the illusion.** Watching a list of small caps, you see many
confirmations — but they are the *same* confirmation, repeated across coins that move as one.

## 4. The costs close it even if you ignore the statistics

Every one of the 16 cells is **negative net of fees at every assumption tested:**

| best cells | net @18 bps | net @40 bps | net @80 bps |
|---|---|---|---|
| `S4_movesurge` 24h | **−13.9 bps** | −35.9 | −75.9 |
| `S1_breakout` 24h | −18.3 | −40.3 | −80.3 |

**The best cell in the study loses 14 bps at the cheapest possible cost assumption.**

## 5. ⚠️ And at a 3-day hold it is actively **worse** than just owning the coin

Against the coin's own non-signal days, **all four signals go negative at 72h:**

| signal | vs N1 at 72h | z |
|---|---|---|
| `S3_both` | **−3.28%** | −2.30 |
| `S1_breakout` | **−2.45%** | −2.56 |
| `S2_volsurge` | **−1.77%** | **−2.88** |
| `S4_movesurge` | −0.47% | −0.61 |

**None clears the Bonferroni bar of 2.95** (`S2_volsurge` comes closest at −2.88), so this is not a
finding. But **4 of 4 share the sign**, and it points the same way as the two results that *are*
established: short-horizon **reversal**, in the 5m panel and now in the 42-coin 1h panel.

**Tentative, not claimed: buying a small-cap breakout and holding three days looks worse than holding
that coin indifferently.** It is the cell most worth re-testing as the panel grows.

## 6. The other gates, for completeness

`S3_both` 24h — the best-looking cell — fails them too:

- **Walk-forward: the sign flips.** First half **+0.195%**, second half **−0.024%**.
- **Only 42.9% of events were positive.** The positive mean comes from a minority of large winners.
- Concentration is not the problem here (the total is small relative to individual swings), which is
  the opposite of the `CROSS_SECTIONAL_V2` failure mode and worth noting.

## 7. 🔴 The bias I wrote down before running, restated as the prereg requires

**Hyperliquid serves no candles for delisted perps.** This universe is the 169 coins alive on
2026-10-11. Every small cap that pumped, collapsed and was delisted inside the window is **missing**,
and a momentum-long rule would have bought some of them on the way up.

**So every gross number in §1 is an upper bound, and the true figures are worse than shown.** A null
result under survivorship bias is a *strong* null.

## 8. Verdict

**DOES NOT STAND.** 0 of 16 cells pass. The gross returns are real and the intuition that produced
this question was tracking something true — **it was tracking small-cap drift and co-movement, not
momentum continuation.**

**Nothing changes on the bot.** The server's `momentum_small` flag has no measured edge behind it; it
should stay hidden from the owner and keep being graded live, which is what the server already does.

**What this does deliver, per the owner's narrowed ask (*"paying more attention to them"*):** if
Claude's trade ideas look at moving small caps, the breakout is **not** a reason to size up, and a
**3-day hold is the worst of the horizons tested.** Any small-cap idea has to earn its place on
something other than "it is breaking out on volume."

## Limits
- **Survivorship (§7) is unquantifiable with this data** and biases every number upward.
- **208 days, one market regime** — small caps drifted up over it. The nulls remove that drift, which
  is the point, but regime dependence cannot be tested in a window with one regime.
- **Trailing-volume ranking is a proxy for point-in-time volume.** It uses only prior bars so it does
  not leak, but it is not the server's live top-15 definition.
- **Exits were specified in the prereg as secondary** (trailing 15%/25%, target +10%) and are **not
  yet run** — gate 1 failed on the primary fixed-horizon test, so the exit grid would be fitting
  shapes to noise. It stays available if a future panel changes the primary result.
- **Depth is still missing.** Capacity is a volume proxy; `impactPxs` would make it real, which is the
  same ask `INTRADAY_DISP.md` made.
