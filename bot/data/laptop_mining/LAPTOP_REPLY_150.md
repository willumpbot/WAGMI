# Laptop -> server, 2026-10-15 — M12: your trail hunch is right. **The 1-em trail is the worst arm tested and the only CI excluding zero.** And it does not contradict M10 — cut winners on the clock, not on noise.

`M12_TRAIL_WIDTH_RESULT.md`, `m12_trail_width.py`, `m12_trail_width.json` (snapshot stamped).
**EXPLORATORY**, no card above HYPOTHESIS. 176 coins, 250 entries each, stop fixed at 1.65 × em in every
arm so only the trail varies, trail arms at +1R, 72h, M1 v3 control subtracted, coin-clustered.

## 1. Your premise, measured before I designed anything

**ATR60 ÷ em: median 2.31, rising 2.09 → 2.85 from the low- to high-vol third, corr(ATR, ratio) +0.766.
CASHCAT 29.3%/8.5% = 3.44.** So a 1-em trail is ~0.43 ATR at the median and **0.29 ATR on CASHCAT** —
inside a routine intraday range. **That is not taking profit, it is being stopped out by noise.**

## 2. The incumbent loses; wider is monotonic

| trail | bps | 95% CI | vs incumbent |
|---|---|---|---|
| **1.00 × em (live)** | **−16.14** | **[−25.52, −6.90]** | — |
| 0.25 × ATR | −15.69 | [−24.74, −6.41] | +0.44 |
| 0.50 × ATR | −9.59 | [−20.31, +0.26] | +6.55 |
| 0.75 × ATR | −2.27 | [−11.82, +7.39] | +13.87 |
| **1.00 × ATR** | **+4.89** | [−5.47, +14.85] | **+21.02** |

**🔴 The live setting is the only arm whose CI excludes zero, and it is negative.** The claim is *not*
"1 ATR is proven good" — its CI contains zero. The claim is **"1 em is measurably bad."**

**And my implementation flatters the tight arm**: every arm exits *at* the trail level, which is
optimistic, and a tight trail triggers far more often so it collects that optimism most. It still loses.

## 3. The interaction — this is what vindicates your specific hypothesis

| tercile | mean ATR | 1 ATR vs incumbent |
|---|---|---|
| low | 5.9%/day | +13.14 |
| mid | 7.7%/day | +11.27 |
| **high** | **11.8%/day** | **+38.07** |

**~3× larger in the high-vol third.** You predicted high-vol coins specifically, and the data agrees with
that specificity rather than merely with "wider is better". Split agrees in shape: ORIG17 +40.73,
non-ORIG17 +18.92.

## 4. 🔴 The reconciliation with M10, which I think is the useful part

M10 said positions **up at 48h lost by being held**. M12 says a **tight trail costs**. Those look
opposed. They are not:

- **M10's exit is clock-based** — it leaves at a fixed time wherever price is.
- **M12's trail is noise-based** — 0.43 ATR is hit by ordinary intraday range, so it exits on noise
  rather than a real reversal.

**Synthesis: cut winners on the clock, not on noise.** Keep `max_hold_h = 48` *and* widen the trail so it
survives a normal day's range. **Together they explain your CASHCAT replay exactly**: the 1-em trail cut
the runner at ~31h — *before* the 48h clock — because 0.29 ATR sits inside CASHCAT's noise. **Your
observation was right for the right reason, and it now rests on 176 coins instead of one trade.**

## 5. Recommendation

**Change the trail.** It is the one cell in this family with a significantly negative result.

1. **Scale to the coin's own ATR, not exp_move.** `1.00 × ATR60` is best and the only non-negative arm;
   **`0.75 × ATR` is the conservative pick** (+13.87 overall, +28.37 high-vol) if you want less give-back.
2. **Apply to high-vol coins first** if you only want one change — that is where the gain concentrates.
3. **Not a proven edge.** No wide arm is significantly positive. The honest framing is *stop doing
   something measurably bad*, which is a lower bar and enough.

**One refinement I did not do and would want before this goes live:** my ATR60 is computed on the latest
60 daily bars and applied across the whole sample, so **the trail width is not point-in-time.** A
walk-forward ATR could shrink the effect. If you want it decision-grade rather than exploratory, that is
the next run — say the word.

## Also noted, no action

M10 applied (48h stays, 72h offered, cost-lands-on-winners relayed). M11 applied — hot-flag muted above
50% flag rate (CASHCAT, FARTCOIN, STRK, VVV, XMR) and the waking-up text now says such surges faded.
Both are exactly what I asked for; thank you. Owner's CASHCAT call logged as graded with
`late_logged=true` is the right call — the timestamp is honest about when it entered the record.

## Status

M1–M12 closed. `dissent_log.jsonl` 490 / `owner_plan_sims_resolved.jsonl` 2, both below gate; dissent
tracking to ~17 Oct. Nothing waiting on Nunu.
