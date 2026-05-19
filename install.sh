#!/bin/bash
# lray Installer — installs as system command
#
# Usage:
#   curl -sL https://raw.githubusercontent.com/liberoute/lray/main/install.sh | bash
#   or: ./install.sh

set -e

INSTALL_DIR="/opt/projects/lray"
BIN_LINK="/usr/local/bin/lray"
CONFIG_DIR="/etc/lray"
LOG_DIR="/var/log/lray"
REPO="https://github.com/liberoute/lray.git"

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║     lray Installer                       ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Check root
if [ "$(id -u)" -ne 0 ]; then
    echo "❌ Run as root: sudo ./install.sh"
    exit 1
fi

# Check Python
if ! command -v python3 &>/dev/null; then
    echo "❌ Python 3 not found. Install it first:"
    echo "   apt install python3 python3-pip"
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "  Python: $PY_VER"

# Install/update code
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "  Updating existing installation..."
    cd "$INSTALL_DIR"
    git pull --quiet
else
    echo "  Cloning repository..."
    git clone --quiet "$REPO" "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# Install dependencies
echo "  Installing Python dependencies..."
pip3 install -q -r requirements.txt 2>/dev/null || python3 -m pip install -q -r requirements.txt

# Create directories
mkdir -p "$CONFIG_DIR"
mkdir -p "$LOG_DIR"

# Create CLI wrapper
cat > "$BIN_LINK" << 'EOF'
#!/bin/bash
cd /opt/projects/lray
exec python3 /opt/projects/lray/cli.py "$@"
EOF
chmod +x "$BIN_LINK"

# Install systemd services
cp deploy/systemd/lray.service /etc/systemd/system/
cp deploy/systemd/lray@.service /etc/systemd/system/
systemctl daemon-reload

# Copy env file if not exists
if [ ! -f "$CONFIG_DIR/env" ]; then
    cat > "$CONFIG_DIR/env" << EOF
LRAY_INSTALL_DIR=$INSTALL_DIR
LRAY_CONFIG=$CONFIG_DIR/config.json
LRAY_CA_DIR=$CONFIG_DIR/ca
LRAY_LOG_DIR=$LOG_DIR
EOF
    echo "  Created: $CONFIG_DIR/env"
fi

# Copy example config if no config exists
if [ ! -f "$CONFIG_DIR/config.json" ]; then
    cp config.example.json "$CONFIG_DIR/config.json"
    echo "  Created: $CONFIG_DIR/config.json (edit this!)"
fi

echo ""
echo "✅ Installed!"
echo ""
echo "  Commands:"
echo "    lray setup          — interactive setup wizard"
echo "    lray start          — start proxy"
echo "    lray scan           — find fastest Google IP"
echo "    lray status         — check if running"
echo "    lray version        — show version"
echo "    lray install --ca   — install CA certificate"
echo ""
echo "  Systemd:"
echo "    systemctl start lray"
echo "    systemctl enable lray"
echo ""
echo "  Config: $CONFIG_DIR/config.json"
echo "  Logs:   $LOG_DIR/"
echo ""
echo "  First time? Run: lray setup"
echo ""
