package main

import (
	"context"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"ccproxy/api"
	"ccproxy/config"
	"ccproxy/pool"
)

func main() {
	cfg := config.Load()

	if err := cfg.Validate(); err != nil {
		log.Fatalf("config error: %v", err)
	}

	if cfg.Debug {
		log.Printf("[main] config: port=%d model=%s timeout=%s cwd=%s",
			cfg.Port, cfg.DefaultModel, cfg.PromptTimeout, cfg.CWD)
		log.Printf("[main] claude binary: %s", cfg.ClaudeBin)
	}

	// Initialize process pool (stateless — no warm pool, no sessions).
	p := pool.New(cfg)

	// Wire up HTTP handler.
	handler := api.New(cfg, p)

	srv := &http.Server{
		Addr:         fmt.Sprintf(":%d", cfg.Port),
		Handler:      handler.Router(),
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 15 * time.Minute, // allow long Claude responses
		IdleTimeout:  120 * time.Second,
	}

	// Graceful shutdown on SIGINT / SIGTERM.
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, os.Interrupt, syscall.SIGTERM)

	go func() {
		<-sigCh
		log.Println("[main] shutting down...")

		ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
		defer cancel()

		if err := srv.Shutdown(ctx); err != nil {
			log.Printf("[main] HTTP shutdown error: %v", err)
		}

		p.Shutdown()
	}()

	log.Printf("[main] ccproxy listening on http://0.0.0.0:%d", cfg.Port)
	if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		log.Fatalf("[main] server error: %v", err)
	}

	log.Println("[main] stopped")
}
