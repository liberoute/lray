// Package fronter implements the GAS domain fronting relay engine.
package fronter

import (
	"bytes"
	"context"
	"crypto/sha1"
	"crypto/tls"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"sync/atomic"
	"time"

	"github.com/liberoute/lray/internal/codec"
	"github.com/liberoute/lray/internal/logger"
	"github.com/liberoute/lray/internal/quota"
)

var log = logger.New("Fronter")

// stripHeaders are never forwarded to the upstream server.
var stripHeaders = map[string]bool{
	"accept-encoding":    true,
	"x-forwarded-for":    true,
	"x-forwarded-host":   true,
	"x-forwarded-proto":  true,
	"x-forwarded-port":   true,
	"x-real-ip":          true,
	"forwarded":          true,
	"via":                true,
	"proxy-authorization": true,
	"proxy-connection":   true,
}

// DomainFronter relays HTTP requests through Google Apps Script.
type DomainFronter struct {
	connectHost string
	sniHost     string
	sniHosts    []string
	sniIdx      uint64
	httpHost    string
	scriptIDs   []string
	scriptIdx   uint64
	authKey     string
	verifySSL   bool

	relayTimeout      time.Duration
	tlsConnectTimeout time.Duration

	quotaTracker *quota.Tracker
	client       *http.Client

	totalRequests atomic.Int64
}

// New creates a DomainFronter.
func New(connectHost, sniHost string, sniHosts []string, scriptIDs []string,
	authKey string, verifySSL bool, relayTimeout, tlsTimeout time.Duration,
	qt *quota.Tracker) *DomainFronter {

	if len(sniHosts) == 0 {
		sniHosts = []string{sniHost}
	}

	f := &DomainFronter{
		connectHost:       connectHost,
		sniHost:           sniHost,
		sniHosts:          sniHosts,
		httpHost:          "script.google.com",
		scriptIDs:         scriptIDs,
		authKey:           authKey,
		verifySSL:         verifySSL,
		relayTimeout:      relayTimeout,
		tlsConnectTimeout: tlsTimeout,
		quotaTracker:      qt,
	}

	// Create HTTP client with custom transport for domain fronting
	f.client = &http.Client{
		Timeout: relayTimeout,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{
				ServerName:         sniHost,
				InsecureSkipVerify: !verifySSL,
			},
			DialTLSContext: f.dialTLS,
			MaxIdleConns:        50,
			MaxIdleConnsPerHost: 50,
			IdleConnTimeout:     30 * time.Second,
			DisableCompression:  false,
		},
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if len(via) >= 5 {
				return fmt.Errorf("too many redirects")
			}
			return nil
		},
	}

	log.Info("Response codecs: %s", codec.SupportedEncodings())
	if len(sniHosts) > 1 {
		log.Info("SNI rotation pool (%d): %s", len(sniHosts), strings.Join(sniHosts, ", "))
	}

	return f
}

func (f *DomainFronter) dialTLS(ctx context.Context, network, addr string) (net.Conn, error) {
	// Always connect to our configured Google IP
	sni := f.nextSNI()
	dialer := &net.Dialer{Timeout: f.tlsConnectTimeout}
	conn, err := tls.DialWithDialer(dialer, "tcp",
		net.JoinHostPort(f.connectHost, "443"),
		&tls.Config{
			ServerName:         sni,
			InsecureSkipVerify: !f.verifySSL,
		},
	)
	if err != nil {
		return nil, err
	}
	// Set TCP_NODELAY
	if tc, ok := conn.NetConn().(*net.TCPConn); ok {
		tc.SetNoDelay(true)
	}
	return conn, nil
}

func (f *DomainFronter) nextSNI() string {
	idx := atomic.AddUint64(&f.sniIdx, 1)
	return f.sniHosts[int(idx)%len(f.sniHosts)]
}

func (f *DomainFronter) nextScriptID(hostKey string) string {
	if len(f.scriptIDs) == 1 {
		sid := f.scriptIDs[0]
		if f.quotaTracker != nil {
			f.quotaTracker.RecordRequest(sid)
		}
		return sid
	}

	// Quota-aware selection
	if f.quotaTracker != nil {
		best := f.quotaTracker.GetBestScript(f.scriptIDs)
		if best != "" {
			f.quotaTracker.RecordRequest(best)
			return best
		}
	}

	// Stable per-host selection
	if hostKey != "" {
		h := sha1.Sum([]byte(hostKey))
		base := int(h[0])<<24 | int(h[1])<<16 | int(h[2])<<8 | int(h[3])
		idx := base % len(f.scriptIDs)
		if idx < 0 {
			idx = -idx
		}
		sid := f.scriptIDs[idx]
		if f.quotaTracker != nil {
			f.quotaTracker.RecordRequest(sid)
		}
		return sid
	}

	// Round-robin fallback
	idx := atomic.AddUint64(&f.scriptIdx, 1)
	sid := f.scriptIDs[int(idx)%len(f.scriptIDs)]
	if f.quotaTracker != nil {
		f.quotaTracker.RecordRequest(sid)
	}
	return sid
}

func (f *DomainFronter) execPath(hostKey string) string {
	sid := f.nextScriptID(hostKey)
	return fmt.Sprintf("/macros/s/%s/exec", sid)
}

