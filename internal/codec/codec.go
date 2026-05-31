// Package codec provides content-encoding decoders (gzip, deflate, brotli).
package codec

import (
	"bytes"
	"compress/flate"
	"compress/gzip"
	"io"
	"strings"
)

// SupportedEncodings returns the Accept-Encoding value this relay can decode.
func SupportedEncodings() string {
	return "gzip, deflate"
}

// Decode decompresses body according to Content-Encoding.
// Returns original bytes on unknown encoding or error.
func Decode(body []byte, encoding string) []byte {
	if len(body) == 0 {
		return body
	}
	enc := strings.TrimSpace(strings.ToLower(encoding))
	if enc == "" || enc == "identity" {
		return body
	}

	// Multi-coding: "gzip, deflate" means deflate(gzip(data))
	if strings.Contains(enc, ",") {
		parts := strings.Split(enc, ",")
		for i := len(parts) - 1; i >= 0; i-- {
			body = Decode(body, strings.TrimSpace(parts[i]))
		}
		return body
	}

	switch enc {
	case "gzip":
		r, err := gzip.NewReader(bytes.NewReader(body))
		if err != nil {
			return body
		}
		defer r.Close()
		decoded, err := io.ReadAll(r)
		if err != nil {
			return body
		}
		return decoded

	case "deflate":
		r := flate.NewReader(bytes.NewReader(body))
		defer r.Close()
		decoded, err := io.ReadAll(r)
		if err != nil {
			// Try raw deflate (no zlib wrapper)
			r2 := flate.NewReader(bytes.NewReader(body))
			defer r2.Close()
			decoded2, err2 := io.ReadAll(r2)
			if err2 != nil {
				return body
			}
			return decoded2
		}
		return decoded
	}

	return body
}
