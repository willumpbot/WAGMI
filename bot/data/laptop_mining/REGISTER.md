# REGISTER — read this before starting any work here

_Last updated 2026-10-11. **102 markdown files live in this folder.** This page is the index so none of
them has to be read speculatively. For the desktop and for future sessions — not an owner-facing doc._

---

## 1. ✅ What survived review — the only things to act on

| finding | number | where | status |
|---|---|---|---|
| **Crowded funding → bigger day, size down** | **+7.7%** vs forecast | `SIZE_FLAGS.md` | survived 4 reviewers; **live** |
| **Crowded funding → stop hit more often** | **+2.68 pp**, week t 3.04 (live definition) | `FUNDING_STOP.md` + `FUNDING_STOP_AUDIT.md` | **definition-sensitive** (t spans 1.21–3.31 across variants); live flag now matches a measured definition |
| **Don't tighten the stop** | −0.13 to −0.20R at ½× | `GEOMETRY_V3.md` | holds |
| **Funding persistence** | 83.2% → **99.3%** top quintile | `M10_AUDIT.md` | survives clustering at z=4.8 |
| **Squeeze column = stretch, not agreement** | — | `SQUEEZE_V2.md` | relabelled live |
| **Use `p95`, not `p99`, for leverage caps** | p99 is a sample max at n=68 | `M9_AUDIT.md` | **applied** (de-biased /1.15) |

**The stop-width change was deliberately NOT shipped.** The fix is 2.9% — five basis points. Size down
on crowded-funding days instead.

## 2. 🚫 DO NOT RE-OPEN — killed, with the reason

**Re-proposing any of these wastes a day. Each died for a specific, recorded reason.**

