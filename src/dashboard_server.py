"""
Dashboard HTTP server.

Serves the web dashboard UI and provides a JSON API for real-time stats.
Runs on the same port as the PAC server or a dedicated port.

Endpoints:
  GET /dashboard          → HTML dashboard page
  GET /dashboard/api/stats → JSON stats for the dashboard
"""

import asyncio
import json
import logging
import os
import time

log = logging.getLogger("Dashboard")

_DASHBOARD_HTML: str | None = None


def _load_html() -> str:
    """Load dashboard HTML from file (cached after first load)."""
    global _DASHBOARD_HTML
    if _DASHBOARD_HTML is None:
        html_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
        try:
            with open(html_path, "r", encoding="utf-8") as f:
                _DASHBOARD_HTML = f.read()
        except FileNotFoundError:
            _DASHBOARD_HTML = (
                "<html><body><h1>Dashboard file not found</h1>"
                "<p>Expected at: " + html_path + "</p></body></html>"
            )
    return _DASHBOARD_HTML


class DashboardServer:
    """Lightweight HTTP server for the monitoring dashboard."""

    def __init__(self, proxy_server, port: int = 8087):
        """
        Args:
            proxy_server: Reference to the ProxyServer instance for stats.
            port: Port to serve the dashboard on.
        """
        self._proxy = proxy_server
        self._port = port
        self._server: asyncio.base_events.Server | None = None
        self._started_at = time.time()
        self._total_requests = 0
        self._bytes_total = 0
        self._last_bytes = 0
        self._last_bytes_time = time.time()
        self._bytes_per_sec = 0.0
        self._latencies: list[float] = []
        self._max_latency_samples = 1000
        self._doh_queries = 0
        self._doh_fallbacks = 0

    def record_request(self, bytes_transferred: int = 0, latency_ms: float = 0,
                       is_doh_fallback: bool = False):
        """Called by proxy_server to record a completed request."""
        self._total_requests += 1
        self._bytes_total += bytes_transferred
        if latency_ms > 0:
            self._latencies.append(latency_ms)
            if len(self._latencies) > self._max_latency_samples:
                self._latencies = self._latencies[-self._max_latency_samples:]
        if is_doh_fallback:
            self._doh_fallbacks += 1

    def _compute_bytes_per_sec(self) -> float:
        now = time.time()
        elapsed = now - self._last_bytes_time
        if elapsed >= 1.0:
            self._bytes_per_sec = (self._bytes_total - self._last_bytes) / elapsed
            self._last_bytes = self._bytes_total
            self._last_bytes_time = now
        return self._bytes_per_sec

    def _get_stats(self) -> dict:
        """Gather all stats into a JSON-serializable dict."""
        proxy = self._proxy

        # Cache stats
        cache_hits = 0
        cache_misses = 0
        if hasattr(proxy, "_cache"):
            cache_hits = proxy._cache.hits
            cache_misses = proxy._cache.misses

        # Active connections
        active_conns = len(proxy._client_tasks) if hasattr(proxy, "_client_tasks") else 0

        # Latency stats
        avg_lat = 0
        min_lat = 0
        max_lat = 0
        if self._latencies:
            avg_lat = round(sum(self._latencies) / len(self._latencies))
            min_lat = round(min(self._latencies))
            max_lat = round(max(self._latencies))

        # Top hosts from fronter stats
        top_hosts = []
        if hasattr(proxy, "fronter") and hasattr(proxy.fronter, "_host_stats"):
            stats = proxy.fronter._host_stats
            sorted_hosts = sorted(
                stats.items(), key=lambda x: x[1].requests, reverse=True
            )[:15]
            for host, stat in sorted_hosts:
                route = "relay"
                if hasattr(proxy, "_is_bypassed") and proxy._is_bypassed(host):
                    route = "direct"
                top_hosts.append({
                    "host": host,
                    "requests": stat.requests,
                    "bytes": stat.bytes,
                    "route": route,
                })

        # DoH stats
        doh_info = {"enabled": False}
        if hasattr(proxy, "_doh") and proxy._doh:
            doh_info = {
                "enabled": True,
                "cached": len(proxy._doh._cache),
                "queries": self._doh_queries,
                "fallbacks": self._doh_fallbacks,
                "providers": [
                    {"name": p.name, "failures": p.failures}
                    for p in proxy._doh._providers
                ],
            }

        # Config info
        script_ids = getattr(proxy.fronter, "_script_ids", [])
        config_info = {
            "host": proxy.host,
            "port": proxy.port,
            "socks5": f"{proxy.socks_host}:{proxy.socks_port}" if proxy.socks_enabled else None,
            "pac": f"http://{proxy.host}:{proxy._pac_port}/proxy.pac" if proxy._pac_enabled else None,
            "front_domain": getattr(proxy.fronter, "sni_host", "—"),
            "google_ip": getattr(proxy.fronter, "connect_host", "—"),
            "script_count": len(script_ids) if isinstance(script_ids, list) else 1,
            "doh_enabled": hasattr(proxy, "_doh") and proxy._doh is not None,
            "mode": "apps_script",
        }

        from constants import __version__

        return {
            "version": __version__,
            "uptime_seconds": int(time.time() - self._started_at),
            "started_at": time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(self._started_at)
            ),
            "total_requests": self._total_requests,
            "active_connections": active_conns,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "total_bytes": self._bytes_total,
            "bytes_per_sec": round(self._compute_bytes_per_sec()),
            "avg_latency_ms": avg_lat,
            "min_latency_ms": min_lat,
            "max_latency_ms": max_lat,
            "top_hosts": top_hosts,
            "config": config_info,
            "doh": doh_info,
        }

    async def _handle_request(self, reader: asyncio.StreamReader,
                              writer: asyncio.StreamWriter):
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=10)
            if not request_line:
                writer.close()
                return

            # Read headers
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5)
                if line in (b"\r\n", b"\n", b""):
                    break

            request_str = request_line.decode(errors="replace")
            parts = request_str.split()
            path = parts[1] if len(parts) > 1 else "/"

            if path in ("/dashboard", "/dashboard/", "/"):
                body = _load_html().encode("utf-8")
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: text/html; charset=utf-8\r\n"
                    b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                    b"Cache-Control: no-cache\r\n"
                    b"\r\n" + body
                )
            elif path == "/dashboard/api/stats":
                stats = self._get_stats()
                body = json.dumps(stats).encode("utf-8")
                response = (
                    b"HTTP/1.1 200 OK\r\n"
                    b"Content-Type: application/json\r\n"
                    b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                    b"Access-Control-Allow-Origin: *\r\n"
                    b"Cache-Control: no-cache\r\n"
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
            log.debug("Dashboard request error: %s", e)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def start(self, host: str = "127.0.0.1"):
        """Start the dashboard server."""
        try:
            self._server = await asyncio.start_server(
                self._handle_request, host, self._port
            )
            log.info(
                "Dashboard on http://%s:%d/dashboard", host, self._port
            )
            return self._server
        except OSError as e:
            log.warning("Dashboard failed to start on port %d: %s", self._port, e)
            return None

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
