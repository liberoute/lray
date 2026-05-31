// Config file watcher — hot-reload config without restarting.
package config

import (
	"encoding/json"
	"os"
	"time"

	"github.com/liberoute/lray/internal/logger"
)

var log = logger.New("Config")

// Watcher watches config.json for changes and calls a reload callback.
type Watcher struct {
	path     string
	interval time.Duration
	lastMod  time.Time
	stopCh   chan struct{}
	onReload func(*Config)
}

// NewWatcher creates a config file watcher.
func NewWatcher(path string, interval time.Duration, onReload func(*Config)) *Watcher {
	w := &Watcher{
		path:     path,
		interval: interval,
		stopCh:   make(chan struct{}),
		onReload: onReload,
	}
	if info, err := os.Stat(path); err == nil {
		w.lastMod = info.ModTime()
	}
	return w
}

// Start begins watching.
func (w *Watcher) Start() {
	log.Info("Config watcher started (checking every %v)", w.interval)
	go w.loop()
}

// Stop stops watching.
func (w *Watcher) Stop() {
	close(w.stopCh)
}

func (w *Watcher) loop() {
	ticker := time.NewTicker(w.interval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			w.check()
		case <-w.stopCh:
			return
		}
	}
}

func (w *Watcher) check() {
	info, err := os.Stat(w.path)
	if err != nil {
		return
	}

	if !info.ModTime().After(w.lastMod) {
		return
	}
	w.lastMod = info.ModTime()

	log.Info("Config file changed, reloading...")

	data, err := os.ReadFile(w.path)
	if err != nil {
		log.Error("Failed to read config: %v", err)
		return
	}

	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		log.Error("Failed to parse config: %v", err)
		return
	}

	cfg, err := Load(w.path)
	if err != nil {
		log.Error("Failed to reload config: %v", err)
		return
	}

	if w.onReload != nil {
		w.onReload(cfg)
	}

	log.Info("Config reloaded successfully")
}
