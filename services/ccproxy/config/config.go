package config

import (
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// Config holds all runtime configuration for ccproxy.
type Config struct {
	Port          int
	ClaudeBin     string
	DefaultModel  string
	PromptTimeout time.Duration
	CWD           string
	AllowOrigins  []string
	Debug         bool
}

// Load parses environment variables and CLI flags, returning a populated Config.
// CLI flags take precedence over environment variables.
func Load() *Config {
	cfg := &Config{}

	flag.IntVar(&cfg.Port, "port", envInt("CCPROXY_PORT", 3002), "HTTP port to listen on")
	flag.StringVar(&cfg.ClaudeBin, "claude-bin", os.Getenv("CCPROXY_CLAUDE"), "Path to claude binary")
	flag.StringVar(&cfg.DefaultModel, "model", envStr("CCPROXY_MODEL", "claude-sonnet-4-6"), "Default Claude model")
	flag.DurationVar(&cfg.PromptTimeout, "prompt-timeout", envDuration("CCPROXY_PROMPT_TIMEOUT", 15*time.Minute), "Max time to wait for Claude to respond")
	flag.StringVar(&cfg.CWD, "cwd", envStr("CCPROXY_CWD", mustGetwd()), "Working directory for claude processes")
	flag.BoolVar(&cfg.Debug, "debug", envBool("CCPROXY_DEBUG"), "Enable debug logging")

	originsStr := flag.String("origins", "*", "Comma-separated list of allowed CORS origins")

	flag.Parse()

	if cfg.ClaudeBin == "" {
		cfg.ClaudeBin = detectClaudeBin()
	}

	if *originsStr == "*" {
		cfg.AllowOrigins = []string{"*"}
	} else {
		cfg.AllowOrigins = strings.Split(*originsStr, ",")
	}

	return cfg
}

// detectClaudeBin tries several strategies to find the claude binary.
func detectClaudeBin() string {
	// 1. Which PATH
	if path, err := exec.LookPath("claude"); err == nil {
		return path
	}

	// 2. npm global bin
	if out, err := exec.Command("npm", "bin", "-g").Output(); err == nil {
		candidate := filepath.Join(strings.TrimSpace(string(out)), "claude")
		if _, err := os.Stat(candidate); err == nil {
			return candidate
		}
	}

	// 3. Fallback
	return "claude"
}

func envStr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if i, err := strconv.Atoi(v); err == nil {
			return i
		}
	}
	return def
}

func envDuration(key string, def time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return def
}

func envBool(key string) bool {
	v := strings.ToLower(os.Getenv(key))
	return v == "1" || v == "true" || v == "yes"
}

func mustGetwd() string {
	d, err := os.Getwd()
	if err != nil {
		return "."
	}
	return d
}

// Validate checks that required fields are set.
func (c *Config) Validate() error {
	if c.ClaudeBin == "" {
		return fmt.Errorf("claude binary not found; set CCPROXY_CLAUDE or ensure 'claude' is in PATH")
	}
	return nil
}
