# M32 shape study (Project X) - what each ladder STYLE does to the DISTRIBUTION (not the mean - the mean is a wash). Owner-readable table. Quarters = a smoother ride (fewer losing trades, lower variance) at a cost on the big runners; NEVER fully scale out (it blows up the worst-loss rate).

_From m32_result.json (51,930 moments, persistence-preserving null). Mean (net-vs-runner) is ~0 for every
style - laddering doesn't change expectancy; it reshapes the DISTRIBUTION._

| style | losing-trade rate | worst-loss rate P(<=-1R) | variance (SD) | big-runner cost | mean edge |
|---|---|---|---|---|---|
| runner (50%@1R+trail) | 0.536 | 0.050 | 0.800 | 0 (ref) | 0 |
| **quarters** (25%@.5/.75/1R+trail) | **0.468** | 0.078 | **0.712** | -0.236 | ~0 |
| thirds (33%@.5/1R+trail) | 0.486 | 0.064 | 0.713 | -0.195 | ~0 |
| 25/25 (25%@.5+25%@1R+50%trail) | 0.517 | 0.050 | 0.738 | -0.114 | ~0 |
| aggr (full scale-out, ~0 trail) | 0.441 | **0.258** | 0.711 | -0.359 | ~0 |

## Read (owner)
- QUARTERS = a SMOOTHER RIDE: fewer red trades (54%->47%) and lower bounce (SD .80->.71), for the same
  average result. The price is capping your big runners (~-0.24R) and a touch more full-stops (5%->8%).
- Keep a piece TRAILING: "aggr" (scale out everything, no trail) has the lowest red-trade rate but its
  WORST-loss rate explodes to 26% (5%->26%) - dropping the trail removes the cushion. Never fully exit.
- 25/25 is the gentlest smoothing (keeps 50% trailing): barely changes anything, smallest runner cost.

## Rule (one number)
Laddering doesn't make more money - it makes the ride smoother (fewer red trades, calmer swings). Your
quarters default is a fine smoother; just always leave the last piece trailing. (red-trade rate 54%->47%)
