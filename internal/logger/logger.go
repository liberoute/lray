// Package logger provides colored, column-aligned logging for lray.
package logger

import (
	"fmt"
	"io"
	"log"
	"os"
	"runtime"
	"strings"
	"sync"
	"time"
)

// ANSI color codes
const (
	reset   = "\x1b[0m"
	bold    = "\x1b[1m"
	dim     = "\x1b[2m"
	fgGray  = "\x1b[38;5;245m"
	fgBlue  = "\x1b[38;5;39m"
	fgCyan  = "\x1b[38;5;45m"
	fgGreen = "\x1b[38;5;42m"
	fgYellow = "\x1b[38;5;214m"
	fgRed   = "\x1b[38;5;203m"
	fgMagenta = "\x1b[38;5;177m"
	fgPurple = "\x1b[38;5;141m"
	fgTeal  = "\x1b[38;5;80m"
	fgOrange = "\x1b[38;5;208m"
)

// Level represents log severity.
type Level int

const (
	LevelDebug Level = iota
	LevelInfo
	LevelWarn
	LevelError
)

var levelNames = map[Level]string{
	LevelDebug: "DEBUG",
	LevelInfo:  "INFO ",
	LevelWarn:  "WARN ",
	LevelError: "ERROR",
}

var levelGlyphs = map[Level]string{
	LevelDebug: "·",
	LevelInfo:  "•",
	LevelWarn:  "!",
	LevelError: "✕",
}

var levelColors = map[Level]string{
	LevelDebug: dim + fgGray,
	LevelInfo:  fgGreen,
	LevelWarn:  bold + fgYellow,
	LevelError: bold + fgRed,
}

var componentColors = map[string]string{
	"Main":    fgCyan,
	"Proxy":   fgBlue,
	"Fronter": fgPurple,
	"H2":      fgTeal,
	"MITM":    fgOrange,
	"Cert":    fgMagenta,
	"Router":  fgGreen,
	"DoH":     fgCyan,
	"PAC":     fgGray,
	"Dash":    fgBlue,
	"Quota":   fgYellow,
	"Scanner": fgTeal,
	"Config":  fgGray,
	"MTProto": fgOrange,
	"Pattern": fgPurple,
}

// Logger is a component-scoped logger.
type Logger struct {
	component string
	color     bool
}

var (
	globalLevel Level = LevelInfo
	globalColor bool
	globalMu    sync.RWMutex
	output      io.Writer = os.Stderr
)

func init() {
	globalColor = supportsColor()
	log.SetFlags(0)
	log.SetOutput(os.Stderr)
}

// Configure sets the global log level.
func Configure(level string) {
	globalMu.Lock()
	defer globalMu.Unlock()
	switch strings.ToUpper(level) {
	case "DEBUG":
		globalLevel = LevelDebug
	case "INFO":
		globalLevel = LevelInfo
	case "WARNING", "WARN":
		globalLevel = LevelWarn
	case "ERROR":
		globalLevel = LevelError
	default:
		globalLevel = LevelInfo
	}
}

// SetOutput sets the log output writer.
func SetOutput(w io.Writer) {
	globalMu.Lock()
	defer globalMu.Unlock()
	output = w
}

// New creates a logger for a named component.
func New(component string) *Logger {
	return &Logger{
		component: component,
		color:     globalColor,
	}
}

func (l *Logger) log(level Level, format string, args ...any) {
	globalMu.RLock()
	if level < globalLevel {
		globalMu.RUnlock()
		return
	}
	w := output
	globalMu.RUnlock()

	now := time.Now()
	timeStr := now.Format("15:04:05")
	msg := fmt.Sprintf(format, args...)

	comp := l.component
	if len(comp) > 8 {
		comp = comp[:8]
	}
	comp = fmt.Sprintf("%-8s", comp)

	if l.color {
		compColor := componentColors[l.component]
		if compColor == "" {
			compColor = fgGray
		}
		line := fmt.Sprintf("%s%s%s%s  %s%s %s%s  %s[%s%s%s%s]%s  %s\n",
			dim, fgGray, timeStr, reset,
			levelColors[level], levelGlyphs[level], levelNames[level], reset,
			dim, reset, compColor, comp, reset+dim, reset,
			msg,
		)
		fmt.Fprint(w, line)
	} else {
		line := fmt.Sprintf("%s  %s %s  [%s]  %s\n",
			timeStr, levelGlyphs[level], levelNames[level], comp, msg)
		fmt.Fprint(w, line)
	}
}

func (l *Logger) Debug(format string, args ...any) { l.log(LevelDebug, format, args...) }
func (l *Logger) Info(format string, args ...any)  { l.log(LevelInfo, format, args...) }
func (l *Logger) Warn(format string, args ...any)  { l.log(LevelWarn, format, args...) }
func (l *Logger) Error(format string, args ...any) { l.log(LevelError, format, args...) }

func supportsColor() bool {
	if os.Getenv("NO_COLOR") != "" {
		return false
	}
	if os.Getenv("FORCE_COLOR") != "" {
		return true
	}
	if runtime.GOOS == "windows" {
		// Most modern Windows terminals support ANSI
		return os.Getenv("WT_SESSION") != "" || os.Getenv("TERM_PROGRAM") != ""
	}
	fi, _ := os.Stderr.Stat()
	if fi == nil {
		return false
	}
	return fi.Mode()&os.ModeCharDevice != 0
}

// PrintBanner prints the startup banner.
func PrintBanner(version string) {
	title := " lray "
	subtitle := " Domain-Fronted GAS-CFW Relay "
	versionTag := fmt.Sprintf(" v%s ", version)

	innerWidth := 68
	gap := innerWidth - (len(title) + len(subtitle) + len(versionTag))
	leftGap := gap / 2
	rightGap := gap - leftGap

	top := "╭" + strings.Repeat("─", innerWidth) + "╮"
	mid := "│" + title + strings.Repeat(" ", leftGap) + subtitle + strings.Repeat(" ", rightGap) + versionTag + "│"
	bot := "╰" + strings.Repeat("─", innerWidth) + "╯"

	if globalColor {
		fmt.Fprintf(os.Stderr, "%s%s%s%s\n", dim, fgGray, top, reset)
		fmt.Fprintf(os.Stderr, "%s%s│%s%s%s%s%s%s%s%s%s%s%s%s│%s\n",
			dim, fgGray, reset,
			bold, fgCyan, title, reset,
			strings.Repeat(" ", leftGap),
			fgGray, subtitle, reset,
			strings.Repeat(" ", rightGap),
			bold+fgTeal, versionTag, reset,
		)
		fmt.Fprintf(os.Stderr, "%s%s%s%s\n", dim, fgGray, bot, reset)
	} else {
		fmt.Fprintln(os.Stderr, top)
		fmt.Fprintln(os.Stderr, mid)
		fmt.Fprintln(os.Stderr, bot)
	}
}
