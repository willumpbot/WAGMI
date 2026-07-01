# BT_ADX_SURVIVOR — Forward-Validation of the High-ADX Trend-Continuation "Survivor" — 2026-07-01

**Lane:** validate the one rule that survived MISSED_EV_LOCKDOWN_2026-07-01: *"in a confirmed high-ADX trend, continuation entries in trend direction are worth taking."*
**Method:** 1h Hyperliquid candles (live API, funding_oi_history.jsonl hole avoided), BTC/ETH/SOL/HYPE/XRP. ADX(14) Wilder + DI direction, EMA20, ATR(14). Entry = pullback-to-EMA20 touch in DI direction (prev close on trend side of EMA, bar touches EMA → fill at EMA). Stop 1.5×ATR (=1R), 50% trim at +1R → breakeven, remainder trails close−2×ATR chandelier, max hold 72 bars, one position/symbol, no overlap. Conservative intrabar (stop checked before target). Fees 0.06%/side converted to R per trade. Treatment = entry inside a confirmed high-ADX window (ADX≥25 for ≥3 consecutive bars); Control = same entries, all windows. Script: `bot/tools/backtests/adx_continuation_bt.py`; trade dumps `bot/tools/backtests/adx_trades_{primary,extended}_thr{20,25,30}.csv`.

## VERDICT: **DOES NOT VALIDATE. Same Week-1 artifact, second costume. Do NOT graduate an ADX-conditioned A/B rule.**

The killer number: on the bot's own data span (May 30 → Jul 1), the high-ADX treatment made **+6.89R total, but 2026-W23 (Jun 1–7, the crash week) alone contributed +20.43R**. Excluding W23: **n=59, WR 44.1%, expectancy −0.229R, total −13.54R.** The "survivor" is the June 1–7 crash leg again — exactly the artifact the lockdown doc warned about.

## 1) Primary span (2026-05-30 → 2026-07-01), ADX≥25

| bucket | n | WR | exp gross | exp net | total net |
|---|---|---|---|---|---|
| Treatment (confirmed hi-ADX) | 80 | 55.0% | +0.166R | **+0.086R** | +6.89R |
| ALL entries (control) | 198 | 59.1% | +0.200R | +0.111R | +21.98R |
| Out-of-window only | 118 | 61.9% | +0.223R | **+0.128R** | +15.08R |

**The ADX filter UNDERPERFORMS its own control** on the very span it was discovered in. Weekly treatment: W23 +0.973R/trade (WR 86%); W24 −0.493R; W25 −0.083R; W26 +0.007R; W27 −0.660R. Post-discovery weeks are flat-to-negative.

Direction: treatment SHORT +0.164R vs LONG −0.025R — the profit is short-side, i.e. the bear leg, same one-sidedness as the lockdown finding.

## 2) Out-of-sample extension (2026-01-01 → 2026-07-01, ~26 weeks, n=436 treatment / 557 control)

| bucket | n | WR | exp net | 95% CI (bootstrap) |
|---|---|---|---|---|
| Treatment hi-ADX | 436 | 57.8% | +0.083R | [−0.032, +0.199] — **not distinguishable from 0** |
| Out-of-window | 557 | 60.1% | +0.161R | — |
| Treatment − control diff | — | — | **−0.078R** | [−0.230, +0.079] — filter adds ≤ nothing |

Week-cluster bootstrap on treatment: CI [−0.069, +0.244], only **13/27 weeks positive**. Month split: Jan +0.504R (another single hot month), Feb −0.02, Mar −0.00, Apr −0.21, May +0.06, Jun +0.10. Two crash-trend months (Jan, early Jun) carry everything.

Per symbol (extended treatment): BTC −0.059R, ETH +0.012R, SOL +0.112R, HYPE +0.145R, XRP +0.229R — no symbol-consistent story; XRP's edge is one Jan-02 window (+15.2R, largest of 255 windows).

## 3) Robustness sweeps (primary span)

- ADX≥20: treatment +0.090R vs out-of-window +0.149R (filter worse).
- ADX≥30: treatment +0.276R vs out-of-window +0.055R — *looks* better, but W23 = +1.173R/trade and ex-W23 total is **−6.13R on n=33** (W24 −0.688R, W27 −1.086R, WR 0% that week). Non-monotonic across thresholds + W23-dependence = curve-fit, not signal.
- Window concentration (primary, thr25): 39 windows; top-3 (SOL Jun-01, BTC Jun-03, ETH Jun-02 — all crash-week) = 48% of the positive-window sum.

## 4) What is weakly real (and it is NOT the ADX rule)

The **unconditional** EMA20-pullback continuation entry, pooled over all 993 extended-span trades: +0.127R net, week-cluster CI [+0.018, +0.245], 17/27 weeks positive. Marginally positive, short-biased (+0.147R short vs +0.015R long in-window) over a span that trended down — likely regime beta, not alpha. Conditioning on high ADX makes it *worse*, not better. If anything ever graduates from this lane it would be "EMA-pullback continuation as a signal family," and even that needs a regime-neutral span before belief.

## Reproduction-fidelity caveats (plain)

- Fills assume a resting limit at EMA20 filled at exactly EMA — optimistic by a spread.
- 1h bars cannot resolve intrabar path; I count stop before target on the same bar (conservative), which understates winners slightly — the artifact conclusion does not depend on this.
- Fees 0.12% RT flat; HYPE/XRP real slippage is worse, so their small positive cells shrink further.
- Candles are today's HL API data, not point-in-time bot state; ADX/EMA are deterministic from candles so this is low-risk.
- This simulation does NOT replay the bot's actual signals — it tests the *rule as a rule*. The counterfactual-file version of the claim was already killed in MISSED_EV_LOCKDOWN.

## Recommendation

1. **Do not** add an "enter continuation in high-ADX trends" graduated rule or A/B arm. The survivor is dead: it fails its own span ex-W23, underperforms control OOS, and its profit is concentrated in 2 crash windows.
2. Strike the corresponding line from EV_AND_MISSED follow-ups; the correct residual lesson is only the *negative* one already adopted: don't cite W1 missed-EV as evidence the agent is too cautious.
3. If exploring continuation entries at all, test the unconditional EMA-pullback family across a long-side-trending span first (backtest-before-adding mandate) — current evidence is one bear half-year.
