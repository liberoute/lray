// Package quota tracks GAS script usage and persists across restarts.
package quota

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/liberoute/lray/internal/logger"
)

var log = logger.New("Quota")

const (
	defaultDailyLimit = 20000
	saveInterval      = 30 * time.Second
)

// ScriptQuota holds quota state for a single script.
type ScriptQuota struct {
	ScriptID       string  `json:"script_id"`
	DisplayID      string  `json:"display_id"`
	RequestsToday  int     `json:"requests_today"`
	DailyLimit     int     `json:"daily_limit"`
	FirstRequestAt float64 `json:"first_request_at"`
	ResetAt        float64 `json:"reset_at"`
	Exhausted      bool    `json:"exhausted"`
	ExhaustedAt    float64 `json:"exhausted_at"`
	LastRequestAt  float64 `json:"last_request_at"`
	Errors         int     `json:"errors"`
}

// Tracker tracks quota usage for all GAS scripts.
type Tracker struct {
	scripts  map[string]*ScriptQuota
	dataFile string
	mu       sync.Mutex
	dirty    bool
	lastSave time.Time
}

// New creates a quota tracker.
func New(scriptIDs []string, dataDir string) *Tracker {
	t := &Tracker{
		scripts:  make(map[string]*ScriptQuota),
		dataFile: filepath.Join(dataDir, "quota_state.json"),
	}

	for _, sid := range scriptIDs {
		short := sid
		if len(sid) > 12 {
			short = sid[len(sid)-12:]
		}
		t.scripts[sid] = &ScriptQuota{
			ScriptID:   sid,
			DisplayID:  short,
			DailyLimit: defaultDailyLimit,
		}
	}

	t.load()
	return t
}

// RecordRequest records a request to a script.
func (t *Tracker) RecordRequest(scriptID string) {
	t.mu.Lock()
	defer t.mu.Unlock()

	q := t.getOrCreate(scriptID)
	now := float64(time.Now().Unix())

	// Check if period has reset
	if q.ResetAt > 0 && now > q.ResetAt {
		q.RequestsToday = 0
		q.Exhausted = false
		q.ExhaustedAt = 0
		q.FirstRequestAt = now
		q.ResetAt = now + 86400
	}

	if q.FirstRequestAt == 0 {
		q.FirstRequestAt = now
		q.ResetAt = now + 86400
	}

	q.RequestsToday++
	q.LastRequestAt = now
	t.dirty = true
	t.maybeSave()
}

// RecordExhausted marks a script as quota-exhausted.
func (t *Tracker) RecordExhausted(scriptID string) {
	t.mu.Lock()
	defer t.mu.Unlock()

	q := t.getOrCreate(scriptID)
	q.Exhausted = true
	q.ExhaustedAt = float64(time.Now().Unix())
	q.Errors++
	t.dirty = true
	t.save()

	log.Warn("Script %s quota exhausted (%d requests today)", q.DisplayID, q.RequestsToday)
}

// IsExhausted checks if a script's quota is exhausted.
func (t *Tracker) IsExhausted(scriptID string) bool {
	t.mu.Lock()
	defer t.mu.Unlock()

	q, ok := t.scripts[scriptID]
	if !ok {
		return false
	}

	now := float64(time.Now().Unix())
	if q.Exhausted && q.ResetAt > 0 && now > q.ResetAt {
		q.Exhausted = false
		q.RequestsToday = 0
		q.FirstRequestAt = 0
		t.dirty = true
		return false
	}

	return q.Exhausted
}

// GetBestScript returns the script with most remaining quota.
func (t *Tracker) GetBestScript(scriptIDs []string) string {
	t.mu.Lock()
	defer t.mu.Unlock()

	var best string
	bestRemaining := -1

	for _, sid := range scriptIDs {
		if t.isExhaustedLocked(sid) {
			continue
		}
		q, ok := t.scripts[sid]
		remaining := defaultDailyLimit
		if ok {
			remaining = q.DailyLimit - q.RequestsToday
		}
		if remaining > bestRemaining {
			bestRemaining = remaining
			best = sid
		}
	}

	return best
}

func (t *Tracker) isExhaustedLocked(scriptID string) bool {
	q, ok := t.scripts[scriptID]
	if !ok {
		return false
	}
	now := float64(time.Now().Unix())
	if q.Exhausted && q.ResetAt > 0 && now > q.ResetAt {
		q.Exhausted = false
		q.RequestsToday = 0
		return false
	}
	return q.Exhausted
}

func (t *Tracker) getOrCreate(scriptID string) *ScriptQuota {
	q, ok := t.scripts[scriptID]
	if !ok {
		short := scriptID
		if len(scriptID) > 12 {
			short = scriptID[len(scriptID)-12:]
		}
		q = &ScriptQuota{
			ScriptID:   scriptID,
			DisplayID:  short,
			DailyLimit: defaultDailyLimit,
		}
		t.scripts[scriptID] = q
	}
	return q
}

func (t *Tracker) maybeSave() {
	if time.Since(t.lastSave) > saveInterval && t.dirty {
		t.save()
	}
}

func (t *Tracker) save() {
	data := make(map[string]map[string]interface{})
	for sid, q := range t.scripts {
		data[sid] = map[string]interface{}{
			"requests_today":   q.RequestsToday,
			"first_request_at": q.FirstRequestAt,
			"reset_at":         q.ResetAt,
			"exhausted":        q.Exhausted,
			"exhausted_at":     q.ExhaustedAt,
			"errors":           q.Errors,
			"last_request_at":  q.LastRequestAt,
		}
	}

	b, err := json.MarshalIndent(data, "", "  ")
	if err != nil {
		return
	}
	os.WriteFile(t.dataFile, b, 0644)
	t.lastSave = time.Now()
	t.dirty = false
}

func (t *Tracker) load() {
	data, err := os.ReadFile(t.dataFile)
	if err != nil {
		return
	}

	var raw map[string]map[string]interface{}
	if err := json.Unmarshal(data, &raw); err != nil {
		return
	}

	now := float64(time.Now().Unix())
	for sid, state := range raw {
		q := t.getOrCreate(sid)
		if v, ok := state["requests_today"].(float64); ok {
			q.RequestsToday = int(v)
		}
		if v, ok := state["first_request_at"].(float64); ok {
			q.FirstRequestAt = v
		}
		if v, ok := state["reset_at"].(float64); ok {
			q.ResetAt = v
		}
		if v, ok := state["exhausted"].(bool); ok {
			q.Exhausted = v
		}
		if v, ok := state["exhausted_at"].(float64); ok {
			q.ExhaustedAt = v
		}
		if v, ok := state["errors"].(float64); ok {
			q.Errors = int(v)
		}

		// Auto-reset expired periods
		if q.ResetAt > 0 && now > q.ResetAt {
			q.RequestsToday = 0
			q.Exhausted = false
			q.FirstRequestAt = 0
			q.ResetAt = 0
		}
	}

	log.Info("Loaded quota state: %d scripts", len(raw))
}
