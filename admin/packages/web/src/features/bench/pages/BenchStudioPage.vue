<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Coins, Gavel, RefreshCw, ScanLine } from 'lucide-vue-next'
import {
  type BenchReplay,
  type SearchFunnel,
  buildSearchFunnels,
  fetchThemeMatchBench,
  resolveFunnelNode,
} from '../composables/useBenchApi'
import BenchMetricsBar from '../components/BenchMetricsBar.vue'
import BenchSearchTabs from '../components/BenchSearchTabs.vue'
import BenchFunnel from '../components/BenchFunnel.vue'
import BenchDetailPanel from '../components/BenchDetailPanel.vue'
import BenchCoinCard from '../components/BenchCoinCard.vue'

const data = ref<BenchReplay | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const selectedYear = ref<number | null>(null)
const selectedNodeId = ref<string | null>(null)

const searches = computed<SearchFunnel[]>(() =>
  data.value ? buildSearchFunnels(data.value) : [],
)
const selected = computed<SearchFunnel | null>(
  () => searches.value.find(s => s.year === selectedYear.value) ?? null,
)
const selectedNode = computed(() =>
  selected.value ? resolveFunnelNode(selected.value, selectedNodeId.value) : null,
)

// Changer de recherche → on revient à la vue « pièces canoniques ».
watch(selectedYear, () => { selectedNodeId.value = null })

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

    <div v-if="loading" class="flex flex-1 items-center justify-center">
      <p class="italic" style="font-family: var(--font-display); color: var(--ink-400);">
        Replay en cours…
      </p>
    </div>

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

    <div v-else-if="data" class="flex flex-1 flex-col overflow-y-auto">
      <div class="mx-auto w-full max-w-[1320px] px-7 py-6">
        <!-- Métriques globales -->
        <section>
          <h2 class="mb-2 text-[11px] font-medium uppercase tracking-[0.12em]"
              style="color: var(--ink-400);">
            Bilan global du gold — {{ data.metrics.total }} annonces
          </h2>
          <BenchMetricsBar :metrics="data.metrics" />
        </section>

        <!-- Recherches eBay -->
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

        <!-- Entonnoir + détail -->
        <section
          v-if="selected"
          class="mt-6 overflow-hidden rounded-2xl border"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <div
            class="flex items-baseline gap-2.5 border-b px-6 py-3.5"
            style="border-color: var(--surface-3);"
          >
            <ScanLine class="h-4 w-4 self-center" style="color: var(--ink-400);" />
            <span class="text-[10.5px] font-medium uppercase tracking-[0.13em]"
                  style="color: var(--ink-400);">Recherche eBay</span>
            <span class="text-[19px]"
                  style="font-family: var(--font-display); font-weight: 600; color: var(--ink);">
              {{ selected.country }} · {{ selected.denomination }} · {{ selected.year }}
            </span>
          </div>

          <div class="flex" style="height: min(80vh, 940px); min-height: 540px;">
            <!-- Colonne 1 — pièces canoniques, toujours visibles -->
            <div
              class="flex w-[300px] flex-shrink-0 flex-col border-r"
              style="border-color: var(--surface-3);"
            >
              <div class="flex flex-shrink-0 items-center gap-2 border-b px-5 py-3"
                   style="border-color: var(--surface-3);">
                <Coins class="h-4 w-4" style="color: var(--ink-400);" />
                <h3 class="text-[13px] font-semibold" style="color: var(--ink);">
                  Pièces visées
                </h3>
                <span class="text-[12px]" style="color: var(--ink-400);">
                  {{ selected.coins.length }}
                </span>
              </div>
              <div class="flex-1 space-y-4 overflow-y-auto px-4 py-4">
                <BenchCoinCard
                  v-for="coin in selected.coins"
                  :key="coin.eurio_id"
                  :coin="coin"
                />
              </div>
            </div>

            <!-- Colonne 2 — entonnoir, sélecteur -->
            <div
              class="w-[326px] flex-shrink-0 overflow-y-auto border-r px-5 py-6"
              style="border-color: var(--surface-3); background: var(--surface-1);"
            >
              <BenchFunnel
                :search="selected"
                :selected-node-id="selectedNodeId"
                @select="selectedNodeId = selectedNodeId === $event ? null : $event"
              />
            </div>

            <!-- Colonne 3 — annonces du nœud sélectionné -->
            <div class="min-w-0 flex-1 overflow-hidden">
              <BenchDetailPanel :node="selectedNode" />
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>
