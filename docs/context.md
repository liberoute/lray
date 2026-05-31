# lray — Project Context

> This file provides context about the project for AI assistants and contributors.
> Read this FIRST before making any changes.

## Project Identity

- **Name:** lray
- **Repo:** https://github.com/liberoute/lray
- **Version:** 1.1.1 (in `src/constants.py`)
- **Language:** Python 3.10+ (client), Node.js 18 (server components), Go 1.22+ (client rewrite)
- **License:** MIT

## What This Project Does

lray is a censorship bypass tool that uses **domain fronting** through Google's infrastructure. DPI only sees traffic to `www.google.com`, but the actual payload goes through Google Apps Script to reach blocked websites.

```
Browser → lray (local proxy) → [SNI: www.google.com] → Google Apps Script → Exit → Internet
```

## Architecture Overview

### Client (Python, runs on user's machine)

| File | Purpose |
|------|---------|
| `cli.py` | Entry point, CLI commands |
| `main.py` | Starts the proxy server |
| `src/proxy_server.py` | Core proxy — multi-listener, routing, MITM |
| `src/domain_fronter.py` | HTTP/2 connection to GAS via Google IP |
| `src/mitm.py` | TLS interception (MITM) for HTTPS |
| `src/smart_router.py` | Rule-based routing (direct/relay/forwarder) |
| `src/patterniha_sync.py` | Auto-fetches domain fronting config from GitHub |
| `src/mtproto_proxy.py` | MTProto proxy for Telegram with batching |
| `src/doh_resolver.py` | DNS-over-HTTPS fallback |
| `src/pac_server.py` | PAC file for browser auto-config |
| `src/dashboard_server.py` | Web dashboard API |
| `src/dashboard.html` | Dashboard UI |
| `src/config_parser.py` | Normalizes nested config to flat |
| `src/config_watcher.py` | Hot-reload config on change |
| `src/quota_tracker.py` | Tracks GAS quota per script |
| `src/constants.py` | Version, timeouts, IP lists |

### Server Components (Node.js)

| File | Purpose |
|------|---------|
| `deploy/gas/Code.gs` | Google Apps Script relay |
| `deploy/cloudflare-worker/worker.js` | Cloudflare Worker (middle hop) |
| `deploy/self-hosted-exit/exit_node.js` | Self-hosted exit node (Docker) |
| `deploy/upstream_forwarder/upstream_forwarder.js` | Upstream forwarder for cfw_vps mode |

### Tools

| File | Purpose |
|------|---------|
| `tools/setup.py` | Interactive setup wizard |
| `tools/build.py` | Build binaries + release packages |
| `tools/code_obfuscator.py` | Randomize function names in GAS/Worker code |

## Listener Modes

| Mode | Cert | How it works |
|------|------|-------------|
| `smart` | ✅ | Rule-based: config decides direct/relay/SNI per domain |
| `relay` | ✅ | Always MITM → JSON → GAS → exit |
| `full` | ❌ | Raw TCP bytes → GAS → VPS (no decrypt, no cert needed) |
| `direct` | ❌ | Connect directly, no relay |
| `mitm` | ✅ | SNI rewrite only (patterniha style) |

## Smart Mode Routing (Rule-Based, No Probing)

When listener mode is `smart`, routing order is:

```
1. bypass_hosts → direct (no proxy)
2. block_hosts → refuse (403)
3. direct_google_allow → SNI rewrite (connect to google_ip)
4. force_relay (youtube_via_relay + direct_google_exclude + .google.com etc.) → relay
5. SNI_REWRITE_SUFFIXES → SNI rewrite
6. Patterniha mappings → SNI rewrite
7. Google domain → relay
8. Default → relay
```

**No probe. No timeout. No guessing. Config decides.**

Smart router (`src/smart_router.py`) only returns: `direct`, `relay`, or `forwarder`.

## Config Format

```json
{
  "mode": "apps_script",
  "exit_mode": "cfw",
  "auth_key": "...",
  "script_id": "...",
  "relay": { "google_ip": "216.239.38.120", "front_domain": "www.google.com" },
  "proxies": {
    "lan_sharing": true,
    "listeners": [
      { "port": 2801, "type": "mixed", "mode": "smart" }
    ]
  },
  "routing": {
    "smart_routing": true,
    "bypass_hosts": ["localhost", ".local", ".lan", ".home.arpa"],
    "block_hosts": [],
    "forwarder_hosts": [],
    "youtube_via_relay": true,
    "direct_google_exclude": ["gemini.google.com", "drive.google.com"],
    "direct_google_allow": ["drive.usercontent.google.com"]
  },
  "advanced": {
    "patterniha_sync": false,
    "doh_enabled": true,
    "hot_reload": true
  }
}
```

### Key config fields:
- `youtube_via_relay: true` → YouTube + all Google domains force relay (no SNI rewrite)
- `direct_google_exclude` → these Google domains always relay
- `direct_google_allow` → these Google domains SNI rewrite (highest priority)
- `patterniha_sync` → disabled when Google IP is throttled/blocked

## Exit Modes

| Mode | Path |
|------|------|
| `gas` | GAS → internet directly |
| `cfw` | GAS → Cloudflare Worker → internet |
| `vps` | GAS → VPS exit node → internet |
| `cfw_vps` | GAS → Worker → VPS → internet |

## Mixed Listener

Port with `type: "mixed"` auto-detects SOCKS5 vs HTTP by peeking first byte:
- `\x05` → SOCKS5
- anything else → HTTP

## Code Obfuscator (`tools/code_obfuscator.py`)

- Uses regex word-boundary (`\b`) for safe renaming
- Dead code only between top-level functions (indent=0)
- `"json"` NOT in rename list (was corrupting `application/json`)
- Worker auth key hardcoded for ALL modes (not just cfw_vps)

## Setup Wizard (`tools/setup.py`)

- Asks proxy type (mixed/http/socks5), default port 2801
- Allows multiple listeners
- Auth key hardcoded into worker.js
- `config_parser.py` flattens `direct_google_allow` and `direct_google_exclude` from routing section

## Known Issues

- Google IP `216.239.38.120` may be throttled under heavy concurrent connections → patterniha/SNI rewrite fails
- When IP is blocked: disable patterniha, use relay mode
- `lray scan` finds working Google IPs
- PyInstaller binary: won't crash if config.json missing (shows error instead of wizard)
- `quota_state.json` is gitignored

## Conventions

- Persian comments from developer — code and docs in English
- Default proxy port: 2801 (changed from 8085)
- `config.json` is gitignored — contains secrets
- Line endings: `.sh`, `.env`, `.yml` must be LF
- Env vars: `LRAY_` prefix

## Testing

```bash
python tests/test_imports.py      # All 20 modules import
python tests/test_setup_wizard.py # Setup generates correct files (5 modes)
python tests/run_all.py           # Run everything
```

## TODO

- [x] README.md and docs/ updated for new smart mode and listener modes
- [x] Remove dead code from smart_router.py (record_direct_success/failure, _records, cache logic)
- [x] Remove routing_cache.json logic (no longer needed)
- [x] Remove `_direct_temporarily_disabled` from proxy_server
- [ ] Dashboard: show which mode each request used (relay/SNI/direct)
- [ ] `lray scan` to find working Google IP when current one is blocked
- [ ] Mode `full` (raw TCP) needs testing with real VPS
