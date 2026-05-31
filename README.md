# lray (Go)

Domain-fronted censorship bypass tool. Routes traffic through Google Apps Script, hiding it behind `www.google.com` SNI.

```
Browser → lray (local proxy) → [SNI: www.google.com] → Google Apps Script → Exit → Internet
```

## Quick Start

```bash
# Build
go build -o lray ./cmd/lray

# Copy and edit config
cp config.example.json config.json
# Edit config.json: set auth_key and script_id

# Run
./lray
```

## Usage

```
lray                          Start proxy (default)
lray --config path.json       Use custom config
lray --port 3000              Override listen port
lray --scan                   Find fastest Google IP
lray --install-cert           Install MITM CA certificate
lray --log-level DEBUG        Set log level
lray --version                Show version
```

## Build

```bash
# Current platform
make build

# All platforms
make build-all

# Docker
docker build -t lray .
docker run -v ./config.json:/app/config.json -p 2801:2801 lray
```

## Config

See `config.example.json`. Key fields:

| Field | Description |
|-------|-------------|
| `auth_key` | Shared secret (must match Code.gs) |
| `script_id` | Apps Script deployment ID |
| `relay.google_ip` | Google frontend IP to connect to |
| `relay.front_domain` | SNI hostname (default: www.google.com) |
| `proxies.listeners` | Port/type/mode for each listener |
| `routing.youtube_via_relay` | Force YouTube through relay |
| `routing.bypass_hosts` | Hosts to connect directly |

## Listener Modes

| Mode | Description |
|------|-------------|
| `smart` | Rule-based: config decides direct/relay/SNI per domain |
| `relay` | Always MITM → relay through GAS |
| `direct` | Connect directly, no relay |

## Architecture

```
cmd/lray/           Entry point + CLI
internal/
  config/           Config parsing + hot-reload watcher
  proxy/            Core proxy (HTTP/SOCKS5/CONNECT/MITM)
  fronter/          Domain fronting relay engine
  mitm/             TLS interception + cert generation
  router/           Smart routing rules
  resolver/         DNS-over-HTTPS
  pac/              PAC file server
  dashboard/        Web monitoring dashboard
  quota/            GAS quota tracking
  patterniha/       Patterniha config sync
  mtproto/          MTProto proxy for Telegram
  scanner/          Google IP scanner
  certinstall/      Cross-platform CA installer
  codec/            Content-encoding decoders
  logger/           Colored logging
```

## License

MIT
