# Server Deployment

## What Goes on Your VPS

| Component | Purpose | When needed |
|---|---|---|
| **upstream_forwarder** | HTTP relay exit (Docker) | mode: `cfw_vps` |
| **self-hosted-exit** | Direct exit node (Docker) | mode: `vps` |

## Deploy

```bash
# On your PC — generate files
lray setup    # or: lray setup --rebuild

# Upload to server
scp -r output/self-hosted-exit/ root@your-server:/opt/exit/

# On server
cd /opt/exit
chmod +x start.sh
./start.sh
```

That's it. `start.sh` handles:
- Extracting `update.zip`
- Building and starting Docker container
- SSL (Let's Encrypt or own certs)
- Health checks

## Update

```bash
# On PC
lray setup --rebuild

# Upload only the zip
scp output/self-hosted-exit/update.zip root@server:/opt/exit/

# On server
./start.sh
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

Docker Compose auto-balances between replicas.
