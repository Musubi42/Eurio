package api

import (
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"time"

	"ccproxy/pool"
	"ccproxy/types"
)

// validModels is derived from knownModels (models.go) so the two stay in sync.
var validModels = func() map[string]bool {
	m := make(map[string]bool, len(knownModels))
	for _, mo := range knownModels {
		m[mo.ID] = true
	}
	return m
}()

func (h *Handler) handleChatCompletions(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(io.LimitReader(r.Body, 20<<20)) // 20 MB limit (base64 images are large)
	if err != nil {
		writeError(w, http.StatusBadRequest, "failed to read request body")
		return
	}

	var req types.ChatCompletionRequest
	if err := json.Unmarshal(body, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON: "+err.Error())
		return
	}

	if len(req.Messages) == 0 {
		writeError(w, http.StatusBadRequest, "messages array is empty")
		return
	}

	// Normalize model.
	if !validModels[req.Model] {
		if h.cfg.Debug {
			log.Printf("[chat] unknown model %q, using default %s", req.Model, h.cfg.DefaultModel)
		}
		req.Model = h.cfg.DefaultModel
	}

	// Extract system prompt — required for all worker requests.
	systemPrompt := extractSystemPrompt(req.Messages)
	hasImages := messagesHaveImages(req.Messages)
	hasCacheControl := messagesHaveCacheControl(req.Messages)

	// Use stream-json whenever content is structured: multi-block user messages,
	// images, or any cache_control markers the caller wants passed through.
	useStreamJSON := hasImages || hasCacheControl

	mode := "text"
	if useStreamJSON {
		mode = "vision"
	}
	log.Printf("[chat] mode=%s hasImages=%v hasCacheControl=%v systemPromptLen=%d",
		mode, hasImages, hasCacheControl, len(systemPrompt))

	// Build process mode.
	pm := pool.ProcessMode{
		ToolsSet:     true,
		Tools:        "",
		MaxTurns:     1,
		SystemPrompt: systemPrompt,
		Effort:       "low", // disable extended thinking — workers don't need it
	}

	var inputBytes []byte

	if useStreamJSON {
		// Stream-json mode: structured content blocks (inline images and/or cache_control markers).
		pm.InputFormat = "stream-json"
		inputBytes, err = buildStreamJSONInput(req.Messages)
		if err != nil {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}
	} else {
		// Text mode: plain text input.
		inputBytes, err = buildTextInput(req.Messages)
		if err != nil {
			writeError(w, http.StatusBadRequest, err.Error())
			return
		}
	}

	proc, err := h.pool.Spawn(req.Model, pm)
	if err != nil {
		log.Printf("[chat] Spawn error: %v", err)
		writeError(w, http.StatusServiceUnavailable, "could not spawn claude process: "+err.Error())
		return
	}

	pr, err := proc.SendPrompt(r.Context(), inputBytes)
	if err != nil {
		log.Printf("[chat] SendPrompt error: %v", err)
		writeError(w, http.StatusInternalServerError, "claude error: "+err.Error())
		return
	}

	h.writeCompletionResponse(w, req.Model, inputBytes, pr)
}

