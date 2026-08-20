// Composable pour /review-queue/lots* (V1.5).
//
// Backend : ml/api/review_queue_routes.py — endpoints list_lots / get_lot
// / decide_lot. Doc : docs/sources-refacto/lot-review-kickoff.md §L.A.

import { eurioApi, EurioApiError } from '@/shared/api/eurio-api'
import { ML_API } from '@/features/training/composables/useTrainingApi'

// ─── Types alignés sur Pydantic ───────────────────────────────────────

export interface LotListItem {
  listing_key: string
  source: string
  target_eurio_id: string | null
  listing_title: string | null
  listing_price: number | null
  listing_currency: string
  is_lot_suspected: boolean
  n_images: number
  n_crops_in_review: number
  /** Crops de ce listing que la banque rattache à la classe pêchée.
   *  `null` hors pêche : « pas demandé » ≠ « zéro ». */
  n_matching_crops?: number | null
  oldest_enqueued_at: string
  thumb_url: string | null
}

export interface LotListResponse {
  items: LotListItem[]
  total: number
}

export interface LotCandidate {
  eurio_id: string
  score: number
  label: string
  country: string
  denomination: string
  year: number | null
  canonical_thumb_url: string
}

export interface LotBbox {
  x: number
  y: number
  w: number
  h: number
}

export interface LotCrop {
  asset_id: string
  review_id: string
  crop_url: string
  crop_index: number
  phash: number | null
  current_eurio_id: string | null
  candidate_eurio_ids: LotCandidate[]
  bbox: LotBbox | null
  /**
   * PÊCHE : la banque rattache-t-elle CE crop à la classe pêchée ?
   * `null`/absent hors pêche — « la question n'a pas été posée » ne vaut pas
   * « non ». Un coffret de 36 vignettes dont une seule est la classe se
   * trierait à l'œil sans ce drapeau, alors que la réponse est en base.
   */
  matches_dino_class?: boolean | null
  /**
   * La MARGE de la prédiction sur ce crop (`COALESCE(country_spread, spread)`).
   * C'est elle qui sépare, pas la similarité. Servie même hors pêche : c'est un
   * signal d'affichage. `null` quand la banque n'a pas scoré le crop.
   */
  dino_spread?: number | null
}

export interface LotDetection {
  cx: number
  cy: number
  r: number
  accepted: boolean
  reject_reason: string | null
  method: string
  crop_index: number | null
}

export interface LotImage {
  source_image_id: string
  image_index: number | null
  raw_url: string
  raw_width: number | null
  raw_height: number | null
  detections: LotDetection[]
  crops: LotCrop[]
}

export interface LotDetail {
  listing_key: string
  source: string
  target_eurio_id: string | null
  /** ReviewCandidate enrichi de la cible eBay (image, label, pays/année).
   *  Sert à pré-sélectionner la cible par défaut côté front lot, comme
   *  ReviewItem.target_candidate côté single. null si target_eurio_id
   *  est null ou la coin n'est pas dans le catalog. */
  target_candidate: LotCandidate | null
  listing_title: string | null
  listing_price: number | null
  listing_currency: string
  is_lot_suspected: boolean
  is_multi_crop_single: boolean
  images: LotImage[]
  prev_listing_key: string | null
  next_listing_key: string | null
}

export type LotRejectReason =
  | 'not_a_coin'
  | 'out_of_scope'
  | 'duplicate_in_listing'
  | 'unreadable'
  | 'other'

export interface LotAssignment {
  asset_id: string
  eurio_id?: string
  face?: 'obverse' | 'reverse' | 'unknown'
  variant_kind?: string
  reject_reason?: LotRejectReason
  skip?: boolean
}

export interface LotDecideResponse {
  done: number
  rejected: number
  skipped: number
  errors: string[]
}

// ─── HTTP helpers ─────────────────────────────────────────────────────

export class LotReviewError extends Error {
  status: number
  detail: unknown
  constructor(status: number, message: string, detail?: unknown) {
    super(message)
    this.status = status
    this.detail = detail
    this.name = 'LotReviewError'
  }
}

async function parseError(resp: Response): Promise<LotReviewError> {
  let detail: unknown = null
  let msg = `HTTP ${resp.status}`
  try {
    detail = await resp.json()
    if (detail && typeof detail === 'object' && 'detail' in detail) {
      msg = String((detail as { detail: unknown }).detail)
    }
  } catch {
    // ignore
  }
  return new LotReviewError(resp.status, msg, detail)
}

