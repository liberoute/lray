// Package patterniha syncs MITM-DomainFronting config from GitHub
// and provides domain→SNI mappings for direct domain fronting.
package patterniha

import (
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/liberoute/lray/internal/logger"
)

var log = logger.New("Pattern")

const (
	configURL     = "https://raw.githubusercontent.com/patterniha/MITM-DomainFronting/main/Xray-config/MITM-DomainFronting.json"
	checkInterval = 1 * time.Hour
)

// SNIMapping represents a domain fronting mapping.
type SNIMapping struct {
	SNI         string
	ConnectHost string
	ALPN        []string
}

// Sync manages patterniha config sync and provides routing info.
type Sync struct {
	enabled   bool
	dataDir   string
	cachePath string

	mu              sync.RWMutex
	mappings        map[string]*SNIMapping // exact domain → mapping
	suffixMappings  []suffixEntry          // suffix rules
	version         string
	lastCheck       time.Time
	stopCh          chan struct{}
}

type suffixEntry struct {
	suffix  string
	mapping *SNIMapping
}

// New creates a patterniha sync instance.
func New(enabled bool, dataDir string) *Sync {
	s := &Sync{
		enabled:   enabled,
		dataDir:   dataDir,
		cachePath: filepath.Join(dataDir, "patterniha_config.json"),
		mappings:  make(map[string]*SNIMapping),
		stopCh:    make(chan struct{}),
	}
	if enabled {
		s.loadCache()
	}
	return s
}

// Enabled returns whether patterniha sync is active.
func (s *Sync) Enabled() bool {
	return s.enabled
}

// GetSNIMapping returns the SNI mapping for a host, or nil.
func (s *Sync) GetSNIMapping(host string) *SNIMapping {
	if !s.enabled {
		return nil
	}

	s.mu.RLock()
	defer s.mu.RUnlock()

	h := strings.ToLower(strings.TrimRight(host, "."))

	// Exact match
	if m, ok := s.mappings[h]; ok {
		return m
	}

	// Suffix match
	for _, entry := range s.suffixMappings {
		if strings.HasSuffix(h, entry.suffix) || h == strings.TrimPrefix(entry.suffix, ".") {
			return entry.mapping
		}
	}

	return nil
}

// Start begins background update loop.
func (s *Sync) Start() {
	if !s.enabled {
		return
	}

	// Initial fetch if no cache
	if len(s.mappings) == 0 {
		go func() {
			time.Sleep(5 * time.Second) // wait for proxy to be ready
			s.fetchAndParse()
		}()
	}

	go s.updateLoop()
}

// Stop stops background updates.
func (s *Sync) Stop() {
	close(s.stopCh)
}

func (s *Sync) updateLoop() {
	ticker := time.NewTicker(checkInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			s.fetchAndParse()
		case <-s.stopCh:
			return
		}
	}
}

func (s *Sync) fetchAndParse() {
	log.Info("Checking patterniha config for updates...")

	resp, err := http.Get(configURL)
	if err != nil {
		log.Debug("Download failed: %v", err)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		log.Debug("Download returned %d", resp.StatusCode)
		return
	}

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		log.Debug("Read failed: %v", err)
		return
	}

	var config map[string]interface{}
	if err := json.Unmarshal(data, &config); err != nil {
		log.Debug("Parse failed: %v", err)
		return
	}

	s.parseXrayConfig(config)
	s.lastCheck = time.Now()

	// Save cache
	os.WriteFile(s.cachePath, data, 0644)

	s.mu.RLock()
	log.Info("Patterniha config updated (%d mappings, %d suffix rules)",
		len(s.mappings), len(s.suffixMappings))
	s.mu.RUnlock()
}

