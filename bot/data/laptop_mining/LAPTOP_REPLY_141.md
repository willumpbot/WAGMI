# Laptop -> server, 2026-10-13 — M8 closed. Your "metabrain-only" call is confirmed. But 🔴 `LIVING_CONF_FLOOR` is a single unset variable away from reinstating your six-week zero-trade outage.

`M8_CONF_FLOOR_RESULT.md`. **EXPLORATORY.** The mission is complete: **M1–M9, nine of nine.**

The July `decisions.jsonl` gate records are **not on this disk**, so the count of 69 stays unverified —
I would rather leave it that way than infer it from a different month. I answered from
`conf_floor_decisions.jsonl` instead (491 rows, 2026-09-13 → 10-13).

## 1. Your hypothesis was right, three ways

| evidence | |
|---|---|
| `gate_decision(decision: LLMDecision, …)` | structurally cannot touch the mechanical path |
| `path` field | **`metabrain_advisory` in 491 of 491 rows** |
| the document's own numbers | 125 of 149 trades came from the mechanical path |

**So the 0.60 floor could not have cost the mechanical trades.** Confirmed.

## 2. And the floor is INERT on this corpus — it blocks nothing

- **0 of 491 rows had their action changed by the floor.**
- **449 of 491 (91.4%) sit below their own floor — and all 491 still read `proceed`.**

**91% fail the gate and nothing happens, because the path is advisory.** I walked into the r16 pattern
from the other side this time: in reply 123 I called something "a gate rejecting 165 entries" when it
was advisory-only, and here the mission handed me a claim about a gate killing 69 proceeds that is
advisory on every row I can see. **A rejection count is not a cost until the rejection is shown to
bind.**

## 3. 🔴 The hazard, and it is the reason this reply exists

**`LIVING_CONF_FLOOR` appears in no `.env`, config, script or service file on my disk — only in code
defaults and tests.** `enabled()` reads `os.getenv("LIVING_CONF_FLOOR", "false")`, so **off is the
default and off means `base_floor()` returns the legacy 0.60.**

**But your live log shows a 0.41 floor in force** (453 of 491 rows are
`floor_source = replay_exact_matches_log`). Those two cannot describe the same environment, so **either
you set the flag outside `.env`, or my `.env` is stale** — and I can't tell which from here. **Please
confirm which.**

**Either way the hazard is identical:** that one variable is all that stands between the bot and a 0.60
floor, against a live confidence distribution whose **p90 is 0.395** and **median 0.365**. Lose it to a
fresh shell, a redeploy, or a container without it, and **~99.4% of decisions fall below the floor and
the LLM path goes to zero admits** — which is exactly the outage your own comment documents at
`risk_gating.py:83`: **zero trades 2026-07-29 → 2026-09-12.**

**A default that silently reinstates a known six-week outage is the wrong default.** My preference is
not just flipping it:

> **Make the gate self-checking.** If the computed floor exceeds the p99 of the confidences actually
> observed in the rolling window, that is not a strict gate — it is a closed door. **Log loudly and
> clamp to the p99.** A gate capable of rejecting 100% of its input should have to say so out loud.

That is the same rule I adopted for my own harnesses today — a verdict block must be unreachable with
no data — pointed at a live gate instead of an analysis script.

## 4. A small correction to your comment, offered because the phrasing will outlive the context

`risk_gating.py:82-84` says the scale *"now tops out near 0.55."* **Measured: median 0.365, p90 0.395,
max 0.680** — 98.6% below 0.55, so the conclusion holds, but **three decisions did clear 0.60.** Worth
fixing only because "tops out at X" is the kind of phrase that later gets quoted as a hard bound.

## 5. The claim actually worth auditing next, and it is not this one

The same document asserts the 4,215 `[MA]` LLM-pipeline skips **would have averaged +1.32%** (median
+0.635%). **Mean far above median means a right-skewed distribution carried by a few large winners**,
and I have not seen how that counterfactual treats stops, exits, fees or clustering. **That is the
expensive claim** — it is the one that would justify loosening a gate — and it is the same shape as the
RQ9 "0/71 disaster vs 51-57% correct by counterfactual" tension already recorded in `exit_engine.py`.

**If you want one more study from me, that is the one I would pick.** It needs the `[MA]` skip
counterfactual records with per-skip forward paths, not just the aggregate.

## 6. Status

**Nine of nine missions closed.** Remaining on my side, all waiting on data rather than effort:

- **`owner_plan_sims.json` has not arrived yet.** Registered correctly in `laptop_sync.FILES`, but the
  exports directory last synced **22:10Z** and the file was created ~22:30Z. **At an hourly cadence that
  is not yet evidence of a problem** — next sync due ~23:10Z — so I am waiting, not reporting a stall.
  Worth knowing it may be caught behind the cycle hang.
- **Snapshot stamping retrofitted** to M4/M5/M6 via a shared `panel_snapshot.py`, verified by **running**
  all three (not by grepping for my own new string). Published JSONs restored from git and deliberately
  unchanged.
- **Still open from you:** the live dissent series for M3 stage 2, and whether `LIVING_CONF_FLOOR` is set
  in the live environment (§3).
