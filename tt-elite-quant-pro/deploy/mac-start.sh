#!/usr/bin/env bash
# TT Elite Quant Pro on your Mac, $0. Run from the tt-elite-quant-pro folder:  ./deploy/mac-start.sh
#   TTQ_LAN=1 ./deploy/mac-start.sh   -> also reachable from your phone on the same Wi-Fi
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker Desktop is not installed. Get it free from https://www.docker.com/products/docker-desktop/ then re-run."
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Starting Docker Desktop…"
  open -a Docker 2>/dev/null || true
  for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 3; done
  docker info >/dev/null 2>&1 || { echo "Docker Desktop did not start. Open it manually, then re-run."; exit 1; }
fi

FIRST_RUN=0
if [ ! -f .env ]; then
  FIRST_RUN=1
  rnd() { openssl rand -hex "$1" | cut -c1-"$1"; }  # openssl ships with macOS
  ADMIN_PW="$(rnd 16)"
  cat > .env <<ENV
POSTGRES_USER=ttq
POSTGRES_PASSWORD=$(rnd 32)
POSTGRES_DB=ttq
TTQ_ENV=production
TTQ_ADMIN_USERNAME=admin
TTQ_ADMIN_PASSWORD=$ADMIN_PW
TTQ_JWT_SECRET=$(rnd 64)
TTQ_CORS_ORIGINS=http://localhost:3000
TTQ_USER_TIMEZONE=America/New_York
TTQ_USER_REGION=US-FL
TTQ_MAX_QUOTE_AGE_SECONDS=600
TTQ_ENABLE_DEMO=false
TTQ_ENABLE_TTSERIES=true
TTQ_TTSERIES_MIN_INTERVAL_SECONDS=5
NEXT_PUBLIC_API_URL=
ENV
  chmod 600 .env
  echo
  echo "############################################################"
  echo "  Login:    admin"
  echo "  Password: $ADMIN_PW"
  echo "  (stored in .env on this Mac only; change it there anytime)"
  echo "############################################################"
  echo
fi

if [ "${TTQ_LAN:-0}" = "1" ]; then export TTQ_BIND=0.0.0.0; else export TTQ_BIND=127.0.0.1; fi

# Pick free host ports: other apps on the Mac often use 8000 (the API port is only for debugging anyway).
port_busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
running_here() { docker compose ps --status running --services 2>/dev/null | grep -qx "$1"; }
if [ -z "${TTQ_API_PORT:-}" ]; then
  TTQ_API_PORT=8000
  if port_busy 8000 && ! running_here api; then
    for p in 8011 8021 8031 8041; do port_busy "$p" || { TTQ_API_PORT=$p; break; }; done
  fi
  export TTQ_API_PORT
fi
if port_busy 3000 && ! running_here frontend; then
  echo "Port 3000 is used by another program. Close it (see: lsof -nP -iTCP:3000 -sTCP:LISTEN) and re-run."
  exit 1
fi

echo "Building and starting (first time takes ~5–10 minutes)…"
docker compose build api   # build the backend once (api and worker share it)
docker compose up -d --build
# Drop superseded image versions and build cache so repeated updates don't fill Docker's disk (data volumes are untouched).
docker image prune -f >/dev/null 2>&1 || true
docker builder prune -f --filter until=24h >/dev/null 2>&1 || true

echo "Waiting for the API…"
for _ in $(seq 1 60); do
  docker compose exec -T api python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health')" >/dev/null 2>&1 && break
  sleep 5
done

if [ "$FIRST_RUN" = "1" ] || [ ! -f .ttq-initialized ]; then
  echo "First run: downloading official TT Elite history (~35 min, polite pace) and training the first model in the background."
  docker compose exec -d api sh -c "python -m ttq.cli backfill-ttseries --from-id 1 > /app/artifacts/first_run.log 2>&1 && python -m ttq.cli train-force --live >> /app/artifacts/first_run.log 2>&1 && python -m ttq.cli predict >> /app/artifacts/first_run.log 2>&1"
  touch .ttq-initialized
  echo "Progress: docker compose exec api tail -f /app/artifacts/first_run.log"
fi

echo
echo "Open: http://localhost:3000"
if [ "${TTQ_LAN:-0}" = "1" ]; then
  echo "Phone (same Wi-Fi): http://$(scutil --get LocalHostName 2>/dev/null || hostname -s).local:3000"
fi
open "http://localhost:3000" 2>/dev/null || true
