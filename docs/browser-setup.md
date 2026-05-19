# Browser Setup

## Option 1: SwitchyOmega (Recommended)

[SwitchyOmega](https://github.com/nicehash/SwitchyOmega) is a Chrome/Edge extension for easy proxy management.

### PAC Profile (auto-config)

1. Install SwitchyOmega from [Chrome Web Store](https://chromewebstore.google.com/detail/proxy-switchyomega/padekgcemlokbadohgkifijomclgjgif)
2. Click SwitchyOmega icon → Options
3. New Profile → **PAC Profile**
4. PAC URL: `http://127.0.0.1:8086/proxy.pac`
5. Apply Changes
6. Click icon → select your PAC profile

PAC auto-routes: local traffic direct, everything else through proxy.

### Manual Proxy Profile

1. New Profile → **Proxy Profile**
2. Protocol: `HTTP`
3. Server: `127.0.0.1`
4. Port: `8085`
5. Apply Changes

### SOCKS5 Profile

1. New Profile → **Proxy Profile**
2. Protocol: `SOCKS5`
3. Server: `127.0.0.1`
4. Port: `1080`
5. Apply Changes

## Option 2: FoxyProxy (Firefox)

1. Install [FoxyProxy](https://addons.mozilla.org/en-US/firefox/addon/foxyproxy-standard/)
2. Options → Add Proxy
3. Type: HTTP, Host: `127.0.0.1`, Port: `8085`
4. Save → Enable

## Option 3: System Proxy (all browsers)

### Windows
Settings → Network → Proxy → Manual:
- Address: `127.0.0.1`
- Port: `8085`

Or PAC: Settings → Proxy → Use setup script → `http://127.0.0.1:8086/proxy.pac`

### macOS
System Preferences → Network → Advanced → Proxies:
- Web Proxy (HTTP): `127.0.0.1:8085`
- Or: Automatic Proxy Configuration → `http://127.0.0.1:8086/proxy.pac`

### Linux
```bash
export http_proxy="http://127.0.0.1:8085"
export https_proxy="http://127.0.0.1:8085"
export all_proxy="socks5://127.0.0.1:1080"
```

## Option 4: Mobile (Phone/Tablet)

If LAN sharing is enabled (`lan_sharing: true`):

1. Find your PC's IP (e.g. `192.168.1.8`)
2. On phone: WiFi settings → Proxy → Manual
   - Host: `192.168.1.8`
   - Port: `8085`
3. Or: PAC URL → `http://192.168.1.8:8086/proxy.pac`

## Which to choose?

| Method | Best for |
|---|---|
| SwitchyOmega PAC | Chrome/Edge, easy toggle on/off |
| SwitchyOmega Manual | Chrome/Edge, full control |
| FoxyProxy | Firefox |
| System Proxy | All apps (not just browser) |
| Mobile | Phone/tablet on same WiFi |
