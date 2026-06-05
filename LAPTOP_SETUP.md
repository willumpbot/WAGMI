# LAPTOP SETUP — Control Center Configuration

## What This Laptop Is

**Control Center** for the WAGMI trading system:
- Web dashboard (Next.js, port 3000)
- Development environment (code editing)
- Analysis & coordination hub
- Remote access to desktop bot
- Monitoring & testing

## Quick Start (Do This Now)

### 1. Install Web Dependencies

```bash
cd "C:\Users\vince\WAGMI PROJECT\WAGMI\web"
npm install
```

### 2. Start Web Dashboard

```bash
npm run dev
# Opens: http://localhost:3000
```

### 3. Configure API Endpoint

The web dashboard needs to know where the API is. Check `web/.env.local` or `web/next.config.js` for API URL:

```bash
# Should point to desktop's API (when running)
NEXT_PUBLIC_API_URL=http://[DESKTOP_IP]:8080
# or for local testing:
NEXT_PUBLIC_API_URL=http://localhost:8080
```

### 4. Test API Connection

```bash
curl http://localhost:8080/api/health
# Or when desktop is ready:
curl http://[DESKTOP_IP]:8080/api/health
```

## 5 Control Terminals Setup

### Terminal 1: Website Dashboard

```bash
cd "C:\Users\vince\WAGMI PROJECT\WAGMI\web"
npm run dev
# Serves http://localhost:3000
# Auto-refreshes on code changes
```

### Terminal 2: Code Editing

```bash
cd "C:\Users\vince\WAGMI PROJECT\WAGMI"
code .
# Or for specific area:
code bot/strategies/
```

### Terminal 3: Git/Coordination

```bash
cd "C:\Users\vince\WAGMI PROJECT\WAGMI"
git status
git branch
git log --oneline -5
# Push/pull coordination branches
```

### Terminal 4: API Testing

```bash
# Test bot health
curl http://[DESKTOP_IP]:8080/api/health

# Test equity endpoint
curl http://[DESKTOP_IP]:8080/api/equity

# Test recent trades
curl http://[DESKTOP_IP]:8080/api/trades/recent
```

### Terminal 5: Testing/Analysis

```bash
cd "C:\Users\vince\WAGMI PROJECT\WAGMI\bot"

# Run tests
pytest tests/

# Run specific tests
pytest tests/ -k "agent" -v

# Analysis scripts
python -c "import json; trades = json.load(open('data/llm/decisions.jsonl'))"
```

## Key Directories

```
web/                    # Next.js dashboard (PORT 3000)
  ├── package.json      # npm install here
  ├── pages/            # React components
  └── .env.local        # API endpoint config

api/                    # FastAPI backend (PORT 8080, runs on DESKTOP)
  ├── app/main_v2.py    # API endpoints
  └── requirements.txt   # Backend deps

bot/                    # Trading bot (runs on DESKTOP)
  ├── strategies/       # Edit here to improve signals
  ├── llm/agents/       # Edit agent prompts here
  ├── data/             # decisions.jsonl, trades.csv, etc.
  └── .claude/          # Custom skills (40+)

coordination/           # Two-way communication
  └── handshake.md      # Desktop ↔ Laptop sync log
```

## What to Edit Where

| Goal | Edit | How | Test |
|------|------|-----|------|
| Improve strategy signals | `bot/strategies/*.py` | Change signal logic | `pytest tests/ -k "ensemble"` |
| Tune agent prompts | `bot/llm/agents/prompts.py` | Modify agent system messages | `pytest tests/ -k "agent"` |
| Fix execution/risk | `bot/execution/*.py` | Change position sizing, risk gates | `pytest tests/ -k "safety"` |
| Improve web UI | `web/pages/*` | React components | `npm run dev` then http://localhost:3000 |
| Add new agent | `bot/llm/agents/coordinator.py` | Add to orchestration pipeline | Full test suite |

## Remote Access to Desktop

### Option 1: Via Claude Code Remote Control
```bash
# In Claude Code on this laptop:
# Settings > Remote Control > [Enable]
# Then: Claude on desktop sends commands back
```

### Option 2: Via SSH/RDP
```powershell
# From PowerShell on laptop:
ssh user@[DESKTOP_IP]  # If SSH enabled on desktop
# Or Windows RDP:
mstsc /v:[DESKTOP_IP]
```

### Option 3: Via Git Coordination
```bash
# Check desktop's status via git:
git log --oneline -5
git diff origin/main..origin/desktop-overdrive-2026-05-30

# Or read handshake:
cat coordination/handshake.md
```

## Coordination Workflow

1. **Desktop Claude** does work on `desktop-overdrive-2026-05-30` branch
2. **Laptop Claude** does work on `historical-import-2026-05-30` branch
3. Both update `coordination/handshake.md` with status
4. **Vince** reviews both branches and merges to main

**DO NOT push directly to main from either laptop or desktop.**

## What's Running Where

```
DESKTOP (The Bot Host)
├── Python bot (PID 1864, 30s scans)
├── FastAPI backend (port 8080)
└── Health check (heartbeat.txt every 30s)

LAPTOP (This Machine)
├── Next.js dashboard (port 3000) ← runs here
├── Code editor (VS Code) ← edit strategies/agents here
├── Git coordination ← push/pull branches
└── Testing environment ← pytest, analysis
```

## Next Steps

1. **Install web deps:** `cd web && npm install`
2. **Start dashboard:** `npm run dev` (Terminal 1)
3. **Check desktop status:** Open `coordination/handshake.md`
4. **Wait for desktop Claude** to confirm bot health
5. **Then:** Run analysis on historical data (Terminal 5)

---

**You're now ready to use this laptop as your control center.**
