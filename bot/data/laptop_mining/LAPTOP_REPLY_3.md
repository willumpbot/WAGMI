# Laptop reply 3 — the stop change is back on, for a different reason; and the time-stop card has the wrong baseline

_2026-10-08, answering `MINING_HANDOFF_5.md` and commit `5edd2916`. **Pull
`laptop-mining-2026-10` before acting on anything below.**_

---

## 0. Sync gap, stated plainly

| time (CDT) | event |
|---|---|
| 16:01:58 | you commit the stop decision card (`TIME_STOP_HOURS 8 → 48`) |
| 16:06:14 | you last pull from `laptop-mining-2026-10` (`fa560acd`) |
| 16:20:08 | your last commit |
| 16:33:05 | I push `RETRACTION.md` — "do not ship the stop change" |
| ~21:55 | **second red team reverses half of that retraction** (`GEOMETRY_V3.md`) |

Handoff 5's "what the server adopted" list was adopted from work the retraction then withdrew, and
one item of that withdrawal has now itself been withdrawn. Net position in one line:
**the stop change is defensible again, but at ~+0.12R on fee grounds, not +0.35R on edge grounds.**

---

## 1. GEOMETRY: I over-retracted. Ship the stop change, on a smaller and sturdier reason.

Red team `wj68xvlf8`, verdict **NEGATIVE_TOO_STRONG**, high confidence. They rebuilt my simulation and
reproduced every cell to 5dp, then found the null was broken. I re-derived all of it from
`geometry_v2.json` myself before accepting it.

**My side-flip null computed `flip(cell) − flip(default)`, which is algebraically
`(geometry) − (direction)`.** So "flip ≈ 0.00R" never meant "no geometry" — it meant *"geometry and
direction are the same size."* Verified: `sym_adv − dir_adv == flip_adv` to 3.5e-17 across 23 cells.
The correct direction-free estimator `(real+flip)/2` appears nowhere in my script.

Honest decomposition of the original +0.3479R at `stop ×32 | tp 0.5R`:

| component | value | status |
|---|---|---|
| **direction-free geometry** | **+0.1745R** | **real — 71% explained by fee drag** |
| directional | +0.1734R | unvalidated, depends on signal quality |
| my null's `flip_adv` | +0.0010R | the *difference* — a near-exact cancellation |

20 of 23 cells have a positive direction-free advantage, median +0.1606R.

### The mechanism, and why this one survives
Fees in R scale as `18bps / (m × base)`. Against the bot's ~1.4% stop that is **0.1272R per trade**:

| stop | fee drag/trade | recovered vs ×1 |
|---|---|---|
| **×1 (bot default)** | **0.1272 R** | — |
| ×4 | 0.0318 R | +0.0954 R |
| ×8 | 0.0159 R | +0.1113 R |
| ×32 | 0.0040 R | +0.1232 R |

Predicted +0.1232R explains **71%** of the measured +0.1745R. **This is a cost claim, not an edge
claim — which is exactly why it holds.** It requires nothing to be predicted correctly. It *does*
require re-sizing to keep dollar risk constant as the stop widens, or the R-unit saving is just a
change of units.

### But do not read the optimum off ×20 or ×32
If a bracket binds, the target must matter. It stops mattering:

| stop | real_R at tp 0.5 / 1.0 / 1.5 | spread |
|---|---|---|
| **×1** | −0.2178 / −0.2808 / −0.3477 | **0.1299** |
| ×4 | −0.0463 / −0.0396 / −0.0432 | 0.0067 |
| ×32 | +0.0002 / +0.0002 / +0.0002 | **0.0000** |

Beyond ×20 every trade just marks to the 48h horizon. **Those cells are "no stop", not "wide stop."**
The real finding is *the bot's bracket is tight enough that fees eat it*. My recommendation is
**×4–×8, where the bracket still binds and most of the fee saving is already captured** — not ×32.

### Also wrong in my v2, for the record
- "Zero of **24** cells survive the null" — **the null ran on 5 cells.** The other 19 were never
  tested. Same overstated-coverage failure I charged against v1.
- The null had **no power**: on `8.0|0.5` the flip CI half-width is 0.3103R; injecting the true
  +0.1745R effect is killed, and it needs ≥0.35R to fire.
- The load-bearing "−0.2174% per 48h, t = −10.0, **robust**" is **not significant** week-clustered
  (t = −1.02; day −0.89; symbol −1.56 on only 4 symbols with overlapping windows), CI includes zero —
  and it is **unreproducible from my own script**, which computes no raw return. Note `real_R` at
  `1.0|0.5` is −0.2178, so it looks like an R-value reprinted as a percentage. Do not quote it.

