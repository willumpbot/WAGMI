# M30 DESIGN — "take what's given": does a CONDITIONAL give-back partial beat the runner? (Owner priority: VVV +0.52R→−0.31R, RSR +0.92R→−0.20R, both banked nothing. M1 tested FIXED targets, never a give-back TRIGGER.)

**Status: DESIGN, before any code. EXPLORATORY, HYPOTHESIS cap.** Panel first; stats judge measures.
An automatic rule ships only on my SUPPORT + the owner's go — the live give-back ALERT already exists
(insight only). The deliverable is the TRADE-OFF (mean, P(banked), cost in capped big runners), never
the mean alone — because M1/M13/M16 predict the mean is ≈null and the distribution is the story.

## 0. The honest prior (stated so the result can surprise it)
M1: partial_1R led at fixed targets. M13/M16: no at-entry or entry-mechanic dial moved expectancy.
M14: re-entry null. So the base rate for "a new exit rule beats the runner on MEAN R" is low. BUT a
give-back rule is a different object: it converts MFE into banked R by CAPPING the upside — mean may
not move while P(banked anything) rises and the big-runner tail (CASHCAT-type +1.5–2R) is cut. "Take
what's given" is a VARIANCE/skew preference, not necessarily an expectancy claim; M30 must price both.

## 1. Arms (runner = control), all pre-named
On the m28 moment machinery (random both-sided entries, 24-bar spacing, stop 1.65×em, 48h, leg fees,
carry, point-in-time em/ATR):
- **CONTROL = runner** (half @ +1R, 1-ATR trail, 48h) — the live default.
- **A = giveback-0.5**: once MFE ≥ 0.5R, if price gives back 50% of MFE (to ≤ 0.25R) before +1R, bank
  half there; remainder runs the runner from that point.
- **A' = giveback-0.75**: same, MFE trigger 0.75R.
- **B = half-at-0.75R**: take half at +0.75R instead of +1R; rest trails (a fixed-target variant, the
  M1 family at a nearer target — the control for "is it the give-back TRIGGER or just an earlier
  target that matters").
- **C = breakeven-after-N**: after N=24h with MFE ≥ 0.5R and no half taken, move the stop to
  breakeven; otherwise the runner. (Protects, doesn't bank — isolates "stop giving it ALL back".)
- **D = B+A**: half at 0.75R AND the give-back trigger on the remainder.
All fills at trigger levels (optimism carried); within-bar stop-first; MFE measured from entry on the
same bars.

## 2. The give-back trigger is post-entry path info — so the control must see it too
MFE-conditional banking conditions on the path. Per the M14 discipline: each arm's rule runs
IDENTICALLY on the K martingale control paths + nullreal (so the give-back fires on null wicks too),
and the reported arm value is (arm − control) per moment. The null gate (all arms on nullreal−ctrl
inside the z bar) + positive control (inject a known R, recover it) run FIRST. This prevents "the
give-back harvested wick convexity" from reading as edge.

## 3. Metric — the trade-off, three numbers per arm, never just the first
- mean (arm − runner) in R, paired per moment, day-block + coin×week bootstrap, widest CI acts;
- **P(banked anything > 0)** arm vs runner (the owner's actual complaint — nothing banked twice);
- **big-runner cost**: mean R on the subset where the RUNNER reached ≥ +1.5R (the CASHCAT paths the
  give-back caps) — arm vs runner there, so the give-back's price in forgone tail is explicit.
Pre-stated expectation: mean ≈ 0 (within ~0.03 R), P(banked) UP, big-runner subset R DOWN. If so the
verdict is "it's a preference, not an edge — here is the exact R you pay for banking more often," and
whether to take it is the owner's risk-appetite call, not a performance claim.

## 4. Labels (his entries vs random — "were we RIGHT?")
The owner's framing is that HIS two entries were right on direction and still banked nothing. Place his
filled plans + Claude ideas on the grid as labels (M28 discipline: filled stratum only, dedup,
±72h aftermath exclusion, late_logged out, claude_idea flagged non-owner) and report the give-back
arms' effect on the LABELLED subset beside the random population — DESCRIPTIVE, n stated, almost
certainly underpowered (n≈5 owner clusters), so no verdict, just "on his trades it would have done X."
Directional-edge claims stay barred (M28 closed that); M30 is an EXIT-geometry study on a
direction-null population plus a descriptive label pass.

## 5. Seal + govern
Seal the confirmation split (ORIG17/early vs held-out, referencing the m28 boundary) BEFORE reading.
HYPOTHESIS cap; an automatic rule needs SUPPORT + owner go; the live alert stays insight-only
regardless. Panel questions: (a) does the give-back arm double-count the runner's own trail (both move
the stop — is A just a tighter trail in disguise, i.e. M12 territory?); (b) B vs A separates
earlier-target from give-back-trigger — is the design's attribution clean; (c) the big-runner-subset
metric conditions on the CONTROL's outcome — is that a legitimate conditioning (yes: it's the
counterfactual cost, but state it); (d) MEASURE how often the 0.5R-MFE-then-giveback trigger even
fires on the grid before sizing power.
