<script setup lang="ts">
import CohortDrawerC1 from '@/features/lab/components/CohortDrawerC1.vue'
import CohortDrawerC2 from '@/features/lab/components/CohortDrawerC2.vue'
import CohortDrawerCrop from '@/features/lab/components/CohortDrawerCrop.vue'
import CohortDrawerEbay from '@/features/lab/components/CohortDrawerEbay.vue'
import CohortFlowHeader from '@/features/lab/components/CohortFlowHeader.vue'
import CohortDrawerRescue from '@/features/lab/components/CohortDrawerRescue.vue'
import IterationRow from '@/features/lab/components/IterationRow.vue'
import SensitivityPanel from '@/features/lab/components/SensitivityPanel.vue'
import TrajectoryChart from '@/features/lab/components/TrajectoryChart.vue'
import { useQueryClient } from '@tanstack/vue-query'
import { deleteCohort, stageCohortForTraining } from '@/features/lab/composables/useLabApi'
import {
  useCloneCohortMutation,
  useCohortProgressQuery,
  useCohortQuery,
  useIterationsQuery,
  useRunnerStatusQuery,
  useSensitivityQuery,
  useTrajectoryQuery,
} from '@/features/lab/composables/useLabQueries'
import type {
  CohortStageResult,
  IterationDetail,
} from '@/features/lab/types'
import { ArrowLeft, Copy as CopyIcon, Layers, Loader2, Plus, Trash2, X } from 'lucide-vue-next'
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const cohortId = computed(() => String(route.params.id))

const cohortQuery = useCohortQuery(cohortId)
const cohort = computed(() => cohortQuery.data.value ?? null)

// `pollWhileBusy` is read synchronously during useQuery setup, so it must
// not reference `iterations` (which is declared below — TDZ). Hold the
// flag in a plain ref and let a watcher update it once query data lands.
const pollIterations = ref(false)
const iterationsQuery = useIterationsQuery(cohortId, {
  pollWhileBusy: pollIterations,
})
const iterations = computed<IterationDetail[]>(() => iterationsQuery.data.value ?? [])
watch(
  iterations,
  (its) => {
    pollIterations.value = its.some(
      it => it.status === 'training' || it.status === 'benchmarking',
    )
  },
  { immediate: true },
)

const progressQuery = useCohortProgressQuery(cohortId)
const progress = computed(() => progressQuery.data.value ?? null)
const c2Ready = computed(() => progress.value?.c2.state === 'ready')

const trajectoryQuery = useTrajectoryQuery(cohortId)
const trajectory = computed(() => trajectoryQuery.data.value ?? [])

const sensitivityQuery = useSensitivityQuery(cohortId)
const sensitivity = computed(() => sensitivityQuery.data.value ?? [])

const runnerQuery = useRunnerStatusQuery()
const runnerBusy = computed(() => runnerQuery.data.value?.busy ?? false)

const loading = computed(() => cohortQuery.isLoading.value && cohort.value === null)
const error = computed(() => (cohortQuery.error.value as Error | null)?.message ?? null)

const isDraft = computed(() => cohort.value?.status === 'draft')

const cloneMut = useCloneCohortMutation()
async function handleClone() {
  if (!cohort.value) return
  const proposed = `${cohort.value.name}-clone`
  const name = window.prompt('Nom du clone (kebab-case) :', proposed)?.trim()
  if (!name) return
  try {
    const created = await cloneMut.mutateAsync({ cohortId: cohort.value.id, name })
    router.push(`/lab/cohorts/${created.id}`)
  } catch (e) {
    alert(`Clone échoué : ${(e as Error).message}`)
  }
}

const qc = useQueryClient()
async function handleDeleteCohort() {
  if (!cohort.value) return
  const ok = confirm(
    `Supprimer le cohort "${cohort.value.name}" et ses ${cohort.value.iteration_count} itération(s) ?`,
  )
  if (!ok) return
  try {
    await deleteCohort(cohort.value.id)
    qc.invalidateQueries({ queryKey: ['lab', 'cohorts'] })
    router.push('/lab')
  } catch (e) {
    alert(`Suppression échouée : ${(e as Error).message}`)
  }
}

// Joint cohorte→training_staging : stage les classes de la cohorte (replace).
const staging = ref(false)
const stageResult = ref<CohortStageResult | null>(null)
async function handleStageForTraining() {
  if (!cohort.value) return
  const ok = confirm(
    `Stager pour training : remplacer le staging par les classes de "${cohort.value.name}" `
    + `(${cohort.value.eurio_ids.length} pièces → classes design_group/eurio_id) ?`,
  )
  if (!ok) return
  staging.value = true
  stageResult.value = null
  try {
    stageResult.value = await stageCohortForTraining(cohort.value.id, true)
  } catch (e) {
    alert(`Staging échoué : ${(e as Error).message}`)
  } finally {
    staging.value = false
  }
}

