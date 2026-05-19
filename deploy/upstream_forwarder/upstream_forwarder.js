// Upstream Forwarder — single-file Node 18+ HTTP server.
//
// Purpose: Provide a stable exit IP for the Cloudflare Worker relay so
// CAPTCHA tokens (Turnstile, reCAPTCHA, hCaptcha) bound to the solving
// IP survive verification on the target site.
//
// Required env:
//   AUTH_KEY  — must match the Worker's UPSTREAM_AUTH_KEY (>= 32 chars)
//
// Optional env:
//   PORT             — listen port (default 8787)
//   HOST             — listen host (default 0.0.0.0)
//   MAX_BODY_MB      — max request body in MB (default 50)
//   FETCH_TIMEOUT_MS — timeout for outbound fetch in ms (default 30000)
//   RATE_LIMIT_RPM   — max requests per minute per IP (default 300, 0=unlimited)
//   LOG_REQUESTS     — log each request: "true" or "false" (default "true")
//   CF_IP_WHITELIST  — only allow Cloudflare IPs: "true" or "false" (default "false")
//
// Wire protocol:
//   POST /fwd  body: { u, m, h, b, ct, r }   →  { s, h, b }  or  { e }
//   GET  /          → status page
//   GET  /stats     → JSON metrics
//   GET  /health    → health check (for Docker/load balancers)

"use strict";

const http = require("http");
const fs = require("fs");
const path = require("path");

// ─── Configuration ───────────────────────────────────────────────────────────

const AUTH_KEY          = process.env.AUTH_KEY || "";
const PORT             = parseInt(process.env.PORT, 10) || 8787;
const HOST             = process.env.HOST || "0.0.0.0";
const MAX_BODY_BYTES   = (parseInt(process.env.MAX_BODY_MB, 10) || 50) * 1024 * 1024;
const FETCH_TIMEOUT_MS = parseInt(process.env.FETCH_TIMEOUT_MS, 10) || 30000;
const RATE_LIMIT_RPM   = parseInt(process.env.RATE_LIMIT_RPM, 10) || 300;
const LOG_REQUESTS     = (process.env.LOG_REQUESTS || "true") !== "false";
const CF_IP_WHITELIST  = (process.env.CF_IP_WHITELIST || "false") === "true";
// Optional: route outbound fetch through an external proxy
// Format: http://user:pass@host:port or socks5://host:port
const EXIT_PROXY_URL   = process.env.EXIT_PROXY_URL || "";
// Dashboard basic auth
const DASHBOARD_USER   = process.env.DASHBOARD_USER || "";
const DASHBOARD_PASS   = process.env.DASHBOARD_PASS || "";

if (!AUTH_KEY || AUTH_KEY.length < 32) {
    console.error("FATAL: AUTH_KEY env var missing or shorter than 32 chars.");
    process.exit(1);
}

// ─── Cloudflare IP Ranges ────────────────────────────────────────────────────
// https://www.cloudflare.com/ips/
// Hardcoded as fallback. Auto-updated from CF API on startup if CF_IP_WHITELIST=true.

let CF_IPV4_RANGES = [
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22",
    "103.31.4.0/22", "141.101.64.0/18", "108.162.192.0/18",
    "190.93.240.0/20", "188.114.96.0/20", "197.234.240.0/22",
    "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22",
];

// Auto-fetch latest CF IPs on startup
if (CF_IP_WHITELIST) {
    (async () => {
        try {
            const resp = await fetch("https://www.cloudflare.com/ips-v4");
            if (resp.ok) {
                const text = await resp.text();
                const ranges = text.trim().split("\n").filter(l => l.includes("/"));
                if (ranges.length > 5) {
                    CF_IPV4_RANGES = ranges;
                    log("INFO", `Updated CF IP ranges: ${ranges.length} CIDRs`);
                }
            }
        } catch (e) {
            log("INFO", "Using hardcoded CF IP ranges (fetch failed)");
        }
    })();
}

function ipToLong(ip) {
    return ip.split(".").reduce((acc, octet) => (acc << 8) + parseInt(octet, 10), 0) >>> 0;
}

