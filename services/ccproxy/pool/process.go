package pool

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"sync"
	"time"

	"ccproxy/config"
	"ccproxy/types"
)

// ProcessMode controls which CLI flags are passed to the Claude subprocess.
type ProcessMode struct {
	Tools        string // --tools value: "" disables all, "Read" enables only Read
	ToolsSet     bool   // true if Tools was explicitly set (to distinguish "" from unset)
	MaxTurns     int    // --max-turns N: 0 = not set
	SystemPrompt string // --system-prompt "...": replaces built-in system prompt entirely
	InputFormat  string // --input-format: "stream-json" for structured JSONL input with inline images
	Effort       string // --effort: "low" disables thinking, "high"/"max" enables it
}

const (
	// defaultPromptTimeout is the max time to wait for Claude to respond to a prompt.
	// Can be overridden via config.
	defaultPromptTimeout = 15 * time.Minute
	// linesChanBuf is the buffer depth for the JSONL line channel.
	linesChanBuf = 512
)

// PromptResult holds the full result from a SendPrompt call.
type PromptResult struct {
	Text             string
	SessionID        string
	Usage            *types.ClaudeUsage
	AnthropicCostUSD float64 // Official cost from Claude CLI result message
}

// ClaudeProcess is a claude subprocess driven via stdin/stdout pipes (no PTY).
//
// Lifecycle:
//   - Claude is spawned with stdin/stdout pipes (no terminal → batch mode).
//   - Claude reads stdin until EOF, then processes the full content as a prompt
//     and emits JSONL to stdout.
//   - Each ClaudeProcess handles EXACTLY ONE prompt: after writing the prompt we
//     close stdin (EOF), Claude responds, then exits.
type ClaudeProcess struct {
	cmd       *exec.Cmd
	stdin     io.WriteCloser // write prompt here, then Close() to submit
	stdinOnce sync.Once      // ensures stdin is closed at most once
	sessionID string         // conversation session ID; captured from first response
	lines     chan types.ClaudeMsg
	done      chan struct{} // closed when process exits
	mu        sync.Mutex
	cfg       *config.Config
}

// newProcess spawns a new claude subprocess. Returns immediately after Start();
// the process is waiting for stdin input.
func newProcess(cfg *config.Config, model string, mode ProcessMode) (*ClaudeProcess, error) {
	args := []string{
		"-p", // non-interactive print mode: read stdin until EOF, then respond
		"--output-format", "stream-json",
		"--verbose",
		"--dangerously-skip-permissions",
		"--strict-mcp-config",     // ignore all user/project MCP servers
		"--disable-slash-commands", // skip skills machinery
	}
	if mode.ToolsSet {
		args = append(args, "--tools", mode.Tools)
	}
	if mode.MaxTurns > 0 {
		args = append(args, "--max-turns", strconv.Itoa(mode.MaxTurns))
	}
	if mode.SystemPrompt != "" {
		args = append(args, "--system-prompt", mode.SystemPrompt)
	}
	if mode.InputFormat != "" {
		args = append(args, "--input-format", mode.InputFormat)
	}
	if mode.Effort != "" {
		args = append(args, "--effort", mode.Effort)
	}
	// Pass model explicitly so we don't inherit the user's global default.
	if model != "" {
		args = append(args, "--model", model)
	} else if cfg.DefaultModel != "" {
		args = append(args, "--model", cfg.DefaultModel)
	}

	cmd := exec.Command(cfg.ClaudeBin, args...)
	cmd.Dir = cfg.CWD

	// Strip CLAUDECODE from the child environment so ccproxy can run even when
	// launched from inside a Claude Code session (otherwise Claude refuses to start).
	env := make([]string, 0, len(os.Environ()))
	for _, e := range os.Environ() {
		if len(e) >= 10 && e[:10] == "CLAUDECODE" {
			continue
		}
		env = append(env, e)
	}
	cmd.Env = env

	stdinPipe, err := cmd.StdinPipe()
	if err != nil {
		return nil, fmt.Errorf("stdin pipe: %w", err)
	}

	stdoutPipe, err := cmd.StdoutPipe()
	if err != nil {
		return nil, fmt.Errorf("stdout pipe: %w", err)
	}

	// Claude's stderr (version notices, error messages) goes to ccproxy stderr.
	cmd.Stderr = os.Stderr

	if err := cmd.Start(); err != nil {
		return nil, fmt.Errorf("start claude: %w", err)
	}

	p := &ClaudeProcess{
		cmd:   cmd,
		stdin: stdinPipe,
		lines: make(chan types.ClaudeMsg, linesChanBuf),
		done:  make(chan struct{}),
		cfg:   cfg,
	}

	go p.readLoop(stdoutPipe)

	log.Printf("[process] spawned pid=%d (model=%s inputFmt=%s)", cmd.Process.Pid, model, mode.InputFormat)

	return p, nil
}

