import { supabase } from '@/shared/supabase/client'
import type { Coin } from '@/shared/supabase/types'
import { computed, ref, watch } from 'vue'

// ───────── Types ─────────

export interface QueueEntry {
  numista_id: number
  numista_name: string
  country: string
  year: number
  numista_theme: string
  candidates: { eurio_id: string; score: number }[]
}

export type DecisionStatus = 'pending' | 'assigned' | 'none' | 'skipped'

export interface ArbitrageDecision {
  numista_id: number
  chosen_eurio_id: string | null
  status: DecisionStatus
  synced: boolean
}

// ───────── localStorage ─────────

const STORAGE_KEY = 'eurio-arbitrage-decisions'

function loadDecisions(): Map<number, ArbitrageDecision> {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (!raw) return new Map()
  const arr: ArbitrageDecision[] = JSON.parse(raw)
  return new Map(arr.map(d => [d.numista_id, d]))
}

function saveDecisions(map: Map<number, ArbitrageDecision>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([...map.values()]))
}

// ───────── Composable ─────────

export function useArbitrage() {
  const queue = ref<QueueEntry[]>([])
  const decisions = ref<Map<number, ArbitrageDecision>>(loadDecisions())
  const coinCache = ref<Map<string, Coin>>(new Map())
  const loading = ref(true)
  const syncing = ref(false)
  const syncError = ref<string | null>(null)
  const currentIndex = ref(0)

  // Persist on every change
  watch(decisions, (v) => saveDecisions(v), { deep: true })

  // ── Load queue JSON + fetch candidate coins from Supabase ──

  async function loadData() {
    loading.value = true

    // Fetch review queue (served by Vite dev middleware from ml/datasets/)
    const resp = await fetch('/arbitrage-queue.json')
    if (!resp.ok) {
      console.error('Failed to load arbitrage queue:', resp.statusText)
      loading.value = false
      return
    }
    queue.value = await resp.json() as QueueEntry[]

    // Fetch all candidate coins from Supabase
    const allIds = queue.value.flatMap(e => e.candidates.map(c => c.eurio_id))
    const unique = [...new Set(allIds)]

    // Supabase `in()` has a limit of ~300 items, we're at ~112, fine
    const { data, error } = await supabase
      .from('coins')
      .select('*')
      .in('eurio_id', unique)

    if (error) {
      console.error('Failed to fetch candidate coins:', error.message)
      loading.value = false
      return
    }

    const map = new Map<string, Coin>()
    for (const row of (data ?? []) as Coin[]) {
      map.set(row.eurio_id, row)
    }
    coinCache.value = map
    loading.value = false
  }

  // ── Decision helpers ──

  function getDecision(numista_id: number): ArbitrageDecision {
    return decisions.value.get(numista_id) ?? {
      numista_id,
      chosen_eurio_id: null,
      status: 'pending',
      synced: false,
    }
  }

  function assign(numista_id: number, eurio_id: string) {
    const current = getDecision(numista_id)
    // Toggle off if same candidate clicked again
    if (current.status === 'assigned' && current.chosen_eurio_id === eurio_id) {
      decisions.value.set(numista_id, {
        ...current,
        chosen_eurio_id: null,
        status: 'pending',
        synced: false,
      })
    } else {
      decisions.value.set(numista_id, {
        ...current,
        chosen_eurio_id: eurio_id,
        status: 'assigned',
        synced: false,
      })
    }
    // Trigger reactivity
    decisions.value = new Map(decisions.value)
  }

  function markNone(numista_id: number) {
    const current = getDecision(numista_id)
    // Toggle off
    if (current.status === 'none') {
      decisions.value.set(numista_id, {
        ...current,
        chosen_eurio_id: null,
        status: 'pending',
        synced: false,
      })
    } else {
      decisions.value.set(numista_id, {
        ...current,
        chosen_eurio_id: null,
        status: 'none',
        synced: false,
      })
    }
    decisions.value = new Map(decisions.value)
  }

  function skip(numista_id: number) {
    const current = getDecision(numista_id)
    if (current.status === 'skipped') {
      decisions.value.set(numista_id, {
        ...current,
        status: 'pending',
        synced: false,
      })
    } else {
      decisions.value.set(numista_id, {
        ...current,
        chosen_eurio_id: null,
        status: 'skipped',
        synced: false,
      })
    }
    decisions.value = new Map(decisions.value)
  }

  // ── Sync to Supabase ──

  async function syncToSupabase() {
    syncing.value = true
    syncError.value = null
    let synced = 0

    for (const [numista_id, decision] of decisions.value) {
      if (decision.status !== 'assigned' || decision.synced || !decision.chosen_eurio_id) continue

      // Fetch current cross_refs to merge (don't overwrite other fields)
      const { data: current, error: fetchErr } = await supabase
        .from('coins')
        .select('cross_refs')
        .eq('eurio_id', decision.chosen_eurio_id)
        .single()

      if (fetchErr || !current) {
        syncError.value = `Fetch failed for ${decision.chosen_eurio_id}: ${fetchErr?.message ?? 'not found'}`
        break
      }

      const crossRefs = ((current as Record<string, unknown>).cross_refs ?? {}) as Record<string, unknown>
      crossRefs.numista_id = numista_id

      const { error: updateErr } = await supabase
        .from('coins')
        .update({ cross_refs: crossRefs } as never)
        .eq('eurio_id', decision.chosen_eurio_id)

      if (updateErr) {
        syncError.value = `Update failed for ${decision.chosen_eurio_id}: ${updateErr.message}`
        break
      }

      decision.synced = true
      decisions.value = new Map(decisions.value)
      synced++
    }

    syncing.value = false
    return synced
  }

  // ── Computed stats ──

  const total = computed(() => queue.value.length)

  const resolved = computed(() => {
    let n = 0
    for (const entry of queue.value) {
      const d = decisions.value.get(entry.numista_id)
      if (d && (d.status === 'assigned' || d.status === 'none' || d.status === 'skipped')) n++
    }
    return n
  })

  const pendingSync = computed(() => {
    let n = 0
    for (const d of decisions.value.values()) {
      if (d.status === 'assigned' && !d.synced) n++
    }
    return n
  })

  const syncedCount = computed(() => {
    let n = 0
    for (const d of decisions.value.values()) {
      if (d.synced) n++
    }
    return n
  })

  const currentEntry = computed(() => queue.value[currentIndex.value] ?? null)

  function getCoin(eurio_id: string): Coin | undefined {
    return coinCache.value.get(eurio_id)
  }

  return {
    queue,
    decisions,
    loading,
    syncing,
    syncError,
    currentIndex,
    currentEntry,
    total,
    resolved,
    pendingSync,
    syncedCount,
    loadData,
    getDecision,
    assign,
    markNone,
    skip,
    syncToSupabase,
    getCoin,
  }
}