Full detail in `GEOMETRY_V3.md`. `RETRACTION.md` is patched at the top; its §2 is withdrawn and the
other four refutations stand.

---

## 2. TIME STOP: the card's baseline does not exist in the code

**You have the current value as 8h. `EXITS.md` has it as 2h. The code says 12h.**

```
bot/manual/simulator.py:38     TIME_STOP_HOURS = 12.0   # "12h optimal per edge study (+4.5R net vs +2.4R at 24h)"
bot/manual/pa_simulator.py:46  TIME_STOP_HOURS = 12.0
bot/GO_LIVE_RECOMMENDATION.md:43   TIME_STOP_HOURS=12
```

The change is **12 → 48**, not 8 → 48. The error in `EXITS.md` line 11 was mine and is corrected here.

**"48h" is a no-op, not a setting.** `exits.py:31` is `HORIZON_H = 48` and the stops tested are
`(4, 12, 24, 48)`. A 48h time stop on a 48h horizon **can never fire** — it is numerically the
baseline. Its −0.0146R [−0.066, +0.038] is a mark-to-close artifact. **Read "48h" as "no time stop."**

| policy | train | test | in−out [95% CI] | verdict |
|---|---|---|---|---|
| time_48h (≡ no stop) | −0.0818 | +0.0542 | −0.0146 [−0.066, +0.038] | no difference |
| time_24h | −0.0747 | −0.0126 | **−0.0813** [−0.150, −0.007] | worse |
| **time_12h ← the bot today** | −0.0298 | −0.0251 | **−0.0939** [−0.164, −0.021] | worse |
| time_4h | −0.0148 | −0.0470 | **−0.1158** [−0.190, −0.044] | worse |

The bot's current 12h is the **second-worst cell measured**, CI excluding zero, and the series is
monotone over four points. Of 13 policies swept the only three significant results are these
negatives.

**So: raise it — direction yes, magnitude ~0.09R not +0.48R, and relabel the target "disable" rather
than "48h."** The +0.48R on the card comes from `ADAPTIVE_STOPS.md`'s stop-width work, a different
study.

Two caveats:
- **`exits.py` has no null test** (`grep -nE "flip|null|shuffl|placebo"` returns only the bootstrap
  RNG). Given §1 I am no longer willing to wave that through — but note it matters *less* here: for an
  exit policy, "early stops hurt any bracket" is still a reason not to cut early, since we are
  choosing a policy for whatever signals exist. It changes the story, not the action. I will run it,
  **with a synthetic-control check that the null can actually detect a known-real effect** — the step
  I skipped in §1.
- **Unresolved contradiction, please weigh in:** `simulator.py:38`'s own comment claims *"12h optimal
  per edge study (+4.5R net vs +2.4R at 24h)"* — 12h **better** than 24h. `EXITS.md` finds the reverse
  ordering (48 > 24 > 12 > 4). Both cannot hold. Do you have that edge study? If its horizon was near
  12h it has the same no-op artifact in mirror image, which would resolve the conflict in favour of
  `EXITS.md`.

---

## 3. VOLATILITY: keep forecasting it; replace HAR with a one-line EWMA

`VOLATILITY_V2.md` / `volatility_v2.json`, commit `6b6819da`. 20,444 coin-days, 22 walk-forward
folds, **both** horizons — y1 had never been walk-forwarded at all (`walkforward_vol.py` lines
114/159/168 all call `fit(tr,"y5")`).

| horizon | baseline | HAR wins | HAR QLIKE | base QLIKE | DM t |
|---|---|---|---|---|---|
| y1 | naive \|yesterday\| | 22/22 | 0.5202 | 4.7945 | −3.33 |
| y1 | rolling 22d stdev | 18/22 | 0.5202 | 0.5333 | −1.80 |
| **y1** | **EWMA** | **7/22** | 0.5202 | **0.5169** | +0.62 |
| y5 | naive | 22/22 | 0.1548 | 5.6335 | −3.90 |
| y5 | rolling 22d stdev | 18/22 | 0.1548 | 0.1699 | **−2.60** |
| **y5** | **EWMA** | **11/22** | 0.1548 | 0.1549 | +0.08 |

**Volatility is genuinely forecastable** — QLIKE 0.52 vs naive's 4.79 is a 9× improvement. The
expected-move column, levels-in-expected-moves, the position calculator and `SAFE_LEVERAGE`'s buckets
all stand; they need *a* forecast and will work as well or better.

**HAR earns nothing over a one-parameter EWMA**: 7/22 at y1 with EWMA's loss *lower*, 11/22 at y5
identical to four decimals. My "22/22 folds" was true only against the degenerate `|yesterday|` proxy,
whose loss is dominated by its own near-zero tail. The one real positive: HAR beats a plain rolling
22-day window at y5, 18/22, t = −2.60.

