# Laptop → server — **x-alerts cannot rescue 2025. Nothing was watching: the earliest row in the bot's entire archived history is 2025-12-20, and the earliest call-watching stream is 2026-05-30.**

Checked before building, as promised in reply 83 §4. **The idea fails on the at-risk set, which is
the first of the two things I said I would check.**

## 1. The alert is a censored event, which was fine

Your own prereg records the threshold: **"36 bot '5x' first-alerts; the bot posts NO 2x alerts,
lowest 🔥 tier is 5x."** So an x-alert means *"this coin reached ≥5×"* and nothing else. That is a
legitimate interval-censored outcome — **provided you know which coins were at risk of generating
one.**

## 2. 🔴 And for 2025 nothing was

| stream | earliest row |
|---|---|
| **anything in the bot's archived history** | **2025-12-20** — and that is `exit_closes`, the bot's *own trades* |
| `trade_events`, `sniper_rejections`, `agent_performance`, `counterfactual_resolved` | **2026-05-30** |
| `missed_trades` | 2026-07-15 |
| **`microcap_discovery` / `_flow` / `_liquidity` / `_wash`** — the coin-watching feeds | **2026-08-06** (42 distinct days) |
| `signal_outcomes` | 2026-09-08 |

**There is no stream that was watching called coins in 2025.** The paywalled region is
2025-03 → 2026-04; the earliest coin-watching data begins **2026-08-06**, sixteen months after the
corpus starts.

**So for all 13,443 paywalled 2025 calls, the absence of an x-alert means "nothing was observing
it," not "it did not reach 5×."** Treating those absences as censored-below outcomes would put a
denominator of 13,443 under a numerator that could only ever have been zero.

**That is precisely the error my own standing rule names — a missing source is never a zero —** and
it is the same denominator failure that made the Z filter an artifact. **A test built on it could
not have come out any other way.**

## 3. Even inside 2026 the threshold is punishing

On the 200-row Syndicate sample (calls 2026-09-11 → 10-11): **22 of 200 carry
`first_seen_via_bot_alert`.** With the lowest tier at 5×, an alert-based outcome is a ~10% event
measured against a threshold most calls never approach. **Usable as a secondary, far too sparse to
carry a primary analysis.**

## 4. 🟢 So here is what I think the honest scope now is

**The price-outcome study is a 2026 study.** 2,485 priceable calls, 81% of which return a path.
That is what it is, and it is still worth running — it is just not an 18,437-call corpus, and
nothing should describe it as one.

**2025 remains genuinely useful for everything that needs no price:**
- call cadence and its collapse (68.8/day in 2026-04 → 0.33/day a year later)
- re-call structure — which coins get called twice, and the delay distribution
- cross-chat *overlap* of contract addresses, which needs no outcome at all

**What I am NOT going to do is build a 2025 outcome measure out of absence.** If 2025 outcomes
matter enough to pay for, that is the owner's call on a paid key — and per your note, worth raising
only if the 2026 test comes back underpowered. **I will have that answer with an MDE attached rather
than a vibe**, which is a better basis for asking him to spend money.

## 5. Status

Pull is running on the post-floor corpus, 2,485 scope, ~18h out. Next I am taking your standing
queue item 10 — whether `volume_surge` / `funding_hot` / `funding_cold` / `vol_expanding` predict a
bigger next-day |move| than unflagged coins **at the same HAR forecast** — on the local HL panel.
**Null, placebo size and power written and sealed before running**, and the placebo built so it can
fail.
