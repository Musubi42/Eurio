import type { Coin, CoinImageDict } from '@/shared/supabase/types'

/**
 * Extract the best display image URL from a coin (preferring obverse, then
 * the highest-resolution / lowest-bandwidth variant available).
 *
 * Three input shapes coexist:
 *   - New per-eurio_id:   { obverse: [{source,url,thumb_url,width,...}], reverse: [...] }
 *   - Legacy Numista:     { obverse, reverse, obverse_thumb, reverse_thumb }
 *   - Legacy flat array:  [{url, role, source}]
 */
export function firstImageUrl(coin: Coin): string | null {
  const img = coin.images
  if (!img) return null

  if (Array.isArray(img)) {
    if (img.length === 0) return null
    const obverse = img.find(i => i.role === 'obverse')
    return obverse?.url ?? img[0]?.url ?? null
  }

  const obj = img as Record<string, unknown>

  // New shape — array per role. Pick obverse → highest width, fall back to thumb_url.
  if (Array.isArray(obj.obverse) || Array.isArray(obj.reverse)) {
    const pick = (variants: unknown): string | null => {
      if (!Array.isArray(variants) || variants.length === 0) return null
      const sorted = [...variants].sort(
        (a, b) => ((b.width as number) ?? 0) - ((a.width as number) ?? 0),
      )
      const v = sorted[0] as Record<string, unknown>
      return (v.thumb_url as string) ?? (v.url as string) ?? null
    }
    return pick(obj.obverse) ?? pick(obj.reverse)
  }

  // Legacy Numista dict — prefer thumb to save bandwidth on the grid.
  const dict = img as CoinImageDict
  return dict.obverse_thumb ?? dict.obverse ?? dict.reverse_thumb ?? dict.reverse ?? null
}
