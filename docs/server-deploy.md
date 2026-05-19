# Server Deployment

## What Goes on Your VPS

| Component | Purpose | When needed |
|---|---|---|
| **upstream_forwarder** | HTTP relay exit (Docker + Traefik) | mode: `vps` or `cfw_vps` |
| **self-hosted-exit** | Simpler HTTP relay (single container) | mode: `vps` (alternative) |
| **ws-tunnel-server** | TCP tunnel (SSH, DB) when VPS is directly reachable | Optional |

For most users: **upstream_forwarder** is all you need.

## Deploy upstream_forwarder

```bash
# On your PC — generate files
lray setup    # or: lray update

# Upload to server
scp -r dist/upstream_forwarder/ root@your-server:/opt/forwarder/

# On server
cd /opt/forwarder
chmod +x start.sh
./start.sh
```

That's it. `start.sh` handles:
- Extracting `update.zip`
- Starting Docker (Traefik + forwarder containers)
- SSL (Let's Encrypt or own certs)
- Health checks

## Update

```bash
# On PC
lray update

# Upload only the zip
scp dist/upstream_forwarder/update.zip root@server:/opt/forwarder/

# On server
./start.sh restart
```

`start.sh` detects `update.zip`, extracts, overwrites all files, restarts.

## Commands

```bash
./start.sh              # Start
./start.sh stop         # Stop
./start.sh restart      # Restart
./start.sh status       # Show containers
./start.sh logs         # Follow logs
./start.sh build        # Rebuild image
```

## SSL Options

Set in `.env`:

| SSL_MODE | Description |
|---|---|
| `letsencrypt` | Auto-obtain free cert (needs port 80 + real domain) |
| `own` | Your own cert files (set paths in .env) |
| `none` | No SSL, HTTP only |

## Dashboard

`https://your-domain:port/dashboard`

Protected by Basic Auth:
- User: `DASHBOARD_USER` from `.env` (default: admin)
- Pass: `DASHBOARD_PASS` from `.env` (default: AUTH_KEY)

## Scaling

```env
FORWARDER_REPLICAS=4    # Run 4 instances
MEM_LIMIT=1g            # 1GB per instance
CPU_LIMIT=2.0           # 2 cores per instance
```

Traefik auto-balances between replicas.
