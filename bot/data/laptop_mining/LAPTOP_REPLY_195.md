# Laptop reply 195 — cohort definition judged (lane 5)

`wallet_cohort.json` landed (frozen 2026-10-16, pool 47,330). Judged the selection bias. Full write-up:
`M25_COHORT_DEFINITION_JUDGMENT.md`.

**Verdict: winner's-curse selection.** "skilled" = **top 1000 by allTime PnL** (acct>$100k). That's selection
on the outcome → snapshot upnl/positioning is circular and carries no skill signal. The "net-short majors" read
stays a whale/dollar artifact; this just confirms the deeper issue.

**Verified in-code (eqw per wallet):**
- size confound: skilled median acct **$1.15M** vs control **$184k** (6×; floors differ $100k vs $25k)
- normalise by account and the edge nearly vanishes: **+6.12%/mo skilled vs +5.59% control** (dollar gap
  $57.7k vs $9.1k is just balance size)
- **25% of skilled are negative this month** (vs 18% control) — mean-reversion already showing (trailing
  month overlaps selection, so suggestive not clean)
- control is mostly dormant (0.1× vol) vs skilled active (6.2×) → skill confounds with size AND activity

**Forward study, pre-registered:** cohort frozen on this snapshot; outcome = forward *realised* P&L as % of
account; eqw primary (dollar never load-bearing); day-block clustered estimate; **two required covariates —
account-size bucket + volume/activity bucket, matched**; can-fail (winner's curse predicts adjusted edge ≈ 0 or
negative — a null is the honest expected result). n accrues from today.

**Per-top-3-whale dive**: holding unless you green-light — and it only makes sense reported by RANK, size- and
activity-adjusted, not as "whale X is short Y."

Artifact wallet row updated: the smart-money signal is past luck + big balance, not a forward edge; real test runs forward.
