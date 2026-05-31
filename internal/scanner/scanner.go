// Package scanner finds the fastest reachable Google frontend IP.
package scanner

import (
	"crypto/tls"
	"fmt"
	"net"
	"sort"
	"sync"
	"time"

	"github.com/liberoute/lray/internal/logger"
)

var log = logger.New("Scanner")

// CandidateIPs are Google frontend IPs to probe.
var CandidateIPs = []string{
	"216.239.32.120", "216.239.34.120", "216.239.36.120", "216.239.38.120",
	"142.250.80.142", "142.250.80.138", "142.250.179.110", "142.250.185.110",
	"142.250.184.206", "142.250.190.238", "142.250.191.78",
	"172.217.1.206", "172.217.14.206", "172.217.16.142", "172.217.22.174",
	"172.217.164.110", "172.217.168.206", "172.217.169.206",
	"34.107.221.82",
	"142.251.32.110", "142.251.33.110", "142.251.46.206", "142.251.46.238",
	"142.250.80.170", "142.250.72.206", "142.250.64.206", "142.250.72.110",
}

// ProbeResult holds the result of a single IP probe.
type ProbeResult struct {
	IP        string
	LatencyMs int
	Error     string
}

// Run scans all candidate IPs and displays results.
func Run(frontDomain string) bool {
	timeout := 4 * time.Second
	concurrency := 8

	fmt.Println()
	fmt.Printf("Scanning %d Google frontend IPs\n", len(CandidateIPs))
	fmt.Printf("  SNI: %s\n", frontDomain)
	fmt.Printf("  Timeout: %v per IP\n", timeout)
	fmt.Printf("  Concurrency: %d parallel probes\n", concurrency)
	fmt.Println()

	sem := make(chan struct{}, concurrency)
	var mu sync.Mutex
	var results []ProbeResult
	var wg sync.WaitGroup

	for _, ip := range CandidateIPs {
		wg.Add(1)
		go func(ip string) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			result := probeIP(ip, frontDomain, timeout)
			mu.Lock()
			results = append(results, result)
			mu.Unlock()
		}(ip)
	}
	wg.Wait()

	// Sort: successful first, then by latency
	sort.Slice(results, func(i, j int) bool {
		iOK := results[i].Error == ""
		jOK := results[j].Error == ""
		if iOK != jOK {
			return iOK
		}
		return results[i].LatencyMs < results[j].LatencyMs
	})

	// Display
	fmt.Printf("%-20s %-12s %-25s\n", "IP", "LATENCY", "STATUS")
	fmt.Printf("%-20s %-12s %-25s\n", "--------------------", "------------", "-------------------------")

	okCount := 0
	for _, r := range results {
		if r.Error == "" {
			fmt.Printf("%-20s %8dms   OK\n", r.IP, r.LatencyMs)
			okCount++
		} else {
			fmt.Printf("%-20s %-12s %s\n", r.IP, "—", r.Error)
		}
	}

	fmt.Println()
	fmt.Printf("Result: %d / %d reachable\n", okCount, len(results))

	if okCount == 0 {
		fmt.Println("No Google IPs reachable from this network.")
		return false
	}

	// Top 3
	fmt.Println()
	fmt.Println("Top 3 fastest IPs:")
	count := 0
	for _, r := range results {
		if r.Error == "" {
			count++
			fmt.Printf("  %d. %s (%dms)\n", count, r.IP, r.LatencyMs)
			if count >= 3 {
				break
			}
		}
	}

	fmt.Println()
	fmt.Printf("Recommended: Set \"google_ip\": \"%s\" in config.json\n", results[0].IP)
	fmt.Println()
	return true
}

func probeIP(ip, sni string, timeout time.Duration) ProbeResult {
	start := time.Now()

	conn, err := net.DialTimeout("tcp", ip+":443", timeout)
	if err != nil {
		return ProbeResult{IP: ip, Error: fmt.Sprintf("connect: %v", err)}
	}
	defer conn.Close()

	conn.SetDeadline(time.Now().Add(timeout))

	tlsConn := tls.Client(conn, &tls.Config{
		ServerName:         sni,
		InsecureSkipVerify: true,
	})
	if err := tlsConn.Handshake(); err != nil {
		return ProbeResult{IP: ip, Error: fmt.Sprintf("tls: %v", err)}
	}
	defer tlsConn.Close()

	// Send minimal HTTP request
	req := fmt.Sprintf("HEAD / HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n", sni)
	if _, err := tlsConn.Write([]byte(req)); err != nil {
		return ProbeResult{IP: ip, Error: fmt.Sprintf("write: %v", err)}
	}

	buf := make([]byte, 256)
	n, err := tlsConn.Read(buf)
	if err != nil && n == 0 {
		return ProbeResult{IP: ip, Error: "empty response"}
	}

	elapsed := time.Since(start).Milliseconds()
	return ProbeResult{IP: ip, LatencyMs: int(elapsed)}
}
