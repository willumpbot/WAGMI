"""
Pre-Flight Validation for Live Trading.

Checks every critical requirement before switching from paper to live mode.
Run: cd bot && python -m tools.preflight_check

Exit codes:
  0 = All checks passed, safe to go live
  1 = Warnings present but passable
  2 = Critical failures, DO NOT go live
"""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("preflight")

PASS = "[PASS]"
WARN = "[WARN]"
FAIL = "[FAIL]"
SKIP = "[SKIP]"


class PreflightResult:
    def __init__(self):
        self.checks = []
        self.critical_failures = 0
        self.warnings = 0

    def add(self, status, name, detail=""):
        self.checks.append((status, name, detail))
        if status == FAIL:
            self.critical_failures += 1
        elif status == WARN:
            self.warnings += 1

    def report(self):
        print("\n" + "=" * 60)
        print("  PRE-FLIGHT VALIDATION FOR LIVE TRADING")
        print("=" * 60 + "\n")
        for status, name, detail in self.checks:
            line = f"  {status} {name}"
            if detail:
                line += f": {detail}"
            print(line)
        print()
        if self.critical_failures > 0:
            print(f"  VERDICT: FAIL — {self.critical_failures} critical issue(s)")
            print("  DO NOT GO LIVE until all FAIL items are resolved.")
        elif self.warnings > 0:
            print(f"  VERDICT: PASS WITH WARNINGS — {self.warnings} warning(s)")
            print("  Review warnings before proceeding.")
        else:
            print("  VERDICT: ALL CLEAR — safe to go live")
        print("\n" + "=" * 60)


def check_env_vars(result: PreflightResult):
    """Verify required environment variables are set."""
    required = {
        "ANTHROPIC_API_KEY": "LLM decision engine",
    }
    exchange_required = {
        "HL_API_KEY": "Hyperliquid wallet address",
        "HL_API_SECRET": "Hyperliquid private key",
    }
    recommended = {
        "TELEGRAM_TOKEN": "Trade alerts",
        "TELEGRAM_CHAT_ID": "Alert destination",
    }

    for var, purpose in required.items():
        val = os.getenv(var, "")
        if val:
            result.add(PASS, f"ENV {var}", f"Set ({purpose})")
        else:
            result.add(FAIL, f"ENV {var}", f"MISSING — needed for {purpose}")

    for var, purpose in exchange_required.items():
        val = os.getenv(var, "")
        if val:
            result.add(PASS, f"ENV {var}", f"Set ({purpose})")
        else:
            result.add(WARN, f"ENV {var}", f"Not set — needed for live orders ({purpose})")

    for var, purpose in recommended.items():
        val = os.getenv(var, "")
        if val:
            result.add(PASS, f"ENV {var}", f"Set ({purpose})")
        else:
            result.add(WARN, f"ENV {var}", f"Not set — {purpose} won't work")


def check_environment_mode(result: PreflightResult):
    """Check ENVIRONMENT setting."""
    env = os.getenv("ENVIRONMENT", "paper")
    if env == "production":
        result.add(PASS, "ENVIRONMENT", "production (live mode)")
    elif env == "paper":
        result.add(WARN, "ENVIRONMENT", "paper — change to 'production' for live")
    else:
        result.add(WARN, "ENVIRONMENT", f"'{env}' — expected 'production' or 'paper'")


def check_safety_params(result: PreflightResult):
    """Verify safety parameters are conservative."""
    cb_overrides = int(os.getenv("MAX_CB_OVERRIDES", "0"))
    if cb_overrides == 0:
        result.add(PASS, "CB overrides", "Disabled (0)")
    else:
        result.add(WARN, "CB overrides", f"Set to {cb_overrides} — recommend 0 for live")

    max_dd = float(os.getenv("MAX_DRAWDOWN_PCT", "0.10"))
    if max_dd <= 0.10:
        result.add(PASS, "Max drawdown", f"{max_dd:.0%}")
    else:
        result.add(WARN, "Max drawdown", f"{max_dd:.0%} — recommend <=10%")

    session_dd = float(os.getenv("MAX_SESSION_DRAWDOWN_PCT", "0.20"))
    if session_dd <= 0.20:
        result.add(PASS, "Session drawdown halt", f"{session_dd:.0%}")
    else:
        result.add(WARN, "Session drawdown halt", f"{session_dd:.0%} — recommend <=20%")

    risk_per = float(os.getenv("RISK_PER_TRADE", "0.005"))
    if risk_per <= 0.01:
        result.add(PASS, "Risk per trade", f"{risk_per:.1%}")
    else:
        result.add(FAIL, "Risk per trade", f"{risk_per:.1%} — too high, max 1%")


