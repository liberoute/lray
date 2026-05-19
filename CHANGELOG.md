# Changelog

## [1.1.0] — 2026-05-19

### Added
- **Multi-listener proxies** — define multiple listeners with different types and modes
  - Types: `mixed` (HTTP+SOCKS5 auto-detect), `http`, `socks5`, `mtproto`
  - Modes: `smart` (direct→mitm→relay), `relay` (always GAS), `direct`, `mitm` (SNI rewrite)
- **Per-listener routing mode** — each port can have its own routing strategy
- **Patterniha sync** — auto-fetches MITM-DomainFronting config for direct access without relay
- **Smart router persistence** — learned routes cached to `routing_cache.json`, survives restarts
- **Probe timeout reduced** — 3s instead of 4s for faster first-load

### Changed
- **Config format**: `proxies` section now supports `listeners` array (old format still works)
- **Smart router**: cache persists to disk, max 5000 entries, 24h expiry
- **Rebrand complete**: all `MHR_` env vars → `LRAY_`, no remaining old references
- **Build system**: releases named `lray-{os}-{arch}-v{version}.zip`
- **GitHub Actions**: builds zip packages instead of tar.gz
- **README**: added credits section, release table, patterniha acknowledgment

### Fixed
- **exit_node.js**: duplicate `let server` declaration causing crash
- **start.sh**: added `docker compose down` before `up` to prevent container name conflicts
- **setup --update**: now correctly detects exit mode from `config.json`
- **install.sh**: env vars renamed to `LRAY_*`

---

## [1.0.0] — 2026-05-19

### Added

#### Exit Modes
- **4 exit modes**: `gas`, `cfw`, `vps`, `cfw_vps` — choose how traffic exits
- **Self-hosted exit node** (`deploy/self-hosted-exit/`) — full Cloudflare Worker replacement
- **GAS direct mode** — GAS fetches target directly without any intermediary

#### Networking
- **DNS-over-HTTPS** — automatic fallback when system DNS is censored (Cloudflare, Google, Quad9)
- **Smart Routing** — auto-learns which hosts are blocked, routes direct when possible
- **PAC file server** — auto-configure browsers at `http://localhost:8086/proxy.pac`
- **Multi-worker failover** (GAS) — round-robin + automatic failover on 429/5xx
- **Multiple upstream forwarder failover** (Worker) — tries each forwarder in order
- **Exit through proxy** — route forwarder outbound through external HTTP proxy
- **CORS headers** on Worker responses
- **SSH via CONNECT** — tunnel SSH, databases through HTTP CONNECT proxy

#### Server (Upstream Forwarder)
- **Complete Docker rewrite** — dynamic `.env`, SSL modes, replicas, resource limits
- **3 SSL modes**: Let's Encrypt (auto), own certificate, none
- **Protocol modes**: HTTP, HTTPS, or both — all configurable
- **Rate limiting** — per-IP request limits
- **Body size limit** — prevents memory exhaustion
- **Fetch timeout** — no hanging connections
- **Cloudflare IP whitelist** — restrict `/fwd` to CF IPs only
- **Dashboard** with auth (`/dashboard`) — requests, latency, bandwidth, logs
- **Metrics endpoints** — `/stats`, `/health`
- **TCP tunnel support** — persistent sessions for SSH etc.
- **UDP relay support** — send/receive UDP packets
- **Log rotation** — max-size per container
- **Graceful shutdown** — clean connection handling
- **Auto-update mechanism** — upload `update.zip`, run `start.sh`
- **`start.sh`** — start/stop/restart/status/logs/build commands with validation

#### Client
- **Dashboard** — real-time web UI with traffic chart, top hosts, cache stats
- **Config hot-reload** — change `config.json` without restarting
- **Quota tracker** — per-script usage tracking, persists across restarts
- **Setup wizard** — interactive setup generates all code into `dist/`
- **Update mode** (`lray update`) — regenerate dist/ preserving settings
- **Systemd services** — `lray.service` + `lray@.service` for named instances
- **CLI command** (`lray`) — unified interface: start, setup, update, scan, status, version
- **`--config` flag** — run with any config file: `lray --config /path/to.json`
- **Pre-built binaries** — GitHub Actions builds for Linux/Windows/macOS (amd64 + arm64)
- **One-line installer** — `curl | bash` installs everything on Linux
- **Logging split** — stdout=access (INFO), stderr=errors (WARNING+) for systemd

#### Dashboards (all password-protected)
- **Local dashboard** — `http://localhost:8087/dashboard`
- **Forwarder dashboard** — Basic Auth (user/pass from `.env`)
- **Worker dashboard** — cookie-based login with AUTH_KEY
- **GAS dashboard** — login page with AUTH_KEY, shows quota usage

#### Quota Monitoring
- **GAS quota tracking** — requests today / daily limit / reset time
- **Quota progress bar** in GAS dashboard (green/orange/red)
- **`cmd: "quota"`** endpoint — client can query remaining quota
- **`quota_state.json`** — persists across restarts
- **Auto-switch scripts** when one is exhausted

### Changed
- **Logging split**: stdout = access (INFO), stderr = errors (WARNING+)
- **Worker code** now hardcodes forwarder URL + auth key (no manual env vars needed)
- **GAS Code.gs** rewritten with multi-mode support + dashboard + quota tracking
- **`.env`** now includes all settings (dashboard auth, exit proxy, resource limits)
- **`docker-compose.yml`** uses `deploy.replicas` instead of hardcoded node1/node2
- **Setup wizard** asks exit mode, generates correct code per mode
- **Worker** accepts both HTTP and HTTPS forwarder URLs (was HTTPS-only)

### Fixed
- **Windows `\r\n` line endings** on Linux — added `.gitattributes` + LF conversion
- **Build path** in docker-compose was wrong (`./services/...` → `.`)
- **Network** was `external: true` causing errors — now auto-created
- **`traefik.yml`** didn't support env vars — moved to `command` args
- **GAS Code.gs syntax error** — leftover doGet lines removed
- **Dashboard metrics** counted dashboard requests as relay requests
- **`DASHBOARD_PASS` empty** = no auth — now falls back to AUTH_KEY

### Security
- All dashboards require authentication
- Forwarder: Basic Auth
- Worker: cookie-based (HttpOnly, SameSite=Strict, 24h expiry)
- GAS: query param login page
- `AUTH_KEY` minimum 32 characters enforced
- `no-new-privileges` in systemd service
- Docker `security_opt: no-new-privileges`

---

## [0.x] — Previous releases (as mhr-cfw)

- Initial domain fronting relay
- HTTP/2 multiplexing
- SNI rotation
- MITM proxy
- SOCKS5 support
- Request batching + coalescing
- Response cache
- Chunked downloads
- Google IP scanner
- LAN sharing
- Certificate installer

### Documentation
- Added `docs/` folder with 7 guides:
  - getting-started.md — first-time setup
  - exit-modes.md — all 4 modes explained with decision tree
  - server-deploy.md — VPS deployment guide
  - ssh-tunnel.md — SSH through proxy (CONNECT)
  - configuration.md — all config options reference
  - dashboard.md — monitoring & quota
  - architecture.md — technical deep-dive with diagrams
- README.md simplified — links to docs for details
