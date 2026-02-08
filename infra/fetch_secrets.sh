#!/usr/bin/env bash
# fetch_secrets.sh - robust helper to fetch secrets from AWS Secrets Manager
# Usage: fetch_secrets.sh [secret-name] [out-file] [format]
#   secret-name: AWS Secrets Manager secret id (default: nunuirl/staging)
#   out-file: path to write the secret (default: .env.staging)
#   format: dotenv | json (default: dotenv)

set -euo pipefail
SECRET_NAME=${1:-nunuirl/staging}
OUT_FILE=${2:-.env.staging}
FORMAT=${3:-dotenv}

command -v aws >/dev/null 2>&1 || { echo "ERROR: aws CLI not found. Install and configure AWS CLI." >&2; exit 2; }
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq not found. Install jq to parse JSON." >&2; exit 2; }

TMPFILE=$(mktemp)
cleanup() { rm -f "$TMPFILE" || true; }
trap cleanup EXIT

echo "Fetching secret '$SECRET_NAME' into '$OUT_FILE' (format=$FORMAT)"
if ! aws secretsmanager get-secret-value --secret-id "$SECRET_NAME" --query SecretString --output text > "$TMPFILE"; then
	echo "ERROR: failed to fetch secret '$SECRET_NAME' from AWS Secrets Manager" >&2
	exit 3
fi

# Validate JSON
if ! jq empty "$TMPFILE" >/dev/null 2>&1; then
	echo "ERROR: secret fetched is not valid JSON" >&2
	cat "$TMPFILE" >&2
	exit 4
fi

if [ "$FORMAT" = "json" ]; then
	mv "$TMPFILE" "$OUT_FILE"
	echo "Wrote JSON secret to $OUT_FILE"
	exit 0
fi

# Default: dotenv format
jq -r 'to_entries|map("\(.key)=\(.value|tostring)")|.[]' "$TMPFILE" > "$OUT_FILE"
echo "Wrote dotenv file to $OUT_FILE"
