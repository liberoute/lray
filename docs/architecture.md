# Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                           YOUR PC                                    │
│                                                                     │
│  Browser ──→ lray proxy (HTTP:8085 / SOCKS5:1080)               │
│                    │                                                │
│                    ├── PAC Server (:8086)                           │
│                    ├── Dashboard (:8087)                            │
│                    ├── Smart Router (rule-based direct/relay/SNI)   │
│                    ├── Response Cache                               │
│                    ├── DoH Resolver (fallback DNS)                  │
│                    └── Config Watcher (hot-reload)                  │
│                                                                     │
│              ┌─── MITM decrypt (local HTTPS) ───┐                  │
│              │                                   │                  │
│              ▼                                   ▼                  │
│     Direct tunnel                    GAS Relay                     │
│   (unblocked sites)          (blocked sites)                       │
│                                      │                             │
└──────────────────────────────────────┼─────────────────────────────┘
                                       │
                              TLS (SNI: www.google.com)
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    GOOGLE INFRASTRUCTURE                             │
│                                                                     │
│  Google CDN Edge → script.google.com → Apps Script (Code.gs)       │
│                                              │                     │
│                                    ┌─────────┼─────────┐           │
│                                    ▼         ▼         ▼           │
│                              gas    cfw       vps           │
│                              (fetch)    (Worker)   (VPS)           │
└─────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         EXIT NODE                                    │
│                                                                     │
│  Option A: GAS direct (UrlFetchApp)                                │
│  Option B: Cloudflare Worker (worker.js)                           │
│  Option C: Your VPS (upstream_forwarder / self-hosted-exit)        │
│                                                                     │
│  Features: HTTP fetch, TCP tunnel, UDP relay, dashboard            │
└─────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
                                   INTERNET
```

## Components

### Client (src/)

| Module | Purpose |
|--------|---------|
| `proxy_server.py` | Async HTTP/SOCKS5 proxy, routing decisions |
| `domain_fronter.py` | GAS relay engine (pool, batching, H2, SNI rotation) |
| `h2_transport.py` | HTTP/2 multiplexing (100+ streams per connection) |
| `mitm.py` | MITM certificate generation |
| `smart_router.py` | Rule-based routing (direct/relay/forwarder) — no probing |
| `doh_resolver.py` | DNS-over-HTTPS (Cloudflare, Google, Quad9) |
| `pac_server.py` | PAC file for browser auto-config |
| `dashboard_server.py` | Real-time monitoring UI |
| `config_watcher.py` | Hot-reload config.json |
| `quota_tracker.py` | Per-script quota tracking |
| `ws_tunnel.py` | WebSocket TCP tunnel client |
| `tcp_over_relay.py` | TCP tunnel through GAS relay |
| `udp_over_relay.py` | UDP tunnel through GAS relay |
| `codec.py` | gzip/brotli/zstd decompression |
| `google_ip_scanner.py` | Find fastest Google frontend IP |

### Server (deploy/)

| Component | Purpose |
|-----------|---------|
| `gas/Code.gs` | Google Apps Script relay (4 modes) |
| `cloudflare-worker/worker.js` | Cloudflare Worker exit |
| `upstream_forwarder/` | Docker-based HTTP relay + TCP/UDP |
| `self-hosted-exit/` | Simple exit node (Worker alternative) |
| `ws-tunnel-server/` | WebSocket TCP tunnel server |
| `systemd/` | Linux service files |

## Data Flow (mode: vps)

```
1. Browser requests https://example.com
2. Proxy intercepts (MITM decrypts locally)
3. Smart Router: "example.com blocked? → check config rules → relay"
4. Domain Fronter:
   a. Pick script ID (quota-aware round-robin)
   b. Encode request as JSON {u, m, h, b}
   c. TLS connect to Google IP (SNI: www.google.com)
   d. HTTP POST to script.google.com/macros/s/{id}/exec
5. GAS receives, forwards to VPS URL
6. VPS fetches https://example.com
7. Response flows back: VPS → GAS → Proxy → Browser
```

## Security Layers

| Layer | Protection |
|-------|-----------|
| DPI bypass | SNI shows www.google.com |
| Auth | AUTH_KEY on every relay request |
| MITM | Local-only, CA cert installed by user |
| Dashboard | Password protected (all 4 dashboards) |
| Forwarder | CF IP whitelist, rate limiting |
| Systemd | NoNewPrivileges, ProtectSystem=strict |
