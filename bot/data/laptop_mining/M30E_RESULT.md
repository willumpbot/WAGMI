# M30 (e) sibling-close: NO net edge (main contrast NULL, 7th exit-dial null). The one cell that looked like an edge (+0.088R on big runners) is ENTIRELY a same-side by-construction artifact - the clean OPPOSITE-side contrast is strongly NEGATIVE (-0.28R). An automatic "close when a same-coin plan hits target" rule is contraindicated.

_2026-10-15. m30e_run.py to M30EF_AMENDMENT_1 (panel wf_02794887-1de). EXPLORATORY, HYPOTHESIS cap.
51,930 moments / 176 coins; sibling fired on 27,774 (53.5%). Owner (a4cbdffd): "sibling close when a
same-coin plan exits at target." Auto rule needs SUPPORT + owner go._

## 1. Both gates passed BEFORE the read
- POSITIVE CONTROL: injected a post-sibling adverse drift = MDE on the runner's remaining exposure; the
  arm closes at the sibling bar and AVOIDS it, so measured (arm-runner) rose +0.0108R on fired
  (= mean(frac_open)*MDE, ~0.6x; PASS, <= delta).
- PLACEBO (can-fail, the fix): the FATAL-3 joint coin-level null makes D_null itself correctly nonzero
  (it is the mechanical same-coin component), so the placebo is TWO INDEPENDENT null draws differenced:
  A-B = -0.0001R [-0.0024,+0.0024] -> straddles 0, PASS. (A biased estimator would have shown nonzero.)
- MDE pre-registered on the fired subset: 0.0179R.

## 2. The read - HEADLINE double difference D_real - D_null (joint coin-level null), widest CI
| cell | n | coins | double-diff | 95% CI | read |
|---|---|---|---|---|---|
| **fired (main contrast)** | 27,774 | 176 | **+0.0028 R** | [-0.0109,+0.0154] | **NULL** (within +/-MDE) |
| big-runner-so-far (all) | 3,920 | 176 | +0.0875 R | [+0.0335,+0.1440] | see split |
| big · SAME-side sibling | 3,498 | 176 | +0.1323 R | [+0.0670,+0.1954] | by-construction |
| big · OPPOSITE-side sibling | 422 | 153 | **-0.2836 R** | [-0.3804,-0.1921] | clean contrast: NEGATIVE |
| non-big (all) | 23,854 | 176 | -0.0111 R | [-0.0205,-0.0021] | slightly negative |

D_real on fired was +0.0099R; the joint null captured +0.0071R of it as mechanical same-coin wick
convexity (exactly the FATAL-3 risk), leaving +0.0028R = NULL. Sibling-close has NO net edge.

## 3. Why the big-cell "edge" is not real
The +0.088R on big runners is ENTIRELY same-side (+0.1323R; the opposite-side cell is tiny by
comparison). Same-side means: a same-coin SAME-direction sibling hit +1R, so the coin moved our way
and this position is already up >=1.5R at that instant - closing BANKS a favourable move by
construction. The joint null under-subtracts it only because block-bootstrap breaks the exact
intra-move co-timing (a residual by-construction leak, flagged as the panel's same-side MATERIAL).
It is NOT forward-tradeable: it conditions on a correlated same-coin sibling reaching target AND on
being up 1.5R at that bar - a post-hoc selection, and it is the SAME correlated-peak phenomenon M18
already surfaces as a live warning. The decisive tell is the OPPOSITE-side cell: when the sibling that
hits +1R is on the OTHER side (the coin whipsawed), closing the big winner is strongly BAD, -0.2836R
[-0.380,-0.192], n=422 over 153 coins - a real, directionally-clean NEGATIVE. There is no "close on a
sibling's target" edge; if anything, closing on an opposite-side sibling's target destroys R.

## 4. Owner answer + recommendation
"Close this position when a same-coin plan hits its target" does NOT make money on average (NULL), and
in the one clean case it can be tested (the sibling is on the opposite side) it LOSES ~0.28R. The
same-side case that looks good is you banking a correlated move you were already winning - which the
live M18 co-stop warning already covers. Recommendation: auto NOTHING on sibling-close; do not add a
"close on sibling target" rule. The only exit move that ever helped across the whole M30 family stays
BREAKEVEN-PROTECT (A-D arm C). This is the 7th independent exit-geometry null (M13/M14/M16/M28/M30 A-D/
M30 f/M30 e).

## Limits
Direction-null population (M28 closed direction); fills at levels (optimistic); joint null is an
imperfect subtraction for same-side peak co-timing (hence the same-side residual - treated as artifact,
not edge); opposite-side cell n=422 but directionally clean and tight; HYPOTHESIS cap. The M30 family
(A-D, e, f) is now complete: no exit dial moves expectancy; breakeven-protect is the lone exception.
