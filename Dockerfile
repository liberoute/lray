FROM golang:1.22-alpine AS builder

WORKDIR /app
COPY go.mod go.sum* ./
RUN go mod download 2>/dev/null || true

COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -buildvcs=false -ldflags="-s -w" -o lray ./cmd/lray

FROM alpine:3.19
RUN apk --no-cache add ca-certificates

WORKDIR /app
COPY --from=builder /app/lray .
COPY config.example.json ./config.example.json

EXPOSE 2801 8086 8087

ENTRYPOINT ["./lray"]
CMD ["--config", "/app/config.json"]
