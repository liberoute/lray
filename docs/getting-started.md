# Getting Started

## Requirements

- Python 3.10+
- Google account (free)
- Optional: Cloudflare account (free)
- Optional: VPS with Docker

## Install

```bash
git clone https://github.com/liberoute/lray.git
cd lray
pip install -r requirements.txt
```

## Setup

```bash
lray setup
```

The wizard asks:
1. **Auth key** — generates a random secret
2. **VPS?** — if you have one, enter domain/IP
3. **Exit mode** — how traffic exits (see [Exit Modes](exit-modes.md))
4. **Proxy ports** — HTTP and SOCKS5
5. **TCP tunnels** — SSH, databases (optional)

After setup, `output/` folder contains everything ready to deploy.

## Deploy

### If you only have Google (mode: gas)

1. Go to [script.google.com](https://script.google.com)
2. New project → paste `output/gas/Code.gs` → Deploy as Web app
3. Copy Deployment ID → put in `config.json`
4. `lray start`

### If you have Google + Cloudflare (mode: cfw)

1. Deploy Code.gs (same as above)
2. Go to [Cloudflare Dashboard](https://dash.cloudflare.com) → Workers → Create
3. Paste `output/cloudflare-worker/worker.js` → Deploy
4. `lray start`

### If you have Google + VPS (mode: vps)

1. Deploy Code.gs (same as above)
2. Upload `output/self-hosted-exit/` to VPS → `./start.sh`
3. `lray start`

## Use

Set browser proxy to `127.0.0.1:8085` or use PAC: `http://127.0.0.1:8086/proxy.pac`

## Verify

```bash
lray test
```

Should show exit IP different from your real IP.
