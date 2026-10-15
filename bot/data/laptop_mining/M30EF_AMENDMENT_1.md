# M30 (e)/(f) AMENDMENT 1 - adopts ALL 3 FATAL + 11 MATERIAL + 4 MINOR from the 3-judge panel (wf_02794887-1de; all three returned BUILD-AFTER-FIXES). This is the governing spec; the original design's conflicting clauses are superseded.

## FATAL (all adopted - without these neither arm yields a valid verdict)
1. **(e) leak guard was a tautology.** `max(sibling_hit_idx - decision_idx) <= 0` can never fail when
   the close executes AT the sibling bar. REPLACED by a FORWARD-SCAN + a guard that CAN fail: for
   position p (entry e_p, natural exit x_p) enumerate every OTHER same-coin plan s; compute each
   sibling's first-+1R bar h_s using ONLY bars <= h_s; close_idx = min over siblings of h_s subject to
   e_p < h_s <= x_p; close at p's OWN price at close_idx, never a bar < close_idx. GUARD: recompute
   h_s* after deleting all sibling bars > close_idx; if h_s* changes, a future bar set the hit ->
   look-ahead -> FAIL. Drop "nearest overlapping entry" selection entirely.
2. **(both) headline is the DOUBLE DIFFERENCE, not (arm-runner).** A-D proved (arm-runner)_real is the
   mechanical quantity. HEADLINE = D_real - D_null where D_real = mean paired (arm-runner) on real
   paths, D_null = same on persistence-preserving null paths. Wider-of-coin/day-block CI on the DOUBLE
   DIFFERENCE. D_real and D_null are diagnostics only.
3. **(e) needs a JOINT coin-level null.** Same-coin sibling-close is dominated by within-coin wick
   convexity; an independent-path null under-estimates it and leaves a spurious positive. NULL =
   resample ONE circular-block index sequence per coin (block 6 start), carry BOTH the sibling target
   detection AND this position's close price through the SAME resampled coin path; assert sibling-hit
   idx <= decision idx on null paths too.

## MATERIAL (all adopted)
- **(f) survivor bias:** anchor the sample at the half-fill bar over ALL protected runners; difference
  PAIRED per position (control_i = natural runner outcome; arm_i = identical up to T then flat).
  Pre-T exits have arm_i-control_i = 0 by identity and STAY in the set. Never compare against an
  unconditional remainder population.
- **(f) T-sweep population drift:** cross-T curve on the FIXED common sub-population (half-fill early
  enough that all swept T up to 30h fit the available path). Report per-T binding n.
- **(f) multiplicity:** ONE primary T = 24h is the verdict-bearing test; {12,18,30}h are the
  descriptive curve with a family-wise band. "Exists a T where fwd-expectancy<=0" is a min-over-T
  cherry-pick and is NOT a verdict. FWER over ~2 effective independent tests (strong nesting).
- **(f) per-T MDE table:** tabulate n_T, coin/day-block SD_T, MDE_T for all four T BEFORE any read;
  each curve point read against its OWN MDE_T.
- **(f) variance-removed is BY-CONSTRUCTION:** a fixed-age cap mechanically lowers variance. Flag it
  DESCRIPTIVE; the only honest variance claim is null-subtracted (capped-arm var minus the SAME cap on
  null remainders), paired on the same paths with the big-runner cost it pays for.
- **(f) big-runner cost must be point-in-time:** define the big-runner subset from MFE-so-far AT bar T
  (not whole-life MFE, which fixes the cost's sign). Or report the cap's cost unconditionally.
- **(f) positive control fully specified:** inject decay ONLY in the post-T remainder at magnitude
  ~= per-T MDE; headline must recover it (recovered ~= injected within CI). SEPARATELY a ZERO-injection
  placebo on FRESHLY resampled null remainders each rep (not pinned to zero) must recover 0 within CI.
  Pass requires BOTH.
- **(e) NOT underpowered on count:** 24-bar spacing + 48-bar holds make same-coin overlap structural;
  qualifying-sibling subset ~1-2x10^4 moments. Binding constraint is coin-cluster n_eff~176 ->
  pre-register MDE ~0.04-0.08R; a DEFER must come from the clustered CI, never from a count.
- **(e) thin cell:** qualifying-sibling INTERSECT big-runner(MFE>=1.5R) ~1-2.5k moments / ~100-150
  coins; n_eff may be <100. Pre-state a SEPARATE MDE for this cell; if its widest CI can't resolve the
  -0.09..-0.31R tail band, declare the CELL UNDERPOWERED up front - never report the pooled tail as if
  the cell were resolved.
- **(e) hindsight fill:** execute contemporaneously (first bar the sibling-hit becomes true in a
  streaming pass), never a scanned-back peak. Label realized-P&L / P(banked>0) / same-side-sibling
  slices DESCRIPTIVE; the only tested quantity is the full-outcome double difference.
- **(e) needs a positive control too:** inject a known post-sibling-hit drift ~= (e)'s MDE and confirm
  the double difference recovers it; if not, verdict is UNDERPOWERED, not null.

## MINOR (adopted)
- (e) require close_idx >= e_p and strict t_entry < h_sibling <= t_entry+48 (exclude pre-entry/entry-bar
  hits that would close p at ~0R and bias the mean to 0); report n before/after the guard.
- (f) only verdict quantity = paired control-subtracted mean; all conditional slices (hour-of-fill,
  MFE-since-half sign at T [annotated by-construction], funding sign) DESCRIPTIVE with own n.
- (f) null = circular-block-bootstrap the forward return series FROM the half-fill bar (block 6), carry
  trail + fixed-age-T close, D_null = (f_null - runner_null) on the common open-at-T set.

## Build order (unchanged governance)
null gate + positive control run FIRST and must pass; MDE/MDE_T stated before any verdict; report the
DOUBLE DIFFERENCE with widest CI; by-construction slices flagged descriptive; HYPOTHESIS cap; auto
rule only on my SUPPORT + owner go; the live give-back ALERT stays insight-only. Likely verdicts to
pre-admit: (e) main contrast powered but its tail cell possibly UNDERPOWERED; (f) a clean paired
clock study, owner-priority ("mine it extremely" = descriptive T-depth, not a lower bar).
