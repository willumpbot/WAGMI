# WAGMI HIVEMIND - design brief (draft v1, 2026-10-13; for laptop red-team, then owner)

## 1. What it is / is not
The hivemind is the project's memory and conscience: ONE registry of everything we believe about the market and the
bot - each belief with its evidence, strength, last check, and every place it is used. When a belief weakens, every
dependent (bot rules, agent prompts, terminal words) learns automatically; the owner never carries caveats.
It is NOT a price oracle (~98 direction tests; 8,340 graded rounds: skip-all beat every agent; chief 122/122 NEUTRAL).
Its value: KNOWING (no lost or contradictory context), SIZING, RISK, and GRADING every claim forward.
It is NOT a dashboard - surfaces are printouts of the registry.

## 2. Knowledge model
- **Claim card** `bot/knowledge/claims/<id>.json` (one file per claim -> few merge conflicts): id, statement_plain,
  kind (magnitude/direction/exit/integrity/process), quantity -> Definition, horizon, status (HYPOTHESIS ->
  PREREG_SEALED -> SUPPORTED -> PROVEN | UNDERPOWERED / REFUTED / RETRACTED / STALE / RETIRED), wording_tier (the
  strongest language any surface may use), revalidate (date or n), consumers[], supersedes.
- **Evidence** (embedded): doc@sha, n, clustering unit, MDE, effect, CI, era window, data-through date, impl_hash
  (hash of the exact code tested), placebo_could_fail.