function isInCidr(ip, cidr) {
    const [range, bits] = cidr.split("/");
    const mask = ~(2 ** (32 - parseInt(bits, 10)) - 1) >>> 0;
    return (ipToLong(ip) & mask) === (ipToLong(range) & mask);
}

function isCloudflareIp(ip) {
    // Strip IPv6 prefix for mapped IPv4
    const cleanIp = ip.replace(/^::ffff:/, "");
    return CF_IPV4_RANGES.some(cidr => isInCidr(cleanIp, cidr));
}

// ─── Rate Limiter (fixed window per IP) ──────────────────────────────────────

const rateBuckets = new Map(); // ip → { count, resetAt }

function isRateLimited(ip) {
    if (RATE_LIMIT_RPM === 0) return false;

    const now = Date.now();
    let bucket = rateBuckets.get(ip);

    if (!bucket || now > bucket.resetAt) {
        bucket = { count: 0, resetAt: now + 60000 };
        rateBuckets.set(ip, bucket);
    }

    bucket.count++;
    return bucket.count > RATE_LIMIT_RPM;
}

// Cleanup stale buckets every 5 minutes
setInterval(() => {
    const now = Date.now();
    for (const [ip, bucket] of rateBuckets) {
        if (now > bucket.resetAt) rateBuckets.delete(ip);
    }
}, 300000).unref();

// ─── Metrics ─────────────────────────────────────────────────────────────────

const metrics = {
    startedAt: new Date().toISOString(),
    totalRequests: 0,
    successfulFetches: 0,
    failedFetches: 0,
    rateLimited: 0,
    unauthorized: 0,
    totalBytesOut: 0,
    avgLatencyMs: 0,
    _latencySum: 0,
    _latencyCount: 0,
};

function recordLatency(ms) {
    metrics._latencySum += ms;
    metrics._latencyCount++;
    metrics.avgLatencyMs = Math.round(metrics._latencySum / metrics._latencyCount);
}

// ─── Logging ─────────────────────────────────────────────────────────────────

const LOG_BUFFER = [];
const LOG_BUFFER_MAX = 200;

