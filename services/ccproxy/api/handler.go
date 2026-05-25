package api

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"

	"ccproxy/config"
	"ccproxy/pool"
)

// Handler bundles shared dependencies and the chi router.
type Handler struct {
	cfg    *config.Config
	pool   *pool.Pool
	router chi.Router
}

// New creates a Handler with all routes registered.
func New(cfg *config.Config, p *pool.Pool) *Handler {
	h := &Handler{cfg: cfg, pool: p}
	h.router = h.buildRouter()
	return h
}

// Router returns the http.Handler for the server.
func (h *Handler) Router() http.Handler {
	return h.router
}

func (h *Handler) buildRouter() chi.Router {
	r := chi.NewRouter()

	// Middleware
	r.Use(middleware.RealIP)
	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)
	r.Use(corsMiddleware(h.cfg.AllowOrigins))

	// Routes
	r.Get("/", h.handleRoot)
	r.Get("/health", h.handleHealth)
	r.Get("/stats", h.handleStats)

	r.Route("/v1", func(r chi.Router) {
		r.Get("/models", h.handleModels)
		r.Get("/models/{id}", h.handleModelByID)
		r.Post("/chat/completions", h.handleChatCompletions)
	})

	return r
}

// corsMiddleware adds CORS headers for the configured origins.
func corsMiddleware(origins []string) func(http.Handler) http.Handler {
	allowAll := len(origins) == 1 && origins[0] == "*"

	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			origin := r.Header.Get("Origin")

			if allowAll {
				w.Header().Set("Access-Control-Allow-Origin", "*")
			} else {
				for _, o := range origins {
					if o == origin {
						w.Header().Set("Access-Control-Allow-Origin", origin)
						w.Header().Set("Vary", "Origin")
						break
					}
				}
			}

			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")

			if r.Method == http.MethodOptions {
				w.WriteHeader(http.StatusNoContent)
				return
			}

			next.ServeHTTP(w, r)
		})
	}
}
