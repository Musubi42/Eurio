// Sets API — thin fetch wrappers vers ml/api/sets_routes.py.
//
// P.8b du chantier coin-richness : remplace les reads/writes Supabase de
// SetEditDrawer.vue par des calls FastAPI. Doctrine SQLite-only.

import { ML_API } from '@/features/training/composables/useTrainingApi'

export interface SetRow {
  id: string
  name_i18n: Record<string, string>
  description_i18n: Record<string, string> | null
  category: string
  kind: string
  param_key: string | null
  criteria: Record<string, unknown> | null
  display_order: number
  expected_count: number | null
  icon: string | null
  reward: Record<string, unknown> | null
  active: boolean
}

export interface SetMember {
  eurio_id: string
  position: number | null
  // joined coins data (read-only)
  country: string | null
  year: number | null
  face_value: number | null
  theme: string | null
  is_commemorative: boolean | null
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${ML_API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!resp.ok) {
    const body = await resp.text().catch(() => '')
    throw new Error(`${resp.status} ${resp.statusText}: ${body}`)
  }
  if (resp.status === 204) return undefined as unknown as T
  return resp.json() as Promise<T>
}

export function fetchSets(activeOnly = false): Promise<SetRow[]> {
  return json<SetRow[]>(`/sets${activeOnly ? '?active_only=true' : ''}`)
}

export function fetchSet(id: string): Promise<SetRow> {
  return json<SetRow>(`/sets/${encodeURIComponent(id)}`)
}

export function fetchSetMembers(id: string): Promise<SetMember[]> {
  return json<SetMember[]>(`/sets/${encodeURIComponent(id)}/members`)
}

export function createSet(payload: SetRow): Promise<SetRow> {
  return json<SetRow>('/sets', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateSet(id: string, payload: SetRow): Promise<SetRow> {
  return json<SetRow>(`/sets/${encodeURIComponent(id)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function deleteSet(id: string): Promise<void> {
  return json<void>(`/sets/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function replaceSetMembers(
  id: string,
  members: { eurio_id: string; position: number | null }[],
): Promise<SetMember[]> {
  return json<SetMember[]>(`/sets/${encodeURIComponent(id)}/members`, {
    method: 'POST',
    body: JSON.stringify({ members }),
  })
}

export function patchSetActive(id: string, active: boolean): Promise<SetRow> {
  return json<SetRow>(`/sets/${encodeURIComponent(id)}/active`, {
    method: 'PATCH',
    body: JSON.stringify({ active }),
  })
}