function log(level, msg, meta) {
    const ts = new Date().toISOString();
    const base = `[${ts}] [${level}] ${msg}`;
    const full = meta
        ? base + " " + (typeof meta === "string" ? meta : JSON.stringify(meta))
        : base;
    console.log(full);

    // Keep in buffer for dashboard
    LOG_BUFFER.push(full);
    if (LOG_BUFFER.length > LOG_BUFFER_MAX) LOG_BUFFER.shift();
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const SKIP_HEADERS = new Set([
    "host", "connection", "content-length",
    "transfer-encoding", "proxy-connection", "proxy-authorization"
]);

function getClientIp(req) {
    return req.headers["x-forwarded-for"]?.split(",")[0]?.trim()
        || req.headers["x-real-ip"]
        || req.socket.remoteAddress
        || "unknown";
}

function readBody(req, maxBytes) {
    return new Promise((resolve, reject) => {
        const chunks = [];
        let size = 0;

        req.on("data", (chunk) => {
            size += chunk.length;
            if (size > maxBytes) {
                req.destroy();
                reject(new Error("body_too_large"));
                return;
            }
            chunks.push(chunk);
        });

        req.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
        req.on("error", reject);
    });
}

function sendJson(res, status, obj) {
    const body = JSON.stringify(obj);
    res.writeHead(status, {
        "content-type": "application/json",
        "content-length": Buffer.byteLength(body),
    });
    res.end(body);
}

// ─── Pages ───────────────────────────────────────────────────────────────────

const STATUS_PAGE =
    "<!DOCTYPE html><html><head><title>Forwarder Active</title>" +
    '<meta name="viewport" content="width=device-width,initial-scale=1"></head>' +
    '<body style="font-family:system-ui,sans-serif;max-width:600px;margin:40px auto;padding:0 20px">' +
    '<h1>Forwarder <span style="color:#16a34a">Active</span> ✓</h1>' +
    "<p>Upstream forwarder is running and accepting requests.</p>" +
    '<p style="color:#666;font-size:0.9em">Endpoints: POST /fwd | GET /stats | GET /health</p>' +
    "</body></html>";

// ─── Dashboard Auth ──────────────────────────────────────────────────────────

function checkDashboardAuth(req, res) {
    // If no password set, dashboard is open
    if (!DASHBOARD_PASS) return true;

    const authHeader = req.headers["authorization"] || "";
    if (!authHeader.startsWith("Basic ")) {
        res.writeHead(401, {
            "www-authenticate": 'Basic realm="Dashboard"',
            "content-type": "text/plain",
        });
        res.end("Authentication required");
        return false;
    }

    const decoded = Buffer.from(authHeader.slice(6), "base64").toString();
    const [user, pass] = decoded.split(":", 2);

    if (user === DASHBOARD_USER && pass === DASHBOARD_PASS) {
        return true;
    }

    res.writeHead(401, {
        "www-authenticate": 'Basic realm="Dashboard"',
        "content-type": "text/plain",
    });
    res.end("Invalid credentials");
    return false;
}

// ─── Request Handler ─────────────────────────────────────────────────────────

async function handleRequest(req, res) {
    const startTime = Date.now();
    const clientIp = getClientIp(req);

    // Don't count dashboard/stats/health requests in metrics
    const isDashboardReq = req.url && (
        req.url.startsWith("/dashboard") ||
        req.url === "/stats" ||
        req.url === "/health" ||
        req.url === "/" ||
        req.url === ""
    );

    if (!isDashboardReq) {
        metrics.totalRequests++;
    }

    // ── GET endpoints ────────────────────────────────────────────────────────

    if (req.method === "GET") {
        switch (req.url) {
            case "/":
            case "":
                res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
                res.end(STATUS_PAGE);
                return;

            case "/health":
                sendJson(res, 200, { status: "ok", uptime: process.uptime() | 0 });
                return;

            case "/stats":
                sendJson(res, 200, {
                    uptime_seconds: process.uptime() | 0,
                    started_at: metrics.startedAt,
                    total_requests: metrics.totalRequests,
                    successful_fetches: metrics.successfulFetches,
                    failed_fetches: metrics.failedFetches,
                    rate_limited: metrics.rateLimited,
                    unauthorized: metrics.unauthorized,
                    total_bytes_out: metrics.totalBytesOut,
                    avg_latency_ms: metrics.avgLatencyMs,
                    memory_mb: Math.round(process.memoryUsage().rss / 1024 / 1024),
                    active_rate_buckets: rateBuckets.size,
                });
                return;

            case "/dashboard":
            case "/dashboard/": {
                if (!checkDashboardAuth(req, res)) return;
                const htmlPath = path.join(__dirname, "dashboard.html");
                try {
                    const html = fs.readFileSync(htmlPath, "utf8");
                    res.writeHead(200, { "content-type": "text/html; charset=utf-8", "cache-control": "no-cache" });
                    res.end(html);
                } catch (e) {
                    res.writeHead(404, { "content-type": "text/plain" });
                    res.end("Dashboard HTML not found: " + htmlPath);
                }
                return;
            }

            case "/dashboard/logs":
                if (!checkDashboardAuth(req, res)) return;
                sendJson(res, 200, LOG_BUFFER.slice(-100));
                return;

            default:
                sendJson(res, 404, { e: "not found" });
                return;
        }
    }

    // ── Only POST /fwd from here ─────────────────────────────────────────────

    if (req.method !== "POST" || req.url !== "/fwd") {
        sendJson(res, 404, { e: "not found" });
        return;
    }

    // Cloudflare IP whitelist
    if (CF_IP_WHITELIST && !isCloudflareIp(clientIp)) {
        if (LOG_REQUESTS) log("WARN", `Blocked non-CF IP: ${clientIp}`);
        sendJson(res, 403, { e: "forbidden" });
        return;
    }

    // Rate limit
    if (isRateLimited(clientIp)) {
        metrics.rateLimited++;
        if (LOG_REQUESTS) log("WARN", `Rate limited: ${clientIp}`);
        sendJson(res, 429, { e: "rate limited" });
        return;
    }

    // Auth
    if (req.headers["x-upstream-auth"] !== AUTH_KEY) {
        metrics.unauthorized++;
        if (LOG_REQUESTS) log("WARN", `Unauthorized: ${clientIp}`);
        sendJson(res, 401, { e: "unauthorized" });
        return;
    }

    // Read body
    let raw;
    try {
        raw = await readBody(req, MAX_BODY_BYTES);
    } catch (err) {
        if (err.message === "body_too_large") {
            sendJson(res, 413, { e: "body too large", max_mb: MAX_BODY_BYTES / 1024 / 1024 });
            return;
        }
        sendJson(res, 400, { e: "read error" });
        return;
    }

    // Parse
    let body;
    try {
        body = JSON.parse(raw);
    } catch (_) {
        sendJson(res, 400, { e: "invalid json" });
        return;
    }

    // ── TCP Tunnel commands ──────────────────────────────────────────────────
    if (body.tunnel) {
        await handleTcpTunnel(body, res);
        return;
    }

    // ── UDP Relay ────────────────────────────────────────────────────────────
    if (body.udp) {
        await handleUdpRelay(body, res);
        return;
    }

    // ── MTProto Relay ────────────────────────────────────────────────────────
    if (body.cmd === "mtproto") {
        // Forward to exit node (upstream_forwarder is a middle hop)
        // In cfw_vps mode: Worker → Forwarder → DC
        // Reuse the same handler as self-hosted-exit
        await handleMTProtoRelay(body, res);
        return;
    }

    // Validate URL
    if (!body.u || typeof body.u !== "string" || !/^https?:\/\//i.test(body.u)) {
        sendJson(res, 400, { e: "bad url" });
        return;
    }

    // Build headers
    const headers = {};
    if (body.h && typeof body.h === "object") {
        for (const [k, v] of Object.entries(body.h)) {
            if (typeof v !== "string") continue;
            if (SKIP_HEADERS.has(k.toLowerCase())) continue;
            headers[k] = v;
        }
    }
    headers["x-fwd-hop"] = "1";

    // Fetch options
    const fetchOptions = {
        method: (body.m || "GET").toUpperCase(),
        headers,
        redirect: body.r === false ? "manual" : "follow",
        signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    };

    if (body.b) {
        fetchOptions.body = Buffer.from(body.b, "base64");
    }

    // Use proxy if configured (from env or per-request from Worker)
    const proxyUrl = body._proxy || EXIT_PROXY_URL;
    if (proxyUrl) {
        try {
            const { ProxyAgent } = require("undici");
            fetchOptions.dispatcher = new ProxyAgent(proxyUrl);
        } catch (e) {
            // undici ProxyAgent not available — try without proxy
            if (LOG_REQUESTS) log("WARN", `Proxy agent unavailable: ${e.message}, fetching direct`);
        }
    }

    // Execute fetch
    let resp;
    try {
        resp = await fetch(body.u, fetchOptions);
    } catch (err) {
        metrics.failedFetches++;
        const reason = err.name === "TimeoutError"
            ? `fetch timeout (${FETCH_TIMEOUT_MS}ms)`
            : "fetch failed: " + String(err?.message || err);

        if (LOG_REQUESTS) log("ERROR", `${fetchOptions.method} ${body.u} → FAILED`, { ip: clientIp, error: reason });
        sendJson(res, 502, { e: reason });
        return;
    }

    // Read response
    const buf = Buffer.from(await resp.arrayBuffer());
    const responseHeaders = {};
    resp.headers.forEach((v, k) => { responseHeaders[k] = v; });

    metrics.successfulFetches++;
    metrics.totalBytesOut += buf.length;

    const elapsed = Date.now() - startTime;
    recordLatency(elapsed);

    if (LOG_REQUESTS) {
        log("INFO", `${fetchOptions.method} ${body.u} → ${resp.status} (${formatBytes(buf.length)}, ${elapsed}ms)`, { ip: clientIp });
    }

    sendJson(res, 200, {
        s: resp.status,
        h: responseHeaders,
        b: buf.toString("base64")
    });
}

function formatBytes(bytes) {
    if (bytes < 1024) return bytes + "B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + "KB";
    return (bytes / 1048576).toFixed(1) + "MB";
}

// ─── Server ──────────────────────────────────────────────────────────────────

const SSL_CERT_FILE = process.env.SSL_CERT_FILE || "";
const SSL_KEY_FILE = process.env.SSL_KEY_FILE || "";
const HTTP_PORT = parseInt(process.env.HTTP_PORT, 10) || 0;
const PROTOCOL_MODE = process.env.PROTOCOL_MODE || "auto";

const requestHandler = async (req, res) => {
    try {
        await handleRequest(req, res);
    } catch (err) {
        log("ERROR", "Unhandled error", { error: String(err?.message || err) });
        if (!res.headersSent) {
            sendJson(res, 500, { e: "internal error" });
        }
    }
};

let server;
let httpServer;
let useHttps = false;
let useHttp = false;

if (PROTOCOL_MODE === "both") {
    useHttps = !!(SSL_CERT_FILE && SSL_KEY_FILE);
    useHttp = true;
} else if (PROTOCOL_MODE === "https") {
    useHttps = true;
} else if (PROTOCOL_MODE === "http") {
    useHttp = true;
} else {
    useHttps = !!(SSL_CERT_FILE && SSL_KEY_FILE);
    useHttp = !useHttps || !!HTTP_PORT;
}

if (useHttps && SSL_CERT_FILE && SSL_KEY_FILE) {
    const https = require("https");
    try {
        server = https.createServer({
            cert: fs.readFileSync(SSL_CERT_FILE),
            key: fs.readFileSync(SSL_KEY_FILE),
        }, requestHandler);
        log("INFO", `TLS enabled: ${SSL_CERT_FILE}`);
    } catch (e) {
        log("WARN", `TLS failed: ${e.message}. Falling back to HTTP.`);
        useHttps = false;
        useHttp = true;
    }
}

if (useHttp && !useHttps) {
    server = http.createServer(requestHandler);
} else if (useHttp && useHttps) {
    httpServer = http.createServer(requestHandler);
}

server.keepAliveTimeout = 120000;
server.headersTimeout = 125000;

server.listen(PORT, HOST, () => {
    const proto = useHttps ? "https" : "http";
    log("INFO", `━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
    log("INFO", `  Upstream Forwarder started`);
    log("INFO", `  ${proto}://${HOST}:${PORT}`);
    if (httpServer) log("INFO", `  http://${HOST}:${HTTP_PORT || 80}`);
    log("INFO", `  Max body: ${MAX_BODY_BYTES / 1024 / 1024}MB`);
    log("INFO", `  Fetch timeout: ${FETCH_TIMEOUT_MS}ms`);
    log("INFO", `  Rate limit: ${RATE_LIMIT_RPM === 0 ? "unlimited" : RATE_LIMIT_RPM + " req/min/ip"}`);
    log("INFO", `  CF IP whitelist: ${CF_IP_WHITELIST ? "ON" : "OFF"}`);
    log("INFO", `━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
});

if (httpServer) {
    httpServer.keepAliveTimeout = 120000;
    httpServer.headersTimeout = 125000;
    httpServer.listen(HTTP_PORT || 80, HOST);
}

// ─── TCP Tunnel ──────────────────────────────────────────────────────────────

const net = require("net");
const dgram = require("dgram");

const tcpSessions = new Map();

setInterval(() => {
    const now = Date.now();
    for (const [sid, session] of tcpSessions) {
        if (now - session.lastActivity > 300000) {
            session.socket.destroy();
            tcpSessions.delete(sid);
        }
    }
}, 60000).unref();

// ─── MTProto Relay ───────────────────────────────────────────────────────────

const TELEGRAM_DCS_FWD = {
    1: { host: "149.154.175.50", port: 443 },
    2: { host: "149.154.167.50", port: 443 },
    3: { host: "149.154.175.100", port: 443 },
    4: { host: "149.154.167.91", port: 443 },
    5: { host: "91.108.56.100", port: 443 },
};

const dcConnectionsFwd = new Map();

async function handleMTProtoRelay(body, res) {
    const dc = body.dc || 2;
    const dataB64 = body.data || "";
    const compressed = body.compressed || false;

    if (!dataB64) { sendJson(res, 400, { e: "no data" }); return; }

    const dcInfo = TELEGRAM_DCS_FWD[Math.abs(dc)] || TELEGRAM_DCS_FWD[2];

    try {
        let data = Buffer.from(dataB64, "base64");
        if (compressed) {
            const zlib = require("zlib");
            data = zlib.gunzipSync(data);
        }

        const count = data.readUInt16LE(0);
        let offset = 2;
        const packets = [];
        for (let i = 0; i < count && offset < data.length; i++) {
            const pktLen = data.readUInt32LE(offset);
            offset += 4;
            if (offset + pktLen > data.length) break;
            packets.push(data.slice(offset, offset + pktLen));
            offset += pktLen;
        }

        if (packets.length === 0) { sendJson(res, 400, { e: "no packets" }); return; }

        const conn = await getDcConnectionFwd(dc, dcInfo);
        const responses = [];
        for (const pkt of packets) {
            const resp = await sendToDcFwd(conn, pkt);
            if (resp) responses.push(resp);
        }

        let respData = Buffer.alloc(2);
        respData.writeUInt16LE(responses.length, 0);
        for (const resp of responses) {
            const lenBuf = Buffer.alloc(4);
            lenBuf.writeUInt32LE(resp.length, 0);
            respData = Buffer.concat([respData, lenBuf, resp]);
        }

        if (compressed) {
            const zlib = require("zlib");
            respData = zlib.gzipSync(respData);
        }

        sendJson(res, 200, { data: respData.toString("base64"), compressed, packets: responses.length });
        log("INFO", "MTProto relay", { dc, in: packets.length, out: responses.length });
    } catch (err) {
        log("ERROR", "MTProto error", { error: String(err.message || err) });
        sendJson(res, 500, { e: "mtproto error" });
    }
}

async function getDcConnectionFwd(dcId, dcInfo) {
    const net = require("net");
    const key = `dc${dcId}`;
    const existing = dcConnectionsFwd.get(key);
    if (existing && existing.socket && !existing.socket.destroyed) {
        existing.lastUsed = Date.now();
        return existing;
    }
    return new Promise((resolve, reject) => {
        const socket = net.createConnection(dcInfo.port, dcInfo.host, () => {
            const conn = { socket, buffer: Buffer.alloc(0), lastUsed: Date.now(), pending: [] };
            dcConnectionsFwd.set(key, conn);
            socket.on("data", (chunk) => {
                conn.buffer = Buffer.concat([conn.buffer, chunk]);
                while (conn.pending.length > 0 && conn.buffer.length >= 4) {
                    const pktLen = conn.buffer.readUInt32LE(0);
                    if (pktLen > 0 && conn.buffer.length >= 4 + pktLen) {
                        const pkt = conn.buffer.slice(4, 4 + pktLen);
                        conn.buffer = conn.buffer.slice(4 + pktLen);
                        const { resolve: res, timeout } = conn.pending.shift();
                        clearTimeout(timeout);
                        res(pkt);
                    } else break;
                }
            });
            socket.on("error", () => { dcConnectionsFwd.delete(key); conn.pending.forEach(p => { clearTimeout(p.timeout); p.resolve(null); }); });
            socket.on("close", () => { dcConnectionsFwd.delete(key); });
            resolve(conn);
        });
        socket.setTimeout(10000);
        socket.on("timeout", () => { socket.destroy(); reject(new Error("timeout")); });
        socket.on("error", reject);
    });
}

function sendToDcFwd(conn, packet) {
    return new Promise((resolve) => {
        if (!conn.socket || conn.socket.destroyed) { resolve(null); return; }
        const lenBuf = Buffer.alloc(4);
        lenBuf.writeUInt32LE(packet.length, 0);
        conn.socket.write(Buffer.concat([lenBuf, packet]));
        const timeout = setTimeout(() => { const idx = conn.pending.findIndex(p => p.resolve === resolve); if (idx >= 0) conn.pending.splice(idx, 1); resolve(null); }, 5000);
        conn.pending.push({ resolve, timeout });
    });
}

setInterval(() => { const now = Date.now(); for (const [k, c] of dcConnectionsFwd) { if (now - c.lastUsed > 300000) { try { c.socket.destroy(); } catch(_){} dcConnectionsFwd.delete(k); } } }, 300000).unref();

async function handleTcpTunnel(body, res) {
    const { sid, cmd, host, port, b } = body;
    if (!sid) { sendJson(res, 400, { e: "missing sid" }); return; }

    switch (cmd) {
        case "open": {
            if (!host || !port) { sendJson(res, 400, { e: "missing host/port" }); return; }
            if (host === "localhost" || host === "127.0.0.1") { sendJson(res, 403, { e: "blocked" }); return; }
            try {
                const socket = await new Promise((resolve, reject) => {
                    const s = net.createConnection({ host, port }, () => resolve(s));
                    s.on("error", reject);
                    setTimeout(() => { s.destroy(); reject(new Error("timeout")); }, 10000);
                });
                const session = { socket, buffer: Buffer.alloc(0), lastActivity: Date.now(), closed: false };
                socket.on("data", (chunk) => { session.buffer = Buffer.concat([session.buffer, chunk]); session.lastActivity = Date.now(); });
                socket.on("close", () => { session.closed = true; });
                socket.on("error", () => { session.closed = true; });
                tcpSessions.set(sid, session);
                sendJson(res, 200, { ok: true });
            } catch (err) {
                sendJson(res, 502, { e: "connect failed: " + (err.message || err) });
            }
            break;
        }
        case "data": {
            const session = tcpSessions.get(sid);
            if (!session) { sendJson(res, 404, { e: "session not found" }); return; }
            if (b) { session.socket.write(Buffer.from(b, "base64")); session.lastActivity = Date.now(); }
            sendJson(res, 200, { ok: true });
            break;
        }
        case "recv": {
            const session = tcpSessions.get(sid);
            if (!session) { sendJson(res, 200, { closed: true }); return; }
            if (session.closed && session.buffer.length === 0) { tcpSessions.delete(sid); sendJson(res, 200, { closed: true }); return; }
            const data = session.buffer;
            session.buffer = Buffer.alloc(0);
            session.lastActivity = Date.now();
            sendJson(res, 200, { b: data.length > 0 ? data.toString("base64") : "", closed: !!session.closed });
            break;
        }
        case "close": {
            const session = tcpSessions.get(sid);
            if (session) { session.socket.destroy(); tcpSessions.delete(sid); }
            sendJson(res, 200, { ok: true });
            break;
        }
        default: sendJson(res, 400, { e: "unknown cmd" });
    }
}

// ─── UDP Relay ───────────────────────────────────────────────────────────────

async function handleUdpRelay(body, res) {
    const { host, port, b, timeout } = body;
    if (!host || !port || !b) { sendJson(res, 400, { e: "missing host/port/b" }); return; }
    if (host === "localhost" || host === "127.0.0.1") { sendJson(res, 403, { e: "blocked" }); return; }

    const packet = Buffer.from(b, "base64");
    const recvTimeout = Math.min(timeout || 3000, 10000);

    try {
        const response = await new Promise((resolve, reject) => {
            const socket = dgram.createSocket("udp4");
            let done = false;
            socket.on("message", (msg) => { if (!done) { done = true; socket.close(); resolve(msg); } });
            socket.on("error", (err) => { if (!done) { done = true; socket.close(); reject(err); } });
            setTimeout(() => { if (!done) { done = true; socket.close(); resolve(null); } }, recvTimeout);
            socket.send(packet, port, host);
        });
        sendJson(res, 200, { b: response ? response.toString("base64") : "" });
    } catch (err) {
        sendJson(res, 502, { e: "udp failed: " + (err.message || err) });
    }
}

// ─── Graceful Shutdown ───────────────────────────────────────────────────────

let shuttingDown = false;

function shutdown(signal) {
    if (shuttingDown) return;
    shuttingDown = true;

    log("INFO", `${signal} received — shutting down gracefully...`);

    server.close(() => {
        log("INFO", "All connections closed. Bye!");
        process.exit(0);
    });

    // Force exit after 10s
    setTimeout(() => {
        log("WARN", "Forcing exit after timeout.");
        process.exit(1);
    }, 10000).unref();
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
