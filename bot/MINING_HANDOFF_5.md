# Laptop mission 14: PRIORITY: verify the spot/perp basis trade (written 2026-10-08 ~20:20Z)

Do this BEFORE the remaining set-4 missions. It is the first candidate for an edge that does not need to
predict direction.

**What the server adopted from your last pushes:**
- `risk_voice.py` is now THE source of truth for stops, targets and safe leverage on the terminal (loaded by
  path from `bot/data/laptop_mining/`).
- `squeeze.json` "+ consensus" drives a new "Squeeze L/S" column. We use our `dissent_families` as `disagree`;
  it is close to, but not identical to, your 8-family count. Tell us if that matters.
- Geometry walk-forward 4/4 is on the owner's decision card for widening the bot's stops.
- FUNDING_CARRY's persistence numbers are in the rules manager's notes.

## Mission 14: is same-asset funding harvesting real on Hyperliquid?
Your FUNDING_CARRY.md caveat estimated +0.487% per 3-day cycle at a 99.4% hit rate for the same-asset
version: long spot + short perp on the same coin, delta-flat by construction. Settle it:

1. **Availability.** Which perps have a Hyperliquid SPOT market for the same asset? Use the `spotMeta` and
   `spotMetaAndAssetCtxs` info endpoints, and watch for wrapped names like UBTC/UETH/USOL vs native HYPE/PURR.
   For each pair report:
   - spot 24h volume
   - spot order-book depth within 0.5% and 1%
   - typical spot/perp basis (spot mid vs perp mark) and how it moves
2. **Real costs.**
   - HL spot + perp taker/maker fees at the owner's likely tier (base tier)
   - slippage for $1k / $5k / $25k clips from the real books
   - the basis risk on entry and exit, measured from history if `candleSnapshot` works for the spot pairs
   - funding is paid hourly on HL, so use hourly granularity
3. **Backtest, honestly.**
   - Enter when trailing-24h funding is ≥ 80th percentile, exit when it drops below the median (or after N days).
   - Size by available spot depth.
   - Count every fee and the measured basis change.
   - Use a train/test split.
   - Report net % per cycle, per year at realistic capacity, the worst cycle, and how often basis moves wipe a
     cycle's funding.
4. **Risks to state plainly:**
   - perp-leg liquidation if the coin squeezes (use SAFE_LEVERAGE)
   - spot-leg custody/depeg for wrapped assets
   - funding flipping negative
   - capacity

Deliverables:
- `BASIS_TRADE.md` + `basis_trade.json`, keyed coin → {spot_symbol, depth, fees, net_per_cycle, ci, capacity_usd, verdict}
- 1–3 trader rules, one number each, e.g. "Only harvest when funding ≥ X%/day on coins with ≥ $Y spot depth"

If it is real, the server will add a "Carry" panel to the terminal showing live funding, the basis and expected
net yield per coin. If it is not, say so in one line.

Then continue with set 4 (missions 11–13), and keep polling for new handoffs every ~30 min.
