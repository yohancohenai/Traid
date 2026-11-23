#!/usr/bin/env bash
# DANGER: drops every table in TTQ_DATABASE_URL and recreates the schema. Development only.
set -euo pipefail
cd "$(dirname "$0")/.."
alembic downgrade base
alembic upgrade head
