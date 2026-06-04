// Composable — Crop Bench (banc de qualité du crop eBay).
//
// Backend : ml/api/crop_bench_routes.py (prefix /crop-bench). Source de
// vérité = ml/state/crop_diag/results.csv (diagnostic Otsu, lecture seule).
//
// Chunk 0 — lecture seule : stats agrégées + échantillon de cartes
// raw↔crop + overlay serveur (cercle pipeline vs vrai rim). Les colonnes
// d'algorithmes alternatifs (fitEllipse/EDCircles/FastSAM) arrivent aux
// chunks 1-2.
//
// Local-only : dégrade proprement si le backend ML est éteint.

import { ML_API } from '@/features/training/composables/useTrainingApi'

export class CropBenchApiError extends Error {
  constructor(public status: number, message: string) {
    super(message)
    this.name = 'CropBenchApiError'
  }
}

export interface CropBenchBucket {
  bucket: string
  n: number
  undercrop_pct: number
  wrong_pct: number
  ok_pct: number
  mean_fill_ratio: number
  bimetal_inner_ring_pct: number
  r_ratio_median: number | null
  // Oracle DINOv2 (Chunk 3) — la vraie qualité (voit le mauvais objet).
  dino_bad_pct: number | null
  dino_wrong_pct: number | null
  dino_suspect_pct: number | null
  dino_good_pct: number | null
  dino_sim_median: number | null
}

export interface CropBenchStats {
  total: number
  judged: number
  judged_pct: number
  n_undercrop: number
  undercrop_pct_judged: number
  n_wrong: number
  n_bimetal_inner_ring: number
  buckets: CropBenchBucket[]
  listing_buckets: CropBenchBucket[]   // strates single/multi × tight/small (Chunk 2)
  oracle_blind_pct: number             // % crops sans r_ratio (oracle Otsu muet → ok par défaut)
  dino_coverage_pct: number            // % crops avec un dino_sim
  dino_bad_pct: number                 // % bad (wrong+suspect) parmi les couverts — LE vrai chiffre
  generated_at: string
}

export type CropSeverity = 'red' | 'amber' | 'green' | 'gray'

export interface CropBenchCard {
  asset_id: string
  source_image_id: string | null
  eurio_id: string
  country: string
  year: string
  detection_method: string
  bucket: string
  listing_type: string            // single/multi × tight/small | unknown (Chunk 2)
  n_coins_in_img: number
  coin_frac: number | null
  dino_sim: number | null         // DINOv2 top1_sim crop↔ancre (Chunk 3)
  dino_class: string              // good | suspect | wrong | unknown
  crop_class: string
  fill_ratio: number | null
  r_pipe: number | null
  r_probe: number | null
  r_ratio: number | null
  axis_ratio: number | null       // b/a de l'ellipse fitEllipse (1.0 = cercle parfait)
  tilt_deg: number | null         // angle de l'axe principal en degrés [0, 90]
  tilt_trustworthy: boolean       // false si axis_ratio trop proche de 1 (indistinguable)
  severity: CropSeverity
  bimetal_inner_ring: boolean
  is_light_bg: boolean
  is_bimetal_coin: boolean
  has_bbox: boolean
  raw_url: string | null
  crop_url: string
  overlay_url: string
}

export interface CropBenchSampleResponse {
  cards: CropBenchCard[]
  total_matched: number
  n_returned: number
  seed: number
}

export interface CropBenchSampleParams {
  n?: number
  bucket?: string | null
  listing_type?: string | null
  klass?: string | null
  dino_class?: string | null
  bias?: string | null
  strata?: boolean
  seed?: number
  eurio_ids?: string[] | null
}

export interface CropBenchRecrop {
  asset_id: string
  algo: string
  ok: boolean
  method: string | null
  reason: string | null
  cx: number | null
  cy: number | null
  r: number | null
  r_ratio_oracle: number | null
  r_probe: number | null
  severity: CropSeverity
  crop_b64: string | null
  debug: Record<string, unknown>
}

