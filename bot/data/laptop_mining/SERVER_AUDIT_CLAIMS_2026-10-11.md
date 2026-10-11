# Server audit: every owner-facing claim in the terminal, and whether it is graded forward (2026-10-11)

This was a read-only audit. No code was changed. Data was read at about 19:25Z on 10-11.

The principle being checked: every claim shown to the owner should either be graded forward automatically, or be clearly labelled as untested.

**Headline:**
- **Forward grades exist for some claims but none of them reach the owner.** `scan_grades.json`, `voice_grades` live, `chief_scorecard` 1d, `ai_stats` Brier and `geometry_shadow` are all computed. But every FLAGS tooltip is static text from `scanner.py:27-53`. `desk.py:306-318` never puts `scan_grades.json` into `DATA`. When a grade turns, the wording on screen will not change.
- **The scan grader cannot test most of the wording it sits under.**
  - Only `ma50_pullback` (long) and `on_20d_low` (short) are signed (`scan_grader.py:25`).
  - Every other flag is graded as the mean of |coin − universe median| (`scan_grader.py:109`). That number has no baseline and no forecast to compare against, so it measures nothing the tooltips claim.
  - `momentum_small` is graded unsigned, so the "falls back" claim can never be confirmed or refuted.
  - `funding_hot` claims a higher stop-hit rate, but it is graded on |excess move|.
  - The bootstrap CI is per row, not clustered by day (`scan_grader.py:66`). Example: funding_cold has 69 rows from 4 days.

## Scanner flags: tooltip vs `scan_grades.json` (1d only; the first 5d rows are due 10-13)

| Flag (scanner.py line) | Tooltip claims | Forward graded? | n (1d) | Current result | Wording still honest? | Fix |
|---|---|---|---|---|---|---|
| ma50_pullback (28) | "no edge, random dates did as well" (724 cases) | Yes, signed long, minus 9 bps fee | 33 (9 coins, 4 days) | mean +0.05%, CI [−0.59, +0.72], hit 42%, "collecting" | **Yes.** Forward agrees: no edge. | Cluster the CI by day. Show the forward n and mean in the tooltip. |
| on_20d_low (31) | "low breaks more than chance; as a short, too few cases"; label `untested` | Yes, signed short | 8 (about 3 days) | +0.79%, CI [−0.08, +1.59], hit 62% | **Yes.** It says untested and n is tiny. | Same. Also grade the break itself: did the 20d low break within 1 day, vs a random line at the same distance (use ctx_snapshots marks). |
| vol_expanding (34) | "Expected move already includes this (+1%, t=0.24): use the expected move instead." | Unsigned \|excess\| only | 9 | mean \|excess\| 3.86%, no baseline | **No.** The SIZE_FLAGS red team refuted argument (c). Row-weighted within-cell is −8.1% (t −2.37, smaller moves), and `rv22 > median` beats it. Forward data cannot speak to the claim. | Reword: "Untested as a size signal; red team found a possible opposite effect." Grade realized \|1d ret\| / exp_move against same-day unflagged coins. |
| funding_hot (37) | "stop hit +2.7 pts (~24% vs ~22%), t=3.0, 1,010 days, exactly this definition"; evidence `tested` (green chip, sorts first) | Yes, but on \|excess\| (wrong metric) | 18 | mean \|excess\| 6.8%, CI [2.6, 12.4], no baseline | **Partly.** The definition now matches FUNDING_STOP (top quintile, strictly above; FUNDING_STOP_AUDIT §4). The forward test does not check stop-hit at all. The green "tested" chip implies more than a +2 pt effect deserves. | Grade the claim itself. For each flagged coin-day and every unflagged one, check whether the low (for longs) or high (for shorts) breached 1.65×exp_move within 24h. Use the 1h candles scan_grader already fetches. Report the difference in pts, clustered by day. |
| funding_cold (41) | "Context only" | Unsigned | 69 | 2.5% | Yes (claims nothing) | Stop grading it, or grade it like funding_hot. |
| volume_surge (42) | "next day ~12% bigger than forecast, failed the red team's bar (p=0.027 vs 0.025)" | Unsigned \|excess\| | 25 | 9.2%, CI [6.1, 12.8], no baseline | **Mostly.** But SIZE_FLAGS says "PULL it from the terminal", and lessons.json lists "Volume surge as a sizing signal" as DEAD. It still appears as a "setup" in the left "Scanner now" panel (`terminal.html:971` hides only funding_cold and momentum_small). | Hide it in setupsNow, or grade realized/exp_move vs unflagged so the 12% can come back. |
| squeeze (44) | "breakout direction not predictable" | Logged when it fires | **0** (it never fired in 4 days) | n/a | Unverifiable so far | Fine. Grade the sign of the next \|move\| vs the breakout side once it fires. |
| momentum_small (46) | "Tested on 164 coins (M2 corrected): FALL BACK vs other small caps 1-7d, more the further above the high. Don't chase long." | Logged, **unsigned**, benchmark = median of the top-60 universe including majors | 5 logged, 0 resolved | none | **Direction matches the laptop's correction, but it overclaims as a test.** (1) PREREG_SMALLCAP_FADE says the in-sample result "was found by exploration… nothing in §4 is acted on", yet milestones.json:245 marks it `proven`. (2) The live definition is not the one tested (see note A). (3) The grader would score a −15% fade as +15% "size". | Add `"momentum_small": -1` to SIGN. Benchmark against same-day non-breakout coins ranked below 15 by volume. Add a 3d horizon. Label it "in-sample finding, forward test sealed 10-11". |
| above_20d_high (51) | "the 20-day high meant nothing either way" | Unsigned | 7 | 14.2%, CI [5.9, 26.5] | Claim is consistent with LEVELS (hi20 beats_null False). The forward number is meaningless (n=7, mostly STRK). | Grade it signed long, two-sided, so "nothing either way" can actually fail. |

