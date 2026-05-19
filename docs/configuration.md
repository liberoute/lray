# Configuration

## config.json structure

```json
{
  "mode": "apps_script",
  "exit_mode": "vps",
  "auth_key": "your-secret-key",
  "script_id": "your-deployment-id",

  "relay": { ... },
  "proxies": { ... },
  "dashboard": { ... },
  "pac": { ... },
  "routing": { ... },
  "advanced": { ... }
}
```

## Sections

### relay

| Key | Default | Description |
|-----|---------|-------------|
| `google_ip` | `216.239.38.120` | Google frontend IP |
| `front_domain` | `www.google.com` | SNI hostname shown to DPI |
| `timeout` | `25` | Seconds per relay request |
| `tls_connect_timeout` | `15` | TLS handshake timeout |
| `tcp_connect_timeout` | `10` | TCP connect timeout |
| `parallel_relay` | `1` | Fan-out (fire N scripts) |
| `verify_ssl` | `true` | Verify TLS certs |

### proxies

Two formats supported:

#### New format (listeners array)

```json
"proxies": {
  "lan_sharing": false,
  "listeners": [
    { "port": 8085, "type": "mixed", "mode": "smart" },
    { "port": 1080, "type": "socks5", "mode": "relay" },
    { "port": 9090, "type": "http", "mode": "direct" },
    { "port": 8443, "type": "mtproto", "mode": "relay", "secret": "ee..." }
  ]
}
```

Each listener has:

| Key | Values | Description |
|-----|--------|-------------|
| `port` | number | Port to listen on |
| `type` | `mixed`, `http`, `socks5`, `mtproto` | Protocol to accept |
| `mode` | `smart`, `relay`, `direct`, `mitm` | How to route traffic |
| `secret` | string | MTProto secret (only for mtproto type) |

**Types:**

| Type | Description |
|------|-------------|
| `mixed` | Auto-detect HTTP or SOCKS5 from first byte (recommended) |
| `http` | HTTP proxy only |
| `socks5` | SOCKS5 proxy only |
| `mtproto` | MTProto proxy for Telegram |

**Modes:**

| Mode | Description |
|------|-------------|
| `smart` | Try direct first (3s timeout), then MITM/relay. Learns over time. |
| `relay` | Always route through GAS relay. Guaranteed to work for blocked sites. |
| `direct` | Always connect directly. Fast, but only works for unblocked sites. |
| `mitm` | SNI rewrite only (patterniha style). No relay, no quota usage. |

**Example use cases:**

```json
"listeners": [
  { "port": 8085, "type": "mixed", "mode": "smart" },
  { "port": 8086, "type": "http", "mode": "relay" },
  { "port": 1080, "type": "socks5", "mode": "direct" },
  { "port": 8443, "type": "mtproto", "mode": "relay", "secret": "ee..." }
]
```

- Port 8085: Main browser proxy — smart routing (learns what's blocked)
- Port 8086: For apps that need guaranteed access — always relay
- Port 1080: For downloads from unblocked sites — fast direct
- Port 8443: Telegram MTProto — always relay

#### Old format (still supported)

```json
"proxies": {
  "lan_sharing": false,
  "http": { "enabled": true, "port": 8085 },
  "socks5": { "enabled": true, "port": 1080 },
  "mtproto": { "enabled": false, "port": 8443, "secret": "" }
}
```

Automatically converted to listeners internally.

### dashboard

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `true` | Enable web dashboard |
| `port` | `8087` | Dashboard port |
| `user` | `""` | Username (empty = AUTH_KEY only) |
| `pass` | `""` | Password (empty = AUTH_KEY) |

### pac

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `true` | Enable PAC file server |
| `port` | `8086` | PAC port |

### routing

| Key | Default | Description |
|-----|---------|-------------|
| `smart_routing` | `true` | Auto-learn direct vs relay |
| `bypass_hosts` | `[...]` | Always direct (regardless of listener mode) |
| `block_hosts` | `[]` | Always refuse |
| `forwarder_hosts` | `[]` | Always through forwarder |
| `youtube_via_relay` | `false` | Route YouTube through relay |

### advanced

| Key | Default | Description |
|-----|---------|-------------|
| `doh_enabled` | `true` | DNS-over-HTTPS fallback |
| `hot_reload` | `true` | Watch config for changes |
| `log_level` | `INFO` | DEBUG, INFO, WARNING, ERROR |
| `patterniha_sync` | `true` | Auto-fetch patterniha MITM-DomainFronting config |
| `hosts` | `{}` | Custom DNS overrides (domain → IP) |

### Patterniha Sync

When enabled, lray automatically fetches the latest [MITM-DomainFronting](https://github.com/patterniha/MITM-DomainFronting) config from GitHub. This provides direct domain fronting access to certain sites (Google services, GitHub, Reddit, Vercel, Fastly, Netlify) without using the GAS relay — saving quota.

- Checks for updates every hour
- Caches config locally (`patterniha_config.json`)
- Falls back to relay if direct fronting fails
- Disable with `"patterniha_sync": false` in advanced config

### Smart Router Cache

The smart router persists learned routes to `routing_cache.json`:
- Saves every 60 seconds and on shutdown
- Loads on startup — no re-learning after restart
- Entries expire after 24 hours
- Max 5000 entries (keeps most recent)

## LAN Sharing

Set `proxies.lan_sharing` to `true`:
```json
{ "proxies": { "lan_sharing": true } }
```

Proxy binds to `0.0.0.0`. Other devices use your IP + port.

## Multi-Script

```json
{ "script_ids": ["id1", "id2", "id3"] }
```

Auto-rotates. Each = 20K requests/day.

## Backward Compatibility

Old flat format still works:
```json
{ "listen_host": "127.0.0.1", "listen_port": 8085, "socks5_port": 1080 }
```

Automatically normalized to new format internally.
