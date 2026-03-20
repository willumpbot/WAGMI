# START — How to Run Everything

> Quick guide for coming back after a break. Two commands, two terminals.

---

## Prerequisites (one-time setup)

```bash
# 1. Install Python deps
cd /home/user/WAGMI/bot && pip install -r requirements.txt
cd /home/user/WAGMI/api && pip install -r requirements.txt

# 2. Install Node deps
cd /home/user/WAGMI/web && npm install

# 3. Set up environment (if not done)
cp /home/user/WAGMI/bot/.env.example /home/user/WAGMI/bot/.env
# Edit bot/.env — add ANTHROPIC_API_KEY at minimum
```

---

## Running (two terminals)

### Terminal 1 — API backend (port 8000)
```bash
cd /home/user/WAGMI/api
uvicorn app.main:app --reload --port 8000
```

### Terminal 2 — Web dashboard (port 3000)
```bash
cd /home/user/WAGMI/web
npm run dev
```

Open browser: **http://localhost:3000**

---

## Optional: Run the trading bot

### Terminal 3 — Paper trading bot
```bash
cd /home/user/WAGMI/bot
python run.py paper
```

The bot writes to `bot/data/` — the dashboard reads from there automatically.

---

## Quick sanity checks

```bash
# Is the API working?
curl http://localhost:8000/v1/summary

# Is the build clean?
cd /home/user/WAGMI/web && npm run build

# Run bot tests
cd /home/user/WAGMI/bot && pytest tests/ -x
```

---

## Dashboard pages

| URL | What it shows |
|-----|---------------|
| `/` | Dashboard — KPIs, heatmap, live signals |
| `/today` | Morning brief — regime, daily targets |
| `/signals` | Live signal breakdown per strategy |
| `/copy-trade` | How to manually copy bot trades |
| `/portfolio` | Open positions, PnL |
| `/results` | Track record — equity curve, trade table |
| `/performance` | Win rates, by-symbol breakdown |
| `/backtest` | Run backtests, view historical results |
| `/forensics` | Deep loss analysis |
| `/llm-audit` | LLM decision audit trail |
| `/ai-decisions` | Decision theater — each agent's reasoning |
| `/strategies` | Strategy health, signal funnels |
| `/learn` | Educational hub — how everything works |
| `/pricing` | Cost breakdown |
| `/about` | Project transparency |

---

## Branch
Active development: `claude/enable-llm-trading-bot-TEfDG`
