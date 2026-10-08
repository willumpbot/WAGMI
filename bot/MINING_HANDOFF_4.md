# Laptop mission set 4 (written 2026-10-08 ~20:10Z on the server)

Read `bot/data/laptop_mining/SERVER_REPLY.md` first: it covers what was adopted, the owner's feedback, and the
new rule that **every deliverable ends with 1–3 trader rules, one number each**. Same house rules. Plain
`git add bot/data/laptop_mining/` (never `-f`). Commit and push after each mission.

## Mission 11: what happens at the levels the terminal flags
The terminal has a "Near a level" strip. It flags when price is within ½ expected daily move of the 20-day
high or low, the 50-day average, or a big liquidation cluster. The owner will look at these, so give them
base rates. For every touch of each level type on the six coins (BTC, ETH, SOL, HYPE, XRP, NEAR) plus your
validated alts, 2020+ (liquidation clusters only where your collector data allows):
- How often does price **break through** (close beyond it by ≥ 0.5 expected moves within 2 days) vs **reject**
  (move ≥ 1 expected move away)?
- How big is the follow-through after each outcome?
- Does the answer depend on the daily structure (uptrend vs downtrend), on the side approached from, or on
  the forecast vol quintile?
- Use a train/test split and in-minus-out vs a random-level null (same distance, random dates).

Deliverables:
- `LEVELS.md`
- `levels.json`, keyed level_type → structure → approach_side → {n, break_rate, reject_rate,
  median_follow_through, ci}, shaped for the terminal to read
- Trader rules at the end

## Mission 12: the coins people send the owner (meme / shitcoin risk card)
Using free sources only (DexScreener API `api.dexscreener.com/latest/dex/...`, GeckoTerminal OHLCV, and
Hyperliquid where listed), build `memecard.py`. Given a ticker or contract address, it returns:
- liquidity
- 24h volume
- pair age
- price history
- realised volatility
- max drawdown from ATH
- **estimated slippage for $100 / $500 / $2,000 orders** (from liquidity)
- a **position-size cap** that keeps slippage under 2%

Then test whether your HAR vol model's calibration transfers to DEX memes: on ~100 memes with 60+ days of
OHLCV, does it under-predict, and by how much? Ship a correction factor. Be honest about rug and
survivorship bias: dead tokens must be included, so sample from historical pair lists, not just today's
survivors.

Deliverables:
- `MEMECARD.md`
- `memecard.py` (importable: `card(query) -> dict`), which the server will wire into the terminal search box
- Trader rules

## Mission 13: should the muted strategies be flipped?
Five of the bot's strategies are IC-muted (rolling IC < 0, weight 0): confidence_scorer, multi_tier_quality,
bollinger_squeeze, regime_trend and mean_reversion. On your 15.6k-signal corpus plus anything newer you can
pull, test whether **inverting** each one (taking the opposite side) has an edge after 9 bps fees out of
sample, with block bootstrap and train/test sign stability.

The prior is "no" (every directional idea has died). It matters because the server currently drops ~99.8% of
signals through this gate (the `ic_muted` events in `trade_events.jsonl` since 2026-10-08). If inverting is
also flat, the honest recommendation is to keep the gate, and the owner's decision becomes easy.

Deliverables: `MUTED_FLIP.md` and `muted_flip.json`, plus a one-line verdict for the owner.

Finish with a ≤10-line plain-language summary (visual learner: takeaway first, one number per line).
