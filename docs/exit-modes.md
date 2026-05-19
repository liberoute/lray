# Exit Modes

## Overview

| Mode | Path | Exit IP | Cost | TCP Tunnel |
|------|------|---------|------|------------|
| `gas` | GAS → target | Google | Free | ❌ |
| `cfw` | GAS → Worker → target | Cloudflare (rotating) | Free | ❌ |
| `vps` | GAS → VPS → target | Your VPS (fixed) | VPS cost | ✅ |
| `cfw_vps` | GAS → Worker → VPS → target | Your VPS (fixed) | VPS cost | ✅ |

## Mode 1: gas

```
Client → Proxy → Google CDN → GAS → UrlFetchApp → target
```

- **Simplest** — only need a Google account
- GAS fetches the target directly
- Exit IP = Google's servers
- Some sites block Google IPs
- 20,000 requests/day limit
- No TCP tunnel support (HTTP only)

**Best for:** Quick setup, light browsing

## Mode 2: cfw

```
Client → Proxy → Google CDN → GAS → Cloudflare Worker → target
```

- Need Google + free Cloudflare account
- Worker does the actual fetch
- Exit IP = Cloudflare (rotates per request)
- CAPTCHA issues on some sites (rotating IP)
- 100,000 requests/day (Worker limit)

**Best for:** More capacity than gas, still free

## Mode 3: vps

```
Client → Proxy → Google CDN → GAS → Your VPS → target
```

- Need Google + VPS ($3-5/month)
- VPS does the fetch
- Exit IP = your VPS (fixed, stable)
- No CAPTCHA issues
- TCP tunnel works (SSH, databases)
- Best performance (one less hop than cfw_vps)

**Best for:** Serious use, SSH access, CAPTCHA-protected sites

## Mode 4: cfw_vps

```
Client → Proxy → Google CDN → GAS → Worker → VPS → target
```

- Need Google + Cloudflare + VPS
- Worker forwards to VPS
- Exit IP = your VPS (fixed)
- Extra redundancy (if VPS is down, Worker can fallback to direct)
- Slightly more latency (extra hop)

**Best for:** Maximum reliability, enterprise use

## Choosing

```
Do you have a VPS?
├── No → Do sites block you?
│        ├── No → gas
│        └── Yes → cfw
└── Yes → Do you need SSH/TCP tunnel?
         ├── No → vps (simplest with VPS)
         └── Yes → vps (SSH works via CONNECT proxy)
```

## SSH Through Any Mode

If you have a VPS and it's your exit node, SSH works through the HTTP proxy's CONNECT method:

```bash
ssh -o ProxyCommand="ncat --proxy 127.0.0.1:8085 --proxy-type http %h %p" root@your-vps
```

No special tunnel setup needed. The proxy handles CONNECT to port 22.
