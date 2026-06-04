<script setup lang="ts">
// Tiroir §C5 — Jetées & Rescue.
// Trois sections :
//   1. Tableau par eurio_id : total_discards + breakdown by_reason avec badges reason.
//   2. Liste rescue candidates (is_rescue_candidate=true) avec bouton Reclasser 1-clic.
//      → POST /lab/discarded/{id}/rescue : insère dans source_images (dédup). Le crop
//        n'existe pas encore — l'image sera dans source_images mais pas encore dans
//        image_assets. L'utilisateur doit re-fetcher les crops manuellement.
//   3. Bruit readonly (<details>) : noise_total + top reasons.

import DrawerSection from '@/features/lab/components/DrawerSection.vue'
import {
  useRescueCandidatesQuery,
  useRescueDiscardMutation,
} from '@/features/lab/composables/useLabQueries'
import type { DiscardReasonRow, DiscardSummaryClass, DrawerState } from '@/features/lab/types'
import { Loader2, RotateCcw } from 'lucide-vue-next'
import { computed, ref } from 'vue'

const props = defineProps<{
  cohortId: string
}>()

const candidatesQuery = useRescueCandidatesQuery(() => props.cohortId)
const rescue = useRescueDiscardMutation(() => props.cohortId)

const data = computed(() => candidatesQuery.data.value ?? null)
const loading = computed(() => candidatesQuery.isPending.value)
const error = computed(() => candidatesQuery.error.value)

const perClass = computed<DiscardSummaryClass[]>(() => data.value?.per_class ?? [])
const noiseTotal = computed(() => data.value?.noise_total ?? 0)
const noiseByReason = computed(() => data.value?.noise_by_reason ?? [])

// Candidates avec au moins une raison rescue
const rescuableClasses = computed(() =>
  perClass.value.filter(c => c.rescue_count > 0),
)

const totalRescuable = computed(() =>
  perClass.value.reduce((s, c) => s + c.rescue_count, 0),
)

const state = computed<DrawerState>(() => {
  if (loading.value || !data.value) return 'empty'
  if (totalRescuable.value > 0) return 'partial'
  if (perClass.value.some(c => c.total_discards > 0)) return 'ready'
  return 'empty'
})

const summary = computed(() => {
  if (loading.value || !data.value) return 'Chargement…'
  const total = perClass.value.reduce((s, c) => s + c.total_discards, 0)
  if (total === 0) return 'Aucun rejet scopé à cette cohort'
  const r = totalRescuable.value
  const n = noiseTotal.value
  const parts: string[] = [`${total} rejetés`]
  if (r > 0) parts.push(`${r} récupérables 1-clic`)
  if (n > 0) parts.push(`${n} bruit`)
  return parts.join(' · ')
})

// Suivi des rescues en cours + résultat (idempotence feedback)
const rescuing = ref<Set<string>>(new Set())
const rescuedMap = ref<Record<string, { eurio_id: string; already_existed: boolean }>>({})

async function onRescue(discardId: string) {
  if (rescuing.value.has(discardId)) return
  rescuing.value = new Set([...rescuing.value, discardId])
  try {
    const result = await rescue.mutateAsync(discardId)
    rescuedMap.value = {
      ...rescuedMap.value,
      [discardId]: { eurio_id: result.eurio_id, already_existed: result.already_existed },
    }
  } catch (e) {
    alert(`Rescue échoué (${discardId.slice(0, 8)}…) : ${(e as Error).message}`)
  } finally {
    const next = new Set(rescuing.value)
    next.delete(discardId)
    rescuing.value = next
  }
}

function rescueRows(c: DiscardSummaryClass): DiscardReasonRow[] {
  return c.by_reason.filter(r => r.is_rescue_candidate)
}
</script>

