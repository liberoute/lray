// Cloudflare Worker — with CORS, proxy exit, multi-forwarder failover

const WORKER_URL = "myworker.workers.dev";
const DEFAULT_UPSTREAM_TIMEOUT_MS = 25000;

// CORS headers to add to responses
const CORS_HEADERS = {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS, HEAD",
    "access-control-allow-headers": "*",
    "access-control-max-age": "86400",
};

export default {
    async fetch(request, env) {
        // Handle CORS preflight
        if (request.method === "OPTIONS") {
            return new Response(null, { status: 204, headers: CORS_HEADERS });
        }

        try {
            const hop = request.headers.get("x-relay-hop");
            const fwdHop = request.headers.get("x-fwd-hop");
            if (hop === "1" || fwdHop === "1") {
                return json({ e: "loop detected" }, 508);
            }

            if (request.method === "GET") {
                const url = new URL(request.url);
                if (url.pathname === "/dashboard") {
                    // Auth via cookie (set by POST login)
                    const cookie = request.headers.get("cookie") || "";
                    const authKey = (env && env.UPSTREAM_AUTH_KEY) || (typeof _FORWARDER_KEY !== 'undefined' ? _FORWARDER_KEY : "");
                    const hasAuth = cookie.includes("dash_key=" + authKey);
                    if (!authKey || !hasAuth) {
                        return addCors(new Response(WORKER_LOGIN_HTML, {
                            status: 200,
                            headers: { "content-type": "text/html; charset=utf-8" },
                        }));
                    }
                    return addCors(new Response(WORKER_DASHBOARD_HTML, {
                        status: 200,
                        headers: { "content-type": "text/html; charset=utf-8" },
                    }));
                }
                if (url.pathname === "/dashboard/login") {
                    // POST login sets a cookie
                    return addCors(new Response(WORKER_LOGIN_HTML, {
                        status: 200,
                        headers: { "content-type": "text/html; charset=utf-8" },
                    }));
                }
                return json({ e: "Relay is Active.", workers: 1 }, 200);
            }

            // Dashboard login POST
            if (request.method === "POST") {
                const url = new URL(request.url);
                if (url.pathname === "/dashboard/login") {
                    const body = await request.json().catch(() => ({}));
                    const authKey = (env && env.UPSTREAM_AUTH_KEY) || (typeof _FORWARDER_KEY !== 'undefined' ? _FORWARDER_KEY : "");
                    if (body.key === authKey) {
                        return new Response(JSON.stringify({ ok: true }), {
                            status: 200,
                            headers: {
                                "content-type": "application/json",
                                "set-cookie": `dash_key=${authKey}; Path=/dashboard; HttpOnly; SameSite=Strict; Max-Age=86400`,
                                ...CORS_HEADERS,
                            },
                        });
                    }
                    return json({ ok: false, e: "invalid key" }, 401);
                }
            }

            if (request.method !== "POST") {
                return json({ e: "Method not allowed." }, 405);
            }

            const req = await request.json();

            // ── MTProto relay (forward to upstream forwarder) ────────────────
            if (req.cmd === "mtproto") {
                const upstreamUrls = getUpstreamUrls(env);
                if (upstreamUrls.length === 0) {
                    return addCors(json({
                        e: "mtproto requires UPSTREAM_FORWARDER_URL (Worker can't do raw TCP)"
                    }, 501));
                }
                // Forward entire MTProto batch to forwarder
                const mtpResp = await forwardWithFailover(req, env, upstreamUrls);
                if (mtpResp) return addCors(mtpResp);
                return addCors(json({ e: "all forwarders failed for mtproto" }, 502));
            }

            if (!req.u) {
                return json({ e: "missing url" }, 400);
            }

            const targetUrl = new URL(req.u);

            const BLOCKED_HOSTS = [WORKER_URL];
            if (BLOCKED_HOSTS.some(h => targetUrl.hostname.endsWith(h))) {
                return json({ e: "self-fetch blocked" }, 400);
            }

            // ── Upstream Forwarder (with multi-URL failover) ─────────────────
            const upstreamUrls = getUpstreamUrls(env);
            const wantForward = (req.f === 1) || (req.f === undefined);

            if (upstreamUrls.length > 0 && wantForward) {
                const upstreamResp = await forwardWithFailover(req, env, upstreamUrls);
                if (upstreamResp) return addCors(upstreamResp);
                // fall through to direct fetch if all forwarders failed and mode is open
            }

            // ── Exit through external proxy (optional) ───────────────────────
            const exitProxy = (env && env.EXIT_PROXY_URL) || "";

            // ── Direct fetch ─────────────────────────────────────────────────
            const headers = new Headers();
            if (req.h && typeof req.h === "object") {
                for (const [k, v] of Object.entries(req.h)) {
                    headers.set(k, v);
                }
            }
            headers.set("x-relay-hop", "1");

            const fetchOptions = {
                method: (req.m || "GET").toUpperCase(),
                headers,
                redirect: req.r === false ? "manual" : "follow",
            };

            if (req.b) {
                fetchOptions.body = Uint8Array.from(atob(req.b), c => c.charCodeAt(0));
            }

            if (exitProxy && upstreamUrls.length === 0) {
                return json({
                    e: "EXIT_PROXY_URL requires UPSTREAM_FORWARDER_URL to be set. " +
                       "The forwarder on your VPS handles proxy routing."
                }, 501);
            }

            const resp = await fetch(targetUrl.toString(), fetchOptions);

            // Read response safely
            const buffer = await resp.arrayBuffer();
            const uint8 = new Uint8Array(buffer);

            let binary = "";
            const chunkSize = 0x8000;
            for (let i = 0; i < uint8.length; i += chunkSize) {
                binary += String.fromCharCode.apply(null, uint8.subarray(i, i + chunkSize));
            }
            const base64 = btoa(binary);

            const responseHeaders = {};
            resp.headers.forEach((v, k) => { responseHeaders[k] = v; });

            return addCors(json({
                s: resp.status,
                h: responseHeaders,
                b: base64
            }));

        } catch (err) {
            return addCors(json({ e: String(err) }, 500));
        }
    }
};

