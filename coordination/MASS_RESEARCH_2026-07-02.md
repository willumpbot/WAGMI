# MASS RESEARCH SYNTHESIS — 2026-07-02
8 lanes, all committed, all scoped. Ranked by decision-weight. Full evidence in the per-lane reports; this page is the index and the verdicts.

Lane reports: RQ_MULTIYEAR_SIM.md, RQ16_20_RISK_MATH.md, RQ12_SYMBOL_PERSONALITY.md, RQ11_SESSIONS.md, RQ14_CF_MODEL.md, RQ13_LEAD_LAG.md, RQ15_THESIS_FORENSICS.md, RQ21_ARCHIVE_MINING.md.

## 1. WHAT WE NOW KNOW (ranked)

1. **Restored S3 exit geometry is structural, not era-luck** — beat current live geometry AND a naive SL/TP control in every year, half, symbol, and side over 2.5 years. n=1,131 identical dumb entries; RESTORED +91.7R (t=3.80, WR 78%, maxDD 13.1R) vs CURRENT −65.0R vs NAIVE −133.5R; +0.139R/trade value-add, DD cut 5.5×. Honest shape: 78%-WR scratch machine (avg win +0.41R vs loss −1.08R), not a runner-catcher. [multi-year-sim]
2. **Leverage above ~2x buys ruin with ZERO median growth** — 10k-path block-bootstrap MC: 2x→5x median final is flat ($2,235→$2,257) while P(ruin) goes 2.8%→65%. Mean R is only +0.031 even S3-restored (−0.082 on the Jun7+ entry mix — Kelly says 0x there). Current 1%/trade ≈ quarter-Kelly of the BEST measured distribution. [risk-math]
3. **Loss streaks are real clustering, not bad luck** — runs-test p=0.012; WR after a loss 20% vs 46% after a win; no session/symbol pocket — it's temporal. The fix is after-loss de-sizing, not filtering. [risk-math]
4. **Confidence floors have ~zero rank signal** — test AUC 0.516; TP1-by-decile non-monotone (46-49 band 10.4% > top decile 9.0%). They throttle volume; they don't select winners. A simple logistic beats base (AUC 0.616, TP1 37.5% vs 9.5% at ~2/day, p=2e-5) but NOT confidence head-to-head (Fisher p=0.13–0.27) — no graduation. [cf-model]
5. **Thesis quality is legible in the text** — composite checklist score≥2 → 74% right (48/65) vs ≤0 → 37% (15/41), monotonic, both eras. Fresh numeric market target 64% vs 37%; ≤25 words monotonic 66%→41%. QB anti-signal confirmed with nuance: bare "validated" is fine (59%); small-n/session NUMBERS are the toxin. [thesis-forensics]
6. **Winners don't breathe** — 26/36 winners had ZERO adverse excursion before peak (15m replay, 156 trades). HYPE doesn't pay: 29 trades, 17% WR, −$914, negative in both eras and every grid cell; HYPE-LONG 1/13 qualifies for the n≥13 data-learned veto. LLM_EXIT_AGENT −$1,535/85 vs TRAILING_STOP +$1,268/16. Per-trade expectancy fee-adj negative for ALL 5 symbols — the +$959 book P&L is size skew. [symbol-personality]
7. **No session is a real dollar edge** — only positive session (US 12-18, +$729/34) is ONE trade: remove the Jun-3 $1,010 winner → −$281, and it flipped to −$64 in era 2. Skipped signals lose in all 4 sessions post-Jun-16 (12/12 cells negative) — the night block's "savings" were generic selectivity, not the clock. Side-find: trades.csv is missing 54 trades (~+$695 optimistic bias) — use trade_ledger.csv. [session-structure]
8. **BTC→alt lead-lag at 1-6h does not exist** — all lagged |r| ≤ 0.057 across 4,980 hourly bars; alts overshoot BTC inside the same bar (contemporaneous r 0.55–0.90). Tradeable residue after 12bps fees: zero. Scout claim rejected. [lead-lag]
9. **The archive's cross-era patterns** — trend-shorts edge (SHORT +$1,441/61 vs LONG −$690/27), HYPE LONG toxic in every era (12–23% WR), conf 60–79 = anti-signal (70–79 → 0% WR n=14), skip quality 86%. Two contaminated instruments poison most archive stats: shadow-ledger expiry bias (7,245/8,714 expired) and the counterfactual applied/correct bug. The 82 frozen A/B rules' primary data is PURGED — quotes only. Sniper was April's only live-profitable path (+$328/34); sim WR replicates (62.7%, n=59) but PF 1.02 — exit geometry eats the edge. [archive-mining]

## 2. WHAT DIED (killed hypotheses — logged as wins)