**Note A: three definitions of "small-cap breakout" disagree.**
- **The scanner flag** (`scanner.py:184-186`): coins ranked 16-60 by 24h volume within the top-60 scanned. Price is above the 20d high (an intraday high) AND (vol_ratio > 2 OR the 24h move is more than 1.5× the expected move).
- **The planner warning** (`terminal.html:579`): vol_rank > 15 and price above the 20d high, at any distance, with no volume condition.
- **The tested and preregistered definition**: close at least 4% above the maximum close of the prior 480h, among all ~169 HL perps outside the top 15 by trailing 20d volume. The benchmark is the same-hour non-breakout cross-section, with funding subtracted.

The live flag covers a different population: mid caps 16-60, not the tested ~150 small caps.

## All other owner-facing claims

| Claim (terminal.html line) | What it says | Graded forward? (where, n, result) | Wording still honest? | Fix / cheap grading |
|---|---|---|---|---|
| Exp. move ±x% (351, 1169, Lab 817; milestone 10-08 "proven") | "Size IS predictable, 22/22 test periods" | **No.** Historical walk-forward only. The forecast value is not logged anywhere. scan_log stores px only; voice_log has no vol. | Yes historically, but never checked live | Log `exp_move` per coin per day (scan.json already computes it for 57 coins). Grade QLIKE vs the naive rv5 next day using HL 1d candles. About 20 lines of code. |
| Safe lev L/S (352, 1171, 797; planner warnings 576, 856) | "Above this a 1-in-100 bad day liquidates you"; "13k coin-days, held out of sample" | **No.** | Board value is de-biased /1.15 (300). **The scanner column (953) is not de-biased** and uses a different method (365-day open-to-low p99 /1.5). The same coin shows two different "safe" numbers. | Apply `/SAFE_LEV_DEBIAS` in renderScan, or relabel it "rough". Grade: count days where the adverse 1d move went past the liquidation distance implied by safe lev (expected ≤1%). Use ctx_snapshots marks (15-min) or HL 1h candles. |
| Squeeze L/S % (353, 1172) | Tooltip: "SQUEEZE_V2: driven by how stretched the coin is, **not by voices agreeing**" | **No.** | **No: the tooltip is factually wrong.** `assemble.py:321-331` computes the V1 `"+ consensus"` model from squeeze.json (inputs: log forecast + voice dissent). squeeze_v2.json is not on the server. | Either wire V2 or change the tooltip to "V1 (consensus) model". Log `squeeze_pct` daily and grade the Brier score for "adverse > 2×exp_move within 1d" vs base_rate_test, using 1h candles. |
| Top traders L/S (354) | "no track record yet" | **Yes, pending.** `top_traders` is in voice_log (1,818 rows); live grading starts about 10-13. | Yes, but the text is static and will go stale | Read the trust and n from voice_grades. |
| Voices agree / "Bigger move expected" filter (360, 1176, 1185; chief SYSTEM chief.py:38-40) | Tooltip: link to bigger moves is "+4%, small and unproven". Filter label: "Bigger move expected". Chief prompt: "~5% vs ~3%". | **No.** consensus.move_size is not logged. | **No.** The filter label and the chief prompt state as fact what the tooltip calls unproven. The chief prompt still carries the old ~5% vs ~3% claim. | Rename the filter to "Voices aligned (untested)". Update chief.py:38-40. Log move_size per coin-day and grade realized \|1d\|/exp_move by bucket. |
| Hist 5D ▲ % (359, Calls tab "Next 5 days") | Up% coloured blue/red at 55/45 | **Yes, pending.** `history_5d` voice logged (1,930 rows), 5d grading from about 10-13 | Colour implies direction while n_eff is small | Grey it unless voice_grades says earned. |
| Chief lean + conviction (361, 592, 1157, 1177) | Directional pill | Partly. chief_scorecard: 1d n=86, **n_directional 0**; 5d n=0. All 122 chief calls are NEUTRAL (110 at conv 1, 12 at conv 2, breaking the conv≥2 rule). | The card text "0 calls graded at 5d, still collecting" (desk.py:299) hides that the chief has never taken a side | Show "122 calls, 0 directional" plus the Brier score once n is enough. |
| Chief p_up_24h (chief.py:54) | Brier-scored | Wired, n=0 so far | n/a (not displayed) | Display it at n≥30, with skill vs 0.25. |
| Chief expected_move_pct (chief.py:58) | Prompt says it "is compared against the HAR forecast" | **No.** `resolve()` (chief.py:140-188) never compares it | **No.** The prompt promises grading that does not exist. | Add MAE / QLIKE of the chief's number vs HAR vs realized \|ret_1d\| in resolve(). Both are already in chief_calls. |
| Chief neutral_quiet_rate 0.977 (scorecard) | "neutral was right" | Computed | Trivial bar: \|1d\| ≤ 1 ATR happens most days anyway | Compare against the unconditional rate, or drop it. |
| Levels tab per-level verdict + "✔ holds" near-level chip + Situation tooltip (331, 512, 845, 1173) | 50d avg "held more than chance"; Situation: "the 50d avg holds from above" | **No.** Static LEVELS.md 2020-26 numbers. | **No.** It was measured on the **SMA**, but the terminal draws the **EMA** (ch.ema50). MISSIONS_REVISED: the SMA effect decayed from −9.4 pts pre-2024 to −2.1 pts since, with a CI that covers the null. The Lab card (820) already says "mostly gone"; the Levels tab, near chips and Situation still say "holds". | Drop "holds" for ma50, or say "pre-2024 effect, mostly gone". Grade cheaply: detect touches of hi20/lo20/ema50 in ctx_snapshots 15-min marks and compare break rate vs a random line at the same distance. |
| lo20 "broke more than chance (weak evidence)" | same | **No** | OK (labelled weak) | Same touch grader. |
| Planner "funding_hot" warning (578) | "stop got hit +2 points" | **No** (see funding_hot) | OK, matches laptop | Graded by the funding_hot stop-hit fix above. |
| Planner small-cap warning (579-580) | "Tested on 164 coins… about −15% in 3 days" | **No** | **No.** Different definition (note A). The −15% is an exploratory in-sample number the prereg says not to act on. | Say "in-sample, forward test running". Align it with the flag definition. |
| Planner "stop tighter than a normal day got hit a lot" (581), "Survivable setup ✔" (585), myPosWarn (860) | Geometry | Yes. geometry_shadow: n=360 signals / **21 days**; current −0.361R vs 2× forecast −0.112R, paired +0.249 CI [0.09, 0.36], "confirmed live" | Direction yes. The CI is per signal, so "confirmed" is strong for 21 days. | Cluster by day before calling it "confirmed". |
| Lab "hidden filter is RIGHT" (825) + milestone 10-09 | IC-dropped signals would lose | Yes, live_scorecard ic_muted_drops n=370, −24.6 bps, hit 33% | Yes | Cluster by day. |
| Lab "0/98", "no scanner setup has an edge", "liq clusters ≈0" (815-823) | refutations | Static | Yes (consistent with scan_grades) | Pull the forward n from scan_grades into the scanner card. |
| Playbook cards (790-802), hidden (`display:none`, 229) | "50d is real support", "2× stop, TP at half, 48h", "tight stops lost ~0.4R" | n/a | **No** (withdrawn recipe, decayed level) | Delete it so it cannot resurface. |
| Syndicate Claude verdict pill + ✔/✖ (1112) | runner / coin flip / avoid with p_15x; ✔ when it ran 1.5x | Yes. ai_verdict_log n=1 (a v1 "avoid" that **ran 1.5x**); 7/7 v1 labels were "avoid" vs a 62% chat base rate; Brier for v2 n=0 | **UI bug:** ✔ means "it ran", not "the verdict was right". "avoid ✔" reads as correct when it was wrong. | Show ✔ only when the verdict matched the outcome, or show "ran 1.5x: yes/no". |
| Syndicate verdict stats header (1108) | "avoid: 1/1 hit 1.5x" | Yes | Shows no Brier and no base rate | Show Brier vs 0.236 (constant 62%) at n≥30. Fix the tg_track docstring: it says "2x", the display says 1.5x. |
| Caller ★ watch + tooltip "Since tracking: X of Y hit 1.5x" (1103) | Post-hoc stars, "being confirmed on new calls" | Partly. `fwd_*` is rebuilt every run from the **7-day rolling window** (tg_track.py:345-351). It includes calls before the prereg and calls still running, so it is not a cumulative ledger. Now: stars 4/12 = 33% vs chat base 62%. | **No.** "Since tracking" is wrong: the count is the last 7 days and resets. CALLER_15X_PREREG's 15-call verdict will never be computed automatically. | Add a persistent per-caller forward ledger from 2026-10-10 21:00Z, matured at 7 days, scoring the prereg rule. |
| Brief "Rule that historically worked: sell all at 1.5×" (1068) | The rule works | Forward prereg running (see above) | **Overclaims.** It was picked post-hoc from 16 exit rules (+2.4%/call in-sample). Milestone 10-09 says following every call loses (median −53% under the strict rule). | Say "best of 16 rules in hindsight; forward test running". |
| Claude trade ideas track record (1005) | graded like plans | Yes (ai_plans.json): 3 ideas, 0 finished | Yes | none |
| Bot second opinion take/skip (901-908), bot paper-trades plan | graded side by side | Yes, plans.json by_review / by_exec: n=0 | Yes | none |
| Owner calls card (750) | graded 1d/5d | owner_scorecard.json does not exist yet; shows "no graded calls yet" | Yes | none |
| Voices tab trust pills (519) | earned / promising / backwards / unproven | History grades only (live pending). **"promising" = mean > 0 with CI far across zero** (e.g. structure +29.9 bps, CI [−34.5, +91.6]) | **No.** "promising" in blue is a test that couldn't fail | Rename to "unproven (+)". Reserve colour for earned and backwards. |
| Rules chips "earned/testing" (522) | rule status | Yes, rules manager: 5 testing, 0 earned | Yes | none |
| Context chips "book supports / BTC with" (524-525, green/red) | Implies a directional tailwind | `book` and `btc` are in voice_log, live grading pending | Colour implies an edge not yet shown | Neutral colour until graded. |
| History tab "What we know for sure" (1079) ← milestones.json `proven` | Includes "Crowded longs = bigger days ~7-8%" (161) and "Don't chase small-cap breakouts" (245) | Neither is forward-graded (see funding_hot / momentum_small) | 245: **no** (prereg says exploratory). 161: consistent with the current definition, but not forward-graded. | Add a `forward_status` field to milestones and show "in-sample" vs "forward-confirmed". |
| lessons.json DEAD "Small-cap momentum… about −4% in 3 days, −15% when 8%+ above" | Same as above | n/a | The tooltip says only −15%; the lesson says −4% overall. Consistent, but exploratory. | Same label. |
| Memecard risk flags, "Suggested stop distance", "Max position (≤2% slip)" (626-636) | Heuristics, computed | No | Not labelled as untested | Add "heuristic, untested". Slippage could be checked against later quotes. |
| Descriptive items: funding colour, OI, liq clusters (7d), order-book imbalance, weather/breadth, bot positions, journal | Measurements | n/a | OK, no predictive claim | none |