// ─── Multi-Forwarder Failover ────────────────────────────────────────────────

/**
 * Parse upstream forwarder URLs from env.
 * Supports:
 *   UPSTREAM_FORWARDER_URL = "https://node1.example.com/fwd"  (single)
 *   UPSTREAM_FORWARDER_URLS = "https://node1.example.com/fwd,https://node2.example.com/fwd"  (multi, comma-separated)
 */
function getUpstreamUrls(env) {
    if (!env) return [];

    // Multi-URL takes priority
    const multi = env.UPSTREAM_FORWARDER_URLS || "";
    if (multi) {
        return multi.split(",").map(u => u.trim()).filter(u => u.length > 0);
    }

    // Fallback to single URL
    const single = env.UPSTREAM_FORWARDER_URL || "";
    return single ? [single] : [];
}

/**
 * Try each forwarder in order. If one fails, try the next.
 * Returns Response on success, or null if all failed and mode is "open".
 */
async function forwardWithFailover(req, env, urls) {
    const failMode = (env.UPSTREAM_FAIL_MODE || "closed").toLowerCase();
    const timeoutMs = parseInt(env.UPSTREAM_TIMEOUT_MS, 10) || DEFAULT_UPSTREAM_TIMEOUT_MS;
    const authKey = env.UPSTREAM_AUTH_KEY || "";

    if (!authKey) {
        return upstreamFailure("UPSTREAM_AUTH_KEY missing", failMode);
    }

    const payload = {
        u: req.u,
        m: req.m,
        h: req.h,
        b: req.b,
        ct: req.ct,
        r: req.r,
    };

    if (env.EXIT_PROXY_URL) {
        payload._proxy = env.EXIT_PROXY_URL;
    }

    let lastError = "";

    for (const url of urls) {
        let parsed;
        try {
            parsed = new URL(url);
        } catch (_) {
            lastError = `invalid URL: ${url}`;
            continue;
        }
        if (parsed.hostname.endsWith(WORKER_URL)) {
            lastError = "self-forward blocked";
            continue;
        }

        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), timeoutMs);

        try {
            const resp = await fetch(url, {
                method: "POST",
                headers: {
                    "content-type": "application/json",
                    "x-upstream-auth": authKey,
                },
                body: JSON.stringify(payload),
                signal: controller.signal,
            });

            if (!resp.ok) {
                lastError = `${url} → status ${resp.status}`;
                continue; // try next forwarder
            }

            const body = await resp.text();
            return new Response(body, {
                status: 200,
                headers: { "content-type": "application/json" },
            });
        } catch (err) {
            lastError = `${url} → ${err?.message || err}`;
            continue; // try next forwarder
        } finally {
            clearTimeout(timer);
        }
    }

    // All forwarders failed
    return upstreamFailure("all forwarders failed, last: " + lastError, failMode);
}