- **BTC→alt lead-lag (Q13)**: KILL. Noise at every lag; only residue (HYPE fade) sign-flips across eras (E1 t=−3.2 → E3 t=+2.0). [RQ13]
- **night_session_block as session-specific (Q11)**: kill stays killed (already active:false). Derivation-era night skips were the BEST counterfactual cell. "Night is dead" premise factually wrong — EU 06-12 is the quiet window, US 12-18 the loud one (12/12 cells). [RQ11]
- **Confidence floors as winner-selectors (Q14)**: AUC 0.516 ≈ coin flip. GBM overfits (0.507). [RQ14]
- **"Filter the streak session/symbol" (Q16)**: streaks are proportional across all — temporal, not located. [RQ16_20]
- **Exit geometry as standalone alpha**: worst-case intra-candle ordering drops S3 to +30.6R, t=1.25 (2024 → −2.4R). Direction robust; alpha claim not. [MULTIYEAR]
- **Any exit-geometry grid cell as alpha (Q12)**: all best combos negative after fragility check; SOL k=0.5 cell (+0.7pp) fragile. [RQ12]
- **Thesis features that DON'T predict (Q15)**: stated-invalidation (6/12), timeframe-cited (undiscriminating), ADX-token (57/57 null), hedging language (unmeasurable n). [RQ15]
- **Archive kills (Q21)**: confidence_60_70_sweet_spot; stat-citing prompts (48% vs 57%, both "validated edge" citations in worst-10); post-crash breakdown chasing; INSTANT_SL_stop_buffer (11% WR). [RQ21]
- **Leverage >2x under any current distribution**: 3x = 20.5% ruin even on the forward assumption; 4-5x = 44–65% under the OPTIMISTIC dist. [RQ16_20]

## 3. ACTIONABLE UNDER THE_STANDARD v1.1

### Ship-eligible (validated + reversible — ship autonomously, watch window, report)
1. **Restore S3 exit geometry live** — every-year/symbol/side win, adversarially checked, config-flag reversible. This is also the risk-math prerequisite for ever earning 2x. Watch window: 15-20 closes. [MULTIYEAR + RQ16_20]
2. **After-loss de-sizing** — risk-reducing-only (cut-only ladder), post-loss WR 20% vs 46%, p=0.012. Ships on backtest + flag per §2. [RQ16_20]
3. **HYPE-LONG data-learned veto** — 1/13, −$916, dollar-negative in both eras on the current ledger; meets §2b n≥13 + dollar re-validation. Reversible rule entry. [RQ12, corroborated RQ21 across 3 eras]
4. **Re-point all analyses at trade_ledger.csv** — trades.csv missing 54 trades (+$695 optimistic bias); audit signal_quality by_session tracker. Measurement fix = autonomous per §2. [RQ11]
5. **Thesis prompt A/B (auto-retire)** — inject: fresh numeric market target required, ≤25 words, cross-asset confirmation; ban: numeric QB-stat citations, session/UTC-hour edge language, "holds/continues" continuation theses, self-referential "to TP1/TP2" targets. In-sample upper bound → ships only as A/B with auto-retire, which §2 allows. [RQ15]

### Owner-gated (per v1.1 narrowed set)
- **CB re-key onto loss streaks / rolling-R** instead of per-trade — correct per MULTIYEAR failure mode (−1R clustering, 10–15R rolling DD), but CB changes reach the owner first. Proposal, not ship.
- **Any leverage step to 2x** — gate defined below; not evidenced yet.

### Needs-more-data
- **2x leverage**: requires S3 geometry live + n≥30 live trades mean R ≥ +0.10, WR ≥55%, survives drop-best. [RQ16_20]
- **CF logistic model**: beats base, not confidence head-to-head (p=0.13–0.27); era shift 4x between train/test. NO deployment; re-test after more clean closes. [RQ14]
- **Sniper re-enable**: only after exit-geometry fix AND sim PF ≥1.3 over 20 trades; verify 5x cap (old −$147 ran at 9.7x). [RQ21]
- **Archive revivals** (high-ADX ETH/BTC short boost, conf≥80 sizing gate, night-block re-test, BTC-only BB-squeeze short 74%/n=68 — NOT symmetric, ETH 6%): each has required-evidence spec in RQ21. [RQ21]
- **Tight stops (0.75×ATR1h) + 4–8h hold caps**: halve bleed everywhere but create no alpha; superseded by S3 restore — re-examine on post-restore data. [RQ12]
- **XRP personality**: n=10, no verdict. [RQ12]

## 4. LEVERAGE-RAMP TABLE (risk-math, verbatim)

| Step | Risk/trade | Gate (all required) | MC basis |
|---|---|---|---|
| **1x — NOW** | 1% | none; this is ~quarter-Kelly of the *best* measured dist | ruin ≤0.5% even pessimistic |
| **2x** | 2% | (1) S3-style lock geometry live; (2) **n≥30 live trades, mean R ≥ +0.10** and WR ≥55%; (3) survives drop-best-trade; (4) owner accepts P(25%DD)≈57% | S3 fwd ruin 2.8%, pess 30% — gate exists to kill the pess branch |
| **3x** | 3% | n≥60 live at 2x with mean R ≥ +0.20, era-split positive both halves, streak-aware de-sizing live (Part A autocorr) | ruin 20.5% under today's fwd dist = NOT justified by any current evidence |
| **4x–5x** | 4-5% | n≥100 with mean R ≥ +0.30; re-run this MC on the live distribution first | today: 44-65% ruin under the OPTIMISTIC dist — unreachable |

Bottom line (risk-math): the path back to bigger positions is not a leverage decision, it is a **mean-R decision**. Fix expectancy (exit geometry restore + entry mix), collect 30 honest trades, and 2x self-justifies.
