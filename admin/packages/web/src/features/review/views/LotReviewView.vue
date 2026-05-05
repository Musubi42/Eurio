<script setup lang="ts">
// Vue Lot du flow review (V1.5).
// Grille de listings groupés (LotCard) → click navigue vers
// /review/lot/:listing_key (page full-page Specimen Plate, chunk 5).

import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Loader2, Package } from 'lucide-vue-next'
import {
  fetchLots, LotReviewError,
  type LotListItem,
} from '../composables/useLotReview'
import LotCard from '../components/LotCard.vue'

const router = useRouter()

const lots = ref<LotListItem[]>([])
const total = ref(0)
const loading = ref(true)
const error = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    const resp = await fetchLots({ limit: 24 })
    lots.value = resp.items
    total.value = resp.total
  } catch (err) {
    error.value = err instanceof LotReviewError ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

onMounted(load)

function openLot(key: string) {
  // Navigate to the full-page review detail (Phase 2 chunk 5).
  void router.push(`/review/lot/${encodeURIComponent(key)}`)
}
</script>

<template>
  <div class="flex flex-1 flex-col overflow-hidden">
    <!-- Sub-header : compteurs -->
    <div
      class="flex flex-wrap items-center justify-between gap-4 border-b px-8 py-2.5"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <p class="font-mono text-[11px] tabular-nums" style="color: var(--ink-500);">
        <span class="font-semibold" style="color: var(--gold-600);">{{ total }}</span>
        <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">listings à reviewer</span>
      </p>
      <p class="font-mono text-[10px]" style="color: var(--ink-400);">
        Cliquer une card pour ouvrir le détail (full-page)
      </p>
    </div>

    <!-- Body -->
    <section class="flex-1 overflow-y-auto px-8 py-6">
      <div
        v-if="loading"
        class="flex items-center justify-center gap-2 py-16 text-sm"
        style="color: var(--ink-400);"
      >
        <Loader2 class="h-4 w-4 animate-spin" /> Chargement…
      </div>

      <div
        v-else-if="error"
        class="rounded-lg border px-5 py-3 text-sm"
        style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);"
      >
        {{ error }}
      </div>

      <div
        v-else-if="!lots.length"
        class="flex flex-col items-center justify-center gap-4 py-16 text-center"
      >
        <Package class="h-10 w-10" :style="{ color: 'var(--gold-600)' }" />
        <p
          class="font-display text-3xl italic font-semibold"
          style="color: var(--indigo-700);"
        >
          Aucun lot à reviewer.
        </p>
        <p class="max-w-md text-sm" style="color: var(--ink-500);">
          Les coffrets et listings multi-pièces apparaissent ici quand le
          pipeline les flagge (D-26 niveaux 1+2). La prochaine ronde de
          scrapes alimentera la file.
        </p>
      </div>

      <div
        v-else
        class="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4"
      >
        <LotCard
          v-for="lot in lots"
          :key="lot.listing_key"
          :lot="lot"
          @open="openLot"
        />
      </div>
    </section>
  </div>
</template>