def check_kill_switch(result: PreflightResult):
    """Check kill switch is not active."""
    kill_file = os.getenv("KILL_SWITCH_FILE", "data/.kill_switch")
    if os.path.exists(kill_file):
        try:
            with open(kill_file) as f:
                reason = f.read().strip()[:100]
        except Exception:
            reason = "unknown"
        result.add(FAIL, "Kill switch", f"ACTIVE — {reason}. Delete {kill_file} to clear.")
    else:
        result.add(PASS, "Kill switch", "Not active")


def check_data_files(result: PreflightResult):
    """Check critical data files exist and are valid."""
    files = {
        "data/trades.csv": "Trade history",
        "data/llm/decisions.jsonl": "LLM decision log",
    }
    for path, purpose in files.items():
        if os.path.exists(path):
            size = os.path.getsize(path)
            result.add(PASS, f"Data: {path}", f"Exists ({size:,} bytes)")
        else:
            result.add(WARN, f"Data: {path}", f"Missing — {purpose} won't have history")


def check_tests(result: PreflightResult):
    """Run test suite (quick mode)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no", "-x"],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode == 0:
            # Parse test count from output
            last_line = [l for l in proc.stdout.strip().split("\n") if l.strip()][-1]
            result.add(PASS, "Test suite", last_line.strip())
        else:
            result.add(FAIL, "Test suite", f"FAILED — {proc.stdout.strip()[-200:]}")
    except subprocess.TimeoutExpired:
        result.add(WARN, "Test suite", "Timed out (120s) — run manually")
    except Exception as e:
        result.add(WARN, "Test suite", f"Could not run: {e}")


def check_exchange_connectivity(result: PreflightResult):
    """Test exchange connectivity (read-only)."""
    try:
        import ccxt
        hl = ccxt.hyperliquid({
            "apiKey": os.getenv("HL_API_KEY", ""),
            "secret": os.getenv("HL_API_SECRET", ""),
        })
        # Read-only: fetch ticker
        ticker = hl.fetch_ticker("BTC/USDC:USDC")
        if ticker and ticker.get("last"):
            result.add(PASS, "Exchange connectivity", f"BTC/USDC: ${ticker['last']:,.0f}")
        else:
            result.add(WARN, "Exchange connectivity", "Connected but no price data")
    except ImportError:
        result.add(SKIP, "Exchange connectivity", "CCXT not installed")
    except Exception as e:
        err = str(e)[:100]
        if "API" in err or "auth" in err.lower():
            result.add(WARN, "Exchange connectivity", f"Auth issue: {err}")
        else:
            result.add(WARN, "Exchange connectivity", f"Failed: {err}")


def check_disk_space(result: PreflightResult):
    """Verify sufficient disk space."""
    import shutil
    try:
        usage = shutil.disk_usage(os.path.dirname(os.path.abspath(".")))
        free_gb = usage.free / (1024 ** 3)
        if free_gb > 1.0:
            result.add(PASS, "Disk space", f"{free_gb:.1f}GB free")
        else:
            result.add(WARN, "Disk space", f"Only {free_gb:.1f}GB free")
    except Exception:
        result.add(SKIP, "Disk space", "Could not check")


def check_cb_state(result: PreflightResult):
    """Check circuit breaker saved state."""
    cb_path = "data/logs/circuit_breaker_state.json"
    if os.path.exists(cb_path):
        try:
            with open(cb_path) as f:
                state = json.load(f)
            tripped = state.get("tripped", False)
            halted = state.get("session_halted", False)
            if halted:
                result.add(FAIL, "CB state", "Session HALTED — need manual reset")
            elif tripped:
                result.add(WARN, "CB state", f"Tripped: {state.get('trip_reason', '?')}")
            else:
                result.add(PASS, "CB state", "Clean")
        except Exception as e:
            result.add(WARN, "CB state", f"Could not read: {e}")
    else:
        result.add(PASS, "CB state", "No saved state (fresh start)")


def main():
    result = PreflightResult()

    print("Running pre-flight checks...\n")

    check_env_vars(result)
    check_environment_mode(result)
    check_safety_params(result)
    check_kill_switch(result)
    check_cb_state(result)
    check_data_files(result)
    check_disk_space(result)
    check_exchange_connectivity(result)
    check_tests(result)

    result.report()

    if result.critical_failures > 0:
        sys.exit(2)
    elif result.warnings > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