function withMlApi(url: string | null): string | null {
  if (!url) return null
  return url.startsWith('http') ? url : `${ML_API}${url}`
}

// ─── Public API ───────────────────────────────────────────────────────

export async function fetchLots(
  opts: {
    limit?: number
    offset?: number
    cohortId?: string | null
    targetEurioId?: string | null
    designGroup?: string | null
    /** Pêche : les listings qui contiennent ≥ 1 crop de cette classe. */
    dinoClass?: string | null
    /** Position de la classe dans le top-k qui suffit à la retenir (1 | 3 | 5). */
    dinoRank?: number | null
    dinoMinSpread?: number | null
    /** `false` lève le filtre pays (actif par défaut côté API). */
    dinoCountryOnly?: boolean
  } = {},
): Promise<LotListResponse> {
  const params = new URLSearchParams()
  if (opts.limit) params.set('limit', String(opts.limit))
  if (opts.offset) params.set('offset', String(opts.offset))
  // Priorité côté API : dino_class (pêche) > design_group (ère standard)
  // > target_eurio_id (commémo) > cohort_id.
  if (opts.dinoClass) params.set('dino_class', opts.dinoClass)
  if (opts.dinoRank) params.set('dino_rank', String(opts.dinoRank))
  if (opts.dinoMinSpread != null) params.set('dino_min_spread', String(opts.dinoMinSpread))
  if (opts.dinoCountryOnly === false) params.set('dino_country_only', 'false')
  if (opts.designGroup) params.set('design_group', opts.designGroup)
  if (opts.targetEurioId) params.set('target_eurio_id', opts.targetEurioId)
  if (opts.cohortId) params.set('cohort_id', opts.cohortId)
  const qs = params.size ? `?${params.toString()}` : ''
  // Phase 2c-b : porté sur eurio-api (Bearer PAT).
  let body: LotListResponse
  try {
    body = await eurioApi.get<LotListResponse>(`/review-queue/lots${qs}`)
  } catch (err) {
    if (err instanceof EurioApiError) throw new Error(`${err.status} ${err.message}`)
    throw err
  }
  return {
    ...body,
    items: body.items.map((it) => ({
      ...it,
      thumb_url: withMlApi(it.thumb_url),
    })),
  }
}

function promoteCandidate(c: LotCandidate): LotCandidate {
  return { ...c, canonical_thumb_url: withMlApi(c.canonical_thumb_url) ?? '' }
}

export async function fetchLot(
  listingKey: string,
  /**
   * Périmètre de la file qu'on déroule, passé tel quel en query. Il ne change
   * pas le contenu du lot — seulement `prev/next_listing_key`. L'omettre fait
   * dérouler la file lot GLOBALE : « suivant » sort alors de la classe au
   * premier clic, sans que rien ne le signale.
   */
  scope?: Record<string, string>,
): Promise<LotDetail> {
  // Phase 2c-b : porté sur eurio-api (Bearer PAT).
  const qs = scope && Object.keys(scope).length
    ? `?${new URLSearchParams(scope).toString()}`
    : ''
  let body: LotDetail
  try {
    body = await eurioApi.get<LotDetail>(
      `/review-queue/lots/${encodeURIComponent(listingKey)}${qs}`,
    )
  } catch (err) {
    if (err instanceof EurioApiError) throw new Error(`${err.status} ${err.message}`)
    throw err
  }
  return {
    ...body,
    target_candidate: body.target_candidate ? promoteCandidate(body.target_candidate) : null,
    images: body.images.map((im) => ({
      ...im,
      raw_url: withMlApi(im.raw_url) ?? '',
      crops: im.crops.map((c) => ({
        ...c,
        crop_url: withMlApi(c.crop_url) ?? '',
        candidate_eurio_ids: c.candidate_eurio_ids.map(promoteCandidate),
      })),
    })),
  }
}

export async function decideLot(
  listingKey: string,
  assignments: LotAssignment[],
): Promise<LotDecideResponse> {
  // Direction A / C3 : la décision de lot est une écriture CANONIQUE → VPS
  // (jumeau `serving/funnel_writes.decide_lot`, chemin identique) via eurioApi,
  // PAS l'API ML locale (readonly sous le flip). Le compute lourd (detect/
  // add-crop/sync-crops ci-dessous) reste sur ML_API — lui seul touche cv2.
  try {
    return await eurioApi.post<LotDecideResponse>(
      `/review-queue/lots/${encodeURIComponent(listingKey)}/decide`,
      { assignments },
    )
  } catch (err) {
    if (err instanceof EurioApiError) throw new Error(`${err.status} ${err.message}`)
    throw err
  }
}

