package types

// ClaudeMsg represents a single JSONL line emitted by `claude --output-format stream-json`.
// Claude v2.x uses snake_case ("session_id"); older versions used camelCase ("sessionId").
// Both are captured and GetSessionID() returns whichever is present.
type ClaudeMsg struct {
	Type           string         `json:"type"`
	Subtype        string         `json:"subtype,omitempty"`
	SessionIDSnake string         `json:"session_id,omitempty"` // v2.x (snake_case)
	SessionIDCamel string         `json:"sessionId,omitempty"`  // legacy (camelCase)
	Message        *ClaudeMessage `json:"message,omitempty"`
	Result         string         `json:"result,omitempty"`
	Error          string         `json:"error,omitempty"`
	IsError        bool           `json:"is_error,omitempty"`
	// Fields present on type=result messages:
	TotalCostUSD float64      `json:"total_cost_usd,omitempty"` // Anthropic's official cost for the turn
	Usage        *ClaudeUsage `json:"usage,omitempty"`          // Cumulative usage for the turn (on result msg)
}

// GetSessionID returns the session ID regardless of which JSON field name was used.
func (m ClaudeMsg) GetSessionID() string {
	if m.SessionIDSnake != "" {
		return m.SessionIDSnake
	}
	return m.SessionIDCamel
}

// ClaudeMessage is the assistant turn inside a ClaudeMsg.
type ClaudeMessage struct {
	ID      string              `json:"id,omitempty"`
	Type    string              `json:"type,omitempty"`
	Role    string              `json:"role"`
	Content []ClaudeContentItem `json:"content"`
	Model   string              `json:"model,omitempty"`
	Usage   *ClaudeUsage        `json:"usage,omitempty"`
}

// ClaudeContentItem is one item in a Claude message's content array.
type ClaudeContentItem struct {
	Type  string `json:"type"` // "text", "tool_use", "tool_result", "thinking"
	Text  string `json:"text,omitempty"`
	ID    string `json:"id,omitempty"`
	Name  string `json:"name,omitempty"`
	Input any    `json:"input,omitempty"`
}

// ClaudeUsage is the token usage block from a Claude assistant message.
type ClaudeUsage struct {
	InputTokens              int `json:"input_tokens"`
	CacheCreationInputTokens int `json:"cache_creation_input_tokens"`
	CacheReadInputTokens     int `json:"cache_read_input_tokens"`
	OutputTokens             int `json:"output_tokens"`
}

// Add accumulates another usage into this one (for multi-message turns).
func (u *ClaudeUsage) Add(other *ClaudeUsage) {
	if other == nil {
		return
	}
	u.InputTokens += other.InputTokens
	u.CacheCreationInputTokens += other.CacheCreationInputTokens
	u.CacheReadInputTokens += other.CacheReadInputTokens
	u.OutputTokens += other.OutputTokens
}

