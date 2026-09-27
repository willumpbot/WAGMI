# WAGMI Trading Co-Pilot

## What this is (and isn't)

This is **decision support for YOU, the human trader** - a set of read-only
tools that watch the coins you actually trade and surface the few things
worth your attention: where you are in the range, whether you'd be safe or
suicidal at a given leverage, what a trade actually costs in fees/funding
before you place it, and which coins on the wider Hyperliquid universe are
suddenly moving.

It is **NOT**:
- An autonomous trader. It never places, closes, or modifies an order.
- A predictive edge. Nothing here claims to know which way price goes next.
  A momentum/breakout "tailwind" signal built from this same kind of data
  was tested and refuted (see `copilot.py`'s module docstring) - so this
  tool sticks to arithmetic (fees, funding, liquidation distance, where-in-
  the-range) and discipline (don't chase, don't add into a falling knife,
  don't stack risk on top of risk), not price prediction.
- Connected to the live WAGMI bot in any way. It never imports `llm/`,
  `execution/`, `core/`, or `strategies/`, and never writes to `.env`,
  `data/replay/`, or any live-bot state file. It only reads market data
  (candles, funding, HL's public `meta`/`metaAndAssetCtxs`) via the
  standalone `data/fetchers/hl_native.py` client.

Think of it as a co-pilot that amplifies your own judgment - it cuts fee
drag, keeps you off the liquidation line, and flags setups/risks - not a
second brain that trades for you.

## The one command

Everything below runs through a single dispatcher:

```
python tools/copilot/cli.py <read|trade|movers|alerts> [flags]
```

Each underlying script (`copilot.py`, `pretrade.py`, `whats_moving.py`,
`copilot_alerts.py`) also still runs standalone with its own CLI - that's
intentional back-compat, in particular for the scheduled Discord alert job
(see below), which calls `copilot_alerts.py` directly and doesn't go through
`cli.py` at all.

---

## 1. `read` - per-coin briefs

```
python tools/copilot/cli.py read
python tools/copilot/cli.py read --symbol SOL
python tools/copilot/cli.py read --symbol POPCAT,SOL,ETH
python tools/copilot/cli.py read --equity 5000 --side long --lev-range 3-15
```

Default watchlist: BTC, SOL, POPCAT. For each symbol you get one brief with,
in order:

1. **Price / trend line** - current price, trend direction (UP/DOWN/CHOP)
   and strength (from EMA20 vs EMA50 + ADX), 7-day return.
2. **Funding-as-carry line** - what funding is costing or paying you per day
   at your notional. This is cost context, never a directional signal.
3. **The CALL: ADD / HOLD / WAIT** - ADD means you're at a support/lower-band
   zone in an intact (or at least non-down) trend, a reasonable spot to
   deploy the next tranche. HOLD means don't chase strength and don't trim a
   conviction hold into it either (a backtest showed swing-trimming into
   pumps is a disguised exit that surrenders upside - see `copilot.py`'s
   docstring for the finding). WAIT means the regime makes the call unsafe
   right now - either a falling knife (strong downtrend, don't catch it) or
   a dead-flat chop (no real dip to buy).
4. **RISK block - the loudest part.** A `[SAFE] / [RISKY] / [SUICIDAL]`
   verdict, the safe-max leverage for THIS coin's actual measured
   volatility (not a generic rule of thumb), your liquidation price and
   distance at your stated leverage, how often this coin has actually moved
   that far in a day historically, and a manual hard-stop price you should
   hit well before HL would liquidate you.
5. **`--lev-range LO-HI`** (default `3-15`, your real trading range) - a
   plain-language read on which part of that range is actually usable on
   this specific coin: HL's real per-asset max leverage (e.g. POPCAT caps at
   **3x** - most of a 3-15x range is simply impossible to open there), the
   volatility-derived safe ceiling, and the $ liquidation price at both ends
   of the usable range. Pass `--lev-range none` to turn this off.
6. **WARNINGS** - extreme funding, falling-knife, exhaustion, HL venue-cap
   violations.

Add `--discord` to also push the brief(s) to your webhook (uses the same
`WAGMI_DISCORD_WEBHOOK` as the rest of the repo) - use this deliberately,
it's a real push every time, no anti-spam here (that's what `alerts` is for).

## 2. `trade` - pre-trade fee/funding/liquidation card

```
python tools/copilot/cli.py trade "SOL long 10x 1500"
python tools/copilot/cli.py trade "POPCAT long 3x 800" --discord
```

Spec format: `"SYMBOL SIDE LEVERAGEx MARGIN_USD"` - `800` is the margin/
collateral you're putting up, **not** the notional (notional = margin x
leverage). Output:

- **Round-trip taker fee** in $ and as a % of your margin, plus the
  **potential** maker-fee alternative (labeled potential - a resting order
  can simply miss the fill, this isn't a guaranteed cheaper path).
- **R needed to scratch** - the price move required just to cover fees plus
  a rough per-symbol slippage estimate, before you're profitable at all.
- **Funding direction/$-per-day** at your notional, and a flag for when
  funding paid would exceed the one-time round-trip fee after N days (so a
  multi-day hold isn't secretly more expensive than it looks at entry).
- **Liquidation / safe-leverage** - same math as `read`, reused not
  duplicated.
- **Bottom line** - one sentence: total cost to open + hold 1 day, and the
  % move needed to scratch. Pure arithmetic, never a call on whether to
  take the trade.

## 3. `movers` - what's-moving scanner

```
python tools/copilot/cli.py movers
python tools/copilot/cli.py movers --top 15
```

Scans the **full HL perp universe** (~230 markets), applies a liquidity/
quality floor to cut out noise and obvious rugs, and surfaces the handful of
coins with genuinely unusual volume/price/OI activity right now. This is a
**radar, not a signal** - it finds attention/movement, never direction or
edge (the same momentum-style signal was tested standalone and refuted). A
parabolic, thin-OI coin topping the list is flagged as a **danger** (late /
thin / rug-risk), not an opportunity - that flag is the point, not a
caveat. Every line reads as "worth a look, here's the risk," never "buy
this." `--watch` lets you mark your own coins (default POPCAT,SOL,BTC) so
you can see where they rank against the rest of the universe. `--alert` (own
anti-spam/cooldown, same idea as below) pushes new top-decile entrants to
Discord; omit it to just print to stdout.

## 4. `alerts` - proactive Discord alerts

```
python tools/copilot/cli.py alerts                                  # dry-run preview, no push, no state write
python tools/copilot/cli.py alerts --equity 5000 --leverage 3 --send # REAL push
```

**Safety default: `cli.py alerts` never pushes to Discord unless you pass
`--send`.** Without it, `--dry-run` is injected automatically - you can run
it as many times as you like just to see what it would say.

This is also the tool that runs **on a schedule, every 2 hours**, via
Windows Task Scheduler (`WAGMI-Copilot-Alerts` task -> `run_alerts.ps1` ->
`copilot_alerts.py` directly - the scheduled job bypasses `cli.py`
entirely so its behavior is fixed and doesn't depend on any dispatcher
default). It watches the default 3-symbol list (**BTC, SOL, POPCAT**) and
pushes a Discord message **only when something actually changes**:

- The dip call enters **ADD** or a **falling-knife WAIT** (wasn't already
  there).
- The leverage verdict **escalates** into RISKY or SUICIDAL.

Everything else - unchanged state, HOLD/WAIT-chop shuffling, small numeric
wiggles that don't cross a bucket boundary - is deliberately ignored. A
6-hour cooldown per symbol is a second guard against flapping near a
boundary. You will not get re-pinged for a standing condition; you'll get
pinged once when it starts, and (only if you opt in with
`--alert-on-clear`) once when it clears.

Check `data/copilot/alerts.log` for the scheduled job's run history and
`data/copilot/alert_state.json` for its current per-symbol state.

---

## Honest caveats

- **This is discipline + risk + context, not a predictive edge.** Nothing
  here tells you which way a coin is going next. The value is cutting fee
  drag, keeping you off the liquidation line, and making you look at the
  right things before you act - not calling direction.
- **POPCAT caps at 3x leverage on Hyperliquid** - not a tool limitation,
  that's the venue's real per-asset max. Don't be surprised when `read`/
  `trade` say most of your usual 3-15x range is simply unavailable there.
- **POPCAT volume is currently thin** - roughly **$270-273K in 24h
  notional** as of this writing. Thin books mean the slippage estimate in
  the pre-trade card is a rougher approximation than on a deep market like
  BTC or SOL, and it also means don't expect to move real size without
  moving the price yourself.
- **Funding is cost context, never a signal.** A funding-fade "edge" was
  tested and came back null - this tool will tell you what funding is
  costing/paying, never imply it predicts direction.
- **The liquidation estimate is a slightly-optimistic floor.** It ignores
  funding accrual, cross-margin PnL on other positions, and slippage on the
  liquidation fill itself - real liquidation happens slightly earlier than
  the number shown. Treat the manual hard-stop as the actual line to
  respect.

## TODO / what would make this sharper

- **Personal-edge learner - blocked on one thing: your Hyperliquid wallet
  address.** Right now every read/warning here is generic (regime math,
  venue rules, volatility) - it has no memory of what has actually worked
  for *you*. HL exposes user fills/positions via a **public wallet address**
  (no private key, safe to share) through the same read-only API this tool
  already uses. Set `HL_API_KEY` (already a recognized env var elsewhere in
  this repo, currently unset) to your wallet address and a follow-on tool
  could pull your actual trade history to answer "what's your real win rate
  on POPCAT longs at 3x," "do you actually do better waiting for ADD zones
  or do you often skip them anyway" - personal, data-backed patterns instead
  of generic rules. Not built yet; this is the one input that unlocks it.
- Everything else here is stable and usable as-is; no other blocking gaps.
