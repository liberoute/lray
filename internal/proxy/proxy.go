// Package proxy implements the core local proxy server.
package proxy

import (
	"bufio"
	"bytes"
	"crypto/tls"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/liberoute/lray/internal/config"
	"github.com/liberoute/lray/internal/fronter"
	"github.com/liberoute/lray/internal/logger"
	"github.com/liberoute/lray/internal/mitm"
	"github.com/liberoute/lray/internal/router"
)

var log = logger.New("Proxy")

// Server is the core proxy server.
type Server struct {
	cfg         *config.Config
	fronter     *fronter.DomainFronter
	certMgr     *mitm.CertManager
	router      *router.SmartRouter
	listeners   []net.Listener
	mu          sync.Mutex
	activeConns sync.WaitGroup
}

// New creates a proxy server.
func New(cfg *config.Config, f *fronter.DomainFronter, cm *mitm.CertManager, r *router.SmartRouter) *Server {
	return &Server{
		cfg:     cfg,
		fronter: f,
		certMgr: cm,
		router:  r,
	}
}

// Start starts all configured listeners.
func (s *Server) Start() error {
	for _, lcfg := range s.cfg.Listeners {
		addr := fmt.Sprintf("%s:%d", s.cfg.ListenHost, lcfg.Port)
		ln, err := net.Listen("tcp", addr)
		if err != nil {
			log.Error("Failed to bind %s: %v", addr, err)
			continue
		}
		s.listeners = append(s.listeners, ln)
		log.Info("Listener %s type=%s mode=%s", addr, lcfg.Type, lcfg.Mode)

		go s.acceptLoop(ln, lcfg)
	}

	if len(s.listeners) == 0 {
		return fmt.Errorf("no listeners started")
	}
	return nil
}

// Stop gracefully shuts down all listeners.
func (s *Server) Stop() {
	for _, ln := range s.listeners {
		ln.Close()
	}
	s.activeConns.Wait()
	s.fronter.Close()
}

func (s *Server) acceptLoop(ln net.Listener, lcfg config.Listener) {
	for {
		conn, err := ln.Accept()
		if err != nil {
			if ne, ok := err.(net.Error); ok && ne.Timeout() {
				continue
			}
			return // listener closed
		}
		s.activeConns.Add(1)
		go func() {
			defer s.activeConns.Done()
			s.handleConn(conn, lcfg)
		}()
	}
}

func (s *Server) handleConn(conn net.Conn, lcfg config.Listener) {
	defer conn.Close()
	conn.SetDeadline(time.Now().Add(120 * time.Second))

	switch lcfg.Type {
	case "socks5":
		s.handleSOCKS5(conn, lcfg.Mode)
	case "mixed":
		s.handleMixed(conn, lcfg.Mode)
	default: // http
		s.handleHTTP(conn, lcfg.Mode)
	}
}

func (s *Server) handleMixed(conn net.Conn, mode string) {
	// Peek first byte to detect SOCKS5 vs HTTP
	br := bufio.NewReader(conn)
	first, err := br.Peek(1)
	if err != nil {
		return
	}

	wrappedConn := &bufferedConn{Conn: conn, reader: br}

	if first[0] == 0x05 {
		s.handleSOCKS5(wrappedConn, mode)
	} else {
		s.handleHTTP(wrappedConn, mode)
	}
}

func (s *Server) handleHTTP(conn net.Conn, mode string) {
	br := bufio.NewReader(conn)
	reqLine, err := br.ReadString('\n')
	if err != nil {
		return
	}

	// Read remaining headers
	var headerBlock strings.Builder
	headerBlock.WriteString(reqLine)
	for {
		line, err := br.ReadString('\n')
		headerBlock.WriteString(line)
		if err != nil || line == "\r\n" || line == "\n" {
			break
		}
	}

	parts := strings.SplitN(strings.TrimSpace(reqLine), " ", 3)
	if len(parts) < 2 {
		return
	}

	method := strings.ToUpper(parts[0])
	target := parts[1]

	if method == "CONNECT" {
		s.handleCONNECT(conn, br, target, mode)
	} else {
		s.handlePlainHTTP(conn, br, method, target, headerBlock.String(), mode)
	}
}

