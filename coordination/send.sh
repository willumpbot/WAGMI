#!/bin/bash
# Append a message to the outbound inbox.
#
# Usage:
#   bash coordination/send.sh <TAG> <subject> [-- body]
#
# Example:
#   bash coordination/send.sh ANNOUNCE "Laptop online cycle 1" -- "Read the briefing, ready to coordinate"
#
# Detects whether to write to desktop->laptop or laptop->desktop based on
# the SENDER env var. Default sender is whatever's in coordination/SENDER file.

set -e
cd "$(dirname "$0")/.."

if [ -z "$SENDER" ]; then
    if [ -f coordination/SENDER ]; then
        SENDER=$(cat coordination/SENDER)
    else
        echo "ERROR: SENDER not set and coordination/SENDER missing." >&2
        echo "Set with: echo desktop > coordination/SENDER  (or laptop)" >&2
        exit 1
    fi
fi

if [ "$SENDER" = "desktop" ]; then
    INBOX="coordination/INBOX_DESKTOP_TO_LAPTOP.md"
elif [ "$SENDER" = "laptop" ]; then
    INBOX="coordination/INBOX_LAPTOP_TO_DESKTOP.md"
else
    echo "ERROR: SENDER must be 'desktop' or 'laptop' (got '$SENDER')" >&2
    exit 1
fi

if [ $# -lt 2 ]; then
    echo "Usage: $0 <TAG> <subject> [-- body]" >&2
    exit 1
fi

TAG="$1"
SUBJECT="$2"
shift 2
if [ "$1" = "--" ]; then
    shift
fi
BODY="$*"

TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

{
    echo
    echo "## $TS [$TAG] $SUBJECT"
    echo
    if [ -n "$BODY" ]; then
        echo "$BODY"
    fi
    echo
    echo "---"
} >> "$INBOX"

echo "Appended to $INBOX:"
echo "  $TS [$TAG] $SUBJECT"
echo
echo "Remember to commit + push:"
echo "  git add $INBOX && git commit -m 'msg: $SENDER $TAG $SUBJECT' && git push origin HEAD:historical-import-2026-05-30"
