// TanStack Query client with IndexedDB persistence (SWR cache for the admin).
//
// Why: Supabase data is quasi-static for our use case (admin tool, single
// user, manual edits). Re-fetching on every page nav burns Supabase quota
// and adds visible latency. With this cache:
//   • cache survives reloads (IndexedDB)
//   • staleTime 5 min → no network hit during normal navigation
//   • gcTime 24 h    → cache resserves across days unless evicted
//   • refetchOnWindowFocus: true → coming back to the tab triggers a check
//
// Mutations should call queryClient.invalidateQueries({ queryKey: [...] })
// in their onSuccess to refresh the affected views.

import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister'
import { persistQueryClient } from '@tanstack/query-persist-client-core'
import { QueryClient } from '@tanstack/vue-query'
import { clear, del, get, set } from 'idb-keyval'

const FIVE_MIN = 5 * 60 * 1000
const TWENTY_FOUR_HOURS = 24 * 60 * 60 * 1000

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: FIVE_MIN,
      gcTime: TWENTY_FOUR_HOURS,
      retry: 1,
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
    },
  },
})

// IndexedDB-backed AsyncStorage adapter for the persister.
// Key namespace prevents collisions if other features use idb-keyval.
const storage = {
  getItem: (key: string) => get<string>(`eurio.query.${key}`).then(v => v ?? null),
  setItem: (key: string, value: string) => set(`eurio.query.${key}`, value),
  removeItem: (key: string) => del(`eurio.query.${key}`),
}

// Default JSON.stringify drops Set/Map structure (Set → {}, Map → {}), so
// queries returning those types lose `.has()` / `.get()` after a reload.
// Tag them on the way out and rehydrate on the way in.
type Tagged = { __t: 'Set' | 'Map'; v: unknown[] }
const isTagged = (v: unknown): v is Tagged =>
  !!v && typeof v === 'object' && '__t' in v && '__t' in (v as Record<string, unknown>)

const replacer = (_key: string, value: unknown) => {
  if (value instanceof Set) return { __t: 'Set', v: [...value] } satisfies Tagged
  if (value instanceof Map) return { __t: 'Map', v: [...value] } satisfies Tagged
  return value
}

const reviver = (_key: string, value: unknown) => {
  if (isTagged(value)) {
    if (value.__t === 'Set') return new Set(value.v)
    if (value.__t === 'Map') return new Map(value.v as [unknown, unknown][])
  }
  return value
}

const persister = createAsyncStoragePersister({
  storage,
  key: 'cache',
  throttleTime: 1000,
  serialize: data => JSON.stringify(data, replacer),
  deserialize: data => JSON.parse(data, reviver),
})

persistQueryClient({
  queryClient,
  persister,
  // 7 days. After that the persisted snapshot is considered too old and
  // dropped on cold start; in-memory fetches still populate normally.
  maxAge: 7 * TWENTY_FOUR_HOURS,
  // Bumped to v2 to drop pre-fix snapshots where Set/Map were stored as `{}`.
  buster: 'v2',
})

// Manual escape hatch — call from devtools as `window.__clearAdminCache()`.
declare global {
  interface Window {
    __clearAdminCache?: () => Promise<void>
  }
}
if (typeof window !== 'undefined') {
  window.__clearAdminCache = async () => {
    queryClient.clear()
    await clear()
    console.info('[admin] query cache cleared')
  }
}