func (s *Server) handleCONNECT(conn net.Conn, br *bufio.Reader, target, mode string) {
	host, portStr, err := net.SplitHostPort(target)
	if err != nil {
		host = target
		portStr = "443"
	}

	log.Info("CONNECT → %s:%s (mode=%s)", host, portStr, mode)

	// Send 200 Connection Established
	conn.Write([]byte("HTTP/1.1 200 Connection Established\r\n\r\n"))

	s.handleTargetTunnel(conn, br, host, portStr, mode)
}

func (s *Server) handleTargetTunnel(conn net.Conn, br *bufio.Reader, host, port, mode string) {
	// Block check
	if config.HostMatchesRules(host, s.cfg.BlockHosts) {
		log.Warn("BLOCKED → %s:%s", host, port)
		conn.Write([]byte("HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n"))
		return
	}

	// Bypass check
	if config.HostMatchesRules(host, s.cfg.BypassHosts) {
		log.Info("Bypass → %s:%s", host, port)
		s.directTunnel(conn, br, host, port)
		return
	}

	switch mode {
	case "direct":
		s.directTunnel(conn, br, host, port)
	case "full":
		// Raw TCP relay (no MITM)
		s.directTunnel(conn, br, host, port)
	case "relay":
		s.mitmAndRelay(conn, br, host, port)
	case "smart":
		s.smartRoute(conn, br, host, port)
	default:
		s.smartRoute(conn, br, host, port)
	}
}

func (s *Server) smartRoute(conn net.Conn, br *bufio.Reader, host, port string) {
	h := strings.ToLower(strings.TrimRight(host, "."))

	// Smart routing order:
	// 1. Force relay (youtube, google domains via smart router)
	if s.router.Enabled() {
		route := s.router.GetRoute(h)
		if route == router.RouteRelay || route == router.RouteForwarder {
			log.Info("Rule: relay → %s:%s", host, port)
			s.mitmAndRelay(conn, br, host, port)
			return
		}
		if route == router.RouteDirect {
			log.Info("Rule: direct → %s:%s", host, port)
			s.directTunnel(conn, br, host, port)
			return
		}
	}

	// Default: relay
	log.Info("Rule: relay (default) → %s:%s", host, port)
	s.mitmAndRelay(conn, br, host, port)
}

func (s *Server) directTunnel(conn net.Conn, br *bufio.Reader, host, port string) {
	target := net.JoinHostPort(host, port)
	remote, err := net.DialTimeout("tcp", target, time.Duration(s.cfg.TCPConnectTimeout)*time.Second)
	if err != nil {
		log.Error("Direct connect failed (%s): %v", target, err)
		return
	}
	defer remote.Close()

	// If there's buffered data from the reader, write it first
	if br.Buffered() > 0 {
		buffered := make([]byte, br.Buffered())
		n, _ := br.Read(buffered)
		if n > 0 {
			remote.Write(buffered[:n])
		}
	}

	// Bidirectional pipe
	pipe(conn, remote)
}

func (s *Server) mitmAndRelay(conn net.Conn, br *bufio.Reader, host, port string) {
	if s.certMgr == nil {
		log.Error("MITM not available (no cert manager)")
		s.directTunnel(conn, br, host, port)
		return
	}

	// Get cert for this domain
	cert, err := s.certMgr.GetCertForHost(host)
	if err != nil {
		log.Error("Generate cert for %s: %v", host, err)
		return
	}

	// TLS handshake with client (we are the server)
	tlsConfig := &tls.Config{
		Certificates: []tls.Certificate{*cert},
	}

	var rawConn net.Conn = conn
	if br.Buffered() > 0 {
		// Wrap with buffered data
		rawConn = &bufferedConn{Conn: conn, reader: br}
	}

	tlsConn := tls.Server(rawConn, tlsConfig)
	if err := tlsConn.Handshake(); err != nil {
		log.Debug("TLS handshake failed for %s: %v", host, err)
		return
	}
	defer tlsConn.Close()

	// Now read decrypted HTTP requests and relay them
	s.relayHTTPStream(tlsConn, host, port)
}

