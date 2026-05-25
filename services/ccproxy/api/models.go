package api

import (
	"net/http"

	"github.com/go-chi/chi/v5"

	"ccproxy/types"
)

// knownModels is the list of Claude models exposed via /v1/models.
var knownModels = []types.ModelObject{
	{ID: "claude-opus-4-6", Object: "model", Created: 1740000000, OwnedBy: "anthropic"},
	{ID: "claude-sonnet-4-6", Object: "model", Created: 1740000000, OwnedBy: "anthropic"},
	{ID: "claude-haiku-4-5-20251001", Object: "model", Created: 1730000000, OwnedBy: "anthropic"},
	{ID: "claude-sonnet-4-5-20250929", Object: "model", Created: 1727600000, OwnedBy: "anthropic"},
	{ID: "claude-haiku-3-5-20241022", Object: "model", Created: 1729555200, OwnedBy: "anthropic"},
}

var modelIndex = func() map[string]types.ModelObject {
	m := make(map[string]types.ModelObject, len(knownModels))
	for _, mo := range knownModels {
		m[mo.ID] = mo
	}
	return m
}()

func (h *Handler) handleModels(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, types.ModelList{
		Object: "list",
		Data:   knownModels,
	})
}

func (h *Handler) handleModelByID(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "id")
	mo, ok := modelIndex[id]
	if !ok {
		writeError(w, http.StatusNotFound, "model '"+id+"' not found")
		return
	}
	writeJSON(w, http.StatusOK, mo)
}
