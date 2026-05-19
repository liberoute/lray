# lray v1.1.0

### Domain-Fronted Relay — Bypass DPI Censorship

Traffic goes through Google's infrastructure. DPI only sees `www.google.com`.

```
Browser → Local Proxy → [SNI: www.google.com] → GAS → Exit → Internet
```

---

## Quick Start

```bash
# Install
git clone https://github.com/liberoute/lray.git && cd lray
pip install -r requirements.txt

# Setup (interactive wizard)
python setup.py

# Run
lray
```

Or one-line install (Linux):
```bash
curl -sL https://raw.githubusercontent.com/liberoute/lray/main/install.sh | sudo bash
lray setup
```

Pre-built binaries: [Releases](https://github.com/liberoute/lray/releases)

---

## Choose Your Mode

| You have | Best mode | Path |
|---|---|---|
| Only Google account | `gas` | GAS → internet |
| Google + Cloudflare | `cfw` | GAS → Worker → internet |
| Google + VPS | `vps` | GAS → VPS → internet |
| Google + CF + VPS | `cfw_vps` | GAS → Worker → VPS → internet |

The wizard asks and configures everything for you.

---

## CLI Commands

```bash
lray                       # Start proxy
lray setup                 # Interactive setup (from scratch)
lray setup --rebuild       # Re-generate output/ without questions
lray update                # Check for updates & self-update
lray test                  # Test connectivity
lray check                 # Validate config
lray status                # Check if running
lray scan                  # Find fastest Google IP
lray install               # Install service + CA cert
lray install --service     # Install systemd service only
lray install --ca          # Install CA certificate only
lray uninstall             # Remove everything
lray uninstall --service   # Remove service only
lray uninstall --ca        # Remove CA only
lray --config path.json    # Start with custom config
lray version               # Show version
```

---

## Documentation

| Guide | Description |
|---|---|
| [Getting Started](docs/getting-started.md) | First-time setup guide |
| [Exit Modes](docs/exit-modes.md) | Detailed explanation of all 4 modes |
| [Server Deploy](docs/server-deploy.md) | Deploy on VPS (Docker) |
| [Browser Setup](docs/browser-setup.md) | SwitchyOmega, FoxyProxy, system proxy |
| [SSH Tunnel](docs/ssh-tunnel.md) | SSH through the proxy |
| [Configuration](docs/configuration.md) | All config options |
| [Dashboard](docs/dashboard.md) | Monitoring & dashboards |
| [Building](docs/building.md) | Build binary from source |
| [Troubleshooting](docs/troubleshooting.md) | Common issues & fixes |
| [Architecture](docs/architecture.md) | Technical deep-dive |

---

## Releases

Pre-built binaries are available on the [Releases](https://github.com/liberoute/lray/releases) page.

Release naming: `lray-{os}-{arch}-v{version}.zip`

| Platform | File |
|---|---|
| Linux x64 | `lray-linux-amd64-v1.0.0.zip` |
| Linux ARM64 | `lray-linux-arm64-v1.0.0.zip` |
| Windows x64 | `lray-windows-amd64-v1.0.0.zip` |
| Windows ARM64 | `lray-windows-arm64-v1.0.0.zip` |
| macOS ARM64 | `lray-macos-arm64-v1.0.0.zip` |
| macOS x64 | `lray-macos-amd64-v1.0.0.zip` |

---

## Inspiration & Credits

lray is inspired by these projects:

- [MasterHttpRelayVPN](https://github.com/masterking32/MasterHttpRelayVPN) — the original concept of domain fronting through Google Apps Script
- [mhr-cfw](https://github.com/denuitt1/mhr-cfw) — Cloudflare Worker extension of the original
- [MITM-DomainFronting](https://github.com/patterniha/MITM-DomainFronting) — MITM domain fronting approach by [@patterniha](https://github.com/patterniha)

### Special Thanks — @patterniha

The direct domain fronting method used in lray (the `patterniha_sync` module) is based on the pioneering work of [@patterniha](https://github.com/patterniha). Without their research and continuous updates to the MITM-DomainFronting config, this approach would not have been possible.

If you find this useful, please consider supporting patterniha directly:

- GitHub: [github.com/patterniha](https://github.com/patterniha)
- Telegram: [@patterniha](https://t.me/patterniha)
- USDT (BEP20): `0x76a768B53Ca77B43086946315f0BDF21156bF424`
- USDT (TRC20): `TU5gKvKqcXPn8itp1DouBCwcqGHMemBm8o`

### Differences from those projects

- **Rewritten from scratch** — cleaner architecture, modular codebase
- **4 exit modes** instead of single-mode — flexible deployment (gas, cfw, vps, cfw_vps)
- **Self-hosted exit node** — no Cloudflare dependency required
- **Setup wizard** — interactive config generation with code obfuscation
- **Smart routing** — auto-learns which hosts need relay vs direct
- **Multi-worker failover** — automatic failover across GAS scripts
- **Dashboard** — real-time monitoring on all components (local, GAS, Worker, VPS)
- **CLI tool** — unified interface with self-update
- **Pre-built binaries** — no Python needed for end users

---

## License

[MIT](LICENSE)
