// Google Apps Script — Multi-Mode Relay
//
// Exit modes:
//   MODE = "gas"         → GAS fetches target directly (no Worker, no VPS)
//   MODE = "cfw"         → GAS → Cloudflare Worker → target
//   MODE = "vps"         → GAS → VPS (self-hosted exit) → target
//   MODE = "cfw_vps"     → GAS → Cloudflare Worker → VPS → target

const AUTH_KEY = "STRONG_SECRET_KEY";
const MODE = "cfw"; // Change this: "gas", "cfw", "vps", "cfw_vps"

// Cloudflare Worker URLs (for MODE = "cfw" or "cfw_vps")
const WORKER_URLS = [
  "https://worker1.workers.dev",
];

// VPS URLs (for MODE = "vps")
// GAS sends directly to your VPS — no Cloudflare in between
const VPS_URLS = [
  // "https://your-vps.com",
];

const SKIP_HEADERS = {
  host: 1, connection: 1, "content-length": 1,
  "transfer-encoding": 1, "proxy-connection": 1, "proxy-authorization": 1,
};

// ─── Request Handler ─────────────────────────────────────────────────────────

function doPost(e) {
  try {
    var req = JSON.parse(e.postData.contents);
    if (req.k !== AUTH_KEY) return _json({ e: "unauthorized" });

    // Track stats
    var props = PropertiesService.getScriptProperties();
    var count = parseInt(props.getProperty("_totalRequests") || "0", 10) + 1;
    props.setProperty("_totalRequests", String(count));
    props.setProperty("_lastRequest", new Date().toISOString());

    // Track quota reset time (24h after first request of the day)
    var resetAt = props.getProperty("_quotaResetAt") || "";
    var now = new Date().getTime();
    if (!resetAt || now > parseInt(resetAt, 10)) {
      // New quota period — reset counter
      props.setProperty("_quotaResetAt", String(now + 86400000)); // +24h
      props.setProperty("_periodRequests", "1");
    } else {
      var periodCount = parseInt(props.getProperty("_periodRequests") || "0", 10) + 1;
      props.setProperty("_periodRequests", String(periodCount));
    }

    // Quota info request (from client dashboard)
    if (req.cmd === "quota") {
      var qProps = PropertiesService.getScriptProperties();
      var periodReqs = parseInt(qProps.getProperty("_periodRequests") || "0", 10);
      var resetAt = parseInt(qProps.getProperty("_quotaResetAt") || "0", 10);
      var totalReqs = parseInt(qProps.getProperty("_totalRequests") || "0", 10);
      var totalErrs = parseInt(qProps.getProperty("_totalErrors") || "0", 10);
      return _json({
        quota_limit: 20000,
        quota_used: periodReqs,
        quota_remaining: Math.max(0, 20000 - periodReqs),
        quota_reset_at: resetAt,
        total_requests: totalReqs,
        total_errors: totalErrs,
        mode: MODE,
      });
    }

    // MTProto batch relay (Telegram traffic)
    if (req.cmd === "mtproto") {
      return _doMTProto(req);
    }

    if (Array.isArray(req.q)) return _doBatch(req.q);
    return _doSingle(req);

  } catch (err) {
    try {
      var props2 = PropertiesService.getScriptProperties();
      var errs = parseInt(props2.getProperty("_totalErrors") || "0", 10) + 1;
      props2.setProperty("_totalErrors", String(errs));
    } catch(_){}
    return _json({ e: String(err) });
  }
}

