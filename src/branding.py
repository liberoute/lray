"""
Branding — white-label configuration.

All project name references read from here.
Change these values to rebrand the entire project.
"""

# ─── Project Identity ─────────────────────────────────────────────────────────

APP_NAME = "lray"
APP_DISPLAY_NAME = "lray"
APP_DESCRIPTION = "Domain-Fronted Relay — Bypass DPI Censorship"

# GitHub
GITHUB_REPO = "liberoute/lray"
GITHUB_URL = f"https://github.com/{GITHUB_REPO}"
GITHUB_RAW = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"

# Install paths (Linux)
INSTALL_DIR = f"/opt/projects/{APP_NAME}"
CONFIG_DIR = f"/etc/{APP_NAME}"
LOG_DIR = f"/var/log/{APP_NAME}"
BIN_PATH = f"/usr/local/bin/{APP_NAME}"

# Service
SERVICE_NAME = APP_NAME
SERVICE_FILE = f"{APP_NAME}.service"
SERVICE_TEMPLATE_FILE = f"{APP_NAME}@.service"

# CA
CA_CERT_NAME = APP_DISPLAY_NAME
