# PRE-REGISTRATION — M3: sell it all, or keep a moonbag?

**Sealed 2026-10-11, before any exit rule has been evaluated on this data.** The price paths
finished fetching minutes ago (`syndicate_paths.jsonl`, 182 of 200 calls) and **nothing has been
computed from them.** Mission M3, prompted by the owner via the server: *"holding some could be an
option, sometimes there are bigger runners."*

## 0. Why this needs sealing more than most

The rule space is enormous — the server is simulating **17 rules × 5 entry delays × 3 cost
assumptions**. That is 255 cells on 182 observations. **Something will look excellent by
chance.** So the primary test is a *small fixed set* declared here, and everything else is
explicitly sensitivity reporting, not testing.

## 1. 🔴 The population changed under the brief, and I am not pretending otherwise

| | brief | what actually landed |
|---|---|---|
| calls | 91 | **200** |
| window | 14 days | **30 days** (2026-09-11 → 10-11) |
| design | fit week 1, test week 2 | **does not map onto 30 days** |

So the split is **redefined here, now**: fit on the **first 15 days**, test on the **last 15**.
The server's own 17-rule simulation was written against the 14-day arms; **its numbers and mine are
therefore not comparable**, and I will not present them as replications of each other.

## 2. Exclusions, stated before looking at outcomes

182 of 200 calls have a usable path. **18 do not: 12 with no liquidity pool, 6 with no price
history.** This is the dangerous exclusion in this study: **a token with no pool may be one that
rugged**, which is the worst possible outcome, so dropping them could bias every rule upward.

**Pre-committed:** I will report the 18 separately — call timestamps and whatever the API still
knows — and state the verdict **both** with them excluded and with them scored as **total losses
(multiple = 0)**. If those two differ materially, the honest answer is a range, not a number.

## 3. The caller fields are not used, and will not be

`caller_hash` and `starred` were dropped at fetch time and are absent from `syndicate_paths.jsonl`.
The standing rule is that the laptop does not build caller grading. **When to sell does not require
knowing who called it**, so the question is answerable without ever touching those fields.

## 4. Rules — PRIMARY set, fixed now (6 only)

Entry at the call bar, measured in multiples of entry price.

| id | rule |
|---|---|
| `R1_hold24` | hold 24h, then exit |
| `R2_hold7d` | hold 7 days, then exit |
| `R3_tp2x` | exit all at 2× if touched, else at 7d |
| `R4_trail40` | 40% trailing stop from the running peak, else 7d |
| `R5_moon_50at2x` | **sell 50% at 2×, keep 50% for 7d** |
| `R6_moon_75at15` | **sell 75% at 1.5×, keep 25% for 7d** |

**Primary cell: each rule at 0-minute delay and 6% round-trip cost.** One number per rule.

## 5. Statistic and the number that governs

- Per call: realised multiple net of cost, minus 1, as a percentage return.
- **Reported as BOTH the mean over calls AND the equal-weighted mean over calendar days**, side by
  side. **The day-weighted figure governs.** Clustering the variance by day while averaging by
  event produced a published false null in this project this morning; the same error is not being
  repeated here.
- `corr(calls per day, day mean)` is reported beside both, because when it is non-zero the pooled
  figure is the wrong number rather than merely a noisy one.
- **Day-block bootstrap** for intervals. **MDE printed before any verdict.**
- Multiplicity on the primary set: 6 rules, Bonferroni two-sided 0.05/6 → **|z| > 2.64**.

## 6. The comparison that decides whether a moonbag pays

**H1:** a moonbag rule (`R5`, `R6`) beats its own full-exit twin (`R3`, and `R1`/`R2`) — i.e. the
fat right tail pays for the many zeros. Tested as a **paired** difference per call, which removes
the common entry and most of the market move.

**H0:** it does not, and the extra variance is unpaid.

## 7. 🔴 Power, before any verdict

Memecoin call outcomes are extremely right-skewed; the server reports a **median of −53%** over its
Jun–Oct 188-call history. With 182 calls over 30 days and roughly 6 calls/day, the clustered n is
**~30**, not 182. A skew-heavy distribution at n≈30 day-blocks will have a **very wide** MDE.

**I expect this study to be underpowered for the moonbag comparison, and I am writing that down
now** so a null is not later dressed up as evidence against moonbags. The MDE will be printed and
the verdict will state **UNDERPOWERED** where it applies.

## 8. Sensitivity — reported, never used as a test

Entry delays **1, 5, 15, 30 min**; costs **3%, 6%, 10%**. These answer "how fast does the edge
decay" and "how fragile is it to slippage". **No cell from the sensitivity grid may be promoted to
a finding**, and the count of cells examined is reported so the multiplicity is visible.

## 9. The regime question, which I cannot answer alone

"Is this window hot?" needs the Jun–Oct 188-call history, which lives on the server (median call
−53%). **That number is an external benchmark I cannot verify**, so any comparison to it is
labelled as resting on the server's figure, not mine.

## 10. Verdict rule, fixed now

| outcome | conclusion |
|---|---|
| a moonbag rule beats its twin at \|z\| > 2.64 on the **day-weighted** paired statistic, net of 6%, and holds in both halves | **SUPPORT** a moonbag exit; sizing proposed separately |
| it wins but MDE > the effect | **UNDERPOWERED — no finding**, reported as such |
| full-exit wins | **moonbags are not justified** on this data |
| the 18 excluded calls flip the sign when scored as zeros | **UNANSWERABLE** until their fate is known |

**No change to anything live on this prereg alone.** This is a question about the owner's own
discretionary exits, not a bot change, and it carries no SUPPORT verdict by itself.
