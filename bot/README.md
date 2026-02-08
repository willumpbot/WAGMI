NunuIRL Bot

Multi-strategy auto-trading bot with ensemble voting, self-improving ML, and trailing stop loss.

## Quick Start (Paper Trading)
```bash
cd bot
cp .env.example .env
# Edit .env with your Discord webhook and/or Telegram token
pip install -r requirements.txt
python multi_strategy_main.py
```

## Docker
```bash
docker build -t nunuirl_bot:local .
docker run --rm --env-file .env nunuirl_bot:local
```

## Strategies
- Regime Trend (1h/6h/16h WaveTrend + MACD/MFI)
- Monte Carlo Zones (SMA20/50 + MC simulation)
- Confidence Scorer (adaptive zone scoring with win rate tracking)
- Multi-Tier Quality (EMA crossover + VWAP + tiered signals)

## Configuration
- Copy `.env.example` to `.env` and edit values
- `ENVIRONMENT=paper` for paper trading (default), `production` for live
- Set `DISCORD_WEBHOOK` and/or `TELEGRAM_TOKEN` + `TELEGRAM_CHAT_ID` for alerts
