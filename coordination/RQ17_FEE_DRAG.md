# RQ17 — FEE DRAG MAP (2026-07-01)

**Standard:** THE_STANDARD.md v1.3 — denominators, era-splits, adversarial pass, week-1-artifact test, small-n humility.
**Script:** `bot/tools/research/rq17_fee_drag.py` (read-only over `bot/data/trade_ledger.csv` + `bot/data/trades.csv` + `bot/data/logs/exit_closes.jsonl`).
**Eras:** W1 = Jun 1–7, MID = Jun 8–23, LATE = Jun 24+.

## VERDICT
The round-trip fee floor is **~10.4 bps of notional, uniform across all 5 symbols** (taker both sides; matches the goldmine's "~10bps fees"). Fees are **not** the primary killer ex-W1 (fees $85 vs gross −$712), but they define the floor, and **one entire trade class lived below it: LLM_EXIT_AGENT closes — 57 trades, 0 net-positive, ever** (8 gross-positive, all flipped or dwarfed by fees; ex-W1: n=52, −$690 net, median realized |move| 23.5 bps ≈ 2× fees on a coin-flip direction = guaranteed bleed). Separately, a **ledger integrity hole**: 35/157 trades (Jun 2–10) have **blank fees with net==gross** — realized fee drag is understated by an estimated **$90–360** (vs $365 total logged fees), so early-era net PnL is overstated.

## 1. Data + integrity
- `trade_ledger.csv`: 157 rows; **123 parsed with fees**; identity `gross − fees + funding = net` holds on all 123 (0 violations > $0.02).
- **HOLE (new):** 35 rows Jun 2–10 have `fees=''` and `net_pnl == gross_pnl` (sum gross −$640.69). Missing fees estimated $92 (notional capped at p90=$3,772) to $360 (uncapped; inflated by tiny-move notional derivation). These 35 rows are EXCLUDED from all fee stats below. → belongs in HOLES.md.
- trades.csv (92 rows) matched 92/92 to ledger for setup metadata.
- Notional derived as |gross/move| → per-trade fee-bps is noisy when move≈0; **medians are robust, p90s are inflated** — read medians only.

## 2. Fee floor table (round-trip fees as bps of notional)
| Symbol | n | med RT fee (bps) | MID med | LATE med | breakeven \|move\| | move for fee≤25% gross | move for fee≤10% gross |
|---|---|---|---|---|---|---|---|
| BTC | 37 | 10.6 | 11.3 | 10.5 | ~11 bps | ~42 bps | ~106 bps |
| ETH | 31 | 9.5 | 8.8 | 10.1 | ~10 bps | ~40 bps | ~100 bps |
| SOL | 23 | 7.4 | 7.2 | 10.3 | ~10 bps* | ~41 bps | ~103 bps |
| HYPE | 21 | 10.0 | 10.1 | 10.4 | ~10 bps | ~42 bps | ~104 bps |
| XRP | 11 | 10.4 | — | 10.4 | ~10 bps | ~42 bps | ~104 bps |

*Current regime = LATE column: **all five symbols sit at 10.1–10.5 bps** (HL taker 4.5 bps/side + spread-crossing residue). SOL/ETH sub-10 medians are W1/MID artifacts. Slippage is NOT separately measured (no intended-price log); HL top-of-book spread ~1–2 bps BTC/ETH, ~2–5 bps XRP/HYPE → **practical planning floor: 12–15 bps expected favorable move minimum, ~42 bps for fees to be a rounding error (≤25% of gross), ~105 bps to trade like the winners do.**
- W1 median fee was 4.1 bps (n=20) — driven by TP2/TRAILING limit fills (W1 trailing med 1.4 bps, TP2 5.7 bps = **maker pricing**). Era-unstable; do not plan on it — but it proves **limit exits roughly halve the round trip** when they fill.

## 3. Fee drag map (fees as % of Σ|gross|, parsed 123)
**Per exit type (the real axis):**
| Exit | n | Σgross | Σfees | Σnet | fee%\|gross\| | med \|move\| | net+ |
|---|---|---|---|---|---|---|---|
| LLM_EXIT_AGENT | 57 | −706 | 61 | −767 | 8.6% | **26.8 bps** | **0/57** |
| SL | 46 | −416 | 175 | −590 | 23.3% | 96.5 bps | 12 |
| TRAILING_STOP | 16 | +1,287 | 19 | +1,268 | **1.5%** | 225.5 bps | 16/16 |
| TP2 | 3 | +881 | 110 | +771 | 12.5% | 298.8 bps | 3/3 |

**Per hold bucket:** <1h and 1–4h pay **16.4–16.6%** of gross magnitude in fees (Σnet −$1,039, 62 trades); ≥12h pays **3.7%** (Σnet +$60). 4–12h is where the money was (+$1,665) at 6.8%.
**Per symbol:** BTC most fee-punished (19.8% of |gross|; MID-era BTC = **39.4%** — med move 19.7 bps vs 11.3 bps fee = scalping the floor). SOL cheapest (2.2%).
**Per size:** S/M/L med fee-bps identical (~10) — fee floor is size-independent in this range; no tier relief.
**Per setup:** LLM_FIRST entries = 15.8% drag, −$1,073 net (n=66). num_agree=2 = 23.7% drag, −$488 (n=16) vs num_agree=1 = 11.4% (n=53) — more agreement did not buy bigger moves. (Signal-quality confound; small n.)
**Per regime:** `range` = 41.0% drag (n=15). Trends/high-vol 2–8%.

## 4. Where fees flip gross-positive → negative-net
10 flips found; **all dust** (|gross| ≤ $0.38) — 8 of 10 are LLM_EXIT_AGENT micro-scratches. Flips are not the dollar story. The dollar story:
- **21/123 trades (17%) realized |move| < the round-trip fee** — could not have profited even with perfect direction. **16/21 are LLM_EXIT_AGENT**, concentrated in 1–12h holds.
- **Never-had-a-chance classes (net of fees):** (a) LLM_EXIT_AGENT closes as a class — median realized move 23.5 bps ex-W1, 0/57 net-positive across all three eras (W1 0/5, MID 0/37, LATE 0/15 — era-stable); (b) MID-era BTC scalps (med move 19.7 bps vs 11.3 fee, n=16, −$51); (c) sub-1h holds (1 gross+, 0 net+, n=11); (d) `range`-regime entries at 41% drag.
- Winners' geometry for contrast: TRAILING/TP2 realized 225–300 bps = **20–30× the fee floor**. The system wins when it rides; it bleeds when it scratches.

## 5. Minimum-edge requirement (what the system should know)
At current fee levels, per trade on any symbol:
- **Absolute floor:** expected favorable move > **10.5 bps** (fees only, 100% hit-rate fantasy).
- **Realistic floor:** with ~50% direction accuracy and symmetric exits, expected edge (E[move·direction]) must exceed **~10.5 bps of notional per round trip**; with spread/slippage bound: **~12–15 bps**.
- **Practical gate:** thesis targets < **40 bps** expected move should not trade (fees >25% of hoped gross); the historically profitable classes all had ≥100 bps realized. This is consistent with, and explains, the goldmine kill: a −9 bps/4h gross stream can never clear a 10 bps floor at any threshold.
- **Cheapest lever seen in our own data:** maker/limit exits (W1 trailing fills at 1.4 bps) ≈ halve the round trip to ~6–7 bps. Recommendation only — bot code untouched (two agents editing).

## 6. Adversarial self-check
- **Week-1 test:** fee floor conclusion is W1-independent (MID 10.2 / LATE 10.4 med). LLM_EXIT_AGENT 0-net-positive holds in all three eras. BTC 19.8% headline drag IS W1-inflated ($172 of $203 BTC fees are W1 big-notional) — use MID/LATE rows instead. W1's cheap fees are a maker artifact, flagged, not extrapolated.
- **Fragility:** LLM_EXIT_AGENT has zero positive trades — removing the best trade cannot rescue it. TP2 (n=3), TIME_STOP (n=1), num_agree=3 (n=1), regime cells n<15: reported, not graduated.
- **Denominator honesty:** every table carries n; 35 fee-blank rows excluded and disclosed; per-trade fee-bps medians used, p90s distrusted (notional-derivation noise).
- **Refutation attempt:** "fees killed the system" — REJECTED. Ex-W1 fees $85 vs gross −$712 (12% of the loss). Signal quality is the killer; fees only guarantee that sub-25-bps-move trading loses. Both this and the goldmine's upstream-signal finding stand.

## 7. Ledger action items (for the wiring lane — NOT done here)
1. HOLES.md: fees blank on 35 trades Jun 2–10 (net==gross); early-era net overstated ~$90–360.
2. Fee floor (~10.5 bps RT + 40 bps practical minimum-move gate) belongs in the RECALL layer / LLM raw-context per §3b — with n and era attached.
3. The unwired rr/fee/ev floors noted in GOLDMINE item 12: this file supplies the number they were missing.
