#!/usr/bin/env bash
# Start the local PostgreSQL 19 server bundled with Postgres.app.
# The data directory lives inside the project so the demo is self-contained.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PGBIN="${PGBIN:-$HOME/Applications/Postgres.app/Contents/Versions/19/bin}"
PGDATA="$ROOT/.pgdata"
PGLOG="$ROOT/.pglog"
PORT="${PGPORT:-5433}"

if [ ! -x "$PGBIN/pg_ctl" ]; then
  echo "PostgreSQL binaries not found at $PGBIN" >&2
  echo "Install Postgres.app (free) or set PGBIN to a PostgreSQL bin directory." >&2
  exit 1
fi

mkdir -p "$PGLOG"

if [ ! -f "$PGDATA/PG_VERSION" ]; then
  echo "Initialising PostgreSQL data directory at $PGDATA"
  "$PGBIN/initdb" -D "$PGDATA" -U "$(whoami)" --auth=trust --encoding=UTF8 --locale=C
fi

if "$PGBIN/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; then
  echo "PostgreSQL is already running on port $PORT."
else
  "$PGBIN/pg_ctl" -D "$PGDATA" -l "$PGLOG/postgres.log" \
    -o "-p $PORT -k $PGDATA" start
fi

# Create the database if it does not exist yet.
if ! "$PGBIN/psql" -h localhost -p "$PORT" -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='product_search'" | grep -q 1; then
  "$PGBIN/createdb" -h localhost -p "$PORT" product_search
fi

echo "PostgreSQL ready: postgresql://localhost:$PORT/product_search"
