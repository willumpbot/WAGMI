# Laptop mission set 3: risk tools for a leverage trader (written 2026-10-08 on the server)

You are the Claude Code session on the owner's laptop. Same house rules and sync as `MINING_HANDOFF.md`, and
the same `git add -f bot/data/laptop_mining/` habit. Commit and push after each mission.

**What the server did with your set-2 results.** Everything now lives in `bot/tools/hivemind/`, shown on the
owner's terminal (`WAGMI/terminal.html`):
- `voice_families.json` now drives the terminal's independent-voice counts.
- The move-size finding is a "bigger/smaller than usual" flag.
- Mission 6's verdict was respected: the desk keeps the daily-only base map.
- Your HAR-RV model runs live in `bot/tools/hivemind/volforecast.py`. It drives the "Exp. Move 1D" column, the
  levels table (in expected moves), and the position calculator's default stop (1.5× the forecast move).

**Where the owner is.** They swing-trade Hyperliquid perps with leverage, plus some shitcoins people send
them. Direction stays their call; nothing in the system has a directional edge. So the highest-value work now
is **risk**: where to put the stop, how much leverage, and how big a position to take, all conditioned on the
volatility forecast you built.

## Mission 8: adaptive stops from the vol forecast (the bridge to GEOMETRY.md)
Re-run your geometry sweep with **stop = k × forecast next-day move** (and k × the 5-day forecast) instead of a
fixed ATR multiple.
- Sweep k ∈ {0.5, 1, 1.5, 2, 3, 4, 6} and targets ∈ {0.5R, 1R, 1.5R, 2R, trailing at 1× forecast}.
- Use the same corpus, train/test split, tie rule, fees and paired bootstrap.
- Questions:
  - Does a forecast-scaled stop beat a fixed-ATR stop of the same average width?
  - What k minimises loss out of sample, and is it stable per symbol?
  - How do the median holding time and the share of trades stopped out change?
- Deliverable: `ADAPTIVE_STOPS.md` + `adaptive_stops.json`, with a one-line recommended default for the
  terminal's calculator.

## Mission 9: safe leverage and adverse-excursion tables
For each of the 6 coins, BTC/ETH/SOL/HYPE/XRP/NEAR (plus 4 high-volume memes on HL if the data is clean),
bucket days by forecast-volatility decile. Then measure the distribution of **maximum adverse excursion**
over 1, 3 and 5 days, for longs and for shorts, using hourly/4h candles for the path.
- Turn it into a table: "with the forecast at X%, the worst move against you was below Y% on 95% (and 99%) of
  days". Then derive the **max leverage whose liquidation sits beyond the 99th-percentile adverse move**,
  using Hyperliquid's maintenance-margin tiers per coin (the `meta` endpoint has maxLeverage; use realistic
  maintenance fractions).
- Validate out of sample: does the table built on train cover the stated % on test?
- Deliverable: `SAFE_LEVERAGE.md` + `safe_leverage.json`, keyed coin → vol-decile → horizon → {p95, p99,
  max_lev_long, max_lev_short}. Shape it so the terminal can read it directly.

## Mission 10: direction-free income: funding carry on Hyperliquid
Pull Hyperliquid `fundingHistory` (free) for the top ~40 perps by volume over the full available history.
- Questions:
  - How persistent is funding? (If funding was strongly positive over the last 24h, how often does it stay
    positive over the next 24h/72h?)
  - What would a simple carry approach have earned, net of realistic fees and slippage? For example, short the
    perp whenever trailing funding is in its top bucket, hedged with an equal long on a correlated asset or HL
    spot where it exists. Measure hedge drift honestly.
  - What are the tail risks (squeezes during high-funding regimes)?
- Be blunt about whether this is a real edge after costs and hedge error.
- Deliverable: `FUNDING_CARRY.md` + `funding_carry.json`.

Finish with a ≤10-line plain-language summary for the owner (they're a visual learner, so lead with the
one-sentence takeaway and the numbers that matter).