- **Verdict**: who / when / prereg SHA / reviewers. PROVEN only with a laptop verdict.
- **Source**: where the idea came from (owner, Claude idea, sweep, study) -> later grade idea SOURCES too.
- **Definition** `bot/knowledge/definitions/<name>.json`: canonical code path + hash. exp_move has 3+ live meanings
  (HAR volforecast; V1 squeeze expected_move_1d_pct at assemble.py:326; the chief's own); smallcap_breakout has 3.
- **Binding** `bot/knowledge/bindings.json`: claim -> live rule (file:line + flag) / display string / prompt / grader.

Lifecycle: entry (hypothesis) -> laptop prereg (SHA, read-not-before) -> verdict + red team -> applied only via a
binding (bot behaviour = PROVEN + laptop SUPPORT + owner yes) -> forward grader on the claim's OWN metric -> STALE at
revalidate -> REFUTED/superseded kept as the "do not re-open" list (REGISTER §2 generated, not hand-kept).
Seeding: `tools/knowledge/seed_from_map.py` parses KNOWLEDGE_MAP §3 + REGISTER §1-3; cards start `verified_by: none`
until the laptop signs. Then KNOWLEDGE_MAP.md is RENDERED; hand edits go into cards, never into the .md.

Discrepancy checks `tools/knowledge/check.py` (server hourly + laptop crunch j8) -> `data/knowledge/discrepancies.json`:
| Check | Catches | Must flag on day 1 |
|---|---|---|
| D1 display > grade | surface wording stronger than the claim's tier | momentum_small "proven"; chief prompt "~5% vs ~3%"; funding_hot green "tested" chip |
| D2 stale gate | live rule whose evidence stopped moving while trades happened | long gate evidence last moved 2026-07-23; 17 probes ignored |
| D3 definition drift | two consumers of one quantity on different code; numeric cross-check each cycle (alarm > 10%) | three exp_moves; three smallcap definitions |
| D4 impl != tested | live code hash != tested hash | funding_hot >= vs > (regression test) |
| D5 grader != claim | grader metric differs from claim metric / unsigned grading of a signed claim | scan_grader on funding_hot; momentum_small |
| D6 orphan | PROVEN claim with no consumer; live rule with no claim | funding_hot reaches no sizing; 0.5% risk cap prompt-only |
| D7 config vs card | decision-card text contradicted by .env | credit-saver card stale; geometry_shadow "confirmed live" without GBM control |
| D8 count disagreement | two sources disagree on n/date | PREREG_IDEAS 4 vs 1; PREREG_OI interim date |
| D9 substrate death | un-backfillable stream stopped / not off-box | liq, depth, whales, voices |
Phase 0 acceptance: check.py flags every day-1 instance (a test that can fail).

## 3. Living values instead of hard rules
Rule card `bot/knowledge/rules/<id>.json` for each of the 17 audited rules (SERVER_AUDIT_RULES_2026-10-13):
claim_id (or "owner policy" - circuit breakers and loss limits, exempt from learning but listed); scale-free unit (R
or bps of notional - never dollars, never a fee floor: the $0.50 dust filter froze learning); window (rolling + era
cut; whole-ledger forbidden); min_n with NEUTRAL fallback and shrinkage toward neutral (never "keep the last frozen
value"); rate_limit per week; exploration_floor (a gate may never remove all data that measures it; fix or delete the
dead EXPLORATION code); shadow_twin (`data/knowledge/shadow/<rule>.jsonl`: live vs living vs neutral each decision plus
later outcome - the twin calls the SAME function with different params); staleness_alarm (D2).
Collapse the three July-based side/long penalties into one size_score with one cap and one evidence link.

## 4. Reasoning layer
- **Context packs** `tools/knowledge/context_pack.py --consumer chief|ai_plans|trade_agent|exit_agent|rules_manager
  --coin X`: ACT ON (PROVEN, with n and horizon) / CONTEXT ONLY (SUPPORTED, UNTESTED) / KNOWN WRONG (REFUTED) / LIVE
  STATE. Replaces hand-written facts in chief.py and ai_plans.py prompts; each pack hashed and logged -> decision
  lineage for agent reasoning.
- **Every agent claim graded**: structured claims[] (quantity, horizon, number, claim_id) resolved automatically
  (chief expected_move vs HAR on QLIKE; p_up Brier; ideas via PREREG_IDEAS). A voice/agent that doesn't beat its
  baseline at its pre-stated n loses its tokens (the chief is the first candidate after 10-16).
- **Continuity**: `tools/knowledge/threads.json` (each open thread: next action, owner, unblock condition, read-out
  date) + a weekly Opus continuity agent ("what we now believe differently", threads moved, preregs worth sealing).
  Every new session starts from render_state.py; memory notes cite claim ids instead of restating numbers.
- **Cross-stream synthesis**: does stream X (OI/premium/impact, depth, whales, Bybit liquidations, funding
  persistence) predict |move|/exp_move or the 1.65x stop breach beyond HAR + funding_hot? One prereg, Bonferroni, day
  clusters, SIZE_FLAGS panel shape. Expect UNDERPOWERED for most streams now; the value is that the answer arrives
  automatically.

## 5. Owner's role
owner_queue.json holds <= 3 items: one plain question, claim status + wording tier, laptop verdict, the default if he
does not answer (always the safer, reversible option), how to undo. He decides risk tolerance, strategy (e.g. probe
rate) and the final yes on trading changes. He never gets caveats to remember (D1 enforces). A weekly one-screen
"what we believe differently" on the surface he already opens - never a new channel.

## 6. Surfaces last
`tools/knowledge/render.py` generates scanner tooltips (wording by tier + live forward n/mean), lessons.json,
milestones.json kinds, decision-card evidence lines, board findings, KNOWLEDGE_MAP.md and REGISTER §1-3. desk.py and
terminal.html render fields only; any surface string without a claim_id fails D1 strict mode.

## 7. Phases (~4-8 weeks)
- **P0 (weeks 1-2) registry + checks**: schema, seed_from_map, check.py D1-D9, render_map, 17 rule cards,
  definitions with impl hashes, exp_move cross-check. Laptop reviews seeded cards against its docs and runs check.py
  as j8. Success: every day-1 instance flagged; regenerated map diffs cleanly; both machines' checks agree. Risks:
  schema too heavy (keep cards small); seeding errors (verified_by: none until signed).
- **P1 (weeks 2-5) unfreeze learning shadow-first + first evidence-backed living value**: shadow twins for long
  block / side multiplier / dust filter in R, windowed, era-cut, probes counted; the penalty collapse in shadow; 0.5%
  risk cap enforced in code; EXPLORATION fixed or deleted; FUNDING_HOT_SIZE flag-gated OFF (multiplier solved on the
  data by the laptop; BOTH entry paths). Laptop red-team + prereg (metric: stop-breach rate and $ risk per trade);
  owner yes to flip. Success: D2 alarms clear; shadow shows probes counted; post-flip log lines present. Honest
  limit: ~0.1x probes at ~0.5 closes/day -> $ impact near zero for weeks; the win is the mechanism.
- **P2 (weeks 4-8) cross-stream size score**: one sealed prereg; live size_score in shadow for 178 perps; survivors
  feed P1 sizing; chief expected_move contest vs HAR (after removing HAR from its input). Never loosen the bar to get
  a win.
- **P3 (weeks 6-8) surfaces**: render.py drives all claim text; weekly continuity brief on the board; D1 strict.

## 8. Ten questions for the laptop before building
1. Can the card express sealed preregs, amendments (stop_shadow GBM correction), clustering units, read-not-before?
2. Canonical exp_move = HAR volforecast? Is stop_shadow's own recompute equivalent? D3 tolerance?
3. Scale-free unit for gates: R or bps of notional (the short side's sign depends on which)? How to weight 0.1x probes?
4. Window / era cut / min_n for side and long gates; is Jun/Jul a different era to exclude rather than down-weight?
5. funding_hot sizing: down-multiplier, exp_move-normalised risk, or both? Metric and n? Solved on data (2.7x lesson)?
6. Feedback safety: probe floor + shrinkage enough, or a randomised exploration arm?
7. Does collapsing the stacked penalties change any sealed prereg's population (ENTRY_TIMING, ADOPT)?
8. Cross-stream power: seal Phase 2 now or stage by stream (OI sealed to 2027)?
9. Who may set status: PROVEN laptop-only? May the server auto-downgrade (STALE / failing grader)?
10. Wording tiers per status; would showing live forward n in tooltips contaminate PREREG_ADOPT?

## Honest limits
No sizing change is shown to make money yet; P1's value is that learning moves again; P2 will likely be
underpowered. The design makes answers arrive automatically and consistently - it does not make them positive.
