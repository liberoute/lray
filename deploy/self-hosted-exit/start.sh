#!/bin/bash
# lray Self-Hosted Exit Node — Deploy Script
#
# Usage:
#   ./start.sh          — Start
#   ./start.sh stop     — Stop
#   ./start.sh restart  — Restart
#   ./start.sh status   — Show status
#   ./start.sh logs     — Follow logs

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ─── Auto-update from update.zip ──────────────────────────────────────────────

if [ -f "update.zip" ]; then
    echo "📦 update.zip found — applying update..."
    unzip -o update.zip -d . 2>/dev/null || {
        echo "❌ Failed to extract (install unzip: apt install unzip)"
        exit 1
    }
    rm -f update.zip
    echo "✓  Update applied."
    chmod +x start.sh
    exec ./start.sh "$@"
fi

# ─── Load .env ────────────────────────────────────────────────────────────────

if [ ! -f .env ]; then
    echo "❌ .env not found!"
    exit 1
fi

while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    key=$(echo "$key" | xargs)
    export "$key=$value"
done < .env

# ─── Commands ─────────────────────────────────────────────────────────────────

ACTION="${1:-start}"

case "$ACTION" in
    stop)
        docker compose down
        echo "✓ Stopped."
        exit 0
        ;;
    restart)
        docker compose down
        exec "$0" start
        ;;
    status)
        docker compose ps
        exit 0
        ;;
    logs)
        docker compose logs -f --tail=100
        exit 0
        ;;
    start)
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        exit 1
        ;;
esac

# ─── Validation ───────────────────────────────────────────────────────────────

if [ "${#AUTH_KEY}" -lt 32 ]; then
    echo "❌ AUTH_KEY too short (min 32 chars)"
    exit 1
fi

# ─── Start ────────────────────────────────────────────────────────────────────

echo "🚀 Starting self-hosted exit node..."
echo "   Domain: ${DOMAIN:-localhost}"
echo "   Port: ${PORT:-3000}"
echo "   Auth: ${AUTH_KEY:0:8}..."

# Remove old containers to avoid name conflicts
docker compose down --remove-orphans 2>/dev/null || true
docker rm -f exit-node 2>/dev/null || true
docker compose up -d --build

# Detect protocol
if [ -n "$SSL_CERT_FILE" ] && [ -f "$SSL_CERT_FILE" ]; then
    PROTO="https"
else
    PROTO="http"
fi

echo ""
echo "✓ Running!"
echo "   Exit URL:   ${PROTO}://${DOMAIN:-localhost}:${PORT:-3000}"
echo "   Health:     ${PROTO}://${DOMAIN:-localhost}:${PORT:-3000}/health"
echo "   Stats:      ${PROTO}://${DOMAIN:-localhost}:${PORT:-3000}/stats"
echo "   Dashboard:  ${PROTO}://${DOMAIN:-localhost}:${PORT:-3000}/dashboard"
echo ""
