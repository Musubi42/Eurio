<script setup lang="ts">
// Tiroir C2 — captures device.
// Embarque CaptureSection existant. Locked tant que C1 n'est pas ready.

import CaptureSection from '@/features/lab/components/CaptureSection.vue'
import DrawerSection from '@/features/lab/components/DrawerSection.vue'
import type { CohortProgress, CohortSummary } from '@/features/lab/types'
import { computed } from 'vue'

const props = defineProps<{
  cohortId: string
  cohort: CohortSummary
  progress: CohortProgress | null
}>()

const c1Ready = computed(() => props.progress?.c1.state === 'ready')
const c2 = computed(() => props.progress?.c2 ?? null)

const state = computed(() => {
  if (!c1Ready.value) return 'empty'
  return c2.value?.state ?? 'empty'
})

const summary = computed(() => {
  if (!c2.value) return 'Aucune capture'
  const total = props.cohort.eurio_ids.length
  const expected = c2.value.expected_per_coin
  if (c2.value.state === 'empty')
    return 'Aucune capture'
  if (c2.value.state === 'ready')
    return `${total} pièces × ${expected} captures · prêtes pour iteration`
  return `${c2.value.fully_captured}/${total} pièces complètes`
})

const locked = computed(() => !c1Ready.value)
const lockReason = "Sélectionne d'abord toutes les pièces avec obverse."
</script>

<template>
  <DrawerSection
    number="C2"
    title="Captures device"
    :state="state"
    :summary="summary"
    :locked="locked"
    :lock-reason="lockReason"
  >
    <template #body>
      <CaptureSection
        :cohort-id="cohort.id"
        :cohort-name="cohort.name"
        :cohort-status="cohort.status"
      />
    </template>
  </DrawerSection>
</template>
