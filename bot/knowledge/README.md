# bot/knowledge - the HIVEMIND registry (Phase 0)

One registry of what we believe, how strongly, on what evidence, and where each belief is used. Design:
`data/laptop_mining/HIVEMIND_DESIGN_BRIEF_2026-10-13.md` plus the laptop red-team (commit 5e50f89d: D10, D11,
numeric placebo, STALE by default, amendments[], server may auto-downgrade but only the laptop upgrades to PROVEN).

Cards are small JSON files, one per item, so the two machines rarely conflict. Hand edits go into cards; the old
`KNOWLEDGE_MAP.md` section 3 is now generated from them (`tools/knowledge/render_map.py`).

| Path | What |
|---|---|
| `claims/<id>.json` | one belief |
| `definitions/<name>.json` | one quantity / flag / data stream, with the exact code that computes it |
| `rules/<id>.json` | one live hard-coded rule (the 17 of SERVER_AUDIT_RULES_2026-10-13) |
| `bindings.json` | claim -> display string / prompt sentence / grader / rule |
| `threads.json` | open threads (next action, read-out, unblock condition, source disagreements) |

Tools (`bot/tools/knowledge/`): `seed_from_map.py` (build cards from the docs + code), `check.py` (D1-D11 ->
`data/knowledge/discrepancies.json`), `render_map.py` (cards -> map table). Tests: `tests/test_knowledge_registry.py`.

## Claim card
| Field | Meaning |
|---|---|
| `id`, `statement_plain`, `question`, `section` | what is claimed, in plain words |
| `kind` | magnitude / direction / exit / integrity / process |
| `quantity` | name of a Definition card (e.g. `exp_move`, `funding_hot`) or null |
| `metric`, `horizon` | the claim's OWN metric (D5 compares graders against it) |
| `status` | HYPOTHESIS, PREREG_SEALED, POSITIVE_UNDERPOWERED, SUPPORTED, REPLICATED, PROVEN, UNDERPOWERED, REFUTED, RETRACTED, STALE, RETIRED |
| `status_qualifier`, `verdict_text`, `status_note` | the original verdict wording and any qualifier ("definition-sensitive") |
| `wording_tier` | strongest language any surface may use; derived from status (table below) |
| `revalidate` | date or n at which the claim goes STALE unless renewed |
| `consumers[]` | generated from bindings: `rule:<id>`, `display:<id>`, `grader:<id>` |
| `live_bot_terms[]`, `live_bot_flags[]` | names a live bot consumer would mention, and the env flags gating it (D6) |
| `evidence` | `source` (first [..] tag), `sources[]`, `doc_sha`, `n`, `clustering_unit`, `mde`, `effect`, `effect_unit`, `ci`, `era_window`, `data_through`, `impl_hash`, `no_edge_median`, `no_edge_ci` |
| `verdict` | `by`, `at`, `prereg_sha` / `prereg_doc`, `read_not_before`, `reviewers[]` |
| `amendments[]` | `{date, text, before_any_read}` - an amendment made after a read is a rescue, not an amendment |
| `idea_source` | where the idea came from (owner / Claude / sweep / study) - later graded too |
| `supersedes`, `needs_source`, `needs_review`, `verified_by`, `seeded_from`, `map_order` | bookkeeping; seeded cards are `verified_by: "none"` |

Rules of the road (laptop red-team): the placebo is a NUMBER - `no_edge_median` / `no_edge_ci` on the claim's own
metric; PROVEN needs the effect outside that spread, never a boolean "placebo could fail". A claim whose `era_window`
has closed is STALE by default and may not bind a live rule. The server may auto-downgrade (STALE, failing grader);
only a laptop verdict upgrades to PROVEN.

Status -> wording tier: PROVEN `proven` | REPLICATED `replicated` (held up once out of sample) | SUPPORTED `supported` | POSITIVE_UNDERPOWERED `leaning` (CI excludes 0, effect below its MDE) | PREREG_SEALED `sealed` ("sealed, reads at N", no
running tally) | HYPOTHESIS `hypothesis` | UNDERPOWERED `unknown` | REFUTED, RETRACTED `refuted` | STALE, RETIRED
`stale`. Rank: proven 4 > supported 3 > hypothesis/unknown/sealed 2 > stale 1 > refuted 0. A display asserting the
NEGATION of a claim ("no AI predicts price") is allowed `proven` only when the claim is REFUTED.

Seeding map (Verdict column -> status, first match wins): RETRACTED; REFUTED / "Null as a trade" -> REFUTED; PROVEN*;
UNDERPOWERED / "can't detect" / NO FINDING -> UNDERPOWERED; KEEP, FIXED -> SUPPORTED; "prereg sealed" ->
PREREG_SEALED; OPEN, UNTESTED -> HYPOTHESIS; anything else -> HYPOTHESIS with `needs_review: true`. Overrides (in
`seed_from_map.py`): `long_side_drain` is STALE (era Jun/Jul closed). Rows with the map's warning sign get
`needs_source: true`.

## Definition card
`id`/`name`, `kind` (quantity / flag / stream), `plain`, `canonical`, `implementations[]` each `{label, path,
function | start+end | pattern, impl_hash (sha256 of that exact source), line, note, role}` (or `{doc, doc_commit,
text}` for a laptop doc), `tested_impl_hash` (the hash the laptop tested; D4), `invariants[]` `{expr, why}` (D11;
`g('a.b')` reads a field), `cross_check` (exp_move). Stream cards add `stream {path, archive, max_age_days, map_keys}`
and `expected_fields[]` (D10 baseline).

## Rule card
`id`, `n`, `description` (audit text), `claim_id` (a claim id, `"owner_policy"` for breakers / loss limits / risk
caps - exempt from learning but listed, or null = orphan), `exempt_reason`, `unit` (today) and `unit_target` (bps of
notional; never dollars, never a fee floor), `window` / `window_target` (rolling + era cut; whole ledger forbidden),
`min_n`, `flags[]` (env names), `fires_37h`, `evidence_source` (machine-readable, e.g. ledger + side + fee floor),
`evidence_through` (computed at seed), `enforcement_check` (prompt marker vs code clamp), `conflicts_with[]`,
`shadow_twin`, `exploration_floor`, `staleness_alarm`, `source`.

## Checks (`tools/knowledge/check.py`)
D1 display > grade; D2 stale gate; D3 definition drift (+ exp_move numeric cross-check); D4 impl != tested; D5 grader
!= claim; D6 orphan (PROVEN with no live consumer, rule with no / dead claim, prompt-only cap); D7 decision card vs
.env; D8 count disagreement; D9 stream death (+ off-box archive); D10 payload completeness; D11 semantic invariants; D12 live definition behaves like the tested one (frozen behaviour
fixture + semantic hash); D13 a claim's decision_numbers[] use the same estimator as its evidence.
Anything a check cannot verify is listed under `not_automated` - never a silent pass.

```
python tools/knowledge/seed_from_map.py --data-dir <live bot/data> --env <live .env>   # read-only on both
python tools/knowledge/check.py --data-dir <live bot/data> --env <live .env> [--out ...]
python tools/knowledge/render_map.py [--with-status]
```
