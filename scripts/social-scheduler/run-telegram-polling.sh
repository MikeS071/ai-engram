#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env.social-scheduler" ]]; then
  set -a
  source .env.social-scheduler
  set +a
fi

exec ./.venv/bin/python -m social_scheduler.main telegram-run
