# RQ11 — SESSION STRUCTURE: dollars by UTC session, trades + counterfactuals + candles

Date: 2026-07-01 (session-research agent). Script: `bot/tools/research/rq11_sessions.py` (rerunnable).
Data: `trade_ledger.csv` n=156 closed trades Jun 1–Jul 1 (superset of trades.csv's 90 — trades.csv is MISSING 54 trades summing −$324.73; ledger total +$45.74 is ground truth). Counterfactuals: `data/llm/counterfactual_resolved.jsonl`, 39,121 resolved raw records May 30–Jul 1, deduped to **293 episodes** (same symbol+side, 2h gap rule). Candles: Hyperliquid 1h, BTC/ETH/SOL, Mar 1–Jul 1 (2,929 bars each; Binance geo-blocked HTTP 451 from this box).
Entry hour = ledger close_ts − hold_hours (ledger timestamp is close time — verified against `trade_log.py` which stamps at close). Dollarization of CF episodes: pct × median actual notional ($670).

## VERDICT (one paragraph)
**No session is a real dollar edge; the night_session_block does NOT hold as a session-specific rule.** The only positive session cell (US 12-18, +$729/34 trades) is one trade — remove the $1,010 winner of Jun 3 and it is −$281. Night (00-06) actual trades are −$233/35 (t=−1.38, not significant) but EU 06-12 is just as bad (−$284/42) and 06-09 UTC is the single worst 3h block (−$523/21, the ONLY cell that survives fragility in its direction: still −$300 after removing its worst loss, t=−1.71). Counterfactual skipped signals lose in **every** session in the two recent eras — blocking night signals "saved" dollars only because blocking *anything* saved dollars. In the era the rule was derived from, blocking night would have **cost** money (night CF episodes +$39, 59% WR, May30–Jun10). The rule's value is general selectivity wearing a time-of-day costume. It is already `active:false` — leave it dead; do not resurrect.

## 1. Real trades by session (net $, entry hour, n=156, total +$45.74)
| Session | n | WR | total $ | rm-best $ | rm-worst $ | t |
|---|---|---|---|---|---|---|
| Asia 00-06 | 35 | .29 | **−232.74** | −310 | −171 | −1.38 |
| EU 06-12 | 42 | .17 | **−283.55** | −662 | −61 | −0.56 |
| US 12-18 | 34 | .18 | **+729.22** | **−281** | +917 | +0.70 |
| Late 18-24 | 45 | .29 | **−167.19** | −544 | +97 | −0.33 |

Era split (E1 Jun 1–15 / E2 Jun 16–Jul 1):
- Night: E1 −$237 (n=15, WR .33) → E2 **+$4** (n=20, WR .25, rm-best −$20). Sign flips. Not stable.
- US 12-18: E1 +$793 (n=14) → E2 **−$64** (n=20). The "edge" did not survive its own era. Driver = single $1,010 trade (2026-06-03 12:28).
- Late 18-24: E1 +$179 → E2 −$346. Sign flips.
- EU 06-12: −$213 → −$71. Only session negative in BOTH eras. 3h view: **06-09 UTC is the worst block** (−$523/21, WR .14; frag-robust both directions). 12-15 (+$964/14) is the $1,010-trade artifact (rm-best −$46).

## 2. Counterfactual episodes by session (293 episodes, $ @ $670 notional)
| Session | ALL n | ALL $ | CF1 May30–Jun10 | CF2 Jun16–25 | CF3 Jun26–Jul1 |
|---|---|---|---|---|---|
| Asia 00-06 | 78 | −195 | **+39** (n=22, WR .59) | −159 (n=35) | −76 (n=21) |
| EU 06-12 | 69 | −223 | −7 (n=22) | −96 (n=23) | −120 (n=24) |
| US 12-18 | 71 | −175 | −36 (n=27) | −45 (n=21) | −93 (n=23) |
| Late 18-24 | 75 | −164 | +11 (n=34) | −60 (n=28) | −114 (n=13) |

Reading: skipped signals lose everywhere post-Jun-16 (12/12 era×session cells negative in CF2+CF3). Night is not an outlier in any era — and in CF1 (the derivation window of the original "19% WR night" claim) night skips were the BEST cell. Adversarial check on the 2026-07-01 rescore's "DOLLAR-POSITIVE (keep)" verdict for night_session_block_v1: its own numbers show first fortnight −$451, and its 21 matched ACTUAL night trades made +$375 — the rule's CF "savings" (+$164) are smaller than what actual night trades earned when allowed. My independent episode dedup agrees: not era-stable, not session-specific.

## 3. Market structure by session (Hyperliquid 1h, Mar–Jun, BTC/ETH/SOL)
- **US 12-18 has the highest vol/range in ALL 4 months for ALL 3 symbols** (BTC mean 1h range 0.84% vs 0.54–0.62% elsewhere). This is the one genuinely stable structural fact (12/12 month×symbol cells).
- **EU 06-12 is the QUIETEST session** in Apr/May/Jun for all symbols — not night. The "night is dead/low-liquidity" premise behind the block is factually wrong for crypto; 00-06 UTC is mid-pack (Asia open).
- Trend efficiency (|net move|/path length per session-day) is flat: 0.37–0.44 across sessions. No session trends meaningfully better. US is marginally highest (0.42–0.44) — consistent with more vol, not more edge.
- Coherence note: the bot's worst actual block (06-09) sits inside the *quietest* market window — losses cluster where there's nothing to catch, which is a selectivity story (chop-trading), not a clock story.

## 4. Standard compliance & kill log
- Denominators: every cell above carries n. Nothing here graduates: largest session cell n=45; era cells n=13–35, most |t|<1.5.
- Fragility: applied both directions (rm-best for positive claims, rm-worst for negative). Only survivor: 06-09 UTC negative (n=21, t=−1.71 — still short of graduation and confounded with EU-quiet + early-June cold streak).
- **KILLED: "US 12-18 session edge"** — one-trade artifact ($1,010 on Jun 3; rm-best flips sign; died in E2). Do not build a session-boost.
- **KILLED: "night_session_block as session-specific alpha"** — CF-negative in its derivation era, redundant with general selectivity after. Already inactive; keep it off. No re-activation without n≥15 *night-specific* live evidence that diverges from the all-session baseline.
- Week-1-artifact test: no opportunity claim survives to need it — nothing to ship. If any time-of-day logic is ever revisited, the candidate is a *06-09 UTC caution flag*, and it must first be disentangled from the chop/selectivity confound (it may just be "don't trade quiet chop," which the confidence pipeline already owns).
- Caveat (actionable): **trades.csv under-reports — 90/156 rows, +$741.11 vs true +$45.74** (missing 54 trades summing −$324.73). Any prior analysis built on trades.csv inherits a ~+$695 optimistic bias; re-point at trade_ledger.csv. The `session_perf` block fed to the LLM prompt uses its own incremental tracker (`feedback/signal_quality.py`, `by_session` state) — source not reconciled against the ledger here; audit whether it caught all 156 closes (Quant-Brain-stats-suspect memory applies).
