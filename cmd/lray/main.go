// lray — Domain-Fronted GAS-CFW Relay
//
// A censorship bypass tool that uses domain fronting through Google's
// infrastructure. DPI only sees traffic to www.google.com, but the actual
// payload goes through Google Apps Script to reach blocked websites.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/liberoute/lray/internal/certinstall"
	"github.com/liberoute/lray/internal/config"
	"github.com/liberoute/lray/internal/fronter"
	"github.com/liberoute/lray/internal/logger"
	"github.com/liberoute/lray/internal/mitm"
	"github.com/liberoute/lray/internal/pac"
	"github.com/liberoute/lray/internal/proxy"
	"github.com/liberoute/lray/internal/quota"
	"github.com/liberoute/lray/internal/router"
	"github.com/liberoute/lray/internal/scanner"
)

const version = "1.2.0"

func main() {
	var (
		configPath  = flag.String("config", envOr("DFT_CONFIG", "config.json"), "Path to config file")
		portOverride = flag.Int("port", 0, "Override listen port")
		logLevel    = flag.String("log-level", "", "Override log level (DEBUG, INFO, WARNING, ERROR)")
		showVersion = flag.Bool("version", false, "Show version and exit")
		installCert = flag.Bool("install-cert", false, "Install MITM CA certificate")
		scan        = flag.Bool("scan", false, "Scan Google IPs for fastest one")
	)
	flag.Parse()

	if *showVersion {
		fmt.Printf("lray v%s\n", version)
		os.Exit(0)
	}

	if *scan {
		logger.Configure("INFO")
		cfg, err := config.Load(*configPath)
		frontDomain := "www.google.com"
		if err == nil && cfg.FrontDomain != "" {
			frontDomain = cfg.FrontDomain
		}
		ok := scanner.Run(frontDomain)
		if ok {
			os.Exit(0)
		}
		os.Exit(1)
	}

	if *installCert {
		logger.Configure("INFO")
		caDir := "ca"
		if cfgDir := filepath.Dir(*configPath); cfgDir != "" && cfgDir != "." {
			caDir = filepath.Join(cfgDir, "ca")
		}
		cm, err := mitm.New(caDir)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error: %v\n", err)
			os.Exit(1)
		}
		ok := certinstall.Install(cm.CACertFile())
		if ok {
			os.Exit(0)
		}
		os.Exit(1)
	}

	// Load config
	cfg, err := config.Load(*configPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		fmt.Fprintln(os.Stderr, "Run setup or copy config.example.json to config.json")
		os.Exit(1)
	}

	if err := cfg.Validate(); err != nil {
		fmt.Fprintf(os.Stderr, "Config error: %v\n", err)
		os.Exit(1)
	}

	// Apply overrides
	if *portOverride > 0 {
		cfg.ListenPort = *portOverride
		// Update first listener port too
		if len(cfg.Listeners) > 0 {
			cfg.Listeners[0].Port = *portOverride
		}
	}
	if *logLevel != "" {
		cfg.LogLevel = *logLevel
	}

	// Setup logging
	logger.Configure(cfg.LogLevel)
	log := logger.New("Main")

	logger.PrintBanner(version)
	log.Info("lray starting (Apps Script relay)")
	log.Info("Apps Script relay: SNI=%s → script.google.com", cfg.FrontDomain)

	scriptIDs := cfg.GetScriptIDs()
	if len(scriptIDs) > 1 {
		log.Info("Script IDs: %d scripts (sticky per-host)", len(scriptIDs))
	} else {
		log.Info("Script ID: ...%s", scriptIDs[0][max(0, len(scriptIDs[0])-12):])
	}

	// Initialize components
	caDir := filepath.Join(cfg.DataDir(), "ca")
	certMgr, err := mitm.New(caDir)
	if err != nil {
		log.Error("Failed to initialize MITM: %v", err)
		os.Exit(1)
	}
	log.Info("MITM CA is ready")

	// Quota tracker
	qt := quota.New(scriptIDs, cfg.DataDir())

	// Domain fronter
	sniHosts := cfg.FrontDomains
	if len(sniHosts) == 0 {
		sniHosts = []string{cfg.FrontDomain}
	}
	df := fronter.New(
		cfg.GoogleIP,
		cfg.FrontDomain,
		sniHosts,
		scriptIDs,
		cfg.AuthKey,
		cfg.VerifySSL,
		time.Duration(cfg.RelayTimeout*float64(time.Second)),
		time.Duration(cfg.TLSConnectTimeout*float64(time.Second)),
		qt,
	)

	// Smart router
	sr := router.New(
		cfg.SmartRouting,
		cfg.ForwarderHosts,
		cfg.BypassHosts,
		cfg.YouTubeViaRelay,
		nil, // force_relay_hosts from config
	)

	// Proxy server
	srv := proxy.New(cfg, df, certMgr, sr)

	// PAC server
	if cfg.PACEnabled {
		socksPort := 0
		for _, l := range cfg.Listeners {
			if l.Type == "socks5" {
				socksPort = l.Port
				break
			}
		}
		pacSrv := pac.New(cfg.ListenHost, cfg.ListenPort, socksPort, cfg.PACPort, cfg.BypassHosts)
		if err := pacSrv.Start(cfg.ListenHost); err != nil {
			log.Warn("PAC server failed: %v", err)
		}
		defer pacSrv.Stop(context.Background())
	}

	// Start proxy
	if err := srv.Start(); err != nil {
		log.Error("Failed to start: %v", err)
		os.Exit(1)
	}

	// Wait for signal
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	<-sigCh

	log.Info("Shutting down...")
	srv.Stop()
	log.Info("Stopped")
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}
