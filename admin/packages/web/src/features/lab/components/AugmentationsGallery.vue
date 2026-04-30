<script setup lang="ts">
import { ML_API } from '@/features/training/composables/useTrainingApi'
import {
  useAugmentationsQuery,
  usePurgeAugmentationsMutation,
} from '@/features/lab/composables/useLabQueries'
import type { IterationStatus } from '@/features/lab/types'
import { Loader2, Trash2 } from 'lucide-vue-next'
import { computed, ref } from 'vue'

const props = defineProps<{
  cohortId: string
  iterationId: string
  status: IterationStatus
  /** Maximum samples to render per coin. */
  perCoinLimit?: number
}>()

const limit = computed(() => props.perCoinLimit ?? 12)

const cohortId = computed(() => props.cohortId)
const iterationId = computed(() => props.iterationId)

const augQuery = useAugmentationsQuery(cohortId, iterationId)
const purge = usePurgeAugmentationsMutation(cohortId, iterationId)
const isLocked = computed(() =>
  props.status === 'training' || props.status === 'benchmarking' || props.status === 'completed',
)

const data = computed(() => augQuery.data.value ?? null)
const total = computed(() => data.value?.total_samples ?? 0)
const seed = computed(() => data.value?.augmentations_seed)

// Cache-bust image URLs after each successful refetch — the filenames
// (sample_001.jpg …) are stable across regenerations so without this
// the browser serves the old cached file.
function imgUrl(relPath: string): string {
  // Backend returns paths like 'datasets/<nid>/augmentations/<iid>/sample_NNN.jpg'.
  // The static endpoint is /datasets/<nid>/augmentations/<iid>/<filename>.
  return `${ML_API}/${relPath}?v=${augQuery.dataUpdatedAt.value}`
}

const zoom = ref<string | null>(null)
function openZoom(url: string) { zoom.value = url }
function closeZoom() { zoom.value = null }

async function handlePurge() {
  if (!confirm(
    'Purger toutes les augmentations de cette itération ? '
    + 'L\'iteration restera consultable mais les samples baked seront supprimés du disque.',
  )) return
  try {
    await purge.mutateAsync()
  } catch (e) {
    alert(`Purge échouée : ${(e as Error).message}`)
  }
}
</script>

<template>
  <div>
    <div class="mb-3 flex items-center justify-between">
      <div>
        <p
          class="text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Augmentations
          <span v-if="seed != null" class="ml-2 font-mono normal-case" style="color: var(--ink-500);">
            seed={{ seed }}
          </span>
        </p>
        <p class="mt-0.5 text-xs" style="color: var(--ink-500);">
          {{ total }} sample(s) sur disque ·
          <span class="font-mono">{{ data?.variant_count ?? '?' }}</span> par pièce
        </p>
      </div>
      <div class="flex items-center gap-2">
        <button
          v-if="!isLocked && total > 0"
          class="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs transition-colors hover:bg-[var(--surface-2)]"
          style="border-color: var(--surface-3); color: var(--ink-500);"
          :disabled="purge.isPending.value"
          title="Supprime les samples baked du disque (l'iteration reste consultable)"
          @click="handlePurge"
        >
          <Loader2 v-if="purge.isPending.value" class="h-3 w-3 animate-spin" />
          <Trash2 v-else class="h-3 w-3" />
          Purger
        </button>
      </div>
    </div>

    <div
      v-if="augQuery.isLoading.value && !data"
      class="flex items-center gap-2 text-sm"
      style="color: var(--ink-500);"
    >
      <Loader2 class="h-4 w-4 animate-spin" />
      Chargement…
    </div>
    <div
      v-else-if="augQuery.error.value"
      class="rounded-md border px-3 py-2 text-xs"
      style="border-color: var(--danger); color: var(--ink);"
    >
      {{ (augQuery.error.value as Error).message }}
    </div>
    <div
      v-else-if="!data || total === 0"
      class="rounded-lg border-2 border-dashed px-6 py-8 text-center text-sm"
      style="border-color: var(--surface-3); color: var(--ink-500);"
    >
      Aucune augmentation sur disque. Clique « Générer » dans §0 pour bake les samples.
    </div>

    <div v-else class="space-y-5">
      <div
        v-for="coin in data.per_coin"
        :key="coin.eurio_id"
      >
        <div class="mb-1.5 flex items-baseline justify-between">
          <p class="font-mono text-xs" style="color: var(--ink);">
            {{ coin.eurio_id }}
            <span v-if="coin.numista_id" class="ml-1" style="color: var(--ink-500);">
              · n{{ coin.numista_id }}
            </span>
          </p>
          <p class="text-[10px]" style="color: var(--ink-500);">
            {{ coin.samples.length }} samples
          </p>
        </div>
        <div
          v-if="coin.samples.length === 0"
          class="text-xs italic"
          style="color: var(--ink-400);"
        >
          (aucune)
        </div>
        <div v-else class="grid grid-cols-6 gap-1.5 sm:grid-cols-8 lg:grid-cols-12">
          <button
            v-for="rel in coin.samples.slice(0, limit)"
            :key="rel"
            class="aspect-square overflow-hidden rounded border transition-transform hover:scale-105"
            style="border-color: var(--surface-3); background: var(--surface);"
            @click="openZoom(imgUrl(rel))"
          >
            <img
              :src="imgUrl(rel)"
              :alt="rel"
              class="h-full w-full object-cover"
              loading="lazy"
            />
          </button>
        </div>
      </div>
    </div>

    <!-- Zoom overlay -->
    <div
      v-if="zoom"
      class="fixed inset-0 z-50 flex items-center justify-center p-8"
      style="background: rgba(0, 0, 0, 0.7);"
      @click="closeZoom"
    >
      <img :src="zoom" class="max-h-full max-w-full rounded-lg shadow-2xl" />
    </div>
  </div>
</template>
