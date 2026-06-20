import { eurioApi } from '@/shared/api/eurio-api'

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
    return await eurioApi.get<EbayFilterConfig>('/sources/ebay/filter-config')
  } catch {
    return null
  }
}
