// Package certinstall handles cross-platform CA certificate installation.
package certinstall

import (
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"

	"github.com/liberoute/lray/internal/logger"
)

var log = logger.New("Cert")

// Install installs the CA certificate as a trusted root on the current platform.
func Install(certPath string) bool {
	log.Info("Installing CA certificate on %s...", runtime.GOOS)

	switch runtime.GOOS {
	case "windows":
		return installWindows(certPath)
	case "darwin":
		return installMacOS(certPath)
	case "linux":
		return installLinux(certPath)
	default:
		log.Error("Unsupported platform: %s", runtime.GOOS)
		return false
	}
}

// Uninstall removes the CA certificate from trusted roots.
func Uninstall(certPath string) bool {
	log.Info("Removing CA certificate on %s...", runtime.GOOS)

	switch runtime.GOOS {
	case "windows":
		return uninstallWindows(certPath)
	case "darwin":
		return uninstallMacOS()
	case "linux":
		return uninstallLinux()
	default:
		log.Error("Unsupported platform: %s", runtime.GOOS)
		return false
	}
}

// IsTrusted checks if the CA cert is already installed.
func IsTrusted(certPath string) bool {
	switch runtime.GOOS {
	case "windows":
		return isTrustedWindows(certPath)
	case "darwin":
		return isTrustedMacOS()
	case "linux":
		return isTrustedLinux()
	default:
		return false
	}
}

// --- Windows ---

func installWindows(certPath string) bool {
	// Try user store first (no admin)
	cmd := exec.Command("certutil", "-addstore", "-user", "Root", certPath)
	if err := cmd.Run(); err == nil {
		log.Info("Certificate installed in Windows user Trusted Root store.")
		return true
	}

	// Try system store (needs admin)
	cmd = exec.Command("certutil", "-addstore", "Root", certPath)
	if err := cmd.Run(); err == nil {
		log.Info("Certificate installed in Windows system Trusted Root store.")
		return true
	}

	// PowerShell fallback
	psCmd := fmt.Sprintf("Import-Certificate -FilePath '%s' -CertStoreLocation Cert:\\CurrentUser\\Root", certPath)
	cmd = exec.Command("powershell", "-NoProfile", "-Command", psCmd)
	if err := cmd.Run(); err == nil {
		log.Info("Certificate installed via PowerShell.")
		return true
	}

	log.Error("Failed to install certificate on Windows.")
	return false
}

func uninstallWindows(certPath string) bool {
	cmd := exec.Command("certutil", "-delstore", "-user", "Root", "lray")
	if err := cmd.Run(); err == nil {
		log.Info("Certificate removed from Windows user store.")
		return true
	}
	cmd = exec.Command("certutil", "-delstore", "Root", "lray")
	if err := cmd.Run(); err == nil {
		log.Info("Certificate removed from Windows system store.")
		return true
	}
	return false
}

func isTrustedWindows(certPath string) bool {
	cmd := exec.Command("certutil", "-user", "-store", "Root")
	out, err := cmd.Output()
	if err != nil {
		return false
	}
	return strings.Contains(string(out), "lray")
}

// --- macOS ---

func installMacOS(certPath string) bool {
	cmd := exec.Command("security", "add-trusted-cert", "-d", "-r", "trustRoot",
		"-k", expandHome("~/Library/Keychains/login.keychain-db"), certPath)
	if err := cmd.Run(); err == nil {
		log.Info("Certificate installed in macOS login keychain.")
		return true
	}

	cmd = exec.Command("sudo", "security", "add-trusted-cert", "-d", "-r", "trustRoot",
		"-k", "/Library/Keychains/System.keychain", certPath)
	if err := cmd.Run(); err == nil {
		log.Info("Certificate installed in macOS system keychain.")
		return true
	}

	return false
}

func uninstallMacOS() bool {
	cmd := exec.Command("security", "delete-certificate", "-c", "lray")
	return cmd.Run() == nil
}

func isTrustedMacOS() bool {
	cmd := exec.Command("security", "find-certificate", "-a", "-c", "lray")
	out, err := cmd.Output()
	if err != nil {
		return false
	}
	return len(out) > 0
}

// --- Linux ---

func installLinux(certPath string) bool {
	// Try Debian/Ubuntu
	if hasCmd("update-ca-certificates") {
		dest := "/usr/local/share/ca-certificates/lray.crt"
		cmd := exec.Command("sudo", "cp", certPath, dest)
		if err := cmd.Run(); err == nil {
			exec.Command("sudo", "update-ca-certificates").Run()
			log.Info("Certificate installed via update-ca-certificates.")
			return true
		}
	}

	// Try RHEL/Fedora
	if hasCmd("update-ca-trust") {
		dest := "/etc/pki/ca-trust/source/anchors/lray.crt"
		cmd := exec.Command("sudo", "cp", certPath, dest)
		if err := cmd.Run(); err == nil {
			exec.Command("sudo", "update-ca-trust", "extract").Run()
			log.Info("Certificate installed via update-ca-trust.")
			return true
		}
	}

	// Try Arch
	if hasCmd("trust") {
		dest := "/etc/ca-certificates/trust-source/anchors/lray.crt"
		cmd := exec.Command("sudo", "cp", certPath, dest)
		if err := cmd.Run(); err == nil {
			exec.Command("sudo", "trust", "extract-compat").Run()
			log.Info("Certificate installed via trust extract-compat.")
			return true
		}
	}

	log.Warn("Unknown Linux distro. Manually install %s as a trusted root CA.", certPath)
	return false
}

func uninstallLinux() bool {
	paths := []string{
		"/usr/local/share/ca-certificates/lray.crt",
		"/etc/pki/ca-trust/source/anchors/lray.crt",
		"/etc/ca-certificates/trust-source/anchors/lray.crt",
	}
	for _, p := range paths {
		exec.Command("sudo", "rm", "-f", p).Run()
	}
	exec.Command("sudo", "update-ca-certificates").Run()
	exec.Command("sudo", "update-ca-trust", "extract").Run()
	return true
}

func isTrustedLinux() bool {
	paths := []string{
		"/usr/local/share/ca-certificates/lray.crt",
		"/etc/pki/ca-trust/source/anchors/lray.crt",
		"/etc/ca-certificates/trust-source/anchors/lray.crt",
	}
	for _, p := range paths {
		if fileExists(p) {
			return true
		}
	}
	return false
}

// --- Helpers ---

func hasCmd(name string) bool {
	_, err := exec.LookPath(name)
	return err == nil
}

func expandHome(path string) string {
	if len(path) > 1 && path[0] == '~' {
		home, _ := exec.Command("sh", "-c", "echo $HOME").Output()
		if len(home) > 0 {
			return string(home[:len(home)-1]) + path[1:]
		}
	}
	return path
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
