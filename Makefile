APP_NAME := lray
VERSION := 1.3.0
BUILD_FLAGS := -buildvcs=false -ldflags="-s -w -X main.version=$(VERSION)"

.PHONY: build run clean test build-linux build-windows build-mac build-linux-arm build-linux-mips build-linux-mipsle build-freebsd build-all

build:
	CGO_ENABLED=0 go build $(BUILD_FLAGS) -o $(APP_NAME) ./cmd/lray

run: build
	./$(APP_NAME)

clean:
	rm -f $(APP_NAME) $(APP_NAME).exe $(APP_NAME)-linux-amd64 $(APP_NAME)-windows-amd64.exe $(APP_NAME)-darwin-amd64 $(APP_NAME)-darwin-arm64 $(APP_NAME)-linux-arm6 $(APP_NAME)-linux-mips $(APP_NAME)-linux-mipsle $(APP_NAME)-freebsd-amd64

test:
	go test ./...

# Cross-compilation
build-linux:
	CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build $(BUILD_FLAGS) -o $(APP_NAME)-linux-amd64 ./cmd/lray

build-windows:
	CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build $(BUILD_FLAGS) -o $(APP_NAME)-windows-amd64.exe ./cmd/lray

build-mac:
	CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 go build $(BUILD_FLAGS) -o $(APP_NAME)-darwin-amd64 ./cmd/lray
	CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build $(BUILD_FLAGS) -o $(APP_NAME)-darwin-arm64 ./cmd/lray

build-linux-arm:
	CGO_ENABLED=0 GOOS=linux GOARCH=arm GOARM=6 go build $(BUILD_FLAGS) -o $(APP_NAME)-linux-arm6 ./cmd/lray

build-linux-mips:
	CGO_ENABLED=0 GOOS=linux GOARCH=mips go build $(BUILD_FLAGS) -o $(APP_NAME)-linux-mips ./cmd/lray

build-linux-mipsle:
	CGO_ENABLED=0 GOOS=linux GOARCH=mipsle go build $(BUILD_FLAGS) -o $(APP_NAME)-linux-mipsle ./cmd/lray

build-freebsd:
	CGO_ENABLED=0 GOOS=freebsd GOARCH=amd64 go build $(BUILD_FLAGS) -o $(APP_NAME)-freebsd-amd64 ./cmd/lray

build-all: build-linux build-windows build-mac build-linux-arm build-linux-mips build-linux-mipsle build-freebsd
