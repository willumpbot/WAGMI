# M16 DESIGN — limit-entry adverse selection: do filled limits underperform the same setup at market, by limit distance? (Backlog M16. The owner trades limit entries at levels; a limit fills exactly when price moves AGAINST the idea first.)

**Status: DESIGN, before any code. EXPLORATORY, HYPOTHESIS cap. DEFER pre-authorized** if the
population or the fill rates make honest reads impossible — the stats judge measures first.

## 1. The question, framed so it can be answered
A limit order below market (long) is a bet that the adverse path to the fill is noise; adverse
selection says the paths that DO fill are disproportionately the ones that keep going. The clean
estimand is M14's: **ITT per setup-moment** — at each grid moment, compare:
- **L(d)**: place a limit d × ATR14 toward the adverse side (d ∈ {0.25, 0.5, 1.0}, pre-named); if it
  fills within the watch window W = 24h, run the live runner engine from the fill (em/ATR re-resolved
  at the FILL day; stop 1.65 × em_f from the fill); no fill → outcome 0 AND the market arm's outcome
  is still earned — so the contrast is per-moment: **L(d) − M on the same moment**, where
- **M**: enter at the moment's next-bar open at market, same engine.
ITT keeps fill-selection priced: the SAME limit logic runs on the K t-anchored martingale draws +
nullreal, so the control's limit arm fills on null wicks too. The adverse-selection claim is the
pre-stated sign: **L(d) − M < 0 and worsening in d** if adverse selection dominates the better entry
price; **> 0** if the price improvement wins (the two effects fight — that is the study).

## 2. Mechanics (all pre-stated)
- Grid: m28's 24-bar-spaced both-sided moments; both sides share paths (D/A machinery if pooling sides;
  the primary read is per-side ITT contrasts which difference out the shared-path drift since L and M
  sit on the SAME moment and side).
- Limit fill = bar low ≤ limit (long) with the fill bar participating stop-first afterward; fill price
  = the limit level (optimism carried; the pessimistic next-bar-open sensitivity reported). Pre-triggered
  moments (market already through the limit at placement) are IMPOSSIBLE by construction here (the limit
  is defined relative to the placement price) — stated so the panel can check it.
- Fees identical per leg on both arms; carry from each arm's own fill bar; chains where [t, t+W+48h]
  windows overlap (M14 dedupe); eligibility ≥ W+48 forward bars at the moment level.
- Family: 3 contrasts (d = 0.25/0.5/1.0, each L−M) at z ≥ 3.0; fill rates with events/fills n;
  verdict floor fill ≥ 20% AND n_fills ≥ 1,000 per cell; per-cell MDEs before any verdict; null gate +
  positive control (linearity + 1.5× own-MDE detection) first.
- The owner-relevance bridge (descriptive only): his real limit plans' distances-in-ATR histogram from
  plans.json, so the tested d's are mapped to what he actually does.

## 3. Panel's standing questions
(a) Is L−M on the same moment free of the M15 class of by-construction contrasts (both arms share the
moment and side; L's fill conditions on an adverse excursion M already survived — does the shared-moment
differencing plus ITT control subtraction price it, or does the runner's convexity interact with the
lower fill differently in a mechanical way)? (b) The fill-bar's remaining range after a limit fill is
by construction moving against the position — stop-first handling and its optimism bound. (c) Measure
the population and fill rates per d BEFORE verdict rules freeze; DEFER if born underpowered.
(d) W = 24h — does the window choice manufacture the answer (a longer W fills more adversely by
construction)? Pre-state W sensitivity (12h/24h/48h, descriptive).
