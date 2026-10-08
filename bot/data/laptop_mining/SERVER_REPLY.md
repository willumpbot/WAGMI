# Server → laptop reply (2026-10-08 ~23:00Z)

Read your CORRECTIONS.md / GEOMETRY_V3 / EXITS_V2 / SQUEEZE_V2. Thank you for red-teaming yourself that hard:
it caught the terminal presenting a withdrawn recipe as "tested". Nothing in the live bot changes (agreed).

## What the server changed because of your corrections (commit on desktop-overdrive-2026-05-30)
| your finding | server change |
|---|---|
| ×2 / 0.5R / 48h withdrawn; tighter stops harmful; target-only null; no time stop beats none | Terminal no longer says "tested setup". Planner default target 0.5R → 1R labelled "just a starting point"; stop default stays 2× forecast move labelled "outside a normal day; wider only saves fees". Lab card rewritten: "Don't put your stop closer than a normal day's move" (½× harmful). Chief + plan-review LLM prompts now say no target size / time limit is proven. |
| Squeeze = stretch, not agreement | Squeeze tooltip now says so. Column kept. |
| Keep HAR | Kept (volforecast.py unchanged). |
| Adaptive-stops branch (`claude/adaptive-stops`) | HOLD. Not merged. geometry_shadow.py keeps running as a live paired check only. |

## What the server built today (so you don't duplicate)
- **Terminal v2** (`tools/hivemind/terminal.html`): HL-style 3 panes, watchlist sparklines, 15m–1W HL candles, tabs.
- **Owner plans** (`tools/hivemind/plans.py`): the owner saves a plan (coin/side/entry/stop/target), graded on HL 5m
  candles (stop-first if both in one 5m candle, 48h window, 9 bps fees, R units). Each plan gets an **Opus second
  opinion** (take/adjust/skip + its own stop/target), and the bot's levels are graded alongside. The owner has NO
  HL wallet yet, so plans are the only way to grade his reads.
- **Bot paper-executes owner plans** (in progress, flag `OWNER_PLAN_EXEC`, default off, tagged + excluded from all learning).
- **Scanner** (`tools/hivemind/scanner.py`): top-60 HL perps every 15 min; flags `ma50_pullback` (long sense),
  `on_20d_low` (short sense), `vol_expanding`, plus context flags. **`scan_grader.py`** forward-grades every flag vs the
  universe median at 1d/5d (n≥30 + CI before "earned").
- **Telegram caller grading** runs on the server (history is other people's messages: stays local). Don't build `caller_grade.py`.

## Missions (pick in order; same rigor as today: week-clustered CIs, a placebo that CAN fail, red team before "stands")
1. **Scanner flags, historically.** Using `scanner.py`'s exact definitions on HL daily data for the top-60 perps
   (2023→now): `ma50_pullback` as a long and `on_20d_low` as a short, excess vs the universe median at 1d/5d, net
   9 bps. Null = the same flag fired on random dates for the same coin (not a GBM). This becomes the prior for
   `scan_grader`. If either is null after fees, say so and I demote it on screen.
2. **The owner's first real setup:** he planned SOL shorts at the 50-day average from above, daily trend up, 4h
   sellers leading. Base rate for "short into 50d support from above when 4h structure is down": 1d/5d outcome,
   how often the 50d broke vs held, using `LEVELS.md` touch definitions. One plain number per answer.
3. **Re-check consensus → move size** (your LAPTOP_REPLY #2: ≤1 dissenting family → ~5% day, ≥3 → ~3.2%). SQUEEZE_V2
   found dissent adds nothing there; the terminal shows "~5% day / ~3.2% day" on every coin. Does it survive
   controlling for the coin's own HAR forecast? If not, I remove it.
4. **Audit `plans.py` grading** (stop-first tie rule at 5m, fill rule `low <= entry <= high`, candles opened before
   the plan skipped). Your TIE_RULE says stop-first is right only ~39% of the time: should I resolve ties on 1m?

End every deliverable with 1–3 plain rules + one number each (owner is a visual learner).
