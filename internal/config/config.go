// Package config handles loading and normalizing lray configuration.
package config

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// Config is the normalized flat configuration used by all components.
type Config struct {
	// Identity
	Mode     string `json:"mode"`
	ExitMode string `json:"exit_mode"`
	AuthKey  string `json:"auth_key"`

	// Script IDs (single or multiple)
	ScriptID  string   `json:"script_id"`
	ScriptIDs []string `json:"script_ids"`

	// Relay
	GoogleIP          string   `json:"google_ip"`
	FrontDomain       string   `json:"front_domain"`
	FrontDomains      []string `json:"front_domains"`
	RelayTimeout      float64  `json:"relay_timeout"`
	TLSConnectTimeout float64  `json:"tls_connect_timeout"`
	TCPConnectTimeout float64  `json:"tcp_connect_timeout"`
	ParallelRelay     int      `json:"parallel_relay"`
	VerifySSL         bool     `json:"verify_ssl"`

	// Listeners
	ListenHost string     `json:"listen_host"`
	ListenPort int        `json:"listen_port"`
	Listeners  []Listener `json:"listeners"`
	LANSharing bool       `json:"lan_sharing"`

	// Routing
	SmartRouting       bool     `json:"smart_routing"`
	BypassHosts        []string `json:"bypass_hosts"`
	BlockHosts         []string `json:"block_hosts"`
	ForwarderHosts     []string `json:"forwarder_hosts"`
	YouTubeViaRelay    bool     `json:"youtube_via_relay"`
	DirectGoogleExclude []string `json:"direct_google_exclude"`
	DirectGoogleAllow   []string `json:"direct_google_allow"`

	// Advanced
	DOHEnabled     bool              `json:"doh_enabled"`
	HotReload      bool              `json:"hot_reload"`
	LogLevel       string            `json:"log_level"`
	PatternihaSync bool              `json:"patterniha_sync"`
	Hosts          map[string]string `json:"hosts"`

	// PAC
	PACEnabled bool `json:"pac_enabled"`
	PACPort    int  `json:"pac_port"`

	// Dashboard
	DashboardEnabled bool `json:"dashboard_enabled"`
	DashboardPort    int  `json:"dashboard_port"`

	// Download tuning
	ChunkedDownloadMinSize    int `json:"chunked_download_min_size"`
	ChunkedDownloadChunkSize  int `json:"chunked_download_chunk_size"`
	ChunkedDownloadMaxParallel int `json:"chunked_download_max_parallel"`
	ChunkedDownloadMaxChunks  int `json:"chunked_download_max_chunks"`

	// Internal
	ConfigPath string `json:"-"`
}

// Listener represents a single proxy listener.
type Listener struct {
	Port   int    `json:"port"`
	Type   string `json:"type"`   // mixed, http, socks5, mtproto
	Mode   string `json:"mode"`   // smart, relay, full, direct, mitm
	Secret string `json:"secret"` // for mtproto
}

