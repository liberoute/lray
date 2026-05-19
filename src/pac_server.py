"""
PAC (Proxy Auto-Configuration) file server.

Serves a PAC file that browsers can use to automatically route traffic
through this proxy. No manual proxy configuration needed — just point
the browser's "automatic proxy configuration URL" to:

    http://<proxy_host>:<pac_port>/proxy.pac

The PAC file dynamically includes bypass rules from config so that
local/LAN traffic goes direct while everything else uses the proxy.
"""

import asyncio
import logging
from urllib.parse import urlparse

log = logging.getLogger("PAC")


def generate_pac(proxy_host: str, proxy_port: int,
                 socks_port: int | None,
                 bypass_hosts: list[str] | None = None) -> str:
    """Generate a PAC file string based on current proxy configuration."""

    bypass_rules = bypass_hosts or []

    # Build shExpMatch conditions for bypass hosts
    bypass_conditions = []
    for rule in bypass_rules:
        rule = rule.strip()
        if not rule:
            continue
        if rule.startswith("."):
            # Suffix rule: .local → *.local
            bypass_conditions.append(
                f'        if (shExpMatch(host, "*{rule}")) return direct;'
            )
        else:
            # Exact match
            bypass_conditions.append(
                f'        if (host === "{rule}") return direct;'
            )

    bypass_block = "\n".join(bypass_conditions) if bypass_conditions else ""

    # Determine proxy string
    if socks_port:
        proxy_string = f"SOCKS5 {proxy_host}:{socks_port}; PROXY {proxy_host}:{proxy_port}; DIRECT"
    else:
        proxy_string = f"PROXY {proxy_host}:{proxy_port}; DIRECT"

    pac = f"""function FindProxyForURL(url, host) {{
    var direct = "DIRECT";
    var proxy = "{proxy_string}";

    // Localhost always direct
    if (host === "localhost" || host === "127.0.0.1" || host === "::1") return direct;

    // Private/LAN ranges always direct
    if (isInNet(host, "10.0.0.0", "255.0.0.0")) return direct;
    if (isInNet(host, "172.16.0.0", "255.240.0.0")) return direct;
    if (isInNet(host, "192.168.0.0", "255.255.0.0")) return direct;
    if (isInNet(host, "169.254.0.0", "255.255.0.0")) return direct;

    // Bypass rules from config
{bypass_block}

    // Everything else goes through proxy
    return proxy;
}}
"""
    return pac.strip()


class PACServer:
    """Simple HTTP server that serves the PAC file."""

    def __init__(self, proxy_host: str, proxy_port: int,
                 socks_port: int | None = None,
                 pac_port: int = 8086,
                 bypass_hosts: list[str] | None = None):
        self.proxy_host = proxy_host
        self.proxy_port = proxy_port
        self.socks_port = socks_port
        self.pac_port = pac_port
        self.bypass_hosts = bypass_hosts or []
        self._server: asyncio.base_events.Server | None = None

        # Pre-generate PAC content
        self._pac_content = generate_pac(
            proxy_host, proxy_port, socks_port, bypass_hosts
        )

    async def _handle_request(self, reader: asyncio.StreamReader,
                              writer: asyncio.StreamWriter):
        try:
            # Read the HTTP request line
            request_line = await asyncio.wait_for(
                reader.readline(), timeout=10
            )
            if not request_line:
                writer.close()
                return

            # Read remaining headers (discard them)
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5)
                if line in (b"\r\n", b"\n", b""):
                    break

            request_str = request_line.decode(errors="replace")
            parts = request_str.split()
            method = parts[0] if parts else ""
            path = parts[1] if len(parts) > 1 else "/"

            if method == "GET" and path in ("/proxy.pac", "/wpad.dat", "/"):
                body = self._pac_content.encode()
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/x-ns-proxy-autoconfig\r\n"
                    b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                    b"Cache-Control: no-cache\r\n"
                    b"Access-Control-Allow-Origin: *\r\n"
                    b"\r\n" + body
                )
            elif method == "GET" and path == "/info":
                import json
                info = {
                    "proxy_host": self.proxy_host,
                    "proxy_port": self.proxy_port,
                    "socks_port": self.socks_port,
                    "pac_url": f"http://{self.proxy_host}:{self.pac_port}/proxy.pac",
                    "bypass_hosts": self.bypass_hosts,
                }
                body = json.dumps(info, indent=2).encode()
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                    b"\r\n" + body
                )
            else:
                body = b"Not Found"
                response = (
                    b"HTTP/1.1 404 Not Found\r\n"
                    b"Content-Length: 9\r\n"
                    b"\r\n" + body
                )

            writer.write(response)
            await writer.drain()

        except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError):
            pass
        except Exception as e:
            log.debug("PAC request error: %s", e)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self, host: str = "127.0.0.1"):
        """Start the PAC file server."""
        try:
            self._server = await asyncio.start_server(
                self._handle_request, host, self.pac_port
            )
            log.info("PAC file server on http://%s:%d/proxy.pac", host, self.pac_port)
            return self._server
        except OSError as e:
            log.warning("PAC server failed to start on port %d: %s", self.pac_port, e)
            return None

    async def stop(self):
        """Stop the PAC file server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
