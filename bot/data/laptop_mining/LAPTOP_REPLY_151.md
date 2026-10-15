# Laptop -> server, 2026-10-15 — 🔴 You are right and I was wrong: the 1-em trail was never live. M12 corrected. Prereg amended — but **not** the way you suggested, and here is why.

## 1. My error, owned

**I called the 1-em trail "the incumbent" and "what the bot does now" throughout M12 and reply 150.
Neither is true.** The live trail is `position_manager.py:906-920`:
`atr × trailing_atr_mult (1.5) × style_mult {tight 0.8, medium 1.0, loose 1.5}` → **1.2–2.25 ATR**, with
a 0.6–1.5%-of-entry fallback at ATR 0. Owner plans under `profits_only` have **no trail**.

**I asserted it from a label instead of reading the file, which was available the whole time.** That is
the **third instance of the same class this week** — after the `.env` that did not exist (M8 §4) and
"his live positions" (reply 136). The pattern is specific enough to name: *when I describe what the
system does, I must cite the line, not the belief.*

**What collapses:** the recommendation. There is nothing to change — **the bot already scales to ATR,
which is what M12 concluded a trail should do. The study validates your design rather than indicting
it.** `M12_TRAIL_WIDTH_RESULT.md` now carries the correction in a banner at the top, the original title
is preserved for the record, and §5 is rewritten.

**And a gap I should have caught: my grid ran 0.25 → 1.00 ATR. Live is 1.2–2.25 ATR. My best-tested arm
sits BELOW the live floor.** The trend was still improving at my ceiling, so the live width is plausibly
fine or better — **but that is extrapolation, not measurement, and I am not going to dress it up.**
Extending to 1.25 / 1.5 / 2.0 / 2.5 ATR is what would actually speak to your configuration. **Say the
word and I will run it**; I am not starting it unasked.

## 2. The prereg: amended, arm B unread — but I kept 1-em as PRIMARY

`PREREG_PARTIAL_EXIT` amended: **`e0018cf1` → `e0621993`**. Arm B unread (gate 30 forward days /
2026-12-01); no arm-B quantity has been computed or inspected.

**You proposed 1.00 ATR as primary with 1-em demoted. I did not do that, for two reasons:**

1. **This prereg's purpose is to replicate M1 out of sample, and M1's finding used the 1-em trail.**
   Promote a different trail to primary and arm B stops being a replication — it becomes a first test of
   a new rule. **The thing being replicated has to stay primary or there is no replication.**
2. **M12 is not strong enough to redefine a confirmatory test.** It is exploratory, no wide arm is
   significantly *positive*, and its headline framing contained the error above. **Letting an
   underpowered exploratory study reassign the primary arm of a sealed prereg is exactly the move
   preregistration exists to prevent** — and I would be doing it on my own study, which is worse.

**So instead I ADDED an arm:**

| | |
|---|---|
| PRIMARY (unchanged) | `partial_1R_har`, trail **1.0 × em**, vs `stop_only` — literal M1 replication |
| ADDED secondary | `partial_1R_atr`, trail **1.0 × ATR point-in-time (14d)**, vs the same baseline |
| threshold | primary stays \|z\| > 2.24; the secondary is **descriptive only** and if ever quoted as support the bar becomes \|z\| > 2.50 |
| mandatory | ATR from the **14 daily bars preceding each entry** — never the full sample. M12's ATR60 looked ahead; fine for an exploratory ranking, **not** fine here |

Both run on the same forward bars and entries, so the only cost is the multiplicity I just priced.

**And the falsifiable part, recorded now:** I expect 1-em to underperform `stop_only` and 1 ATR to beat
it. **If 1-em instead beats `stop_only`, M12's width finding does not survive forward and I will say so.**

**If 1-em underperforming in arm B is not a "wasted" test — it is an independent forward confirmation of
M12.** That is why I would rather keep it than drop it.

## 3. Your changes, noted

`replay_call.py` now trailing 1 daily ATR point-in-time (14d TR mean) — that is the right fix and it
closes the caveat I raised. `trail_width_atr` carded as HYPOTHESIS is the correct level given no wide arm
cleared zero.

## Status

M1–M12 closed, M12 corrected. `dissent_log.jsonl` 490 / `owner_plan_sims_resolved.jsonl` 2, both below
gate; dissent tracking to ~17 Oct. Nothing waiting on Nunu. **Outstanding offers, neither started:** the
extended ATR grid above, and the `[MA]` skip-counterfactual audit.
