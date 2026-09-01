#!/usr/bin/env bash
# Print a free TCP port on stdout, starting from a preferred one (KAN-391 follow-up).
#
# WHY THIS EXISTS. `make dev` binds three ports — Postgres, uvicorn, Vite — and on a
# machine running more than one project the defaults (5432/8000/5173) are routinely
# held by something else. The failure was not a clean "port in use": Postgres refused
# a password (a FOREIGN Postgres answered), and a foreign :8000 let Vite proxy to an
# app that is not this one. Both look like application bugs, which is the expensive
# part. Picking a free port up front turns that class of confusion into one printed
# line.
#
# Usage:  free-port.sh PREFERRED [TRIES]
#   PREFERRED  the port to use if it is free (the project default)
#   TRIES      how many consecutive ports to try before giving up (default 200)
#
# Diagnostics go to stderr so the port alone is on stdout and `$(…)` stays clean.
set -euo pipefail

preferred="${1:?usage: free-port.sh PREFERRED [TRIES]}"
tries="${2:-200}"

case "$preferred" in
  ''|*[!0-9]*) echo "free-port.sh: PREFERRED must be a number, got '$preferred'" >&2; exit 2 ;;
esac

# A connect test rather than a listener table: it needs no `ss`/`netstat`/`lsof` (so
# it behaves the same on a Mac and in a slim container), and it asks the question we
# actually care about — would a client reaching this port find somebody already
# there. bash opens /dev/tcp itself; nothing is spawned.
port_in_use() {
  (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null || return 1
  exec 3<&- 3>&-
  return 0
}

port="$preferred"
end=$((preferred + tries))
while [ "$port" -lt "$end" ]; do
  # Stay inside the unprivileged range; a port past 65535 is not a port.
  if [ "$port" -gt 65535 ]; then break; fi
  if ! port_in_use "$port"; then
    if [ "$port" != "$preferred" ]; then
      echo "free-port.sh: :$preferred is taken, using :$port instead" >&2
    fi
    echo "$port"
    exit 0
  fi
  port=$((port + 1))
done

echo "free-port.sh: no free port in [$preferred, $end) — is something scanning?" >&2
exit 1
