# Configuration

## config.json structure

```json
{
  "mode": "apps_script",
  "auth_key": "your-secret-key",
  "script_id": "your-deployment-id",

  "relay": { ... },
  "proxies": { ... },
  "dashboard": { ... },
  "pac": { ... },
  "dns_relay": { ... },
  "tunnels": { ... },
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

| Key | Default | Description |
|-----|---------|-------------|
| `lan_sharing` | `false` | Share proxy on LAN (binds to 0.0.0.0) |
| `http.enabled` | `true` | Enable HTTP proxy |
| `http.port` | `8085` | HTTP proxy port |
| `socks5.enabled` | `true` | Enable SOCKS5 |
| `socks5.port` | `1080` | SOCKS5 port |
| `mtproto.enabled` | `false` | MTProto proxy (future) |
| `mtproto.port` | `8443` | MTProto port |

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

### dns_relay

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `false` | Enable UDP DNS relay |
| `port` | `5353` | Local DNS port |
| `server` | `8.8.8.8` | Upstream DNS server |

### tunnels

| Key | Default | Description |
|-----|---------|-------------|
| `tcp` | `[]` | TCP tunnel definitions |
| `udp` | `[]` | UDP tunnel definitions |

TCP tunnel example:
```json
{ "name": "SSH", "local_port": 2222, "remote_host": "127.0.0.1", "remote_port": 22 }
```

### routing

| Key | Default | Description |
|-----|---------|-------------|
| `smart_routing` | `true` | Auto-learn direct vs relay |
| `bypass_hosts` | `[...]` | Always direct |
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
| `hosts` | `{}` | Custom DNS overrides |

### Patterniha Sync

When enabled, lray automatically fetches the latest [MITM-DomainFronting](https://github.com/patterniha/MITM-DomainFronting) config from GitHub. This provides direct domain fronting access to certain sites (Google services, GitHub, Reddit, Vercel, Fastly, Netlify) without using the GAS relay — saving quota.

- Checks for updates every hour
- Caches config locally (`patterniha_config.json`)
- Falls back to relay if direct fronting fails
- Disable with `"patterniha_sync": false` in advanced config

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
