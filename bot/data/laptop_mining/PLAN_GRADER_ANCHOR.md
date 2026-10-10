> # ⚠️ CORRECTED: 1.26–1.42%, not 1.80% (red team `wxoc7han2`)
>
> Direction stands and is near-mechanical — a 5m bar must span **2.2%** to contaminate at this
> geometry. Reviewers reproduced mission 4's comparison cells byte-exact (25.53%, 3.60%) and then
> measured **1.26% sampled / 1.42% exhaustive** at the owner's exact geometry, and **0.00% on SOL**
> specifically. So the shipped fix is right and the magnitude is smaller still: roughly **1 plan in
> 75**, not 1 in 55.

# Mission 7 — at the owner's real geometry the fill-candle bug hits 1.80%, not 9.62%.

_2026-10-10. Anchored on `server_exports/plans.json`, 11 clean perps, 5m bars.
Corrects the headline of `PLANS_AUDIT.md` as applied to the owner's actual trading._

---

## The real geometry, read from the plan rather than guessed

| field | value | |
|---|---|---|
| limit entry | 112.335 vs price 110.305 | **1.84% away = 0.411 stop-distances** |
| stop | 117.280 | **4.40% of entry** |
| `exp_move_pct` | 2.66% | so the stop is **1.65 expected moves** |
| target | 109.862 | **exactly 0.500R** |
| entry window / max hold | 24h / 48h | |
| leverage / risk | 7× / $62.50 | |
| result | **expired, entry never reached** | |

(SOL SHORT, plan `892daf3001`. The brief described this as "stop 4.4% ~1 expected move" — it is
**1.65** expected moves. Worth knowing, because it is the number that matters for the one surviving
geometry finding.)

## The anchored answer

| geometry | limit fills | contaminated | share |
|---|---|---|---|
| my Mission 4 guess: stop 1.0%, tp 0.5R, offset 0.5 | 4,953 | 1,273 | **25.70%** |
| my Mission 4 guess: stop 3.0%, tp 0.5R, offset 0.5 | 3,570 | 131 | 3.67% |
| **REAL: stop 4.40%, tp 0.500R, offset 0.411** | 3,215 | 58 | **1.80%** |

**`PLANS_AUDIT.md`'s 9.62% headline was an average across a sweep dominated by stops of 0.5–1%, which
the owner does not use.** At his real geometry the figure is **1.80%** — a 5× overstatement as
applied to his actual trading. The bug is real and the fix was right; the urgency was overstated.

### Two reasons the old number was wrong, not one
1. **Wrong geometry.** The sweep's tight-stop cells dominated the average, and the real stop (4.40%)
   is *wider than anything I swept* (max 3.0%). Contamination falls steeply with stop width.
2. **Contaminated symbol set.** The 9.62% was computed over 22 "symbols" that included the stale
   `*_spot` series — the same filter bug that invalidated Mission 1. This run uses **11 clean perps**.

## What does not change
- The fix itself stands and the server has already shipped it (adverse-side-only, not a blanket
  skip). At 1.80% it is a small correction rather than an urgent one, but it is free and it removes a
  genuine bias.
- The *mechanism* was never in doubt: the fill candle really was tested on its own pre-fill range.
  Only the magnitude moved.

## One thing the owner should hear
**His stop placement is consistent with the only geometry finding that survived review.** `GEOMETRY_V3`
concluded "do not put your stop closer than a normal day's move" (tightening to ½× cost −0.13R to
−0.20R). His stop is **1.65 expected moves** — comfortably outside. Whatever else is unsettled, that
choice is right.

## Trader rules — one number each
1. **The grader's fill-candle bias affects about 1 plan in 55 at your geometry** (1.80%), not 1 in 10.
2. **Wide stops are self-protecting against this class of bug.** At a 1% stop it would be **25.7%**;
   at your 4.4% it is 1.8%.
3. **Your stop is 1.65 expected moves** — outside a normal day, which is the one stop rule that
   survived.

## Limits
- **One plan.** This anchors the geometry, not the dispersion. If the owner's later plans use tighter
  stops the figure rises steeply — re-anchor once there are more (see `DATA_REQUEST.md` §4).
- 11 perps with 5m history, a short window; the ambiguous/contamination rate depends on 5m range
  relative to bracket width, so a more volatile regime would raise it.
- Limit fills still assumed on any touch, exits at the level, no slippage.
