#!/bin/bash
# lray Upstream Forwarder — Deploy Script
#
# Usage:
#   ./start.sh          — Start
#   ./start.sh stop     — Stop
#   ./start.sh restart  — Restart
#   ./start.sh status   — Show status
#   ./start.sh logs     — Follow logs
#   ./start.sh build    — Rebuild image

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
    build)
        docker compose build --no-cache
        echo "✓ Built."
        exit 0
        ;;
    start)
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs|build}"
        exit 1
        ;;
esac

# ─── Validation ───────────────────────────────────────────────────────────────

if [ "${#AUTH_KEY}" -lt 32 ]; then
    echo "❌ AUTH_KEY too short (min 32 chars)"
    exit 1
fi

# ─── Start ────────────────────────────────────────────────────────────────────

PROTO="http"
if [ -n "$SSL_CERT_FILE" ] && [ -f "$SSL_CERT_FILE" ]; then
    PROTO="https"
fi

echo "🚀 Starting upstream forwarder..."
echo "   Domain: ${DOMAIN:-localhost}"
echo "   Port: ${PORT:-8787} ($PROTO)"
if [ "$PROTOCOL_MODE" = "both" ]; then
    echo "   HTTP: ${HTTP_PORT:-80}"
fi
echo "   Auth: ${AUTH_KEY:0:8}..."

# Remove old containers to avoid name conflicts
docker compose down --remove-orphans 2>/dev/null || true
docker compose up -d --build

echo ""
echo "✓ Running!"
echo "   ${PROTO}://${DOMAIN:-localhost}:${PORT:-8787}"
if [ "$PROTOCOL_MODE" = "both" ]; then
    echo "   http://${DOMAIN:-localhost}:${HTTP_PORT:-80}"
fi
echo "   Health:    /health"
echo "   Stats:     /stats"
echo "   Dashboard: /dashboard"
echo ""
