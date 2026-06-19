<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { AlertCircle, ArrowLeft, ExternalLink, RefreshCw, Wifi, WifiOff } from 'lucide-vue-next'
import { checkMlApi, ML_API } from '@/features/training/composables/useTrainingApi'
import {
  fetchDivergences,
  type DivergenceEntry,
  type DivergencesResponse,
} from '../composables/useReferentialApi'

// ─── State ─────────────────────────────────────────────────────────────

const apiStatus = ref<'checking' | 'online' | 'offline'>('checking')
const data = ref<DivergencesResponse | null>(null)
const loading = ref(false)
const loadError = ref<string | null>(null)
const filter = ref<'all' | 'hard' | 'soft'>('all')
const selected = ref<DivergenceEntry | null>(null)
const softThreshold = ref<number>(0.65)

// ─── Loaders ───────────────────────────────────────────────────────────

async function refreshHealth() {
  apiStatus.value = 'checking'
  apiStatus.value = (await checkMlApi()) ? 'online' : 'offline'
}

async function refreshData() {
  loading.value = true
  loadError.value = null
  try {
    const r = await fetchDivergences(softThreshold.value)
    data.value = r
    if (!selected.value && r.divergences.length) {
      selected.value = r.divergences[0]
    }
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : 'Erreur'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await refreshHealth()
  if (apiStatus.value === 'online') await refreshData()
})

// ─── Derived ───────────────────────────────────────────────────────────

const filtered = computed<DivergenceEntry[]>(() => {
  if (!data.value) return []
  if (filter.value === 'all') return data.value.divergences
  return data.value.divergences.filter((d) => d.severity === filter.value)
})

function imgUrl(eurioId: string, source: 'numista' | 'bce_comm', thumb = false): string {
  const path = `/referential/canonical/${eurioId}/obverse${thumb ? '/thumb' : ''}?source=${source}`
  return `${ML_API}${path}`
}

function numistaUrl(id: number | null): string | null {
  if (!id) return null
  return `https://en.numista.com/catalogue/pieces${id}.html`
}
</script>