<template>
  <DrawerSection
    number="C5"
    title="Jetées & Rescue"
    :state="state"
    :summary="summary"
  >
    <template #body>
      <div v-if="loading" class="text-xs" style="color: var(--ink-400);">
        Chargement des rejets…
      </div>

      <template v-else-if="data">
        <!-- Section 1 — tableau par eurio_id -->
        <div
          v-if="perClass.length > 0"
          class="overflow-hidden rounded-md border"
          style="border-color: var(--surface-3);"
        >
          <div
            v-for="c in perClass"
            :key="c.eurio_id"
            class="coin"
          >
            <!-- L1 : identité + totaux -->
            <div class="coin__l1">
              <span class="coin__id">{{ c.eurio_id }}</span>
              <span class="coin__totals">
                <span
                  class="coin__badge"
                  :style="{
                    background: c.rescue_count > 0
                      ? 'color-mix(in srgb, var(--warning) 14%, var(--surface))'
                      : 'var(--surface-2)',
                    color: c.rescue_count > 0 ? 'var(--warning)' : 'var(--ink-400)',
                  }"
                >{{ c.total_discards }} rejetés</span>
                <span
                  v-if="c.rescue_count > 0"
                  class="coin__badge"
                  style="background: color-mix(in srgb, var(--success) 12%, var(--surface)); color: var(--success);"
                >{{ c.rescue_count }} rescue</span>
              </span>
            </div>

            <!-- L2 : breakdown by_reason en badges -->
            <div class="coin__reasons">
              <span
                v-for="r in c.by_reason"
                :key="r.reason"
                class="reason-badge"
                :class="{ 'reason-badge--rescue': r.is_rescue_candidate }"
              >
                {{ r.reason }}
                <span class="reason-badge__n">{{ r.n }}</span>
              </span>
            </div>
          </div>
        </div>
        <p v-else class="text-xs" style="color: var(--ink-400);">
          Aucun rejet scopé aux pièces de cette cohort.
        </p>

        <!-- Section 2 — rescue candidates 1-clic -->
        <div
          v-if="rescuableClasses.length > 0"
          class="mt-3"
        >
          <p class="mb-2 text-[10px] font-medium uppercase" style="letter-spacing: var(--tracking-eyebrow); color: var(--ink-400);">
            Rescue — {{ totalRescuable }} candidats 1-clic
          </p>
          <div class="overflow-hidden rounded-md border" style="border-color: var(--surface-3);">
            <div
              v-for="c in rescuableClasses"
              :key="`rescue-${c.eurio_id}`"
              class="coin"
            >
              <div class="coin__l1">
                <span class="coin__id">{{ c.eurio_id }}</span>
                <span
                  class="coin__badge"
                  style="background: color-mix(in srgb, var(--success) 12%, var(--surface)); color: var(--success);"
                >cible de reclassification</span>
              </div>

              <div
                v-for="row in rescueRows(c)"
                :key="row.reason"
                class="coin__rescue-row"
              >
                <span class="coin__muted">{{ row.reason }} · {{ row.n }} listing(s)</span>
                <div class="coin__actions">
                  <template v-for="dId in row.discard_ids" :key="dId">
                    <span
                      v-if="rescuedMap[dId]"
                      class="coin__muted"
                      :style="{ color: rescuedMap[dId].already_existed ? 'var(--ink-400)' : 'var(--success)' }"
                    >
                      {{ rescuedMap[dId].already_existed ? 'déjà en base' : 'reclassé ✓' }}
                      <span class="font-mono text-[9px]">{{ dId.slice(0, 6) }}</span>
                    </span>
                    <button
                      v-else
                      type="button"
                      class="coin__btn"
                      :disabled="rescuing.has(dId)"
                      :style="{ opacity: rescuing.has(dId) ? 0.5 : 1, cursor: rescuing.has(dId) ? 'not-allowed' : 'pointer' }"
                      :title="`Reclasser ${dId.slice(0, 8)} → ${c.eurio_id}`"
                      @click="onRescue(dId)"
                    >
                      <Loader2 v-if="rescuing.has(dId)" class="h-3 w-3 animate-spin" />
                      <RotateCcw v-else class="h-3 w-3" />
                      Reclasser
                      <span class="font-mono text-[9px]">{{ dId.slice(0, 6) }}</span>
                    </button>
                  </template>
                </div>
              </div>

              <!-- Avertissement image à re-fetcher -->
              <p class="rescue-note">
                Image reclassée en base uniquement — le crop n'existera pas avant un re-fetch des crops.
              </p>
            </div>
          </div>
        </div>
        <p v-else-if="perClass.length > 0" class="mt-3 text-xs" style="color: var(--ink-400);">
          Aucun candidat rescue — tous les rejets sont du bruit non récupérable.
        </p>

        <!-- Section 3 — bruit readonly -->
        <details v-if="noiseTotal > 0" class="mt-3 noise">
          <summary class="noise__summary">
            Bruit ({{ noiseTotal }} listings non récupérables)
          </summary>
          <dl class="mt-2 noise__grid">
            <template v-for="r in noiseByReason.slice(0, 10)" :key="r.reason">
              <dt>{{ r.reason }}</dt>
              <dd>{{ r.n }}</dd>
            </template>
          </dl>
          <p v-if="noiseByReason.length > 10" class="mt-1 text-[10px]" style="color: var(--ink-400);">
            +{{ noiseByReason.length - 10 }} autres raisons
          </p>
        </details>
      </template>

      <div
        v-else-if="error"
        class="text-xs"
        style="color: var(--danger);"
      >
        Erreur de chargement des rejets.
      </div>
    </template>
  </DrawerSection>
