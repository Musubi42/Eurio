<script setup lang="ts">
// Tiroir I2 — Bake des augmentations.
// Bouton "Générer" (bake idempotent) + galerie. "Régénérer" force le rebuild
// via l'endpoint regenerate existant.

import AugmentationsGallery from '@/features/lab/components/AugmentationsGallery.vue'
import DrawerSection from '@/features/lab/components/DrawerSection.vue'
import {
  useBakeIterationMutation,
  useRegenerateAugmentationsMutation,
} from '@/features/lab/composables/useLabQueries'
import type {
  IterationDetail,
  IterationProgressI2,
} from '@/features/lab/types'
import { Loader2, RefreshCw, Wand2 } from 'lucide-vue-next'
import { computed, ref, toRefs } from 'vue'

const props = defineProps<{
  cohortId: string
  iteration: IterationDetail
  progress: IterationProgressI2 | null
  locked: boolean
  lockReason: string
}>()

const { cohortId } = toRefs(props)
const iterationId = computed(() => props.iteration.id)

const bakeMut = useBakeIterationMutation(cohortId, iterationId)
const regenMut = useRegenerateAugmentationsMutation(cohortId, iterationId)
const error = ref<string | null>(null)

const isPending = computed(() => props.iteration.status === 'pending')

const summary = computed(() => {
  const p = props.progress
  if (!p) return 'Chargement…'
  if (p.state === 'empty')
    return 'Aucune augmentation bakée'
  if (p.state === 'partial') {
    const missing = p.per_coin.filter(c => c.baked < c.expected).length
    return `${p.total_baked}/${p.total_expected} samples — ${missing} pièce(s) incomplète(s)`
  }
  const coins = p.per_coin.length
  return `${p.total_expected} samples (${coins} × ${props.iteration.variant_count}) · obverse uniquement`
})

const missingCoins = computed(() =>
  (props.progress?.per_coin ?? []).filter(c => c.baked < c.expected),
)

async function bake() {
  error.value = null
  try {
    await bakeMut.mutateAsync()
  }
  catch (e) {
    error.value = (e as Error).message
  }
}

async function regenerate() {
  if (!confirm('Effacer les augmentations existantes et tout rebuild ?')) return
  error.value = null
  try {
    await regenMut.mutateAsync()
  }
  catch (e) {
    error.value = (e as Error).message
  }
}
</script>

<template>
  <DrawerSection
    number="I2"
    title="Bake des augmentations"
    :state="progress?.state ?? 'empty'"
    :summary="summary"
    :locked="locked"
    :lock-reason="lockReason"
  >
    <template #body>
      <div v-if="isPending" class="mb-4 flex flex-wrap items-center justify-end gap-2">
        <button
          class="flex items-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium"
          :style="{
            background: bakeMut.isPending.value ? 'var(--surface-2)' : 'var(--gold)',
            color: bakeMut.isPending.value ? 'var(--ink-400)' : 'var(--ink)',
            cursor: bakeMut.isPending.value ? 'wait' : 'pointer',
          }"
          :disabled="bakeMut.isPending.value"
          @click="bake"
        >
          <Loader2 v-if="bakeMut.isPending.value" class="h-3 w-3 animate-spin" />
          <Wand2 v-else class="h-3 w-3" />
          Générer
        </button>
        <button
          v-if="(progress?.total_baked ?? 0) > 0"
          class="flex items-center gap-1.5 rounded-md border px-3 py-2 text-xs"
          :style="{
            borderColor: 'var(--surface-3)',
            color: regenMut.isPending.value ? 'var(--ink-400)' : 'var(--ink)',
            cursor: regenMut.isPending.value ? 'wait' : 'pointer',
          }"
          :disabled="regenMut.isPending.value"
          title="Wipe + rebuild from scratch"
          @click="regenerate"
        >
          <Loader2 v-if="regenMut.isPending.value" class="h-3 w-3 animate-spin" />
          <RefreshCw v-else class="h-3 w-3" />
          Régénérer
        </button>
      </div>

      <div
        v-if="missingCoins.length > 0"
        class="mb-4 rounded-md border px-3 py-2 text-xs"
        style="border-color: var(--warning); background: color-mix(in srgb, var(--warning) 8%, var(--surface)); color: var(--ink);"
      >
        <p class="mb-1 font-medium" style="color: var(--warning);">
          {{ missingCoins.length }} pièce(s) incomplète(s)
        </p>
        <ul class="flex flex-wrap gap-2">
          <li
            v-for="c in missingCoins"
            :key="c.eurio_id"
            class="font-mono text-[11px]"
          >
            {{ c.eurio_id }} ({{ c.baked }}/{{ c.expected }}<span v-if="c.skipped_reason"> — {{ c.skipped_reason }}</span>)
          </li>
        </ul>
      </div>

      <p v-if="error" class="mb-3 rounded-md border px-3 py-2 text-xs" style="border-color: var(--danger); color: var(--ink);">
        {{ error }}
      </p>

      <AugmentationsGallery
        v-if="(progress?.total_baked ?? 0) > 0"
        :cohort-id="cohortId"
        :iteration-id="iteration.id"
        :status="iteration.status"
        :per-coin-limit="12"
      />
    </template>
  </DrawerSection>
</template>
