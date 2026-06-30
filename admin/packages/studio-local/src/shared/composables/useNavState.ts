import { onMounted, onUnmounted, ref } from 'vue'
import { ML_API } from '@/shared/api/ml-api'
import { HAS_LOCAL_ML_API } from '@/shared/config/deploy-target'

// Shared reactive badge counts keyed by nav item id
const badges = ref<Record<string, number>>({})

let refCount = 0
let pollInterval: ReturnType<typeof setInterval> | null = null

async function fetchBadges() {
  if (!HAS_LOCAL_ML_API) return
  try {
    const res = await fetch(`${ML_API}/numista-review/stats`)
    if (!res.ok) return
    const stats = await res.json()
    if (stats.pending > 0) {
      badges.value = { ...badges.value, 'numista-review': stats.pending }
    } else {
      const next = { ...badges.value }
      delete next['numista-review']
      badges.value = next
    }
  } catch {
    const next = { ...badges.value }
    delete next['numista-review']
    badges.value = next
  }
}

export function useNavState() {
  onMounted(() => {
    refCount++
    if (refCount === 1) {
      fetchBadges()
      pollInterval = setInterval(fetchBadges, 30_000)
    }
  })
  onUnmounted(() => {
    refCount--
    if (refCount === 0 && pollInterval !== null) {
      clearInterval(pollInterval)
      pollInterval = null
    }
  })
  return { badges }
}