export interface LotImageDetectResponse {
  source_image_id: string
  detections: LotDetection[]
}

/**
 * Re-détection LIVE d'UNE image (Chunk C) — rattrapage manuel quand le scrape
 * a raté des pièces. Relance detect_circles_multi côté backend, rafraîchit
 * detections_json, renvoie les cercles (acceptés + rejetés) pour overlay.
 * Coûteux (YOLO+Hough) → une image à la fois, déclenché à la main.
 */
export async function detectLotImage(
  listingKey: string,
  sourceImageId: string,
): Promise<LotImageDetectResponse> {
  const resp = await fetch(
    `${ML_API}/review-queue/lots/${encodeURIComponent(listingKey)}`
    + `/images/${encodeURIComponent(sourceImageId)}/detect`,
    { method: 'POST' },
  )
  if (!resp.ok) throw await parseError(resp)
  return (await resp.json()) as LotImageDetectResponse
}

/**
 * Add-crop manuel (Chunk D) : crée un nouveau crop sur une source_image depuis
 * un cercle (cx,cy,r en px natifs du raw). Renvoie le LotCrop enrichi (avec
 * review_id + candidats) à insérer en place dans le lot. Rattrapage des pièces
 * ratées par la détection (cercle détecté cliqué OU tracé manuel).
 */
export async function addLotCrop(
  listingKey: string,
  sourceImageId: string,
  circle: { cx: number; cy: number; r: number },
): Promise<LotCrop> {
  const resp = await fetch(
    `${ML_API}/review-queue/lots/${encodeURIComponent(listingKey)}`
    + `/images/${encodeURIComponent(sourceImageId)}/crops`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(circle),
    },
  )
  if (!resp.ok) throw await parseError(resp)
  const crop = (await resp.json()) as LotCrop
  return {
    ...crop,
    crop_url: withMlApi(crop.crop_url) ?? '',
    candidate_eurio_ids: crop.candidate_eurio_ids.map(promoteCandidate),
  }
}

export interface LotSyncCropsResponse {
  source_image_id: string
  crops: LotCrop[]
  repointed: number
  created: number
  deleted: number
}

/**
 * Resync crops ↔ détection — action explicite, distincte de Re-détecter.
 * Reconstruit les crops d'UNE image pour coller aux cercles ACCEPTÉS du constat
 * (`detections_json`, l'overlay validé) : re-pointe / crée / supprime. Le
 * backend recompute le Dino par crop (corrige les suggestions périmées).
 * REFUSE (409) si un crop est déjà décidé. Ne relance PAS la détection.
 */
export async function syncLotCrops(
  listingKey: string,
  sourceImageId: string,
): Promise<LotSyncCropsResponse> {
  const resp = await fetch(
    `${ML_API}/review-queue/lots/${encodeURIComponent(listingKey)}`
    + `/images/${encodeURIComponent(sourceImageId)}/sync-crops`,
    { method: 'POST' },
  )
  if (!resp.ok) throw await parseError(resp)
  const data = (await resp.json()) as LotSyncCropsResponse
  return {
    ...data,
    crops: data.crops.map((crop) => ({
      ...crop,
      crop_url: withMlApi(crop.crop_url) ?? '',
      candidate_eurio_ids: crop.candidate_eurio_ids.map(promoteCandidate),
    })),
  }
}

export interface RequalifySingleResponse {
  status: string
  listing_key: string
  n_requalified: number
  n_images: number
}

/**
 * Inverse de la requalif single→lot : ce listing n'est PAS un lot (faux
 * positif v2). Rebascule toutes ses rows open en kind='single' → elles
 * repartent dans le flow single.
 */
export async function requalifyLotAsSingle(
  listingKey: string,
): Promise<RequalifySingleResponse> {
  // Direction A / C3 : requalif canonique (lot→single) → VPS (jumeau lean
  // serving/review_queue/writes.py, chemin identique) via eurioApi, PAS ML_API.
  try {
    return await eurioApi.post<RequalifySingleResponse>(
      `/review-queue/lots/${encodeURIComponent(listingKey)}/requalify-single`,
      undefined,
    )
  } catch (err) {
    if (err instanceof EurioApiError) throw new Error(`${err.status} ${err.message}`)
    throw err
  }
}
