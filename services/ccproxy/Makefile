.PHONY: build run dev install clean

BIN := bin/ccproxy

build:
	go build -o $(BIN) .

run: build
	./$(BIN)

dev:
	go run . --debug

install:
	go install .

clean:
	rm -rf bin/

test:
	go test ./...

tidy:
	go mod tidy
