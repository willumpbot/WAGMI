# M8 — the "0.60 floor killed proceeds" claim is **metabrain-only: confirmed.** On the month of data I have, the floor changes **nothing at all** — and that exposed a **latent** hazard worth more than the original question (§4 corrected: it is latent, not live — the flag is set).

_2026-10-13. **EXPLORATORY.** Source: `server_exports/conf_floor_decisions.jsonl`, 491 rows,
**2026-09-13 → 2026-10-13**. The July `decisions.jsonl` gate records are **not on this disk**, so the
July count of 69 is **not directly verifiable here** — stated up front rather than implied._

---

## 1. The scope claim: confirmed three independent ways

The mission asked whether the July claim at `DEEP_MINE_2026-07-13.md:228` — *"69 proceeds killed by the
0.60 floor … since June 7: 0 of ~1,400 pipeline decisions allowed"* — was metabrain-only.

| evidence | finding |
|---|---|
| **code signature** | `risk_gating.gate_decision(decision: LLMDecision, …)` takes an **`LLMDecision`**. It is structurally incapable of touching the mechanical path. |
| **the data's own field** | `path` = **`metabrain_advisory`** in **491 of 491** rows. Not a majority — all of them. |
| **the document's own numbers** | 125 of 149 executed trades came from the mechanical path, which this gate never sees. |

**So: confirmed. The 0.60 floor could not have cost the mechanical trades, and the "killed proceeds"
were LLM-pipeline proceeds only.**

## 2. 🔴 And on this corpus the floor is INERT — it blocks nothing

This is the part I did not expect:

| | |
|---|---|
| rows where the floor **changed the action** | **0 of 491 (0.0%)** |
| rows sitting **below their own floor** | **449 of 491 (91.4%)** |
| `action` / `original_action` | `proceed` in **all 491** |

**91% of these decisions fail the floor and every single one still reads `proceed`.** The path is named
`metabrain_advisory`, and advisory is exactly what it behaves like — **the floor is recorded, not
enforced, on this corpus.**

**This is the r16 pattern again, and I walked into it from the other side this time.** In reply 123 I
called something "a gate rejecting 165 entries" when it was advisory-only. Here the mission handed me a
claim about a gate killing 69 proceeds, and the gate turns out to be advisory on every row I can see.
**A rejection count is not a cost until you show the rejection was binding.**

## 3. The confidence distribution — and a small correction to the code's own comment

`risk_gating.py:82-84` says the 0.60 constant *"silently became an absolute wall … against a scale that
now tops out near 0.55."*

| llm_confidence | |
|---|---|
| median | **0.365** |
| p90 | 0.395 |
| **max** | **0.680** |
| ≥ 0.55 | 7 rows (1.4%) |
| ≥ 0.60 | 3 rows (0.6%) |

**"Tops out near 0.55" is right about the bulk — 98.6% sit below it — but not literally: the maximum is
0.680, and three decisions did clear 0.60.** A small thing, and the comment's conclusion is unaffected;
worth correcting because "tops out at X" is the kind of phrase that later gets used as a hard bound.

**The floor actually in force on this corpus is ~0.41** (min 0.383, median 0.404, max 0.413) — i.e. the
**living** floor, not the legacy 0.60. 453 of 491 rows carry
`floor_source = replay_exact_matches_log`, so that 0.41 is matched against what the live log recorded.

## 4. 🔴 CORRECTED 2026-10-14 02:15Z — the hazard is LATENT, not live. I had this wrong.

> **The server answered: `LIVING_CONF_FLOOR=true` and `LIVING_CONF_FLOOR_PCTL=90` are set in the live
> `.env`, so the floor genuinely in force is 0.41/0.38 — never 0.60. There is no live hazard.**
>
> **And the reason I got it wrong is worse than the conclusion.** I wrote that the flag "appears in no
> `.env`" — but **there is no `./.env` on this disk at all.** My check was
> `grep … .env 2>/dev/null`, and **`2>/dev/null` silenced the "No such file or directory" error**,
> leaving an empty result I read as "the pattern is absent." *File missing* and *setting absent* became
> indistinguishable **because I suppressed the one signal that separates them.**
>
> **The substantive claim survived by luck:** `bot/.env` does exist (54 lines) and does not contain the
> flag either, so "not on my disk" was true. But the inference I drew from it was wrong. The correct
> statement was never "the flag is probably unset" — it was **"this disk does not carry the live
> environment, so I cannot determine this from here."** The server put it in one line: *"Your disk has
> no `.env`, hence the default."*
>
> **I did name the ambiguity** — the original text said the flag might be set outside the `.env` I can
> read — **and then overrode it with "either way the hazard is live," which is the part that was not
> entitled.** Naming an uncertainty and then concluding past it is worse than not naming it.

**What survives, correctly scoped:** `living_conf_floor.enabled()` reads
`os.getenv("LIVING_CONF_FLOOR", "false")`, so **the default is off, and off returns the legacy 0.60**
against a confidence distribution whose **p90 is 0.395**. That is a **latent** hazard, guarded by one
environment variable: lose it to a fresh shell, a new deploy, or a container without it, and
**~99.4% of decisions fall below the floor and the LLM path goes to zero admits.**

**The consequence is not hypothetical even though the trigger now is:** losing that variable reproduces
precisely the outage the code comment already documents — **zero trades 2026-07-29 → 2026-09-12**, six
weeks. **What is hypothetical is the trigger**, and §4's correction is that the flag is in fact set.

**A default that silently reinstates a known six-week outage is the wrong default.** Two fixes, and I
prefer the second:

- **Flip the default to on.** Simple, but it still leaves a magic constant deciding a live gate.
- **Make the gate self-checking:** if the computed floor exceeds the p99 of the confidences actually
  observed in the rolling window, that is not a strict gate, it is a closed door — **log loudly and
  clamp to the p99 instead.** A gate that can reject 100% of its input should have to say so.

**This is the same standing rule I adopted for my own harnesses today** — a verdict block must be
unreachable with no data — pointed at a live gate instead of an analysis script.

## 5. What this does NOT settle
- **The July count of 69 is unverified.** Those gate records are not on this disk. If anyone wants it
  confirmed, it needs the July `decisions.jsonl`; I would rather leave it unverified than infer it from
  a different month.
- **Whether the LLM-pipeline skips would have been profitable.** The same document claims the 4,215
  `[MA]` skips would have averaged **+1.32%** (median +0.635%). **Mean well above median means a
  right-skewed distribution carried by a few large winners**, and I have not seen how the counterfactual
  handles stops, exits, fees or clustering. **That claim is the one actually worth auditing**, and it is
  a separate study from this one — the same shape as the RQ9 "0/71 disaster vs 51-57% correct by
  counterfactual" tension already recorded in `exit_engine.py`.
- Advisory **on this corpus**. I cannot rule out that the same floor was enforcing in June/July, before
  the path became advisory — which is another reason the July records matter.
