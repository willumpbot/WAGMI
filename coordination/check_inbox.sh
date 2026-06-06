#!/bin/bash
# Show unread / recent messages from the other side's outbox.
#
# Usage: bash coordination/check_inbox.sh [count]
#   count: how many recent messages to show (default 5)
#
# Reads SENDER from env or coordination/SENDER file to decide which inbox to check.

set -e
cd "$(dirname "$0")/.."

COUNT="${1:-5}"

if [ -z "$SENDER" ]; then
    if [ -f coordination/SENDER ]; then
        SENDER=$(cat coordination/SENDER)
    else
        echo "ERROR: SENDER not set." >&2
        exit 1
    fi
fi

if [ "$SENDER" = "desktop" ]; then
    INBOX="coordination/INBOX_LAPTOP_TO_DESKTOP.md"
    OTHER="laptop"
elif [ "$SENDER" = "laptop" ]; then
    INBOX="coordination/INBOX_DESKTOP_TO_LAPTOP.md"
    OTHER="desktop"
else
    echo "ERROR: SENDER must be 'desktop' or 'laptop'" >&2
    exit 1
fi

# Fetch latest from origin
git fetch origin historical-import-2026-05-30 2>&1 | tail -1

# Check if remote inbox is ahead
LOCAL_INBOX_HASH=$(git hash-object "$INBOX" 2>/dev/null || echo "missing")
REMOTE_INBOX_HASH=$(git rev-parse "origin/historical-import-2026-05-30:$INBOX" 2>/dev/null || echo "missing")

if [ "$LOCAL_INBOX_HASH" != "$REMOTE_INBOX_HASH" ] && [ "$REMOTE_INBOX_HASH" != "missing" ]; then
    echo "(remote inbox differs from local — showing REMOTE content)"
    echo
    git show "origin/historical-import-2026-05-30:$INBOX" 2>/dev/null > /tmp/_inbox_remote.md
    INBOX_FILE="/tmp/_inbox_remote.md"
else
    INBOX_FILE="$INBOX"
fi

echo "============================================="
echo "  Inbox from $OTHER  (last $COUNT messages)"
echo "============================================="
echo

# Extract last N message blocks (each block starts with "## " and ends at next "## " or "---")
python3 - "$INBOX_FILE" "$COUNT" <<'EOF'
import sys, re

path, count = sys.argv[1], int(sys.argv[2])
text = open(path, encoding='utf-8').read()

# Split on "## " message headers
blocks = re.split(r'\n(?=## \d{4})', text)
# Filter to actual message blocks
msgs = [b.strip() for b in blocks if re.match(r'^## \d{4}', b.strip())]

# Show last N
for m in msgs[-count:]:
    print(m)
    print()
    print('---')
    print()

if not msgs:
    print("(no messages yet)")
EOF

echo "============================================="
echo "  Tip: see all unread with 'git log -p $INBOX'"
echo "============================================="
