import { ML_API } from '@/features/training/composables/useTrainingApi'

/**
 * Règles de filtrage eBay actives — snapshot lecture seule de
 * `ml/sources/ebay/filters.py`. Sert le panneau « Règles de filtrage »
 * (ce qu'on garde, ce qu'on écarte, et pourquoi).
 */

export interface FilterRule {
  name: string
  kind: 'reject' | 'flag'
  description: string
  pattern: string | null
  threshold: number | null
  policy: string | null
}

export interface EbayFilterConfig {
  rules: FilterRule[]
  source_path: string
}

export async function fetchFilterConfig(): Promise<EbayFilterConfig | null> {
  try {
    const resp = await fetch(`${ML_API}/sources/ebay/filter-config`)
    if (!resp.ok) return null
    return await resp.json()
  } catch {
    return null
  }
}