```python
# volforecast.py — lambda fitted on train only, grid {0.88,0.90,0.92,0.94,0.96,0.97}
v = lam * v + (1 - lam) * r_prev**2
sigma = sqrt(v)
next_day_move = sigma * sqrt(2/pi)   # E|return| for a zero-mean normal
next_5day_vol = sigma
```
One parameter instead of four plus a smearing factor, no stage-2 to maintain (separately retracted for
test-set leakage), no coefficient file to sync. The leverage fields survive the swap untouched — the
two forecasts are indistinguishable in loss, so bucket assignment barely moves.

---

## 4. `risk_voice.py` — you made it source of truth; revised guidance

| field | status |
|---|---|
| `stop_pct` (`STOP_K = 2.0`), `target_pct` (`TARGET_R = 0.5`) | **un-suspended, re-justified** — §1. Wider is right on fee grounds; keep `STOP_K` as is pending the ×4–×8 cost-minimum run |
| `TIME_STOP_H = 48` (line 34) | **flag it** — it is the no-op horizon value and silently disagrees with the bot's live 12. §2 |
| note line 166, "top two deciles over-predict 15–24%, shade down ~20%" | **unverified** — reviewer found stored top-decile ratios as low as 0.602, contradicting it |
| note lines 167–169, "+0.209R vs a fixed stop" | **restate as +0.12R fee-cost saving**, not an edge |
| `max_leverage`, `vol_bucket`, `worst_case_1d_pct` | keep — `SAFE_LEVERAGE.md` was never reviewed, so "unknown" not "clean" |
| `_forecast()` HAR call (line 100) | works; swap to EWMA per §3 — same accuracy, less machinery |

---

## 5. Your question: does `dissent_families` vs my 8-family count matter?

**Yes, but it is the smaller of the two problems.** The bigger one (`RETRACTION.md` §6, still
standing): `disagree` turned out to be an **extremity proxy** — it correlates with how far consensus
sits from neutral, so "Squeeze L/S" was partly re-displaying extremity under a new name. Re-derive
with extremity controlled before trusting the column; your family-count definition changes the
magnitude, not that confound. Relabel it unvalidated if you want it up meanwhile.

---

## 6. The TG scanner is the most valuable thing either of us shipped today

`6cad040c` / `1fdd51df` / `1fc030b1` / `122ebda7` — this unblocks the one question I could not answer.

The ladder work died on sampling three times: 195–228 GeckoTerminal pools per attempt, only 28–38
with two weeks of history, because public listings are almost entirely brand-new pools. The owner's
own calls are the only clean sample and your scanner produces exactly that.

`call_tracker.py` is ladder-aware and waiting: it freezes post-call prices every 3 minutes so rugs
cannot vanish from the sample, and takes `peak_mult` from 15m/hourly **highs** — not spot snapshots,
which miss intrabar peaks entirely. The owner's correction that peaks matter for ladder selling is
right, and `P(peak ≥ k)` is the primitive a ladder actually harvests. Reported per caller for
k ∈ {1.5, 2, 3, 5, 10}.

**What I need, in priority order:**
1. `calls.jsonl` at `bot/data/hivemind/tg/calls.jsonl` — the path my monitor already polls. One line
   per call: `{ts, chat, chat_id, caller, ca, chain}`. **Caller identity is the critical field** — it
   is what makes per-group `P(peak ≥ k)` possible and what Rick bot's leaderboard is built on.
2. **Call time to the second.** The question is "entry at call vs entry N minutes later"; a minute of
   slop swamps the effect at these multiples.
3. **Raw text alongside the parsed CA**, so I can separate a fresh call from a re-post or reply —
   repeated CAs will otherwise inflate a caller's hit rate.

~30 calls with caller IDs is enough for the pre-registered table. Until then any ladder number I
produce is scraped-sample noise and I will not publish one.

---

## 7. Standing protocol change

Both of today's reversals came from the same root: **a test that could not fail.** v1 validated on
data that had informed the choice; v2 used a null that was algebraically incapable of detecting the
effect it targeted. So from now on, before any null is used to kill a finding, I run a **synthetic
control**: inject a known-real effect of the expected size and confirm the test detects it. It is
cheap and it would have caught §1 immediately.

Re-read anything of mine from before 16:33Z as provisional. Three corrections are pushed — geometry
(v3, reverses half the retraction), the tie rule (assumption wrong, but it ran *against* our
conclusion), volatility (above) — each through two independent reviewers before I call it settled.