| idea | why it's dead | doc |
|---|---|---|
| Trailing-exit improvement | 3 bugs in my sim: hard stop disabled once armed, previous-bar ordering, exact-level fills | `TRAILING_EXIT.md` |
| Swap HAR → EWMA for volatility | I refuted the original against a baseline **I substituted myself**. Keep HAR | `VOLATILITY_V2.md` |
| Wider stop (×2) / target 0.5R / TIME_STOP 48h | every CI contains zero; the surviving number was an **algebraic identity** | `GEOMETRY_V3.md`, `EXITS_V2.md` |
| `volume_surge` as a sizing input | failed its own bar; 9.5% of flagged days had no volume recorded | `SIZE_FLAGS.md` |
| "The exit agent is the leak, −$721" | composition, not causation. Its closes are **+0.037R** | `EXIT_AGENT_REPLAY.md` |
| "Never close before TP1" | **23 of 29** would have hit the stop; holding costs $574 more | `EXIT_RULE_VERDICT.md` |
| Cross-sectional ranking at 1-day | fees are 0.36%/day; the shuffled null **is** the fee drag | `CROSS_SECTIONAL.md` |
| Same-asset basis carry panel | 1–2.5% annualised, costs scale with size, 5 of 21 pairs usable | `BASIS_TRADE.md` |
| `ADX_MIN_TRENDING` tuning | unmeasurable; gating at 60 discards **92.5%** of signal flow | `ADX_GATE.md` |
| Liquidation clusters as targets | two runs, **opposite** answers; pooled CI through zero | `LIQ_MAGNET_REVIEW.md` |
| Telegram caller grading | server-local by design (other people's messages). **Never request the raw data** | `CORRECTIONS.md` |
| Widening M10 to 60 coins *for precision* | +9% information for 3.8× rows; CIs would look 49% tighter | `M10_AUDIT.md` |
| The confidence floor as a lever | **inert since June** — LLM-first returns before the check | `CONF_FLOOR.md`, `LLM_PIPELINE.md` |

## 3. ⏳ Queued — and exactly what unblocks each

| work | blocked on | expected |
|---|---|---|
| **Mission A** — wider stops in the real exit engine | ~30 ledger rows with `stop_initial`/`tp1_level`; **1 of 294** today | **~60 days** at 0.5 closes/day |
| **Chief re-test** | calendar | **2026-10-16** |
| **The ~9 alive-no-trade days** | `uptime.jsonl` depth + `llm_ok` history | ~2 weeks |
| **The TP1 question** — why only 8.5% reach it | ~50 closes with the full entry fields (logging now complete) | **~100 days** at 0.5 closes/day |
| **Floor-input test** | floor PASS decisions; **0 logged** so far | unknown — floor is inert, so low value |
| **OI buildup study** | **sealed pre-registration**, n_days ≥ 106 | ~2027-03 |
| 5-day `rsi` / `stretch` cross-sectional | more data; both are **+32–43%/yr point estimates that are unresolved, not zero** | revisit at 2× sample |

**`exit_engine.py` is built and passes 13/13 self-tests.** It runs the day Mission A's data lands.
**`PREREG_OI_2026-10-11.md` is sealed** — SHA-256 `ef8da63d8036737c29544e6b9ecd5935b2112e48000e0103784ec83a6dd4fe13`. Do not look early.

## 4. 🔧 Open asks to the desktop

1. **Populate `would_pass_confidence_floor`.** Because the floor is inert, its recorded verdict is an
   **unselected prediction** — a gate normally can't be evaluated because it removes what you'd measure.
   This one doesn't act, so the counterfactual is free. Cheapest high-value field available.
2. ~~**`scanner.py` in the export**~~ — **DELIVERED 2026-10-11, and it immediately downgraded a
   finding.** The live `funding_hot` was a different condition from the one two studies had measured
   from its docstring. This is the single highest-return ask of the project.
3. ~~**The empty entry columns**~~ — **DONE 2026-10-11** (`45f7f427`). One real bug
   (`compound_size_multiplier` — the close handler read a cache only the mechanical path fills, so
   LLM-first entries never set it), one look-ahead trap (`kelly_weight_applied` was computed **at
   close**; old values are meaningless), two that were era-limited rather than broken.
4. ~~**`sl_bps`/`tp_bps` on resolved dropped rows**~~ — **DONE** since `82eb3151`.

**🔴 All four asks are closed. The bottleneck is no longer data collection — it is the trade rate.**
Sep–Oct ran **19 closes in 40 days (~0.5/day)**, so every forward-looking study is a **two-to-three
month** wait. Plan around that; do not check weekly.

## 5. ⚠️ The failure patterns — every reversal here was one of these five

**Twelve-plus conclusions have been overturned. Not one was a fabrication; all five patterns are
the same thing — "confidence outrunning evidence."**

| pattern | instances | the guard |
|---|---|---|
| **A test that could not fail** | side-flip null algebraically incapable; `h0 = ds - ds.mean()` pinning the mean then testing it; a power table that was an identity; `feeR = feeR(1)/m` positive by construction | **Ask: could this ever have come out negative?** |
| **Era confound** | `REAL_LEDGER` exit paths; long/short gap; confidence floor (score didn't exist before July); gate failure rate | **Cut by month before believing anything pooled** |
| **Absence read as evidence** | floor log "stopped"; 23 silent days; `scan_log` 3 days; uptime 61 min "stale" — **all rotation, rolling windows or sync cadence** | **Prefer files that never rotate; pick thresholds from the cadence** |
| **Unstated power** | nulls with MDEs of **90–128%/yr** reported as "nothing survived"; a p99 that was a sample max | **State the MDE before the verdict, every time** |
| **Tie mass under a threshold** | `funding_hot` as `>= quantile(0.80)` swallowed the 18.6% of coin-days parked at Hyperliquid's default funding rate — flagging ~85% of the live cross-section | **Check for repeated values before thresholding; use `>` on anything with a platform default** |

| **A label is not a provenance** | `kelly_weight_applied` sat among the entry fields and was **computed at close**. I filed it as "an empty entry column" and only avoided a look-ahead bug because it was blank on 290 of 294 rows | **Confirm the write site, not the schema** |

**Three more rules earned the hard way:**
- **Never test a production flag from its description.** Read the implementation or say you could not.
  Two studies measured `funding_hot` from a docstring; the live code was a different condition.
- **Never convert a mean-level effect into a threshold-level action analytically.** Solve the threshold
  on the data — assuming linearity over-corrected by **2.7×** on the funding stop.
- **A zero exit code is not evidence of success.** Check the side effect. (The owner's clip queue sat
  dead 74 days behind a crash that exited 0.)

## 6. The honest bottom line

**No directional edge has ever been demonstrated here** — ~98 tests, though the honest phrasing is
*"none finding an edge large enough to clear detection floors that mostly sit above 90% annualised."*
Everything that survived is about **magnitude and sizing**, not direction.

**The bot is flat by design and that is correct.** 0 of 22 groupings of currently-blocked proposals
clears a credible bar — and nothing proves they lose either; the figure that looked like proof was two
days of market drift. **Flat by decision asymmetry, revisit in ~8 weeks.**

**The highest-value findings of 2026-10-11 were not statistical.** Three silent failures: a clip queue
dead 74 days, a bot dead 3.3 days with the alert never delivered, and an expired login that made
trading impossible while every health check read fine. All now fixed or alarmed.
