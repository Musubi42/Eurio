// Coin enrichment assets — wraps ml/api/coin_assets_routes.py.
//
//   GET  /coins/{eurio_id}/assets?include_unresolved=&limit=&offset=
//   POST /coins/assets/reflag-needs-review
//
// B3 (direction 1, 2026-08-16) : compteurs, galerie et reflag lisent/écrivent le
// CANONIQUE (`eurioApi`), comme les métadonnées de la pièce et la file de review.
// Avant, le compteur lisait le ML API local pendant que la review écrivait sur le
// VPS : valider un crop n'incrémentait jamais le badge.
//
// Conséquence assumée : les crops produits localement en `--no-push` n'apparaissent
// qu'une fois poussés au canonique.
//
// Le `file_url` est désormais une URL S3 signée **absolue** — `promoteUrl` devient
// un no-op, exactement comme ce fichier l'avait anticipé. Les routes Dino et
// l'édition de crop restent sur ML_API : elles sont lourdes (cv2) et absentes de
// l'image lean du VPS.

import { eurioApi } from '@/shared/api/eurio-api'
import { ML_API } from '@/features/training/composables/useTrainingApi'
import { HAS_LOCAL_ML_API } from '@/shared/config/deploy-target'

export type CoinAssetStatus =
  | 'auto_name'
  | 'auto_phash'
  | 'manual'
  | 'needs_review'
  | 'rejected'

export interface CoinAsset {
  id: string
  source: string
  source_ref: string
  listing_url: string | null
  listing_title: string | null
  file_url: string  // promoted to absolute URL client-side
  face: 'obverse' | 'reverse' | 'unknown' | null
  variant_kind: string
  resolution_status: CoinAssetStatus
  resolution_confidence: number | null
  decided_by: string | null
  resolved_at: string | null
  width: number | null
  height: number | null
  /** B · si ce crop sert de référence Dino : 'fps' | 'manual_pin' |
   *  'manual_exclude'. null = n'en est pas une. */
  dino_reference: DinoRefMethod | null
}

export type DinoRefMethod = 'canonical' | 'fps' | 'manual_pin' | 'manual_exclude'

export interface DinoReferenceEntry {
  asset_id: string | null // null = ligne canonique (avers Numista)
  eurio_id: string
  method: DinoRefMethod
  rank: number | null
  selected_sim: number | null
  file_url: string | null // promu absolu client-side ; null pour le canonique
  face: 'obverse' | 'reverse' | 'unknown' | null
  resolution_status: CoinAssetStatus | null
}

export interface DinoReferencesResponse {
  eurio_id: string
  class_id: string
  anchors_kind: string
  /** true = banque jamais bâtie en multi-exemplaires (lancer le build). */
  never_built: boolean
  entries: DinoReferenceEntry[]
}

export interface CoinAssetsPage {
  eurio_id: string
  total: number
  assets: CoinAsset[]
  next_offset: number | null
}

export interface ReflagResponse {
  n_reflagged: number
  n_skipped: number
  skipped_reasons: string[]
  /** Rows review_queue open des assets fournis → navigation /review/manual?ids= */
  review_ids: string[]
}

function promoteUrl(url: string): string {
  return url.startsWith('http') ? url : `${ML_API}${url}`
}

export async function fetchCoinAssets(
  eurioId: string,
  opts: { includeUnresolved?: boolean; limit?: number; offset?: number } = {},
): Promise<CoinAssetsPage> {
  const params = new URLSearchParams()
  if (opts.includeUnresolved) params.set('include_unresolved', 'true')
  params.set('limit', String(opts.limit ?? 60))
  params.set('offset', String(opts.offset ?? 0))
  const body = await eurioApi.get<CoinAssetsPage>(
    `/coins/${encodeURIComponent(eurioId)}/assets?${params.toString()}`,
  )
  return {
    ...body,
    assets: body.assets.map((a) => ({ ...a, file_url: promoteUrl(a.file_url) })),
  }
}

/** Compteur global eurio_id → n_enrichment, pour les badges sur la
 *  liste des coins. Une seule query côté ML — coût ~ms. */
export async function fetchEnrichmentCounts(): Promise<Record<string, number>> {
  try {
    return await eurioApi.get<Record<string, number>>('/coins/enrichment-counts')
  } catch {
    return {}   // badge absent plutôt qu'une liste de coins en erreur
  }
}

export async function reflagAssetsNeedsReview(
  assetIds: string[],
): Promise<ReflagResponse> {
  // Écriture → canonique, comme la décision de review. Sous Direction A,
  // `eurio-api` est le writer unique : un reflag écrit en local ne serait jamais
  // vu par la file de review, qui est lue depuis le VPS.
  return await eurioApi.post<ReflagResponse>('/coins/assets/reflag-needs-review', {
    asset_ids: assetIds,
  })
}

// ─── Références Dino (improvement-loop B) ─────────────────────────────────

/** Références Dino de la CLASSE d'une pièce (canonique + exemplaires FPS +
 *  overrides), pour la section « Références Dino » de la page coin-detail. */
export async function fetchDinoReferences(
  eurioId: string,
): Promise<DinoReferencesResponse> {
  if (!HAS_LOCAL_ML_API) {
    return { eurio_id: eurioId, class_id: eurioId, anchors_kind: '2eur_all', never_built: true, entries: [] }
  }
  const resp = await fetch(
    `${ML_API}/coins/${encodeURIComponent(eurioId)}/dino-references`,
  )
  if (!resp.ok) throw new Error(`fetchDinoReferences failed: ${resp.status}`)
  const body = (await resp.json()) as DinoReferencesResponse
  return {
    ...body,
    entries: body.entries.map((e) => ({
      ...e,
      file_url: e.file_url ? promoteUrl(e.file_url) : null,
    })),
  }
}

/** Épingle / bannit / réinitialise un crop comme référence Dino. L'effet
 *  s'applique au prochain build d'ancres (pas de rebuild live). */
export async function setDinoReference(
  assetId: string,
  action: 'pin' | 'exclude' | 'clear',
): Promise<{ asset_id: string; action: string; applied: boolean; rebuild_required: boolean }> {
  const resp = await fetch(
    `${ML_API}/coins/assets/${encodeURIComponent(assetId)}/dino-reference`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    },
  )
  if (!resp.ok) throw new Error(`setDinoReference failed: ${resp.status}`)
  return await resp.json()
}

// ─── Visual helpers ─────────────────────────────────────────────────────

export interface StatusVisual {
  ringColor: string
  label: string
  labelColor: string
}

/** Couleurs ring + label par statut. Les `auto_*` + `manual` n'ont pas
 *  de label (ce sont les "validés" — sobre, pas de bruit visuel). */
export function statusVisual(status: CoinAssetStatus): StatusVisual {
  switch (status) {
    case 'auto_name':
    case 'auto_phash':
      return {
        ringColor: 'var(--success)',
        label: '',
        labelColor: 'var(--success)',
      }
    case 'manual':
      return {
        ringColor: 'var(--indigo-700)',
        label: '',
        labelColor: 'var(--indigo-700)',
      }
    case 'needs_review':
      return {
        ringColor: 'var(--gold-600)',
        label: 'needs review',
        labelColor: 'var(--gold-600)',
      }
    case 'rejected':
      return {
        ringColor: 'var(--danger)',
        label: 'rejected',
        labelColor: 'var(--danger)',
      }
  }
}

/** Initiale source (e=ebay, n=numista, c=catawiki, …) — petite pastille. */
export function sourceInitial(source: string): string {
  return (source || '?').trim().charAt(0).toLowerCase() || '?'
}
