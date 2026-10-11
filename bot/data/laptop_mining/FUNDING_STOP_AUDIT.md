# ⚠️ Downgrading my own funding/stop finding: the terminal's `funding_hot` is a different, stricter condition than the one I tested — and the effect's significance is definition-dependent.

_2026-10-11, hours after publishing `FUNDING_STOP.md`. Triggered by `scanner.py` finally landing in the
export — the ask that had been open across two red teams. **Reading the actual code changed the result.**_

---

## 1. The live flag is not the flag I measured

`server_exports/scanner.py:159-163`:

```python
hot = sorted((r["funding_h"] for r in rows), reverse=True)
cut = hot[max(0, len(hot) // 10 - 1)] if hot else None     # TOP DECILE
if cut is not None and r["funding_h"] >= cut and r["funding_h"] > 1.25e-5:   # + absolute floor
    r["flags"].append("funding_hot")
```

**Top decile, plus an absolute hourly-funding floor.** Both `SIZE_FLAGS.md` (+7.7%) and
`FUNDING_STOP.md` (+12%) used **top quintile per date with no floor** — the definition quoted in a
docstring, which is all anyone had seen. The live flag fires on **5.14%** of coin-days; mine fires on
**26.33%**. Every live-flagged row is inside my set, so it is a strict subset — **5× narrower.**

## 2. 🔴 And the effect's significance does not survive the narrowing

Stop-exceedance at K = 1.65, matched within date × em-quintile, week-clustered — identical method,
only the flag definition changes:

| variant | n flagged | effect (pp) | week t |
|---|---|---|---|
| **as published** — pandas `quantile(0.80)`, no floor | 4,122 | **+2.64** | **3.31** |
| index-based top 20%, no floor | 3,202 | +1.87 | 2.08 |
| top 20% + absolute floor | 1,626 | +1.99 | 1.67 |
| top 10%, no floor | 1,374 | +1.48 | 1.21 |
| **LIVE** — top 10% + absolute floor | 804 | +1.87 | **1.28** |

**Direction is positive in all five. Significance is not.** t ranges **1.21 to 3.31**, and the live
flag's own definition reaches **1.28 — not significant.**

**Two things I have to own here:**

1. **The published figure is the most favourable of the variants.** I did not pick it to maximise t — I
   reused `size_flags.py`'s existing definition — but the effect of that choice is that **t = 3.31 sits
   at the optimistic end of a 1.21–3.31 range**, and I reported it as the result without knowing a
   range existed.
2. **Even two "top 20%" definitions disagree.** `pandas.quantile(0.80)` interpolates; indexing a sorted
   list at `len//5 - 1` does not. That alone moves n from 4,122 to 3,202 and t from 3.31 to 2.08. **A
   finding that moves this much on a cut-point convention is weaker than I presented.**

## 3. What is still true

- **The sign is robust.** Every variant is positive, +1.48 to +2.64 pp. Crowded funding is associated
  with the stop being hit more often; that direction held through 17 leave-one-out tests and a
  calibrated placebo on the published definition.
- **The live flag is not refuted — it is underpowered.** At 804 flagged rows the standard error is
  ~2.3× the published version's, so t = 1.28 with a point estimate 71% the size is **consistent with
  the same underlying effect**, just unmeasurable at that sample. **"Untested at this definition" is
  the honest label, not "doesn't work."**

## 4. 🔧 Recommendation — change the flag, not the claim

**Align the live flag to the tested definition: top quintile per date, no absolute floor.** One-line
change to `scanner.py:160-162`.

**Why that direction rather than softening the terminal text:**
- The quintile definition has **4,122 observations, a calibrated placebo, and 17/17 leave-one-out
  survivals** behind it. The decile definition has none of that and cannot be verified for months.
- A flag that fires on 5% of coin-days will show the owner a tested label he almost never sees, and
  when he does see it the supporting number was measured on something else.
- **If the flag stays as-is, the terminal text must drop the number and the "survived red team" claim**,
  because neither applies to the condition being flagged.

**Either is defensible. What is not defensible is the current pairing** — a strict flag carrying a
number from a loose one.

## 5. The scanner's other flag texts, now auditable

Checked while I was in there. **These are accurate and honestly worded:**

- `vol_expanding` — *"the expected-move forecast already includes this (adds +1%, t=0.24): use the
  expected move instead"* ✅
- `volume_surge` — *"it just failed the red team's bar (p=0.027 vs 0.025)"* ✅ correct, and admirably
  specific about a near-miss
- `above_20d_high` — *"the 20-day high meant nothing either way"* ✅ matches `LEVELS.md`
- `on_20d_low` — *"too few clean cases to measure anything"* ✅ correct after the spot contamination fix
- `squeeze` — *"breakout direction is not predictable from this"* ✅

**One label fix:** `funding_hot`'s text cites **`laptop FUNDING_SIZING`**. The doc is **`FUNDING_STOP.md`**.

## 6. The lesson, which is the fifth instance of one pattern

**I measured a flag from its docstring for two separate studies and never read the code.** Two red teams
flagged that the definitions were unauditable; I treated that as a documentation gap rather than a
threat to the results. It was a threat to the results.

**Rule, now in `REGISTER.md`: never test a production flag from its description. Read the implementation
or state that you could not.** This is the same family as "read the baseline prior work actually used" —
which I had already written down after the volatility straw man, and then did not apply here.

## Limits
- All five variants use the same panel, outcome and matching, so the comparison between them is clean.
- `funding_h` in `scanner.py` is an hourly rate; my panel sums funding to a daily figure, so I converted
  the floor as `24 × 1.25e-5`. If the live `funding_h` is already a daily or 8-hour figure, the floor row
  above is wrong — **worth the server confirming the unit.** The decile-vs-quintile finding is unaffected.
- This does not re-examine `SIZE_FLAGS.md`'s +7.7%, which used the same quintile definition and therefore
  inherits the same issue. **That number should be treated as definition-dependent too until re-run.**
