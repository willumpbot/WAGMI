# Laptop mission set 2: the hivemind co-operation study (written 2026-10-08 on the server)

You are the Claude Code session on the owner's laptop. It has about 12 GB of free RAM; the server has about
1 GB, so the heavy research belongs here. Work autonomously and push results. Read `bot/MINING_HANDOFF.md`
first (house rules, earlier findings, how to sync). Your mission-1–4 reports are in `bot/data/laptop_mining/`.

## Context: what the server built today
The owner wants a **hivemind**: every signal and voice in the system, per coin, graded, so it learns whose
view to trust. The plan is that eventually it tunes the bot itself. It's live on the server:
- `bot/tools/hivemind/assemble.py` builds per-coin state from these voices:
  - co-pilot market read (structure / pullback / +DI-DI driver / range)
  - base-rate history (`basemap.py`)
  - liquidation clusters, funding/OI
  - decision-time context (book lean, funding side, session, BTC 4h)
  - the bot's AI agents with report cards
  - IC strategy status
  - rules-manager rules
  - the bot's position and the owner's calls
- `bot/tools/hivemind/chief.py` is an Opus chief analyst whose calls are graded at 1d/5d.
- What's been established: no single voice predicts direction. Taking every signal loses about 10–14 bps per
  4h. Slices found in-sample died out-of-sample (your mission 4).

**The open question nobody has tested:** do voices have value TOGETHER, even though none has it alone?

## Mission 5: voice co-operation study (the core)
Build a per-day panel, plus a per-4h panel where the data allows. Use `bot/tools/hivemind/basemap.py`'s
Hyperliquid daily history (2020+ for the majors) and your 16k signal corpus. Wherever you can reconstruct
a voice point-in-time, include it. Candidates, each encoded as bull / bear / neutral:
- daily structure (EMA20 vs EMA50)
- stretch (price vs EMA20)
- 20d range third
- +DI/-DI driver
- RSI zone
- Bollinger position
- 7d momentum
- volatility expansion
- BTC 4h / 1d trend relative to the coin
- funding sign (backfill free from HL `fundingHistory`)
- OI change, where available
- the bot's strategy votes (from the corpus)
- weekday / session

Then answer, with train/test splits and cluster-bootstrap CIs (house rules):
1. **Redundancy:** the correlation matrix between voices. Which are copies of each other (e.g. structure vs
   driver)? Collapse them into independent families.
2. **Agreement:** when k independent families agree, does the forward 1d/5d return in that direction improve
   with k? Plot the consensus-vs-outcome curve. Is it monotonic, flat or inverted? (On the server's ledger,
   agree=3+ looked ANTI-predictive.)
3. **Contradiction:** when strong voices disagree (e.g. structure UP but driver SELLERS), what follows? Higher
   volatility? Mean reversion? Measure volatility and direction separately. Some voices may predict *size of
   move* even though none predict direction.
4. **Conditional trust:** does any voice work only inside a regime (e.g. driver only when ADX > 25)? Report
   only interactions that survive train/test.
5. **The honest bottom line:** is there any combination with an out-of-sample edge after 9 bps fees at 1–5
   day horizons? If not, say so plainly, and state what *is* predictable (volatility, range, path).

Deliverables:
- `bot/data/laptop_mining/COOPERATION.md` (headline first, with plain-language takeaways for a visual learner)
- `cooperation.json` (machine-readable)
- `voice_families.json`: for each voice, its family plus an independence weight. The server's hivemind will
  use this to stop double-counting copies.

## Mission 6: multi-timeframe base-rate maps (for the desk)
Extend the `basemap.py` approach with 4h-candle states: 4h structure, 4h stretch, 4h driver, and the daily
state combined with the 4h state. Compute next-1d/next-3d/next-5d return and volatility distributions per
combined state, with train (before 2025-06) / test (after) stability. Flag states whose distribution is stable
across both halves. Those are the only base rates the desk should headline.
- Deliverable: `bot/data/laptop_mining/basemap_mtf.json`, using the same key shape as basemap's `table.json`
  so the server can load it, plus `BASEMAP_MTF.md`.

## Mission 7 (if time remains): volatility forecasting
If mission 5 shows voices predict move SIZE better than direction, build and validate a simple next-1d/5d
realized-volatility forecaster. A swing trader can use it for stops and position sizing even without a
directional edge. Report the out-of-sample calibration.

Sync exactly as before: branch `laptop-mining-2026-10`, use plain `git add bot/data/laptop_mining/` (never `-f`), and commit +
push after EACH mission. Finish with a ≤10-line plain-language summary for the owner.