function _doSingle(req) {
  if (!req.u || typeof req.u !== "string" || !req.u.match(/^https?:\/\//i)) {
    return _json({ e: "bad url" });
  }

  switch (MODE) {
    case "gas":
      return _doGasDirect(req);
    case "cfw":
      return _doCfw(req);
    case "vps":
      return _doVps(req);
    case "cfw_vps":
      return _doCfwVps(req);
    default:
      return _json({ e: "unknown MODE: " + MODE });
  }
}

// ─── Mode 1: GAS Direct (GAS fetches target itself) ─────────────────────────

function _doGasDirect(req) {
  var headers = {};
  if (req.h && typeof req.h === "object") {
    for (var k in req.h) {
      if (req.h.hasOwnProperty(k) && !SKIP_HEADERS[k.toLowerCase()]) {
        headers[k] = req.h[k];
      }
    }
  }

  var options = {
    method: (req.m || "GET").toLowerCase(),
    headers: headers,
    muteHttpExceptions: true,
    followRedirects: req.r !== false,
  };

  if (req.b) {
    options.payload = Utilities.newBlob(Utilities.base64Decode(req.b)).getBytes();
  }
  if (req.ct) {
    options.contentType = req.ct;
  }

  var resp = UrlFetchApp.fetch(req.u, options);

  var respHeaders = {};
  var allHeaders = resp.getAllHeaders();
  for (var hk in allHeaders) {
    if (allHeaders.hasOwnProperty(hk)) {
      respHeaders[hk.toLowerCase()] = String(allHeaders[hk]);
    }
  }

  return _json({
    s: resp.getResponseCode(),
    h: respHeaders,
    b: Utilities.base64Encode(resp.getContent()),
  });
}

// ─── Mode 2: CFW (GAS → Cloudflare Worker → target) ─────────────────────────

function _doCfw(req) {
  var payload = _buildWorkerPayload(req);
  return _json(_fetchWithFailover(WORKER_URLS, payload));
}

// ─── Mode 3: VPS (GAS → VPS → target) ───────────────────────────────────────

function _doVps(req) {
  var payload = _buildWorkerPayload(req);
  // VPS uses same wire protocol as Worker — just different URL
  return _json(_fetchWithFailover(VPS_URLS, payload));
}

// ─── Mode 4: CFW+VPS (GAS → Worker → VPS → target) ──────────────────────────

function _doCfwVps(req) {
  // Tell the Worker to forward through VPS (f=1 flag)
  var payload = _buildWorkerPayload(req);
  payload.f = 1; // force upstream forwarder
  return _json(_fetchWithFailover(WORKER_URLS, payload));
}

// ─── MTProto Relay (Telegram DC forwarding) ──────────────────────────────────
//
// Client sends batched Telegram packets (optionally gzip-compressed).
// We forward them to the appropriate Telegram DC and return the response.
//
// Request format:
//   { cmd: "mtproto", dc: 2, data: "base64...", compressed: true }
//
// The data field contains:
//   [count:u16][len1:u32][pkt1][len2:u32][pkt2]...
//   (optionally gzip-compressed)
//
// We unpack, send each packet to the DC via TCP (using UrlFetchApp as HTTP
// since GAS can't do raw TCP), and return responses.
//
// For VPS/CFW modes: forward the entire batch to exit node which handles TCP.

var TELEGRAM_DC_IPS = {
  1: "149.154.175.50",
  2: "149.154.167.50",
  3: "149.154.175.100",
  4: "149.154.167.91",
  5: "91.108.56.100",
};

function _doMTProto(req) {
  var dc = req.dc || 2;
  var data = req.data || "";
  var compressed = req.compressed || false;

  if (!data) return _json({ e: "no data" });

  // For VPS/CFW modes: forward entire batch to exit node
  if (MODE === "vps" || MODE === "cfw_vps") {
    var urls = (MODE === "vps") ? VPS_URLS : WORKER_URLS;
    var payload = {
      cmd: "mtproto",
      dc: dc,
      data: data,
      compressed: compressed,
      k: AUTH_KEY,
    };
    return _json(_fetchWithFailover(urls, payload));
  }

  // For GAS direct mode: we can't do raw TCP from GAS
  // But we can forward to Telegram's HTTPS API endpoints
  // This is limited — only works for API calls, not raw MTProto
  //
  // For full MTProto support, use VPS or CFW mode.
  // In GAS-only mode, Telegram should use HTTP proxy (CONNECT) instead.

  return _json({
    e: "mtproto_gas_unsupported",
    msg: "MTProto relay requires VPS or CFW mode. Use HTTP/SOCKS5 proxy for Telegram in GAS-only mode.",
  });
}

// ─── Batch ───────────────────────────────────────────────────────────────────

function _doBatch(items) {
  var results = [];

  if (MODE === "gas" || MODE === "gas") {
    // Gas direct: use fetchAll for parallelism
    var fetchArgs = [];
    var errorMap = {};

    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      if (!item.u || typeof item.u !== "string" || !item.u.match(/^https?:\/\//i)) {
        errorMap[i] = "bad url";
        continue;
      }

      var headers = {};
      if (item.h && typeof item.h === "object") {
        for (var k in item.h) {
          if (item.h.hasOwnProperty(k) && !SKIP_HEADERS[k.toLowerCase()]) {
            headers[k] = item.h[k];
          }
        }
      }

      var options = {
        url: item.u,
        method: (item.m || "GET").toLowerCase(),
        headers: headers,
        muteHttpExceptions: true,
        followRedirects: item.r !== false,
      };
      if (item.b) {
        options.payload = Utilities.newBlob(Utilities.base64Decode(item.b)).getBytes();
      }
      if (item.ct) {
        options.contentType = item.ct;
      }

      fetchArgs.push({ _i: i, _o: options });
    }

    var responses = [];
    if (fetchArgs.length > 0) {
      responses = UrlFetchApp.fetchAll(fetchArgs.map(function(x) { return x._o; }));
    }

    var rIdx = 0;
    for (var i = 0; i < items.length; i++) {
      if (errorMap.hasOwnProperty(i)) {
        results.push({ e: errorMap[i] });
      } else {
        var resp = responses[rIdx++];
        var respHeaders = {};
        var allH = resp.getAllHeaders();
        for (var hk in allH) {
          if (allH.hasOwnProperty(hk)) respHeaders[hk.toLowerCase()] = String(allH[hk]);
        }
        results.push({
          s: resp.getResponseCode(),
          h: respHeaders,
          b: Utilities.base64Encode(resp.getContent()),
        });
      }
    }
  } else {
    // For cfw/vps/cfw_vps: send batch to exit targets
    var urls = (MODE === "vps") ? VPS_URLS : WORKER_URLS;
    var fetchArgs = [];
    var errorMap = {};

    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      if (!item.u || typeof item.u !== "string" || !item.u.match(/^https?:\/\//i)) {
        errorMap[i] = "bad url";
        continue;
      }

      var payload = _buildWorkerPayload(item);
      if (MODE === "cfw_vps") payload.f = 1;

      var targetUrl = urls[i % urls.length];
      fetchArgs.push({
        _i: i,
        _payload: payload,
        _o: {
          url: targetUrl,
          method: "post",
          contentType: "application/json",
          payload: JSON.stringify(payload),
          muteHttpExceptions: true,
          followRedirects: true,
        }
      });
    }

    var responses = [];
    if (fetchArgs.length > 0) {
      responses = UrlFetchApp.fetchAll(fetchArgs.map(function(x) { return x._o; }));
    }

    var rIdx = 0;
    for (var i = 0; i < items.length; i++) {
      if (errorMap.hasOwnProperty(i)) {
        results.push({ e: errorMap[i] });
      } else {
        var resp = responses[rIdx];
        var code = resp.getResponseCode();
        if (code === 429 || code >= 500) {
          var retryResult = _fetchWithFailover(urls, fetchArgs[rIdx]._payload);
          results.push(retryResult);
        } else {
          try {
            results.push(JSON.parse(resp.getContentText()));
          } catch (e) {
            results.push({ e: "invalid response" });
          }
        }
        rIdx++;
      }
    }
  }

  return _json({ q: results });
}

// ─── Failover fetch ──────────────────────────────────────────────────────────

function _fetchWithFailover(urls, payload) {
  if (!urls || urls.length === 0) {
    return { e: "no exit URLs configured" };
  }

  var startIdx = _getNextIdx(urls.length);
  var lastError = null;

  for (var attempt = 0; attempt < urls.length; attempt++) {
    var idx = (startIdx + attempt) % urls.length;
    var url = urls[idx];

    try {
      var resp = UrlFetchApp.fetch(url, {
        method: "post",
        contentType: "application/json",
        payload: JSON.stringify(payload),
        muteHttpExceptions: true,
        followRedirects: true,
      });

      var code = resp.getResponseCode();
      if (code === 429 || code >= 500) {
        lastError = "target " + idx + " returned " + code;
        continue;
      }

      try {
        return JSON.parse(resp.getContentText());
      } catch (e) {
        return { e: "invalid response", raw: resp.getContentText().substring(0, 200) };
      }
    } catch (err) {
      lastError = "target " + idx + ": " + String(err);
      continue;
    }
  }

  return { e: "all targets failed", last_error: lastError };
}

function _getNextIdx(total) {
  var props = PropertiesService.getScriptProperties();
  var idx = parseInt(props.getProperty("_targetIdx") || "0", 10);
  var next = (idx + 1) % total;
  props.setProperty("_targetIdx", String(next));
  return idx;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function _buildWorkerPayload(req) {
  var headers = {};
  if (req.h && typeof req.h === "object") {
    for (var k in req.h) {
      if (req.h.hasOwnProperty(k) && !SKIP_HEADERS[k.toLowerCase()]) {
        headers[k] = req.h[k];
      }
    }
  }

  var out = {
    u: req.u,
    m: (req.m || "GET").toUpperCase(),
    h: headers,
    b: req.b || null,
    ct: req.ct || null,
    r: req.r !== false,
  };

  if (typeof req.f === "number") out.f = req.f;
  return out;
}

// ─── Dashboard ───────────────────────────────────────────────────────────────

function doGet(e) {
  var params = e ? e.parameter : {};
  if (params.key !== AUTH_KEY) {
    return HtmlService.createHtmlOutput(
      '<!DOCTYPE html><html><head><title>Login</title>' +
      '<meta name="viewport" content="width=device-width,initial-scale=1">' +
      '<style>body{font-family:system-ui,sans-serif;background:#0f1117;color:#e4e7ef;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}' +
      '.box{background:#1a1d27;border:1px solid #2e3345;border-radius:12px;padding:30px;max-width:350px;width:100%}' +
      'h2{margin-bottom:16px;font-size:1.2rem}input{width:100%;padding:10px;border-radius:8px;border:1px solid #2e3345;background:#242836;color:#e4e7ef;margin-bottom:12px;font-size:.9rem}' +
      'button{width:100%;padding:10px;border-radius:8px;border:none;background:#6366f1;color:#fff;font-weight:600;cursor:pointer;font-size:.9rem}button:hover{background:#4f46e5}</style></head>' +
      '<body><div class="box"><h2>\uD83D\uDD12 GAS Dashboard</h2>' +
      '<input type="password" id="key" placeholder="Enter AUTH_KEY" autofocus onkeydown="if(event.key===\'Enter\')go()">' +
      '<button onclick="go()">Login</button>' +
      '<script>function go(){var k=document.getElementById("key").value;if(k)window.location.href=window.location.pathname+"?key="+encodeURIComponent(k)}</script>' +
      '</div></body></html>'
    ).setTitle("Login");
  }

  var props = PropertiesService.getScriptProperties();
  var totalRequests = parseInt(props.getProperty("_totalRequests") || "0", 10);
  var totalErrors = parseInt(props.getProperty("_totalErrors") || "0", 10);
  var lastRequest = props.getProperty("_lastRequest") || "never";
  var periodRequests = parseInt(props.getProperty("_periodRequests") || "0", 10);
  var quotaResetAt = parseInt(props.getProperty("_quotaResetAt") || "0", 10);

  // Quota calculation
  var DAILY_LIMIT = 20000; // free account limit
  var quotaUsedPct = Math.round((periodRequests / DAILY_LIMIT) * 100);
  var quotaRemaining = Math.max(0, DAILY_LIMIT - periodRequests);
  var resetIn = "";
  if (quotaResetAt > 0) {
    var msLeft = quotaResetAt - new Date().getTime();
    if (msLeft > 0) {
      var hLeft = Math.floor(msLeft / 3600000);
      var mLeft = Math.floor((msLeft % 3600000) / 60000);
      resetIn = hLeft + "h " + mLeft + "m";
    } else {
      resetIn = "resetting...";
    }
  }

  var exitInfo = MODE;
  if (MODE === "vps") exitInfo += " (" + VPS_URLS.length + " VPS)";
  else if (MODE === "cfw") exitInfo += " (" + WORKER_URLS.length + " Workers)";
  else if (MODE === "cfw_vps") exitInfo += " (Workers→VPS)";

  return HtmlService.createHtmlOutput(
    '<!DOCTYPE html><html><head><title>GAS Dashboard</title>' +
    '<meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<style>' +
    ':root{--bg:#0f1117;--surface:#1a1d27;--surface2:#242836;--border:#2e3345;--text:#e4e7ef;--text2:#8b92a8;--green:#22c55e;--red:#ef4444;--blue:#3b82f6;--radius:12px}' +
    '[data-theme="light"]{--bg:#f8f9fa;--surface:#ffffff;--surface2:#f0f1f3;--border:#e2e4e9;--text:#1a1d27;--text2:#6b7280}' +
    '*{margin:0;padding:0;box-sizing:border-box}' +
    'body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;padding:24px}' +
    '.card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px;margin-bottom:16px}' +
    '.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin-bottom:20px}' +
    '.label{font-size:.7rem;text-transform:uppercase;color:var(--text2);margin-bottom:6px}' +
    '.value{font-size:1.4rem;font-weight:700}' +
    '.green{color:var(--green)}.red{color:var(--red)}.blue{color:var(--blue)}' +
    '.hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}' +
    'h1{font-size:1.3rem}' +
    '.tbtn{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:6px 12px;cursor:pointer;color:var(--text);font-size:.8rem}' +
    '</style></head><body>' +
    '<div class="hdr"><h1>\u26A1 GAS Relay Dashboard</h1><button class="tbtn" onclick="toggleTheme()" id="tb">\uD83C\uDF19</button></div>' +
    '<div class="grid">' +
    '<div class="card"><div class="label">Status</div><div class="value green">Active</div></div>' +
    '<div class="card"><div class="label">Mode</div><div class="value blue" style="font-size:1rem">' + exitInfo + '</div></div>' +
    '<div class="card"><div class="label">Requests</div><div class="value">' + totalRequests + '</div></div>' +
    '<div class="card"><div class="label">Errors</div><div class="value red">' + totalErrors + '</div></div>' +
    '</div>' +
    '<div class="card"><div class="label">Daily Quota (' + periodRequests + ' / ' + DAILY_LIMIT + ')</div>' +
    '<div style="background:var(--surface2);border-radius:6px;height:8px;margin:8px 0"><div style="background:' + (quotaUsedPct > 80 ? '#ef4444' : quotaUsedPct > 50 ? '#f59e0b' : '#22c55e') + ';height:100%;border-radius:6px;width:' + Math.min(quotaUsedPct, 100) + '%"></div></div>' +
    '<div style="font-size:.75rem;color:var(--text2)">' + quotaRemaining + ' remaining \u2022 resets in ' + resetIn + '</div></div>' +
    '<div class="card"><div class="label">Last Request</div><div class="value" style="font-size:.9rem">' + lastRequest + '</div></div>' +
    '<div class="card"><div class="label">Exit Targets</div><div style="font-size:.8rem;color:var(--text2)">' +
    (MODE === "vps" ? VPS_URLS.join("<br>") : WORKER_URLS.join("<br>")) +
    '</div></div>' +
    '<script>function toggleTheme(){var h=document.documentElement,n=h.getAttribute("data-theme")==="light"?"":"light";h.setAttribute("data-theme",n);localStorage.setItem("t",n);document.getElementById("tb").textContent=n==="light"?"\u2600\uFE0F":"\uD83C\uDF19"}(function(){var s=localStorage.getItem("t");if(s){document.documentElement.setAttribute("data-theme",s);document.getElementById("tb").textContent=s==="light"?"\u2600\uFE0F":"\uD83C\uDF19"}})()</script>' +
    '</body></html>'
  ).setTitle("GAS Dashboard");
}

function _json(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
