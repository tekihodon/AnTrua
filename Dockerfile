FROM golang:1.21-alpine AS builder

WORKDIR /app

COPY go.mod go.sum ./
RUN go mod download

COPY . .

RUN CGO_ENABLED=0 GOOS=linux go build -o an-trua-server .

FROM alpine:3.18

RUN apk --no-cache add ca-certificates

WORKDIR /app

COPY --from=builder /app/an-trua-server .
COPY config.example.json ./config.json
COPY init_db.sql ./init_db.sql

EXPOSE 5000

ENV DATABASE_URL=""

CMD ["./an-trua-server"]