// Self-Hosted Exit Node — Cloudflare Worker alternative
//
// Purpose: Replace Cloudflare Worker entirely. This runs on your own VPS
// and does the same job: receives relay requests from GAS and fetches
// the target URL directly.
//
// Architecture:
//   Client → Local Proxy → GAS → THIS SERVER → Target Website
//
// No Cloudflare needed. Your VPS IP is the exit IP.
//
// Required env:
//   AUTH_KEY  — must match the AUTH_KEY in Code.gs WORKER_URL (>= 32 chars)
//
// Optional env:
//   PORT             — listen port (default 3000)
//   HOST             — listen host (default 0.0.0.0)
//   MAX_BODY_MB      — max request body in MB (default 100)
//   FETCH_TIMEOUT_MS — timeout for outbound fetch (default 30000)
//   RATE_LIMIT_RPM   — max requests per minute per IP (default 300, 0=unlimited)
//   EXIT_PROXY_URL   — route outbound fetch through a proxy (optional)
//   LOG_REQUESTS     — log each request (default true)
//
// Wire protocol (same as Cloudflare Worker):
//   POST /  body: { u, m, h, b, ct, r }  →  { s, h, b }  or  { e }
//   GET  /  → status page

"use strict";

const http = require("http");
const fs = require("fs");
const path = require("path");

// ─── Configuration ───────────────────────────────────────────────────────────

const AUTH_KEY          = process.env.AUTH_KEY || "";
const PORT             = parseInt(process.env.PORT, 10) || 3000;
const HOST             = process.env.HOST || "0.0.0.0";
const MAX_BODY_BYTES   = (parseInt(process.env.MAX_BODY_MB, 10) || 100) * 1024 * 1024;
const FETCH_TIMEOUT_MS = parseInt(process.env.FETCH_TIMEOUT_MS, 10) || 30000;
const RATE_LIMIT_RPM   = parseInt(process.env.RATE_LIMIT_RPM, 10) || 300;
const EXIT_PROXY_URL   = process.env.EXIT_PROXY_URL || "";
const LOG_REQUESTS     = (process.env.LOG_REQUESTS || "true") !== "false";

if (!AUTH_KEY || AUTH_KEY.length < 32) {
    console.error("FATAL: AUTH_KEY env var missing or shorter than 32 chars.");
    process.exit(1);
}

// ─── Rate Limiter ────────────────────────────────────────────────────────────

const rateBuckets = new Map();

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

function log(level, msg, meta) {
    const ts = new Date().toISOString();
    const base = `[${ts}] [${level}] ${msg}`;
    const full = meta
        ? base + " " + (typeof meta === "string" ? meta : JSON.stringify(meta))
        : base;
    console.log(full);
    LOG_BUFFER.push(full);
    if (LOG_BUFFER.length > LOG_BUFFER_MAX) LOG_BUFFER.shift();
}

const LOG_BUFFER = [];
const LOG_BUFFER_MAX = 200;

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
            if (size > maxBytes) { req.destroy(); reject(new Error("body_too_large")); return; }
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
        "access-control-allow-origin": "*",
    });
    res.end(body);
}

// ─── Dashboard Auth ──────────────────────────────────────────────────────────

const DASHBOARD_USER = process.env.DASHBOARD_USER || "";
const DASHBOARD_PASS = process.env.DASHBOARD_PASS || "";

function checkDashboardAuth(req, res) {
    // If both user and pass are empty, use AUTH_KEY-only login
    if (!DASHBOARD_USER && !DASHBOARD_PASS) {
        // Just check AUTH_KEY via Basic Auth (any username, password = AUTH_KEY)
        const authHeader = req.headers["authorization"] || "";
        if (!authHeader.startsWith("Basic ")) {
            res.writeHead(401, { "www-authenticate": 'Basic realm="Dashboard"', "content-type": "text/plain" });
            res.end("Enter any username, password = AUTH_KEY");
            return false;
        }
        const decoded = Buffer.from(authHeader.slice(6), "base64").toString();
        const [, pass] = decoded.split(":", 2);
        if (pass === AUTH_KEY) return true;
        res.writeHead(401, { "www-authenticate": 'Basic realm="Dashboard"', "content-type": "text/plain" });
        res.end("Invalid key");
        return false;
    }

    // User/pass mode
    const authHeader = req.headers["authorization"] || "";
    if (!authHeader.startsWith("Basic ")) {
        res.writeHead(401, { "www-authenticate": 'Basic realm="Dashboard"', "content-type": "text/plain" });
        res.end("Authentication required");
        return false;
    }
    const decoded = Buffer.from(authHeader.slice(6), "base64").toString();
    const [user, pass] = decoded.split(":", 2);
    if (user === DASHBOARD_USER && pass === DASHBOARD_PASS) return true;
    res.writeHead(401, { "www-authenticate": 'Basic realm="Dashboard"', "content-type": "text/plain" });
    res.end("Invalid credentials");
    return false;
}

