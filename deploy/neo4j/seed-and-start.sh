#!/usr/bin/env bash
# Seed Neo4j on first boot, then start it. Two sources, in priority order:
#
#   1. DISCOVERY_LOCAL_DUMP — a bind-mounted local .dump (see
#      docker-compose.seed-local.yml). Best for LOCAL testing: no upload/download.
#   2. DISCOVERY_GDRIVE_ID  — a Google Drive dump, pulled with gdown. For the VM.
#
# The dump loads into the DEFAULT `neo4j` database (always known to the DBMS, so no
# post-load `CREATE DATABASE` step is needed), which is why the app runs with
# NEO4J_DISCOVERY_DATABASE=neo4j. The image is Neo4j Enterprise (eval license)
# because the source graph uses the Enterprise-only block store format.
# `neo4j-admin database load` reads "<db>.dump" (i.e. neo4j.dump) from its
# --from-path, so the mount / download provides the file under that name. Loading
# is offline, so it runs before Neo4j starts; the /data sentinel makes restarts instant.
set -euo pipefail

SENTINEL=/data/.watchline-seeded
DUMP=/tmp/neo4j.dump

load_from_dir() {  # $1 = directory containing neo4j.dump
  echo "[seed] loading dump into the default 'neo4j' database (offline)"
  neo4j-admin database load neo4j --from-path="$1" --overwrite-destination=true
}

if [ -f "$SENTINEL" ]; then
  echo "[seed] already seeded (found $SENTINEL) — starting Neo4j"
elif [ -n "${DISCOVERY_LOCAL_DUMP:-}" ] && [ -f "${DISCOVERY_LOCAL_DUMP}" ]; then
  echo "[seed] using local dump ${DISCOVERY_LOCAL_DUMP}"
  load_from_dir "$(dirname "${DISCOVERY_LOCAL_DUMP}")"
  touch "$SENTINEL"
  echo "[seed] done"
elif [ -n "${DISCOVERY_GDRIVE_ID:-}" ]; then
  echo "[seed] downloading dump from Google Drive (${DISCOVERY_GDRIVE_ID})"
  # Accept either a bare file id or a full share URL (…/file/d/<id>/view…).
  case "$DISCOVERY_GDRIVE_ID" in
    *drive.google.com*|*://*) gdown --fuzzy "$DISCOVERY_GDRIVE_ID" -O "$DUMP" ;;
    *)                        gdown "$DISCOVERY_GDRIVE_ID" -O "$DUMP" ;;
  esac
  load_from_dir /tmp
  rm -f "$DUMP"
  touch "$SENTINEL"
  echo "[seed] done"
else
  echo "[seed] no DISCOVERY_LOCAL_DUMP or DISCOVERY_GDRIVE_ID — starting Neo4j with whatever is on /data"
fi

# Hand off to the stock Neo4j entrypoint (starts the server in the foreground).
exec /startup/docker-entrypoint.sh neo4j
