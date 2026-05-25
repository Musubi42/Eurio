package types

// ChatCompletionRequest is the OpenAI-compatible request body.
// SessionID is a ccproxy extension for conversation continuity.
type ChatCompletionRequest struct {
	Model     string        `json:"model"`
	Messages  []ChatMessage `json:"messages"`
	Stream    bool          `json:"stream"`
	SessionID string        `json:"session_id"`
	MaxTokens *int          `json:"max_tokens,omitempty"`
}

// ChatMessage is a single message in the conversation.
// Content can be either a plain string or a slice of ContentBlock (for multi-modal).
type ChatMessage struct {
	Role    string `json:"role"`
	Content any    `json:"content"` // string or []ContentBlock
}

// ContentBlock represents a structured content item within a message.
type ContentBlock struct {
	Type     string `json:"type"`
	Text     string `json:"text,omitempty"`
	ImageURL *struct {
		URL string `json:"url"`
	} `json:"image_url,omitempty"`
}

// ChatCompletionResponse is the OpenAI-compatible non-streaming response.
// SessionID is a ccproxy extension.
type ChatCompletionResponse struct {
	ID        string   `json:"id"`
	Object    string   `json:"object"`
	Created   int64    `json:"created"`
	Model     string   `json:"model"`
	Choices   []Choice `json:"choices"`
	Usage     Usage    `json:"usage"`
	SessionID string   `json:"session_id"`
}

// Choice is one completion candidate.
type Choice struct {
	Index        int         `json:"index"`
	Message      ChatMessage `json:"message"`
	FinishReason string      `json:"finish_reason"`
}

// Usage contains token counts from Claude CLI JSONL (real data when available).
type Usage struct {
	PromptTokens             int     `json:"prompt_tokens"`
	CompletionTokens         int     `json:"completion_tokens"`
	TotalTokens              int     `json:"total_tokens"`
	CacheCreationInputTokens int     `json:"cache_creation_input_tokens,omitempty"`
	CacheReadInputTokens     int     `json:"cache_read_input_tokens,omitempty"`
	AnthropicCostUSD         float64 `json:"anthropic_cost_usd,omitempty"` // Official cost from Claude CLI result
}

// ModelObject matches the OpenAI model list format.
type ModelObject struct {
	ID      string `json:"id"`
	Object  string `json:"object"`
	Created int64  `json:"created"`
	OwnedBy string `json:"owned_by"`
}

// ModelList is the response for GET /v1/models.
type ModelList struct {
	Object string        `json:"object"`
	Data   []ModelObject `json:"data"`
}