## Top 5 fixes, ranked

1. **Make the scan grader test the claims actually shown** (`scan_grader.py:25,109`).
   - Sign `momentum_small` −1 and benchmark it against same-day non-top-15 non-breakouts.
   - Give `above_20d_high` a signed two-sided test.
   - Grade `funding_hot` on stop-breach rate vs unflagged coins: did the 24h low/high cross 1.65×exp_move? The 1h candles are already fetched.
   - Grade `volume_surge` and `vol_expanding` on realized\|ret\|/exp_move vs unflagged.
   - This needs one extra line per cycle: log every scanned coin's {px, exp_move, flags, vol_rank} in scan_log, not only the flagged ones.
   - Cluster the CI by day. Today's 300-row "earned" bar would fall after about 12 days of funding_cold.
2. **Surface the grades and stop writing verdicts as static text.**
   - Add `scan_grades.json` to `DATA` (desk.py:306).
   - Render each FLAGS tooltip as wording plus "forward: n=…, result …, verdict …".
   - Drop the green "tested" chip and the sort boost for any flag whose forward grade is `backwards`.
   - Do the same for top_traders and voice trust.
3. **Fix the three factually wrong labels now:**
   - The Squeeze tooltip says V2, but the V1 consensus model runs (terminal.html:353 vs assemble.py:328).
   - The ma50 "holds" text in the Levels tab, near chips and Situation (331/845/1173) was measured on the SMA, has decayed since 2024, and is drawn on the EMA.
   - The Syndicate ✔/✖ (1112) shows the outcome, not whether the verdict was correct.
4. **Line the small-cap claim up with its test.**
   - Use one definition for the flag (scanner.py:184), the planner warning (terminal.html:579) and the prereg.
   - Change milestones.json:245 from `proven` to "in-sample, forward test sealed 10-11". Keep "don't chase longs"; drop the −15% figure until PREREG_SMALLCAP_FADE resolves.
   - Make that prereg's forward computation automatic. It is a strong candidate to build on ctx_snapshots, which has every perp every 15 minutes since 10-10.
5. **Log and grade the numbers the owner actually sizes with.**
   - Exp. move (QLIKE vs naive, daily).
   - Safe-lev breach rate (expect ≤1%).
   - Squeeze Brier.
   - Chief expected_move_pct vs HAR (the prompt promises this and the code does not do it).
   - A cumulative Syndicate caller forward ledger, replacing the 7-day rolling `fwd_*`.
   - Also de-bias the scanner's safe-lev column (terminal.html:953) so it matches the board.