// writeCompletionResponse builds and writes the OpenAI-compatible JSON response.
func (h *Handler) writeCompletionResponse(w http.ResponseWriter, model string, inputBytes []byte, pr *pool.PromptResult) {
	now := time.Now()

	usage := pr.Usage
	var u types.Usage
	if usage != nil && (usage.InputTokens > 0 || usage.OutputTokens > 0 || usage.CacheCreationInputTokens > 0 || usage.CacheReadInputTokens > 0) {
		u = types.Usage{
			PromptTokens:     usage.InputTokens,
			CompletionTokens: usage.OutputTokens,
			// Include cache tokens in the total — they are input tokens the model processed,
			// just billed at different rates. Keeping them out under-reports prompt volume.
			TotalTokens:              usage.InputTokens + usage.OutputTokens + usage.CacheCreationInputTokens + usage.CacheReadInputTokens,
			CacheCreationInputTokens: usage.CacheCreationInputTokens,
			CacheReadInputTokens:     usage.CacheReadInputTokens,
			AnthropicCostUSD:         pr.AnthropicCostUSD,
		}
	} else {
		u = types.Usage{
			PromptTokens:     len(inputBytes) / 4,
			CompletionTokens: estimateTokens(pr.Text),
			TotalTokens:      len(inputBytes)/4 + estimateTokens(pr.Text),
		}
	}

	resp := types.ChatCompletionResponse{
		ID:      fmt.Sprintf("chatcmpl-%d", now.UnixNano()),
		Object:  "chat.completion",
		Created: now.Unix(),
		Model:   model,
		Choices: []types.Choice{
			{
				Index: 0,
				Message: types.ChatMessage{
					Role:    "assistant",
					Content: pr.Text,
				},
				FinishReason: "stop",
			},
		},
		Usage:     u,
		SessionID: pr.SessionID,
	}
	writeJSON(w, http.StatusOK, resp)
}

// buildTextInput extracts the last user message text for plain-text stdin mode.
func buildTextInput(msgs []types.ChatMessage) ([]byte, error) {
	var lastUser *types.ChatMessage
	for i := len(msgs) - 1; i >= 0; i-- {
		if msgs[i].Role == "user" {
			lastUser = &msgs[i]
			break
		}
	}
	if lastUser == nil {
		return nil, fmt.Errorf("no user message found")
	}

	text, err := contentToString(lastUser.Content)
	if err != nil {
		return nil, err
	}
	if text == "" {
		return nil, fmt.Errorf("user message has no text content")
	}
	return []byte(text), nil
}

// buildStreamJSONInput converts OpenAI-format messages with image_url blocks
// into Claude CLI's --input-format stream-json JSONL format.
// Images are sent inline as base64 content blocks — no temp files needed.
// Image order is strictly preserved.
func buildStreamJSONInput(msgs []types.ChatMessage) ([]byte, error) {
	var lastUser *types.ChatMessage
	for i := len(msgs) - 1; i >= 0; i-- {
		if msgs[i].Role == "user" {
			lastUser = &msgs[i]
			break
		}
	}
	if lastUser == nil {
		return nil, fmt.Errorf("no user message found")
	}

	// Build content blocks array in Claude API format.
	contentBlocks, err := convertToClaudeContentBlocks(lastUser.Content)
	if err != nil {
		return nil, err
	}

	if len(contentBlocks) == 0 {
		return nil, fmt.Errorf("user message has no content blocks")
	}

	// Build the stream-json JSONL line.
	msg := map[string]any{
		"type": "user",
		"message": map[string]any{
			"role":    "user",
			"content": contentBlocks,
		},
		"session_id":         "default",
		"parent_tool_use_id": nil,
	}

	data, err := json.Marshal(msg)
	if err != nil {
		return nil, fmt.Errorf("marshal stream-json input: %w", err)
	}

	return append(data, '\n'), nil
}

// convertToClaudeContentBlocks converts OpenAI-format content (string or []ContentBlock)
// into Claude API content blocks with inline images.
func convertToClaudeContentBlocks(content any) ([]map[string]any, error) {
	switch v := content.(type) {
	case string:
		return []map[string]any{{"type": "text", "text": v}}, nil

	case []any:
		var blocks []map[string]any
		for _, item := range v {
			m, ok := item.(map[string]any)
			if !ok {
				continue
			}

			t, _ := m["type"].(string)
			// Prompt caching: pass through cache_control markers from the caller
			// so they reach the Claude API. The CLI relays these verbatim.
			// Field shape: {"type": "ephemeral", "ttl": "5m" | "1h"}
			cacheControl, _ := m["cache_control"].(map[string]any)

			switch t {
			case "text":
				text, _ := m["text"].(string)
				if text != "" {
					block := map[string]any{"type": "text", "text": text}
					if cacheControl != nil {
						block["cache_control"] = cacheControl
					}
					blocks = append(blocks, block)
				}

			case "image_url":
				imageURL, ok := m["image_url"].(map[string]any)
				if !ok {
					continue
				}
				rawURL, _ := imageURL["url"].(string)
				if rawURL == "" {
					continue
				}

				mediaType, b64Data, err := parseDataURL(rawURL)
				if err != nil {
					return nil, err
				}

				block := map[string]any{
					"type": "image",
					"source": map[string]any{
						"type":       "base64",
						"media_type": mediaType,
						"data":       b64Data,
					},
				}
				if cacheControl != nil {
					block["cache_control"] = cacheControl
				}
				blocks = append(blocks, block)
			}
		}
		return blocks, nil

	case nil:
		return nil, fmt.Errorf("content is nil")

	default:
		return nil, fmt.Errorf("unsupported content type: %T", content)
	}
}

