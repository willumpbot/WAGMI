# M10 — **Keep 48h.** It is the best or near-best cell everywhere, nothing beats it on held-out data, and the timeout did **not** cost the owner on the case he asked about.

_2026-10-14. `m10_time_limit.py`. **EXPLORATORY**, no card above HYPOTHESIS. Source snapshot stamped in
`m10_time_limit.json`. 177 coins, 150 random-time both-sided entries each, M1 v3 martingale control
subtracted **per horizon**, bps of notional net of 9 bps fees, equal-weighted by coin._

**Owner:** *"why do we have the 48 hr time stop? it would've just timed us out at a rough time."*

---

## 1. The answer to the question he actually asked

**Among positions still open at 48h, holding to 7d instead of timing out was WORSE, in all three
groups:**

| group | all still open | **DOWN at 48h** (his case) | up at 48h |
|---|---|---|---|
| MAJORS (asked) | −22.9 bps (z −1.67) | **−8.3 bps (z −0.49)** | −32.2 bps (z −2.06) |
| ORIG17 discovery | −53.9 bps (z −3.00) | **−42.8 bps (z −2.47)** | −58.9 bps (z −2.67) |
| NON-ORIG17 held-out | −13.1 bps (z −1.95) | **−7.3 bps (z −0.69)** | −15.9 bps (z −1.75) |

*(positive would mean holding beat the timeout)*

**So the 48h limit is not costing him — if anything it is helping slightly.** Every cell is negative.
**And for the specific case he raised, a position DOWN at 48h, the penalty for timing out is the
smallest and least significant of the three** (−8.3 on majors, z −0.49; −7.3 held-out, z −0.69).
**There is no measurable cost to being timed out while underwater.**

## 2. 🔴 The surprise, and it inverts his intuition about where the pain is

**The cost of holding past 48h falls mainly on positions that are UP at 48h, not down** — −32.2 vs −8.3
on majors, −15.9 vs −7.3 held out, and the same ordering on ORIG17. **Holding winners past two days
hurt about four times more than holding losers.**

That is mean reversion in the winners, and it is the same direction as **M1**, where `partial_1R_*`
(taking something off at +1R) led at all five K values. **Two independent studies now point at the same
thing: the profitable adjustment is banking a winner earlier, not holding a loser longer.**

## 3. The time-limit table

**bps net of fees, control subtracted, equal-weighted by coin** — `K = 1.65 × exp_move` geometry:

| limit | ORIG17 (discovery) | NON-ORIG17 (held-out) | timeout rate |
|---|---|---|---|
| 24h | −3.5 (z −0.23) | −0.6 (z −0.14) | ~79% |
| **48h** | **+4.7 (z 0.27)** | **+4.1 (z 0.75)** | ~59% |
| 72h | −1.9 (z −0.10) | +3.9 (z 0.63) | ~45% |
| 7d | −27.4 (z −1.30) | −0.6 (z −0.08) | ~18% |
| none (30d) | **−62.7 (z −2.60)** | **−0.2 (z −0.02)** | ~0% |

The fixed-1.7% geometry is flatter and uniformly slightly negative (−1.6 to −2.6 bps held-out, best at
72h/7d), with timeout rates 17% → 0%.

**48h is the top cell in both arms.** But see §4 before reading any of these as real.

## 4. What does NOT survive, and I am saying it before the recommendation

**🔴 The "no time limit is terrible" result does NOT replicate.** ORIG17 says −62.7 bps at z −2.60 —
the only cell in the whole study whose CI excludes zero — and the held-out arm says **−0.2 bps, z
−0.02.** That is not a weakened effect, it is nothing. **So the magnitude of the no-limit penalty is
not trustworthy, and I will not quote the −62.7 as a finding.**

**Nothing clears significance on the held-out arm.** The largest held-out |z| anywhere is 1.33. By the
standard I have applied all week, **this study is UNDERPOWERED and its ranking is suggestive only.**

**And the entries are directionless by construction.** Random-time, both-sided, no thesis — so this
measures the *geometry* of a time limit, not what happens to a plan the owner actually believed in. His
ETH long had a reason behind it; my 26,550 entries did not.

**MAJORS ⊂ ORIG17**, so the majors column he asked for is inside the discovery set and is not
independent evidence. The held-out column is the one that carries weight.

## 5. Recommendation

**Keep `max_hold_h = 48` as the default.** Not because it is proven optimal — nothing here is proven —
but because:

1. **It is the best or near-best cell in both arms and both stop geometries.** No candidate beats it.
2. **The evidence runs against the owner's hypothesis**, consistently and in every group: holding past
   48h was worse, not better.
3. **Changing an arbitrary default to another arbitrary default on an underpowered study is how a
   constant acquires false authority.** 48h was never tested; it is now tested and survives.

**If he wants a change anyway, 72h is the only defensible alternative** — held-out +3.9 vs +4.1 at 48h,
statistically indistinguishable, and it halves the timeout rate (45% vs 59%) if being timed out is
annoying in itself. **24h is the one I would actively avoid:** at a ~79% timeout rate it is barely a
stop-and-target rule at all.

**What I would put in front of him instead of a time-limit change:** §2. The measurable money is in
taking something off a winner, not in holding anything longer.

## Limits
- Random-time both-sided entries; directionless by construction. Magnitude and geometry only.
- Target fixed at 2R in both geometries so the R scale is comparable across horizons; a different
  target would redistribute the timeout/stop/target mix.
- Same-bar stop/target ambiguity counted as the **stop** throughout (conservative).
- 30d stands in for the planner's "none" — a genuinely unbounded hold is not simulable on 208 days of
  1h bars.
- Control subtracted per horizon, which is what makes the columns comparable: a timeout samples price
  at a fixed clock time while stop/target are barrier exits, so they are not equally priced even with
  no edge.
- One venue, 2026-03-17 → 10-14.
