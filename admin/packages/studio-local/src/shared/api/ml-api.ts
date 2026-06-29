/**
 * URL de base du ML API local (go-task ml:api → FastAPI sur 8042).
 *
 * Configurable via VITE_ML_API dans .env.local — utile si le port change
 * ou pour pointer vers un container. Par défaut 127.0.0.1 (pas localhost)
 * car uvicorn bind en IPv4 uniquement : sur macOS, localhost résout ::1 en
 * premier et ajoute ~500 ms de latence avant le fallback IPv4.
 */
export const ML_API: string =
  (import.meta.env.VITE_ML_API as string | undefined) ?? 'http://127.0.0.1:8042'
