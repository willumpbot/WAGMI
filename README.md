# NunuIRL Platform

Multi-strategy crypto auto-trading system with self-improving ML, ensemble voting, trailing stop loss, and dynamic leverage (1x-25x).

## Quick Start (Paper Trading with Signals)

```bash
cd bot
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your alert channels:

```bash
# Discord - create a webhook in your server's channel settings
DISCORD_WEBHOOK=https://discord.com/api/webhooks/YOUR_WEBHOOK_HERE

# Telegram - create a bot via @BotFather, get chat ID via @userinfobot
TELEGRAM_TOKEN=YOUR_BOT_TOKEN
TELEGRAM_CHAT_ID=YOUR_CHAT_ID
```

Then run:

```bash
# Paper trading (signals to Discord/Telegram):
python run.py paper

# One-shot signal check (print and exit):
python run.py signals

# Market assessment from all strategies:
python run.py status

# Backtest:
python run.py backtest --symbols BTC,ETH,SOL --days 30

# Backtest specific strategies:
python run.py backtest --symbols BTC,HYPE --days 60 --strategies regime_trend,monte_carlo_zones
```

## Architecture

```
bot/
  run.py                    # Unified launcher (paper, backtest, signals, status)
  multi_strategy_main.py    # Full bot loop
  trading_config.py         # All config via env vars
  strategies/               # 4 strategies + ensemble voting
  execution/                # Position manager, leverage, risk
  ml/                       # Self-improving ML learner
  backtest/                 # Backtesting engine
  alerts/                   # Discord + Telegram routing
  data/                     # CoinGecko data fetcher

api/                        # FastAPI backend (dashboard, trade logging)
web/                        # Next.js frontend
executor/                   # Copy trading executor
infra/                      # Docker Compose orchestration
```

## Strategies

| # | Strategy | Edge | Timeframes | Origin |
|---|----------|------|------------|--------|
| 1 | Regime Trend | WaveTrend + MACD/MFI multi-TF regime | 1h, 6h, 16h | Long-term bot |
| 2 | Monte Carlo Zones | SMA zones + 1000-sim price prediction | Daily | Swing bot |
| 3 | Confidence Scorer | Zone signals + historical win-rate tracking | Daily | Swing bot |
| 4 | Multi-Tier Quality | EMA crossover + VWAP + tiered confidence | 5m, 30m, 1h | Leverage bot |

Ensemble voting requires 2+ strategies to agree on direction. More consensus = higher confidence = more leverage.

## Leverage Tiers

| Confidence | Leverage | Requirements |
|-----------|----------|-------------|
| < 60% | No trade | - |
| 60-69% | 1x (spot) | Any 1 strategy |
| 70-79% | 2-3x | 2+ strategies agree |
| 80-89% | 3-5x | 2+ strategies agree |
| 90-94% | 5-10x | 3+ strategies agree |
| 95%+ | 10-25x | ALL strategies agree (rare) |

## Key Features

- **Trailing stop loss** - Activates after TP1 (40% partial close), trails by 1.5x ATR
- **Dynamic leverage** - 1x to 25x based on confidence + strategy consensus
- **ML self-improvement** - Learns from every trade outcome, adjusts confidence over time
- **Circuit breakers** - Halts on 5% daily loss, 5 consecutive losses, or 10% drawdown
- **CoinGecko data** - Supports all coins including HYPE
- **Discord + Telegram alerts** - Tiered routing (priority/regular/manual)
- **Dedup + rate limiting** - No spam, burst protection built in

## Hosting (for 24/7 paper trading)

Cheapest option: any VPS with Python 3.9+

```bash
# On your VPS:
git clone <repo> && cd NunuIRL-platform/bot
pip install -r requirements.txt
cp .env.example .env && nano .env  # add your webhook URLs

# Run in background with screen/tmux:
screen -S nunu
python run.py paper
# Ctrl+A, D to detach

