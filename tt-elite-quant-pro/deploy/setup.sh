#!/usr/bin/env bash
# One-time server setup for TT Elite Quant Pro on Ubuntu 22.04/24.04.
# Usage (as root, from the tt-elite-quant-pro folder):  ./deploy/setup.sh tt.yourdomain.com
set -euo pipefail
DOMAIN="${1:?usage: ./deploy/setup.sh tt.yourdomain.com}"
cd "$(dirname "$0")/.."
COMPOSE="docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml"

echo "==> Checking DNS for $DOMAIN"
MYIP=$(curl -fsS https://api.ipify.org || true)
DNSIP=$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1 || true)
if [ -n "$MYIP" ] && [ "$MYIP" != "$DNSIP" ]; then
  echo "WARNING: $DOMAIN resolves to '${DNSIP:-nothing}', this server is $MYIP."
  echo "Create an A record $DOMAIN -> $MYIP, wait a few minutes, then re-run. (HTTPS certificates need it.)"
  exit 1
fi

if ! command -v docker >/dev/null; then
  echo "==> Installing Docker"
  curl -fsSL https://get.docker.com | sh
fi

echo "==> Firewall: allow SSH, HTTP, HTTPS only"
if command -v ufw >/dev/null; then
  ufw allow OpenSSH >/dev/null; ufw allow 80/tcp >/dev/null; ufw allow 443/tcp >/dev/null
  ufw --force enable >/dev/null
fi

if [ ! -f .env ]; then
  echo "==> Generating secrets into .env"
  rnd() { openssl rand -base64 48 | tr -dc 'A-Za-z0-9' | head -c "$1"; }
  ADMIN_PW=$(rnd 20)
  cp .env.example .env
  sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rnd 32)|" .env
  sed -i "s|^TTQ_JWT_SECRET=.*|TTQ_JWT_SECRET=$(rnd 64)|" .env
  sed -i "s|^TTQ_ENV=.*|TTQ_ENV=production|" .env
  sed -i "s|^TTQ_CORS_ORIGINS=.*|TTQ_CORS_ORIGINS=https://$DOMAIN|" .env
  sed -i "s|^NEXT_PUBLIC_API_URL=.*|NEXT_PUBLIC_API_URL=|" .env   # same-origin /api via the frontend proxy
  echo "TTQ_DOMAIN=$DOMAIN" >> .env
  chmod 600 .env
  echo "==> Building images"
  $COMPOSE build
  HASH=$($COMPOSE run --rm --no-deps -T api python -m ttq.cli hash-password --password "$ADMIN_PW" | tail -1)
  sed -i "s|^TTQ_ADMIN_PASSWORD_HASH=.*|TTQ_ADMIN_PASSWORD_HASH='$HASH'|" .env  # single quotes: Compose must not expand the $ in bcrypt hashes
  sed -i "s|^TTQ_ADMIN_PASSWORD=.*|TTQ_ADMIN_PASSWORD=|" .env
  echo
  echo "############################################################"
  echo "  Login:    admin"
  echo "  Password: $ADMIN_PW"
  echo "  Save this now; it is not stored anywhere in plain text."
  echo "############################################################"
  echo
fi

echo "==> Starting the stack"
$COMPOSE up -d --build
echo "==> Waiting for the API"
for i in $(seq 1 60); do
  if curl -fsS "https://$DOMAIN/api/health" >/dev/null 2>&1; then break; fi
  sleep 5
done
curl -fsS "https://$DOMAIN/api/health" && echo && echo "Done: open https://$DOMAIN"
echo "Optional DEMO data:  $COMPOSE exec api python -m ttq.cli seed-demo"
