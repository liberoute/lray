// Package mtproto implements an MTProto proxy for Telegram with batching.
package mtproto

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"fmt"
	"io"
	"net"
	"sync"
	"sync/atomic"
	"time"

	"github.com/liberoute/lray/internal/logger"
)

var log = logger.New("MTProto")

// Telegram DC addresses
var telegramDCs = map[int]string{
	1: "149.154.175.50:443",
	2: "149.154.167.50:443",
	3: "149.154.175.100:443",
	4: "149.154.167.91:443",
	5: "91.108.56.100:443",
}

// Proxy is an MTProto proxy server.
type Proxy struct {
	port    int
	secret  []byte
	fakeTLS bool
	mode    string // "relay" or "direct"

	totalConns  atomic.Int64
	activeConns atomic.Int64

	listener net.Listener
	mu       sync.Mutex
}

// New creates an MTProto proxy.
func New(port int, secretHex, mode string) *Proxy {
	p := &Proxy{
		port: port,
		mode: mode,
	}
	p.parseSecret(secretHex)
	return p
}

func (p *Proxy) parseSecret(s string) {
	if s == "" {
		return
	}
	// Remove "ee" prefix (fake-TLS) or "dd" prefix
	if len(s) == 34 && (s[:2] == "ee" || s[:2] == "dd") {
		if s[:2] == "ee" {
			p.fakeTLS = true
		}
		s = s[2:]
	}
	// Decode hex
	p.secret = make([]byte, len(s)/2)
	for i := 0; i < len(s)/2; i++ {
		fmt.Sscanf(s[i*2:i*2+2], "%02x", &p.secret[i])
	}
}

// Start starts the MTProto proxy listener.
func (p *Proxy) Start(host string) error {
	addr := fmt.Sprintf("%s:%d", host, p.port)
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return err
	}
	p.listener = ln

	secretPreview := ""
	if len(p.secret) > 4 {
		secretPreview = fmt.Sprintf("%x...", p.secret[:4])
	}
	log.Info("MTProto proxy on %s (secret=%s, fake_tls=%v)", addr, secretPreview, p.fakeTLS)

	go p.acceptLoop()
	return nil
}

// Stop stops the MTProto proxy.
func (p *Proxy) Stop() {
	if p.listener != nil {
		p.listener.Close()
	}
}

func (p *Proxy) acceptLoop() {
	for {
		conn, err := p.listener.Accept()
		if err != nil {
			return
		}
		p.totalConns.Add(1)
		p.activeConns.Add(1)
		go func() {
			defer p.activeConns.Add(-1)
			p.handleConn(conn)
		}()
	}
}

func (p *Proxy) handleConn(conn net.Conn) {
	defer conn.Close()
	conn.SetDeadline(time.Now().Add(60 * time.Second))

	var dcID int
	var err error

	if p.fakeTLS {
		dcID, err = p.handleFakeTLS(conn)
	} else {
		dcID, err = p.handleObfuscated2(conn)
	}

	if err != nil {
		log.Debug("MTProto handshake failed: %v", err)
		return
	}

	dcAddr, ok := telegramDCs[abs(dcID)]
	if !ok {
		dcAddr = telegramDCs[2] // default DC2
	}

	log.Info("MTProto → DC%d (%s)", dcID, dcAddr)

	// Direct tunnel to Telegram DC
	remote, err := net.DialTimeout("tcp", dcAddr, 10*time.Second)
	if err != nil {
		log.Warn("MTProto connect to DC%d failed: %v", dcID, err)
		return
	}
	defer remote.Close()

	// Bidirectional pipe
	done := make(chan struct{}, 2)
	go func() {
		io.Copy(remote, conn)
		done <- struct{}{}
	}()
	go func() {
		io.Copy(conn, remote)
		done <- struct{}{}
	}()
	<-done
}

