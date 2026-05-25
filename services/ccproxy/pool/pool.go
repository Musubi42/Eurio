package pool

import (
	"fmt"
	"log"
	"sync"
	"sync/atomic"

	"ccproxy/config"
)

// Pool manages spawning Claude processes for incoming requests.
// Each request gets a fresh process — no warm pool, no session pinning.
type Pool struct {
	cfg           *config.Config
	wg            sync.WaitGroup
	shutdown      chan struct{}
	totalSpawned  atomic.Int64
	totalRequests atomic.Int64
}

// Stats holds snapshot counters for the diagnostic endpoint.
type Stats struct {
	TotalSpawned  int64 `json:"total_spawned"`
	TotalRequests int64 `json:"total_requests"`
}

// New creates a Pool.
func New(cfg *config.Config) *Pool {
	return &Pool{
		cfg:      cfg,
		shutdown: make(chan struct{}),
	}
}

// Stats returns a snapshot of pool counters.
func (p *Pool) Stats() Stats {
	return Stats{
		TotalSpawned:  p.totalSpawned.Load(),
		TotalRequests: p.totalRequests.Load(),
	}
}

// Spawn creates a fresh Claude process with the given mode flags.
func (p *Pool) Spawn(model string, mode ProcessMode) (*ClaudeProcess, error) {
	if model == "" {
		model = p.cfg.DefaultModel
	}

	p.totalRequests.Add(1)
	p.totalSpawned.Add(1)

	log.Printf("[pool] spawn (model=%s tools=%q maxTurns=%d inputFmt=%s effort=%s)",
		model, mode.Tools, mode.MaxTurns, mode.InputFormat, mode.Effort)

	proc, err := newProcess(p.cfg, model, mode)
	if err != nil {
		return nil, fmt.Errorf("spawn: %w", err)
	}
	return proc, nil
}

// Shutdown waits for all tracked goroutines to finish.
func (p *Pool) Shutdown() {
	close(p.shutdown)
	p.wg.Wait()
	log.Println("[pool] shutdown complete")
}
