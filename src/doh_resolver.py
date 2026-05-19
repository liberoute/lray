"""
DNS-over-HTTPS (DoH) resolver.

Resolves domain names using encrypted DNS queries over HTTPS,
bypassing local DNS censorship/filtering.

Supports multiple DoH providers with automatic failover:
  - Cloudflare (1.1.1.1)
  - Google (8.8.8.8)
  - Quad9 (9.9.9.9)

Usage:
    resolver = DoHResolver()
    ip = await resolver.resolve("example.com")
    # Returns "93.184.216.34" or None on failure
"""

import asyncio
import json
import logging
import ssl
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CONTEXT = ssl.create_default_context()

log = logging.getLogger("DoH")


@dataclass
class _CacheEntry:
    ip: str
    expires: float


@dataclass
class _DoHProvider:
    name: str
    host: str
    ip: str  # hardcoded IP to avoid chicken-and-egg DNS problem
    path: str = "/dns-query"
    failures: int = 0
    last_failure: float = 0.0


# Providers with hardcoded IPs (no DNS needed to reach them)
_DEFAULT_PROVIDERS = [
    _DoHProvider(name="Cloudflare", host="cloudflare-dns.com", ip="1.1.1.1"),
    _DoHProvider(name="Google", host="dns.google", ip="8.8.8.8"),
    _DoHProvider(name="Quad9", host="dns9.quad9.net", ip="9.9.9.9"),
]

# Cooldown after failure before retrying a provider
_FAILURE_COOLDOWN = 60.0  # seconds
_MAX_FAILURES = 3


class DoHResolver:
    """Async DNS-over-HTTPS resolver with caching and failover."""

    def __init__(self, providers: list[_DoHProvider] | None = None,
                 cache_ttl: int = 300,
                 timeout: float = 5.0):
        self._providers = providers or list(_DEFAULT_PROVIDERS)
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_ttl = cache_ttl
        self._timeout = timeout
        self._lock = asyncio.Lock()

    async def resolve(self, hostname: str, record_type: str = "A") -> str | None:
        """Resolve a hostname to an IP address using DoH.

        Returns the first A/AAAA record or None on failure.
        """
        hostname = hostname.lower().rstrip(".")

        # Check cache
        cache_key = f"{hostname}:{record_type}"
        entry = self._cache.get(cache_key)
        if entry and time.time() < entry.expires:
            return entry.ip

        # Try each provider
        for provider in self._available_providers():
            try:
                result = await self._query(provider, hostname, record_type)
                if result:
                    # Cache the result
                    self._cache[cache_key] = _CacheEntry(
                        ip=result, expires=time.time() + self._cache_ttl
                    )
                    # Reset failure count on success
                    provider.failures = 0
                    return result
            except Exception as e:
                provider.failures += 1
                provider.last_failure = time.time()
                log.debug("DoH query failed (%s): %s", provider.name, e)
                continue

        log.warning("All DoH providers failed for %s", hostname)
        return None

    def _available_providers(self) -> list[_DoHProvider]:
        """Return providers that aren't in cooldown."""
        now = time.time()
        available = []
        for p in self._providers:
            if p.failures >= _MAX_FAILURES:
                if now - p.last_failure < _FAILURE_COOLDOWN:
                    continue
                # Cooldown expired, give it another chance
                p.failures = 0
            available.append(p)

        # If all are in cooldown, try them all anyway
        return available if available else self._providers

    async def _query(self, provider: _DoHProvider,
                     hostname: str, record_type: str) -> str | None:
        """Send a DoH query using JSON API (RFC 8484 wireformat alternative)."""

        params = urlencode({"name": hostname, "type": record_type})
        path = f"{provider.path}?{params}"

        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {provider.host}\r\n"
            f"Accept: application/dns-json\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    provider.ip, 443, ssl=_SSL_CONTEXT,
                    server_hostname=provider.host,
                ),
                timeout=self._timeout,
            )
        except (asyncio.TimeoutError, OSError) as e:
            raise ConnectionError(f"Connect to {provider.name} failed: {e}")

        try:
            writer.write(request.encode())
            await writer.drain()

            # Read response
            response = b""
            try:
                response = await asyncio.wait_for(
                    reader.read(8192), timeout=self._timeout
                )
            except asyncio.TimeoutError:
                raise ConnectionError(f"Read timeout from {provider.name}")

            # Parse HTTP response
            if b"\r\n\r\n" not in response:
                return None

            _, body = response.split(b"\r\n\r\n", 1)

            # Handle chunked transfer encoding
            if b"transfer-encoding: chunked" in response.lower():
                body = self._decode_chunked(body)

            data = json.loads(body)

            # Extract answer
            if data.get("Status") != 0:  # NOERROR
                return None

            answers = data.get("Answer", [])
            for answer in answers:
                if answer.get("type") in (1, 28):  # A or AAAA
                    return answer.get("data")

            return None

        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    @staticmethod
    def _decode_chunked(data: bytes) -> bytes:
        """Simple chunked transfer-encoding decoder."""
        result = bytearray()
        while data:
            # Find chunk size line
            nl = data.find(b"\r\n")
            if nl < 0:
                break
            size_str = data[:nl].decode(errors="replace").strip()
            try:
                chunk_size = int(size_str, 16)
            except ValueError:
                break
            if chunk_size == 0:
                break
            data = data[nl + 2:]
            result.extend(data[:chunk_size])
            data = data[chunk_size + 2:]  # skip trailing \r\n
        return bytes(result)

    def cache_stats(self) -> dict:
        """Return cache statistics."""
        now = time.time()
        valid = sum(1 for e in self._cache.values() if now < e.expires)
        return {
            "total_cached": len(self._cache),
            "valid_entries": valid,
            "providers": [
                {"name": p.name, "failures": p.failures}
                for p in self._providers
            ],
        }

    def clear_cache(self):
        """Clear the DNS cache."""
        self._cache.clear()
