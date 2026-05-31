// Package mitm handles TLS interception with dynamic certificate generation.
package mitm

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"net"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/liberoute/lray/internal/logger"
)

var log = logger.New("MITM")

// CertManager generates and caches per-domain TLS certificates.
type CertManager struct {
	caKey  *rsa.PrivateKey
	caCert *x509.Certificate
	cache  map[string]*tls.Certificate
	mu     sync.RWMutex
	caDir  string
}

// New creates a CertManager, loading or generating the CA.
func New(caDir string) (*CertManager, error) {
	if caDir == "" {
		caDir = "ca"
	}

	m := &CertManager{
		cache: make(map[string]*tls.Certificate),
		caDir: caDir,
	}

	keyFile := filepath.Join(caDir, "ca.key")
	certFile := filepath.Join(caDir, "ca.crt")

	if fileExists(keyFile) && fileExists(certFile) {
		if err := m.loadCA(keyFile, certFile); err != nil {
			return nil, err
		}
		log.Info("Loaded CA from %s", caDir)
	} else {
		if err := m.createCA(keyFile, certFile); err != nil {
			return nil, err
		}
		log.Warn("Generated new CA certificate: %s", certFile)
		log.Warn(">>> Install this file in your browser's Trusted Root CAs! <<<")
	}

	return m, nil
}

// CACertFile returns the path to the CA certificate file.
func (m *CertManager) CACertFile() string {
	return filepath.Join(m.caDir, "ca.crt")
}

// GetServerConfig returns a tls.Config that dynamically generates certs.
func (m *CertManager) GetServerConfig() *tls.Config {
	return &tls.Config{
		GetCertificate: func(hello *tls.ClientHelloInfo) (*tls.Certificate, error) {
			return m.getCert(hello.ServerName)
		},
	}
}

// GetCertForHost returns a TLS certificate for the given domain.
func (m *CertManager) GetCertForHost(domain string) (*tls.Certificate, error) {
	return m.getCert(domain)
}

func (m *CertManager) getCert(domain string) (*tls.Certificate, error) {
	m.mu.RLock()
	if cert, ok := m.cache[domain]; ok {
		m.mu.RUnlock()
		return cert, nil
	}
	m.mu.RUnlock()

	m.mu.Lock()
	defer m.mu.Unlock()

	// Double-check after acquiring write lock
	if cert, ok := m.cache[domain]; ok {
		return cert, nil
	}

	cert, err := m.generateCert(domain)
	if err != nil {
		return nil, err
	}
	m.cache[domain] = cert
	return cert, nil
}

func (m *CertManager) generateCert(domain string) (*tls.Certificate, error) {
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		return nil, err
	}

	serial, _ := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	now := time.Now()

	template := &x509.Certificate{
		SerialNumber: serial,
		Subject:      pkix.Name{CommonName: domain},
		NotBefore:    now,
		NotAfter:     now.Add(365 * 24 * time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}

	// SAN: IP or DNS
	if ip := net.ParseIP(domain); ip != nil {
		template.IPAddresses = []net.IP{ip}
	} else {
		template.DNSNames = []string{domain}
	}

	certDER, err := x509.CreateCertificate(rand.Reader, template, m.caCert, &key.PublicKey, m.caKey)
	if err != nil {
		return nil, err
	}

	tlsCert := &tls.Certificate{
		Certificate: [][]byte{certDER, m.caCert.Raw},
		PrivateKey:  key,
	}

	return tlsCert, nil
}

func (m *CertManager) loadCA(keyFile, certFile string) error {
	keyPEM, err := os.ReadFile(keyFile)
	if err != nil {
		return err
	}
	block, _ := pem.Decode(keyPEM)
	if block == nil {
		return os.ErrInvalid
	}
	key, err := x509.ParsePKCS1PrivateKey(block.Bytes)
	if err != nil {
		// Try PKCS8
		keyI, err2 := x509.ParsePKCS8PrivateKey(block.Bytes)
		if err2 != nil {
			return err
		}
		key = keyI.(*rsa.PrivateKey)
	}
	m.caKey = key

	certPEM, err := os.ReadFile(certFile)
	if err != nil {
		return err
	}
	block, _ = pem.Decode(certPEM)
	if block == nil {
		return os.ErrInvalid
	}
	cert, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return err
	}
	m.caCert = cert

	return nil
}

func (m *CertManager) createCA(keyFile, certFile string) error {
	os.MkdirAll(m.caDir, 0755)

	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		return err
	}
	m.caKey = key

	serial, _ := rand.Int(rand.Reader, new(big.Int).Lsh(big.NewInt(1), 128))
	now := time.Now()

	template := &x509.Certificate{
		SerialNumber: serial,
		Subject: pkix.Name{
			CommonName:   "lray",
			Organization: []string{"lray"},
		},
		NotBefore:             now,
		NotAfter:              now.Add(10 * 365 * 24 * time.Hour),
		IsCA:                  true,
		MaxPathLen:            0,
		MaxPathLenZero:        true,
		BasicConstraintsValid: true,
		KeyUsage:              x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign | x509.KeyUsageCRLSign,
	}

	certDER, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		return err
	}

	cert, err := x509.ParseCertificate(certDER)
	if err != nil {
		return err
	}
	m.caCert = cert

	// Write key
	keyPEM := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(key)})
	if err := os.WriteFile(keyFile, keyPEM, 0600); err != nil {
		return err
	}

	// Write cert
	certPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: certDER})
	if err := os.WriteFile(certFile, certPEM, 0644); err != nil {
		return err
	}

	return nil
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}