func (s *Server) relayHTTPStream(conn net.Conn, host, port string) {
	br := bufio.NewReader(conn)

	for {
		conn.SetDeadline(time.Now().Add(120 * time.Second))

		req, err := http.ReadRequest(br)
		if err != nil {
			return
		}

		// Build full URL
		scheme := "https"
		if port == "80" {
			scheme = "http"
		}
		fullURL := fmt.Sprintf("%s://%s%s", scheme, host, req.URL.RequestURI())

		log.Info("MITM → %s %s", req.Method, fullURL)

		// Read body
		var body []byte
		if req.Body != nil {
			body, _ = io.ReadAll(req.Body)
			req.Body.Close()
		}

		// Convert headers
		headers := make(map[string]string)
		for k, v := range req.Header {
			headers[k] = strings.Join(v, ", ")
		}

		// CORS preflight — respond locally
		if req.Method == "OPTIONS" && req.Header.Get("Access-Control-Request-Method") != "" {
			corsResp := buildCORSPreflight(req.Header.Get("Origin"),
				req.Header.Get("Access-Control-Request-Method"),
				req.Header.Get("Access-Control-Request-Headers"))
			conn.Write(corsResp)
			continue
		}

		// Relay through Apps Script
		response, err := s.fronter.Relay(req.Method, fullURL, headers, body)
		if err != nil {
			log.Error("Relay error (%s): %v", fullURL, err)
			errBody := fmt.Sprintf("Relay error: %v", err)
			response = []byte(fmt.Sprintf(
				"HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain\r\nContent-Length: %d\r\n\r\n%s",
				len(errBody), errBody,
			))
		}

		// Inject CORS headers if Origin present
		if origin := req.Header.Get("Origin"); origin != "" && response != nil {
			response = injectCORSHeaders(response, origin)
		}

		conn.Write(response)
	}
}

func (s *Server) handlePlainHTTP(conn net.Conn, br *bufio.Reader, method, rawURL, headerBlock, mode string) {
	// Parse headers from headerBlock
	headers := make(map[string]string)
	lines := strings.Split(headerBlock, "\r\n")
	for _, line := range lines[1:] {
		if idx := strings.IndexByte(line, ':'); idx > 0 {
			headers[strings.TrimSpace(line[:idx])] = strings.TrimSpace(line[idx+1:])
		}
	}

	// Read body based on Content-Length
	var body []byte
	if cl := headers["Content-Length"]; cl != "" {
		var length int
		fmt.Sscanf(cl, "%d", &length)
		if length > 0 && length < 100*1024*1024 {
			body = make([]byte, length)
			io.ReadFull(br, body)
		}
	}

	log.Info("HTTP → %s %s", method, rawURL)

	// Relay
	response, err := s.fronter.Relay(method, rawURL, headers, body)
	if err != nil {
		log.Error("Relay error: %v", err)
		errBody := fmt.Sprintf("Relay error: %v", err)
		response = []byte(fmt.Sprintf(
			"HTTP/1.1 502 Bad Gateway\r\nContent-Type: text/plain\r\nContent-Length: %d\r\n\r\n%s",
			len(errBody), errBody,
		))
	}

	conn.Write(response)
}

