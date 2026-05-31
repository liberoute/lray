// Package dashboard serves the web monitoring dashboard.
package dashboard

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"net/http"
	"sync"
	"sync/atomic"
	"time"

	"github.com/liberoute/lray/internal/logger"
)

var log = logger.New("Dash")

// StatsProvider is implemented by the proxy server to provide stats.
type StatsProvider interface {
	ActiveConnections() int
	TotalRequests() int64
}

// Server serves the monitoring dashboard.
type Server struct {
	port      int
	startedAt time.Time
	server    *http.Server
	provider  StatsProvider

	totalRequests atomic.Int64
	totalBytes    atomic.Int64
	mu            sync.RWMutex
	topHosts      map[string]*hostStat
}

type hostStat struct {
	Requests int   `json:"requests"`
	Bytes    int64 `json:"bytes"`
}

// New creates a dashboard server.
func New(port int, provider StatsProvider) *Server {
	return &Server{
		port:      port,
		startedAt: time.Now(),
		provider:  provider,
		topHosts:  make(map[string]*hostStat),
	}
}

// RecordRequest records a completed request for stats.
func (s *Server) RecordRequest(host string, bytes int) {
	s.totalRequests.Add(1)
	s.totalBytes.Add(int64(bytes))

	s.mu.Lock()
	h, ok := s.topHosts[host]
	if !ok {
		h = &hostStat{}
		s.topHosts[host] = h
	}
	h.Requests++
	h.Bytes += int64(bytes)
	s.mu.Unlock()
}

// Start starts the dashboard server.
func (s *Server) Start(host string) error {
	mux := http.NewServeMux()
	mux.HandleFunc("/dashboard", s.handleDashboard)
	mux.HandleFunc("/dashboard/", s.handleDashboard)
	mux.HandleFunc("/dashboard/api/stats", s.handleStats)
	mux.HandleFunc("/", s.handleDashboard)

	addr := fmt.Sprintf("%s:%d", host, s.port)
	s.server = &http.Server{
		Addr:    addr,
		Handler: mux,
	}

	ln, err := net.Listen("tcp", addr)
	if err != nil {
		log.Warn("Dashboard failed to start on port %d: %v", s.port, err)
		return err
	}

	log.Info("Dashboard on http://%s:%d/dashboard", host, s.port)
	go s.server.Serve(ln)
	return nil
}

// Stop stops the dashboard server.
func (s *Server) Stop(ctx context.Context) error {
	if s.server != nil {
		return s.server.Shutdown(ctx)
	}
	return nil
}

func (s *Server) handleDashboard(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.Write([]byte(dashboardHTML))
}

func (s *Server) handleStats(w http.ResponseWriter, r *http.Request) {
	stats := s.getStats()
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Header().Set("Cache-Control", "no-cache")
	json.NewEncoder(w).Encode(stats)
}

func (s *Server) getStats() map[string]interface{} {
	uptime := int(time.Since(s.startedAt).Seconds())

	// Top hosts
	s.mu.RLock()
	type hostEntry struct {
		Host     string `json:"host"`
		Requests int    `json:"requests"`
		Bytes    int64  `json:"bytes"`
	}
	var topHosts []hostEntry
	for host, stat := range s.topHosts {
		topHosts = append(topHosts, hostEntry{
			Host:     host,
			Requests: stat.Requests,
			Bytes:    stat.Bytes,
		})
	}
	s.mu.RUnlock()

	// Sort by requests (simple bubble sort for small list)
	for i := 0; i < len(topHosts); i++ {
		for j := i + 1; j < len(topHosts); j++ {
			if topHosts[j].Requests > topHosts[i].Requests {
				topHosts[i], topHosts[j] = topHosts[j], topHosts[i]
			}
		}
	}
	if len(topHosts) > 15 {
		topHosts = topHosts[:15]
	}

	activeConns := 0
	if s.provider != nil {
		activeConns = s.provider.ActiveConnections()
	}

	return map[string]interface{}{
		"version":            "1.2.0",
		"uptime_seconds":     uptime,
		"total_requests":     s.totalRequests.Load(),
		"active_connections": activeConns,
		"total_bytes":        s.totalBytes.Load(),
		"top_hosts":          topHosts,
	}
}

const dashboardHTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>lray Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: system-ui, -apple-system, sans-serif; background: #0f1117; color: #e4e4e7; padding: 2rem; }
h1 { font-size: 1.5rem; margin-bottom: 1.5rem; color: #60a5fa; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 2rem; }
.card { background: #1e2030; border-radius: 8px; padding: 1.2rem; }
.card .label { font-size: 0.75rem; text-transform: uppercase; color: #71717a; margin-bottom: 0.3rem; }
.card .value { font-size: 1.5rem; font-weight: 600; }
table { width: 100%; border-collapse: collapse; background: #1e2030; border-radius: 8px; overflow: hidden; }
th, td { padding: 0.6rem 1rem; text-align: left; border-bottom: 1px solid #27272a; }
th { background: #27272a; font-size: 0.75rem; text-transform: uppercase; color: #a1a1aa; }
.refresh { color: #71717a; font-size: 0.8rem; margin-top: 1rem; }
</style>
</head>
<body>
<h1>lray Dashboard</h1>
<div class="grid" id="cards"></div>
<table id="hosts"><thead><tr><th>Host</th><th>Requests</th><th>Bytes</th></tr></thead><tbody></tbody></table>
<p class="refresh">Auto-refreshes every 3s</p>
<script>
function fmt(n) { if (n > 1048576) return (n/1048576).toFixed(1)+'MB'; if (n > 1024) return (n/1024).toFixed(1)+'KB'; return n+'B'; }
function fmtTime(s) { let h=Math.floor(s/3600),m=Math.floor((s%3600)/60); return h?h+'h '+m+'m':m+'m'; }
async function refresh() {
  try {
    const r = await fetch('/dashboard/api/stats');
    const d = await r.json();
    document.getElementById('cards').innerHTML = [
      {l:'Uptime',v:fmtTime(d.uptime_seconds)},
      {l:'Requests',v:d.total_requests},
      {l:'Active',v:d.active_connections},
      {l:'Traffic',v:fmt(d.total_bytes)},
    ].map(c=>'<div class="card"><div class="label">'+c.l+'</div><div class="value">'+c.v+'</div></div>').join('');
    const tbody = document.querySelector('#hosts tbody');
    tbody.innerHTML = (d.top_hosts||[]).map(h=>'<tr><td>'+h.host+'</td><td>'+h.requests+'</td><td>'+fmt(h.bytes)+'</td></tr>').join('');
  } catch(e) {}
}
refresh(); setInterval(refresh, 3000);
</script>
</body>
</html>`
