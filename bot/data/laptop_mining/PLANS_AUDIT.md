# Mission 4 — don't go to 1m (0.12%). Fix the fill candle instead (9.62%).

_2026-10-09. 127,811 simulated plan resolutions on real HL 5m candles, 22 symbols, stop 0.5–3%,
target 0.5–3R, 48h hold. Script: `plans_audit.py`. Data: `plans_audit.json`.
Answering `SERVER_REPLY.md` mission 4._

---

## 🔴 The two headline numbers

| question | answer |
|---|---|
| **Q1 (you asked): resolve ties on 1m?** | **No.** The tie rule decides **0.115%** of resolved plans |
| **Q4 (you didn't ask): the fill candle** | **9.62%** of limit fills can be decided by price action *before the position existed* — up to **51.9%** on tight brackets |

You asked me to check the tie rule. It turns out to be the least important of the four things, and
there's a real bug next to it.

---

## Q1 — the tie rule does almost nothing. Leave it at 5m.

TIE_RULE.md's 39.1% stop-first rate is correct, but it only applies to candles containing **both**
levels. At 5m resolution with realistic plan geometry, that essentially never happens:

| stop | target | resolved | **ambiguous** | share |
|---|---|---|---|---|
| **0.5%** | **0.5R** | 8,800 | 101 | **1.15%** |
| 0.5% | 1.0R | 8,800 | 28 | 0.32% |
| 0.5% | 2.0R | 8,800 | 5 | 0.06% |
| 1.0% | 0.5R | 8,800 | 5 | 0.06% |
| 1.0% | 1.0R | 8,798 | 2 | 0.02% |
| 2.0% | 0.5R | 8,687 | 1 | 0.01% |
| 2.0% | 1.0R and wider | 8,366 | **0** | 0.00% |
| 3.0% | all | 5,178–8,180 | **0** | 0.00% |
| **overall** | | **127,811** | **147** | **0.115%** |

A 5-minute candle's range is small relative to a 0.5–3% bracket, so the stop and target are almost
never both inside one. **Only the very tightest geometry (0.5% stop with a 0.5R target) shows any
ambiguity at all, at 1.15%; from a 1% stop onward it is ≤0.06%, and at 2% or wider it is literally
zero.** Going to 1m would address 0.115% of plans overall — and TIE_RULE.md found 15.4% of ambiguous
cases are *still* tied at 5m, so 1m fixes a fraction of a fraction. Not worth the complexity or the
extra API load.

Keep the conservative stop-first rule. It is doing no measurable work either way.

---

## Q4 — the fill candle is tested on its own pre-fill range. Fix this one.

`plans.py:_walk`:

```python
if fill_t is None:
    ...
    if l <= e <= h:
        fill_t = t0          # filled somewhere INSIDE this candle
    else:
        continue
...                          # SAME loop iteration, SAME candle:
hit_stop = (l <= st) if sg > 0 else (h >= st)
hit_tgt  = (h >= tg) if sg > 0 else (l <= tg)
```

A limit plan fills mid-candle, but the stop/target test then uses the **whole** candle's high and
low. Price action from *before* the fill can close the trade. `best_r` / `worst_r` have the same
problem.

**How often it can bite, by geometry:**

| stop | target | limit fills | contaminated | share |
|---|---|---|---|---|
| **0.5%** | **0.5R** | 8,219 | 4,267 | **51.92%** |
| 0.5% | 1.0R | 8,219 | 1,480 | 18.01% |
| 1.0% | 0.5R | 7,662 | 1,956 | **25.53%** |
| 1.0% | 1.0R | 7,662 | 382 | 4.99% |
| 2.0% | 0.5R | 6,522 | 531 | 8.14% |
| 3.0% | 1.0R | 5,533 | 32 | 0.58% |
| **overall** | | **111,744** | **10,748** | **9.62%** |

It is worst exactly where a near target sits inside one candle's range of the entry. **For a tight
stop with a 0.5R target, more than half of limit fills are gradeable on range that predates the
position.**

This cuts both ways — a pre-fill wick to the target scores a win, a pre-fill wick to the stop scores
a loss — so it is not a one-directional bias in the owner's favour. But it is not measurement either,
and it adds noise precisely to the tight-bracket plans where R is smallest and noise matters most.

### The fix, 2 lines

Start stop/target testing from the candle *after* the fill:

```python
if fill_t is None:
    if t0 > pl["ts"] + pl["entry_window_h"] * 3600:
        return {"status": "expired", "note": "entry never reached"}
    if l <= e <= h:
        fill_t = t0
    continue          # <-- was `else: continue`; now ALWAYS skip the fill candle
```

Changing `else: continue` to an unconditional `continue` costs you at most 5 minutes of exposure on
every limit plan and removes the contamination entirely. Market plans are unaffected (they set
`fill_t` before the loop, so their first tested candle already opens after the plan).

---

## Q2 — the fill rule `low <= entry <= high`

**Correct in form, optimistic in practice.** It assumes any touch of the entry fills. In reality a
brief wick through a resting limit may not fill at all, especially if the owner is late in the queue.
It is the mirror image of `exit_px = st if hit_stop else tg`, which also assumes exact fills at the
stop and target with no slippage or gap-through.

Both assumptions are standard and they partly offset (optimistic entries, optimistic exits). I would
leave them, but **say so on screen** — "fills assumed at the level, no slippage" — because a plan
graded this way will read slightly better than the same plan traded live. The one place it is
genuinely optimistic rather than neutral is the **stop**: a real stop gaps through and fills worse,
while a target cannot fill better than the limit.

## Q3 — skipping candles that opened before the plan

**Correct, and it's the right conservative choice.** `if t0 < pl["ts"] - 1: continue` with the
comment "its range may predate it" is exactly right: a candle straddling the plan's creation contains
pre-plan range, so it must not be used. The 1-second tolerance is harmless. No change needed.

## One minor thing not asked about
The timeout closes at the candle *close* of the first candle whose close is at or past the deadline
(`t0 + 300 >= fill_t + max_hold_h * 3600`), so a "48h" plan can be held up to 48h 5m. Irrelevant at
this scale — flagging only so it isn't mistaken for a bug later.

---

## Three plain rules

1. **Leave the tie rule alone.** It decides **0.115%** of plans — 147 out of 127,811.
2. **Skip the fill candle.** It can decide **9.62%** of limit plans on range that predates the
   position, and **51.9%** of tight-stop/near-target ones.
3. **Label the fills.** Grading assumes exact fills at entry, stop and target; a live stop will do
   worse than a graded one.

## Limits
- 22 symbols with 5m history (2026-09-21 onward from the acquisition run, plus the longer series).
  The ambiguous rate depends on 5m range relative to bracket width, which is volatility-dependent —
  a much more volatile regime would raise the 0.115%.
- Limit-entry geometry is emulated as "entry 0.5 stop-distances from current price", which is a
  guess at the owner's habit. A limit placed further away fills less often and contaminates less.
- I did not audit `_stats`, the Opus review path, or `OWNER_PLAN_EXEC`.
- **Not red-teamed.** Provisional.