// readLoop reads JSONL from Claude's stdout and sends to p.lines.
func (p *ClaudeProcess) readLoop(r io.Reader) {
	defer func() {
		close(p.done)
		log.Printf("[process] readLoop exited (sessionID=%s)", p.sessionID)
	}()
	defer close(p.lines)

	scanner := bufio.NewScanner(r)
	scanner.Buffer(make([]byte, 2*1024*1024), 2*1024*1024)

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())

		if p.cfg.Debug {
			log.Printf("[process] stdout: %s", line)
		}

		if line == "" || !strings.HasPrefix(line, "{") {
			continue
		}

		var msg types.ClaudeMsg
		if err := json.Unmarshal([]byte(line), &msg); err != nil {
			if p.cfg.Debug {
				log.Printf("[process] json parse error: %v | line: %s", err, line)
			}
			continue
		}

		// Capture session ID from first message that carries one.
		if sid := msg.GetSessionID(); sid != "" {
			p.mu.Lock()
			if p.sessionID == "" {
				p.sessionID = sid
				if p.cfg.Debug {
					log.Printf("[process] captured sessionId=%s", p.sessionID)
				}
			}
			p.mu.Unlock()
		}

		if p.cfg.Debug {
			log.Printf("[process] msg type=%s subtype=%s", msg.Type, msg.Subtype)
		}

		select {
		case p.lines <- msg:
		default:
			log.Printf("[process] lines channel full, dropping type=%s", msg.Type)
		}
	}

	if err := scanner.Err(); err != nil {
		log.Printf("[process] scanner error: %v", err)
	}
}

// SessionID returns the Claude session ID (empty until first response arrives).
func (p *ClaudeProcess) SessionID() string {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.sessionID
}

// IsAlive reports whether the underlying process is still running.
func (p *ClaudeProcess) IsAlive() bool {
	select {
	case <-p.done:
		return false
	default:
		return true
	}
}

// SendPrompt delivers prompt to Claude and collects the assistant reply.
//
// Claude (in pipe mode) reads stdin until EOF, then processes the accumulated
// content as a single prompt. We close stdin after writing so Claude starts.
//
// Because stdin is closed, this process can only be used ONCE.
func (p *ClaudeProcess) SendPrompt(ctx context.Context, input []byte) (*PromptResult, error) {
	t0 := time.Now()
	log.Printf("[perf] prompt=%d bytes, sending stdin", len(input))

	if _, err := p.stdin.Write(input); err != nil {
		return nil, fmt.Errorf("write to stdin: %w", err)
	}

	// Close stdin → EOF → Claude processes the prompt and starts emitting JSONL.
	p.stdinOnce.Do(func() { _ = p.stdin.Close() })
	log.Printf("[perf] stdin closed at T+%s", time.Since(t0).Round(time.Millisecond))

	// Collect response until type=="result" or process exits.
	var textParts []string
	var firstMsgAt, firstTextAt time.Time
	var accUsage types.ClaudeUsage
	msgCount := 0

	timeout := p.cfg.PromptTimeout
	if timeout == 0 {
		timeout = defaultPromptTimeout
	}
	timeoutCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	mkResult := func(usage *types.ClaudeUsage, costUSD float64) *PromptResult {
		return &PromptResult{
			Text:             strings.Join(textParts, ""),
			SessionID:        p.SessionID(),
			Usage:            usage,
			AnthropicCostUSD: costUSD,
		}
	}

	for {
		select {
		case <-timeoutCtx.Done():
			return nil, fmt.Errorf("prompt timeout: %w", timeoutCtx.Err())

		case <-p.done:
			if len(textParts) > 0 {
				return mkResult(&accUsage, 0), nil
			}
			return nil, fmt.Errorf("claude process exited without producing output")

		case msg, ok := <-p.lines:
			if !ok {
				if len(textParts) > 0 {
					return mkResult(&accUsage, 0), nil
				}
				return nil, fmt.Errorf("lines channel closed without result")
			}

			msgCount++
			if firstMsgAt.IsZero() {
				firstMsgAt = time.Now()
				log.Printf("[perf] first JSONL at T+%s (type=%s)", time.Since(t0).Round(time.Millisecond), msg.Type)
			}

			switch msg.Type {
			case "assistant":
				if msg.Message != nil {
					for _, item := range msg.Message.Content {
						if item.Type == "text" && item.Text != "" {
							if firstTextAt.IsZero() {
								firstTextAt = time.Now()
								log.Printf("[perf] first text at T+%s (%d chars)", time.Since(t0).Round(time.Millisecond), len(item.Text))
							}
							textParts = append(textParts, item.Text)
						}
					}
					accUsage.Add(msg.Message.Usage)
				}

			case "result":
				finalUsage := &accUsage
				if msg.Usage != nil {
					finalUsage = msg.Usage
				}

				totalChars := 0
				for _, part := range textParts {
					totalChars += len(part)
				}
				log.Printf("[perf] result at T+%s — %d msgs, %d chars output, tokens in=%d out=%d cache_create=%d cache_read=%d cost=$%.6f",
					time.Since(t0).Round(time.Millisecond), msgCount, totalChars,
					finalUsage.InputTokens, finalUsage.OutputTokens,
					finalUsage.CacheCreationInputTokens, finalUsage.CacheReadInputTokens,
					msg.TotalCostUSD)

				if sid := msg.GetSessionID(); sid != "" {
					p.mu.Lock()
					p.sessionID = sid
					p.mu.Unlock()
				}
				if msg.IsError {
					errText := msg.Error
					if errText == "" && msg.Result != "" {
						errText = msg.Result
					}
					return nil, fmt.Errorf("claude error: %s", errText)
				}
				if len(textParts) == 0 && msg.Result != "" {
					textParts = append(textParts, msg.Result)
				}
				return mkResult(finalUsage, msg.TotalCostUSD), nil

			case "system":
				if msg.Subtype == "error" {
					return nil, fmt.Errorf("system error: %s", msg.Error)
				}

			default:
				// tool_use, tool_result, thinking, rate_limit_event — drop.
			}
		}
	}
}

// Terminate kills the underlying process.
func (p *ClaudeProcess) Terminate() {
	p.stdinOnce.Do(func() { _ = p.stdin.Close() })
	if p.cmd.Process != nil {
		_ = p.cmd.Process.Kill()
	}
	_ = p.cmd.Wait()
}
