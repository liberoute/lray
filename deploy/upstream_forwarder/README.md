# Upstream Forwarder — Docker Deployment

Provides a stable exit IP for the lray relay. Solves the CAPTCHA/IP-binding problem where Cloudflare Workers exit through rotating IPs.

## Quick Start

```bash
# 1. Copy config
cp .env.example .env

# 2. Edit .env — at minimum set:
#    - DOMAIN (your domain or IP)
#    - AUTH_KEY (long random string, min 32 chars)

# 3. Start
chmod +x start.sh
./start.sh
```

That's it. The script auto-detects the best configuration based on your `.env`.

## Commands

| Command | What it does |
|---|---|
| `./start.sh` | Start everything |
| `./start.sh stop` | Stop everything |
| `./start.sh restart` | Restart |
| `./start.sh status` | Show running containers |
| `./start.sh logs` | Follow logs |
| `./start.sh logs forwarder` | Follow only forwarder logs |
| `./start.sh build` | Rebuild forwarder image |

## Configuration Examples

### Simplest: IP address, no SSL

```env
DOMAIN=185.100.50.25
AUTH_KEY=my-super-secret-key-that-is-at-least-32-characters
PROTOCOL_MODE=auto
SSL_MODE=none
HTTP_PORT=8080
```

### Domain with free SSL (Let's Encrypt)

```env
DOMAIN=forwarder.mysite.com
AUTH_KEY=my-super-secret-key-that-is-at-least-32-characters
PROTOCOL_MODE=auto
SSL_MODE=letsencrypt
LETSENCRYPT_EMAIL=me@gmail.com
HTTP_PORT=80
HTTPS_PORT=443
```

### Domain with your own SSL certificate

```env
DOMAIN=forwarder.mysite.com
AUTH_KEY=my-super-secret-key-that-is-at-least-32-characters
PROTOCOL_MODE=auto
SSL_MODE=own
SSL_CERT_FILE=./certs/fullchain.pem
SSL_KEY_FILE=./certs/privkey.pem
HTTPS_PORT=443
```

## Scaling

Change `FORWARDER_REPLICAS` in `.env` to run more instances:

```env
FORWARDER_REPLICAS=4
```

Traefik automatically load-balances between all replicas.

## Endpoints

| Path | Method | Description |
|---|---|---|
| `/` | GET | Status page |
| `/fwd` | POST | Forward request (requires auth) |
| `/health` | GET | Health check (for monitoring) |
| `/stats` | GET | JSON metrics (requests, errors, latency) |

## Connecting to Cloudflare Worker

In your Cloudflare Worker settings, add these environment variables:

| Name | Value |
|---|---|
| `UPSTREAM_FORWARDER_URL` | `https://yourdomain.com/fwd` (or `http://your-ip:port/fwd`) |
| `UPSTREAM_AUTH_KEY` | Same value as `AUTH_KEY` in your `.env` |

## File Structure

```
upstream_forwarder/
├── .env.example          ← Copy to .env
├── .env                  ← Your config (don't commit!)
├── start.sh              ← Deploy script
├── docker-compose.yml    ← Base Docker config
├── dynamic.yml           ← Traefik TLS config (for own certs)
├── Dockerfile            ← Forwarder container
├── upstream_forwarder.js ← Forwarder app
└── README.md             ← This file
```

## Security Features

- **Rate limiting** — Configurable per-IP request limit
- **Body size limit** — Prevents memory exhaustion attacks
- **Fetch timeout** — No hanging connections
- **Cloudflare IP whitelist** — Optional, only allows CF Worker IPs
- **Auth key** — Required on every request
- **Resource limits** — CPU and memory caps per container
- **Log rotation** — Prevents disk from filling up
- **Graceful shutdown** — Clean connection handling on restart

## Troubleshooting

**SSL not working with Let's Encrypt:**
- Make sure port 80 is open (needed for HTTP challenge)
- Make sure your domain DNS points to this server
- Check logs: `./start.sh logs traefik`

**Connection refused:**
- Check if containers are running: `./start.sh status`
- Check forwarder logs: `./start.sh logs forwarder`
- Make sure AUTH_KEY matches between Worker and forwarder

**High memory usage:**
- Lower `MEM_LIMIT` in `.env`
- Lower `FORWARDER_REPLICAS`
- Lower `MAX_BODY_MB`
