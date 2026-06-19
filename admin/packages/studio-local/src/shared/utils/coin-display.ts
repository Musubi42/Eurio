/**
 * Display name resolver for a coin (chantier D, 2026-05-26).
 *
 * Stratégie :
 * - Commemos : on préfère le `commemorated_topic` verbeux Numista
 *   (lang FR > EN > autre). Plus distinctif que le `title` court
 *   "(Independence)".
 * - Standards : `theme` Numista si suffisamment verbeux (≥ 12 chars),
 *   sinon synthèse "<denom>€ standard (<variant>)" où `variant` est
 *   extrait du slug eurio_id après "-standard-". Évite les H1 d'1
 *   token ("1st map") ou l'eurio_id brut comme fallback.
 */
type TopicLike = { source: string; lang: string; topic: string }
type CoinLike = {
  eurio_id: string
  theme?: string | null
  is_commemorative: boolean
  face_value: number
  topics?: TopicLike[]
}

const LANG_PRIORITY = ['fr', 'en'] as const
const STANDARD_THEME_MIN_LENGTH = 12

export function coinDisplayName(coin: CoinLike): string {
  if (coin.is_commemorative) {
    const topics = coin.topics ?? []
    const numista = topics.filter((t) => t.source === 'numista_api')
    for (const lang of LANG_PRIORITY) {
      const hit = numista.find((t) => t.lang === lang)
      if (hit?.topic) return hit.topic
    }
    if (numista[0]?.topic) return numista[0].topic
  }

  const theme = (coin.theme ?? '').trim()
  if (theme.length >= STANDARD_THEME_MIN_LENGTH) return theme

  const variant = extractVariantFromSlug(coin.eurio_id)
  const denom = `${coin.face_value}€`
  if (variant) return `${denom} standard (${variant})`
  if (theme) return `${denom} standard (${theme})`
  return `${denom} standard`
}

function extractVariantFromSlug(eurioId: string): string | null {
  const m = eurioId.match(/-standard-(.+)$/)
  if (!m) return null
  return m[1].replace(/-/g, ' ')
}
