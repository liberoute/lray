# SSH Through the Proxy

## The Simple Way (CONNECT method)

lray supports HTTP CONNECT. SSH can tunnel through it directly:

```bash
ssh -o ProxyCommand="ncat --proxy 127.0.0.1:8085 --proxy-type http %h %p" root@your-server
```

### How it works

```
SSH client → CONNECT your-server:22 → lray proxy → GAS relay → VPS:22
```

DPI sees: traffic to `www.google.com`
Reality: SSH to your VPS

### Make it permanent (~/.ssh/config)

```
Host myserver
    HostName worker.kr0.site
    User root
    ProxyCommand ncat --proxy 127.0.0.1:8085 --proxy-type http %h %p
```

Then just: `ssh myserver`

### Windows (PuTTY)

1. Connection → Proxy
2. Type: HTTP
3. Host: 127.0.0.1
4. Port: 8085

### Windows (OpenSSH)

Install `ncat` from [Nmap](https://nmap.org/download.html), then:
```
ssh -o ProxyCommand="ncat --proxy 127.0.0.1:8085 --proxy-type http %h %p" root@server
```

Or use `connect.exe` (from Git for Windows):
```
ssh -o ProxyCommand="connect -H 127.0.0.1:8085 %h %p" root@server
```

## Alternative: WS Tunnel (direct to VPS)

If your VPS is **not** filtered (reachable directly), WS Tunnel is faster:

```json
// config.json
{
  "ws_tunnel_server": "wss://your-vps:9090",
  "ws_tunnels": [
    { "name": "SSH", "local_port": 2222, "remote_host": "127.0.0.1", "remote_port": 22 }
  ]
}
```

Then: `ssh root@localhost -p 2222`

**But:** If VPS is filtered, this won't work. Use the CONNECT method above.

## Alternative: TCP-over-Relay (through GAS)

For when VPS is filtered AND you need non-CONNECT TCP:

```json
{
  "tcp_tunnels": [
    { "name": "SSH", "local_port": 2222, "remote_host": "127.0.0.1", "remote_port": 22 }
  ]
}
```

Goes through GAS relay. Slower but works when everything is blocked.

## Which to use?

| Situation | Method |
|---|---|
| VPS reachable, SSH works | Don't need any of this |
| VPS reachable, SSH port blocked | WS Tunnel (fast) |
| VPS filtered, proxy running | **CONNECT method** (recommended) |
| Everything blocked | TCP-over-Relay (slowest, always works) |
