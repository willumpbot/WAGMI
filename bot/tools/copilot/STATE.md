# WAGMI Co-Pilot — Current State (read this first)

**As of 2026-08-03.** One page to catch up. Details live in `SIGNAL_SCORECARD.md`
(signals) and `LIVEBOT_RISK_AUDIT.md` (risk + measurement). This is the top-level.

## What the machine is now

An **honest risk co-pilot + a self-running forward-evidence engine.** It does not
have — and cannot manufacture from the exhausted 14-month history — a directional
entry edge. What it does: keep a leveraged position from blowing up (correct
liquidation math, horizon-validated leverage, the falling-knife path-risk gate,
correlated-exposure `book` view, honest fee/funding/session-vol context), and it
now collects its own forward evidence to test — on unseen data, pre-registered —
whether any edge exists. **It won't lie to you about which of those it is.** The
entry decision stays yours; the data says your discretion beats every mechanical
entry rule tested (~23 of them).

## What's running by itself (nothing for you to do)

- **Live paper bot** — alive, flat, 0 errors, ~$4760 equity.
- **Liquidation collector** — un-backfillable cascade data, reboot-watchdog'd.
- **Funding/OI collector** — daemon in the bot.
- **Daily job (13:13 UTC)** — logs the co-pilot's calls + runs all 5 pre-registered
  hypothesis harnesses (H1–H5), strictly gated so nothing concludes early.
- **Alerter (every 2h)** — Discord alerts on real ADD/knife transitions (fixed a
  silent-failure bug; you're getting them again).

## The forward bet (the one real path to knowing if edge exists)

Five hypotheses were pre-registered *before* their outcome data existed, so the
eventual test can't be post-hoc fished. Each has a verified, gated analysis harness
that auto-surfaces its result to `data/copilot/daily.log` the moment its bar clears:

| Hypothesis | Tests | Answerable |
|---|---|---|
| H3 / H5 | liquidation clustering & session-timing | **~11 days** |
| H1 / H2 | ADD-vs-WAIT return, weather regime | weeks–months |
| H4 | OI-buildup → cascade risk | weeks–months |

Nothing to do but wait — I'll bring you each result when it lands.

## Your decision items (all optional, all small-dollar at current size)

From `LIVEBOT_RISK_AUDIT.md` — owner-gated because they touch live-bot code, and
they matter most if you scale leverage back up:

1. **Exchange-side resting stops** — your SL is bot-process-dependent; one trade
   slipped 11% through its stop during a 153h outage (survived only at 1.5×).
2. **Confidence-sizing flaw** — the bot sizes *up* on high-confidence trades, but
   confidence is anti-predictive; a notional cap would cut drawdown ~75%.
3. **Five dead "adaptive" subsystems** — `self_tuning` tiers, the circuit breaker,
   the drawdown dial, the strategy-reactivation instrument, the decision ledger all
   look active but are dead/inert/broken. Decide: wire them or delete the facade.
4. **Two elevated scheduling commands** (need admin) — reboot-persist the liq
   collector + register the 7am briefing. Watchdog covers the collector meanwhile.

## The honest bottom line

The session didn't find an edge (none exists in the old data). What it built is a
machine that tells you the truth about its limits, protects a leveraged book, and
can find a real edge if one shows up in the forward data — without fooling itself.
That truthfulness was the thing that was actually broken, and it's fixed.

## THE CALL COMMAND — your discretion, instrumented (added 2026-08-06)

The highest-leverage instrument yet. You log your OWN entry and it does 3 things
at once: (1) logs your read with an entry-time-safe snapshot → forward proof of
whether YOUR discretion has edge, accruing every trade not every 60 days;
(2) hands back survive-the-trade risk math; (3) captures the RIGHT features
(flow/holders for memes, not dead OHLCV). It never claims to know your direction.

    python tools/copilot/cli.py call POPCAT long "reclaimed 200MA" --leverage 3 --equity 5000
    python tools/copilot/cli.py call KITTY long "range low reclaim, holders ripping"
    python tools/copilot/cli.py call resolve      # (auto-runs in the daily job)

HL coins → liq-safe leverage / liq price / fee-cleared stop / 0.5%-risk size /
book-correlation. DEX-spot memes → size + organic-health + slippage + flow
(honestly NO leverage/liq — it's spot). Gated: no edge verdict until n>=20 calls.
Ledger: data/copilot/owner_call_ledger.jsonl. ONE thing still open: how you fire
it from your phone (Discord-inbound recommended — see below / SIGNAL_SCORECARD).

## Micro-cap frontier (added 2026-08-06)

We reached the arena you actually trade — Solana cat/meme coins ($POPCAT, $KITTY,
etc.) — via free public data (GeckoTerminal candles + DexScreener liquidity +
Jupiter health). Two honest results so far:

1. **Wash-metric artifact caught+fixed.** An early pass flagged 14/15 coins as
   "wash trading"; cross-checking against Jupiter's real `organicScore` proved
   that was a measurement bug (it flagged strict organic-buy *volume*, ~10% even
   for healthy coins). Fixed. The clean set is **12 genuinely-traded coins**;
   8 (incl. 3 dead pump.fun "PEPE" clones) correctly excluded.

2. **History track = clean null.** A full-moat harness (entry-time-safe, net-of-
   cost, OOS-decisive, BH-FDR, negative-control-verified) ran 7 hypotheses × 12
   coins: **0 survivors.** Same verdict as the HL data — no mechanical history
   edge. **The structural reason matters:** the only place edge could plausibly
   live — a coin's first &lt;90 days — is *unreachable by history* (GeckoTerminal's
   ~180d window predates all 12 survivors). Early-life is FORWARD-only by
   construction. So the real micro-cap test can only be run going forward, on
   coins tracked from birth — which is the instrument now being built.
