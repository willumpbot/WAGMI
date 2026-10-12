# Laptop state — read this first. 2026-10-12, end of a long autonomous run.

**Purpose:** so the next session (mine or the server's) does not start blind, and so Nunu does not
have to re-explain anything. Everything below is current as of commit time.

---

## 1. What is RUNNING right now

| | |
|---|---|
| `megacalls_fetch.py` | fetching 2,477 priceable calls, **473 unique done**, ETA **~18h**. Single process, holds `geckoterminal.lock`. |
| `WAGMI-LaptopCrunch` (hourly task) | 7 jobs, all green on the last cycle |
| server `stop_shadow.py` | live 5m shadow stops, ~2 entries/day, accruing |

**If the fetch dies:** it is resumable — restart with
`Start-Process cmd '/c "<pythoncore path>" -u megacalls_fetch.py >> megacalls_fetch.log 2>&1'`.
**Do NOT launch it via a `WindowsApps\python.exe` alias** — that is a stub that spawns the real
interpreter, and killing the stub kills the worker. I lost a run that way.

## 2. 🔴 Three preregs are SEALED and must NOT be run early

| prereg | commit | runs when | my recorded expectation |
|---|---|---|---|
| `PREREG_STOP_SHADOW_2026-10-12` | sealed at n=3 | **n=150 resolved, or 2027-04-12** | UNDERPOWERED |
| `PREREG_RECALL_CROSSCHAT_2026-10-12` | `ca25df56`, n=35 | **n ≥ 250 re-called** (35 now) | UNDERPOWERED or small negative |
| `PREREG_CALLER_FORM_2026-10-12` | `60e17310` + amendment `636a885a` | **ONCE, at fetch completion or 2026-10-20** | UNDERPOWERED, small positive |

**Each records its expectation on purpose**, so neither a null nor a positive can be dressed up
afterwards. **Running any of them early makes that run the one that counts** — stated in the
documents themselves.

## 3. The settled answer on the Telegram calls

**Buying every call loses, at every horizon, before fees — and no position size is cheap.**

| horizon | best rule | eq-weighted | CI95 |
|---|---|---|---|
| 24h | 2.0× | −4.9% | [−15.5%, +5.1%] |
| 7d | 2.0× | −6.7% | [−19.3%, +5.7%] |
| **14d** | 1.5× | **−9.1%** | **[−18.5%, −0.8%]** |
| hold | — | **−42%** | — |

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
2. **Chat-vs-chat outcome differences** — the "which calls" half. **Needs no identity.** But the
   three chats barely overlap in time (`dtn` ends 06-21, `syndicate` starts 08-24, **zero shared
   days**), so it is confounded with calendar time and only ~24–32 shared day-clusters exist per
   usable pair. **Prereg before looking.**
3. **`PREREG_OI`** — open interest now has 178 coin-days of a stream that was declared permanently
   unrecoverable. Worth revisiting once it has a few weeks.

## 7. For the server

Replies 77–101 are the channel; **101 is the latest**. Outstanding from me: nothing blocking.
**Dropped after four asks:** `tp1` first-touch in `stop_shadow` — nice-to-have, and the sealed
prereg forbids it being load-bearing.
