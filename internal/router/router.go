// Package router implements rule-based routing for each host.
package router

import (
	"strings"
)

// Route represents the routing decision for a host.
type Route string

const (
	RouteDirect    Route = "direct"
	RouteRelay     Route = "relay"
	RouteForwarder Route = "forwarder"
)

// SmartRouter decides direct/relay/forwarder per host based on config rules.
type SmartRouter struct {
	enabled        bool
	forwarderExact map[string]bool
	forwarderSuffix []string
	bypassExact    map[string]bool
	bypassSuffix   []string
	forceRelayExact map[string]bool
	forceRelaySuffix []string
}

// New creates a SmartRouter from config values.
func New(enabled bool, forwarderHosts, bypassHosts []string, youtubeViaRelay bool, forceRelayHosts []string) *SmartRouter {
	r := &SmartRouter{enabled: enabled}

	r.forwarderExact, r.forwarderSuffix = loadRules(forwarderHosts)
	r.bypassExact, r.bypassSuffix = loadRules(bypassHosts)

	// Build force relay list
	relay := make([]string, 0, len(forceRelayHosts))
	relay = append(relay, forceRelayHosts...)
	if youtubeViaRelay {
		relay = append(relay,
			".youtube.com", ".youtu.be", ".ytimg.com",
			".ggpht.com", ".googlevideo.com",
			".google.com", ".googleapis.com", ".gstatic.com",
			".googleusercontent.com",
		)
	}
	// Always relay githubusercontent (patterniha needs it on first start)
	relay = append(relay, ".githubusercontent.com")
	r.forceRelayExact, r.forceRelaySuffix = loadRules(relay)

	return r
}

// Enabled returns whether smart routing is active.
func (r *SmartRouter) Enabled() bool {
	return r.enabled
}

// GetRoute returns the route for a host.
func (r *SmartRouter) GetRoute(host string) Route {
	if !r.enabled {
		return RouteRelay
	}

	h := strings.ToLower(strings.TrimRight(host, "."))

	if matches(h, r.forwarderExact, r.forwarderSuffix) {
		return RouteForwarder
	}
	if matches(h, r.forceRelayExact, r.forceRelaySuffix) {
		return RouteRelay
	}
	if matches(h, r.bypassExact, r.bypassSuffix) {
		return RouteDirect
	}
	return RouteRelay
}

func loadRules(raw []string) (map[string]bool, []string) {
	exact := make(map[string]bool)
	var suffixes []string
	for _, item := range raw {
		h := strings.ToLower(strings.TrimSpace(strings.TrimRight(item, ".")))
		if h == "" {
			continue
		}
		if strings.HasPrefix(h, ".") {
			suffixes = append(suffixes, h)
		} else {
			exact[h] = true
		}
	}
	return exact, suffixes
}

func matches(host string, exact map[string]bool, suffixes []string) bool {
	if exact[host] {
		return true
	}
	for _, s := range suffixes {
		if strings.HasSuffix(host, s) {
			return true
		}
	}
	return false
}