<template>
  <div class="container mx-auto px-6 py-6" style="background: var(--surface-1); min-height: 100vh;">
    <!-- ═══ Header ═══ -->
    <header class="mb-6 flex items-baseline justify-between">
      <div>
        <router-link to="/referential"
                     class="inline-flex items-center gap-1.5 text-xs"
                     style="color: var(--ink-500);">
          <ArrowLeft class="h-3 w-3" /> Référentiel
        </router-link>
        <h1 class="mt-1 text-2xl font-bold" style="color: var(--ink);">
          Divergences BCE ↔ Numista
        </h1>
        <p class="mt-1 text-sm" style="color: var(--ink-500);">
          Lecture seule. Compare les métadonnées BCE (sidecar JSON sur disque)
          avec Numista (eurio.db) pour les coins matched.
        </p>
      </div>

      <div class="flex items-center gap-3">
        <div class="flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs"
             :style="{
               borderColor: apiStatus === 'online' ? 'var(--success)' : 'var(--danger)',
               color: apiStatus === 'online' ? 'var(--success)' : 'var(--danger)',
             }">
          <Wifi v-if="apiStatus === 'online'" class="h-3 w-3" />
          <WifiOff v-else class="h-3 w-3" />
          {{ apiStatus === 'online' ? 'API en ligne' : 'API hors-ligne' }}
        </div>
        <button v-if="apiStatus === 'online'"
                class="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium"
                style="border-color: var(--surface-3); color: var(--ink-500);"
                :disabled="loading"
                @click="refreshData">
          <RefreshCw class="h-3 w-3" :class="{ 'animate-spin': loading }" /> Refresh
        </button>
      </div>
    </header>

    <div v-if="loadError"
         class="mb-6 rounded-lg border px-5 py-3 text-sm"
         style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);">
      <AlertCircle class="mr-1 inline-block h-4 w-4 -mt-0.5" />
      {{ loadError }}
    </div>

    <template v-if="data">
      <!-- ═══ Summary + filters ═══ -->
      <section class="mb-4 flex items-center justify-between gap-4">
        <div class="grid grid-cols-4 gap-3 flex-1">
          <div class="rounded-lg border px-4 py-2"
               style="border-color: var(--surface-3); background: var(--surface);">
            <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Matched BCE</div>
            <div class="font-mono text-lg font-bold" style="color: var(--ink);">{{ data.n_matched_bce }}</div>
          </div>
          <div class="rounded-lg border px-4 py-2"
               style="border-color: var(--surface-3); background: var(--surface);">
            <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Hard (year/country)</div>
            <div class="font-mono text-lg font-bold"
                 :style="{ color: data.n_hard > 0 ? 'var(--danger)' : 'var(--success)' }">
              {{ data.n_hard }}
            </div>
          </div>
          <div class="rounded-lg border px-4 py-2"
               style="border-color: var(--surface-3); background: var(--surface);">
            <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Soft (theme)</div>
            <div class="font-mono text-lg font-bold"
                 :style="{ color: data.n_soft > 0 ? 'var(--warning, #d97706)' : 'var(--success)' }">
              {{ data.n_soft }}
            </div>
          </div>
          <div class="rounded-lg border px-4 py-2"
               style="border-color: var(--surface-3); background: var(--surface);">
            <div class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Clean</div>
            <div class="font-mono text-lg font-bold" style="color: var(--success);">{{ data.n_clean }}</div>
          </div>
        </div>

        <div class="flex items-center gap-2">
          <label class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Seuil soft</label>
          <input v-model.number="softThreshold" type="number" min="0" max="1" step="0.05"
                 class="w-16 rounded border px-2 py-1 text-xs font-mono"
                 style="border-color: var(--surface-3); background: var(--surface); color: var(--ink);"
                 @change="refreshData" />
        </div>
      </section>

      <section class="mb-3 flex gap-2">
        <button v-for="f in (['all','hard','soft'] as const)" :key="f"
                class="rounded-full px-3 py-1 text-xs font-medium"
                :style="filter === f
                  ? { background: 'var(--ink)', color: 'var(--surface)' }
                  : { background: 'var(--surface)', color: 'var(--ink-500)', border: '1px solid var(--surface-3)' }"
                @click="filter = f">
          {{ f === 'all' ? 'Toutes' : f === 'hard' ? `Hard (${data.n_hard})` : `Soft (${data.n_soft})` }}
        </button>
      </section>

      <!-- ═══ Two-pane layout ═══ -->
      <div class="grid gap-4 lg:grid-cols-[1fr_1.2fr]">
        <!-- ── Table left ── -->
        <div class="rounded-lg border overflow-hidden"
             style="border-color: var(--surface-3); background: var(--surface);">
          <table class="w-full text-sm">
            <thead class="text-[10px] uppercase font-mono"
                   style="background: var(--surface-1); color: var(--ink-500);">
              <tr>
                <th class="px-3 py-2 text-left">Sev</th>
                <th class="px-3 py-2 text-left">Pays·An</th>
                <th class="px-3 py-2 text-left">Numista / BCE</th>
                <th class="px-3 py-2 text-right">Sim</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="d in filtered" :key="d.eurio_id"
                  class="cursor-pointer border-t"
                  :style="selected?.eurio_id === d.eurio_id
                    ? { background: 'color-mix(in srgb, var(--indigo-700) 6%, var(--surface))', borderColor: 'var(--surface-2)' }
                    : { borderColor: 'var(--surface-2)' }"
                  @click="selected = d">
                <td class="px-3 py-2">
                  <span class="inline-block rounded-full px-2 py-0.5 font-mono text-[9px] uppercase"
                        :style="d.severity === 'hard'
                          ? { background: 'color-mix(in srgb, var(--danger) 12%, var(--surface))', color: 'var(--danger)' }
                          : { background: 'color-mix(in srgb, var(--warning, #d97706) 12%, var(--surface))', color: 'var(--warning, #d97706)' }">
                    {{ d.severity }}
                  </span>
                </td>
                <td class="px-3 py-2 font-mono text-xs" style="color: var(--ink);">
                  {{ d.country }}·{{ d.year }}
                </td>
                <td class="px-3 py-2 text-xs">
                  <div style="color: var(--ink);" class="line-clamp-1">{{ d.numista_theme || '—' }}</div>
                  <div style="color: var(--ink-500);" class="line-clamp-1">{{ d.bce_feature || '—' }}</div>
                </td>
                <td class="px-3 py-2 text-right font-mono text-xs">
                  <template v-for="diff in d.diffs" :key="diff.field">
                    <span v-if="diff.field === 'theme' && diff.similarity != null"
                          :style="{ color: diff.similarity < 0.3 ? 'var(--danger)' : 'var(--warning, #d97706)' }">
                      {{ diff.similarity.toFixed(2) }}
                    </span>
                  </template>
                </td>
              </tr>
              <tr v-if="!filtered.length">
                <td colspan="4" class="px-3 py-8 text-center text-xs" style="color: var(--success);">
                  ✓ Aucune divergence sur ce filtre.
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- ── Detail right ── -->
        <div v-if="selected" class="rounded-lg border p-5"
             style="border-color: var(--surface-3); background: var(--surface);">
          <div class="mb-3 flex items-baseline justify-between gap-3">
            <div>
              <div class="font-mono text-xs" style="color: var(--ink-500);">{{ selected.eurio_id }}</div>
              <div class="mt-1 text-sm font-medium" style="color: var(--ink);">
                {{ selected.country }} · {{ selected.year }}
              </div>
            </div>
            <span class="inline-block rounded-full px-2 py-0.5 font-mono text-[10px] uppercase"
                  :style="selected.severity === 'hard'
                    ? { background: 'color-mix(in srgb, var(--danger) 12%, var(--surface))', color: 'var(--danger)' }
                    : { background: 'color-mix(in srgb, var(--warning, #d97706) 12%, var(--surface))', color: 'var(--warning, #d97706)' }">
              {{ selected.severity }}
            </span>
          </div>

          <!-- Images côte à côte -->
          <div class="mb-4 grid grid-cols-2 gap-3">
            <div>
              <div class="mb-1 flex items-center justify-between">
                <span class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Numista</span>
                <a v-if="numistaUrl(selected.numista_id)"
                   :href="numistaUrl(selected.numista_id)!" target="_blank" rel="noopener"
                   class="inline-flex items-center gap-1 text-[10px]"
                   style="color: var(--indigo-700);">
                  #{{ selected.numista_id }} <ExternalLink class="h-2.5 w-2.5" />
                </a>
              </div>
              <img :src="imgUrl(selected.eurio_id, 'numista')"
                   class="aspect-square w-full rounded-md object-contain"
                   style="background: var(--surface-1);"
                   @error="(e) => ((e.target as HTMLImageElement).style.opacity = '0.2')" />
            </div>
            <div>
              <div class="mb-1 flex items-center justify-between">
                <span class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">BCE</span>
                <a v-if="selected.bce_page_url"
                   :href="selected.bce_page_url" target="_blank" rel="noopener"
                   class="inline-flex items-center gap-1 text-[10px]"
                   style="color: var(--indigo-700);">
                  page BCE <ExternalLink class="h-2.5 w-2.5" />
                </a>
              </div>
              <img :src="imgUrl(selected.eurio_id, 'bce_comm')"
                   class="aspect-square w-full rounded-md object-contain"
                   style="background: var(--surface-1);"
                   @error="(e) => ((e.target as HTMLImageElement).style.opacity = '0.2')" />
            </div>
          </div>

          <!-- Diff fields -->
          <div class="space-y-2">
            <div v-for="diff in selected.diffs" :key="diff.field"
                 class="rounded-md border p-3"
                 style="border-color: var(--surface-3); background: var(--surface-1);">
              <div class="mb-1.5 flex items-center justify-between">
                <span class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                  {{ diff.field }}
                </span>
                <span v-if="diff.similarity != null"
                      class="font-mono text-[10px]"
                      :style="{ color: diff.similarity < 0.3 ? 'var(--danger)' : 'var(--warning, #d97706)' }">
                  sim={{ diff.similarity.toFixed(3) }}
                </span>
              </div>
              <div class="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <div class="mb-0.5 font-mono text-[9px] uppercase" style="color: var(--ink-500);">Numista</div>
                  <div style="color: var(--ink);">{{ diff.numista_value || '—' }}</div>
                </div>
                <div>
                  <div class="mb-0.5 font-mono text-[9px] uppercase" style="color: var(--ink-500);">BCE</div>
                  <div style="color: var(--ink);">{{ diff.bce_value || '—' }}</div>
                </div>
              </div>
            </div>
          </div>

          <!-- Provenance run BCE -->
          <div v-if="selected.bce_run_id"
               class="mt-4 pt-3 border-t text-[10px] font-mono"
               style="border-color: var(--surface-2); color: var(--ink-500);">
            Sidecar BCE produit par run
            <router-link :to="`/sources/bce/runs/${selected.bce_run_id}`"
                         style="color: var(--indigo-700);">
              {{ selected.bce_run_id.slice(0, 8) }}
            </router-link>
          </div>
        </div>

        <div v-else class="rounded-lg border p-12 text-center text-sm"
             style="border-color: var(--surface-3); background: var(--surface); color: var(--ink-500);">
          Sélectionne une divergence à gauche.
        </div>
      </div>
    </template>
  </div>
</template>