// Relay sends an HTTP request through Apps Script and returns the raw HTTP response.
func (f *DomainFronter) Relay(method, targetURL string, headers map[string]string, body []byte) ([]byte, error) {
	f.totalRequests.Add(1)

	payload := f.buildPayload(method, targetURL, headers, body)
	payload["k"] = f.authKey

	jsonBody, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("marshal payload: %w", err)
	}

	hostKey := extractHost(targetURL)
	path := f.execPath(hostKey)
	reqURL := fmt.Sprintf("https://%s%s", f.httpHost, path)

	req, err := http.NewRequest("POST", reqURL, bytes.NewReader(jsonBody))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept-Encoding", codec.SupportedEncodings())

	resp, err := f.client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("relay request: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read relay response: %w", err)
	}

	// Decompress if needed
	if enc := resp.Header.Get("Content-Encoding"); enc != "" {
		respBody = codec.Decode(respBody, enc)
	}

	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("upstream HTTP %d", resp.StatusCode)
	}

	return f.parseRelayResponse(respBody)
}

func (f *DomainFronter) buildPayload(method, targetURL string, headers map[string]string, body []byte) map[string]interface{} {
	payload := map[string]interface{}{
		"m": method,
		"u": targetURL,
		"r": false,
	}

	if len(headers) > 0 {
		filtered := make(map[string]string)
		for k, v := range headers {
			if !stripHeaders[strings.ToLower(k)] {
				filtered[k] = v
			}
		}
		if len(filtered) > 0 {
			payload["h"] = filtered
		}
	}

	if len(body) > 0 {
		payload["b"] = base64.StdEncoding.EncodeToString(body)
		if ct, ok := headers["Content-Type"]; ok {
			payload["ct"] = ct
		} else if ct, ok := headers["content-type"]; ok {
			payload["ct"] = ct
		}
	}

	return payload
}

func (f *DomainFronter) parseRelayResponse(body []byte) ([]byte, error) {
	text := strings.TrimSpace(string(body))
	if text == "" {
		return errorResponse(502, "Empty response from relay"), nil
	}

	var data map[string]interface{}
	if err := json.Unmarshal([]byte(text), &data); err != nil {
		// Try to extract JSON from response
		re := regexp.MustCompile(`\{.*\}`)
		match := re.Find(body)
		if match == nil {
			return errorResponse(502, "No JSON in relay response"), nil
		}
		if err := json.Unmarshal(match, &data); err != nil {
			return errorResponse(502, "Bad JSON in relay response"), nil
		}
	}

	if errMsg, ok := data["e"]; ok {
		return errorResponse(502, fmt.Sprintf("Relay error: %v", errMsg)), nil
	}

	status := 200
	if s, ok := data["s"].(float64); ok {
		status = int(s)
	}

	respHeaders := make(map[string]interface{})
	if h, ok := data["h"].(map[string]interface{}); ok {
		respHeaders = h
	}

	var respBody []byte
	if b, ok := data["b"].(string); ok {
		respBody, _ = base64.StdEncoding.DecodeString(b)
	}

	// Build raw HTTP response
	statusText := http.StatusText(status)
	if statusText == "" {
		statusText = "OK"
	}

	var buf bytes.Buffer
	fmt.Fprintf(&buf, "HTTP/1.1 %d %s\r\n", status, statusText)

	skipHeaders := map[string]bool{
		"transfer-encoding": true,
		"connection":        true,
		"keep-alive":        true,
		"content-length":    true,
		"content-encoding":  true,
	}

	for k, v := range respHeaders {
		if skipHeaders[strings.ToLower(k)] {
			continue
		}
		switch val := v.(type) {
		case string:
			fmt.Fprintf(&buf, "%s: %s\r\n", k, val)
		case []interface{}:
			for _, item := range val {
				fmt.Fprintf(&buf, "%s: %v\r\n", k, item)
			}
		default:
			fmt.Fprintf(&buf, "%s: %v\r\n", k, val)
		}
	}

	fmt.Fprintf(&buf, "Content-Length: %d\r\n", len(respBody))
	buf.WriteString("\r\n")
	buf.Write(respBody)

	return buf.Bytes(), nil
}

// Close shuts down the fronter.
func (f *DomainFronter) Close() {
	f.client.CloseIdleConnections()
}

// ConnectHost returns the configured Google IP.
func (f *DomainFronter) ConnectHost() string {
	return f.connectHost
}

// SNIHost returns the configured front domain.
func (f *DomainFronter) SNIHost() string {
	return f.sniHost
}

func errorResponse(status int, message string) []byte {
	body := fmt.Sprintf("<html><body><h1>%d</h1><p>%s</p></body></html>", status, message)
	return []byte(fmt.Sprintf(
		"HTTP/1.1 %d Error\r\nContent-Type: text/html\r\nContent-Length: %d\r\n\r\n%s",
		status, len(body), body,
	))
}

func extractHost(rawURL string) string {
	if rawURL == "" {
		return ""
	}
	u, err := url.Parse(rawURL)
	if err != nil {
		return ""
	}
	return strings.ToLower(strings.TrimRight(u.Hostname(), "."))
}
