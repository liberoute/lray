APP_NAME := lray
VERSION := 1.1.1
BUILD_FLAGS := -buildvcs=false -ldflags="-s -w"

.PHONY: build run clean test

build:
	go build $(BUILD_FLAGS) -o $(APP_NAME) ./cmd/lray

run: build
	./$(APP_NAME)

clean:
	rm -f $(APP_NAME) $(APP_NAME).exe

test:
	go test ./...

# Cross-compilation
build-linux:
	GOOS=linux GOARCH=amd64 go build $(BUILD_FLAGS) -o $(APP_NAME)-linux-amd64 ./cmd/lray

build-windows:
	GOOS=windows GOARCH=amd64 go build $(BUILD_FLAGS) -o $(APP_NAME)-windows-amd64.exe ./cmd/lray

build-mac:
	GOOS=darwin GOARCH=amd64 go build $(BUILD_FLAGS) -o $(APP_NAME)-darwin-amd64 ./cmd/lray
	GOOS=darwin GOARCH=arm64 go build $(BUILD_FLAGS) -o $(APP_NAME)-darwin-arm64 ./cmd/lray

build-all: build-linux build-windows build-mac
