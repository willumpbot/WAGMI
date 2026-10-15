# M32 LADDER ATLAS = PROJECT X part 1. DESIGN (exploratory; owner request, runs despite the convergence note because it targets the SHAPE/WHY, not mean R). Map the whole scale-out surface (levels x fractions) and - the real prize - whether a circumstance known AT THE PEAK tells faders from runners in advance.

**Status: DESIGN before code. EXPLORATORY throughout; any confirmatory sub-claim gets sealed + a panel.**
Convergence note stands for MEAN R (7 exit nulls); M32 does NOT relitigate the mean - it reports the
DISTRIBUTION and the CIRCUMSTANCE table. Server seed (his 28 trades): runner +0.168R, quarters +0.162,
thirds +0.157, 25/25 +0.136 - ladders rescue faders (VVV -1->-0.5, SUI -0.47->+0.08), shave winners
~0.1R. The mean is a wash (as expected); the question is the shape and whether fade is predictable.

## 1. The ladder resolver (generalises m30's single trim to multi-step)
On the m28 moment grid (random both-sided entries, 24-bar spacing, stop 1.65em, 48h, point-in-time
em/ATR, leg fees). Each STYLE = an ordered set of (level, fraction) tranches + a trailing remainder:
- runner (control): 50% @ +1R, 50% trail 1 ATR.
- quarters: 25% @ +0.5R, 25% @ +0.75R, 25% @ +1R, 25% trail 1 ATR (the owner's new default).
- thirds: 33% @ +0.5R, 33% @ +1R, 34% trail.
- 25/25: 25% @ +0.5R, 25% @ +1R, 50% trail.
- ATR-level variants: the same fractions at +0.5/+1/+1.5 ATR instead of R (level sets in ATR).
Within-bar stop-first; each tranche fills at its level (optimism carried, stated); remainder trails at
runmax - 1 ATR from the last fill. Fees PER LEG (Project X part 4): more tranches = more fees, and the
per-leg fee as a fraction of a THIN-coin tranche is larger - model it explicitly, report net-of-fee.

## 2. The surface (levels x fractions) - map it, don't verdict it
Grid of styles above x {R-levels, ATR-levels}. For each style report, vs the runner, PAIRED per moment:
- mean (arm-runner) in R AND the persistence-preserving null mean (so a "win" that is mechanical is
  flagged - the convergence lesson); expect ~0 net.
- THE DISTRIBUTION (Project X part 2, the real deliverable): P(loss), P(<=-1R), give-back size
  (peak R - realised R), realised-R variance, max adverse drawdown streak. A smoother equity curve at
  equal mean has value to a human - quantify it per style.
- big-runner cost: mean R on the runner-MFE>=1.5R subset (what laddering out costs the real runners).

## 3. The prize - WHY trades fade after +0.5R (Project X part 3): an atlas of fade vs run
For every moment that reached +0.5R, label it FADE (gave back to <=0 before +1.5R) vs RUN (reached
>=+1.5R). Then test what was knowable AT THE +0.5R BAR (point-in-time, no look-ahead):
- VELOCITY: bars taken to reach +0.5R (fast spike vs slow grind);
- volume / range expansion into the +0.5R bar; funding sign + a fresh funding flip; time-of-day /
  session; BTC direction at that bar (co-move); distance to the nearest liq cluster crossed;
  vol tier (ATR percentile); trend state (above/below 20d).
Report P(FADE | circumstance) vs the base P(FADE), each as a table with n and a day-block CI. IF any
circumstance separates fade from run at the peak, THAT is the actual lever (which trades to ladder
harder) - a conditional signal, not an exit dial - and it would then graduate to a SEALED confirmatory
study with its own panel. Exploratory here: surface candidates, no live claim.

## 4. Labels + his history (Project X parts 5-6)
- His filled plans/ideas on the grid as labels (M28 discipline: filled stratum, dedup, +-72h exclusion,
  claude_idea flagged non-owner, late_logged out) - "on his trades, style X would have done Y",
  descriptive, n stated, underpowered - no verdict.
- Wallet A/B exits (M29) vs these styles: decompose how much of his realised loss was EXITS vs ENTRIES
  (re-exit his actual fills under each ladder style, compare to what he did). Owner's question: "how
  much of my past loss was exits."
- Every output a TABLE the owner can read (visual learner), ending in 1-3 plain rules + one number each.

## 5. Swarm plan (owner: "take swarms at this, data mining")
Part 3 (fade-vs-run) is the swarm target: parallel lenses (velocity / funding / BTC-comove / liq /
time-of-day), each mining its own circumstance, + an adversarial verifier that kills by-construction
labels (FADE/RUN is defined on the post-+0.5R path - the circumstance must be strictly pre-peak) and
mechanical nulls. Build order: resolver + surface (parts 1-2) FIRST (one run, the distribution table),
THEN the fade atlas (part 3 swarm), THEN labels/history (4). Red-team the incoming
claude/owner-ladder-style branch (quarters default) when the PC pushes it - same standard as the runner.