// ─── Request Handler ─────────────────────────────────────────────────────────

const STATUS_PAGE =
    "<!DOCTYPE html><html><head><title>Exit Node Active</title>" +
    '<meta name="viewport" content="width=device-width,initial-scale=1"></head>' +
    '<body style="font-family:system-ui,sans-serif;max-width:600px;margin:40px auto;padding:0 20px">' +
    '<h1>Exit Node <span style="color:#16a34a">Active</span> ✓</h1>' +
    "<p>Self-hosted exit node — Cloudflare Worker alternative.</p>" +
    '<p style="color:#666;font-size:0.9em">POST / to relay | GET /stats | GET /health</p>' +
    "</body></html>";

async function handleRequest(req, res) {
    const startTime = Date.now();
    const clientIp = getClientIp(req);

    // Don't count dashboard/stats/health in metrics
    const isDashboardReq = req.method === "GET" && (
        req.url === "/" || req.url === "" ||
        req.url === "/health" ||
        req.url === "/stats" ||
        req.url.startsWith("/dashboard")
    );

    if (!isDashboardReq) {
        metrics.totalRequests++;
    }

    // ── GET endpoints ────────────────────────────────────────────────────────
    if (req.method === "GET") {
        switch (req.url) {
            case "/":
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
                    total_bytes_out: metrics.totalBytesOut,
                    avg_latency_ms: metrics.avgLatencyMs,
                    memory_mb: Math.round(process.memoryUsage().rss / 1024 / 1024),
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
                    res.end("Dashboard HTML not found");
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

    // ── Only POST / ──────────────────────────────────────────────────────────
    if (req.method !== "POST") {
        sendJson(res, 405, { e: "method not allowed" });
        return;
    }

    // Loop detection
    if (req.headers["x-relay-hop"] === "1" || req.headers["x-fwd-hop"] === "1") {
        sendJson(res, 508, { e: "loop detected" });
        return;
    }

    // Rate limit
    if (isRateLimited(clientIp)) {
        metrics.rateLimited++;
        sendJson(res, 429, { e: "rate limited" });
        return;
    }

    // Read body
    let raw;
    try {
        raw = await readBody(req, MAX_BODY_BYTES);
    } catch (err) {
        if (err.message === "body_too_large") {
            sendJson(res, 413, { e: "body too large" });
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

    // Validate URL
    if (!body.u || typeof body.u !== "string" || !/^https?:\/\//i.test(body.u)) {
        sendJson(res, 400, { e: "bad url" });
        return;
    }

    // Self-fetch protection
    try {
        const targetHost = new URL(body.u).hostname;
        if (targetHost === "localhost" || targetHost === "127.0.0.1") {
            sendJson(res, 400, { e: "self-fetch blocked" });
            return;
        }
    } catch (_) {
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
    headers["x-relay-hop"] = "1";

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

    // Proxy support
    const proxyUrl = body._proxy || EXIT_PROXY_URL;
    if (proxyUrl) {
        try {
            const { ProxyAgent } = require("undici");
            fetchOptions.dispatcher = new ProxyAgent(proxyUrl);
        } catch (e) {
            if (LOG_REQUESTS) log("WARN", `Proxy agent unavailable: ${e.message}`);
        }
    }

    // Execute fetch
    let resp;
    try {
        resp = await fetch(body.u, fetchOptions);
    } catch (err) {
        metrics.failedFetches++;
        const reason = err.name === "TimeoutError"
            ? `timeout (${FETCH_TIMEOUT_MS}ms)`
            : String(err?.message || err);
        if (LOG_REQUESTS) log("ERROR", `${fetchOptions.method} ${body.u} → FAILED: ${reason}`, { ip: clientIp });
        sendJson(res, 502, { e: "fetch failed: " + reason });
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
        b: buf.toString("base64"),
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

const requestHandler = async (req, res) => {
    try {
        await handleRequest(req, res);
    } catch (err) {
        log("ERROR", "Unhandled error", { error: String(err?.message || err) });
        if (!res.headersSent) sendJson(res, 500, { e: "internal error" });
    }
};

// ─── Server Setup ────────────────────────────────────────────────────────────

const HTTP_PORT = parseInt(process.env.HTTP_PORT, 10) || 0;
const PROTOCOL_MODE = process.env.PROTOCOL_MODE || "auto"; // http, https, both, auto

let server;
let httpServer;

// Determine what to start
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
    // auto: HTTPS if certs available, HTTP always as fallback
    useHttps = !!(SSL_CERT_FILE && SSL_KEY_FILE);
    useHttp = !useHttps || !!HTTP_PORT;
}

// HTTPS server
if (useHttps && SSL_CERT_FILE && SSL_KEY_FILE) {
    const https = require("https");
    try {
        const options = {
            cert: fs.readFileSync(SSL_CERT_FILE),
            key: fs.readFileSync(SSL_KEY_FILE),
        };
        server = https.createServer(options, requestHandler);
        server.keepAliveTimeout = 120000;
        server.headersTimeout = 125000;
        log("INFO", `TLS enabled: ${SSL_CERT_FILE}`);
    } catch (e) {
        log("WARN", `Failed to load TLS certs: ${e.message}`);
        useHttps = false;
        useHttp = true;
    }
}

// HTTP server (primary if no HTTPS, or secondary for "both" mode)
if (useHttp && !useHttps) {
    server = http.createServer(requestHandler);
    server.keepAliveTimeout = 120000;
    server.headersTimeout = 125000;
} else if (useHttp && useHttps) {
    httpServer = http.createServer(requestHandler);
    httpServer.keepAliveTimeout = 120000;
    httpServer.headersTimeout = 125000;
}

// Start main server
server.listen(PORT, HOST, () => {
    const proto = useHttps ? "https" : "http";
    log("INFO", `━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
    log("INFO", `  Self-Hosted Exit Node started`);
    log("INFO", `  ${proto}://${HOST}:${PORT}`);
    if (httpServer) {
        const hp = HTTP_PORT || 80;
        log("INFO", `  http://${HOST}:${hp}`);
    }
    log("INFO", `  Max body: ${MAX_BODY_BYTES / 1024 / 1024}MB`);
    log("INFO", `  Fetch timeout: ${FETCH_TIMEOUT_MS}ms`);
    log("INFO", `  Rate limit: ${RATE_LIMIT_RPM === 0 ? "unlimited" : RATE_LIMIT_RPM + " req/min/ip"}`);
    log("INFO", `━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`);
});

// Start HTTP server if "both" mode
if (httpServer) {
    const hp = HTTP_PORT || 80;
    httpServer.listen(hp, HOST, () => {
        log("INFO", `  HTTP also listening on ${HOST}:${hp}`);
    });
}

// ─── TCP Tunnel ──────────────────────────────────────────────────────────────

const net = require("net");
const dgram = require("dgram");

// Active TCP sessions: sid → { socket, buffer }
const tcpSessions = new Map();

// Cleanup idle sessions every 60s
setInterval(() => {
    const now = Date.now();
    for (const [sid, session] of tcpSessions) {
        if (now - session.lastActivity > 300000) { // 5 min idle
            session.socket.destroy();
            tcpSessions.delete(sid);
        }
    }
}, 60000).unref();

async function handleTcpTunnel(body, res) {
    const { sid, cmd, host, port, b } = body;

    if (!sid) {
        sendJson(res, 400, { e: "missing session id" });
        return;
    }

    switch (cmd) {
        case "open": {
            if (!host || !port) {
                sendJson(res, 400, { e: "missing host/port" });
                return;
            }
            // Block localhost
            if (host === "localhost" || host === "127.0.0.1" || host === "::1") {
                sendJson(res, 403, { e: "blocked" });
                return;
            }

            try {
                const socket = await new Promise((resolve, reject) => {
                    const s = net.createConnection({ host, port }, () => resolve(s));
                    s.on("error", reject);
                    setTimeout(() => { s.destroy(); reject(new Error("timeout")); }, 10000);
                });

                const session = {
                    socket,
                    buffer: Buffer.alloc(0),
                    lastActivity: Date.now(),
                };

                // Collect incoming data
                socket.on("data", (chunk) => {
                    session.buffer = Buffer.concat([session.buffer, chunk]);
                    session.lastActivity = Date.now();
                });
                socket.on("close", () => {
                    session.closed = true;
                });
                socket.on("error", () => {
                    session.closed = true;
                });

                tcpSessions.set(sid, session);
                sendJson(res, 200, { ok: true });
            } catch (err) {
                sendJson(res, 502, { e: "connect failed: " + (err.message || err) });
            }
            break;
        }

        case "data": {
            const session = tcpSessions.get(sid);
            if (!session) {
                sendJson(res, 404, { e: "session not found" });
                return;
            }
            if (b) {
                const data = Buffer.from(b, "base64");
                session.socket.write(data);
                session.lastActivity = Date.now();
            }
            sendJson(res, 200, { ok: true });
            break;
        }

        case "recv": {
            const session = tcpSessions.get(sid);
            if (!session) {
                sendJson(res, 200, { closed: true });
                return;
            }
            if (session.closed && session.buffer.length === 0) {
                tcpSessions.delete(sid);
                sendJson(res, 200, { closed: true });
                return;
            }
            // Return buffered data
            const data = session.buffer;
            session.buffer = Buffer.alloc(0);
            session.lastActivity = Date.now();
            sendJson(res, 200, {
                b: data.length > 0 ? data.toString("base64") : "",
                closed: !!session.closed,
            });
            break;
        }

        case "close": {
            const session = tcpSessions.get(sid);
            if (session) {
                session.socket.destroy();
                tcpSessions.delete(sid);
            }
            sendJson(res, 200, { ok: true });
            break;
        }

        default:
            sendJson(res, 400, { e: "unknown cmd: " + cmd });
    }
}

// ─── UDP Relay ───────────────────────────────────────────────────────────────

async function handleUdpRelay(body, res) {
    const { host, port, b, timeout } = body;

    if (!host || !port || !b) {
        sendJson(res, 400, { e: "missing host/port/b" });
        return;
    }

    // Block localhost
    if (host === "localhost" || host === "127.0.0.1" || host === "::1") {
        sendJson(res, 403, { e: "blocked" });
        return;
    }

    const packet = Buffer.from(b, "base64");
    const recvTimeout = Math.min(timeout || 3000, 10000); // max 10s

    try {
        const response = await new Promise((resolve, reject) => {
            const socket = dgram.createSocket("udp4");
            let responded = false;

            socket.on("message", (msg) => {
                if (!responded) {
                    responded = true;
                    socket.close();
                    resolve(msg);
                }
            });

            socket.on("error", (err) => {
                if (!responded) {
                    responded = true;
                    socket.close();
                    reject(err);
                }
            });

            // Timeout — return empty if no response
            setTimeout(() => {
                if (!responded) {
                    responded = true;
                    socket.close();
                    resolve(null);
                }
            }, recvTimeout);

            socket.send(packet, port, host);
        });

        if (response) {
            sendJson(res, 200, { b: response.toString("base64") });
        } else {
            sendJson(res, 200, { b: "" }); // no response within timeout
        }
    } catch (err) {
        sendJson(res, 502, { e: "udp failed: " + (err.message || err) });
    }
}

// ─── Graceful Shutdown ───────────────────────────────────────────────────────

let shuttingDown = false;
function shutdown(signal) {
    if (shuttingDown) return;
    shuttingDown = true;
    log("INFO", `${signal} — shutting down...`);
    server.close(() => { log("INFO", "Bye!"); process.exit(0); });
    setTimeout(() => { process.exit(1); }, 10000).unref();
}
process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
