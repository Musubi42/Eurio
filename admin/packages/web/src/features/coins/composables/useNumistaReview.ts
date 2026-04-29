import { computed, ref } from 'vue'

const ML_API = 'http://127.0.0.1:8042'

export interface ReviewCandidate {
  eurio_id: string
  score: number
}

export interface ReviewResolution {
  eurio_id: string | null
  resolved_at: string
}

export interface ReviewItem {
  numista_id: number
  numista_name: string
  country: string
  year: number
  numista_theme: string
  candidates: ReviewCandidate[]
  resolution?: ReviewResolution | null
}

export interface ReviewStats {
  total: number
  resolved: number
  pending: number
  skipped: number
}

export function useNumistaReview() {
  const queue = ref<ReviewItem[]>([])
  const stats = ref<ReviewStats>({ total: 0, resolved: 0, pending: 0, skipped: 0 })
  const loading = ref(false)
  const error = ref<string | null>(null)
  const saving = ref(false)

  async function fetchQueue() {
    loading.value = true
    error.value = null
    try {
      const [qRes, sRes] = await Promise.all([
        fetch(`${ML_API}/numista-review/queue`),
        fetch(`${ML_API}/numista-review/stats`),
      ])
      if (!qRes.ok || !sRes.ok) throw new Error('ML API non disponible')
      queue.value = await qRes.json()
      stats.value = await sRes.json()
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Erreur inconnue'
    } finally {
      loading.value = false
    }
  }

  async function resolve(numista_id: number, eurio_id: string | null) {
    saving.value = true
    try {
      const res = await fetch(`${ML_API}/numista-review/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ numista_id, eurio_id }),
      })
      if (!res.ok) throw new Error('Erreur lors de la résolution')
      const resolution: ReviewResolution = await res.json()
      const item = queue.value.find(i => i.numista_id === numista_id)
      if (item) item.resolution = resolution
      const sRes = await fetch(`${ML_API}/numista-review/stats`)
      if (sRes.ok) stats.value = await sRes.json()
    } finally {
      saving.value = false
    }
  }

  const pending = computed(() => queue.value.filter(i => !i.resolution))
  const resolved = computed(() => queue.value.filter(i => i.resolution?.eurio_id != null))
  const skipped = computed(() => queue.value.filter(i => i.resolution != null && i.resolution.eurio_id == null))

  return { queue, stats, loading, error, saving, fetchQueue, resolve, pending, resolved, skipped }
}
