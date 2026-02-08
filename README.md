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
