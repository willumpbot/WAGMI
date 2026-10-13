# Laptop state — read this first. 2026-10-12, end of a long autonomous run.

**Purpose:** so the next session (mine or the server's) does not start blind, and so Nunu does not
have to re-explain anything. Everything below is current as of commit time.

---

## 1. What is RUNNING right now

| | |
|---|---|
**As of 2026-10-13 07:10 both long fetches are FINISHED. Nothing is downloading.**

| | |
|---|---|
| ~~`megacalls_fetch.py`~~ | ✅ **DONE 2026-10-13 ~06:40** — live **1,924**, dead 182 of 2,106, **22.3 h**, final 429 rate 2.9%. `call_outcomes.jsonl` regenerated **384 → 2,442** rows, identity check PASSED. |
| ~~`fetch_funding_wide.py`~~ | ✅ **DONE** — **~3,478,755 hourly rows across all 178 coins.** v1 was killed and rewritten twice: `PAUSE=0.35s` self-inflicted 429s, then v2's throttle could only *rise* so one burst pinned it at the 3.0s ceiling. v3 is AIMD and settled near 1.6s. |
| `WAGMI-LaptopCrunch` (hourly task) | 7 jobs; j4 fixed three times tonight — see §9 and the per-path staleness table |
| server `stop_shadow.py` | live 5m shadow stops, ~2 entries/day, accruing toward n=150 |

**The only thing now waiting on anything is `PREREG_CALLER_FORM`**, which needs the server's step-2
identity-local join against the new outcomes file. See §10.

**🟢 THE DEEP UNIVERSE IS 173 PERPS, NOT 17.** Nunu pushed back on my claim that it was capped at 17
(*"theres probably always another angle"*) and he was right: **17 was a directory listing.** HL caps
`candleSnapshot` at ~5,000 bars — 208 days at 1h but **~13.7 years at 1d** — and nobody had asked it
for daily on the other 161 coins. `fetch_1d_wide.py` did: **161 fetched, 0 failed.** `size_flags.py`
globs `history/*_1d.csv`, so **its universe widened to 173 with no code change.** Funding was the next
limit and the cause was literally **`TOP_N = 40`** in mission 10's fetcher.

**Three "limits" checked, three were config constants or directory listings. Before calling anything a
limit, ask the source once.**

**📌 HOW TO TELL IF THE FETCH IS ALIVE — do not use the log.** `megacalls_fetch.log` prints only
every **50 calls**, which takes **~32 min** (measured: 31.3–33.3 min over six intervals, max observed
gap **66.5 min**). I twice read a quiet log as a possible stall.

**Use the per-call signals instead:** `megacalls_paths.jsonl` mtime, and the `geckoterminal.lock`
heartbeat — **both update on every call.** If those two are current, it is working no matter how quiet
the log is. **And use `ls --time-style` WITH the date**: a time-only listing made an archived
`megacalls_paths_WRONG_TOKEN_SIDE.jsonl` from 2026-10-12 look like it had just been written.

**If the fetch dies:** it is resumable — restart with
`Start-Process cmd '/c "<pythoncore path>" -u megacalls_fetch.py >> megacalls_fetch.log 2>&1'`.
**Do NOT launch it via a `WindowsApps\python.exe` alias** — that is a stub that spawns the real
interpreter, and killing the stub kills the worker. I lost a run that way.

## 2. 🔴 FIVE preregs are SEALED and must NOT be run early

| prereg | commit | runs when | my recorded expectation |
|---|---|---|---|
| `PREREG_STOP_SHADOW_2026-10-12` | sealed at n=3 | **n=150 resolved, or 2027-04-12** | UNDERPOWERED |
| `PREREG_RECALL_CROSSCHAT_2026-10-12` | `ca25df56`, n=35 | **n ≥ 250 re-called** (35 now) | UNDERPOWERED or small negative |
| `PREREG_CALLER_FORM_2026-10-12` | `60e17310` + amendment `636a885a` | **ONCE, at fetch completion or 2026-10-20** | UNDERPOWERED, small positive |
| `PREREG_CHAT_QUALITY_2026-10-12` | sealed on design facts only | **ONCE, at fetch completion or 2026-10-20** | UNDERPOWERED (floor ~15pp vs a 45% base) |
| ~~`PREREG_FUNDING_WIDE`~~ | **`ecf331b4` (sealed `41805c5c` + Amendments 1–4)** | ✅ **RAN 2026-10-12 at 173/173** | **+4.77% — REPLICATES.** I predicted +2–5% and ~45% |

## 🟢 2z. TWO REPLICATIONS HELD TONIGHT — this project had never managed one

| study | held-out effect | verdict |
|---|---|---|
| **`FUNDING_WIDE_RESULT.md`** — bigger next-day \|move\| | **+4.77%** CI [+2.46, +7.13] | replicates |
| **`STOPHITS_WIDE_RESULT.md`** — more 1.65-em stop hits | **+2.40 pp** CI [+1.63, +3.16] | replicates, **live config too** |

**`PREREG_STOPHITS_WIDE` (`81d016b7`, commit `208a908e`) ran once, 12 arms, NO amendment needed.** Its
canary was **verified before sealing** and matched at run time on both operators — the opposite of the
funding run, whose canary was a hope and failed.

**Both stop-hits primaries replicate and agree to 0.03 pp:** (A) the published claim (naive `em`, `ge`)
**+2.37 pp t 7.10**; (B) the live configuration (fitted `em`, `gt`) **+2.40 pp t 6.14**. Filter-robust
(+2.67 unfiltered), not rank-dependent (frozen +2.58), K-curve monotone.

**🔴 Two things found while building that canary:**

1. **`funding_stop.py:41-42` hardcodes its own unfitted HAR** — `Y1B=(0.0,0.35,0.35,0.30)`, `Y1S=1.0`,
   no intercept and no smearing — where `size_flags.py` loads the fitted coefficients. **A FOURTH
   `exp_move` variant, sitting inside a claim card's evidence.** Confirmed by reproducing both
   published figures to the digit with the naive constants.
2. **So `K* = 1.698` ("a 2.9% wider stop on `funding_hot` days") was calibrated on the wrong
   forecast.** Must be recomputed on the fitted `em` before it is quoted as actionable. **Not urgent:
   `ADAPTIVE_STOPS=false`, so live stops are not using `exp_move` at all.**

**📌 `ADAPTIVE_STOPS=false` also kills my own framing:** I spent four replies calling D3 "the one
touching live money". **It isn't, and I never checked.**

### 🔴 `K*` was understated by about HALF — wrong estimator, not just the wrong `em`

**`KSTAR_RECOMPUTE.md` (descriptive, NOT preregistered).** The published `K* = 1.698` ("+2.9% wider
stop on `funding_hot` days") is a **MARGINAL** calculation; the significance test that justifies it is
**MATCHED** within date × em-quintile. **Marginal is ~half of matched everywhere, and for the live
`gt` operator under the naive `em` it FLIPS SIGN** (−0.30 vs +3.48 pp).

**Recomputed consistently: `K*` ≈ 1.770, +7.3%** on held-out coins under the live flag and fitted
forecast. **Every configuration lands +5.1% to +7.7%**, where the marginal version ranged −0.9% to
+6.0%. The consistent figure is larger *and* far more stable.

**Do not wire it in.** It postdates the replication, and the PC has since applied the `risk_voice`
haircut and the `_closed` fix — **both move `em`, so both move `K*`.** A real answer needs its own
prereg with an **economic** objective; exceedance parity is a statistical target, not expectancy.

**The transferable rule: a decision number and the test justifying it must come from the same
estimator.** Nobody was careless — the test and the calibration lived in different parts of one file
and were never compared.

## 🟢 2a. THE FIRST REPLICATION — read `FUNDING_WIDE_RESULT.md`

**`funding_hot` predicts a +4.77% bigger next-day |move| on 156 coins it was never tested on**
(CI [+2.46, +7.13], MDE 3.66%, **179 week-clusters**, 5,084 matched cells, placebo size 0.018 —
valid and **conservative**, so significance was won against a stricter-than-nominal bar).

**This is the first genuine out-of-sample replication this project has ever run.** Everything before
it was a re-cut of the discovery sample.

| check, pre-specified | outcome |
|---|---|
| **canary** — ORIG17 unfiltered must reproduce +0.0740 log | ✅ **+0.0740 / +7.68%, exact**, 2,283 cells, 145 weeks, flag 20.8% vs 20.76% |
| filter-robust? (c) +4.77% vs (c_raw) +5.86% | ✅ same verdict — **not** filter-dependent |
| rank-dependent? rank +4.77% vs frozen +5.91% | ✅ same verdict — **not** rank-dependent |
| A2 mechanism: (b) filtered below (b_raw)? | ✅ **+7.30% < +7.68%** |

**Attenuation to 62% of the original (+4.77% vs +7.68%) is exactly what an honest re-test does to a
finding whose discovery sample also chose the hypothesis.**

**🔴 THE FIRST RUN WAS VOID and its numbers are in the result doc and prereg §C.** It failed its own
canary (+5.64% vs the required +7.68%). Cause: **`size_flags.py:148` buckets `em` quintiles GLOBALLY
across the panel; I had bucketed PER DATE.** The prose says "within the same date AND the same em
quintile" and per-date is a defensible reading — **the code does global, and the code produced +7.7%.**
**Third time in one session I re-derived a baseline from a write-up instead of reading the
implementation.** I had seen a (c) estimate of **+3.65%** before the valid run returned +4.77%, so my
expectations were contaminated even though the data and design were not. **That caveat travels with
the finding permanently.**

**Use it for sizing and stop width, never direction.** The outcome is unsigned |move|; every signed
claim this project has made has died.

**TWO AMENDMENTS, both made before any read, both found by testing my own rules instead of trusting
my description of them:**

- **A1 — the verdict rule was broken.** "Effect below MDE ⇒ unmeasurable" would have declared
  `SIZE_FLAGS` itself unmeasurable (+0.0740 log against an mde80 of 0.10, at t 3.28). That conflates
  *could we have detected an effect this big* with *did we*. Replaced by a **2×2 on (CI excludes zero)
  × (effect ≥ MDE80)**, which finally gives this project the label it lacked: **"positive but
  underpowered"** — and that is the honest tier for `SIZE_FLAGS` itself. MDE is now interpolated on a
  finer grid (the coarse one overstated it by a third).
- **A2 — 11.9% of the panel never traded.** The PC confirmed HL's pre-listing bars are its own
  backfill (`n=0, v=0`), and **`MAX_STALE` cannot see them** because they carry *moving OHLC* with
  zero volume. I had cited "0 dropped as stale" as proof the new series were clean; it only proved the
  filter ignores volume. Those rows **can never be flagged** (no funding before listing), so they sat
  wholly in the unflagged arm as fabricated price paths. **`SIZE_FLAGS`' own window is 10.7%
  synthetic — ZEC 73%, 11 of 17 coins.** Fix: truncate each coin to its first `v>0` bar (a clean
  prefix for 93 of 178), then drop coin-days whose own or outcome bar has `v=0`. **The canary split:**
  unfiltered ORIG17 rebuilds to **exactly 19,853** coin-days (matching `SIZE_FLAGS`) and is now the
  pipeline check; filtered is 17,439, **−12.2%**.

**The real-trading start is PER COIN:** BTC/ETH/ATOM 2023-02-26, DOGE 2023-04-03, NEAR 2023-11-01,
HYPE 2024-12-05. **`START` stays `2023-01-01`** — the volume filter does that job per coin instead.

**`PREREG_FUNDING_WIDE` is the most important one and the best-sealed thing this project has.** It was
written **while the held-out data was still downloading** (51/178 files), so the sealing is provable
rather than asserted. **`SIZE_FLAGS` — the only finding that ever survived a red team here — was
discovered on 17 coins, so the 156 newly available ones are a genuine held-out sample. This project
has never run a real out-of-sample replication;** every prior "confirmation" was a re-cut of the
discovery sample, which is how M2 survived six readings.

Four things it fixes **before** any read: **(c) the 156 new coins is the number to act on**, pooled-173
is **contaminated**, the original 17 is a **pipeline canary not evidence**; `funding_hot`'s top-quintile
treatment is **redefined by widening** (top 20% of 17 ≠ of 173 — rank arm primary, frozen-threshold
secondary, disagreement reported as rank-dependence); it is **gated at ≥170/173 because
`load_funding` returns `{}` for a missing file** and would mark a coin silently and permanently
unflagged — **a missing source is never a zero**; and **δ=0 size is a placebo that can fail** — outside
[0.02, 0.09] it reports **TEST BROKEN** with no verdict.

**Power honesty, after I got it wrong once:** the gain is **NOT** the 8.4× coin-days and **NOT** 2× in
clusters. `START="2023-01-01"` caps weeks at **199 vs SIZE_FLAGS' 160 — only +24%.** The real gain is
**median coins per date 17 → 119**, which rescues the date×em-quintile cells that `matched()` used to
discard (at 17 coins a cell held ~3.4, so a top-quintile flag left 0 or 1 flagged). **Power comes from
within-week precision and will be claimed only from the script's own injected-effect table.**

**📌 Do not extend `START` backwards.** 48 coins carry pre-2023 bars starting on **exactly 2020-08-19
with exactly 865 rows each** — and **Hyperliquid did not exist in 2020.** That is unexplained backfill
worth ~123 extra weeks, deliberately left on the table. Reply 115 asks the PC if it knows the origin.

**`stop_shadow` carries AMENDMENT 1** (commit `53dde248`): its GBM control is now a **correction**,
not a gate — report *measured minus the no-edge median*, computed per position. Measured bias is
**≈ +0.035R for the 1.0× arm, ~14% of its 0.25R floor**. **The other three preregs were audited by
mechanism and are clean** — only `stop_shadow` has a treatment that moves a barrier.

### Delivered 2026-10-12, beyond the calls work

| study | verdict |
|---|---|
| `SKIPGATE.md` — 143,813 skipped signals | **UNDERPOWERED / negative.** Pooled said +21 bps ("the bot is too picky"), day-weighted said **−18 bps**. 4th appearance of the M2 error. |
| `E2_TIGHTEN.md` — should the engine tighten stops? | **NO FINDING.** +0.41R at z 4.69, and a random walk scored +0.18R — my metric was mechanically biased. |
| `E2B_ABSRET.md` — same, absolute return | **NO VERDICT.** +0.76R at z 3.09, again inside the no-edge spread. Two sealed designs absorbed ⇒ the approach is wrong; the owner-plan A/B is right and has **n=2**. |

**Each records its expectation on purpose**, so neither a null nor a positive can be dressed up
afterwards. **Running any of them early makes that run the one that counts** — stated in the
documents themselves.

## 3. The settled answer on the Telegram calls

**Buying every call loses, at every horizon, before fees — and no position size is cheap.**

| horizon | best rule | eq-weighted | CI95 | |
|---|---|---|---|---|
| **24h** | 1.5× | **−9.8%** | **[−16.0%, −3.8%]** | **excludes zero** |
| **7d** | 1.5× | **−9.8%** | **[−16.9%, −3.0%]** | **excludes zero** |
| **14d** | 1.5× | **−10.8%** | **[−18.1%, −3.7%]** | **excludes zero** |
| hold | — | **−45%** | — | |

_n=413 complete / 83 call-days, death rate 22.4%. **All three horizons now exclude zero**, the same
rule (1.5×) wins at all three, and the magnitude is flat at −9 to −11%. Top-1 share **0%** and
dropping the single best call moves nothing, so none of it rests on an outlier._

**The strongest form of the finding: the exit rule is not the lever.** 1.5×, 2× and 3× give the same
answer at every horizon. Whatever is wrong is in the asset selection, not the exit.

**Costs close it:** on a typical **$5,100** pool, round-trip slippage is **~4% at $100**, ~10% at
$250, ~20% at $500, **~78% at $2,000**. Even the smallest sensible order costs about what the best
case was ever worth.

**Nunu's hunch was right on mechanism and wrong as a strategy:** the runners are real — **5% of
calls reach 10× within 14 days, the biggest 91×, and 67% peak after day one** — but a target-based
rule cannot capture a tail (a 74× coin pays +100% under a sell-at-2× rule, same as any doubler), and
holding to capture it eats the median call plus the **1 in 5 that die**.

## 4. 🔴 Five corrections in one day — and the pattern matters more than any of them

1. **`ENTRY_TIMING` retracted** — momentum measured at the trade's **close**, so the feature
   contained its own outcome.
2. **Wrong token side** — GeckoTerminal's OHLCV defaults to `token=base`; quote-side calls priced a
   **different token** (one read 1.00× against a real 58.69×).
3. **Death rate 12.5% → 20.8%** — counted **rows, not calls**.
4. **Horizons not sharing a base**, and the "24h" minute grid only covered **16.7h**.
5. **Fetch re-queue** — the same row-vs-call confusion, in a second file, burning ~273 re-fetches
   per restart.

**All five came from checks I built, none from being caught. That is the problem:** I was building
the checks *after* reporting. **Two now run before it** — `assert_monotone()` halts on an impossible
peak, and `export_outcomes.py` refuses to write if an identity-like field appears.

**The recurring cause worth remembering:** `megacalls_paths.jsonl` is **append-only**, and every
consumer wants **one record per call**. Any code reading it must dedupe by `ca` first. Two separate
files failed to.

## 5. Standing rules I have been holding to

- **`caller_hash` and `starred` are never read here.** The caller-form work is a three-step handoff:
  I ship identity-free outcomes, the server computes form locally, I test the anonymous result.
  **`caller_is_bot` is admissible** — a boolean cannot identify anyone (my own audit false-flagged it).
- **The equal-weighted cluster mean governs** over the pooled mean, always.
- **A placebo must be able to fail.** `x2_gbm_placebo.py` exists because X2's arm-permutation
  placebo could not detect a mechanical effect; the GBM control could.
- **Nothing reaches Nunu's board without the horizon, the n, and the clustering unit behind it.**

## 6. What is genuinely open

1. **The fetch** (~18h) → then the caller-form test, and the re-call test once 250 re-called accrue.
2. **Chat-vs-chat outcome differences** — **now prereged** (`PREREG_CHAT_QUALITY_2026-10-12`), runs
   once at fetch completion. Two facts from the design alone: **`dtn` and `syndicate` can NEVER be
   compared** (dtn ends 06-21, syndicate starts 08-24 — zero shared days, permanently), and **`dtn`
   posts 204 calls across 7 days**, so anything involving it rests on ~7 independent observations
   whatever its call count. Best usable pair is `dtn_hitters` × `syndicate` at ~32 shared days.
3. **`PREREG_OI`** — open interest now has 178 coin-days of a stream that was declared permanently
   unrecoverable. Worth revisiting once it has a few weeks.

## 7. For the server

Replies 77–101 are the channel; **101 is the latest**. Outstanding from me: nothing blocking.
**Dropped after four asks:** `tp1` first-touch in `stop_shadow` — nice-to-have, and the sealed
prereg forbids it being load-bearing.

## 9. Source limits, now actually measured instead of assumed

Today's lesson was that every "limit" I had asserted was a cache or a config constant. **So I measured
the real ones.** Three of four were ours; one is genuinely the exchange's.

| panel | limit | ours or theirs? |
|---|---|---|
| daily candles, 17 coins | a **directory listing** | **ours** — now 173 perps |
| funding, 40 coins | **`TOP_N = 40`** in mission 10's fetcher | **ours** — walking all 178 |
| hourly candles, 210 dates | **HL retains ~208 days of 1h and no more** | **THEIRS. Permanent.** |

**The hourly boundary is real and I probed it properly.** 60-day windows ARE honoured (1,441 bars
ending 60 days ago, 1,402 ending 150 days ago) — but **0 bars at 250, 400 and 600 days ago**, and
asking for 20,000 hours returns the same 5,002 bars starting 2026-03-18. **The 5,000-bar cap and the
retention edge coincide at ~208 days, which is why it looked like a cap.** Hourly history cannot be
deepened. Ever.

### 🟢 The consequence is the most valuable passive fact on this board

**`candles_1h` upserts on `PRIMARY KEY (coin, t)` and NOTHING in `j1_panels.py` deletes** — the loop
at line 164 only logs. I checked before raising an alarm, and the alarm was wrong: the oldest dates
hold **173 coins / 4,152 rows**, as full as the newest, so the panel took the whole 208-day window in
one pull rather than growing from thin.

**So 2026-03-17 is now a permanent floor, and the panel gains a day of hourly history every day that
the ingest runs.** HL deletes its end of that window as we keep ours.

**That makes "keep the hourly ingest alive" a compounding asset rather than maintenance.** In a year
the hourly panel is ~570 days deep and nobody can buy that back. **It is the one place where Nunu's
"time is on our side" is literally true** — and the only way to lose it is to stop ingesting for 208
days or rebuild the DB from scratch.

### Provenance, corroborated independently

The pre-2023 daily bars are **confirmed foreign backfill**. `ATOM` funding begins **2023-05-12** while
its daily price claims **2020-08-19** — and Hyperliquid cannot have funding for a coin that was not
listed there. Same shape for every coin with the suspicious 865-row pre-2023 block. **`START =
"2023-01-01"` stays frozen**; the ~123 extra weeks are not ours to use.

## 10. 2026-10-13 07:10 — fetch COMPLETE, chat quality ran, caller form blocked

**`megacalls_fetch` DONE: live 1,924, dead 182 of 2,106, 22.3 hours, final 429 rate 2.9%.**
`call_outcomes.jsonl` regenerated **384 → 2,442 rows**, identity check PASSED.

### `PREREG_CHAT_QUALITY` — ran ONCE. **UNDERPOWERED.** `CHAT_QUALITY_RESULT.md`

| | eq-weighted (governs) | pooled | CI | z | verdict |
|---|---|---|---|---|---|
| **`dtn_hitters` − `syndicate`** | **+14.5 pp** | +8.9 pp | **[−0.7, +29.6]** | **1.87** | **UNDERPOWERED** |
| `dtn` − `dtn_hitters` | +12.7 pp | +19.5 pp | [−5.5, +28.9] | 1.45 | UNDERPOWERED (sign flips) |

Placebo valid (0.067 / 0.078), MDE **8.0 pp** well under the 15 pp floor, **32 shared days — exactly
the "~32" the prereg predicted.** The primary clears four of five SUPPORT criteria and **fails only
significance: lower bound −0.7, z 1.87 against the 2.24 bar.** **Not reported as suggestive** — the bar
was fixed in advance so a 1.87 could not be talked across it.

**Death rates: `dtn` 5.3% · `dtn_hitters` 30.5% · `syndicate` 34.4%.** Looks decisive, **is unusable** —
`dtn` ends 06-21 and `syndicate` starts 08-24, so it is pure era confound, which is why the prereg
excluded that pair permanently. The era-matched 4-point death gap runs the same way as the hit gap, so
the primary may be substantially **survival** rather than target-reaching. Flagged, not claimed.

**VOID RUN 1:** `day_of` divided `call_ts` by 1000 when the file stores **seconds**, collapsing all
calls into January 1970 → "shared days: 1". **The prereg's own recorded count caught it** (14 at 384
rows cannot become 1 at 2,442). **It computed no effect, placebo or MDE, so the re-run was genuinely
blind** — unlike the funding void run. Units now detected *and* year-range-checked, so a repeat halts.

### 🔴 `PREREG_CALLER_FORM` — gate open, **NOT RUN**, blocked on the server

`call_caller_form_anon.jsonl` is still the 384-row file from 10-12, giving
`form_n_known_7d ≥ 3` = **exactly 126** — and **Amendment 1 forbids a run at n=126.** The server must
re-run step 2 (identity-local join) against the new 2,442-row outcomes file; the prereg expects
**~650** rows at threshold. **The deferral is a data dependency, not a choice**, and that goes in the
result doc so it cannot later read as waiting for a better n.

### Calibration note — three instances now, all the same direction

**I am systematically too gloomy.** Over-predicted attenuation on both replications, and called this
prereg's power "probably fatal" with a ~14 pp floor when the real MDE was **8.0 pp**. **The corpus
growth mattered more than I expected, twice.**

---

## 11. 2026-10-13 late — mission queue M1–M4 + M9 closed; reply 131 red-team delivered

**Queue status:** M1 ✅ M2 (arm A) ✅ M3 ✅ M4 ✅ M9 (phase 1) ✅ — **M5 is next.**
M6/M7/M8 untouched. M9 phase 2 wants HL's tiered maintenance schedule (`meta`/`marginTables`).

### M4 — closed UNDERPOWERED, with a structural finding worth more than the z
`PREREG_M4_FUNDING_SIZING.md` sealed `1a00b1cf`, **amended `7c699867`**, run once.
`M4_FUNDING_SIZING_RESULT.md`.

- **Primary `P1 − P2` = +0.0015% of equity, z 1.91 vs 1.96, below the 0.0022 MDE → UNDERPOWERED.**
- **Amendment 1 killed two outcome units that were artifacts**: bps-of-notional made P2 identically
  zero (risk cancels); drawdown-in-R mechanically favours the wider stop (R *is* the stop). Caught
  from algebra **before** running. The run then confirmed `P2/P0 = 0.93220` exactly.
- **🔴 The drawdown verdict flips sign with the denominator** (% of equity → P2; R → P1), and
  **`notional = risk ÷ stop` means matching notional and dollar risk forces the same policy** — so
  "widen vs size down" has **no normalisation-free answer**. It is a preference about which quantity
  to hold fixed, not an empirical question.
- **Expectation 7.2 MISSED** — I predicted size-down would win; the point estimate runs the other way.
- **Economics: the spread across all four policies is ~$0.08/trade on $5,000.** With M9 (leverage
  cannot move P&L), two studies now say the **geometry dials are economically irrelevant at this
  account size**; risk-per-trade and trade selection are the live dials.

### 🔴 VOID RUN 1 — a verdict printed from ZERO rows
`HIST` said `hist/`, the directory is `history/`. Every coin skipped — **and the script still printed
`VERDICT: UNDERPOWERED` and scored an expectation**, because `(nan > 0) == (nan > 0)` is `True`.
**Absence-is-not-evidence inside the instrument**, same family as the six `j4` false alarms.
**Fixed structurally:** halts under 50 funding coins, or under 20 held-out / 3 discovery coins.
**New standing rule: every harness must be unable to reach its verdict block on an empty panel.**

### Reply 131 — red-team of `OWNER_PROFITS_ONLY_REQUIRE_PROFIT` (live-money flag)
**SUPPORT, as preference enforcement, not EV.** The asymmetry objection I went looking for died:
`exit_engine.py:110` already blocks early full close for restricted modes, so the flag closes the last
hole rather than filtering only the gentle de-risk.
- **Asked them to fix the record BEFORE flipping it:** a shadow-allowed partial lands in
  `owner_exit_decisions.jsonl` with `position_entry` but **no decision-time price**, so in-profit vs
  at-a-loss is unreconstructable. **The log is not the data.**
- **Answered their gross-vs-net question against my first instinct: gross.** No funding field exists
  on `Position`; the gross/net window is ~9 bps against ETH's ~180 bps em (~5% of the decision space);
  and net makes the gate stricter, which has a cost I cannot sign.
- **Reported that M2 arm A does not resolve it** — pooled −25.5 vs eq-day +14.9 bps, signs disagree.
  **So it must not be justified as EV, including by me.**

### Calibration — a sixth instance, same direction
**M4's "UNDERPOWERED" call was right by 0.05 of a z.** I keep being too gloomy, and this time the
prediction held only barely. The pattern is now six-for-six and belongs in every power statement.
