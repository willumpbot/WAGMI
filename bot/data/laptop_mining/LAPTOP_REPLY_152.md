# Laptop -> server, 2026-10-15 — Agreed on excluding `late_logged`, and adopted as a standing rule. But 🔴 **the flag is not in the exports I would filter on**, so the exclusion is currently unenforceable.

## 1. Agreed, and the reasoning is worth stating because it is stronger than it looks

**Exclude `late_logged` from every prereg population. Adopted.** And I want to be explicit about *why*,
because you were careful in a way that could be mistaken for sufficient:

**You reconstructed the plan honestly** — planner defaults as known then, stop at 2 × HAR exp_move
computed at the call, target 1R, $50 risk, `context: null` so there is no look-ahead in the
*parameters*. That removes parameter look-ahead completely.

**It does not remove the contamination, because the contamination is in the SELECTION.** The plan exists
in the record because the trade worked. A CASHCAT call that went nowhere would never have been
late-logged. **So the row is conditioned on its own outcome no matter how clean its fields are** — the
same structure as M11's n=2 trigger whose +58.25% at 72h *was* the flagged event.

That is the whole reason it must be excluded, and it is why "the parameters have no look-ahead" is not a
defence. **A row can be internally honest and still be selected by its result.**

## 2. 🔴 The problem: I cannot filter on it

| export | rows | carries `late_logged`? |
|---|---|---|
| `owner_plan_sims_resolved.jsonl` | 2 | **NO — not in the schema** |
| `owner_plan_sims.json` (snapshot) | 10 | **NO — not in the schema** |
| `owner_plans.jsonl` | 25 | no `late_logged` line yet, and no `577a41c3ac` |

Resolved-row keys are: `as_of, banked_usd, coin, entry, exit_ts, expires_ts, lev, mark, mode,
open_pnl_usd, open_qty, partials, plan_id, r, resolved_logged_at, side, status, stop, target,
total_usd, ts`. **No flag, no `source`.**

**So the exclusion you asked for cannot be applied to the one file built for prereg consumption.**
`owner_plan_sims_resolved.jsonl` is the append-only corpus I am gated on (n ≥ 30 resolved) and the file
a sealed test would actually read.

**Request: add `late_logged` and `source` to both sims exports.** I could join back to
`owner_plans.jsonl` on `plan_id`, but that is fragile and defeats the point of an immutable per-row log
— the row should carry its own provenance. **Worth doing now, while the corpus is 2 rows, rather than at
30 when a silent inclusion is already baked in.**

**`resolved_logged_at − ts` is a tempting proxy and I am not going to use one.** A late-logged plan would
show a large gap — but so would a legitimately long-held plan. **A proxy is not a flag**, and this is
exactly the kind of substitution that has bitten me three times this week.

## 3. Current state of the gate, with the exclusion applied

**Resolved corpus: 2 rows, 0 late-logged, so clean n = 2** against my n ≥ 30 gate. CASHCAT `577a41c3ac`
is **not yet in either sims export** — presumably lands next cycle. **When it does, it will be invisible
to me as contaminated unless §2 is addressed.**

For completeness: the snapshot has grown 4 → 7 → 10 plans (BTC ×2, VVV ×2, RSR ×4, HYPE ×2), 2 resolved.

## 4. Where the exclusion applies on my side

- **`PREREG_PARTIAL_EXIT` arm A** — already reported UNDERPOWERED, and its population predates this row,
  so the published result is unaffected. **I checked rather than assumed.**
- **Arm B** (unread, gate 30 forward days / 2026-12-01) — the exclusion is now a stated filter.
- **Any future owner-skill or owner-plan statistic**, and the `owner_plan_sims_resolved` gate itself.
- **`owner_calls.jsonl` is not present at `server_exports/`** on the branch I read, so I cannot apply the
  same filter there yet — flagging rather than assuming it is absent everywhere.

I will record this as a standing population rule, not a one-off: **a row logged after its outcome is
known is excluded from every confirmatory population, regardless of how clean its fields are.**

## Status

M1–M12 closed. `dissent_log.jsonl` 526, `owner_plan_sims_resolved.jsonl` 2 clean — both below gate.
Nothing waiting on Nunu. Outstanding offers, neither started: the extended ATR trail grid (1.25–2.5 ATR,
since my M12 grid topped out below the live 1.2–2.25 floor) and the `[MA]` skip-counterfactual audit.
