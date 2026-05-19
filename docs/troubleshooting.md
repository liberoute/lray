# Troubleshooting

## Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| `Relay error: HTTP 403` | GAS auth mismatch or not deployed | Redeploy Code.gs, check AUTH_KEY matches |
| CAPTCHA loops | Cloudflare rotating IP | Use `vps` or `cfw_vps` mode (stable IP) |
| `dns lookup failed` | System DNS blocked | Should auto-fallback to DoH. Check `doh_enabled: true` |
| Slow speeds | Normal for relay (~2-3s) | Try `lray scan` for faster Google IP |
| Certificate errors | CA not installed | `lray install-cert` |
| `\r` error on Linux | Windows line endings | `sed -i 's/\r$//' start.sh .env` |
| Dashboard no auth | DASHBOARD_PASS empty | Falls back to AUTH_KEY automatically |
| 429 from GAS | Quota exhausted | Add more scripts (`script_ids` array) |
| Worker not responding | Worker crashed or rate limited | Check CF dashboard, redeploy |
| SSH not connecting | Need ProxyCommand | See [SSH Tunnel](ssh-tunnel.md) |

## Diagnostic Commands

```bash
lray check      # Validate config
lray status     # Check if running
lray test       # Full connectivity test
lray scan       # Find fastest Google IP
```

## Debug Logging

```bash
lray --log-level DEBUG
```

Or in config.json:
```json
{ "log_level": "DEBUG" }
```

## GAS Quota Exhausted

Symptoms: requests start failing with 429 or timeout.

Fix:
1. Deploy Code.gs on another Google account
2. Add the new Deployment ID to `script_ids` array:
```json
{ "script_ids": ["first-id", "second-id"] }
```
3. Restart proxy — auto-rotates between scripts

## Forwarder Not Starting

```bash
./start.sh logs     # Check container logs
docker compose ps   # Check container status
```

Common issues:
- Port already in use → change in `.env`
- SSL cert not found → check `SSL_CERT_FILE` path
- Docker not installed → `curl -fsSL https://get.docker.com | sh`

## Reset Everything

```bash
# Stop proxy
lray stop  # or Ctrl+C

# Delete generated files
rm -rf output/ config.json ca/

# Start fresh
lray setup
```
