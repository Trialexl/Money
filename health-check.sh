#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env"
  set +a
fi

HEALTH_URL="${HEALTH_URL:-https://${APP_DOMAIN:-localhost}/api/v1/health/}"
ALERT_WEBHOOK_URL="${ALERT_WEBHOOK_URL:-}"
LOG_FILE="${LOG_FILE:-/tmp/money-health-check.log}"

notify() {
  local message="$1"
  if [[ -n "$ALERT_WEBHOOK_URL" ]]; then
    curl -fsS \
      -H "Content-Type: application/json" \
      -d "{\"text\":\"${message//\"/\\\"}\"}" \
      "$ALERT_WEBHOOK_URL" >/dev/null || true
  fi
}

timestamp="$(date -Iseconds)"
if curl -fsS "$HEALTH_URL" >/dev/null; then
  printf '%s OK %s\n' "$timestamp" "$HEALTH_URL" >>"$LOG_FILE"
  exit 0
fi

message="Money healthcheck failed: $HEALTH_URL"
printf '%s FAIL %s\n' "$timestamp" "$HEALTH_URL" >>"$LOG_FILE"
notify "$message"
exit 1