# Or use systemd for auto-restart:
# See infra/ for Docker Compose setup
```

Recommended: DigitalOcean $6/mo droplet, Hetzner $4/mo VPS, or Railway/Render free tier.

## Exchange Integration (Future)

The bot currently runs as signal-only (paper trading + alerts). For live auto-trading:

- **Hyperliquid** - DEX, no KYC, 40x max, Python SDK available, API wallet for security
- **Blofin** - CEX, 150x max, demo trading API, Python SDK available
- Both support CCXT for unified interface

## Symbols Tracked

BTC, ETH, SOL, XRP, AVAX, HYPE, BNB, RENDER, JUP


⭐ THE REAL PHASES 1–10 (Corrected for Your Intent)
This version is built around one principle:

→ You only deploy real money AFTER you fully understand and trust the system.
Not before.

Not during.

After.

🟦 PHASE 1 — Core Bot (DONE)
Bot runs, trades, logs, and makes money.

You already completed this.

🟩 PHASE 2 — Structure, Safety, and Learning (CURRENT PHASE)
This is where you are right now.

This phase includes:

State machine

TP1% mapping

Precision table

Risk formulas

ML logging

Trade logging

Learning from every scan

Learning from every trade

Bot‑only positions

Manual trading compatibility

Telegram commands

VPS readiness (but NOT deployment)

You do NOT deploy real money here.

This phase is about making the bot safe and predictable.

🟧 PHASE 3 — Backtesting, Replay Mode, and Historical Validation
This is the phase you want BEFORE touching real money.

This is where you gain confidence.
This phase includes:

Full backtesting engine

Replay mode (feed historical candles into the live engine)

Scenario simulation

Stress tests

TP1→SL analysis

ML confidence vs PnL correlation

Symbol‑specific behavior analysis

Performance dashboards

You still do NOT deploy real money here.

This phase is about proving the bot works.

🟨 PHASE 4 — ML Retraining, Feature Engineering, and Adaptive Logic
Once you have backtesting + replay, you can improve the ML.

This phase includes:

ML retraining pipeline

Feature engineering

Adaptive TP1%

Adaptive trailing

Adaptive strategy weights

Regime detection

ML drift detection

Model versioning

You still do NOT deploy real money here.

This phase is about making the bot smarter.

🟫 PHASE 5 — Full System Validation & Confidence Building
This is the phase where you decide if the bot is ready for real money.

This phase includes:

Run the bot in paper mode for weeks

Compare paper results vs backtest results

Validate ML predictions

Validate risk filters

Validate TP1→SL protection

Validate early exit

Validate trailing

Validate precision

Validate state machine

Validate manual trading compatibility

Validate Telegram control

Validate crash recovery

You STILL do NOT deploy real money here.

This phase is about trust.

🟪 PHASE 6 — VPS Deployment (Paper Mode Only)
Now you deploy to a VPS — but still paper trading.

This phase includes:

VPS setup

VPN setup

Auto‑restart

Crash recovery

Persistent state

Telegram commands

Logging to disk

Daily log rotation

Hyperliquid precision enforcement

Network health checks

Still no real money.

This phase is about 24/7 stability.

🟥 PHASE 7 — Small Real Money Deployment (Controlled, Safe)
This is the FIRST time you use real money — and only after:

Backtesting

Replay

ML validation

Paper trading

VPS stability

Full system confidence

This phase includes:

$50–$200 real money

Strict risk limits

Daily loss limit

Weekly loss limit

Circuit breaker

Telegram alerts

Manual override

This phase is about real‑world validation.

🟦 PHASE 8 — Scaling Real Money (Gradual, Data‑Driven)
Only after Phase 7 proves stable.

This phase includes:

Increase size slowly

Increase leverage caps

Increase number of symbols

Add performance‑based scaling

Add drawdown‑based de‑scaling

This phase is about controlled growth.

🟩 PHASE 9 — Multi‑Symbol, Multi‑Threaded Engine
Now you expand horizontally.

This phase includes:

Independent position managers per symbol

Independent ML pipelines per symbol

Symbol‑specific configs

Multi‑threaded scanning

Multi‑symbol concurrency

This phase is about portfolio trading.

🟧 PHASE 10 — Institutional‑Grade Automation & Redundancy
This is the final evolution.

This phase includes:

Multi‑VPS redundancy

Failover

State replication

Hot‑swap ML models

Hot‑swap configs

Multi‑region deployment

Multi‑account support

Disaster recovery

Zero‑downtime updates

This phase is about full autonomy.

🎯 So what’s the corrected answer to your question?
You do NOT deploy real money until Phase 7.
