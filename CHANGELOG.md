# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] - 2025-05-31

### Removed

- Empty `go/` placeholder directory (dead code)
- `docs/` folder — wiki is maintained in a separate GitHub wiki repo
- Stale tracked docs files from git index

### Changed

- Added `.kiro/` to `.gitignore` (local-only dev tooling)
- Added `docs/` to `.gitignore` (wiki repo is separate)

## [1.2.0] - 2025-01-15

### Added

- Direct Cloudflare Worker connection mode (`cloudflare_direct`) for environments where Cloudflare is accessible but Google is throttled
- Smart routing with SNI rewrite, block hosts, and patterniha integration
- Extended cross-compilation targets: linux/arm (GOARM=6), linux/mips, linux/mipsle, freebsd/amd64
- CI pipeline with test and lint steps using GitHub Actions
- Property-based and unit test suites for all internal packages
- CONTRIBUTING.md with development setup and PR guidelines
- PAC server for proxy auto-configuration
- Quota tracker for Google Apps Script usage management
- DNS-over-HTTPS resolver with caching and provider failover
- MITM certificate manager with caching and auto-generated CA
- Configuration hot-reload via file watcher

### Changed

- Complete rewrite from Python to Go (module: github.com/liberoute/lray, Go 1.22+)
- Zero external dependencies — uses only Go standard library
- Version string injected at build time via ldflags (single source of truth in Makefile)
- Static binaries via CGO_ENABLED=0 for all build targets

### Removed

- Python codebase and all Python source files
- PyInstaller build system and packaging
- pip dependencies and requirements.txt
- Python-based proxy implementation
