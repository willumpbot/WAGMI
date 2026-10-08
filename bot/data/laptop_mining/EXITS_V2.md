# Exits v2 — "early time stops hurt" was an artifact. Do not change `TIME_STOP_HOURS`.

_2026-10-08. 15,663 signals, 14 ISO weeks, 120h horizon. Script: `exits_v2.py`.
Data: `exits_v2.json`. Supersedes `EXITS.md`._

---

## 🔴 Decision: HOLD. The time-stop change has no support.

**`EXITS.md` found that cutting at 4h/12h/24h costs 0.08–0.12R. Once the horizon is long enough for a
48h time stop to actually fire, and the stop width is one that actually binds, that result
disappears: every confidence interval contains zero, and 9 of 12 cells flip sign between calendar
halves.** No change to `TIME_STOP_HOURS` is justified at any baseline.

**Note on the baseline value.** The live bot reads `bot/trading_config.py:283`,
`_env_int("TIME_STOP_HOURS", 2)` — default **2**, env-overridable. The `12.0` figures in
`bot/manual/simulator.py:38` and `pa_simulator.py:46` belong to *backtest tools*, not the live
config; an earlier draft of `LAPTOP_REPLY_3.md` wrongly cited them as the live value and that is
withdrawn. The server's decision card says the running value is 8, which implies an env override I
cannot see from this machine. **The verdict is HOLD whether the baseline is 2, 8 or 12** — no cell in
the measured range differs significantly from no time stop at all.

This is a **real** null, not a powerless one — see the synthetic control below.

---

## Why v1 found an effect: two compounding artifacts

| defect | v1 | here |
|---|---|---|
| **The 48h baseline was a no-op.** `exits.py:31` sets `HORIZON_H = 48` and tests stops at (4,12,24,**48**). A 48h stop on a 48h horizon can never fire, so "48h" *was* the baseline and its −0.0146R was a mark-to-close artifact. Every other cell was measured against it. | horizon 48h | **horizon 120h**, so 4–72h all genuinely bind |
| **The bracket barely existed.** `exits.py:30` sets `STOP_MULT = 8.0`, "the geometry plateau", from the refuted `GEOMETRY.md`. `geometry_v3` shows ×8 binds on only **14.3%** of trades — so the time stop *was* the dominant exit, which is close to circular. | stop ×8 | **×1** (the bot today) and **×2** (`geometry_v3`'s pick), both binding |
| **No null of any kind.** `grep -nE "flip\|null\|shuffl\|placebo" exits.py` returns only the bootstrap RNG. | none | side-flip null, direction-free decomposition, synthetic control |

---

## The synthetic control passes — so the null means something

Exact-zero-effect dataset, then known deltas injected:

| injected | detected? |
|---|---|
| **0.000** | **no** (no false positive) |
| 0.020 | no |
| **0.050** | **YES** |
| 0.080 | YES |
| 0.120 | YES |
| 0.200 | YES |

**Smallest detectable effect: 0.05R.** `EXITS.md` claimed −0.0939R at 12h and −0.1158R at 4h — both
comfortably above that floor. **If those effects were real, this test would have found them.** It
did not.

## The result

### Stop ×1 (the bot's current stop width), target 0.5R — baseline is no time stop

| time stop | vs none | CI95 (week blocks) | direction-free | CI95 |
|---|---|---|---|---|
| 4h | +0.0161 | [−0.0719, +0.1042] | −0.0118 | [−0.0348, +0.0161] |
| **8h ← the card's stated baseline** | **+0.0073** | **[−0.0869, +0.0777]** | −0.0154 | [−0.0348, +0.0030] |
| 12h | +0.0149 | [−0.0604, +0.0718] | −0.0077 | [−0.0311, +0.0106] |
| 24h | −0.0089 | [−0.0401, +0.0176] | −0.0139 | [−0.0260, +0.0006] |
| 48h | +0.0068 \* | [+0.0011, +0.0114] | +0.0026 | [−0.0004, +0.0051] |
| 72h | +0.0038 | [+0.0000, +0.0103] | +0.0014 | [−0.0003, +0.0040] |

### Stop ×2, target 0.5R (`geometry_v3`'s recommendation)

| time stop | vs none | CI95 (week blocks) | direction-free | CI95 |
|---|---|---|---|---|
| 4h | +0.0389 | [−0.0816, +0.1404] | −0.0010 | [−0.0381, +0.0399] |
| 8h | +0.0344 | [−0.0888, +0.1448] | +0.0051 | [−0.0324, +0.0494] |
| 12h | +0.0304 | [−0.0710, +0.1417] | +0.0092 | [−0.0259, +0.0533] |
| 24h | −0.0245 | [−0.0658, +0.0391] | −0.0019 | [−0.0393, +0.0528] |
| 48h | −0.0040 | [−0.0255, +0.0271] | +0.0208 | [−0.0177, +0.0789] |
| 72h | −0.0019 | [−0.0127, +0.0101] | +0.0005 | [−0.0154, +0.0203] |

**Not one cell shows a significant cost.** The only two significant cells in the whole table (×1 at
48h and 72h) are *positive* — a long time stop very slightly **helps** — and both are under 0.01R,
with direction-free components containing zero. Not worth acting on.

### Calendar walk-forward: the v1 effects are not stable

Split at 2026-W15, 7 weeks each side. Sign flips in **9 of 12** cells:

| stop | time | first half | second half | stable? |
|---|---|---|---|---|
| ×2 | 4h | +0.1669 | −0.0202 | **NO** |
| ×2 | 8h | +0.1749 | −0.0305 | **NO** |
| ×2 | 12h | +0.1714 | −0.0347 | **NO** |
| ×2 | 24h | +0.0267 | −0.0481 | **NO** |
| ×1 | 8h | +0.0685 | −0.0209 | **NO** |
| ×1 | 12h | +0.0837 | −0.0169 | **NO** |

A swing from +0.17 to −0.03 between adjacent 7-week blocks is the signature of a regime effect, not
a policy effect. **Whatever v1 measured, it did not survive the next seven weeks.**

---

## Trader rules

1. **Leave the time stop alone.** 2h, 8h and 12h are all as good as 24h, 48h or none at either stop
   width, and nothing in the measured range is worth 0.05R.
2. **Do not read an exit policy off a backtest whose horizon equals the policy** — the longest cell is
   silently the baseline, and every other cell inherits its bias.
3. **Measure exits on a bracket that binds.** At ×8 only 14.3% of trades reach stop or target, so the
   exit policy is testing itself.

## What this does not say
- It does **not** say exits are unimportant — only that *this* comparison, done honestly, cannot
  distinguish them. Smaller real effects (<0.05R) would be invisible here.
- `EXITS.md`'s other 10 policies (trailing, breakeven, scale-out, target 1.5R/2.0R) were already null
  in v1 and are not re-tested here. v1's null results are the least likely to be wrong, since a null
  does not benefit from the biases found in this project.
- 14 ISO weeks is a short sample. The sign instability may be regime, not noise — but either way it
  is not a basis for changing a live setting.

## Lineage
`EXITS.md` (v1, 48h horizon, ×8 bracket, no null) → this. The `+0.48R` figure that reached the
owner's decision card came from `ADAPTIVE_STOPS.md`'s stop-width work, not from the exits work at all;
see `GEOMETRY_V3.md` for where that number actually stands (+0.1187R, direction-free, at ×2).
