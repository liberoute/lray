// Package resolver implements DNS-over-HTTPS resolution with caching and failover.
package resolver

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/liberoute/lray/internal/logger"
)

var log = logger.New("DoH")

type cacheEntry struct {
	ip      string
	expires time.Time
}

type provider struct {
	name     string
	host     string
	ip       string
	path     string
	failures int
	lastFail time.Time
}

const (
	failureCooldown = 60 * time.Second
	maxFailures     = 3
)

// Resolver is an async DNS-over-HTTPS resolver with caching and failover.
type Resolver struct {
	providers []*provider
	cache     map[string]cacheEntry
	cacheTTL  time.Duration
	timeout   time.Duration
	mu        sync.RWMutex
	client    *http.Client
}

// New creates a DoH resolver.
func New(cacheTTL time.Duration, timeout time.Duration) *Resolver {
	if cacheTTL == 0 {
		cacheTTL = 5 * time.Minute
	}
	if timeout == 0 {
		timeout = 5 * time.Second
	}

	r := &Resolver{
		providers: []*provider{
			{name: "Cloudflare", host: "cloudflare-dns.com", ip: "1.1.1.1", path: "/dns-query"},
			{name: "Google", host: "dns.google", ip: "8.8.8.8", path: "/dns-query"},
			{name: "Quad9", host: "dns9.quad9.net", ip: "9.9.9.9", path: "/dns-query"},
		},
		cache:    make(map[string]cacheEntry),
		cacheTTL: cacheTTL,
		timeout:  timeout,
	}

	// Custom transport that dials directly to the provider IP
	r.client = &http.Client{
		Timeout: timeout,
		Transport: &http.Transport{
			TLSClientConfig: &tls.Config{},
			DialContext: func(ctx context.Context, network, addr string) (net.Conn, error) {
				// addr will be like "1.1.1.1:443"
				d := net.Dialer{Timeout: timeout}
				return d.DialContext(ctx, network, addr)
			},
		},
	}

	return r
}

// Resolve resolves a hostname to an IP address using DoH.
func (r *Resolver) Resolve(hostname string) (string, error) {
	hostname = strings.ToLower(strings.TrimRight(hostname, "."))

	// Check cache
	r.mu.RLock()
	if entry, ok := r.cache[hostname]; ok && time.Now().Before(entry.expires) {
		r.mu.RUnlock()
		return entry.ip, nil
	}
	r.mu.RUnlock()

	// Try each provider
	for _, p := range r.availableProviders() {
		ip, err := r.query(p, hostname)
		if err != nil {
			p.failures++
			p.lastFail = time.Now()
			log.Debug("DoH query failed (%s): %v", p.name, err)
			continue
		}
		if ip != "" {
			r.mu.Lock()
			r.cache[hostname] = cacheEntry{ip: ip, expires: time.Now().Add(r.cacheTTL)}
			r.mu.Unlock()
			p.failures = 0
			return ip, nil
		}
	}

	return "", fmt.Errorf("all DoH providers failed for %s", hostname)
}

func (r *Resolver) availableProviders() []*provider {
	now := time.Now()
	var available []*provider
	for _, p := range r.providers {
		if p.failures >= maxFailures && now.Sub(p.lastFail) < failureCooldown {
			continue
		}
		if p.failures >= maxFailures {
			p.failures = 0
		}
		available = append(available, p)
	}
	if len(available) == 0 {
		return r.providers
	}
	return available
}

func (r *Resolver) query(p *provider, hostname string) (string, error) {
	params := url.Values{}
	params.Set("name", hostname)
	params.Set("type", "A")

	reqURL := fmt.Sprintf("https://%s%s?%s", p.ip, p.path, params.Encode())
	req, err := http.NewRequest("GET", reqURL, nil)
	if err != nil {
		return "", err
	}
	req.Host = p.host
	req.Header.Set("Accept", "application/dns-json")

	resp, err := r.client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", err
	}

	var result dnsResponse
	if err := json.Unmarshal(body, &result); err != nil {
		return "", err
	}

	if result.Status != 0 {
		return "", nil
	}

	for _, answer := range result.Answer {
		if answer.Type == 1 || answer.Type == 28 { // A or AAAA
			return answer.Data, nil
		}
	}

	return "", nil
}

// ClearCache clears the DNS cache.
func (r *Resolver) ClearCache() {
	r.mu.Lock()
	r.cache = make(map[string]cacheEntry)
	r.mu.Unlock()
}

type dnsResponse struct {
	Status int         `json:"Status"`
	Answer []dnsAnswer `json:"Answer"`
}

type dnsAnswer struct {
	Type int    `json:"type"`
	Data string `json:"data"`
}
