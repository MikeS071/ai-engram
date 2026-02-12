#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env.social-scheduler" ]]; then
  set -a
  source .env.social-scheduler
  set +a
fi

LISTEN="${1:-127.0.0.1}"
PORT="${2:-8080}"
URL_PATH="${3:-/telegram}"
WEBHOOK_URL="${4:-}"

exec ./.venv/bin/python -m social_scheduler.main telegram-webhook \
  --listen "$LISTEN" \
  --port "$PORT" \
  --url-path "$URL_PATH" \
  --webhook-url "$WEBHOOK_URL"
