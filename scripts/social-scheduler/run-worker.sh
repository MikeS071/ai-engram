#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ -f ".env.social-scheduler" ]]; then
  set -a
  source .env.social-scheduler
  set +a
fi

INTERVAL="${1:-60}"
DRY_RUN="${2:-true}"

exec ./.venv/bin/python -m social_scheduler.main worker-daemon --interval-seconds "$INTERVAL" --dry-run "$DRY_RUN"
