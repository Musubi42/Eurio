<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  RefreshCw,
  Wifi,
  WifiOff,
} from 'lucide-vue-next'
import {
  checkMlApi,
  usePoller,
} from '@/features/training/composables/useTrainingApi'
import {
  fetchSourcesStatus,
  getPipelineMeta,
  type SourcesStatusResponse,
  type SourceStatus,
} from '../composables/useSourcesApi'
import SourceCard from '../components/SourceCard.vue'
import QuotaProgressBar from '../components/QuotaProgressBar.vue'

// ─── State ─────────────────────────────────────────────────────────────

const apiStatus = ref<'checking' | 'online' | 'offline'>('checking')
const data = ref<SourcesStatusResponse | null>(null)
const loadError = ref<string | null>(null)

async function refreshApiStatus(opts: { showProbe?: boolean } = {}) {
  if (opts.showProbe) apiStatus.value = 'checking'
  const online = await checkMlApi()
  apiStatus.value = online ? 'online' : 'offline'
}

async function refreshSources() {
  try {
    data.value = await fetchSourcesStatus()
    loadError.value = null
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : 'Erreur de chargement'
  }
}

// ─── Derived: split sources by pipeline role ───────────────────────────
// Référentiel canonique = ce qui détermine *quoi* existe (Numista, futurs).
// Enrichissement        = ce qui *associe* aux eurio_id existants images,
//                         prix, métadonnées (eBay, MdP, BCE, Wikipedia, …).

const referentialSources = computed<SourceStatus[]>(() =>
  data.value?.sources.filter((s) => getPipelineMeta(s.id)?.role === 'referential') ?? [],
)
const enrichmentSources = computed<SourceStatus[]>(() =>
  data.value?.sources.filter((s) => getPipelineMeta(s.id)?.role === 'enrichment') ?? [],
)

const numistaQuota = computed(() => data.value?.quota_groups.numista ?? null)

// ─── Lifecycle ─────────────────────────────────────────────────────────

const sourcesPoller = usePoller(
  () => fetchSourcesStatus(),
  10_000,
  (resp) => {
    data.value = resp
  },
)

let healthPoller: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await refreshApiStatus({ showProbe: true })
  await refreshSources()
  // Start polling regardless of API state — mock data is always available.
  // When the real endpoint lands, gate the poller on apiStatus === 'online'.
  sourcesPoller.start()

  healthPoller = setInterval(async () => {
    await refreshApiStatus()
  }, 10_000)
})

onUnmounted(() => {
  if (healthPoller) clearInterval(healthPoller)
  sourcesPoller.stop()
})
</script>

<template>
  <div class="p-8">
    <!-- ═══ Header ═══ -->
    <header class="mb-6 flex items-start justify-between">
      <div>
        <h1
          class="font-display text-2xl italic font-semibold"
          style="color: var(--indigo-700);"
        >
          Sources
        </h1>
        <p class="mt-0.5 text-sm" style="color: var(--ink-500);">
          Panneau de contrôle de la chaîne d'ingestion
          <span
            class="ml-2 rounded-sm px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider"
            style="background: var(--surface-1); color: var(--ink-500); border: 1px solid var(--surface-3);"
          >
            V1 · lecture seule
          </span>
        </p>
      </div>

      <div class="flex items-center gap-3">
        <div
          class="flex items-center gap-2 rounded-full border px-3 py-1 text-xs"
          :style="{
            borderColor: apiStatus === 'online' ? 'var(--success)' : 'var(--danger)',
            color: apiStatus === 'online' ? 'var(--success)' : 'var(--danger)',
            background: apiStatus === 'online'
              ? 'color-mix(in srgb, var(--success) 6%, var(--surface))'
              : 'color-mix(in srgb, var(--danger) 6%, var(--surface))',
          }"
        >
          <Wifi v-if="apiStatus === 'online'" class="h-3 w-3" />
          <WifiOff v-else class="h-3 w-3" />
          {{ apiStatus === 'online' ? 'ML API connectée' : 'ML API hors-ligne' }}
        </div>
      </div>
    </header>

    <!-- ═══ Offline banner ═══ -->
    <div
      v-if="apiStatus === 'offline'"
      class="mb-6 rounded-lg border-2 border-dashed px-5 py-6 text-center"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface));"
    >
      <WifiOff class="mx-auto mb-2 h-6 w-6" style="color: var(--danger);" />
      <p class="text-sm font-medium" style="color: var(--danger);">
        ML API non jointe (http://127.0.0.1:8042)
      </p>
      <p class="mt-1 text-xs" style="color: var(--ink-500);">
        Lance
        <code style="background: var(--surface-1); padding: 1px 4px; border-radius: 3px;">go-task ml:api</code>
        puis clique sur réessayer.
      </p>
      <button
        class="mt-3 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium"
        style="background: var(--ink); color: var(--surface);"
        @click="refreshApiStatus({ showProbe: true })"
      >
        <RefreshCw class="h-3 w-3" /> Réessayer
      </button>
    </div>

    <!-- ═══ Load error ═══ -->
    <div
      v-if="loadError"
      class="mb-6 rounded-lg border px-5 py-3 text-sm"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);"
    >
      Erreur lors du chargement : {{ loadError }}
    </div>

    <template v-if="data">
      <!-- ════════════════════════════════════════════════════════════ -->
      <!-- ═══  Section 1 — RÉFÉRENTIEL CANONIQUE                     ═══ -->
      <!-- ════════════════════════════════════════════════════════════ -->
      <section class="mb-8">
        <h2
          class="mb-3 flex items-baseline gap-2 font-mono text-xs uppercase tracking-wider"
          style="color: var(--ink-500);"
        >
          <span style="color: var(--indigo-700);">Référentiel canonique</span>
          <span class="opacity-60">· source de vérité des pièces qui existent</span>
        </h2>

        <!-- Bandeau quota partagé Numista (les 3 cards référentielles partagent le quota) -->
        <div
          v-if="numistaQuota"
          class="mb-4 rounded-lg border px-5 py-4"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <QuotaProgressBar :quota="numistaQuota" />
        </div>

        <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <SourceCard
            v-for="src in referentialSources"
            :key="src.id"
            :source="src"
          />
        </div>
      </section>

      <!-- ════════════════════════════════════════════════════════════ -->
      <!-- ═══  Section 2 — ENRICHISSEMENT                            ═══ -->
      <!-- ════════════════════════════════════════════════════════════ -->
      <section class="mb-6">
        <h2
          class="mb-3 flex items-baseline gap-2 font-mono text-xs uppercase tracking-wider"
          style="color: var(--ink-500);"
        >
          <span style="color: var(--indigo-700);">Enrichissement</span>
          <span class="opacity-60">· images, prix et métadonnées par eurio_id</span>
        </h2>
        <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <SourceCard
            v-for="src in enrichmentSources"
            :key="src.id"
            :source="src"
          />
        </div>
      </section>
    </template>
  </div>
</template>
