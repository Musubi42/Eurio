<script setup lang="ts">
import CohortDrawerC1 from '@/features/lab/components/CohortDrawerC1.vue'
import CohortDrawerC2 from '@/features/lab/components/CohortDrawerC2.vue'
import CohortDrawerCrop from '@/features/lab/components/CohortDrawerCrop.vue'
import CohortDrawerEbay from '@/features/lab/components/CohortDrawerEbay.vue'
import CohortFlowHeader from '@/features/lab/components/CohortFlowHeader.vue'
import CohortDrawerRescue from '@/features/lab/components/CohortDrawerRescue.vue'
import CohortTrainingQa from '@/features/lab/components/CohortTrainingQa.vue'
import IterationRow from '@/features/lab/components/IterationRow.vue'
import SensitivityPanel from '@/features/lab/components/SensitivityPanel.vue'
import TrajectoryChart from '@/features/lab/components/TrajectoryChart.vue'
import { useQueryClient } from '@tanstack/vue-query'
import { deleteCohort, fetchTrainingReadiness } from '@/features/lab/composables/useLabApi'
import {
  useCloneCohortMutation,
  useCohortProgressQuery,
  useCohortQuery,
  useCurrentMachineQuery,
  useIterationsQuery,
  useRunnerStatusQuery,
  useSensitivityQuery,
  useTrajectoryQuery,
} from '@/features/lab/composables/useLabQueries'
import type {
  CohortReadiness,
  IterationDetail,
} from '@/features/lab/types'
import { ArrowLeft, Copy as CopyIcon, Loader2, Plus, Trash2, X } from 'lucide-vue-next'
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

// Garde-fou « prêt à entraîner » : le staging est IMPLICITE (une itération
// entraîne les pièces de la cohorte). On vérifie le preflight AVANT de naviguer
// vers la création d'itération ; si une classe est trop pauvre, on bloque et on
// montre lesquelles (le hard-block vit aussi côté API, create_iteration → 409).
const checking = ref(false)
const blockReadiness = ref<CohortReadiness | null>(null)
async function handleNewIteration() {
  if (!cohort.value) return
  checking.value = true
  blockReadiness.value = null
  try {
    const r = await fetchTrainingReadiness(cohort.value.id)
    if (r.ready) {
      router.push(`/lab/cohorts/${cohort.value.id}/iterations/new`)
    } else {
      blockReadiness.value = r
    }
  } catch (e) {
    alert(`Vérification « prêt à entraîner » échouée : ${(e as Error).message}`)
  } finally {
    checking.value = false
  }
}

// R3 : machine courante (mac/pc) pour l'origine + le gating des actions lourdes.
const currentMachineQuery = useCurrentMachineQuery()
const currentMachine = computed(() => currentMachineQuery.data.value ?? null)

/** Une itération est « locale » (ouvrable/actionnable ici) si elle a été calculée
 *  sur CETTE machine, ou si son origine est inconnue (pré-sync R3). */
function isLocalIteration(it: IterationDetail): boolean {
  return !it.created_on || !currentMachine.value || it.created_on === currentMachine.value
}

