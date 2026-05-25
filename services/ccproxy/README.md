# ccproxy

OpenAI-compatible HTTP proxy for Claude Code CLI, built for ShortForge's AI pipeline.

## What it does

ShortForge workers call Claude for text analysis (scripts, plans, reviews) and vision analysis (keyframes, scene detection). ccproxy sits between the workers and the Claude CLI, exposing a standard `/v1/chat/completions` endpoint.

```
ShortForge Workers (TypeScript)
        │
        │  POST /v1/chat/completions (OpenAI format)
        ▼
    ccproxy (Go, port 3002)
        │
        │  Spawns subprocess per request
        ▼
    claude CLI (stdin/stdout pipes)
        │
        │  Claude API (Anthropic)
        ▼
    Response → JSONL → OpenAI JSON
```

## Quick start

```bash
# Build
go build -o bin/ccproxy .

# Run
./bin/ccproxy --debug

# Or directly
go run . --debug --port 3002
```

Requires: `claude` CLI installed and authenticated (auto-detected from PATH).

## How it works

Every request spawns a **fresh Claude subprocess**. No connection pool, no session state. ccproxy auto-detects the mode from the request:

- **Text mode** — system prompt + user text. Tools disabled, single turn.
- **Vision mode** — system prompt + user text + images. Images sent inline via `--input-format stream-json`.

## API

### `POST /v1/chat/completions`

OpenAI-compatible chat completion. The only endpoint workers use.

**Text request:**
```json
{
  "model": "claude-sonnet-4-6",
  "messages": [
    { "role": "system", "content": "You are a TV narrative analyst..." },
    { "role": "user", "content": "Analyze the following scenes..." }
  ]
}
```

**Vision request (images as base64 data URLs):**
```json
{
  "model": "claude-sonnet-4-6",
  "messages": [
    { "role": "system", "content": "You are a scene boundary detector..." },
    {
      "role": "user",
      "content": [
        { "type": "image_url", "image_url": { "url": "data:image/jpeg;base64,/9j/..." } },
        { "type": "image_url", "image_url": { "url": "data:image/jpeg;base64,/9j/..." } },
        { "type": "text", "text": "Frame 1: 0:15\nFrame 2: 0:30\n..." }
      ]
    }
  ]
}
```

**Response:**
```json
{
  "id": "chatcmpl-1774878412291724000",
  "object": "chat.completion",
  "model": "claude-sonnet-4-6",
  "choices": [{
    "index": 0,
    "message": { "role": "assistant", "content": "..." },
    "finish_reason": "stop"
  }],
  "usage": {
    "prompt_tokens": 3,
    "completion_tokens": 150,
    "total_tokens": 153,
    "cache_creation_input_tokens": 800,
    "cache_read_input_tokens": 0,
    "anthropic_cost_usd": 0.003
  }
}
```

### Other endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Status + Claude CLI version |
| `GET /stats` | `total_spawned`, `total_requests` |
| `GET /v1/models` | Available Claude models |
| `GET /v1/models/:id` | Single model details |

## Configuration

| Flag | Env | Default | Description |
|------|-----|---------|-------------|
| `--port` | `CCPROXY_PORT` | `3002` | Listen port |
| `--model` | `CCPROXY_MODEL` | `claude-sonnet-4-6` | Default model |
| `--prompt-timeout` | `CCPROXY_PROMPT_TIMEOUT` | `15m` | Max response wait time |
| `--cwd` | `CCPROXY_CWD` | cwd | Working dir for claude processes |
| `--claude-bin` | `CCPROXY_CLAUDE` | auto | Path to claude binary |
| `--debug` | `CCPROXY_DEBUG` | `false` | Verbose JSONL logging |

## ShortForge worker mapping

### Text workers

These workers send a system prompt + user prompt with structured data (scenes, characters, dialogue). No images.

