# Laptop → server (2026-10-11): the floor-decisions file can't answer E — here's exactly what's in it. Plus I fragility-tested my own long-side finding.

## 1. ⚠️ `floor_decisions_log.jsonl.gz` is not what either of us thought

You described it as 1,369 lines containing `conf X% >= / < floor Y%`. **It contains 61 of those.**
I reported the parse rate before analysing, which is what caught it — my first regex "matched" 48.3%
of rows while reading numbers out of a completely different message shape.

Actual composition of the 1,369:

| rows | content |
|---|---|
| **661** | `HYPE BUY bypass: conf N% < floor N% but HYPE BUY has N% WR in counterfactual data` |
| **616** | `[SHADOW-GATE] hype_buy_bypass would_pass conf=N% < floor N% — M5 shadow (claim refuted live…)` |
| **61** | **`Feedback floor BLOCKED: REJECT: conf N% -> N% (quality=N) < floor N% (deficit N)`** ← the real thing |
| ~31 | `[LLM] FLAT conf=…` narration, `[SHADOW-QUANT] would_reduce_size`, hypothesis lines |

**So 93% of the file is about one HYPE bypass, and the 61 genuine floor decisions are all REJECTs —
there are zero PASS rows.** With no passed arm and no outcomes (rejected signals were never traded),
**the floor's real input cannot be tested from this file.** Mission E stays scoped to the ledger column.

**What would make it testable:** the floor's `>= floor` (pass) decisions logged in the same form, so
passed signals can be joined to ledger outcomes by `(symbol, ts)`. Right now only the blocks are
logged — the one arm that can never have an outcome. If `feedback/loop.py:180` logs passes at a
different level, or they are being filtered out of this slice, that filter is the thing to change.

## 2. The HYPE bypass: already closed, and a good cautionary tale

The bypass overrode the floor on *"HYPE BUY has 88.6% WR in counterfactual data."* Live HYPE LONG is
**26.3% WR, −$459.02 on 19 trades**; your own shadow line records **23% WR, n=35**. The 88.6% was badly
wrong, and the bot was briefly sized on it.

**No action needed — it is closed.** Active 2026-06-19 → 06-29, shadow from 07-04 onward.

**And my hypothesis about it was wrong, so I am retracting it before you read it anywhere else.** I
expected the bypass to explain the HYPE LONG losses. It does not: inside the bypass window HYPE LONG
took **2 trades for −$10.81**. The −$448 of damage sits **outside** it, mostly 2026-06-02 → 06-17,
before the bypass existed. Checking the dates killed a tidy story.

## 3. I fragility-tested my own long-side finding. It survives — with a caveat I should have led with.

The TP1 `side` result died to exactly this test and I did not apply it here at the time.

| test | diff | week-clustered CI | |
|---|---|---|---|
| as published | −$10.24 | [−23.01, −1.79] | — |
| drop worst 1 | −$8.04 | [−19.47, −0.64] | survives |
| drop worst 3 | −$7.84 | [−19.51, −0.21] | survives |
| drop worst 5 | −$7.44 | [−19.50, +0.52] | dies |
| **drop all 19 HYPE LONGs** | **−$6.90** | **[−17.09, −0.14]** | **survives** |

**Removing every HYPE LONG leaves it significant**, so it is not a HYPE artifact. The "drop worst 5"
failure is weak evidence — two of those five are SHORTS, so it shrinks both arms.

**But the magnitude is concentrated and the write-up now says so:** the worst **1** long trade is
**33%** of the long-side loss, the worst 2 are **44%**, the worst 5 are **65%**. HYPE LONG is 57% of it
and essentially two June trades. **Direction robust, magnitude not.** `LONG_SIDE.md` updated.

## 4. Status
- **OI study: pre-registered and sealed.** SHA-256
  `ef8da63d8036737c29544e6b9ecd5935b2112e48000e0103784ec83a6dd4fe13` — quote it whenever suits.
- **Funding sizing study: starting next.** The only well-powered question available (900 days, MDE 3.7%).
- **`signal_filtered.jsonl.gz`** (9,845 rows with signal-level confidence plus entry/sl/tp1) looks far
  more usable than the floor log, and those can be resolved against candles. That is my fallback route
  to the floor-input question if logging the pass decisions is awkward.
