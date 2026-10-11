# Moonbags: **UNANSWERABLE on this data**, and the prereg said so before I looked. The 20 missing calls flip the sign on their own.

_2026-10-11. `syndicate_moonbag.py`. 180 of 200 Syndicate first-calls with usable price paths,
2026-09-11 → 10-11, **31 distinct call days**. Design sealed in
`PREREG_M3_MOONBAG_2026-10-11.md` (SHA-256 `03818a91…`), committed `55b09d22` **before any exit
rule touched these paths.**_

Owner, via the server: *"holding some could be an option, sometimes there are bigger runners."*

---

## 1. The verdict, and which prereg clause produced it

**UNANSWERABLE.** Two of the prereg's four outcome conditions fired independently:

| prereg condition | fired? |
|---|---|
| "the 18 excluded calls flip the sign when scored as zeros" → **UNANSWERABLE** | **yes** |
| "it wins but MDE > the effect" → **UNDERPOWERED** | **yes, for all four comparisons** |

**Neither is evidence against moonbags.** It is an absence of evidence in either direction, which
is a different thing and must not be reported as the first.

## 2. 🔴 The exclusion decides the answer by itself

**20 calls have no usable path** — 12 with no liquidity pool, 6 with no price history, 2 too short.
The prereg flagged in advance that *a token with no pool may be one that rugged*, so this was never
a neutral drop:

| best day-weighted rule (`R1_hold24`) | |
|---|---|
| excluding the 20 | **+6.7%** |
| scoring all 20 as **total losses** | **−8.0%** |
| **sign flips** | **yes** |

**One unmeasured group of 20 reverses the headline.** Until their fate is known, every number below
is a range that straddles zero, and no rule can be preferred on this data.

## 3. Nothing is resolvable — the floors dwarf the effects

| rule | day-weighted | **MDE** | z | median call | % positive |
|---|---|---|---|---|---|
| `R1_hold24` | +6.7% | **77.5%** | +0.24 | −46.8% | 17% |
| `R2_hold7d` | +1.0% | **86.5%** | +0.03 | −55.0% | 17% |
| `R3_tp2x` | −11.9% | 21.1% | −1.58 | −14.8% | 37% |
| `R4_trail40` | +0.1% | 22.9% | +0.01 | −14.6% | 28% |
| `R5_moon_50at2x` | −5.4% | 50.1% | −0.30 | −14.8% | 28% |
| `R6_moon_75at15` | −0.9% | 28.6% | −0.09 | +6.3% | **54%** |

**31 call days is the clustered n, not 180.** The prereg predicted this would be underpowered and
it is: detection floors of **21–87%** against effects of **0.1–12%**.

**The moonbag comparison itself, paired per call** (same entry, same path, different exit):

| | day-weighted | CI95 | MDE | z |
|---|---|---|---|---|
| `moon_75at15` − `tp2x` | **+11.0%** | [−2.3, +28.7] | 22.1% | **+1.40** |
| `moon_50at2x` − `tp2x` | +6.5% | [−13.5, +41.2] | 39.1% | +0.46 |
| `moon_50at2x` − `hold7d` | −6.5% | [−41.1, +13.1] | 38.7% | −0.47 |
| `moon_75at15` − `hold7d` | −2.0% | [−55.7, +31.4] | 62.2% | −0.09 |

**None clears the Bonferroni bar of 2.64.** The best is +1.40, and its effect sits inside its own
floor.

## 4. ⚠️ And the walk-forward says most of this is noise

The prereg's split — first 15 days against last 15. **Five of six rules change sign:**

| rule | first half | second half | same sign |
|---|---|---|---|
| `R1_hold24` | **+56.1%** | **−39.6%** | no |
| `R2_hold7d` | −25.8% | +26.2% | no |
| `R4_trail40` | +19.6% | −18.2% | no |
| `R5_moon_50at2x` | −14.9% | +3.4% | no |
| `R6_moon_75at15` | −8.9% | +6.6% | no |
| `R3_tp2x` | −4.0% | −19.4% | **yes** |

**`R1_hold24` swinging 96 points between halves is the whole study in one line.** The only rule
with a stable sign is `R3_tp2x`, negative in both — taking the full 2× profit and leaving is
consistently the *worst* of the six, which at least points the same way as the owner's intuition.
Its magnitude is still inside the MDE, so it is a direction and not a finding.

## 5. 🔎 A tell in the sensitivity grid worth naming

Longer entry delays look **better**, monotonically: `R2_hold7d` runs +1.0% at 0 min to **+29.5% at
30 min**; `R1_hold24` +6.7% → +10.4%.

**A real edge on a memecoin call decays with delay — it does not improve.** An apparent *gain* from
waiting half an hour is what noise looks like when you slice 48 cells. **48 sensitivity cells were
examined** and none may be promoted to a finding; this one is reported precisely because it points
the wrong way and so helps calibrate how much of the grid is chance.

## 6. What this does say

**The base rate is brutal and that part is solid:** median call **−46.8% to −55.0%** on the hold
rules, **only 17% of calls positive.** That lines up with the server's Jun–Oct 188-call history
(median −53%), which I cannot verify myself and am citing as theirs.

**So the honest answer to the owner's question is:** *most of these calls lose most of their value,
and on 31 days of data nothing can tell you whether keeping a slice beats taking the lot. The one
rule that is consistently worst is selling everything at 2×.*

**No rule is recommended. Nothing changes.** The prereg stays sealed and the question reopens when
the call count roughly triples — the server exports 30 days rolling, and the laptop now archives it
permanently, so this gets more answerable every week rather than less.

## Limits
- **Closes only.** An intrabar wick that would have hit a 2× target or a 40% trailing stop is
  invisible, which biases target rules **down** and trailing rules **up**. Stated rather than
  corrected, because the data cannot support correcting it.
- **The population changed under the brief** (91 calls/14 days → 200/30 days), so the split was
  redefined in the prereg and **the server's 17-rule simulation and this are not replications of
  each other.**
- **Costs are charged as a flat 6% on the realised multiple**, not per leg; partial exits therefore
  pay slightly less than reality.
- `caller_hash` and `starred` were dropped at fetch and never used. When to sell does not require
  knowing who called it.
- The regime question ("was this window hot?") rests on the server's history figure, not mine.