const BACKEND_DOWN = 'Backend ML injoignable — lance `go-task ml:api`.'

async function getJson<T>(url: string): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(url)
  } catch {
    throw new CropBenchApiError(0, BACKEND_DOWN)
  }
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      if (body?.detail) detail = body.detail
    } catch {
      /* ignore */
    }
    throw new CropBenchApiError(resp.status, detail)
  }
  return resp.json() as Promise<T>
}

export async function fetchCropBenchStats(): Promise<CropBenchStats> {
  return getJson<CropBenchStats>(`${ML_API}/crop-bench/stats`)
}

export async function fetchCropBenchSample(
  params: CropBenchSampleParams = {},
): Promise<CropBenchSampleResponse> {
  const qs = new URLSearchParams()
  if (params.n != null) qs.set('n', String(params.n))
  if (params.bucket) qs.set('bucket', params.bucket)
  if (params.listing_type) qs.set('listing_type', params.listing_type)
  if (params.klass) qs.set('klass', params.klass)
  if (params.dino_class) qs.set('dino_class', params.dino_class)
  if (params.bias) qs.set('bias', params.bias)
  if (params.strata) qs.set('strata', 'true')
  if (params.seed != null) qs.set('seed', String(params.seed))
  if (params.eurio_ids && params.eurio_ids.length > 0) qs.set('eurio_ids', params.eurio_ids.join(','))
  const q = qs.toString()
  return getJson<CropBenchSampleResponse>(
    `${ML_API}/crop-bench/sample${q ? `?${q}` : ''}`,
  )
}

export interface CropBenchLabels {
  labels: Record<string, Record<string, string>>  // asset_id → {target: verdict}
  n_labels: number
  per_target: Record<string, { good: number; bad: number }>
  head_to_head: Record<string, { wins: number; losses: number; both_good: number; both_bad: number; n: number }>
}

export async function fetchCropBenchLabels(): Promise<CropBenchLabels> {
  return getJson<CropBenchLabels>(`${ML_API}/crop-bench/labels`)
}

export async function postCropBenchLabel(body: {
  asset_id: string
  target: string
  verdict: 'good' | 'bad'
  algo?: string
  method?: string | null
  r_ratio?: number | null
  dino_sim?: number | null   // capté pour caler les seuils DINOv2 sur vérité humaine
}): Promise<CropBenchLabels> {
  let resp: Response
  try {
    resp = await fetch(`${ML_API}/crop-bench/label`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch {
    throw new CropBenchApiError(0, BACKEND_DOWN)
  }
  if (!resp.ok) throw new CropBenchApiError(resp.status, `HTTP ${resp.status}`)
  return resp.json() as Promise<CropBenchLabels>
}

export async function fetchCropBenchRecrop(
  assetId: string,
  algo = 'fitellipse',
): Promise<CropBenchRecrop> {
  return getJson<CropBenchRecrop>(
    `${ML_API}/crop-bench/recrop/${encodeURIComponent(assetId)}?algo=${encodeURIComponent(algo)}`,
  )
}

// Resolve a relative ML URL (/sources/.../file, /crop-bench/overlay/...) to
// an absolute URL usable in <img src>. `algos` (comma list) overlays the
// detector circles on the raw (ex: 'fitellipse' → cercle bleu).
// `showTilt` ajoute l'ellipse jaune fitEllipse sur le raw (show_tilt=1).
export function resolveCropBenchImg(
  rel: string | null,
  algos?: string,
  showTilt = false,
): string | null {
  if (!rel) return null
  const base = rel.startsWith('http') ? rel : `${ML_API}${rel}`
  const qs = new URLSearchParams()
  if (algos) qs.set('algos', algos)
  if (showTilt) qs.set('show_tilt', '1')
  const q = qs.toString()
  return q ? `${base}?${q}` : base
}
