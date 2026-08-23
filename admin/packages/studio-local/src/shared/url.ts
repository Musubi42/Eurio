/**
 * Ajout d'un paramètre de cache-busting à une URL d'image.
 *
 * POURQUOI CE HELPER EXISTE
 * -------------------------
 * Un crop est ÉCRASÉ AU MÊME CHEMIN quand on le recadre : sans casser le cache,
 * le navigateur ressert l'ancienne image et l'écran ment. D'où le `?v=<phash>`
 * historique.
 *
 * Depuis le lot 1 de `review-collaborative-v2`, ces URLs sont des URLs MinIO
 * PRÉSIGNÉES — elles portent déjà une query string
 * (`?AWSAccessKeyId=…&Signature=…&Expires=…`). Coller un second `?` produit une
 * URL malformée que MinIO refuse. Mesuré le 2026-08-23 sur une URL réelle :
 *
 *     URL signée nue     → 200
 *     + '?v=123'         → 400   ← le bug
 *     + '&v=123'         → 200   ← le correctif
 *
 * La panne était parfaitement muette côté serveur : l'API répondait 200 avec une
 * URL correcte, et seule l'image ne s'affichait pas.
 */
export function withCacheBust(
  url: string | null | undefined,
  value: string | number | null | undefined,
): string {
  if (!url) return ''
  if (value === null || value === undefined || value === '') return url
  return `${url}${url.includes('?') ? '&' : '?'}v=${value}`
}
