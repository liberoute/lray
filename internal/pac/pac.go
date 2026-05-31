// Package pac serves PAC (Proxy Auto-Configuration) files.
package pac

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"strings"

	"github.com/liberoute/lray/internal/logger"
)

var log = logger.New("PAC")

// Server serves PAC files for browser auto-configuration.
type Server struct {
	proxyHost   string
	proxyPort   int
	socksPort   int
	pacPort     int
	bypassHosts []string
	pacContent  string
	server      *http.Server
}

// New creates a PAC server.
func New(proxyHost string, proxyPort, socksPort, pacPort int, bypassHosts []string) *Server {
	s := &Server{
		proxyHost:   proxyHost,
		proxyPort:   proxyPort,
		socksPort:   socksPort,
		pacPort:     pacPort,
		bypassHosts: bypassHosts,
	}
	s.pacContent = s.generate()
	return s
}

func (s *Server) generate() string {
	var bypassBlock strings.Builder
	for _, rule := range s.bypassHosts {
		rule = strings.TrimSpace(rule)
		if rule == "" {
			continue
		}
		if strings.HasPrefix(rule, ".") {
			bypassBlock.WriteString(fmt.Sprintf("        if (shExpMatch(host, \"*%s\")) return direct;\n", rule))
		} else {
			bypassBlock.WriteString(fmt.Sprintf("        if (host === \"%s\") return direct;\n", rule))
		}
	}

	var proxyString string
	if s.socksPort > 0 {
		proxyString = fmt.Sprintf("SOCKS5 %s:%d; PROXY %s:%d; DIRECT", s.proxyHost, s.socksPort, s.proxyHost, s.proxyPort)
	} else {
		proxyString = fmt.Sprintf("PROXY %s:%d; DIRECT", s.proxyHost, s.proxyPort)
	}

	return fmt.Sprintf(`function FindProxyForURL(url, host) {
    var direct = "DIRECT";
    var proxy = "%s";

    if (host === "localhost" || host === "127.0.0.1" || host === "::1") return direct;

    if (isInNet(host, "10.0.0.0", "255.0.0.0")) return direct;
    if (isInNet(host, "172.16.0.0", "255.240.0.0")) return direct;
    if (isInNet(host, "192.168.0.0", "255.255.0.0")) return direct;
    if (isInNet(host, "169.254.0.0", "255.255.0.0")) return direct;

%s
    return proxy;
}`, proxyString, bypassBlock.String())
}

// Start starts the PAC server.
func (s *Server) Start(host string) error {
	mux := http.NewServeMux()
	mux.HandleFunc("/", s.handleRequest)
	mux.HandleFunc("/proxy.pac", s.handleRequest)
	mux.HandleFunc("/wpad.dat", s.handleRequest)

	addr := fmt.Sprintf("%s:%d", host, s.pacPort)
	s.server = &http.Server{
		Addr:    addr,
		Handler: mux,
	}

	ln, err := net.Listen("tcp", addr)
	if err != nil {
		log.Warn("PAC server failed to start on port %d: %v", s.pacPort, err)
		return err
	}

	log.Info("PAC file server on http://%s:%d/proxy.pac", host, s.pacPort)
	go s.server.Serve(ln)
	return nil
}

// Stop stops the PAC server.
func (s *Server) Stop(ctx context.Context) error {
	if s.server != nil {
		return s.server.Shutdown(ctx)
	}
	return nil
}

func (s *Server) handleRequest(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/x-ns-proxy-autoconfig")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Access-Control-Allow-Origin", "*")
	w.Write([]byte(s.pacContent))
}
