/**
 * Capacités runtime du front — surtout : l'API ML lourde locale est-elle joignable ?
 * (Model B / R1)
 *
 * `hasLocalMlApi` gate les features lourdes (crop/scrape/training/lab/bench…) :
 *  - **hébergé** : toujours `false`, et on ne ping PAS (`http://127.0.0.1:8042` depuis
 *    HTTPS = mixed-content / Private Network Access → la requête échouerait de toute façon).
 *  - **local** : baseline `true`, puis raffinée par un ping `${ML_API}/health` au boot —
 *    si l'API ML n'est pas lancée (`go-task ml:api`), on bascule `false` et les vues lourdes
 *    affichent la notice « lance l'API ML ».
 *
 * Le gating lui-même vit dans `AppLayout` (nav grisée + `LocalOnlyNotice` sur les routes
 * `meta.heavy`) — ce store n'expose que l'état.
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { ML_API } from '@/shared/api/ml-api'
import { HAS_LOCAL_ML_API, IS_HOSTED } from '@/shared/config/deploy-target'

type MlStatus = 'unknown' | 'checking' | 'up' | 'down' | 'disabled'

export const useCapabilities = defineStore('capabilities', () => {
  // hébergé → désactivé d'emblée ; local → baseline true en attendant le ping.
  const mlStatus = ref<MlStatus>(IS_HOSTED ? 'disabled' : 'unknown')

  const hasLocalMlApi = computed(() => mlStatus.value === 'up')

  /** Ping best-effort de l'API ML locale. No-op en hébergé (pas de ping mixed-content). */
  async function probe(): Promise<void> {
    if (IS_HOSTED || !HAS_LOCAL_ML_API) {
      mlStatus.value = 'disabled'
      return
    }
    mlStatus.value = 'checking'
    try {
      const ctrl = new AbortController()
      const t = setTimeout(() => ctrl.abort(), 2000)
      const res = await fetch(`${ML_API}/health`, { signal: ctrl.signal })
      clearTimeout(t)
      mlStatus.value = res.ok ? 'up' : 'down'
    } catch {
      mlStatus.value = 'down'
    }
  }

  return { mlStatus, hasLocalMlApi, probe }
})