function upstreamFailure(reason, failMode) {
    if (failMode === "open") {
        console.warn("upstream forwarder failed (falling back to direct):", reason);
        return null;
    }
    return json({ e: "upstream forwarder failed: " + reason }, 502);
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function addCors(response) {
    const newHeaders = new Headers(response.headers);
    for (const [k, v] of Object.entries(CORS_HEADERS)) {
        newHeaders.set(k, v);
    }
    return new Response(response.body, {
        status: response.status,
        headers: newHeaders,
    });
}

function json(obj, status = 200) {
    return new Response(JSON.stringify(obj), {
        status,
        headers: {
            "content-type": "application/json",
            ...CORS_HEADERS,
        },
    });
}

// ─── Worker Dashboard HTML ───────────────────────────────────────────────────

// ─── Worker Login HTML ────────────────────────────────────────────────────────

const WORKER_LOGIN_HTML = `<!DOCTYPE html>
<html><head><title>Login</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body{font-family:system-ui,sans-serif;background:#0f1117;color:#e4e7ef;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}
.box{background:#1a1d27;border:1px solid #2e3345;border-radius:12px;padding:30px;max-width:350px;width:100%}
h2{margin-bottom:16px;font-size:1.2rem}
input{width:100%;padding:10px;border-radius:8px;border:1px solid #2e3345;background:#242836;color:#e4e7ef;margin-bottom:12px;font-size:.9rem}
button{width:100%;padding:10px;border-radius:8px;border:none;background:#6366f1;color:#fff;font-weight:600;cursor:pointer;font-size:.9rem}
button:hover{background:#4f46e5}
.err{color:#ef4444;font-size:.8rem;margin-top:8px;display:none}
</style></head>
<body><div class="box"><h2>🔒 Worker Dashboard</h2>
<input type="password" id="key" placeholder="Enter AUTH_KEY" autofocus onkeydown="if(event.key==='Enter')go()">
<button onclick="go()">Login</button>
<div class="err" id="err">Invalid key</div>
<script>
async function go(){
  var k=document.getElementById("key").value;
  if(!k)return;
  var r=await fetch("/dashboard/login",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({key:k})});
  if(r.ok){window.location.href="/dashboard"}
  else{document.getElementById("err").style.display="block"}
}
</script>
</div></body></html>`;

// ─── Worker Dashboard HTML ───────────────────────────────────────────────────

const WORKER_DASHBOARD_HTML = `<!DOCTYPE html>
<html><head><title>CF Worker Dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#0f1117;--surface:#1a1d27;--border:#2e3345;--text:#e4e7ef;--text2:#8b92a8;--green:#22c55e;--blue:#3b82f6;--radius:12px}
[data-theme="light"]{--bg:#f8f9fa;--surface:#ffffff;--border:#e2e4e9;--text:#1a1d27;--text2:#6b7280}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;padding:24px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:20px}
.label{font-size:.7rem;text-transform:uppercase;color:var(--text2);margin-bottom:6px}
.value{font-size:1.5rem;font-weight:700}
.green{color:var(--green)}.blue{color:var(--blue)}
h1{font-size:1.3rem;margin-bottom:20px}
.info{font-size:.8rem;color:var(--text2);line-height:1.8}
.hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}
.tbtn{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:6px 12px;cursor:pointer;color:var(--text);font-size:.8rem}
</style></head><body>
<div class="hdr">
<h1>⚡ Cloudflare Worker — Relay Dashboard</h1>
<button class="tbtn" onclick="toggleTheme()" id="tb">🌙</button>
</div>
<div class="grid">
<div class="card"><div class="label">Status</div><div class="value green">Active</div></div>
<div class="card"><div class="label">Worker</div><div class="value blue" style="font-size:1rem">\${WORKER_URL}</div></div>
</div>
<div class="card">
<div class="label">Configuration</div>
<div class="info">
<p>Worker URL: \${WORKER_URL}</p>
<p>Upstream Forwarder: \${typeof _FORWARDER_URL !== 'undefined' ? _FORWARDER_URL : 'not configured'}</p>
<p>Fail Mode: check env UPSTREAM_FAIL_MODE</p>
</div>
</div>
<div class="card">
<div class="label">Endpoints</div>
<div class="info">
<p>POST / — relay request</p>
<p>GET / — status JSON</p>
<p>GET /dashboard — this page</p>
</div>
</div>
<script>
function toggleTheme(){var h=document.documentElement,n=h.getAttribute("data-theme")==="light"?"":"light";h.setAttribute("data-theme",n);localStorage.setItem("t",n);document.getElementById("tb").textContent=n==="light"?"☀️":"🌙"}
(function(){var s=localStorage.getItem("t");if(s){document.documentElement.setAttribute("data-theme",s);document.getElementById("tb").textContent=s==="light"?"☀️":"🌙"}})();
</script>
</body></html>`;