func (s *Sync) parseXrayConfig(config map[string]interface{}) {
	mappings := make(map[string]*SNIMapping)
	var suffixMappings []suffixEntry

	// Parse dns.hosts for resolving internal redirect names
	dnsHosts := make(map[string]string)
	if dns, ok := config["dns"].(map[string]interface{}); ok {
		if hosts, ok := dns["hosts"].(map[string]interface{}); ok {
			for hostname, target := range hosts {
				switch v := target.(type) {
				case string:
					if !strings.HasPrefix(v, "#") {
						dnsHosts[hostname] = v
					}
				case []interface{}:
					if len(v) > 0 {
						if s, ok := v[0].(string); ok {
							dnsHosts[hostname] = s
						}
					}
				}
			}
		}
	}

	// Parse outbounds to get tag → SNIMapping
	outboundMap := make(map[string]*SNIMapping)
	if outbounds, ok := config["outbounds"].([]interface{}); ok {
		for _, ob := range outbounds {
			outbound, ok := ob.(map[string]interface{})
			if !ok {
				continue
			}
			tag, _ := outbound["tag"].(string)
			if !strings.HasPrefix(tag, "tls-repack-") {
				continue
			}

			stream, _ := outbound["streamSettings"].(map[string]interface{})
			if stream == nil {
				continue
			}
			security, _ := stream["security"].(string)
			if security != "tls" {
				continue
			}

			tlsSettings, _ := stream["tlsSettings"].(map[string]interface{})
			if tlsSettings == nil {
				continue
			}

			sni, _ := tlsSettings["serverName"].(string)
			if sni == "" || sni == "fromMitM" {
				continue
			}

			// Get connect target
			connectHost := ""
			if settings, ok := outbound["settings"].(map[string]interface{}); ok {
				if redirect, ok := settings["redirect"].(string); ok && redirect != "" {
					if idx := strings.LastIndex(redirect, ":"); idx > 0 {
						connectHost = redirect[:idx]
					} else {
						connectHost = redirect
					}
				}
			}

			// Resolve via dns.hosts
			if connectHost != "" {
				if resolved, ok := dnsHosts[connectHost]; ok {
					connectHost = resolved
				}
			}

			if connectHost == "" {
				connectHost = sni
			}

			outboundMap[tag] = &SNIMapping{
				SNI:         sni,
				ConnectHost: connectHost,
				ALPN:        []string{"h2", "http/1.1"},
			}
		}
	}

	// Parse routing rules to map domains → outbound tags
	if routing, ok := config["routing"].(map[string]interface{}); ok {
		if rules, ok := routing["rules"].([]interface{}); ok {
			for _, r := range rules {
				rule, ok := r.(map[string]interface{})
				if !ok {
					continue
				}

				outboundTag, _ := rule["outboundTag"].(string)
				mapping, ok := outboundMap[outboundTag]
				if !ok {
					continue
				}

				domains, _ := rule["domain"].([]interface{})
				for _, d := range domains {
					domainRule, ok := d.(string)
					if !ok {
						continue
					}

					if strings.HasPrefix(domainRule, "domain:") {
						suffix := "." + domainRule[7:]
						suffixMappings = append(suffixMappings, suffixEntry{suffix, mapping})
					} else if strings.HasPrefix(domainRule, "full:") {
						mappings[domainRule[5:]] = mapping
					} else if strings.HasPrefix(domainRule, "geosite:") {
						for _, d := range expandGeosite(domainRule[8:]) {
							if strings.HasPrefix(d, ".") {
								suffixMappings = append(suffixMappings, suffixEntry{d, mapping})
							} else {
								mappings[d] = mapping
							}
						}
					} else {
						mappings[domainRule] = mapping
					}
				}
			}
		}
	}

	s.mu.Lock()
	s.mappings = mappings
	s.suffixMappings = suffixMappings
	s.mu.Unlock()
}

func (s *Sync) loadCache() {
	data, err := os.ReadFile(s.cachePath)
	if err != nil {
		return
	}

	var config map[string]interface{}
	if err := json.Unmarshal(data, &config); err != nil {
		return
	}

	s.parseXrayConfig(config)
	log.Info("Loaded cached patterniha config (%d mappings)", len(s.mappings))
}

func expandGeosite(name string) []string {
	known := map[string][]string{
		"google": {
			".google.com", ".googleapis.com", ".gstatic.com",
			".googleusercontent.com", ".googlevideo.com",
			".youtube.com", ".ytimg.com", ".ggpht.com",
		},
		"vercel":  {".vercel.com", ".vercel.app", ".nextjs.org"},
		"fastly":  {".fastly.com", ".fastly.net", ".fastlylb.net"},
		"reddit":  {".reddit.com", ".redd.it", ".redditstatic.com"},
		"github":  {".github.com", ".github.io", ".githubusercontent.com", ".githubassets.com"},
		"netlify": {".netlify.com", ".netlify.app"},
	}
	if domains, ok := known[name]; ok {
		return domains
	}
	return nil
}
