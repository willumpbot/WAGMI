# Laptop state — read this first. 2026-10-12, end of a long autonomous run.

**Purpose:** so the next session (mine or the server's) does not start blind, and so Nunu does not
have to re-explain anything. Everything below is current as of commit time.

---

## 1. What is RUNNING right now

| | |
|---|---|
| `megacalls_fetch.py` | fetching 2,477 priceable calls, **935 unique done (38%)**, ETA **~16h**. Single process, holds `geckoterminal.lock`. |
| **`fetch_funding_wide.py`** | **walking hourly funding for the 138 coins that had none, ~59/178 files, ETA ~4.5h.** Hyperliquid API — **no lock contention with the megacall fetch**, which is GeckoTerminal. **v1 was killed and rewritten**: `PAUSE=0.35s` generated its own 429s and spent 45 min to add 11 coins. v2 runs at 1.1s with adaptive backoff, **0 × 429 so far**. Measured cost is **~2.9s/page**, of which only 1.1s is the pause — HL's latency on 500-row historical queries is ~1.8s and inherent, so 4.5h is the honest floor, not a tuning failure. |
| `WAGMI-LaptopCrunch` (hourly task) | 7 jobs, all green on the last cycle |
| server `stop_shadow.py` | live 5m shadow stops, ~2 entries/day, accruing |

**🟢 THE DEEP UNIVERSE IS 173 PERPS, NOT 17.** Nunu pushed back on my claim that it was capped at 17
(*"theres probably always another angle"*) and he was right: **17 was a directory listing.** HL caps
`candleSnapshot` at ~5,000 bars — 208 days at 1h but **~13.7 years at 1d** — and nobody had asked it
for daily on the other 161 coins. `fetch_1d_wide.py` did: **161 fetched, 0 failed.** `size_flags.py`
globs `history/*_1d.csv`, so **its universe widened to 173 with no code change.** Funding was the next
limit and the cause was literally **`TOP_N = 40`** in mission 10's fetcher.

**Three "limits" checked, three were config constants or directory listings. Before calling anything a
limit, ask the source once.**

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
| **`PREREG_FUNDING_WIDE`** | **`624a9e98` (sealed `41805c5c` + Amendments 1 & 2)** | **ONCE, at ≥170 of 173 funding files** | **P(clean positive) ≈ 45%**, attenuating to +2–5% |

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
