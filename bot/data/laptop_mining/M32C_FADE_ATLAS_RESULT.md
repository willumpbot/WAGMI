# Project X part 3 - the fade-vs-run atlas: a +0.5R winner FADES ~64% of the time (the give-back is the NORM), but WHAT'S KNOWABLE AT +0.5R predicts which. An IMPULSIVE +0.5R (fast, high-volume, big-range, moving with BTC) tends to RUN; a QUIET/SLOW drift tends to FADE. All three main tells SURVIVED their confound controls. EXPLORATORY -> graduates to a sealed confirmation next.

_2026-10-15. m32c_fade.py, 22,256 scored +0.5R-reachers / 176 coins, m28 grid. Label: RUN = reached
+1.5R before giving back to <=0; FADE = gave back to <=0 first. EVERY circumstance uses only bars <= the
+0.5R bar (strictly pre-peak; no look-ahead). Base P(FADE) = 0.642._

## 1. The give-back is the norm, now quantified
A trade that reaches +0.5R gives it ALL back before reaching +1.5R **64% of the time**. So the owner's
frustration ("I keep giving winners back") is not bad luck - it is the base rate. That is WHY a
protective exit (ladder / breakeven) feels necessary.

## 2. The pre-peak tells (P(FADE) by bucket; CI clustered by coin; base 0.642)
| circumstance at +0.5R | fades MORE (ladder harder) | fades LESS (let it run) |
|---|---|---|
| **volume surge** at the +0.5R bar | low volume 0.696 | **high volume 0.573** |
| **max bar-range** into +0.5R | small range 0.674 | **big range 0.582** |
| **velocity** (bars to +0.5R) | slow grind 0.669 | **fast spike 0.611** |
| **BTC co-move** (24h) | against BTC 0.682 | **with BTC 0.624** |
| **time-of-day** (UTC) | US 16-23h 0.714 | Asia 0-7h 0.617 |
| vol tier (ATR) | high-ATR 0.662 | low-ATR 0.598 |
| position vs 20d trend | (0.648 vs 0.636 - weak) | |

## 3. Adversarial controls - the three main tells SURVIVE their confounds
- VELOCITY vs remaining-window: a slow +0.5R leaves fewer bars to reach +1.5R (mechanical). Restricting
  to b05<=12h (>=36 bars remain for ALL): fast 0.609 [0.600,0.619] vs slow 0.659 [0.648,0.669] - STILL
  separates. Not a window artifact.
- TIME-OF-DAY vs regime: US-fades holds within BOTH BTC-up (US 0.704 vs Asia 0.593) and BTC-down (US
  0.723 vs Asia 0.638). Not just the sample's down-drift.
- VOLUME-SURGE vs vol-tier: high-surge beats low-surge WITHIN low-ATR (0.537 vs 0.695) AND high-ATR
  (0.616 vs 0.697). Not a restatement of coin volatility.

## 4. The unifying read + the conditional signal (the prize)
They all say the same thing: an IMPULSIVE +0.5R - reached fast, on a volume surge, a big range bar,
moving WITH BTC - has real momentum and RUNS; a QUIET, slow DRIFT to +0.5R is weak and FADES. So the
lever is not a fixed exit dial (those are all null on the mean) but a CONDITIONAL one: **ladder harder /
take the give-back protection on a quiet, slow +0.5R; give an impulsive, high-volume +0.5R room to run.**
This directly informs the owner's M31 give-back decision (Trim vs Hold) and WHICH trades deserve
quarters vs the runner.

## 5. Status + next
EXPLORATORY. The signal passed the FIRST adversarial round (confound controls above). Per the project
standard it now GRADUATES to a SEALED confirmation: freeze the rule (e.g. "high volume-surge OR fast
velocity at +0.5R => let run, else ladder") on the ORIG17/early coins, test on the held-out split, with
a 3-judge panel, before it informs anything live. The effect sizes are modest (~0.10-0.16 in P(FADE))
and n is large, so it is measurable - but a shadow study never writes a live gate, and the owner's go is
needed for any rule.

## Owner rules (one number each)
1. Giving a +0.5R winner back is NORMAL - it happens ~2 of every 3 times. (base fade: 64%)
2. The tell is HOW you got there: a fast, high-volume punch runs; a slow, quiet drift fades. (quiet
   drift fades 70% vs impulsive 54%)
3. So protect (ladder/trim) the quiet ones; give the punchy ones room. US-afternoon +0.5R moves fade
   the most. (US-session fade: 71%)
