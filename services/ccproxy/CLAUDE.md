# ccproxy — Developer Context

Go proxy that wraps the Claude Code CLI behind an OpenAI-compatible HTTP API. Purpose-built for ShortForge's AI pipeline workers.

## Why ccproxy exists

ShortForge workers need to call Claude for text analysis (plan_short, review_plan, narrative_analysis) and vision analysis (vu_analyze, vu_enrich, scenes). The Claude Code CLI provides access to Claude via a local subprocess — ccproxy wraps it as an HTTP API so TypeScript workers can call it like any OpenAI endpoint.

## Architecture: stateless, single-turn

Every request spawns a fresh `claude` subprocess. No warm pool, no session persistence, no process reuse. This matches ShortForge workers exactly: they're all stateless, single-turn, and carry their own system prompt via `--system-prompt`.

```
Worker POST /v1/chat/completions
    ↓
ccproxy detects mode (text or vision)
    ↓
Spawn: claude -p --system-prompt "..." --tools "" --max-turns 1 [--input-format stream-json]
    ↓
Write prompt to stdin → close stdin (EOF)
    ↓
Collect JSONL from stdout until type=result
    ↓
Return OpenAI-format JSON response
```

## Two modes

| Mode | Trigger | Input format | How images are handled |
|------|---------|-------------|----------------------|
| **text** | No `image_url` blocks | Plain text on stdin | N/A |
| **vision** | Has `image_url` blocks | `--input-format stream-json` (JSONL) | Inline base64 content blocks |

Mode is auto-detected from the request — workers don't need to specify it.

### Text mode

Used by: `plan_short`, `review_plan`, `narrative_analysis`, `vu_narrate`, `vu_enrich` (text path), `vu_attribute`, `verbal_beats`, `audio_analysis`

```
Flags: -p --tools "" --max-turns 1 --system-prompt "..." --model <model>
stdin: raw user prompt text
```

No tools, single turn, custom system prompt. Claude's 30K+ built-in system prompt is replaced by the worker's prompt (~800 chars to ~2000 words).

### Vision mode

Used by: `vu_analyze`, `vu_enrich` (vision path), `vision`, `scenes`, `visual_beats`, `iconic_moments`

```
Flags: -p --tools "" --max-turns 1 --system-prompt "..." --model <model> --input-format stream-json
stdin: JSONL with inline base64 image content blocks
```

Images are sent **inline** as base64 — no temp files, no Read tool calls. The JSONL envelope:

```json
{"type":"user","message":{"role":"user","content":[
  {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":"<b64>"}},
  {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":"<b64>"}},
  {"type":"text","text":"Analyze these frames: Frame 1: 0:15, Frame 2: 0:30 ..."}
]},"session_id":"default","parent_tool_use_id":null}
```

Image **order is strictly preserved** — critical for vu_analyze where Frame N in the text maps positionally to image N in the array.

## Performance characteristics

### Text mode (plan_short, review_plan, etc.)
- **Spawn time:** ~500ms (claude CLI startup)
- **System prompt tokens:** ~200-800 (worker's custom prompt) vs 30K+ (Claude Code built-in)
- **Messages:** 4 JSONL lines (init → assistant → rate_limit → result)
- **Total:** 2-10s depending on response length

### Vision mode (vu_analyze, etc.)

| Metric | Old (temp files + Read tool) | New (inline stream-json) |
|--------|------------------------------|--------------------------|
| Messages per request | ~46 (20 tool_use + 20 tool_result + overhead) | ~4 |
| Per-batch latency | ~1m30s | ~4s |
| Temp file I/O | 20 file writes + 20 file reads | None |
| Tools needed | `"Read"` | `""` (none) |

The vision improvement comes from eliminating Read tool round-trips. Each image used to be: write to /tmp → Claude reads file via Read tool → tool_use + tool_result JSONL. Now images are sent inline in a single JSONL message.

## Key files

| File | What |
|------|------|
| `main.go` | Entry point: config, pool, HTTP server, graceful shutdown |
| `config/config.go` | Env vars + CLI flags (`--port`, `--model`, `--debug`, etc.) |
| `pool/pool.go` | Pool struct: `Spawn()` + atomic counters for `/stats` |
| `pool/process.go` | `ClaudeProcess`: subprocess lifecycle, `SendPrompt()`, JSONL collection |
| `api/chat.go` | `POST /v1/chat/completions` — mode detection, input building, response |
| `api/models.go` | `GET /v1/models` — model list (single source of truth) |
| `api/health.go` | `GET /health`, `GET /stats`, `GET /` |
| `api/handler.go` | chi router setup, CORS middleware |
| `types/openai.go` | OpenAI-compatible request/response types |
| `types/claude.go` | Claude CLI JSONL message types |

## How `SendPrompt` works

1. Write prompt bytes to stdin
2. Close stdin (EOF triggers Claude to process)
3. `readLoop` goroutine collects JSONL from stdout line by line
4. Each JSONL line is parsed into `ClaudeMsg` and sent to a buffered channel
5. `SendPrompt` reads from channel until `type=result`
6. Returns collected text, token usage, cost, session ID

## JSONL types from Claude CLI

| `type` | When | What ccproxy does |
|--------|------|-------------------|
| `system/init` | First message | Captures session ID |
| `assistant` | Response text | Collects `content[].text` blocks, accumulates usage |
| `result` | End of turn | Authoritative usage + cost. Returns response. |
| `system/error` | Error | Returns error to client |
| `tool_use`, `tool_result` | Shouldn't happen (`--tools ""`) | Silently dropped |
| `rate_limit_event` | Rate limit info | Silently dropped |

## Config

| Flag | Env var | Default | Description |
|------|---------|---------|-------------|
| `--port` | `CCPROXY_PORT` | `3002` | HTTP listen port |
| `--claude-bin` | `CCPROXY_CLAUDE` | auto-detect | Path to `claude` binary |
| `--model` | `CCPROXY_MODEL` | `claude-sonnet-4-6` | Default model |
| `--prompt-timeout` | `CCPROXY_PROMPT_TIMEOUT` | `15m` | Max wait for Claude response |
| `--cwd` | `CCPROXY_CWD` | process cwd | Working dir for subprocesses |
| `--debug` | `CCPROXY_DEBUG` | `false` | Log every JSONL line |

`CLAUDECODE*` env vars are stripped from child processes so ccproxy works inside a Claude Code session.

## Telemetry

Every request logs `[perf]` timing:
```
[perf] prompt=12345 bytes, sending stdin
[perf] stdin closed at T+0s
[perf] first JSONL at T+500ms (type=system)
[perf] first text at T+2.1s (150 chars)
[perf] result at T+4.5s — 4 msgs, 500 chars output, tokens in=3 out=150 cache_create=800 cache_read=0 cost=$0.003
```

## Adding a new model

Add it to `knownModels` in `api/models.go`. Both `/v1/models` and request validation pick it up automatically.

## Limitations

- **No streaming** — `stream: true` is accepted but response is always buffered
- **Single-use processes** — each turn spawns a new process (subprocess startup cost ~500ms)
- **Base64 only** — external `https://` image URLs are not fetched; only `data:` URLs supported
