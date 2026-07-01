import type { Coin, CoinImageDict } from '@/shared/types/domain'
import { ML_API } from '@/features/training/composables/useTrainingApi'

/**
 * Resolve the canonical thumbnail URL for a coin.
 *
 * In dev (import.meta.env.DEV), the source of truth lives in eurio.db (local)
 * and the images are served by the ML FastAPI from ml/canonical_images/.
 * Cf. memory `feedback_architecture_eurio_db_vs_supabase` (2026-05-24).
 *
 * To avoid asking for zombie coins (present in Supabase but not in eurio.db),
 * a client-side index (`loadCanonicalIndex`) is fetched once and gates the
 * dev rewrite. Coins outside the index fall back to the legacy `coin.images`
 * field (which may itself be empty → shows the placeholder).
 *
 * In a built admin (Vercel preview/prod), the ML API is unreachable, so we
 * always serve from `coin.images`.
 */
let canonicalIndex: Set<string> | null = null

/**
 * Load and cache the set of eurio_ids that have a local canonical image.
 * Idempotent — caller can fire-and-forget at mount, subsequent calls return
 * the already-loaded set. On error (ML API offline), returns empty set so
 * the resolver falls back to Supabase URLs.
 */
export async function loadCanonicalIndex(): Promise<Set<string>> {
  if (canonicalIndex) return canonicalIndex
  if (!import.meta.env.DEV) {
    canonicalIndex = new Set()
    return canonicalIndex
  }
  try {
    const resp = await fetch(`${ML_API}/referential/canonical-index`, {
      signal: AbortSignal.timeout(3000),
    })
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const data = await resp.json() as { eurio_ids: string[] }
    canonicalIndex = new Set(data.eurio_ids)
  } catch {
    canonicalIndex = new Set()
  }
  return canonicalIndex
}

export function firstImageUrl(coin: Coin): string | null {
  // Dev: serve from local FastAPI when we know we have it. Otherwise fall
  // back to the legacy field — which may itself be null → placeholder shown.
  if (
    import.meta.env.DEV
    && coin.eurio_id
    && canonicalIndex?.has(coin.eurio_id)
  ) {
    return `${ML_API}/referential/canonical/${encodeURIComponent(coin.eurio_id)}/obverse/thumb`
  }

  return firstImageUrlFromImagesField(coin.images)
}

/**
 * Pre-dev resolver. Reads the legacy `coins.images` field with its three
 * historic shapes.
 */
function firstImageUrlFromImagesField(img: Coin['images']): string | null {
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
