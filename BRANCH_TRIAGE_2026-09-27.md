# Stale-branch triage — 2026-09-27

12 branches and 15 worktrees, all frozen ≤2026-07-28. Triaged against the
post-salvage `desktop-overdrive-2026-05-30` HEAD. Most are recoverable or already
recovered; one holds work that matters.

## Verdict table

| branch | status | action |
|---|---|---|
| `claude/close-path-routing` | **already merged** | safe to delete |
| `claude/measurement-integrity` | **already merged** | safe to delete |
| `claude/breakeven-ratchet` | **already merged** (0 diff) | safe to delete |
| `claude/measurement-floor` | **already merged** (0 diff) | safe to delete |
| `claude/learning-input-floor` | **superseded** — `LEARNING_INPUT_FLOOR` is already in the tree (5 files) and now committed | safe to delete |
| `claude/pnl-leverage-fix` | **superseded** — `_pnl_lev` is already in the tree (3 files) and now committed | safe to delete |
| `claude/exit-discipline` | **unrecovered**: `CONF_BAND_SIDE_MULT`, `MFE_RATCHET` — neither in tree | see below |
| `claude/profitability` | **unrecovered and valuable** | see below |
| `claude/site-live-20260724` | +599 commits, but ~all automated data/report noise; the one real commit is `29f44287 fix(web): unblock deploy + snapshot-first data feed` | cherry-pick that one commit |

So of nine branches, six are dead weight and the work was never actually lost.
Two hold real unrecovered code. Nothing needs a 599-commit merge.

## The one that matters: `claude/profitability` (3d9d328b)

Three flag-gated fixes, none of which are in the tree
(`LLM_FIRST_QTY_DIV_LEVERAGE`, `FEE_CLEARANCE_GATE*` all return 0 files):

1. **A sizing inconsistency in the LLM-first path** — see below, this is the
   important one.
2. `llm/fee_clearance_gate.py` — skip entries whose realistic MFE cannot clear
   the fee floor. Three such trades cost −$19 in the branch's test run. This aims
   straight at the project's established #1 leak (fee drag ≈ 13% of the risk
   budget per trade).
3. `MFE_RATCHET` v2, profile-aware so the TREND right-tail survives. v1 was
   refuted for live flip (it strangled the June convexity runners); v2 claims to
   fix exactly that. Still shelf-worthy, not a tonight decision.

The commit message also names the **largest unbuilt lever in the project**:
maker-vs-taker fees. Switching to limit orders cut fees 3x ($27.82 → $9.27) and
flipped that run from −$10 to **+$8.51**. It was never built.

## Live finding: the LLM-first sizing path disagrees with every other path

Not asserted as a proven bug — flagged as a verified *inconsistency* that needs
ledger confirmation before anyone acts on it. But it is in the running code.

Three modules size a position as `risk / (stop × leverage)`:

- `bot/execution/risk.py:746` — `qty = risk_amount / (effective_stop * leverage)`
- `bot/execution/risk.py:783` — `qty = risk_usd / (effective_stop * effective_leverage)`
- `bot/execution/leverage.py:514` — `qty = risk_usd / (stop_width * effective_leverage)`

The LLM-first path does not:

- `bot/llm/agents/coordinator.py:2012` — `position_qty = risk_dollars / stop_width`

And booking then multiplies by leverage anyway:

- `bot/multi_strategy_main.py:7595` — `position_size_usd = qty * entry * lev_decision.leverage`

If that reading holds, the LLM-first path — the primary trading path — risks
`risk_pct × leverage` in realized dollar terms, while the other paths hold
`risk_pct` constant. The comment above line 2012 says the old bug was
*multiplying* by leverage and was removed; the branch's claim is that removing
the multiply was only half the fix, because downstream notional still scales by
leverage.

The July leverage migration de-leveraged the **ledgers and derived state**. It is
not clear it touched this **sizing** path. That is the thing to verify.

The branch's fix is strictly risk-*reducing* by construction (leverage is bounded
to [1.0, 20.0], so dividing can only shrink qty), and it ships default-OFF behind
`LLM_FIRST_QTY_DIV_LEVERAGE`.

### I tested it against the ledger. It cannot be settled there — and the test found something worse.

If sizing were over-risking by leverage, realized stop losses as a share of
equity would *scale* with leverage. Across 119 SL closes they do not — medians
sit between 0.011% and 0.094% with no monotonic pattern. But that test is
inconclusive, for three reasons: 79 of 119 SL closes are at leverage 1.0, where
dividing by leverage is a no-op; only 6 SL closes exist post-migration; and the
loss magnitudes are so small that the leverage term is swamped.

That last point is the finding. **Median realized risk per stopped-out trade:**

| window | n closes | median abs net_pnl | median risk, % of equity |
|---|---|---|---|
| Jun 01–30 | 132 | $4.59 | 0.42% |
| Jul 01–26 | 122 | $0.64 | **0.008%** |
| Jul 26–Aug 31 | 20 | $1.26 | 0.12% |
| Sep 01–27 | 13 | $0.16 | **0.015%** |

Intended risk is on the order of 1–2.5% of equity per trade. The bot is
currently risking about **one hundredth of that**, and the median trade now
resolves for **sixteen cents**.

### Where the sizing trace actually got to (one wrong turn, corrected)

