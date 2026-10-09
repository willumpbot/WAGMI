# Unasked: `scan_grader`'s "n≥30 + CI" gate can't fire. Raise the floor to ~300.

_2026-10-09. Derived from `scanner_flags_v2.json`'s measured dispersion on 17 clean perps.
Prompted by commit `bfd75dc1`: "scan_grader: forward-grade every scanner flag vs the universe median
(signed for directional flags, net of fees); **n≥30 + CI before 'earned'**"._

---

## The problem

Your gate is methodologically right — excess vs the universe median, signed, net of fees, CI before
claiming anything. It's the same design I used in Mission 1. **But n≥30 is far too small to resolve
any edge that could actually exist.**

Using the per-trade dispersion I measured:

| n | 95% CI half-width | **80%-power MDE** | |
|---|---|---|---|
| **30** | 1.44% – 1.71% | **2.06% – 2.44%** | **← your floor** |
| 50 | 1.12% – 1.32% | 1.59% – 1.89% | |
| 100 | 0.79% – 0.93% | 1.13% – 1.34% | |
| **300** | 0.46% – 0.54% | **0.65% – 0.77%** | ← first useful rung |
| 724 | 0.29% | 0.42% | ← my clean `ma50_pullback` sample |

Ranges span `ma50_pullback` (tighter) to `on_20d_low` (wider).

**Reference points:**
- round-trip fee: **0.180%**
- a genuinely good crypto daily edge: **0.2% – 0.5%**
- my clean 724-firing test's measured 80%-power MDE: **0.500%** (by lag placebo, not arithmetic)

**So at n=30 the gate can only "earn" an effect 4–12× larger than any plausible edge, and 11–13× the
fee.** A flag making a real 0.3%/trade would read "not earned" essentially forever.

## Three fixes, cheapest first

1. **Display the MDE next to the verdict.** Not `"not earned"` but
   `"not earned — can't detect under 2.1%/trade at n=31"`. This costs one line and it is the single
   most important change, because it stops "not earned" being read as "no edge".
2. **Use three states, not two:** `earned` / `not earned` / **`not yet measurable`**. A flag with
   n=40 belongs in the third. Today's whole lesson is that those are different claims.
3. **Raise the floor to n≥300** for an "earned/not earned" call at all. Below that, report the count
   and the MDE and nothing else.

## Why I'm sending this unasked

This is the exact error I made four times today, and it would have landed on your screen. In Mission
1 v1 I reported a "power table" that was secretly the CI bound restated; in Mission 3 I built a
control so strict it discarded 94% of the data and then called the resulting silence a null. Both
times the output said "no effect" when the honest answer was "this design cannot see an effect this
small."

`scan_grader` is forward-grading in real time, so it will accumulate n slowly — which means it will
spend **months** in the underpowered regime while displaying verdicts. Labelling that correctly now
is much cheaper than retracting later.

## One number to put in the code

```
# 80%-power MDE for a flag's excess-vs-median, from measured perp dispersion:
#   MDE(n) ~= 1.44% * sqrt(30/n) * (1.96+0.84)/1.96     [ma50-like dispersion]
# n=30 -> 2.06% | n=100 -> 1.13% | n=300 -> 0.65% | n=724 -> 0.42%
```

Print `MDE(n)` beside every flag's grade and the display becomes honest at any n.

## Limits
- The scaling assumes the per-trade dispersion I measured on 17 perps carries to your top-60
  universe; newer and smaller coins are more dispersed, so **these MDEs are optimistic** for them.
- `sqrt(n)` scaling ignores that your forward sample will be serially clustered (a flag fires in
  runs), which inflates the true CI further. Treat the table as a floor on the MDE, not an estimate.
- Derived from `scanner_flags_v2.json`, which is itself not red-teamed.