// Load reads and normalizes a config file.
func Load(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read config: %w", err)
	}

	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		return nil, fmt.Errorf("parse config: %w", err)
	}

	// First try direct unmarshal into Config
	cfg := &Config{
		// Defaults
		Mode:              "apps_script",
		GoogleIP:          "216.239.38.120",
		FrontDomain:       "www.google.com",
		RelayTimeout:      25,
		TLSConnectTimeout: 15,
		TCPConnectTimeout: 10,
		ParallelRelay:     1,
		VerifySSL:         true,
		ListenHost:        "127.0.0.1",
		ListenPort:        2801,
		SmartRouting:      true,
		DOHEnabled:        true,
		HotReload:         true,
		LogLevel:          "INFO",
		PatternihaSync:    true,
		PACEnabled:        true,
		DashboardEnabled:  true,
		ChunkedDownloadMinSize:    5 * 1024 * 1024,
		ChunkedDownloadChunkSize:  512 * 1024,
		ChunkedDownloadMaxParallel: 8,
		ChunkedDownloadMaxChunks:  256,
		Hosts:             make(map[string]string),
		BypassHosts:       []string{"localhost", ".local", ".lan", ".home.arpa"},
	}

	// Unmarshal the full raw JSON into cfg
	if err := json.Unmarshal(data, cfg); err != nil {
		return nil, fmt.Errorf("unmarshal config: %w", err)
	}

	// Normalize nested format
	cfg.normalize(data)
	cfg.ConfigPath, _ = filepath.Abs(path)
	cfg.Mode = "apps_script"

	// Ensure listeners exist
	if len(cfg.Listeners) == 0 {
		mode := "smart"
		if cfg.SmartRouting {
			mode = "smart"
		}
		cfg.Listeners = []Listener{
			{Port: cfg.ListenPort, Type: "mixed", Mode: mode},
		}
	}

	return cfg, nil
}

// GetScriptIDs returns the list of script IDs.
func (c *Config) GetScriptIDs() []string {
	if len(c.ScriptIDs) > 0 {
		return c.ScriptIDs
	}
	if c.ScriptID != "" {
		return []string{c.ScriptID}
	}
	return nil
}

func (c *Config) normalize(data []byte) {
	// Parse nested sections
	var nested struct {
		Proxies  *proxiesSection  `json:"proxies"`
		Relay    *relaySection    `json:"relay"`
		Routing  *routingSection  `json:"routing"`
		Advanced *advancedSection `json:"advanced"`
		Dashboard *dashSection   `json:"dashboard"`
		PAC      *pacSection      `json:"pac"`
	}
	json.Unmarshal(data, &nested)

	if nested.Proxies != nil {
		c.LANSharing = nested.Proxies.LANSharing
		if c.LANSharing {
			c.ListenHost = "0.0.0.0"
		}
		if len(nested.Proxies.Listeners) > 0 {
			c.Listeners = nested.Proxies.Listeners
			for _, l := range c.Listeners {
				if l.Type == "mixed" || l.Type == "http" {
					c.ListenPort = l.Port
					break
				}
			}
		}
	}

	if nested.Relay != nil {
		if nested.Relay.GoogleIP != "" {
			c.GoogleIP = nested.Relay.GoogleIP
		}
		if nested.Relay.FrontDomain != "" {
			c.FrontDomain = nested.Relay.FrontDomain
		}
		if nested.Relay.Timeout > 0 {
			c.RelayTimeout = nested.Relay.Timeout
		}
		if nested.Relay.TLSConnectTimeout > 0 {
			c.TLSConnectTimeout = nested.Relay.TLSConnectTimeout
		}
		if nested.Relay.TCPConnectTimeout > 0 {
			c.TCPConnectTimeout = nested.Relay.TCPConnectTimeout
		}
		if nested.Relay.ParallelRelay > 0 {
			c.ParallelRelay = nested.Relay.ParallelRelay
		}
		c.VerifySSL = nested.Relay.VerifySSL
	}

	if nested.Routing != nil {
		c.SmartRouting = nested.Routing.SmartRouting
		if len(nested.Routing.BypassHosts) > 0 {
			c.BypassHosts = nested.Routing.BypassHosts
		}
		c.BlockHosts = nested.Routing.BlockHosts
		c.ForwarderHosts = nested.Routing.ForwarderHosts
		c.YouTubeViaRelay = nested.Routing.YouTubeViaRelay
		c.DirectGoogleExclude = nested.Routing.DirectGoogleExclude
		c.DirectGoogleAllow = nested.Routing.DirectGoogleAllow
	}

	if nested.Advanced != nil {
		c.DOHEnabled = nested.Advanced.DOHEnabled
		c.HotReload = nested.Advanced.HotReload
		if nested.Advanced.LogLevel != "" {
			c.LogLevel = nested.Advanced.LogLevel
		}
		c.PatternihaSync = nested.Advanced.PatternihaSync
		if nested.Advanced.Hosts != nil {
			c.Hosts = nested.Advanced.Hosts
		}
	}

	if nested.Dashboard != nil {
		c.DashboardEnabled = nested.Dashboard.Enabled
		if nested.Dashboard.Port > 0 {
			c.DashboardPort = nested.Dashboard.Port
		}
	}

	if nested.PAC != nil {
		c.PACEnabled = nested.PAC.Enabled
		if nested.PAC.Port > 0 {
			c.PACPort = nested.PAC.Port
		}
	}

	// Set default ports relative to listen port
	if c.PACPort == 0 {
		c.PACPort = c.ListenPort + 1
	}
	if c.DashboardPort == 0 {
		c.DashboardPort = c.ListenPort + 2
	}
}

