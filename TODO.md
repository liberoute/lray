## Done ✅

- [x] Docker deploy (dynamic .env, SSL modes, replicas, resource limits)
- [x] Upstream forwarder (rate limit, timeout, metrics, dashboard, auth)
- [x] Self-hosted exit node (Cloudflare alternative)
- [x] Multi-worker failover (GAS + Worker)
- [x] Multiple upstream forwarder failover
- [x] CORS headers (Worker)
- [x] PAC file server
- [x] DNS-over-HTTPS
- [x] Config hot-reload
- [x] Web dashboard (local + server + Worker + GAS)
- [x] Smart routing (auto-learn direct vs relay)
- [x] 4 exit modes (gas, cfw, vps, cfw_vps)
- [x] Setup wizard (interactive, code generation, output/)
- [x] Update mechanism (update.zip)
- [x] Exit through proxy
- [x] Dashboard auth (all dashboards)
- [x] Quota tracker (per-script, persistent, dashboard)
- [x] GAS quota auto-switch
- [x] CLI command (lray)
- [x] --config flag
- [x] Systemd services (default + named instances)
- [x] Logging split (stdout=access, stderr=error)
- [x] GitHub Actions CI/CD (build for 5 platforms)
- [x] One-line installer (install.sh)
- [x] Pre-built binaries (linux/windows/mac, amd64/arm64)
- [x] Code obfuscation (GAS + Worker randomization)
- [x] White-label / rebrand tool
- [x] Nested config format (backward compatible)
- [x] Shared server support (use someone else's Worker/VPS/GAS)
- [x] Build menu (interactive, per-platform)
- [x] Self-update (binary + git)
- [x] SSH via CONNECT proxy (no extra tunnel needed)
- [x] Patterniha sync (auto-fetch MITM-DomainFronting config for direct access)

## TODO ❌

### High Priority
- [ ] Multi-listener proxies — define multiple listeners with different types/modes:
  ```json
  "proxies": [
    { "port": 8085, "type": "mixed", "mode": "smart" },
    { "port": 8086, "type": "http",  "mode": "relay" },
    { "port": 1080, "type": "socks5","mode": "direct" },
    { "port": 8443, "type": "mtproto","mode": "relay", "secret": "..." }
  ]
  ```
  Types: http, socks5, mixed (auto-detect), mtproto
  Modes: smart (direct→mitm→relay), relay (always GAS), direct, mitm (SNI rewrite only)
- [ ] MTProto proxy — persistent tunnel for Telegram, batch/multiplex to reduce quota
- [ ] Multi-mode per-request — vps + cfw_vps simultaneously (fallback)
- [ ] Code uglify/minify (terser) in addition to obfuscation

### Medium Priority
- [ ] Bandwidth throttling (per-host limits to save GAS quota)
- [ ] Plugin system (ad-blocker, tracker-blocker middleware)
- [ ] Prometheus + Grafana monitoring
- [ ] Web-based setup wizard (browser UI instead of CLI)
- [ ] Config validation on startup (warn about bad values)

### Low Priority / Future
- [ ] VPN/TUN mode (system-wide, no browser config needed)
- [ ] Multi-hop routing (Client → GAS → Worker1 → Worker2 → Exit)
- [ ] Mobile app (Android/iOS proxy config helper)
- [ ] Auto-deploy GAS via Apps Script API (no manual paste)
- [ ] Auto-deploy Worker via Cloudflare API (no manual paste)
- [ ] P2P relay sharing (share your GAS scripts with friends)
- [ ] Traffic stats export (CSV/JSON for analysis)
- [ ] Geo-routing (route by destination country)
- [ ] WebRTC/STUN bypass
