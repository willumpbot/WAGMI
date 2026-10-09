Unasked: scan_grader's n>=30 gate cannot fire. Raise the floor to ~300.

Prompted by bfd75dc1 (scan_grader: n>=30 + CI before "earned"). The methodology is
right -- excess vs universe median, signed, net of fees, CI before claiming anything,
the same design I used in mission 1. But n>=30 cannot resolve any edge that could
plausibly exist.

From the per-trade dispersion measured on 17 clean perps:
   n      95% CI half-width    80%-power MDE
   30         1.44-1.71%         2.06-2.44%   <- the current floor
   50         1.12-1.32%         1.59-1.89%
  100         0.79-0.93%         1.13-1.34%
  300         0.46-0.54%         0.65-0.77%   <- first useful rung
  724              0.29%              0.42%   <- my clean ma50_pullback sample

Against: a round-trip fee of 0.180%, a genuinely good crypto daily edge of 0.2-0.5%,
and the 0.500% MDE my 724-firing test actually achieved (measured by lag placebo, not
by arithmetic on the CI). So at n=30 the gate can only "earn" an effect 4-12x larger
than any plausible edge and 11-13x the fee. A flag making a real 0.3%/trade would read
"not earned" essentially forever.

THREE FIXES, cheapest first:
 1. Display the MDE next to the verdict. Not "not earned" but "not earned -- cannot
    detect under 2.1%/trade at n=31". One line, and the most important of the three,
    because it stops "not earned" being read as "no edge".
 2. Three states, not two: earned / not earned / NOT YET MEASURABLE. A flag at n=40
    belongs in the third.
 3. Raise the floor to n>=300 for an earned/not-earned call at all. Below that, report
    the count and the MDE and nothing else.

ONE NUMBER TO PUT IN THE CODE:
  # 80%-power MDE for a flag's excess-vs-median, from measured perp dispersion:
  #   MDE(n) ~= 1.44% * sqrt(30/n) * (1.96+0.84)/1.96    [ma50-like dispersion]
  # n=30 -> 2.06% | n=100 -> 1.13% | n=300 -> 0.65% | n=724 -> 0.42%
Print MDE(n) beside every flag's grade and the display is honest at any n.

WHY UNASKED: this is the exact error I made four times today and it would have landed
on the owner's screen. scan_grader forward-grades in real time, so it accumulates n
slowly and will spend MONTHS in the underpowered regime while displaying verdicts.
Labelling that correctly now is far cheaper than retracting later.

LIMITS: the scaling assumes my 17-perp dispersion carries to the top-60 universe, and
newer or smaller coins are more dispersed, so these MDEs are OPTIMISTIC for them. The
sqrt(n) scaling also ignores serial clustering (a flag fires in runs), which inflates
the true CI further. Treat the table as a floor on the MDE, not an estimate. Derived
from scanner_flags_v2.json, which is itself not red-teamed.
