#!/usr/bin/env bash
set -euo pipefail

# lray installer — downloads and installs the Go binary
# Usage: curl -fsSL https://raw.githubusercontent.com/liberoute/lray/main/install.sh | bash

APP_NAME="lray"
REPO="liberoute/lray"
INSTALL_DIR="/usr/local/bin"
CONFIG_DIR="/etc/lray"
CA_DIR="/etc/lray/ca"
LOG_DIR="/var/log/lray"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# Detect OS and architecture
detect_platform() {
    local os arch
    os="$(uname -s | tr '[:upper:]' '[:lower:]')"
    arch="$(uname -m)"

    case "$os" in
        linux)  os="linux" ;;
        darwin) os="darwin" ;;
        *)      error "Unsupported OS: $os"; exit 1 ;;
    esac

    case "$arch" in
        x86_64|amd64)   arch="amd64" ;;
        aarch64|arm64)  arch="arm64" ;;
        *)              error "Unsupported architecture: $arch"; exit 1 ;;
    esac

    echo "${os}-${arch}"
}

# Get latest release version from GitHub
get_latest_version() {
    curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest" \
        | grep '"tag_name"' \
        | sed -E 's/.*"v?([^"]+)".*/\1/'
}

# Download and install binary
install_binary() {
    local platform="$1"
    local version="$2"
    local url="https://github.com/${REPO}/releases/download/v${version}/${APP_NAME}-${platform}"
    local tmp

    info "Downloading ${APP_NAME} v${version} for ${platform}..."
    tmp="$(mktemp)"
    
    if ! curl -fsSL -o "$tmp" "$url"; then
        # Try with .tar.gz
        url="${url}.tar.gz"
        if ! curl -fsSL -o "$tmp" "$url"; then
            error "Download failed from: $url"
            rm -f "$tmp"
            exit 1
        fi
        # Extract
        tar -xzf "$tmp" -C "$(dirname "$tmp")"
        tmp="$(dirname "$tmp")/${APP_NAME}"
    fi

    chmod +x "$tmp"

    # Install
    if [ -w "$INSTALL_DIR" ]; then
        mv "$tmp" "${INSTALL_DIR}/${APP_NAME}"
    else
        info "Need sudo to install to ${INSTALL_DIR}"
        sudo mv "$tmp" "${INSTALL_DIR}/${APP_NAME}"
    fi

    info "Installed to ${INSTALL_DIR}/${APP_NAME}"
}

# Setup directories and config
setup_config() {
    info "Setting up directories..."

    if [ ! -d "$CONFIG_DIR" ]; then
        sudo mkdir -p "$CONFIG_DIR" "$CA_DIR" "$LOG_DIR"
    fi

    if [ ! -f "${CONFIG_DIR}/config.json" ]; then
        info "Creating default config..."
        sudo tee "${CONFIG_DIR}/config.json" > /dev/null << 'CONF'
{
  "mode": "apps_script",
  "exit_mode": "cfw",
  "auth_key": "CHANGE_ME_TO_A_STRONG_SECRET",
  "script_id": "YOUR_APPS_SCRIPT_DEPLOYMENT_ID",
  "relay": {
    "google_ip": "216.239.38.120",
    "front_domain": "www.google.com",
    "timeout": 25
  },
  "proxies": {
    "lan_sharing": false,
    "listeners": [
      { "port": 2801, "type": "mixed", "mode": "smart" }
    ]
  },
  "routing": {
    "smart_routing": true,
    "bypass_hosts": ["localhost", ".local", ".lan", ".home.arpa"],
    "youtube_via_relay": true
  },
  "advanced": {
    "doh_enabled": true,
    "hot_reload": true,
    "log_level": "INFO"
  }
}
CONF
        warn "Edit ${CONFIG_DIR}/config.json — set auth_key and script_id!"
    fi
}

# Install systemd service
install_service() {
    if ! command -v systemctl &>/dev/null; then
        warn "systemd not found — skipping service install"
        return
    fi

    info "Installing systemd service..."
    sudo tee /etc/systemd/system/lray.service > /dev/null << EOF
[Unit]
Description=lray - Domain-Fronted Proxy
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=${INSTALL_DIR}/${APP_NAME} --config ${CONFIG_DIR}/config.json
Restart=on-failure
RestartSec=5
LimitNOFILE=65535

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=${CONFIG_DIR} ${LOG_DIR}
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    info "Service installed. Commands:"
    info "  sudo systemctl start lray"
    info "  sudo systemctl enable lray"
    info "  sudo systemctl status lray"
}

# Main
main() {
    echo ""
    echo "  ╭──────────────────────────────────╮"
    echo "  │  lray installer                  │"
    echo "  ╰──────────────────────────────────╯"
    echo ""

    local platform version

    platform="$(detect_platform)"
    info "Platform: ${platform}"

    version="$(get_latest_version 2>/dev/null || echo "")"
    if [ -z "$version" ]; then
        warn "Could not detect latest version. Building from source..."
        if command -v go &>/dev/null; then
            info "Building with Go..."
            go build -o "${APP_NAME}" ./cmd/lray
            sudo mv "${APP_NAME}" "${INSTALL_DIR}/${APP_NAME}"
            info "Built and installed from source"
        else
            error "Go not installed and no release found. Install Go first."
            exit 1
        fi
    else
        info "Latest version: v${version}"
        install_binary "$platform" "$version"
    fi

    setup_config
    install_service

    echo ""
    info "Installation complete!"
    info ""
    info "Next steps:"
    info "  1. Edit config: sudo nano ${CONFIG_DIR}/config.json"
    info "  2. Set auth_key and script_id"
    info "  3. Start: sudo systemctl start lray"
    info "  4. Install CA cert: ${APP_NAME} --install-cert"
    echo ""
}

main "$@"
