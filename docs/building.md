# Building from Source

## Requirements

- Python 3.10+
- pip

## Build Binary

```bash
# 1. Install dependencies
pip install -r requirements.txt
pip install pyinstaller

# 2. Build
pyinstaller --onefile --name lray --paths src \
  --hidden-import h2 \
  --hidden-import hpack \
  --hidden-import hyperframe \
  --hidden-import brotli \
  --hidden-import zstandard \
  --hidden-import certifi \
  cli.py

# 3. Binary is at:
#    Windows: dist/lray.exe
#    Linux/Mac: dist/lray
```

## Quick one-liner

**Windows:**
```powershell
python -m PyInstaller --onefile --name lray --paths src --hidden-import h2 --hidden-import hpack --hidden-import hyperframe --hidden-import brotli --hidden-import zstandard --hidden-import certifi cli.py
```

**Linux/Mac:**
```bash
pyinstaller --onefile --name lray --paths src --hidden-import h2 --hidden-import hpack --hidden-import hyperframe --hidden-import brotli --hidden-import zstandard --hidden-import certifi cli.py
```

## Output

```
dist/
└── lray(.exe)    ~13MB, standalone, no Python needed
```

## Test the binary

```bash
./dist/lray version     # → lray v3.0.0
./dist/lray help        # → all commands
./dist/lray check       # → validate config
```

## Cross-platform

PyInstaller can't cross-compile. Build on each target OS:

| Platform | Build on |
|---|---|
| Windows amd64 | Windows |
| Linux amd64 | Linux x86_64 |
| Linux arm64 | Linux aarch64 (or GitHub Actions) |
| macOS arm64 | macOS M1+ |
| macOS amd64 | macOS Intel |

GitHub Actions does this automatically on tag push (see `.github/workflows/build.yml`).

## Without PyInstaller (run from source)

```bash
git clone https://github.com/liberoute/lray.git
cd lray
pip install -r requirements.txt
python cli.py version
python cli.py setup
python cli.py start
```

No build needed — just Python + dependencies.
