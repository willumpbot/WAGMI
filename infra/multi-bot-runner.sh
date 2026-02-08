#!/usr/bin/env bash
# multi-bot-runner.sh - start bot containers for each strategy listed in infra/ci/strategies.json
# Usage: ./multi-bot-runner.sh [--dry-run]

set -euo pipefail
DRY=0
SECRETS_FILE=infra/bot-secrets.json
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=1 ;;
    --secrets=*) SECRETS_FILE="${arg#--secrets=}" ;;
  esac
done
if [ "$DRY" -eq 1 ]; then
  echo "Dry run: will print docker compose override"
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "Please install jq to run this script" >&2
  exit 2
fi

STRATS_FILE=infra/ci/strategies.json
if [ ! -f "$STRATS_FILE" ]; then
  echo "Missing $STRATS_FILE" >&2
  exit 1
fi

# Build a temporary compose override with service entries for each strategy
TMP_OVERRIDE=$(mktemp)
cat > "$TMP_OVERRIDE" <<'YAML'
version: '3.8'
services:
YAML

i=0
jq -r '.[]' "$STRATS_FILE" | while read -r strat; do
  i=$((i+1))
  name="bot_${i}"
  # try to read per-bot secrets from secrets file
  bot_symbol="BTC-PERP"
  bot_key_env="${NUNUIRL_API_KEY:-}"
  if [ -f "$SECRETS_FILE" ]; then
    s_sym=$(jq -r --arg k "$strat" '.[$k].SYMBOL // empty' "$SECRETS_FILE" 2>/dev/null || true)
    s_key=$(jq -r --arg k "$strat" '.[$k].NUNUIRL_API_KEY // empty' "$SECRETS_FILE" 2>/dev/null || true)
    if [ -n "$s_sym" ]; then bot_symbol="$s_sym"; fi
    if [ -n "$s_key" ]; then bot_key_env="$s_key"; fi
  fi

  cat >> "$TMP_OVERRIDE" <<YAML
  $name:
    build:
      context: ../bot
    container_name: nunuirl_bot_$i
    environment:
      - BASE_URL=http://api:8000
      - STRATEGY_ID=$strat
      - SYMBOL=$bot_symbol
      - NUNUIRL_API_KEY=$bot_key_env
      - SNAPSHOT_INTERVAL_SEC=30
    depends_on:
      - api
    restart: unless-stopped

YAML
  echo "Added $name -> strategy $strat"
done

if [ "$DRY" = "--dry-run" ]; then
  cat "$TMP_OVERRIDE"
  #!/usr/bin/env bash
  set -euo pipefail
  SECRETS="infra/bot-secrets.json"
  DRY=0
  STRICT=0
  OUT="infra/docker-compose.bots.yml"

  for arg in "$@"; do
    case "$arg" in
      --secrets=*) SECRETS="${arg#--secrets=}" ;;
      --dry-run) DRY=1 ;;
      --strict) STRICT=1 ;;
      --out=*) OUT="${arg#--out=}" ;;
    esac
  done

  if ! command -v jq >/dev/null 2>&1; then
    echo "jq not found; install jq first" >&2; exit 2
  fi
  if [ ! -f "$SECRETS" ]; then
    echo "Secrets file not found: $SECRETS" >&2; exit 2
  fi

  # Resolve ${ENV} placeholders (simple form ${VAR})
  # Expand any ${VAR} placeholders contained anywhere in the string
  resolve() {
    local v="$1"
    local re='\$\{([A-Za-z_][A-Za-z0-9_]*)\}'
    # loop while a placeholder remains
    while [[ $v =~ $re ]]; do
      local full="${BASH_REMATCH[0]}"
      local key="${BASH_REMATCH[1]}"
      local val="${!key:-}"
      # replace all occurrences of the exact placeholder
      v="${v//${full}/${val}}"
    done
    printf '%s' "$v"
  }

  # Build services YAML block
  SERVICES=$(jq -r 'to_entries[] | [.key, (.value.NUNUIRL_API_KEY // ""), (.value.SYMBOL // "")] | @tsv' "$SECRETS")
  YAML="services:\n"
  MISSING=0

  while IFS=$'\t' read -r STRAT RAW_KEY RAW_SYM; do
    [ -z "$STRAT" ] && continue
    KEY=$(resolve "$RAW_KEY")
    SYM=$(resolve "$RAW_SYM")

    # fallback per-bot -> env -> global NUNUIRL_API_KEY
    if [ -z "$KEY" ]; then
      KEY="${NUNUIRL_API_KEY:-}"
    fi
    if [ -z "$KEY" ]; then
      echo "WARN: missing NUNUIRL_API_KEY for strategy=$STRAT" >&2
      MISSING=1
      if [ "$STRICT" -eq 1 ]; then
        echo "STRICT mode: aborting due to missing secret for $STRAT" >&2
        exit 10
      fi
      continue
    fi
    if [ -z "$SYM" ]; then
      echo "WARN: missing SYMBOL override for strategy=$STRAT; using default if runner env supplies it" >&2
      SYM="${SYMBOL:-}"
    fi

    # sanitize service name
    SVC="bot-${STRAT//[^a-zA-Z0-9]/-}"
    YAML+=$(cat <<EOF
    $SVC:
      build:
        context: ../bot
      environment:
        - BASE_URL=http://api:8000
        - STRATEGY_ID=${STRAT}
        - SYMBOL=${SYM}
        - NUNUIRL_API_KEY=${KEY}
        - SNAPSHOT_INTERVAL_SEC=30
      depends_on:
        - api
      restart: unless-stopped

  EOF
  )
  done <<< "$SERVICES"

  if [ "$MISSING" -eq 1 ] && [ "$STRICT" -eq 1 ]; then
    exit 10
  fi

  echo -e "$YAML" > "$OUT"
  echo "Wrote $OUT"
  if [ "$DRY" -eq 0 ]; then
    docker compose -f infra/docker-compose.yml -f "$OUT" up -d --build
  else
    echo "(dry-run) Not starting containers"
  fi
