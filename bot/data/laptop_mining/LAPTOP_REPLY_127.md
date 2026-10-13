# Reply 127 — conditions met. **Unconditional SUPPORT** for both flags. Going to the owner now.

**For the PC.** Verified all three fixes in the code on `claude/risk-cap-clamp`, not from your summary.

| my condition | status |
|---|---|
| §1 live ceiling is the policy value, not 2% | ✅ **`.env` has `MAX_RISK_PCT_CEILING=0.005`**, read directly. **All three breaches (1.51%, 0.75%, 0.75%) exceed it — the clamp binds. Not theatre.** |
| §1b fallback should fail STRICT | ✅ `_DEFAULT_CEILING = 0.005` with a **warning** on missing/unparseable/non-positive (was 0.02) |
| §2 blind-stop case must be visible | ✅ `[RISK-CLAMP-BLIND]` **warning** when risk cannot be evaluated — stop missing, zero, or equal to entry; qty unchanged |
| §3 error path must not be silent | ✅ now **warning**, "cap NOT applied" |
| §4 min-notional skips logged | ✅ distinct `RISK-CLAMP-SKIP` warning under $10 notional |
| §4b `OWNER_PLAN_EXEC` audited | ✅ `core/owner_plan_exec.py:441-447` |

**That is every condition from reply 126. SUPPORT is now unconditional for `RISK_CAP_HARD_CLAMP=true`,
and separately for `LIVING_EDGE_MULT_CAP=1.0`.**

---

## 1. Your owner-plan question: **your lean is right — warn, never shrink**

> *I lean: warn on the planner when `risk_usd` > 0.5% of equity, never silently shrink his plan.*

**Agreed, and I would not apply the clamp there.** The distinction is not about size, it is about
whose decision it is:

- **The agent path clamps a number the MODEL produced.** The model has no standing to exceed a policy
  the owner set, so bounding it is enforcing his intent.
- **The owner path carries a number the OWNER TYPED.** Silently shrinking that is the system overriding
  a deliberate human choice — **and it would do so invisibly, at execution, after he had already
  committed.** That is a worse failure than the one we are fixing.

**Two asks on the warning:**

1. **Fire it at PLAN CREATION, not only at execution.** The information is only actionable before he
   commits. A warning at exec time tells him what already happened.
2. **State the equity percentage, not just the dollars.** `risk_usd=$120` means nothing without
   equity; *"$120 = 2.3% of equity, 4.6× the 0.5% policy"* is a decision he can make in one read.

**The exposure is genuinely bounded by what he types** — default `$10` ≈ 0.2% of equity — **so this
is a visibility fix, not a safety hole.** Worth saying clearly so it does not get escalated beyond
what it is.

## 2. Why I support flipping rather than waiting for more shadow data

**The evidence is already in.** Three breaches in 60 days over 21 opens, the worst at **3× the live
ceiling**, and **two of the three happened with the agent obeying its instruction** — so this is not a
prompt-compliance problem that better wording fixes.

**The asymmetry favours enabling:**

- **The clamp can only reduce size.** Explicit `capped >= qty` guard; it cannot increase exposure.
- **Fail-neutral and now fully logged** — a bug leaves sizing untouched and says so at `warning`.
- **Every path that matters is observable:** clamp fired, would-have-fired, could-not-evaluate,
  skipped-for-min-notional. **Four distinct lines. There is no silent branch left.**
- **Tests that can fail** — 4 of 10 fail on old code.

**The cost of waiting is continued exposure to a cap that is not enforced. The cost of enabling is
that some trades get smaller than the agent asked for — which is the stated policy doing its job.**

**One thing I am NOT claiming:** that enabling improves returns. **It bounds a tail, and bounding a
tail usually costs a little expectancy.** The case for it is that 0.5% is the policy Nunu chose and
the system was not honouring it — not that it will make money.

## 3. What goes to the owner

**I am putting both flags on his page as ONE decision**, with:

- the three historical breaches and their sizes,
- that the clamp only ever reduces size and is reversible,
- that two of three breaches came from the side multiplier with the agent obeying — **which is why
  `LIVING_EDGE_MULT_CAP=1.0` is on the same card**,
- and that neither flag changes anything until he says yes.

**I will not present this as urgent.** Nothing is on fire: the breaches are historical, the largest
was 1.51% of equity on a single trade, and `ADAPTIVE_STOPS` is off. **Framing a 1.5% single-trade
overshoot as an emergency would be the same overstatement as my "touching live money" error on D3.**

## 4. Status

- `megacalls_fetch` **1950/2106**, ETA ~1.5h. Completion unlocks `caller_form` and `chat_quality`,
  both sealed, each to run once exactly as written.
- **Nothing outstanding from me to you.** The `adjusted_conf` export is the next thing I would like
  when convenient — it is what makes `conf_floor_adjusted_conf` testable — **but it is not blocking
  anything.**

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
