# BACKTEST EVERYTHING — Synthesis (2026-07-02)

Four lanes, one book. Consolidated verdicts from: sizing-ladder, signal-sources, veto-rescore, adx-survivor.
Full lane reports: `coordination/BT_SIZING_LADDER.md`, `BT_SIGNAL_SOURCES.md`, `BT_VETO_RESCORE.md`, `BT_ADX_SURVIVOR.md`.

## The one-line takeaway

Every lane independently converged on the same finding: **all historical profit is the early-June bear leg** (shorts, Jun 1–9 / crash-week W23). No entry source, no ADX condition, no confidence upweight has demonstrated edge outside it. The provable alpha right now is *subtractive*: cut mid-confidence trades, restore one veto, retire dollar-negative rules.

## 1. DO NOW (ranked by evidence strength)

1. **Adopt the CUT half of the sizing ladder: 60–79 conf → 0.15x (V2 posture).** [sizing-ladder]
   Killer number: 70–79 band is **0-for-14 (−$722)**, 60–69 is 17.4% WR (−$374); robust at n=60. V2 turns the known-conf book from −$1,008 to −$67 and cuts max DD $1,008 → $127. Do NOT ship the 80+ upweight (see §2).

2. **Restore `hype_long_veto_v1` — and verify it actually survived today's regeneration.** [veto-rescore]
   Killer number: combined **~+$1,825/33d** (cf +$1,101 + $592 blocked live losses + fees). But `graduated_rules.json` regenerated 2026-07-01 17:10 does NOT contain it — the restore may have been clobbered. Rule-owner check is the single most urgent action item on this list.

3. **Retire the 12 dollar-negative active rules, starting with the contradiction clusters.** [veto-rescore]
   Killer numbers: HYPE-trend-BUY boost **−$1,120** (directly contradicts hype_long_veto), trend+SELL penalize −$826, new-today HYPE-trend-SELL penalize −$643. Also dissolve the 4 clusters where boost+veto+penalize are live on identical conditions.

4. **Do NOT graduate the ADX continuation rule; kill the A/B.** [adx-survivor]
   Killer number: ex-W23 the treatment is **−0.229R over n=59 (−13.5R total)** and underperforms its own control both in-window and OOS (n=436, CI includes 0). The "survivor" is the crash week wearing a costume.

5. **Fix `strategies_agree` stamping in counterfactual records.** [veto-rescore]
   17 of 59 rules are unmeasurable because cf records never stamp strategy agreement. Cheap instrumentation fix that unblocks the next re-score. Same family as the confidence-metadata gap in §3.

6. **Keep `sol_long_veto_v1` (minor), keep `night_session_block_v1` retired, keep `conf_floor_70_v1` retired.** [veto-rescore]
   sol_long: +$258, positive all 3 fortnights, true blocked-loser rate 67% (not the claimed 14/14). night_block: dollar-negative combined (~−$78; actual night trades made +$375). conf_floor_70: redundant with live floors (−$115 cf-only).

## 2. DO NOT (evidence says stop)

- **Do not ship the 80+ confidence upweight (1.1x/1.3x) or V3.** n=8, all SHORTs, top win = 38.6% of gross wins, 90+ multiplier fitted to n=1. V2b (cut-only, no upweight) captures ~99% of V2's gain — the boost adds nothing provable. [sizing-ladder]
- **Do not treat "conf≥80 has lift" as current fact.** Post-May: 31.2% vs 34.8% would-win, z=−0.72, n=96 — no lift. The full-corpus z=+3.6 is entirely May 30–31 BUYs. [signal-sources]
- **Do not build anything on the 70–80 counterfactual band's apparent edge.** z=+6.9 is regime-confounded: Jun 1–9 SELLs 65.4% would-win vs Jun 10–19 at 28.8%. It's bear beta, not signal quality. [signal-sources]
- **Do not add ADX (or any trend-strength) conditioning to the EMA20-pullback entry.** High-ADX conditioning makes the unconditional entry *worse*. [adx-survivor]
- **Do not restore night_session_block_v1.** [veto-rescore]
- **Do not credit any entry source with edge yet.** LLM-approved is the *worst* bucket (13.6% WR, −$990; LONGs 0/13). Mechanical no-LLM is 3/3 +$58 — n=3 is noise. [signal-sources]

## 3. Open questions (need more data, not more analysis)

- **Where did the +$1,750 come from?** 19/90 trades (21%) have zero confidence metadata (pre-fix bug) and contain ALL the real profit, incl. the Jun 2–4 giants. Ladder is validated only on the losing subset; thesis-history recovery failed (scale mismatch). Until metadata-complete trades accumulate post-fix, we cannot say whether the ladder would have cut the winners too.
- **Is there any edge outside a bear regime?** Early-era shorts: 72.7% WR +$1,601 (n=11). Everything else: 20.3% WR −$860 (n=79). Every backtest span here is one bear half-year. First sustained non-bear stretch is the real out-of-sample test.
- **EMA20-pullback residue:** unconditional +0.127R net, n=993, week-cluster CI [+0.02, +0.25] — the only weakly-real positive entry found across all four lanes. Worth a properly pre-registered forward test, not worth sizing up on yet.
- **LLM-approved LONGs 0/13:** is this a prompt/context problem, a regime problem, or a real directional-competence gap? n too small to separate; tag and watch.
- **Strategy-conditioned rules (17):** unmeasurable until the instrumentation fix (§1.5) has run for a few weeks.

## 4. Interaction with exit-geometry backtest + just-shipped fixes

- **Exit geometry is the missing multiplier on everything above.** All four lanes replayed *realized* PnL or fee-free first-touch counterfactuals — none re-simulated exits. If the exit-geometry lane finds better stop/target placement, the sizing-ladder dollar figures change (linear resize of realized PnL is exact only if exits are unchanged), and the veto-rescore dollar rankings could reshuffle since cf PnL is first-touch. **Do not lock in rule retirements #3 that are marginal (<~$150) until exit-geometry reports; the big ones (−$1,120, −$826, −$643) are safe to act on now.**
- **Sizing ladder and exit geometry compose, they don't compete.** Cut-at-60–79 reduces exposure to the trades exit geometry would be trying to salvage; if both ship, re-run the ladder replay on exit-adjusted PnL before trusting combined dollar claims.
- **Just-shipped confidence-metadata fix** is what makes the §3 open questions answerable: post-fix trades will have full conf attribution, so the ladder gets validated on winners too, and the signal-sources "unknown n=21" bucket stops growing. Same for the strategies_agree stamp once shipped — the veto re-score should be rerun on a schedule (fortnightly) rather than as a one-off.
- **The hype_long_veto restore (§1.2) must be re-verified after ANY rule-regeneration run**, including whatever the exit-geometry or fix pipelines trigger. Today's clobber shows regeneration doesn't preserve manual restores.

## Standing caveats (apply to all dollar figures)

- Counterfactual PnL: unlevered, fee-free, first-touch, skipped-signals-only selection bias.
- Sizing replay: linear resize of realized PnL; exact for the 1x era (47/90), approximate for early 1.5–5.6x leverage; no path/streak-state re-simulation.
- ADX backtest: EMA-touch limit fills optimistic; intrabar ambiguity resolved conservatively (stop-before-target); flat 0.12% RT fees.
- Dollar concentration: most cf dollars sit in the Jun 13–26 selloff fortnight; most realized profit in Jun 1–7. One regime, everywhere.
