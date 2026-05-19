# Dashboards

## Local Dashboard

**URL:** `http://127.0.0.1:8087/dashboard`

Shows:
- Total requests, active connections
- Cache hit rate
- Bandwidth, latency
- Traffic chart (last 60s)
- Top hosts
- DoH status
- Configuration

No auth needed (localhost only).

## Server Dashboard (Upstream Forwarder)

**URL:** `https://your-domain:port/dashboard`

Shows:
- Requests (success/fail)
- Latency, bandwidth
- Memory usage
- Success rate bar
- Recent activity log

**Auth:** Basic Auth (user/pass from `.env`)

## Worker Dashboard

**URL:** `https://your-worker.workers.dev/dashboard`

Shows:
- Status, worker URL
- Forwarder config
- Endpoints

**Auth:** Cookie-based login (enter AUTH_KEY)

## GAS Dashboard

**URL:** Your GAS deployment URL (GET request)

Shows:
- Status, mode
- Total requests, errors
- **Quota usage** (progress bar: used/remaining/reset time)
- Worker list

**Auth:** Login page (enter AUTH_KEY)

## Quota Monitoring

GAS dashboard shows:
```
Daily Quota (15,234 / 20,000)
████████████████░░░░░░  76%
4,766 remaining • resets in 14h 23m
```

Client can query quota:
```json
POST to GAS: { "k": "AUTH_KEY", "cmd": "quota" }
→ { "quota_used": 15234, "quota_remaining": 4766, "quota_reset_at": ... }
```
