#!/usr/bin/env bash
# TT Elite Quant Pro on an always-on Linux server (Oracle Cloud Always Free, Ubuntu 22.04/24.04, ARM or x86).
# Run on the server:  curl -fsSL <raw url> | bash   OR   bash oracle-setup.sh
# Re-running is safe: it keeps your .env, data and model.
set -euo pipefail
BRANCH="claude/tt-elite-quant-pro-6b6pj7"
REPO="github.com/yohancohenai/Traid.git"
DIR="$HOME/Traid"

say() { printf '\n==> %s\n' "$*"; }

if ! command -v docker >/dev/null 2>&1; then
  say "Installing Docker"
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER" || true
fi
DOCKER="docker"; docker info >/dev/null 2>&1 || DOCKER="sudo docker"

if [ "$(swapon --show | wc -l)" -eq 0 ]; then
  say "Adding 4 GB swap (safety net for model training)"
  sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

if [ ! -d "$DIR/.git" ]; then
  say "Downloading the app"
  command -v git >/dev/null || sudo apt-get install -y -q git >/dev/null
  if ! git clone -q -b "$BRANCH" "https://$REPO" "$DIR" 2>/dev/null; then
    echo "The repository is private. Create a read-only GitHub token (github.com -> Settings -> Developer settings ->"
    echo "Fine-grained tokens -> only the 'Traid' repo, Contents: Read-only) and paste it here (input hidden):"
    read -rs GHTOKEN </dev/tty
    git clone -q -b "$BRANCH" "https://x-access-token:${GHTOKEN}@$REPO" "$DIR"
    git -C "$DIR" remote set-url origin "https://x-access-token:${GHTOKEN}@$REPO"
  fi
fi
cd "$DIR/tt-elite-quant-pro"

if [ ! -f .env ]; then
  say "Creating settings (.env)"
  rnd() { openssl rand -hex "$1" | cut -c1-"$1"; }
  ADMIN_PW="$(rnd 20)"
  echo "Telegram bot token (from @BotFather; input hidden):"; read -rs TG_TOKEN </dev/tty
  echo "Telegram chat id (number, e.g. 6872310720):"; read -r TG_CHAT </dev/tty
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
TTQ_ENABLE_DEMO=false
TTQ_ENABLE_TTSERIES=true
TTQ_TELEGRAM_BOT_TOKEN=$TG_TOKEN
TTQ_TELEGRAM_CHAT_ID=$TG_CHAT
TTQ_API_PORT=8000
NEXT_PUBLIC_API_URL=
ENV
  chmod 600 .env
  printf '\n####  Web app login: admin / %s  (also in %s/.env)  ####\n' "$ADMIN_PW" "$PWD"
fi

say "Building and starting (first time ~10 min)"
$DOCKER compose up -d --build
$DOCKER image prune -f >/dev/null 2>&1 || true

say "Waiting for the API"
for _ in $(seq 1 60); do $DOCKER compose exec -T api python -c "import urllib.request;urllib.request.urlopen('http://localhost:8000/api/health')" >/dev/null 2>&1 && break; sleep 5; done

$DOCKER compose exec -T api python -m ttq.cli test-alert || true

if [ ! -f .ttq-initialized ]; then
  say "Downloading official TT Elite history and training the model (~35 min, in the background)"
  $DOCKER compose exec -d api sh -c "python -m ttq.cli backfill-ttseries --from-id 1 > /app/artifacts/first_run.log 2>&1 && python -m ttq.cli train-force --live >> /app/artifacts/first_run.log 2>&1 && python -m ttq.cli predict >> /app/artifacts/first_run.log 2>&1"
  touch .ttq-initialized
fi

say "Done. The bot now runs 24/7 on this server and restarts by itself after reboots."
echo "Check anytime:  cd $PWD && $DOCKER compose exec api python -m ttq.cli status"
