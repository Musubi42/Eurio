<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { FlaskConical, RefreshCw, Search } from 'lucide-vue-next'
import {
  type BenchReplay,
  fetchThemeMatchBench,
  outcomeLabel,
} from '../composables/useBenchApi'
import BenchMetricsBar from '../components/BenchMetricsBar.vue'
import BenchListingRow from '../components/BenchListingRow.vue'

const data = ref<BenchReplay | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

// Filtres
const yearFilter = ref<string>('all')
const outcomeFilter = ref<string>('all')
const disagreementsOnly = ref(false)
const search = ref('')

async function load() {
  loading.value = true
  error.value = null
  try {
    data.value = await fetchThemeMatchBench()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    data.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)

const years = computed(() => {
  if (!data.value) return []
  return [...new Set(data.value.listings.map(l => l.group_year))].sort()
})

const outcomes = computed(() => {
  if (!data.value) return []
  return [...new Set(data.value.listings.map(l => l.outcome))].sort()
})

const filtered = computed(() => {
  if (!data.value) return []
  const q = search.value.trim().toLowerCase()
  return data.value.listings.filter((l) => {
    if (yearFilter.value !== 'all' && String(l.group_year) !== yearFilter.value) return false
    if (outcomeFilter.value !== 'all' && l.outcome !== outcomeFilter.value) return false
    if (disagreementsOnly.value && l.agreement) return false
    if (q && !l.title.toLowerCase().includes(q) && !l.verdict.toLowerCase().includes(q)) return false
    return true
  })
})

const nDisagreements = computed(
  () => data.value?.listings.filter(l => !l.agreement).length ?? 0,
)
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden">
    <!-- En-tête -->
    <header class="flex items-center justify-between border-b px-6 py-4"
            style="border-color: var(--surface-3); background: white;">
      <div>
        <h1 class="flex items-center gap-2 font-display text-xl italic font-semibold"
            style="color: var(--indigo-700);">
          <FlaskConical class="h-5 w-5" />
          Studio bench — theme-matcher
        </h1>
        <p class="mt-0.5 text-xs" style="color: var(--ink-400);">
          Le gold gelé rejoué étape par étape — juge toi-même chaque décision de filtrage.
        </p>
      </div>
      <button
        class="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm transition-colors hover:bg-black/[0.03]"
        style="border-color: var(--surface-3); color: var(--ink-600);"
        :disabled="loading"
        @click="load"
      >
        <RefreshCw class="h-3.5 w-3.5" :class="loading ? 'animate-spin' : ''" />
        Rejouer
      </button>
    </header>

    <!-- États -->
    <div v-if="loading" class="flex flex-1 items-center justify-center">
      <p class="font-display italic" style="color: var(--ink-400);">Replay en cours…</p>
    </div>

    <div v-else-if="error" class="flex flex-1 items-center justify-center">
      <div class="max-w-md text-center">
        <p class="font-display text-lg italic" style="color: var(--danger);">
          Replay indisponible
        </p>
        <p class="mt-1 text-sm" style="color: var(--ink-500);">{{ error }}</p>
        <button
          class="mt-3 rounded-md border px-3 py-1.5 text-sm"
          style="border-color: var(--surface-3); color: var(--ink-600);"
          @click="load"
        >Réessayer</button>
      </div>
    </div>

    <div v-else-if="data" class="flex flex-1 flex-col overflow-hidden">
      <!-- Métriques -->
      <div class="border-b px-6 py-4" style="border-color: var(--surface-3);">
        <BenchMetricsBar :metrics="data.metrics" />
      </div>

      <!-- Filtres -->
      <div class="flex flex-wrap items-center gap-3 border-b px-6 py-2.5"
           style="border-color: var(--surface-3); background: var(--surface-1);">
        <select v-model="yearFilter" class="rounded-md border px-2 py-1 text-sm"
                style="border-color: var(--surface-3); color: var(--ink-600);">
          <option value="all">Toutes années</option>
          <option v-for="y in years" :key="y" :value="String(y)">{{ y }}</option>
        </select>

        <select v-model="outcomeFilter" class="rounded-md border px-2 py-1 text-sm"
                style="border-color: var(--surface-3); color: var(--ink-600);">
          <option value="all">Toutes issues</option>
          <option v-for="o in outcomes" :key="o" :value="o">{{ outcomeLabel(o) }}</option>
        </select>

        <label class="flex items-center gap-1.5 text-sm" style="color: var(--ink-600);">
          <input v-model="disagreementsOnly" type="checkbox" class="rounded" />
          Désaccords seulement
          <span class="rounded-full px-1.5 text-[11px] font-semibold"
                style="background: var(--danger); color: white;">{{ nDisagreements }}</span>
        </label>

        <div class="relative ml-auto">
          <Search class="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2"
                  style="color: var(--ink-400);" />
          <input
            v-model="search"
            type="text"
            placeholder="Filtrer titre / verdict…"
            class="rounded-md border py-1 pl-7 pr-2 text-sm"
            style="border-color: var(--surface-3); color: var(--ink-700); min-width: 220px;"
          />
        </div>

        <span class="text-xs" style="color: var(--ink-400);">
          {{ filtered.length }} / {{ data.listings.length }}
        </span>
      </div>

      <!-- Liste -->
      <div class="flex-1 overflow-y-auto">
        <p v-if="filtered.length === 0" class="px-6 py-10 text-center font-display italic"
           style="color: var(--ink-400);">
          Aucun listing pour ces filtres.
        </p>
        <BenchListingRow
          v-for="l in filtered"
          :key="l.listing_id"
          :listing="l"
          :group-coins="data.groups[String(l.group_year)] ?? []"
        />
      </div>
    </div>
  </div>
</template>