// Validate checks for required fields.
func (c *Config) Validate() error {
	if c.AuthKey == "" {
		return fmt.Errorf("missing required config key: auth_key")
	}
	placeholders := []string{"", "CHANGE_ME_TO_A_STRONG_SECRET", "your-secret-password-here"}
	for _, p := range placeholders {
		if c.AuthKey == p {
			return fmt.Errorf("auth_key is unset or uses a known placeholder")
		}
	}
	sids := c.GetScriptIDs()
	if len(sids) == 0 || sids[0] == "YOUR_APPS_SCRIPT_DEPLOYMENT_ID" {
		return fmt.Errorf("missing script_id in config")
	}
	return nil
}

// DataDir returns the directory containing the config file.
func (c *Config) DataDir() string {
	if c.ConfigPath == "" {
		return "."
	}
	return filepath.Dir(c.ConfigPath)
}

// --- Nested section types ---

type proxiesSection struct {
	LANSharing bool       `json:"lan_sharing"`
	Listeners  []Listener `json:"listeners"`
}

type relaySection struct {
	GoogleIP          string  `json:"google_ip"`
	FrontDomain       string  `json:"front_domain"`
	Timeout           float64 `json:"timeout"`
	TLSConnectTimeout float64 `json:"tls_connect_timeout"`
	TCPConnectTimeout float64 `json:"tcp_connect_timeout"`
	ParallelRelay     int     `json:"parallel_relay"`
	VerifySSL         bool    `json:"verify_ssl"`
}

type routingSection struct {
	SmartRouting        bool     `json:"smart_routing"`
	BypassHosts         []string `json:"bypass_hosts"`
	BlockHosts          []string `json:"block_hosts"`
	ForwarderHosts      []string `json:"forwarder_hosts"`
	YouTubeViaRelay     bool     `json:"youtube_via_relay"`
	DirectGoogleExclude []string `json:"direct_google_exclude"`
	DirectGoogleAllow   []string `json:"direct_google_allow"`
}

type advancedSection struct {
	DOHEnabled     bool              `json:"doh_enabled"`
	HotReload      bool              `json:"hot_reload"`
	LogLevel       string            `json:"log_level"`
	PatternihaSync bool              `json:"patterniha_sync"`
	Hosts          map[string]string `json:"hosts"`
}

type dashSection struct {
	Enabled bool `json:"enabled"`
	Port    int  `json:"port"`
}

type pacSection struct {
	Enabled bool `json:"enabled"`
	Port    int  `json:"port"`
}

// HostMatchesRules checks if a host matches exact or suffix rules.
func HostMatchesRules(host string, rules []string) bool {
	h := strings.ToLower(strings.TrimRight(host, "."))
	for _, rule := range rules {
		r := strings.ToLower(strings.TrimSpace(rule))
		if r == "" {
			continue
		}
		if strings.HasPrefix(r, ".") {
			if strings.HasSuffix(h, r) || h == r[1:] {
				return true
			}
		} else if h == r {
			return true
		}
	}
	return false
}
