package api

import (
	"encoding/json"
	"net/http"
	"os/exec"
	"strings"
)

func (h *Handler) handleRoot(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"name":    "ccproxy",
		"version": "2.0.0",
		"endpoints": []string{
			"GET  /",
			"GET  /health",
			"GET  /stats",
			"GET  /v1/models",
			"GET  /v1/models/:id",
			"POST /v1/chat/completions",
		},
	})
}

func (h *Handler) handleHealth(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"status":         "ok",
		"claude_version": claudeVersion(h.cfg.ClaudeBin),
	})
}

func (h *Handler) handleStats(w http.ResponseWriter, r *http.Request) {
	s := h.pool.Stats()
	writeJSON(w, http.StatusOK, map[string]any{
		"total_spawned":  s.TotalSpawned,
		"total_requests": s.TotalRequests,
	})
}

func claudeVersion(bin string) string {
	out, err := exec.Command(bin, "--version").Output()
	if err != nil {
		return "unknown"
	}
	return strings.TrimSpace(string(out))
}

// writeJSON is a helper that marshals v and writes it with the given status.
func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	enc := json.NewEncoder(w)
	enc.SetEscapeHTML(false)
	_ = enc.Encode(v)
}

// writeError writes a JSON error response in OpenAI format.
func writeError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]any{
		"error": map[string]string{
			"message": msg,
			"type":    "invalid_request_error",
		},
	})
}
