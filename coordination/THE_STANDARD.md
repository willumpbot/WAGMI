# THE STANDARD — how this system runs
Adopted 2026-07-02 (owner: "Let's create that standard truly. Then let's audit that to make it better.")
This unifies the contracts already in force: WIRING_INVARIANTS.md (the wiring), RESEARCH_AGENDA.md (the queue), HOLES.md (the backlog), MORNING_BRIEF/STATE.md (the shared page). This document is itself subject to Section 5.

## 1. Evidence standard — what counts as knowing
- Every claim carries: a denominator (n), an era-split (does it survive outside one window?), a direction-split where applicable, and an adversarial pass (someone tried to refute it at the source).
- The week-1-artifact test is mandatory for any "opportunity" claim. (Track record: missed-EV, ADX survivor, crowding-continuation — all died under it. The test earns its keep.)
- Killed hypotheses are logged as wins in RESEARCH_AGENDA's ANSWERED section. Negative knowledge compounds.
- Small-n humility: nothing graduates on n<15; fragility checks (does the result survive removing the single best trade?) are required.

## 2. Change standard — how anything ships
- Measurement/logging fixes: autonomous, tested, scoped commits, safe restart, live-verified on next data.
- Behavior changes (sizing, exits, entries, rules): EXTENSIVE backtest → counterfactual replay → adversarial self-audit (try to break the finding) → flag-gated / A/B with auto-retire → SHIP AUTONOMOUSLY → watch window (15-20 closes) → keep or revert → REPORT the result to the owner. Owner directive 2026-07-02: validated+reversible changes do NOT wait for sign-off; deferring is the failure mode. What still reaches the owner BEFORE action: real-money mode flips, circuit-breaker/gate changes, spending, and anything that fails the reversibility test.
- Risk-reducing-only changes (cut-only ladders, tighter guards) still follow the pipeline but may ship on backtest + flag without waiting on unrelated results.
- Never: weaken circuit breakers, reorder gates, hardcode directional opinion, add features during an open rewire.

## 2b. Learned-rule provenance & quarantine (anti-poisoning)
Owner concern (2026-07-02): learned vetoes/hard blocks from incomplete data + incomplete wiring are dangerous — the mech->LLM->mech->LLM loop can compound corruption.
- Every learned rule carries PROVENANCE: the data era, n, and ledger-integrity version it was learned from.
- Rules learned on a ledger later shown broken are SUSPECT BY CONSTRUCTION: they may hard-block ONLY after dollar re-validation on trustworthy data (counterfactual re-score or clean closes). Until then: SHADOW MODE — log the would-have-blocked decision, enforce nothing.
- No new rule graduates to enforcement without: n>=13, dollar-positive, learned on the current ledger version.
- The loop is ANCHORED: every cycle grades against PRICE (external truth) — never against the system's own outputs. A rule justified only by system-internal stats is not justified.
- After any major instrument fix, the meta-audit re-runs the dollar re-score of ALL enforcing rules.

## 3. Learning standard — how understanding compounds
- Every thesis graded against price. Every rule scored in dollars. Every agent's calls scored against a baseline. Every dataset consumed or explicitly muted (Invariant 7).
- The learning engine (3h loop) runs: spine verification → HOLES burns → RESEARCH_AGENDA pull → knowledge commit. Findings that change prior conclusions must edit the prior document and say so.
- The RECALL layer goal: every decision informed by everything ever collected, from the clean ledger only.

## 4. Data estate — what we own
- Live collected: trades ledger, 36.5k counterfactuals, 237+ graded theses, decisions/exits/funding-OI streams, deep memory.
- Historical archive (UNDER-MINED): data/reports/paper_trading_*.md (Apr-May), sim_trades.jsonl sniper simulations, replay/backtest artifacts, pre-May trade eras. → RESEARCH_AGENDA Q21.
- Data-integrity duties: collectors watchdogged (H61), gaps documented at the source, exchange candles as price ground-truth.

## 5. THE META-AUDIT — auditing the standard itself
Weekly (or after any 10 HOLES burns / 3 shipped changes, whichever first), one adversarial pass asks:
- Did the standard catch what it should have? (Any bug/artifact that slipped through a rule → the rule gets amended, and the amendment logged here.)
- Is the standard too slow anywhere? (Evidence steps that never changed a decision are candidates for trimming — bureaucracy is also a bug.)
- Are the instruments drifting? (Spot-check: does STATE.md match raw data? Do the scoreboards recompute to the same numbers?)
- What did we decide on vibes anyway? (Find it, backfill the evidence or reverse it.)
Amendments are committed to this file with date + reason. An unamended standard after weeks of use means the meta-audit isn't being honest.

## Amendment log
- 2026-07-02: v1 adopted.
- 2026-07-02: v1.2 — added §2b learned-rule provenance & quarantine (anti-poisoning) per owner concern re: circular mech->LLM->mech corruption.
- 2026-07-02: v1.1 — owner directive: DO-NOW items are questioned/audited/fixed/re-tested and SHIPPED autonomously; owner receives results, not requests. Owner-gated set narrowed to: live-money flips, CB/gate changes, spend, irreversibles.
