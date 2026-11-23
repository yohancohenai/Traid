#!/usr/bin/env sh
# Nightly logical backup with 14-day retention. Used by the `backup` compose service.
set -eu
mkdir -p /backups
while true; do
  f="/backups/ttq_$(date -u +%Y%m%dT%H%M%SZ).sql.gz"
  pg_dump "$PGURL" | gzip > "$f" && echo "backup written: $f"
  find /backups -name 'ttq_*.sql.gz' -mtime +14 -delete
  sleep 86400
done