// parseDataURL extracts media type and base64 data from a data: URL.
// Handles double data: prefixes and missing padding.
func parseDataURL(rawURL string) (mediaType string, b64Data string, err error) {
	if !strings.HasPrefix(rawURL, "data:") {
		return "", "", fmt.Errorf("not a data: URL")
	}

	// Use the LAST ";base64," marker to handle double-prefixed URLs.
	lastIdx := strings.LastIndex(rawURL, ";base64,")
	if lastIdx < 0 {
		return "", "", fmt.Errorf("no ;base64, marker found in data URL")
	}

	// Extract media type from the innermost data: prefix.
	header := rawURL[:lastIdx]
	mediaType = "image/png" // default
	if i := strings.LastIndex(header, "data:"); i >= 0 {
		mediaType = header[i+5:]
	}

	b64Data = rawURL[lastIdx+8:]

	// Strip whitespace that some encoders insert.
	b64Data = strings.Map(func(r rune) rune {
		if r == ' ' || r == '\n' || r == '\r' || r == '\t' {
			return -1
		}
		return r
	}, b64Data)

	// Pad if needed.
	if mod := len(b64Data) % 4; mod != 0 {
		b64Data += strings.Repeat("=", 4-mod)
	}

	return mediaType, b64Data, nil
}

// messagesHaveImages checks if any user message contains image_url blocks.
func messagesHaveImages(msgs []types.ChatMessage) bool {
	for _, m := range msgs {
		if m.Role != "user" {
			continue
		}
		items, ok := m.Content.([]any)
		if !ok {
			continue
		}
		for _, item := range items {
			if block, ok := item.(map[string]any); ok {
				if t, _ := block["type"].(string); t == "image_url" {
					return true
				}
			}
		}
	}
	return false
}

// messagesHaveCacheControl checks if any user content block carries a cache_control marker.
// Callers set these to pin a prefix boundary for Anthropic's prompt cache.
func messagesHaveCacheControl(msgs []types.ChatMessage) bool {
	for _, m := range msgs {
		if m.Role != "user" {
			continue
		}
		items, ok := m.Content.([]any)
		if !ok {
			continue
		}
		for _, item := range items {
			if block, ok := item.(map[string]any); ok {
				if _, has := block["cache_control"]; has {
					return true
				}
			}
		}
	}
	return false
}

// extractSystemPrompt returns the text of the first system message, if any.
func extractSystemPrompt(msgs []types.ChatMessage) string {
	for _, m := range msgs {
		if m.Role == "system" {
			text, _ := contentToString(m.Content)
			return text
		}
	}
	return ""
}

// contentToString converts a ChatMessage Content field (string or []ContentBlock) to plain text.
func contentToString(content any) (string, error) {
	switch v := content.(type) {
	case string:
		return v, nil
	case []any:
		var parts []string
		for _, item := range v {
			if m, ok := item.(map[string]any); ok {
				if t, ok := m["text"].(string); ok {
					parts = append(parts, t)
				}
			}
		}
		return strings.Join(parts, ""), nil
	case nil:
		return "", nil
	default:
		data, err := json.Marshal(v)
		if err != nil {
			return "", fmt.Errorf("unsupported content type: %T", content)
		}
		return string(data), nil
	}
}

// estimateTokens is a rough approximation: ~4 chars per token.
func estimateTokens(s string) int {
	return len(s) / 4
}
