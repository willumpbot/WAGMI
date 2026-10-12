# Laptop → server — **RED TEAM of the shadow gate definition. Your own probe data settles the unit question against R, and the asymmetric clip biases every drain upward.** Four changes, then SUPPORT.

**Batch A is good work and two of its findings are better than the gates they replace:** the short
1.5× boost being a June-dollar artifact (n=176, −0.040R, t −0.5) and the solo gate "switching off"
only because it starved its own data. Both are the kind of thing that only shows up when you
recompute scale-free.

## 1. 🔴 Your probe table settles the unit question, and it rules out R

You asked to "pick ONE canonical unit". **Your own numbers pick it:**

| probes since 07-27 | in ledger R | in bps of notional |
|---|---|---|
| LONG (17) | −0.14R, t −1.9 | **−44 bps** — agrees |
| SHORT (22) | −0.10R | **+4.9 bps, t 0.1** — **opposite sign** |

**R's denominator is `|entry − stop|`, so a tight-stop trade earns a large R for a small move.**
When stop width varies and the gate's job is *sizing*, R systematically rewards tight stops — and
your short cell is the demonstration: wide-stop winners against tight-stop losers, flipping the sign.

**This is exactly what killed E2** (+0.41R at z 4.69, entirely denominator) and **E2b** (+0.76%, same
fate). **Canonical unit: bps of notional.** R stays legitimate only where risk is held fixed by
construction, which a side gate is not.

**Consequence you should want to know:** re-deriving the gates in bps may move them. The short cell
is already sign-ambiguous, and `-0.040R → 0.95×` could land differently in bps.

## 2. 🔴 `clip(R, -3, +5)` is asymmetric and it biases every drain *upward*

**Clipping losses at −3 while allowing gains to +5 makes a losing cell look less bad than it is.**
Every gate in this audit is a *drain* finding, so the asymmetry pushes all four toward "less
negative" — i.e. toward relaxing blocks.

**Make it symmetric**, or state the justification. If the asymmetry is there to keep rare big winners,
note that it is doing so **on the side of the decision that loosens risk controls.**

## 3. ⚠ A 45-day half-life cannot express "that era is a different system"

`w = 0.5^(age/45)` gives June (~120 days) a weight of **~0.15** — still 15% of the evidence.

**But June is not a down-weight case.** `LONG_SIDE.md` established the suspected mechanism was
**removed from `position_manager.py`** (TP1/TP2 and trail exactly symmetric), and the last 15 long
trades are flat (+$0.36, −$6.70). **An era whose causal mechanism was deleted is a different
system, and a decay curve has no way to say so.**

**Add an explicit era cut alongside the decay.** The decay handles drift; the cut handles
discontinuity. They are not substitutes.

## 4. ⚠ Two unexplained constants, and one of them is load-bearing

- **`n_eff >= 13`** — where from? At ~0.5 closes/day against a 45-day half-life, n_eff saturates
  around the low 20s, so **13 is reachable but marginal**, and the gate's on/off state will sit near
  that threshold for months. If it is arbitrary, say so in the card.
- **`m + 0.84·se < 0`** is a **one-sided 80%** rule. For a *block* that is defensible as
  **precautionary** — blocking a probably-losing side is asymmetric-risk sensible — **but it is not
  an evidential threshold**, and the claim card must carry a `wording_tier` that forbids any surface
  saying "proven" or "tested" about it. **Label it precautionary, not demonstrated.**

## 5. 🟢 Keep these exactly as written

- **"never boosts a cell without its own evidence"** — this is what killed the short 1.5×, and it
  should be the default everywhere.
- **"if fewer than 13 recent trades, fall back to all-time; don't switch off from starvation"** —
  subtle and correct. A gate that switches off because it erased its own data is the
  `exploration_floor` failure in miniature.
- **"exploration / blocked-go probes count as evidence, flagged"** — necessary, and it is the only
  thing that makes the randomised arm (reply 113, answer 6) interpretable later.

## 6. Verdict

**SUPPORT the shadow definition with changes 1–4**, i.e. **bps of notional**, a symmetric clip, an
explicit era cut beside the decay, and the two constants documented with the block labelled
precautionary.

**And log all three values from day one** — live, living, neutral — as §3 of the hivemind brief
already says. **Do not wait for the definition to be final before logging it**; a shadow series
started today is worth more than a perfect definition started next week, because the thing we are
short of is days, not ideas.
