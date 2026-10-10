# What predicts reaching TP1? Nothing measurable yet — but the market rose 20% while the bot lost money.

_2026-10-10. 293 real closes, 25 TP1-reachers. Screen, not a test. Data in `server_exports/`._

---

## Why the question

`REAL_LEDGER.md` established that everything profitable in the ledger happens after TP1 — the trail
and TP2 are 8.5% of closes and +$1,161, while the other 91.5% are −$1,351. So **"what gets a trade to
TP1" is a more valuable question than any exit tuning**, and it is answerable from entry-time fields.

## 🔴 Answer: nothing clears, and the one thing that looked like it is one event from collapsing

**Power stated first.** 25 reachers against 268 non-reachers gives an 80%-power MDE of **0.59 standard
deviations**. That is a large effect. This is a **screen** — it can only say what is worth measuring
when n grows.

| entry feature | reached | missed | diff (SD) | clears 0.59? |
|---|---|---|---|---|
| `confidence_score` | 27.69 | 41.44 | **−0.41** | no |
| `hold_hours` | 10.39 | 5.26 | +0.44 | no |
| `agreement_level` | 1.28 | 1.55 | −0.39 | no |
| `leverage` | 2.01 | 1.63 | +0.32 | no |
| `predicted_ev`, `kelly_weight`, funding/OI/premium at entry | — | — | — | **not populated** |

Nothing clears. Worth noting the *direction* on confidence though: trades that reach TP1 have
**lower** entry confidence (27.7 vs 41.4). That is consistent with the reviewed finding that the
confidence score does not rank signals — it is not independent evidence, but it points the same way.

## The one thing that looked real, and how it died

**`side`: 84% of TP1-reachers are SHORT against 57.8% of the rest.** Reach rate **11.9% short vs 3.4%
long** — a 3.5× gap, **z = 3.30**, which clears a Bonferroni threshold of 2.89 over the ~13 features
screened.

It survived two attacks:

1. **The market confound ran backwards.** I expected "shorts win because the market fell". It rose:
   median **+20.3%** over the window (BTC +15.5%, ETH +25.0%, SOL +35.6%, HYPE +14.1%, XRP +8.3%,
   NEAR +92.1%). Drift was working *against* the shorts, which makes the gap harder to explain, not
   easier.
2. **The geometry is identical by side.** LONG stop 1.81% / target 8.12%; SHORT stop 1.78% /
   target 8.01%. Shorts do not have nearer targets, so the mechanical explanation fails.

**And then it died to the fragility check.** The entire long arm rests on **4 events**:

| if this many more longs had reached TP1 | z | verdict |
|---|---|---|
| 0 (as observed) | **3.30** | clears |
| **+1** | **2.49** | **fails Bonferroni** |
| +2 | 2.14 | fails |
| +3 | 1.81 | fails |

**One additional long reaching TP1 destroys it.** A result that cannot survive a single extra event
is an anecdote with a z-score attached, and this project has published enough of those.

## The fact worth keeping from this exercise

**The market rose a median 20.3% over the ledger window and the bot lost $190.** Buy-and-hold on any
of the six traded coins would have made money — NEAR would have nearly doubled. That is not an
argument about the bot's design; it is the benchmark any future version has to clear, and it has not
appeared anywhere in this project's reporting until now.

## Trader rules — one number each
1. **Nothing in the entry data predicts which trades reach their first target** at the sample
   available — the detection floor is **0.59 SD** and nothing comes close.
2. **The short/long gap (11.9% vs 3.4%) is not established.** It dies if **one** more long had
   reached TP1. Do not trade on it; do re-check it at n ≈ 100 reachers.
3. **The benchmark is +20.3%.** That is what holding the traded coins returned over the same window
   the bot lost money in.

## What would make this answerable
- **Populate the empty entry fields.** `predicted_ev`, `kelly_weight_applied`,
  `compound_size_multiplier`, `funding_rate_entry`, `open_interest_entry` and `premium_entry` are all
  present as columns and empty in the rows I have. Those are exactly the features most likely to carry
  signal — funding and open interest are the two non-price fields that have worked anywhere in this
  project.
- **~100 TP1-reachers** brings the MDE to roughly 0.30 SD, which would resolve the confidence
  direction above. At the current 8.5% reach rate that is ~1,200 more closes.

## Limits
- 25 reachers. Everything here is fragile by construction and labelled as such.
- TP1-reached is inferred from `exit_type ∈ {TRAILING_STOP, TP2}`, since the ledger has no `tp1_hit`
  column (`trades.csv` does, and gives a consistent 24 of 235).
- Thirteen features screened, no pre-registration. The Bonferroni adjustment is applied but a screen
  this wide on a sample this small should be read as hypothesis generation only.