</template>

<style scoped>
/* Row-card par coin (même pattern que CohortDrawerEbay) */
.coin {
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 11px 14px;
  background: var(--surface);
}
.coin + .coin { border-top: 1px solid var(--surface-3); }
.coin__l1 {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.coin__id {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--ink);
  min-width: 0;
}
.coin__totals {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.coin__badge {
  border-radius: 3px;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 500;
}
.coin__reasons {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.coin__rescue-row {
  display: flex;
  align-items: flex-start;
  flex-direction: column;
  gap: 4px;
  padding-top: 4px;
  border-top: 1px solid var(--surface-3);
  margin-top: 2px;
}
.coin__actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.coin__btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: 4px;
  padding: 3px 8px;
  font-size: 10px;
  font-weight: 500;
  color: var(--indigo-700);
  background: color-mix(in srgb, var(--indigo-700) 9%, var(--surface));
  transition: background 160ms var(--ease-out, ease);
}
.coin__btn:hover { background: color-mix(in srgb, var(--indigo-700) 16%, var(--surface)); }
.coin__muted { font-size: 10px; color: var(--ink-400); }

/* Badge raison inline */
.reason-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border-radius: 3px;
  padding: 1px 6px;
  font-size: 10px;
  font-family: var(--font-mono);
  background: var(--surface-2);
  color: var(--ink-500);
}
.reason-badge--rescue {
  background: color-mix(in srgb, var(--warning) 12%, var(--surface));
  color: var(--warning);
}
.reason-badge__n {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* Avertissement image à re-fetcher */
.rescue-note {
  font-size: 10px;
  color: var(--ink-400);
  font-style: italic;
  padding-top: 2px;
}

/* Section bruit */
.noise__summary {
  cursor: pointer;
  font-size: 11px;
  font-weight: 500;
  color: var(--ink-500);
  user-select: none;
}
.noise__summary:hover { color: var(--ink); }
.noise__grid {
  display: grid;
  grid-template-columns: 1fr max-content;
  gap: 2px 16px;
  font-size: 11px;
  margin-top: 6px;
}
.noise__grid dt {
  font-family: var(--font-mono);
  color: var(--ink-500);
  font-size: 10px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.noise__grid dd {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
  text-align: right;
}
</style>