func (p *Proxy) handleObfuscated2(conn net.Conn) (int, error) {
	header := make([]byte, 64)
	if _, err := io.ReadFull(conn, header); err != nil {
		return 0, err
	}

	// Derive decryption key: SHA256(header[8:40] + secret)
	keyData := make([]byte, 32+len(p.secret))
	copy(keyData, header[8:40])
	copy(keyData[32:], p.secret)
	keyHash := sha256.Sum256(keyData)
	decryptKey := keyHash[:]

	// IV = header[40:56]
	iv := header[40:56]

	// Decrypt header[56:64] to get DC ID
	block, err := aes.NewCipher(decryptKey)
	if err != nil {
		return 2, nil // fallback to DC2
	}
	stream := cipher.NewCTR(block, iv)
	decrypted := make([]byte, 8)
	stream.XORKeyStream(decrypted, header[56:64])

	// DC ID is at offset 4 (little-endian int16)
	dcID := int(int16(binary.LittleEndian.Uint16(decrypted[4:6])))
	if _, ok := telegramDCs[abs(dcID)]; !ok {
		dcID = 2
	}

	return dcID, nil
}

func (p *Proxy) handleFakeTLS(conn net.Conn) (int, error) {
	// Read TLS record header (5 bytes)
	tlsHeader := make([]byte, 5)
	if _, err := io.ReadFull(conn, tlsHeader); err != nil {
		return 0, err
	}
	if tlsHeader[0] != 0x16 { // Not Handshake
		return 0, fmt.Errorf("not a TLS handshake")
	}

	length := int(binary.BigEndian.Uint16(tlsHeader[3:5]))
	if length > 16384 {
		return 0, fmt.Errorf("TLS record too large")
	}

	// Read ClientHello body
	clientHello := make([]byte, length)
	if _, err := io.ReadFull(conn, clientHello); err != nil {
		return 0, err
	}

	// Send fake ServerHello
	conn.Write(generateFakeServerHello())

	// Now read obfuscated2 header
	return p.handleObfuscated2(conn)
}

func generateFakeServerHello() []byte {
	randomBytes := make([]byte, 32)
	rand.Read(randomBytes)
	sessionID := make([]byte, 32)
	rand.Read(sessionID)

	// ServerHello body
	serverHelloBody := make([]byte, 0, 70)
	serverHelloBody = append(serverHelloBody, 0x03, 0x03) // TLS 1.2
	serverHelloBody = append(serverHelloBody, randomBytes...)
	serverHelloBody = append(serverHelloBody, 32)
	serverHelloBody = append(serverHelloBody, sessionID...)
	serverHelloBody = append(serverHelloBody, 0xc0, 0x2f) // cipher suite
	serverHelloBody = append(serverHelloBody, 0x00)       // compression
	serverHelloBody = append(serverHelloBody, 0x00, 0x00) // extensions length

	// Handshake header
	handshake := make([]byte, 0, 4+len(serverHelloBody))
	handshake = append(handshake, 0x02) // ServerHello
	l := len(serverHelloBody)
	handshake = append(handshake, byte(l>>16), byte(l>>8), byte(l))
	handshake = append(handshake, serverHelloBody...)

	// TLS record
	record := make([]byte, 0, 5+len(handshake))
	record = append(record, 0x16)       // Handshake
	record = append(record, 0x03, 0x03) // TLS 1.2
	hl := len(handshake)
	record = append(record, byte(hl>>8), byte(hl))
	record = append(record, handshake...)

	// Change Cipher Spec
	ccs := []byte{0x14, 0x03, 0x03, 0x00, 0x01, 0x01}

	result := make([]byte, 0, len(record)+len(ccs))
	result = append(result, record...)
	result = append(result, ccs...)
	return result
}

func abs(x int) int {
	if x < 0 {
		return -x
	}
	return x
}

// Stats returns MTProto proxy stats.
func (p *Proxy) Stats() map[string]interface{} {
	return map[string]interface{}{
		"port":              p.port,
		"mode":             p.mode,
		"fake_tls":         p.fakeTLS,
		"total_connections": p.totalConns.Load(),
		"active_connections": p.activeConns.Load(),
	}
}
