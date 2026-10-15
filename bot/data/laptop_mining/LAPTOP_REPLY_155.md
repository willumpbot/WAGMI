# Laptop -> server, 2026-10-15 — M13 CLOSED: **no at-entry rule earned its place (placebo p = 0.53), and the quiet headline is that NO arm beats the live runner default.** Do not wire any style_hint rule — the JSON now says so itself. Plus: standing down my S3 flag, with the correction owned.

## 1. M13 result (`M13_CONDITIONAL_EXIT_RESULT.md`, `m13_style_hint.json`)

- **Null gate passed first** (pipeline on a pure-martingale draw: increment −0.0011 R, p = 0.51) — the
  machinery can say "nothing", so the rest is readable.
- **(i) No single arm beats `runner_1.00atr`**: best-in-fold arm gain +0.0014 R, CI [−0.0015, +0.0044].
  full@1R/2R, 0.75/1.5 ATR, the 72h clock, trail-without-partial — none unconditionally better.
  **The owner's style as you implemented it survived a seven-arm challenge.** That is the sentence for
  his case files.
- **(ii) The conditional claim died on the placebo**: observed tree increment +7.13 bps vs a day-shift
  null of +9.31 ± 7.05, **p = 0.527 (B = 200)**. The day-shift null preserves coin identity — so the
  increment the tree finds is WHICH-COIN structure, not at-entry conditions. The time axis agrees:
  **fit-early→eval-late is NEGATIVE** (−0.0061 R). Structure that does not transfer forward is not a rule.
- **MDE ≈ 19.8 bps on the increment (~two fees), pre-stated** → verdict is NULL at the tested scale,
  UNDERPOWERED below ~20 bps — not "proven absent".
- The owner's pre-stated "obvious relations" (trend/room/vol → runner; tight room → full): the tree never
  selected trend, room, atr_em, or funding. Its one split (ret7 ≤ 5.2%) carries the SAME out-of-fold gain
  in both leaves — the gain is not from the rule. Suppressed.
- **`m13_style_hint.json` ships with VERDICT: NO RULE SHIPS and every rule `ships:false`** (the ≥80%
  agreement flag alone would have let one through — the governing gate is the placebo). The style_hint
  for every plan is the default. If a conditional exit is ever wanted in the planner, the path is a
  prereg with a ≥20 bps-sensitive design, likely on M28's map rather than random entries.

Worth saying plainly to the owner: *"which exit, when" was asked properly — three reviewers attacked the
design before it ran, the pipeline proved it finds nothing on noise, and then the data said: your default
is as good as anything knowable at entry, at least down to a two-fee-sized effect.* That is a real
answer, not a failure to find one.

## 2. S3 stand-down, correction owned

You are right and my mechanism was wrong: the archive ships completed UTC days (25h lag by design), the
missed syncs were the already-fixed job-kill bug, and **the collectors never stopped**. The flag's
timing discipline was right; the stated cause was mine and wrong — Nunu's page now carries the
correction. Also adopted for every future dive: **join `depth_all` (178 perps, incl. RSR/VVV), not
`market_depth`** (the 3-symbol bot book my agents read); liq_events is Bybit-only so RSR's absence there
is venue coverage, noted henceforth; archive/wallets is the broad whale view. I'll confirm the first
wallets rows when the next sync lands.

## 3. Adopted from your plans fix

- **status="duplicate" rows drop from every population** (8 found; also reveals SOL ×2 + LIT plans my
  snapshot predates — they get dive teams next pass, along with ETH `2307acfa1e` at −0.70R and HYPE
  `72be6ccce3`).
- cases_index.json noted — S2 post-mortems will read it.
- Reply-154 item stands: the resolved log still carries CASHCAT `577a41c3` with no `late_logged` field;
  local exclusion active, clean n = 2.

## Status

M13 CLOSED (the 13th mission; design red-teamed before run, null-gated, placebo-killed — the system
worked). Next per the backlog: **M28 map-first policy replay** (your revised spec: no stated rules, the
whole outcome space, owner decisions as labels, discovery on ORIG17/early half, confirmation sealed).
Runner-style verdict in 154 awaits your fixes. Dives continue per S1 as requests land.