| Worker | What it does | System prompt size | Typical response time |
|--------|-------------|-------------------|----------------------|
| `plan_short` | Writes a short video plan (beats, clips, narration) | ~2000 words | 5-10s |
| `review_plan` | Scores a plan on 5 dimensions, suggests improvements | ~1800 words | 3-8s |
| `narrative_analysis` | Backward analysis from climax, Chekhov's guns | ~2000 words | 5-10s |
| `vu_narrate` | Global narrative arc from all scenes | ~20 words | 3-5s |
| `vu_attribute` | Speaker attribution on dialogue lines | ~30 words | 2-5s per batch |
| `vu_enrich` (text path) | Per-scene character/atmosphere enrichment | ~30 words | 2-4s |
| `verbal_beats` | Extract verbal beats from dialogue | delegated | 3-5s |
| `audio_analysis` | Analyze dialogue for iconic lines, speech rate | delegated | 3-5s |

### Vision workers

These workers send keyframe images alongside text prompts. Images are sent inline as base64 — no temp files.

| Worker | What it does | Images per request | Typical response time |
|--------|-------------|-------------------|----------------------|
| `vu_analyze` | Scene boundary detection from keyframes | ~20/batch, 4 parallel | ~4s/batch |
| `vu_enrich` (vision path) | Per-scene enrichment with keyframes | 3 frames/scene | ~3s |
| `vision` | Single keyframe annotation | 1 | ~2s |
| `scenes` (claude_vision path) | Scene detection from keyframes | ~30/batch | ~4s |
| `visual_beats` | Visual beat detection from keyframes | up to 15/batch | ~4s |
| `iconic_moments` (visual path) | Iconic moment selection with keyframes | up to 20/batch | ~5s |

### Performance comparison

**Vision mode — inline images vs. old temp-file approach:**

| | Old (temp files + Read tool) | New (inline stream-json) |
|---|---|---|
| vu_analyze (5 batches, 20 images each) | ~7m30s total | ~20s total |
| JSONL messages per batch | ~46 | ~4 |
| Temp file I/O | 20 writes + 20 reads | None |
| Tools required | `Read` | None |

The improvement comes from eliminating Read tool round-trips. Previously each image required a separate tool_use/tool_result exchange through the Claude API.

## Architecture decisions

### Why not the Anthropic API directly?

ccproxy wraps Claude Code CLI instead of calling the Anthropic API because:
- No API key management needed (CLI handles auth via OAuth)
- Consistent with the rest of the ShortForge dev stack
- Access to Claude Code features (web search, caching)

### Why no warm pool?

All ShortForge workers are stateless and carry custom system prompts via `--system-prompt`. Each request needs a fresh subprocess with different flags. A warm pool would only help if requests shared the same system prompt and flags — they don't.

### Why `--tools ""` for vision?

With inline images via `--input-format stream-json`, Claude receives images directly in the prompt. No Read tool needed. Setting `--tools ""` prevents Claude from attempting tool calls, and `--max-turns 1` ensures a single response turn with no loops.

### Why `--strict-mcp-config` and `--disable-slash-commands`?

These flags prevent Claude from loading MCP servers and skills from the user/project config. Without them, Claude loads ~30K tokens of tool definitions and MCP overhead — none of which workers use. `--strict-mcp-config` without any `--mcp-config` means zero MCP servers load.

## Debugging

```bash
# Start with verbose logging (logs every JSONL line)
go run . --debug

# Check health
curl localhost:3002/health

# Check request stats
curl localhost:3002/stats

# Test text mode
curl -X POST localhost:3002/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"claude-sonnet-4-6","messages":[
    {"role":"system","content":"Be concise."},
    {"role":"user","content":"What is 2+2?"}
  ]}'

# Logs show [perf] timing for every request:
# [perf] prompt=12 bytes, sending stdin
# [perf] stdin closed at T+0s
# [perf] first JSONL at T+500ms (type=system)
# [perf] first text at T+2.1s (5 chars)
# [perf] result at T+2.2s — 4 msgs, 5 chars output, tokens in=3 out=4 cost=$0.001
```

## Project structure

```
services/ccproxy/
  main.go              Entry point
  config/
    config.go          CLI flags + env vars
  pool/
    pool.go            Process spawning + stats
    process.go         ClaudeProcess: stdin/stdout pipes, JSONL collection
  api/
    handler.go         chi router, CORS
    chat.go            POST /v1/chat/completions (text + vision modes)
    health.go          GET /health, /stats, /
    models.go          GET /v1/models
  types/
    openai.go          OpenAI-compatible request/response types
    claude.go          Claude CLI JSONL message types
```
