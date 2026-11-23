#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PGBIN="${PGBIN:-$HOME/Applications/Postgres.app/Contents/Versions/19/bin}"
"$PGBIN/pg_ctl" -D "$ROOT/.pgdata" stop || true
