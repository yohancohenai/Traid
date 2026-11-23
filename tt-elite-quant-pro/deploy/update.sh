#!/usr/bin/env bash
# Update the server copy to the latest version. Keeps .env, data and model.
set -euo pipefail
cd "$(dirname "$0")/.."
DOCKER="docker"; docker info >/dev/null 2>&1 || DOCKER="sudo docker"
git pull -q
$DOCKER compose up -d --build
$DOCKER image prune -f >/dev/null 2>&1 || true
sleep 60
$DOCKER compose exec -T api python -m ttq.cli status
