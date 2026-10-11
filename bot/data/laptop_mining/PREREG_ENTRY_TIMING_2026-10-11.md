# PRE-REGISTRATION — do counter-trend entries actually underperform, prospectively?

**Status: SEALED 2026-10-11, at n = 0 prospectively-recorded entries.** Written the same hour the
in-sample association was found (`ENTRY_TIMING.md`), *before* any forward observation exists, because
that association is observational and bot-selected and therefore cannot settle anything on its own.

## 1. Where this came from, including what went wrong

I predicted the opposite. Two panels show short-horizon cross-sectional **reversal**, so I predicted
the bot would be punished for entering *with* momentum. It was rewarded. The in-sample numbers:

| | against 24h momentum | with |
|---|---|---|
| trades | 75 | 219 |
| win rate | **17%** | **42%** |
| mean realized RR | −0.378 | −0.035 |

Equal-weighted over the 27 days with both arms: **+$11.35** with-minus-against, CI95
`[+2.92, +23.02]`. Win-rate slope **z = +3.99**, size-independent.

**That is in-sample and observational. This prereg is the honest test.**

## 2. Hypotheses, direction fixed now

- **H1 (primary).** Entries with `signed_mom_24h < 0` have a **lower win rate** than entries with
  `signed_mom_24h >= 0`, prospectively.
- **H2 (mechanism — the one that decides the fix).** The gap is carried by **stop-outs**: the
  counter-trend bucket shows a higher share of SL exits (in-sample: 57% vs 37%). If H1 holds and H2
  holds, the indicated fix is **stop placement**. If H1 holds and H2 fails, it is an **entry filter**.
  These are different changes and must not be conflated.
- **H0.** No prospective difference. The in-sample result was selection or regime.

## 3. Definition, fixed now so it cannot drift

`signed_mom_24h = (close_at_entry_hour / close_24h_earlier − 1) × 100 × (+1 if LONG else −1)`

computed from 1h closes on the coin, at the last closed hourly bar at or before the fill. **The
server logs this value on every entry from now on.** A trade with no 24h of prior candles is
excluded, not defaulted to zero.

## 4. Statistic and bar

- **Primary:** difference in win rate between the two buckets, with a **day-clustered** bootstrap
  (the clustering unit is the trading day, not the trade).
- **The number acted on is the equal-weighted daily block mean**, reported next to the pooled
  figure. If the two disagree, the block mean governs.
- **Two-sided α = 0.05.** One interim look only, at **α = 0.005**.
- **Reported alongside, not as the test:** mean realized RR per bucket, and the SL-share split
  for H2.

## 5. 🔴 Power, stated before any look

In-sample the gap was 25 points (17% vs 42%). At a 50/50-ish split and 80% power, detecting a gap
of that size two-sided needs roughly **60 trades per arm**; a 12-point gap needs ~270 per arm.

- **Unlock: one interim look when the counter-trend arm reaches 60 prospective trades**, at α = 0.005.
- **Full analysis at 120 in the counter-trend arm.**
- In-sample the counter-trend bucket was **25% of entries**, so 60 of them implies roughly **240
  total trades** — at the observed ~2.2 trades/day that is on the order of **three to four months.**
  **I am writing that down now so the wait cannot later be reframed as a result.**
- **Until an unlock n is reached, the only thing reported is the two arm counts** (`crunch/j2_trackers.py`).

## 6. What counts as what

| outcome | conclusion |
|---|---|
| H1 holds at the pre-stated bar **and** H2 holds | **SUPPORT** a stop-placement change; entry filter not justified |
| H1 holds, H2 fails | **SUPPORT** an entry filter |
| H1 fails to clear | **NOT A FINDING.** The in-sample result was selection or regime, and `ENTRY_TIMING.md` gets a retraction line |
| arms never reach 60 | **UNANSWERABLE at this trade rate** — reported as that, not as a null |

## 7. Constraints that hold regardless

- **No bot change on this prereg alone.** A SUPPORT verdict is an input to the owner's decision,
  never a substitute for it.
- **The bot is not altered during accrual.** Changing entry logic mid-accrual destroys the test; if
  the owner changes it for other reasons, accrual **restarts** and that is recorded.
- **Nothing here licenses re-reading the in-sample data.** It has been looked at; it is spent.