function openIteration(iterationId: string) {
  const it = iterationsById.value.get(iterationId)
  // Les artefacts d'une itération d'une AUTRE machine ne sont pas ici : la page
  // détail (ML local) 404erait. On ne navigue que vers les itérations locales.
  if (it && !isLocalIteration(it)) return
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
                background: (runnerBusy || !c2Ready || checking) ? 'var(--surface-2)' : 'var(--indigo-700)',
                color: (runnerBusy || !c2Ready || checking) ? 'var(--ink-400)' : 'white',
                cursor: (runnerBusy || !c2Ready || checking) ? 'not-allowed' : 'pointer',
                boxShadow: (runnerBusy || !c2Ready || checking) ? 'none' : 'var(--shadow-sm)',
              }"
              :disabled="runnerBusy || !c2Ready || checking"
              :title="!c2Ready
                ? 'Capture toutes les pièces avant de créer une iteration.'
                : (isDraft
                  ? (runnerBusy ? 'Une itération tourne déjà' : 'Vérifie que les classes sont prêtes, puis fige le cohort')
                  : (runnerBusy ? 'Une itération tourne déjà' : 'Lance une nouvelle itération'))"
              @click="handleNewIteration"
            >
              <Loader2 v-if="checking" class="h-3.5 w-3.5 animate-spin" />
              <Plus v-else class="h-3.5 w-3.5" />
              Nouvelle itération
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

      <!-- Garde-fou : itération bloquée tant que des classes ne sont pas prêtes -->
      <section
        v-if="blockReadiness && !blockReadiness.ready"
        class="mb-6 rounded-lg border"
        style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 6%, var(--surface));"
      >
        <div class="flex items-start justify-between gap-4 px-4 py-3">
          <div class="min-w-0">
            <p class="text-sm font-medium" style="color: var(--ink);">
              Itération bloquée — {{ blockReadiness.preflight.n_blocked + blockReadiness.preflight.n_warned }}
              classe(s) pas prête(s) à entraîner.
            </p>
            <p class="mt-1 text-xs" style="color: var(--ink-500);">
              Enrichis-les (scrape eBay) ou review leurs crops, puis relance. Le staging
              est implicite — une itération entraîne les {{ blockReadiness.n_classes }} pièces de la cohorte.
            </p>
            <p
              v-if="blockReadiness.unresolved.length"
              class="mt-1 text-xs"
              style="color: var(--danger);"
            >
              {{ blockReadiness.unresolved.length }} eurio_id(s) absent(s) du catalogue (réf morte) :
              <code class="font-mono">{{ blockReadiness.unresolved.join(', ') }}</code>
            </p>
          </div>
          <button
            class="rounded p-1 transition-colors hover:bg-[var(--surface-2)]"
            style="color: var(--ink-400);"
            title="Fermer"
            @click="blockReadiness = null"
          >
            <X class="h-3.5 w-3.5" />
          </button>
        </div>
        <table class="w-full border-t text-sm" style="border-color: var(--surface-3);">
          <thead>
            <tr style="background: var(--surface-1);">
              <th class="px-4 py-1.5 text-left text-[10px] uppercase" style="color: var(--ink-500);">Classe pas prête</th>
              <th class="px-2 py-1.5 text-right text-[10px] uppercase" style="color: var(--ink-500);">Réel</th>
              <th class="px-2 py-1.5 text-right text-[10px] uppercase" style="color: var(--ink-500);">eBay</th>
              <th class="px-4 py-1.5 text-left text-[10px] uppercase" style="color: var(--ink-500);">Raison</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="c in blockReadiness.preflight.classes.filter(c => c.status !== 'ok')"
              :key="c.class_id"
              class="border-t"
              style="border-color: var(--surface-3);"
            >
              <td class="px-4 py-1.5 font-mono text-xs" style="color: var(--ink);">{{ c.class_id }}</td>
              <td class="px-2 py-1.5 text-right font-mono text-xs" style="color: var(--ink-500);">{{ c.seed }}</td>
              <td class="px-2 py-1.5 text-right font-mono text-xs" style="color: var(--ink-500);">{{ c.n_ebay }}</td>
              <td class="px-4 py-1.5 text-xs">
                <span :style="{ color: c.status === 'block' ? 'var(--danger)' : 'var(--warning)' }">
                  {{ c.status === 'block' ? '✗ ' : '⚠ ' }}{{ c.reason }}
                </span>
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
        <CohortTrainingQa
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
                  <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Origine</th>
                </tr>
              </thead>
              <tbody>
                <IterationRow
                  v-for="it in iterations"
                  :key="it.id"
                  :iteration="it"
                  :parent="getParent(it)"
                  :current-machine="currentMachine"
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
