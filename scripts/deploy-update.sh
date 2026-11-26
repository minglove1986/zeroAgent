#!/usr/bin/env bash
# zeroAgent one-click deploy update: rebuild + restart API(:8000) / admin-web(:3001) / web(:3000).
# Preserves base services mysql/redis/rabbitmq/litellm; does NOT touch DB.
#
# Usage:
#   ./scripts/deploy-update.sh                   Full rebuild + restart all 5 services
#   ./scripts/deploy-update.sh --skip-api       Frontends only
#   ./scripts/deploy-update.sh --skip-frontends API only
#   ./scripts/deploy-update.sh --no-build       Use existing images (rollback)
#   ./scripts/deploy-update.sh --no-backup      Skip image backup
#
# @author 赵振明
# @date 2026-08-07

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_DIR="$REPO_ROOT/deploy"
COMPOSE_FILE="$COMPOSE_DIR/docker-compose.yml"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

API_PORT=8000
WEB_PORT=3000
ADMIN_PORT=3001

# Service names (docker compose service)
SVC_API=api
SVC_WORKER=worker
SVC_BEAT=beat
SVC_WEB=web
SVC_ADMIN=admin_web

BUILD_TARGETS=("$SVC_API" "$SVC_WEB" "$SVC_ADMIN")
RESTART_SEQUENCE=("$SVC_BEAT" "$SVC_WORKER" "$SVC_API" "$SVC_ADMIN" "$SVC_WEB")

# ---------- Args ----------
SKIP_API=0
SKIP_FRONTENDS=0
NO_BUILD=0
NO_BACKUP=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --skip-api)        SKIP_API=1; shift ;;
        --skip-frontends)  SKIP_FRONTENDS=1; shift ;;
        --no-build)        NO_BUILD=1; shift ;;
        --no-backup)       NO_BACKUP=1; shift ;;
        -h|--help)
            echo "Usage: deploy-update.sh [--skip-api] [--skip-frontends] [--no-build] [--no-backup]"
            exit 1
            ;;
        *)
            echo "[deploy-update][ERROR] Unknown arg: $1" >&2
            exit 2
            ;;
    esac
done

if [[ "$SKIP_API" == "1" && "$SKIP_FRONTENDS" == "1" ]]; then
    echo "[deploy-update][ERROR] --skip-api and --skip-frontends cannot both be set" >&2
    exit 2
fi

log()  { echo "[deploy-update] $1"; }
err()  { echo "[deploy-update][ERROR] $1" >&2; exit 1; }
warn() { echo "[deploy-update][WARN] $1" >&2; }

# ---------- Pre-check ----------
command -v docker >/dev/null 2>&1 || err "docker not found"
docker compose version >/dev/null 2>&1 || err "docker compose not available"
[[ -f "$COMPOSE_FILE" ]] || err "docker-compose.yml not found: $COMPOSE_FILE"

log "Repo: $REPO_ROOT"
log "Timestamp: $TIMESTAMP"

# ---------- Base services ----------
log "Pre-check: base services (mysql / redis / rabbitmq)"
PS_OUTPUT=$(docker compose -f "$COMPOSE_FILE" ps 2>/dev/null || true)
RUNNING=""
for name in zeroagent-mysql zeroagent-redis zeroagent-rabbitmq; do
    if echo "$PS_OUTPUT" | grep -q "$name"; then
        RUNNING="$RUNNING $name"
    fi
done
if [[ -z "$RUNNING" ]]; then
    err "Base services not running. Start: cd deploy && docker compose up -d mysql redis rabbitmq"
fi
log "Base services OK:$RUNNING"

# ---------- Helpers ----------
docker_compose() {
    # Run docker compose in COMPOSE_DIR; swallow stderr (Chinese docker output trips bash).
    (cd "$COMPOSE_DIR" && docker compose "$@" >/dev/null 2>&1)
}

wait_port() {
    local port=$1 name=$2
    log "Waiting $name :$port ..."
    for _ in $(seq 1 90); do
        if (echo >/dev/tcp/127.0.0.1/$port) 2>/dev/null; then
            log "$name :$port ready"
            return 0
        fi
        sleep 1
    done
    err "$name :$port not listening after 90s"
}