The July root-cause fix (`SIZING_CONSTRAINT_UNITS_FIX`) **is still enabled** and
working as written. `.env` has it `true` with `MAX_RISK_PCT_CEILING=0.005` — the
deliberate 0.5% safety cap, lowered from the 0.02 it shipped at.

I first thought the defect was `stop_width_pct` arriving as zero, because the
most recent `[SIZING-CONSTRAINT]` log lines all read `stop_frac=0.0000`.
**That was wrong, and it is worth recording why.** Across the logs, 1,087 of
those lines exist and only 756 have `stop_frac=0.0000` — 331 carry real values
(0.03–0.04, i.e. 3–4% stops). I had sampled the tail and generalised.

More importantly, the zero does not change the outcome. The ceiling is
`min((remaining/100) × stop_frac, cap)`. With a real `stop_frac=0.03` and
`remaining=500%`, that is `min(5.0 × 0.03, 0.005) = min(0.15, 0.005) = 0.005`.
**The 0.005 cap binds either way.** So `stop_frac=0` is cosmetic here, not
causal — worth tidying, but not the size collapse.

### Resolved: September's tiny size is BY DESIGN, not a defect

Following the trace to the end dissolves it. The coordinator proposes healthy
size — recent logs show `risk=3.0% qty=1089.59`. Those lines fire every scan
though, and only 13 trades closed in 15 days, so proposals are not executions.

The executed trades are **deliberate probes**. From `.env`:

```
BLOCKED_GO_PROBE=true
BLOCKED_GO_PROBE_RATE=0.5        # half of gate-BLOCKED entries are re-opened
BLOCKED_GO_PROBE_SIZE_MULT=0.1   # ...at one tenth size
EXPLORATION_RISK_MULT=0.1
EXPLORATION_RISK_PCT=0.004       # 0.4% base for exploration entries
```

and `multi_strategy_main.py:8957` — `qty = qty * _probe_mult`. The probe
program went live **2026-09-12** (`tools/daily_digest.py:110`,
`PROBE_PROGRAM_START`) — the exact date trading resumed and the exact cutoff my
ledger query used.

So: 0.4% exploration risk × 0.1 probe multiplier ≈ 0.04%, against an observed
median of 0.015% (the rest is stops not travelling full width). Consistent.

**The bot is trading at probe size because that is what the drought fix does.**
It is buying forward information about gate-blocked entries, not trying to make
money on them. $0.16 a trade is the intended price of that information.

The July size collapse was a real bug and it *was* fixed
(`SIZING_CONSTRAINT_UNITS_FIX`). September is a different thing wearing the
same numbers.

### What the real question turned out to be

Not "why is size collapsed" but: **the entry gate still blocks essentially every
real entry, and it is blocking correctly on the evidence it has.** The only
trades happening are the half of blocked entries re-opened as tenth-size probes.
That is the co-pilot program working as designed — manufacturing forward
evidence because the historical corpus is exhausted.

So the honest read on "why isn't it making money": it is not sized down by a
bug, it is *deliberately not betting* while it accumulates the evidence needed
to know whether any entry edge exists. Changing that is a strategy decision,
not a bug fix. The lever, if you want dollars sooner, is
`BLOCKED_GO_PROBE_RATE` / `SIZE_MULT` — and raising those means betting real
money on entries the gate's own evidence says lose.

**I got this wrong twice before landing here** (first blaming `stop_width_pct=0`,
then an imagined dead code path). Both were over-reads of partial evidence;
recording them so the pattern is visible. It subsumes almost everything else:
at $0.16 a trade, no gate, exit rule, or edge discovery can move dollars, and
round-trip fees dominate every outcome. It also means **`LLM_FIRST_QTY_DIV_LEVERAGE`
must not be landed as-is** — it divides qty further, and qty is already ~100x
too small. Fix the collapse first; revisit the leverage consistency question
afterwards, when position sizes are large enough for it to matter.

## Why I didn't just cherry-pick tonight

All five candidate commits touch files that just received two months of
uncommitted changes (`kelly_engine.py`, `live_edge.py`, `position_manager.py`,
`coordinator.py`), so every one of them conflicts. Resolving those conflicts
means editing the working tree **the live bot is running out of**, while it is
running and unattended, on a box with ~0.4GB free RAM. Wrong time. They are
small, well-labelled, and all default-OFF, so they will land cleanly in a
dedicated worktree when someone is watching.

## Recommended order (revised after the ledger test)

1. **Nothing to fix on sizing — it resolved to intended probe behaviour.** The
   open decision instead: leave probes at 0.1x and keep buying evidence, or
   raise `BLOCKED_GO_PROBE_RATE` / `SIZE_MULT` to bet real money sooner. That is
   yours, not a bug fix. Revisit when the probe ledger clears n≥30.
2. Build the maker-vs-taker fee change. Biggest *measured* lever, never built —
   and it matters more, not less, when trades are small, since fees are a fixed
   drag.
3. Cherry-pick `29f44287` to unbreak the site deploy.
4. Land `fee_clearance_gate` shadow-on (measures, changes nothing).
5. Delete the six dead branches.
6. **Do not** land `LLM_FIRST_QTY_DIV_LEVERAGE` until item 1 is resolved — it
   shrinks an already-collapsed size.
7. Leave `MFE_RATCHET` shelved until the exit engine is deliberately reopened.
