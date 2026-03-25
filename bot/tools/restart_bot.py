"""
Request a graceful bot restart.

Usage: python -m tools.restart_bot "reason for restart"

Writes a file that the main loop checks every ~2-3 minutes.
The bot will gracefully shut down, cancelling pending orders first.

For the bot to actually restart, it should be running inside a restart loop:
    while true; do cd bot && python run.py paper; sleep 5; done

Or Terminal 1 (babysitter) should restart it after it stops.
"""

import os
import sys
from datetime import datetime, timezone


def main():
    reason = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Restart requested by tools/restart_bot.py"
    restart_file = os.path.join("data", ".restart_requested")

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    content = f"{reason} (at {timestamp})"

    with open(restart_file, "w") as f:
        f.write(content)

    print(f"Restart requested: {content}")
    print(f"Bot will pick this up within ~2-3 minutes and gracefully shut down.")
    print(f"File written: {restart_file}")


if __name__ == "__main__":
    main()
