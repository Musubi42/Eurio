/**
 * Display name resolver for a coin (chantier D, 2026-05-26).
 *
 * Stratégie :
 * - Commemos : on préfère le `commemorated_topic` verbeux Numista
 *   (lang FR > EN > autre). Plus distinctif que le `title` court
 *   "(Independence)".
 * - Standards : `theme` Numista (déjà verbeux, type "Albert II - 2nd
 *   map, 1st type, 1st portrait"), fallback face_value.
 * - Fallback ultime : eurio_id.
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

export function coinDisplayName(coin: CoinLike): string {
  if (coin.is_commemorative) {
    const topics = coin.topics ?? []
    const numista = topics.filter((t) => t.source === 'numista_api')
    for (const lang of LANG_PRIORITY) {
      const hit = numista.find((t) => t.lang === lang)
      if (hit?.topic) return hit.topic
    }
    // Fallback : autre langue Numista, sinon theme
    if (numista[0]?.topic) return numista[0].topic
  }
  return coin.theme ?? coin.eurio_id
}
