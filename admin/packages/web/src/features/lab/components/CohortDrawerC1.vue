<script setup lang="ts">
// Tiroir C1 — sélection des pièces.
// Body reprend la liste des coins de la cohort + signale les pièces sans
// obverse pour qu'on aille les réuploader.

import DrawerSection from '@/features/lab/components/DrawerSection.vue'
import { useRemoveCoinMutation } from '@/features/lab/composables/useLabQueries'
import type { CohortProgress, CohortSummary } from '@/features/lab/types'
import { Plus, X } from 'lucide-vue-next'
import { computed, toRefs } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps<{
  cohortId: string
  cohort: CohortSummary
  progress: CohortProgress | null
}>()
const { cohortId } = toRefs(props)

const router = useRouter()
const removeCoin = useRemoveCoinMutation(cohortId)

const isDraft = computed(() => props.cohort.status === 'draft')

const c1 = computed(() => props.progress?.c1 ?? null)
const state = computed(() => c1.value?.state ?? 'empty')
const missing = computed(() => c1.value?.missing_obverse ?? [])
const total = computed(() => props.cohort.eurio_ids.length)

const summary = computed(() => {
  if (!c1.value) return `${total.value} pièces`
  if (state.value === 'empty')
    return 'Aucune pièce — attache depuis /coins'
  if (state.value === 'partial')
    return `${total.value} pièces · ${missing.value.length} sans obverse`
  return `${total.value} pièces · toutes obverse-ready`
})

async function handleRemove(eid: string) {
  if (!confirm(`Retirer ${eid} du cohort ?`)) return
  try {
    await removeCoin.mutateAsync(eid)
  }
  catch (e) {
    alert(`Échec : ${(e as Error).message}`)
  }
}

function goAddCoins() {
  router.push({ path: '/coins', query: { cohort_attach: props.cohort.id } })
}

function goCoin(eid: string) {
  router.push(`/coins/${eid}`)
}
</script>

<template>
  <DrawerSection
    number="C1"
    title="Sélection des pièces"
    :state="state"
    :summary="summary"
  >
    <template #body>
      <div class="flex items-center justify-between mb-3">
        <p class="text-[10px] font-medium uppercase" style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);">
          {{ total }} pièce(s) {{ isDraft ? '· éditable' : '· frozen' }}
        </p>
        <button
          v-if="isDraft"
          class="flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px]"
          style="border-color: var(--surface-3); color: var(--ink);"
          @click="goAddCoins"
        >
          <Plus class="h-3 w-3" />
          Ajouter
        </button>
      </div>

      <div v-if="total === 0" class="text-sm" style="color: var(--ink-500);">
        Aucune pièce attachée. Va dans <code>/coins</code> et utilise la modal "Cohort lab".
      </div>
      <div v-else class="flex flex-wrap gap-1.5">
        <span
          v-for="eid in cohort.eurio_ids"
          :key="eid"
          class="flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[11px]"
          :style="{
            borderColor: missing.includes(eid) ? 'var(--warning)' : 'var(--surface-3)',
            background: missing.includes(eid) ? 'color-mix(in srgb, var(--warning) 8%, var(--surface))' : 'var(--surface)',
            color: 'var(--ink)',
          }"
        >
          {{ eid }}
          <button
            v-if="isDraft"
            class="rounded-full p-0.5 transition-colors hover:bg-[var(--danger-soft)]"
            :title="`Retirer ${eid}`"
            @click="handleRemove(eid)"
          >
            <X class="h-2.5 w-2.5" style="color: var(--ink-400);" />
          </button>
        </span>
      </div>

      <div
        v-if="missing.length > 0"
        class="mt-4 rounded-md border px-3 py-2 text-xs"
        style="border-color: var(--warning); background: color-mix(in srgb, var(--warning) 8%, var(--surface)); color: var(--ink);"
      >
        <p class="mb-1 font-medium" style="color: var(--warning);">
          {{ missing.length }} pièce(s) sans obverse.jpg/png sur disque
        </p>
        <ul class="flex flex-wrap gap-2">
          <li v-for="eid in missing" :key="eid">
            <button
              class="font-mono text-[11px] underline"
              style="color: var(--ink);"
              @click="goCoin(eid)"
            >
              {{ eid }}
            </button>
          </li>
        </ul>
      </div>
    </template>
  </DrawerSection>
</template>
