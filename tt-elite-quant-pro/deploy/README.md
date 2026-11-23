# Deploying TT Elite Quant Pro (VPS + your domain)

## Buy
* **VPS:** Hetzner Cloud CX22 (2 vCPU, 4 GB RAM, Ubuntu 24.04), about €5/month. A DigitalOcean 4 GB droplet also works.
  4 GB RAM matters: model training needs about 2 GB.
* **Domain:** use one you own. Add a DNS **A record**: `tt` → the VPS IPv4 address.

## Install (about 15 minutes)
```bash
ssh root@YOUR_SERVER_IP
apt-get update && apt-get install -y git
git clone -b claude/tt-elite-quant-pro-6b6pj7 https://github.com/yohancohenai/Traid.git
cd Traid/tt-elite-quant-pro
./deploy/setup.sh tt.yourdomain.com
```
The script checks DNS, installs Docker and enables the firewall (22/80/443 only). It writes `.env` with random secrets
and prints your **admin password once**, then starts everything with automatic HTTPS (Caddy + Let's Encrypt).

## Day-to-day
```bash
cd ~/Traid/tt-elite-quant-pro
C="docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml"
$C ps                                  # status
$C logs -f worker                      # scheduler logs
git pull && $C up -d --build           # update (migrations run automatically)
$C exec api pytest -q                  # run the backend test suite on the server
```

## Backups and restore
Daily compressed dumps go to `./backups/` and are kept for 14 days. Copy them off the server now and then
(`scp root@IP:~/Traid/tt-elite-quant-pro/backups/* .`).
Restore: `gunzip -c backups/<file>.sql.gz | $C exec -T db psql -U ttq ttq`

## Security notes
* Only Caddy is public. The API and frontend listen on 127.0.0.1 and inside the Docker network.
* Change the admin password: `$C run --rm api python -m ttq.cli hash-password --password 'NEW'`, put the hash in
  `.env` as `TTQ_ADMIN_PASSWORD_HASH`, then `$C up -d`.
* Never commit `.env`.

## First real data (run once after setup)
```bash
$C exec api python -m ttq.cli backfill-ttseries --from-id 1   # ~35 min, polite 1 request / 5 s
$C exec api python -m ttq.cli train-force --live              # first real model
$C exec api python -m ttq.cli predict                         # predictions for the next 48 h
```
After that the worker keeps results, predictions and retraining up to date automatically.
