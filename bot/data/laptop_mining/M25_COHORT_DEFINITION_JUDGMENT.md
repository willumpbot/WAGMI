# M25/M26 — cohort definition judgment (lane 5 selection-bias check)

**File judged:** `server_exports/wallet_cohort.json` (frozen day **2026-10-16**, pool = 47,330 leaderboard wallets).
Addresses live only in that gitignored export — this doc reports **aggregates only**.

## The definition (verbatim)
- **skilled** = "allTime pnl > $100k, account > $100k, monthly volume 0.5x–200x account; **top 1000 by allTime pnl**" (n=1000)
- **control** = "random 200 (seed = date) of the rest with account > $25k" (n=200)

## Verdict: WINNER'S-CURSE SELECTION — snapshot is circular, skill is forward-only

"Skilled" is ranked on **past cumulative PnL**. That is selection *on the outcome*: a wallet is in the cohort
*because* it already made money. So its all-time PnL, its current unrealised PnL, and its positioning tell us
**nothing predictive** — they are the selection criterion reflected back. The first-read "smart money is short
majors" was already shown to be a whale/dollar-weight artifact; this confirms the deeper problem — even a clean
positioning signal would not be evidence of skill, because the label is past luck, not forward edge.

## Three things the raw numbers show (equal-weighted per wallet, verified in-code)

| | skilled (n=1000) | control (n=200) |
|---|---|---|
| median account | **$1,154,640** | $183,744 |
| median all-time PnL | $1,294,065 | $43,190 |
| median month PnL ($) | $57,720 | $9,144 |
| **median month return / account** | **+6.12%** | **+5.59%** |
| % negative this month | **25%** | 18% |
| median monthly volume (× account) | 6.2× | 0.1× |

1. **The dollar gap is mostly account size, not skill.** Skilled accounts are ~6× bigger. Normalise by account
   and the typical skilled wallet (+6.1%/mo) is barely ahead of a random one (+5.6%/mo). Dollar-weighting is
   meaningless here — same lesson as the M25 whale artifact, now at cohort level.
2. **The winners are already reverting.** 1 in 4 all-time-top wallets is *losing* money this month — more than
   the control's 18%. (Caveat: the trailing month overlaps the selection window, so this is *suggestive* of
   mean-reversion, not the clean forward test.)
3. **Control is mostly dormant** (0.1× volume) vs skilled active (6.2×). So the naive comparison is
   "active big winners vs inactive small randoms" — skill confounds with *trading at all* and with *size*.

## Forward-study design (updated, pre-registered)

- **Cohort FROZEN** on the 2026-10-16 snapshot. Later leaderboard churn does **not** change membership.
- **Outcome** = forward **realised** closed-trade P&L per wallet from 2026-10-16 onward, expressed as **% of
  account** (eqw across wallets is the number we act on; dollar reported alongside but never load-bearing).
- **Clustering**: day-block CI; cluster the **estimate**, not just the CI (more wallet-rows ≠ more power when
  the binding cluster is the day/regime).
- **Pre-registered covariates to control** (both differ between cohorts, so both must be matched or adjusted):
  **account-size bucket** and **monthly-volume/activity bucket**. Primary comparison is within matched buckets.
- **Can-fail / honest prior**: winner's curse predicts the size- and activity-adjusted forward edge is **≈ 0 or
  negative**. A null or negative result is the expected, publishable outcome — do not inflate a dollar gap into skill.
- **Multiplicity**: if sliced by coin or bucket, correct for the number of slices.

## Owner takeaway (one number)
**Don't copy "smart money."** Divide by account size and the all-time winners make **+6.1%/month** vs a random
wallet's **+5.6%** — basically the same, and 1 in 4 of them is down this month. The label is past luck plus a
big balance, not a forward edge. Whether the cohort has *any* real skill is a question only the forward test,
started today, can answer.