wait_api_health() {
    log "Waiting API /health ..."
    for _ in $(seq 1 60); do
        code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$API_PORT/health" 2>/dev/null || echo 000)
        if [[ "$code" =~ ^2 ]]; then
            log "API /health OK (HTTP $code)"
            return 0
        fi
        if [[ "$code" =~ ^4 ]]; then
            log "API /health responded (HTTP $code)"
            return 0
        fi
        sleep 2
    done
    err "API /health did not pass within 120s"
}

restart_service() {
    local svc=$1
    log "Stopping: $svc"
    docker_compose stop "$svc" || warn "stop failed: $svc"
    log "Starting: $svc"
    docker_compose up -d --no-deps "$svc" || err "start failed: $svc"
}

backup_image() {
    local svc=$1
    local img="zeroagent-${svc}"
    local bak="${img}:backup-${TIMESTAMP}"
    if docker tag "$img" "$bak" 2>/dev/null; then
        log "Backup: $img -> $bak"
    else
        warn "Backup skipped: $img (image may not exist)"
    fi
}

# ---------- Backup ----------
if [[ "$NO_BACKUP" != "1" ]]; then
    log "Backing up current images ..."
    [[ "$SKIP_API" != "1" ]] && backup_image "$SVC_API"
    if [[ "$SKIP_FRONTENDS" != "1" ]]; then
        backup_image "$SVC_WEB"
        backup_image "$SVC_ADMIN"
    fi
else
    log "NoBackup specified, skipping backup"
fi

# ---------- Build ----------
if [[ "$NO_BUILD" != "1" ]]; then
    log "Building images ..."
    if [[ "$SKIP_API" != "1" ]]; then
        log "Building image: $SVC_API"
        docker_compose build "$SVC_API" || err "build failed: $SVC_API"
    fi
    if [[ "$SKIP_FRONTENDS" != "1" ]]; then
        log "Building image: $SVC_WEB"
        docker_compose build "$SVC_WEB" || err "build failed: $SVC_WEB"
        log "Building image: $SVC_ADMIN"
        docker_compose build "$SVC_ADMIN" || err "build failed: $SVC_ADMIN"
    fi
else
    log "NoBuild specified, skipping build"
fi

# ---------- Rolling restart ----------
log "Rolling restart ..."

for svc in "${RESTART_SEQUENCE[@]}"; do
    case "$svc" in
        "$SVC_BEAT"|"$SVC_WORKER"|"$SVC_API")
            [[ "$SKIP_API" == "1" ]] && continue ;;
        "$SVC_ADMIN"|"$SVC_WEB")
            [[ "$SKIP_FRONTENDS" == "1" ]] && continue ;;
    esac
    restart_service "$svc"
done

# ---------- Health ----------
if [[ "$SKIP_API" != "1" ]]; then
    wait_api_health
fi
if [[ "$SKIP_FRONTENDS" != "1" ]]; then
    wait_port "$WEB_PORT" "Web"
    wait_port "$ADMIN_PORT" "Admin"
fi

# ---------- Summary ----------
cat <<EOF

========================================
  Deploy update complete @ $TIMESTAMP
========================================

  Test endpoints:
    API      : http://127.0.0.1:$API_PORT/health
    Admin    : http://127.0.0.1:$ADMIN_PORT
    Web      : http://127.0.0.1:$WEB_PORT

  demo account: username=demo / password=demo1234 (platform_admin)
  super admin: username=root / password=demo1234 (super_admin; local seed)

  Rollback hint (if needed):
EOF

if [[ "$SKIP_API" != "1" ]]; then
    cat <<EOF
    docker compose -f "$COMPOSE_FILE" stop $SVC_API $SVC_WORKER $SVC_BEAT
    docker tag zeroagent-$SVC_API:backup-$TIMESTAMP zeroagent-$SVC_API:latest
    docker compose -f "$COMPOSE_FILE" up -d --no-deps $SVC_API $SVC_WORKER $SVC_BEAT
EOF
fi
if [[ "$SKIP_FRONTENDS" != "1" ]]; then
    cat <<EOF
    docker compose -f "$COMPOSE_FILE" stop $SVC_WEB $SVC_ADMIN
    docker tag zeroagent-$SVC_WEB:backup-$TIMESTAMP zeroagent-$SVC_WEB:latest
    docker tag zeroagent-$SVC_ADMIN:backup-$TIMESTAMP zeroagent-$SVC_ADMIN:latest
    docker compose -f "$COMPOSE_FILE" up -d --no-deps $SVC_WEB $SVC_ADMIN
EOF
fi

cat <<EOF
  Logs: cd deploy && docker compose logs -f --tail=200 <service>
EOF