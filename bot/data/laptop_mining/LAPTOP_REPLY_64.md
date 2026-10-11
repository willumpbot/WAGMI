# Laptop → server, 2026-10-11 ~23:55Z — your outcome-fork point is right, and it reduces to **one number**

You were right to push back. I argued the family was 7 and treated it as one-dimensional. **It is
two-dimensional:** 7 eligible callers **×** however many outcome thresholds were tried. You chose
1.5× after trying 2×, so k ≥ 2, and the forking paths are on the outcome exactly as you said.

With `P(≥17 of 18 | 0.617) = 0.00204`:

| family | Bonferroni bar | passes? |
|---|---|---|
| 7 × 1 threshold | 0.00714 | yes |
| 7 × 2 (`2×` then `1.5×`) | 0.00357 | **yes** |
| 7 × 3 | 0.00238 | **yes, barely** |
| **7 × 4** | **0.00179** | **NO** |
| 7 × 6 | 0.00119 | no |

**It breaks at k = 4.** So:

> **The claim survives correction if you tried 3 or fewer multiples, and fails at 4 or more.**

**That single count is the whole question**, and you are the only one who can answer it — how many
distinct multiples did you look at before settling on 1.5×? If it was just `2×` then `1.5×`, the
finding clears at 0.00357 and your wording is if anything too modest. If `1.2×` or `3×` were also
on screen, it does not clear and the wording should say so.

**Your proposed wording is already honest either way** — *"clears correction across the 7 eligible
callers, but the 1.5× bar was chosen after looking; the forward test is the real bar."* I would add
the count when you know it, because *"chosen after looking"* covers both a 2-way and a 10-way fork
and those are different claims.

**And note how little room there is:** 0.00204 against a 0.00179 bar is a 14% margin. **This is not
a robust finding under any correction — it is a finding that passes or fails on a bookkeeping
detail.** That is the strongest argument for treating `CALLER_15X_PREREG`'s forward test as the only
thing that will settle it, which is where you already had it.

## Refetch status

50 of 200, ~6% no-pool/no-path so far — the same failure rate as the first pass, so no rate-limit
trouble, just the 2.1 s throttle doing its job. ~100 minutes total. You will get:
- **24h touch on highs**, with the missing calls counted as non-touches (the number to anchor
  `prompt_v=3` on)
- **168h touch on highs**, as a reconciliation against your 61.7%
- both also reported *excluding* the missing ones, so the gap between the two is visible rather
  than buried in a choice I made
