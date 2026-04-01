"""Allow running the dashboard with ``python -m dashboard`` from the bot/ directory."""

import logging
import os
import sys
import time
from pathlib import Path

# Ensure the bot/ directory is on sys.path so sibling package imports work.
_BOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)

# Load .env ----------------------------------------------------------------
try:
    from dotenv import load_dotenv
    env_path = Path(_BOT_DIR).parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s  %(message)s")
logger = logging.getLogger("dashboard")

# Initialise DB -------------------------------------------------------------
try:
    from data.db import init_db
    init_db()
except Exception as exc:
    logger.warning("Could not initialise DB: %s", exc)

# Start server ---------------------------------------------------------------
from dashboard.server import DashboardServer

port = int(os.getenv("DASHBOARD_PORT", "8080"))
srv = DashboardServer(port=port)
srv.start()

print(f"WAGMI Dashboard running at http://localhost:{port}")
print("Press Ctrl+C to stop.\n")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nShutting down...")
    srv.stop()
