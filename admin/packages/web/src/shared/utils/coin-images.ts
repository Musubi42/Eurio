import type { Coin, CoinImageDict } from '@/shared/supabase/types'

/**
 * Extract the best display image URL from a coin.
 * Handles both legacy array format [{url, role}] and new dict format {obverse, reverse}.
 */
export function firstImageUrl(coin: Coin): string | null {
  const img = coin.images
  if (!img) return null
  if (!Array.isArray(img)) {
    const dict = img as CoinImageDict
    return dict.obverse ?? dict.reverse ?? null
  }
  if (img.length === 0) return null
  const obverse = img.find(i => i.role === 'obverse')
  return obverse?.url ?? img[0]?.url ?? null
}
