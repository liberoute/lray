# Self-Hosted Exit Node

Replaces Cloudflare Worker entirely. Your VPS fetches target websites directly — no Cloudflare needed.

## Architecture

```
Client → Local Proxy → GAS (Google Apps Script) → THIS SERVER → Target Website
```

Your VPS IP is the exit IP. No rotating Cloudflare IPs, no CAPTCHA issues.

## Quick Start

```bash
cp .env.example .env
# Edit .env — set AUTH_KEY (min 32 chars)
docker compose up -d
```

## Usage with GAS

In `Code.gs`, set `WORKER_URL` to your exit node:

```javascript
const WORKER_URLS = [
  "https://your-vps-domain.com"   // or http://your-ip:3000
];
```

The wire protocol is identical to the Cloudflare Worker — GAS doesn't need any changes beyond the URL.

## With TLS (recommended)

Run behind Caddy for automatic HTTPS:

```
# Caddyfile
your-domain.com {
    reverse_proxy 127.0.0.1:3000
}
```

Or use the upstream_forwarder's Traefik setup and point it at this container.

## Endpoints

| Path | Method | Description |
|---|---|---|
| `/` | GET | Status page |
| `/` | POST | Relay request (same protocol as Worker) |
| `/health` | GET | Health check |
| `/stats` | GET | JSON metrics |

## Optional: Exit through another proxy

Set `EXIT_PROXY_URL` in `.env` to route all outbound traffic through a proxy:

```env
EXIT_PROXY_URL=http://user:pass@proxy-host:port
```

## vs Cloudflare Worker

| | Cloudflare Worker | Self-Hosted Exit |
|---|---|---|
| Exit IP | Rotating (Cloudflare edge) | Fixed (your VPS) |
| CAPTCHA | Often breaks | Works reliably |
| Cost | Free tier limits | VPS cost |
| Setup | Dashboard deploy | Docker one-liner |
| Speed | Fast (edge) | Depends on VPS location |
| Reliability | High (Cloudflare infra) | Depends on VPS |
