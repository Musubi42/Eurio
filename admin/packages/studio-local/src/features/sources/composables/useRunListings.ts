// Composable pour /source-runs/:run_id/listings.
//
// Backend : ml/serving/sources/router.py → get_run_listings.
//
// Le fetch des MÉTADONNÉES passe par eurio-api (Bearer PAT). Les helpers
// `rawFileUrl` / `assetFileUrl` restent sur ML_API (localhost:8042) — les
// fichiers image vivent sur le poste dev où la pipeline ML a tourné, ils
// ne sont pas synchronisés sur le VPS.

import { eurioApi, EurioApiError } from '@/shared/api/eurio-api'
import { ML_API } from '@/features/training/composables/useTrainingApi'
import type { SourceId } from './useSourcesApi'

export type DownloadStatus = 'success' | 'failed' | 'skipped' | null
export type CropStatus = 'success' | 'zero_crops' | 'error' | 'skipped' | null
export type RouteDecision =
  | 'auto_resolved'
  | 'review_single'
  | 'review_lot'
  | 'rejected'
  | 'pending'
  | null

export interface ListingCropAsset {
  asset_id: string
  crop_index: number
  resolution_status: string | null
  eurio_id: string | null
  review_id: string | null
  review_kind: 'lot' | 'single' | null
}

export interface ListingDetail {
  source_image_id: string
  source_ref: string
  source_url: string | null
  target_eurio_id: string | null
  listing_title: string | null
  listing_country: string | null
  listing_year: number | null
  listing_price: number | null
  listing_currency: string | null
  seller_id: string | null
  is_lot_suspected: boolean
  fetched_at: string | null

  download_endpoint: string | null
  download_status: DownloadStatus
  download_http_status: number | null
  download_error: string | null

  crop_status: CropStatus
  crop_error: string | null
  n_crops_detected: number | null

  route_decision: RouteDecision
  route_reason: string | null

  crops: ListingCropAsset[]
}

export interface RunListings {
  run_id: string
  source_id: SourceId
  listings: ListingDetail[]
}

export class RunListingsError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'RunListingsError'
  }
}

export async function fetchRunListings(
  _sourceId: SourceId,
  runId: string,
  eurio_id?: string | null,
): Promise<RunListings> {
  const qs = eurio_id ? `?eurio_id=${encodeURIComponent(eurio_id)}` : ''
  try {
    return await eurioApi.get<RunListings>(`/source-runs/${runId}/listings${qs}`)
  } catch (err) {
    if (err instanceof EurioApiError) {
      throw new RunListingsError(err.status, err.message)
    }
    throw err
  }
}

export function rawFileUrl(sourceId: SourceId, sourceImageId: string): string {
  return `${ML_API}/sources/${sourceId}/raws/${sourceImageId}/file`
}

export function assetFileUrl(sourceId: SourceId, assetId: string): string {
  return `${ML_API}/sources/${sourceId}/assets/${assetId}/file`
}
