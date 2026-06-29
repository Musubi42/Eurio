// Sets API — thin fetch wrappers vers ml/serving/sets_routes.py.
//
// P.8b du chantier coin-richness : remplace les reads/writes Supabase de
// SetEditDrawer.vue par des calls FastAPI. Doctrine SQLite-only.
//
// TC1 : migré de ML_API/fetch vers eurioApi (Bearer PAT, eurio-api.musubi.dev).
// Tous les endpoints sets sont montés sur le VPS via _CANDIDATES dans
// server_serve.py (sans cv2). Les chemins /sets/* sont identiques.

import { eurioApi } from '@/shared/api/eurio-api'

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

// ─── Helpers ─────────────────────────────────────────────────────────────────
//
// Même pattern que useCoinsApi.ts : délègue à eurioApi pour le Bearer PAT.

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method || 'GET').toUpperCase()
  if (method === 'GET') return eurioApi.get<T>(path)
  let body: unknown
  if (typeof init?.body === 'string') {
    try { body = JSON.parse(init.body) } catch { body = init.body }
  } else {
    body = init?.body
  }
  switch (method) {
    case 'POST': return eurioApi.post<T>(path, body)
    case 'PUT': return eurioApi.put<T>(path, body)
    case 'PATCH': return eurioApi.patch<T>(path, body)
    case 'DELETE': return eurioApi.delete<T>(path)
    default: throw new Error(`useSetsApi.json: méthode non supportée ${method}`)
  }
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