function openIteration(iterationId: string) {
  router.push(`/lab/cohorts/${cohortId.value}/iterations/${iterationId}`)
}

const latestIteration = computed<IterationDetail | null>(() => {
  if (iterations.value.length === 0) return null
  return iterations.value[iterations.value.length - 1]
})

const iterationsById = computed(() => {
  const map = new Map<string, IterationDetail>()
  for (const it of iterations.value) map.set(it.id, it)
  return map
})

function getParent(it: IterationDetail): IterationDetail | null {
  if (!it.parent_iteration_id) return null
  return iterationsById.value.get(it.parent_iteration_id) ?? null
}

function zoneColor(zone: string | null): string {
  if (zone === 'green') return 'var(--success)'
  if (zone === 'orange') return 'var(--warning)'
  if (zone === 'red') return 'var(--danger)'
  return 'var(--ink-400)'
}

function formatPct(v: number | null): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}
</script>

<template>
  <div class="p-8">
    <button
      class="mb-4 flex items-center gap-1 text-sm"
      style="color: var(--ink-500);"
      @click="router.push('/lab')"
    >
      <ArrowLeft class="h-3.5 w-3.5" />
      Retour au Lab
    </button>

    <div v-if="loading && !cohort" class="flex items-center gap-3 text-sm" style="color: var(--ink-500);">
      <Loader2 class="h-4 w-4 animate-spin" />
      Chargement…
    </div>
    <div
      v-else-if="error"
      class="rounded-md border px-4 py-3 text-sm"
      style="border-color: var(--danger); color: var(--ink);"
    >
      {{ error }}
    </div>

    <template v-else-if="cohort">
      <!-- Header -->
      <header class="mb-8">
        <div class="flex items-start justify-between gap-6">
          <div class="min-w-0 flex-1">
            <p
              class="mb-1 text-[10px] font-medium uppercase"
              style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
            >
              Cohort · {{ cohort.id }}
            </p>
            <div class="flex items-center gap-3">
              <h1
                class="font-display text-3xl italic font-semibold leading-tight"
                style="color: var(--indigo-700);"
              >
                {{ cohort.name }}
              </h1>
              <span
                class="rounded-full px-2 py-0.5 text-[10px] font-medium uppercase"
                :style="{
                  background: isDraft ? 'color-mix(in srgb, var(--ink-400) 14%, var(--surface))' : 'color-mix(in srgb, var(--indigo-700) 14%, var(--surface))',
                  color: isDraft ? 'var(--ink-500)' : 'var(--indigo-700)',
                  letterSpacing: 'var(--tracking-eyebrow)',
                }"
              >{{ cohort.status }}</span>
              <span
                v-if="cohort.zone"
                class="rounded-full px-2 py-0.5 text-xs font-medium"
                :style="{
                  background: `color-mix(in srgb, ${zoneColor(cohort.zone)} 14%, var(--surface))`,
                  color: zoneColor(cohort.zone),
                }"
              >{{ cohort.zone }}</span>
            </div>
            <p
              v-if="cohort.description"
              class="mt-1.5 text-sm"
              style="color: var(--ink-500);"
            >
              {{ cohort.description }}
            </p>
            <p class="mt-3 text-xs" style="color: var(--ink-500);">
              {{ cohort.eurio_ids.length }} pièces ·
              {{ cohort.iteration_count }} itération(s) ·
              meilleur R@1 : <span class="font-mono" :style="{ color: cohort.best_r_at_1 != null ? 'var(--success)' : 'var(--ink-400)' }">
                {{ formatPct(cohort.best_r_at_1) }}
              </span>
            </p>
          </div>

          <div class="flex flex-shrink-0 items-center gap-3">
            <button
              class="flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-all"
              :style="{
                background: (runnerBusy || !c2Ready) ? 'var(--surface-2)' : 'var(--indigo-700)',
                color: (runnerBusy || !c2Ready) ? 'var(--ink-400)' : 'white',
                cursor: (runnerBusy || !c2Ready) ? 'not-allowed' : 'pointer',
                boxShadow: (runnerBusy || !c2Ready) ? 'none' : 'var(--shadow-sm)',
              }"
              :disabled="runnerBusy || !c2Ready"
              :title="!c2Ready
                ? 'Capture toutes les pièces avant de créer une iteration.'
                : (isDraft
                  ? (runnerBusy ? 'Une itération tourne déjà' : 'Lancer figera le cohort')
                  : (runnerBusy ? 'Une itération tourne déjà' : 'Lance une nouvelle itération'))"
              @click="router.push(`/lab/cohorts/${cohort.id}/iterations/new`)"
            >
              <Plus class="h-3.5 w-3.5" />
              Nouvelle itération
            </button>
            <button
              class="flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm transition-colors hover:bg-[var(--surface-2)]"
              style="border-color: var(--surface-3); color: var(--ink);"
              :disabled="staging"
              :style="{ cursor: staging ? 'wait' : 'pointer' }"
              title="Remplace le staging du prochain run par les classes de cette cohorte (résout les eurio_ids → design_group, dédup) puis affiche le preflight."
              @click="handleStageForTraining"
            >
              <Loader2 v-if="staging" class="h-3.5 w-3.5 animate-spin" />
              <Layers v-else class="h-3.5 w-3.5" />
              Stager pour training
            </button>
            <button
              v-if="!isDraft"
              class="flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm transition-colors hover:bg-[var(--surface-2)]"
              style="border-color: var(--surface-3); color: var(--ink);"
              title="Cloner ce cohort en draft"
              @click="handleClone"
            >
              <CopyIcon class="h-3.5 w-3.5" />
              Cloner
            </button>
            <button
              class="rounded-md border p-2 transition-colors hover:bg-[var(--surface-2)]"
              style="border-color: var(--surface-3); color: var(--ink-400);"
              title="Supprimer le cohort"
              @click="handleDeleteCohort"
            >
              <Trash2 class="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
        <div class="mt-6 h-px w-16" style="background: var(--gold);" />
      </header>

      <!-- Résultat du staging cohorte→training (joint + preflight) -->
      <section
        v-if="stageResult"
        class="mb-6 rounded-lg border"
        :style="{
          borderColor: stageResult.preflight.ok ? 'var(--success)' : 'var(--danger)',
          background: `color-mix(in srgb, ${stageResult.preflight.ok ? 'var(--success)' : 'var(--danger)'} 6%, var(--surface))`,
        }"
      >
        <div class="flex items-start justify-between gap-4 px-4 py-3">
          <div class="min-w-0">
            <p class="text-sm font-medium" style="color: var(--ink);">
              {{ stageResult.staged.length }} classe(s) stagée(s){{ stageResult.replaced ? ' (staging remplacé)' : '' }}
              · <span :style="{ color: stageResult.preflight.ok ? 'var(--success)' : 'var(--danger)' }">
                {{ stageResult.preflight.ok ? 'prêt à entraîner' : `${stageResult.preflight.n_blocked} bloquante(s)` }}
              </span>
              <span v-if="stageResult.preflight.n_warned > 0" style="color: var(--warning);">
                · {{ stageResult.preflight.n_warned }} à surveiller
              </span>
            </p>
            <p
              v-if="stageResult.unresolved.length"
              class="mt-1 text-xs"
              style="color: var(--danger);"
            >
              {{ stageResult.unresolved.length }} eurio_id(s) non résolus (réf morte, non stagés) :
              <code class="font-mono">{{ stageResult.unresolved.join(', ') }}</code>
            </p>
          </div>
          <button
            class="rounded p-1 transition-colors hover:bg-[var(--surface-2)]"
            style="color: var(--ink-400);"
            title="Fermer"
            @click="stageResult = null"
          >
            <X class="h-3.5 w-3.5" />
          </button>
        </div>
        <table class="w-full border-t text-sm" style="border-color: var(--surface-3);">
          <thead>
            <tr style="background: var(--surface-1);">
              <th class="px-4 py-1.5 text-left text-[10px] uppercase" style="color: var(--ink-500);">Classe</th>
              <th class="px-2 py-1.5 text-right text-[10px] uppercase" style="color: var(--ink-500);">Seed</th>
              <th class="px-2 py-1.5 text-right text-[10px] uppercase" style="color: var(--ink-500);">eBay</th>
              <th class="px-4 py-1.5 text-left text-[10px] uppercase" style="color: var(--ink-500);">Statut</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="c in stageResult.preflight.classes"
              :key="c.class_id"
              class="border-t"
              style="border-color: var(--surface-3);"
            >
              <td class="px-4 py-1.5 font-mono text-xs" style="color: var(--ink);">{{ c.class_id }}</td>
              <td class="px-2 py-1.5 text-right font-mono text-xs" style="color: var(--ink-500);">{{ c.seed }}</td>
              <td class="px-2 py-1.5 text-right font-mono text-xs" style="color: var(--ink-500);">{{ c.n_ebay }}</td>
              <td class="px-4 py-1.5 text-xs">
                <span
                  :style="{
                    color: c.status === 'block' ? 'var(--danger)' : c.status === 'warn' ? 'var(--warning)' : 'var(--success)',
                  }"
                >{{ c.status === 'block' ? '✗ bloque' : c.status === 'warn' ? '⚠ ' + (c.reason ?? '') : 'ok' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- F3 : frise du flow 10 étapes (statut par étage = compteur d'état réel) -->
      <CohortFlowHeader
        :cohort-id="cohort.id"
        :cohort="cohort"
        :progress="progress"
      />

      <!-- §C1 Sélection + §C2 Captures + §C3 eBay (sourcing & funnel) + §C4 Review crops -->
      <div class="mb-6 flex flex-col gap-3">
        <CohortDrawerC1
          :cohort-id="cohort.id"
          :cohort="cohort"
          :progress="progress"
        />
        <CohortDrawerC2
          :cohort-id="cohort.id"
          :cohort="cohort"
          :progress="progress"
        />
        <CohortDrawerEbay
          :cohort-id="cohort.id"
          :cohort="cohort"
        />
        <CohortDrawerRescue
          :cohort-id="cohort.id"
        />
        <CohortDrawerCrop
          :cohort-id="cohort.id"
        />
      </div>

      <!-- Sprint 5 — soft cleanup banner: ≥5 iterations + ≥2 failed -->
      <div
        v-if="iterations.length >= 5 && iterations.filter(i => i.status === 'failed').length >= 2"
        class="mb-6 rounded-md border px-4 py-3 text-xs"
        style="border-color: var(--warning); background: color-mix(in srgb, var(--warning) 8%, var(--surface)); color: var(--ink);"
      >
        Cette cohort a {{ iterations.length }} itérations dont
        {{ iterations.filter(i => i.status === 'failed').length }} en échec.
        Tu peux purger leurs augmentations pour récupérer du disque — ouvre
        l'iteration concernée puis clique « Purger » dans la section
        Augmentations.
      </div>

      <!-- Trajectory -->
      <section class="mb-8">
        <p
          class="mb-2 text-[10px] font-medium uppercase"
          style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
        >
          Trajectoire R@1
        </p>
        <TrajectoryChart :points="trajectory" @select="openIteration" />
      </section>

      <div class="grid grid-cols-1 gap-8 lg:grid-cols-[1fr_360px]">
        <!-- Iterations table -->
        <section>
          <p
            class="mb-3 text-[10px] font-medium uppercase"
            style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
          >
            Itérations
          </p>
          <div
            v-if="iterations.length === 0"
            class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed px-8 py-10 text-center"
            style="border-color: var(--surface-3);"
          >
            <p class="font-display italic text-lg" style="color: var(--ink);">
              Aucune itération encore
            </p>
            <p class="mt-1 max-w-sm text-sm" style="color: var(--ink-500);">
              Clique <span class="font-medium" style="color: var(--indigo-700);">Nouvelle itération</span>
              pour lancer la première baseline sur ce cohort.
            </p>
          </div>
          <div
            v-else
            class="overflow-hidden rounded-lg border"
            style="border-color: var(--surface-3); background: var(--surface);"
          >
            <table class="w-full text-sm">
              <thead>
                <tr class="border-b" style="border-color: var(--surface-3); background: var(--surface-1);">
                  <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Nom / hypothèse</th>
                  <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Δ inputs vs parent</th>
                  <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">R@1</th>
                  <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Verdict</th>
                  <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Date</th>
                </tr>
              </thead>
              <tbody>
                <IterationRow
                  v-for="it in iterations"
                  :key="it.id"
                  :iteration="it"
                  :parent="getParent(it)"
                  @click="openIteration(it.id)"
                />
              </tbody>
            </table>
          </div>
          <p v-if="latestIteration" class="mt-3 text-[10px]" style="color: var(--ink-400);">
            La prochaine itération pourra hériter de
            <code class="font-mono" style="color: var(--indigo-700);">{{ latestIteration.name }}</code>
            comme parent par défaut.
          </p>
        </section>

        <!-- Sensitivity sidebar -->
        <aside>
          <SensitivityPanel :entries="sensitivity" />
        </aside>
      </div>
    </template>
  </div>
</template>
