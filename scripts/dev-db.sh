#!/usr/bin/env bash
# Bring up the local compose Postgres on a port that is actually free, and print its
# DATABASE_URL on stdout (KAN-391 follow-up).
#
# Three states, because the interesting one is the third:
#
#   1. DATABASE_URL already exported  -> honour it and do not touch Docker at all. A worktree
#      pointed at its own `make worktree-db` must not have a second DB started under it.
#   2. our db already running WITH a published port -> reuse it. Re-picking a port
#      would recreate the container and throw away the dev data in it.
#   3. our db running but publishing NOTHING -> recreate it. This is the state a
#      failed bind leaves behind, and it is the one that wastes an afternoon: the
#      container is "up", so every check says fine, but nothing on the host can reach
#      it, and a connection to :5432 lands on whatever foreign Postgres won the port
#      (which then fails as `password authentication failed for user "kanban"` — an
#      error that reads like a config bug and is not one).
#
# Diagnostics go to stderr; stdout is the URL alone so `$(…)` stays clean.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -n "${DATABASE_URL:-}" ]; then
  echo "dev-db.sh: DATABASE_URL is already set, using it as-is" >&2
  echo "$DATABASE_URL"
  exit 0
fi

running="$(docker compose ps -q db 2>/dev/null || true)"
published=""
if [ -n "$running" ]; then
  # `docker compose port` prints `0.0.0.0:5432`, or nothing when the service is up
  # without a host binding.
  published="$(docker compose port db 5432 2>/dev/null | tail -n1 | sed 's/.*://' || true)"
fi

if [ -n "$running" ] && [ -n "$published" ]; then
  port="$published"
  echo "dev-db.sh: reusing the running db on :$port" >&2
else
  if [ -n "$running" ]; then
    echo "dev-db.sh: db is up but publishes no host port — recreating it" >&2
    docker compose rm -sf db >/dev/null
  fi
  port="$(./scripts/free-port.sh "${DB_PORT:-5432}")"
  DB_PORT="$port" docker compose up -d db >/dev/null
  echo "dev-db.sh: started db on :$port" >&2
fi

printf 'dev-db.sh: waiting for postgres ' >&2
for _ in $(seq 1 60); do
  if docker compose exec -T db pg_isready -U kanban -d kanban >/dev/null 2>&1; then
    echo 'ready.' >&2
    echo "postgresql+psycopg://kanban:kanban@localhost:$port/kanban"
    exit 0
  fi
  printf '.' >&2
  sleep 1
done

echo '' >&2
echo "dev-db.sh: postgres on :$port never became ready — try 'docker compose logs db'" >&2
exit 1
