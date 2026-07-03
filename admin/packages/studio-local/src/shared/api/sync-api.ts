// Client du badge de sync (local-sync) — parle à l'API ML LOCALE (:8042),
// jamais à eurio-api : le statut/trigger concernent le worker de CETTE machine.

import { ML_API } from '@/shared/api/ml-api'

export interface SyncStatus {
  state: 'ok' | 'pending' | 'syncing' | 'error' | 'disabled'
  machine_id?: string
  pending_events?: number
  last_sync_at?: string | null
  last_sync_ok?: boolean
  last_error?: string | null
  last_push_count?: number
  last_pull_count?: number
  debounce_seconds?: number
  debounce_deadline?: number | null
  next_retry_at?: number | null
  consecutive_failures?: number
  api_url?: string | null
  reason?: string
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${ML_API}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  if (!res.ok) {
    throw new Error(`${init?.method ?? 'GET'} ${path} → ${res.status}`)
  }
  return res.json() as Promise<T>
}

export function fetchSyncStatus(): Promise<SyncStatus> {
  return json<SyncStatus>('/sync/status')
}

export function triggerSync(): Promise<{ status: string }> {
  return json<{ status: string }>('/sync/trigger', { method: 'POST' })
}