func (s *Server) handleSOCKS5(conn net.Conn, mode string) {
	br := bufio.NewReader(conn)

	// Read version + nmethods
	header := make([]byte, 2)
	if _, err := io.ReadFull(br, header); err != nil {
		return
	}
	if header[0] != 0x05 {
		return
	}

	// Read methods
	methods := make([]byte, header[1])
	if _, err := io.ReadFull(br, methods); err != nil {
		return
	}

	// No auth
	conn.Write([]byte{0x05, 0x00})

	// Read connect request
	req := make([]byte, 4)
	if _, err := io.ReadFull(br, req); err != nil {
		return
	}
	if req[0] != 0x05 || req[1] != 0x01 {
		conn.Write([]byte{0x05, 0x07, 0x00, 0x01, 0, 0, 0, 0, 0, 0})
		return
	}

	var host string
	switch req[3] {
	case 0x01: // IPv4
		addr := make([]byte, 4)
		io.ReadFull(br, addr)
		host = net.IP(addr).String()
	case 0x03: // Domain
		lenBuf := make([]byte, 1)
		io.ReadFull(br, lenBuf)
		domain := make([]byte, lenBuf[0])
		io.ReadFull(br, domain)
		host = string(domain)
	case 0x04: // IPv6
		addr := make([]byte, 16)
		io.ReadFull(br, addr)
		host = net.IP(addr).String()
	default:
		conn.Write([]byte{0x05, 0x08, 0x00, 0x01, 0, 0, 0, 0, 0, 0})
		return
	}

	portBuf := make([]byte, 2)
	io.ReadFull(br, portBuf)
	port := fmt.Sprintf("%d", int(portBuf[0])<<8|int(portBuf[1]))

	log.Info("SOCKS5 CONNECT → %s:%s", host, port)

	// Success response
	conn.Write([]byte{0x05, 0x00, 0x00, 0x01, 0, 0, 0, 0, 0, 0})

	s.handleTargetTunnel(conn, br, host, port, mode)
}

// --- Helpers ---

func pipe(a, b net.Conn) {
	done := make(chan struct{}, 2)
	cp := func(dst, src net.Conn) {
		io.Copy(dst, src)
		done <- struct{}{}
	}
	go cp(a, b)
	go cp(b, a)
	<-done
}

func buildCORSPreflight(origin, acrMethod, acrHeaders string) []byte {
	if origin == "" {
		origin = "*"
	}
	allowMethods := "GET, POST, PUT, DELETE, PATCH, OPTIONS"
	if acrMethod != "" {
		allowMethods = acrMethod + ", " + allowMethods
	}
	allowHeaders := "*"
	if acrHeaders != "" {
		allowHeaders = acrHeaders
	}
	return []byte(fmt.Sprintf(
		"HTTP/1.1 204 No Content\r\n"+
			"Access-Control-Allow-Origin: %s\r\n"+
			"Access-Control-Allow-Methods: %s\r\n"+
			"Access-Control-Allow-Headers: %s\r\n"+
			"Access-Control-Allow-Credentials: true\r\n"+
			"Access-Control-Max-Age: 86400\r\n"+
			"Content-Length: 0\r\n\r\n",
		origin, allowMethods, allowHeaders,
	))
}

func injectCORSHeaders(response []byte, origin string) []byte {
	sep := []byte("\r\n\r\n")
	idx := bytes.Index(response, sep)
	if idx < 0 {
		return response
	}

	headerSection := string(response[:idx])
	body := response[idx+4:]

	// Remove existing CORS headers
	var lines []string
	for _, line := range strings.Split(headerSection, "\r\n") {
		if !strings.HasPrefix(strings.ToLower(line), "access-control-") {
			lines = append(lines, line)
		}
	}

	// Add permissive CORS
	lines = append(lines,
		fmt.Sprintf("Access-Control-Allow-Origin: %s", origin),
		"Access-Control-Allow-Credentials: true",
		"Access-Control-Allow-Methods: GET, POST, PUT, DELETE, PATCH, OPTIONS",
		"Access-Control-Allow-Headers: *",
		"Access-Control-Expose-Headers: *",
		"Vary: Origin",
	)

	var buf bytes.Buffer
	buf.WriteString(strings.Join(lines, "\r\n"))
	buf.WriteString("\r\n\r\n")
	buf.Write(body)
	return buf.Bytes()
}

// bufferedConn wraps a net.Conn with a bufio.Reader for peeked data.
type bufferedConn struct {
	net.Conn
	reader *bufio.Reader
}

func (c *bufferedConn) Read(b []byte) (int, error) {
	return c.reader.Read(b)
}
