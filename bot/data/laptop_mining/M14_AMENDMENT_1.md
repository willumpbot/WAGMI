# M14 AMENDMENT 1 — panel verdict (3 judges, 10 FATAL / 12 MATERIAL): the design as written was three degenerate arms and an undeliverable null. RESCOPED before any code; supersedes the design where it conflicts.

The statistics judge MEASURED the degeneracy on the real panel before any build: R2 (EMA20) fills
99.2% of events, R1-on-trail 95.2% (80% within 2 bars — the exit price IS the trigger), R3 84% —
"the arms collapse into one immediate-re-entry trade measured thrice." Only R1-on-clock (43.9% fill)
behaved like a rule. Population: ~15,955 raw events (60.7% CLOCK exits, 39% trail, 0.4% trail-at-floor
— the "momentum ran" framing must say most runners STALLED), chaining into **~1,057 non-overlapping
episodes** — the honest n. Expected MDE ≈ 0.2 R pooled (0.3–0.5 R per split) vs plausible effects
≤ 0.1 R: **this study is a huge-effects-only screen and says so up front.**

## Rescoped arms (3, pre-named; everything else descriptive-only)

- **A1 — immediate re-entry, honestly named**: fill at the FIRST WATCH-BAR OPEN after t_x (a tradeable
  price — never a level the market is already through; pre-trigger share per arm reported). Same runner
  engine; em and ATR14 re-resolved point-in-time at the FILL day (lagged conventions); interpretation
  pre-stated: a positive A1 is evidence about the EXIT being too tight as much as about re-entry.
- **A2 — hold-longer shadow (the owner's real alternative)**: continue the ORIGINAL runner past t_x,
  same trail, 96h clock, FEE-FREE (no new legs). If A1 > 0 but ≤ A2, the verdict is "loosen the exit"
  (M12/M10 territory, zero cost), not "re-enter."
- **A3 — true pullback (R1-on-clock only)**: clock-exit events; re-arm displacement — price must first
  trade ≥ 0.5 × ATR beyond the trigger strictly after t_x, then return; touch from the pre-stated
  direction only; fills at the level with the stop-first fill-bar rule below.
- R2 (EMA) is DELETED (degenerate + no point-in-time spec was written). R3 (retest) demoted to a
  descriptive line (84% fill ≈ A1 duplicate). Mirror arms are DEMOTED to descriptive; the shared-path
  mirror is near-mechanical and cannot fail — leak detection lives in the null gate and a day-shift
  placebo through the identical pipeline.

## Estimand, unit, null — all fixed before code

- **ITT (intention-to-watch)**: per EVENT, arm outcome = net R if filled within 48h else 0, identical
  logic on real and null paths. Headline = per-event ITT mean; per-fill mean + fill rate beside it;
  rule ranking on ITT only; verdict floor: fill ≥ 20% AND n_fills ≥ 1,000 else no verdict language.
- **Unit = the CHAIN**: events deduped to one per coin per overlapping [t_x, t_x+96h] episode
  (keep-first, frozen); opposite-side events of one moment never pooled as independent rows. n reported
  as chains / events / fills; CIs act on the widest of coin-only / chain-level / coin × week; the
  22-week era concentration (top-5 weeks = 29.3% of events) is a stated limit.
- **Null built from scratch**: K martingale continuations + 1 nullreal ANCHORED AT t_x (pool strictly
  before t_x; ≥ 500 prior bars), ≥ 144 bars long; triggers and the full engine run identically on
  them; per-re-entry control draws anchored at the FILL time with pool strictly before it; m28 arrays
  NOT reused. Stated plainly: the unconditional-pool control does NOT price post-run vol conditioning —
  a vol-sensitivity line (post-t_x realized vol vs pool-implied) ships with every read, and no
  directional claim attaches to anything the null gate + placebo did not survive.
- **Eligibility at the EVENT level**: original entry needs ≥ 144 forward bars; truncated re-entries
  resolve at the last bar with a `truncated` flag; excluded/truncated fractions per arm reported;
  HALT on any silent drop. Fill bar participates stop-first (conservative); no same-bar arming credit.
- **Family capped**: 3 ITT cells (A1, A2, A3) vs 0 at z ≥ 3.0, family size written next to the bar.
  Condition-column splits run ONLY on the m28 DISCOVERY era (ORIG17 ∪ daykey < 20693) until the m28
  freeze protocol allows more — the full-panel split was an informal peek at the sealed era.
- Depth-1 scope stated; forward labels tagged with re-entry depth so the sealed forward read can match.
- Carry/fees side-correct on every leg of every arm including A2's absence of them (that asymmetry IS
  A2's point and is stated, not hidden).
