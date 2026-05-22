<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Gavel, RefreshCw } from 'lucide-vue-next'
import {
  type BenchReplay,
  type SearchFunnel,
  buildSearchFunnels,
  fetchThemeMatchBench,
} from '../composables/useBenchApi'
import BenchMetricsBar from '../components/BenchMetricsBar.vue'
import BenchSearchTabs from '../components/BenchSearchTabs.vue'
import BenchFunnel from '../components/BenchFunnel.vue'

const data = ref<BenchReplay | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const selectedYear = ref<number | null>(null)

const searches = computed<SearchFunnel[]>(() =>
  data.value ? buildSearchFunnels(data.value) : [],
)
const selected = computed<SearchFunnel | null>(
  () => searches.value.find(s => s.year === selectedYear.value) ?? null,
)

async function load() {
  loading.value = true
  error.value = null
  try {
    data.value = await fetchThemeMatchBench()
    if (selectedYear.value == null && searches.value.length) {
      selectedYear.value = searches.value[0].year
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    data.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden" style="background: var(--surface-1);">
    <!-- En-tête -->
    <header
      class="flex flex-shrink-0 items-center justify-between border-b px-7 py-4"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <div>
        <h1
          class="flex items-center gap-2 text-[20px] italic"
          style="font-family: var(--font-display); font-weight: 600; color: var(--indigo-700);"
        >
          <Gavel class="h-5 w-5" />
          Studio bench — theme-matcher
        </h1>
        <p class="mt-0.5 text-[12px]" style="color: var(--ink-400);">
          Le gold gelé rejoué recherche par recherche — juge toi-même chaque décision de filtrage.
        </p>
      </div>
      <button
        class="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[13px] transition-colors hover:bg-black/[0.03]"
        style="border-color: var(--surface-3); color: var(--ink-500);"
        :disabled="loading"
        @click="load"
      >
        <RefreshCw class="h-3.5 w-3.5" :class="loading ? 'animate-spin' : ''" />
        Rejouer
      </button>
    </header>

    <!-- Chargement -->
    <div v-if="loading" class="flex flex-1 items-center justify-center">
      <p class="italic" style="font-family: var(--font-display); color: var(--ink-400);">
        Replay en cours…
      </p>
    </div>

    <!-- Erreur -->
    <div v-else-if="error" class="flex flex-1 items-center justify-center">
      <div class="max-w-md text-center">
        <p class="text-[17px] italic"
           style="font-family: var(--font-display); color: var(--danger);">
          Replay indisponible
        </p>
        <p class="mt-1 text-[13px]" style="color: var(--ink-500);">{{ error }}</p>
        <button
          class="mt-3 rounded-lg border px-3 py-1.5 text-[13px]"
          style="border-color: var(--surface-3); color: var(--ink-500);"
          @click="load"
        >Réessayer</button>
      </div>
    </div>

    <!-- Studio -->
    <div v-else-if="data" class="flex flex-1 flex-col overflow-y-auto">
      <div class="mx-auto w-full max-w-[1100px] px-7 py-6">
        <!-- Métriques globales du gold -->
        <section>
          <h2 class="mb-2 text-[11px] font-medium uppercase tracking-[0.12em]"
              style="color: var(--ink-400);">
            Bilan global du gold — {{ data.metrics.total }} annonces
          </h2>
          <BenchMetricsBar :metrics="data.metrics" />
        </section>

        <!-- Les recherches eBay -->
        <section class="mt-7">
          <h2 class="mb-2 text-[11px] font-medium uppercase tracking-[0.12em]"
              style="color: var(--ink-400);">
            {{ searches.length }} recherches eBay — choisis-en une à auditer
          </h2>
          <BenchSearchTabs
            :searches="searches"
            :selected-year="selectedYear"
            @select="selectedYear = $event"
          />
        </section>

        <!-- L'entonnoir de la recherche sélectionnée -->
        <section
          v-if="selected"
          class="mt-7 rounded-2xl border px-6 py-7"
          style="border-color: var(--surface-3); background: var(--surface-1);"
        >
          <BenchFunnel :key="selected.year" :search="selected" />
        </section>
      </div>
    </div>
  </div>
</template>
