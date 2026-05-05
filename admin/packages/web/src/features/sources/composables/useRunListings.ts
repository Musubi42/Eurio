// Composable pour /sources/:id/runs/:run_id/listings.
//
// Backend : ml/api/sources_routes.py → get_run_listings.
// Doc : docs/sources-refacto/listing-debug-view-kickoff.md.

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
  sourceId: SourceId,
  runId: string,
  eurio_id?: string | null,
): Promise<RunListings> {
  const url = new URL(`${ML_API}/sources/${sourceId}/runs/${runId}/listings`)
  if (eurio_id) url.searchParams.set('eurio_id', eurio_id)
  const resp = await fetch(url.toString())
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      if (body && typeof body === 'object' && 'detail' in body) {
        detail = String((body as { detail: unknown }).detail)
      }
    } catch {
      // ignore
    }
    throw new RunListingsError(resp.status, detail)
  }
  return resp.json() as Promise<RunListings>
}

export function rawFileUrl(sourceId: SourceId, sourceImageId: string): string {
  return `${ML_API}/sources/${sourceId}/raws/${sourceImageId}/file`
}

export function assetFileUrl(sourceId: SourceId, assetId: string): string {
  return `${ML_API}/sources/${sourceId}/assets/${assetId}/file`
}
