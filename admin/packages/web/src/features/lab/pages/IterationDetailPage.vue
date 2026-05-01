<script setup lang="ts">
import IterationDrawerI1 from '@/features/lab/components/IterationDrawerI1.vue'
import IterationDrawerI2 from '@/features/lab/components/IterationDrawerI2.vue'
import IterationDrawerI3 from '@/features/lab/components/IterationDrawerI3.vue'
import IterationDrawerI4 from '@/features/lab/components/IterationDrawerI4.vue'
import VerdictBadge from '@/features/lab/components/VerdictBadge.vue'
import {
  deleteIteration,
  fetchCohort,
  fetchIteration,
  updateIteration,
} from '@/features/lab/composables/useLabApi'
import {
  useIterationProgressQuery,
  useStopIterationMutation,
} from '@/features/lab/composables/useLabQueries'
import { useQueryClient } from '@tanstack/vue-query'
import type {
  CohortSummary,
  IterationDetail,
  Verdict,
} from '@/features/lab/types'
import { ArrowLeft, Loader2, Save, Square, Trash2 } from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const cohortId = computed(() => String(route.params.cohortId))
const iterationId = computed(() => String(route.params.iterationId))

const iteration = ref<IterationDetail | null>(null)
const cohort = ref<CohortSummary | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

const notesDraft = ref('')
const verdictOverrideDraft = ref<Verdict | null>(null)
const savingNotes = ref(false)

const qc = useQueryClient()
const status = computed(() => iteration.value?.status ?? null)

const progressQuery = useIterationProgressQuery(cohortId, iterationId, status)
const progress = computed(() => progressQuery.data.value ?? null)

const stopMut = useStopIterationMutation(cohortId)

async function reload() {
  loading.value = true
  error.value = null
  try {
    const it = await fetchIteration(cohortId.value, iterationId.value)
    iteration.value = it
    notesDraft.value = it.notes || ''
    verdictOverrideDraft.value = it.verdict_override
  }
  catch (e) {
    error.value = (e as Error).message
  }
  finally {
    loading.value = false
  }
}

async function loadCohort() {
  try {
    cohort.value = await fetchCohort(cohortId.value)
  }
  catch {
    cohort.value = null
  }
}

onMounted(async () => {
  await Promise.all([reload(), loadCohort()])
})

// When the polled progress flips status, refetch the full iteration so
// metrics (training_summary, benchmark_summary, verdict) refresh too.
watch(
  () => progress.value?.i3.status,
  (newStatus, oldStatus) => {
    if (newStatus && oldStatus && newStatus !== oldStatus) {
      reload()
    }
  },
)

const inProgress = computed(() =>
  status.value === 'training' || status.value === 'benchmarking',
)

const i1Ready = computed(() => progress.value?.i1.state === 'ready')
const i2Ready = computed(() => progress.value?.i2.state === 'ready')
const i3Ready = computed(() => progress.value?.i3.state === 'ready')

async function saveNotes() {
  if (!iteration.value) return
  savingNotes.value = true
  try {
    await updateIteration(cohortId.value, iterationId.value, {
      notes: notesDraft.value,
      verdict_override: verdictOverrideDraft.value,
    })
    await reload()
    qc.invalidateQueries({ queryKey: ['lab', 'cohort', cohortId.value] })
  }
  catch (e) {
    alert(`Sauvegarde échouée : ${(e as Error).message}`)
  }
  finally {
    savingNotes.value = false
  }
}

async function handleStop() {
  if (!iteration.value) return
  if (!confirm('Stopper cette itération ? Le training en cours sera interrompu.')) return
  try {
    await stopMut.mutateAsync(iteration.value.id)
    await reload()
  }
  catch (e) {
    alert(`Stop échoué : ${(e as Error).message}`)
  }
}

async function handleDelete() {
  if (!iteration.value) return
  if (!confirm(`Supprimer l'itération "${iteration.value.name}" ?`)) return
  try {
    await deleteIteration(cohortId.value, iterationId.value)
    router.push(`/lab/cohorts/${cohortId.value}`)
  }
  catch (e) {
    alert(`Suppression échouée : ${(e as Error).message}`)
  }
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('fr-FR', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}
</script>

<template>
  <div class="p-8">
    <button
      class="mb-4 flex items-center gap-1 text-sm"
      style="color: var(--ink-500);"
      @click="router.push(`/lab/cohorts/${cohortId}`)"
    >
      <ArrowLeft class="h-3.5 w-3.5" />
      Retour au cohort
    </button>

    <div v-if="loading && !iteration" class="flex items-center gap-3 text-sm" style="color: var(--ink-500);">
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

    <template v-else-if="iteration">
      <!-- Header -->
      <header class="mb-8">
        <div class="flex items-start justify-between gap-6">
          <div class="min-w-0 flex-1">
            <p
              class="mb-1 text-[10px] font-medium uppercase"
              style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
            >
              Itération · {{ iteration.id }}
            </p>
            <div class="flex items-center gap-3">
              <h1
                class="font-display text-3xl italic font-semibold leading-tight"
                style="color: var(--indigo-700);"
              >
                {{ iteration.name }}
              </h1>
              <VerdictBadge
                :verdict="iteration.verdict"
                :override="iteration.verdict_override"
              />
            </div>
            <p
              v-if="iteration.hypothesis"
              class="mt-2 max-w-2xl text-sm italic"
              style="color: var(--ink-500);"
            >
              « {{ iteration.hypothesis }} »
            </p>
            <div class="mt-3 flex flex-wrap gap-4 text-xs" style="color: var(--ink-500);">
              <span>Démarré : {{ formatDate(iteration.started_at) }}</span>
              <span>Fini : {{ formatDate(iteration.finished_at) }}</span>
              <span v-if="iteration.parent_iteration_id">
                Parent :
                <a
                  class="font-mono underline"
                  style="color: var(--indigo-700);"
                  :href="`/lab/cohorts/${cohortId}/iterations/${iteration.parent_iteration_id}`"
                >{{ iteration.parent_iteration_id }}</a>
              </span>
            </div>
          </div>

          <div class="flex flex-shrink-0 items-start gap-2">
            <button
              v-if="inProgress"
              class="flex items-center gap-1.5 rounded-md border px-3 py-2 text-sm font-medium"
              :style="{
                borderColor: 'var(--danger)',
                color: stopMut.isPending.value ? 'var(--ink-400)' : 'var(--danger)',
                cursor: stopMut.isPending.value ? 'wait' : 'pointer',
              }"
              :disabled="stopMut.isPending.value"
              title="Stopper l'itération en cours"
              @click="handleStop"
            >
              <Loader2 v-if="stopMut.isPending.value" class="h-3.5 w-3.5 animate-spin" />
              <Square v-else class="h-3.5 w-3.5" />
              Stopper
            </button>
            <button
              v-if="!inProgress"
              class="rounded-md border p-2"
              style="border-color: var(--surface-3); color: var(--ink-400);"
              title="Supprimer"
              @click="handleDelete"
            >
              <Trash2 class="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
        <div class="mt-6 h-px w-16" style="background: var(--gold);" />
      </header>

      <!-- In-progress banner -->
      <div
        v-if="inProgress"
        class="mb-6 flex items-center gap-3 rounded-md border px-4 py-3 text-sm"
        style="border-color: var(--warning); background: color-mix(in srgb, var(--warning) 6%, var(--surface)); color: var(--ink);"
      >
        <Loader2 class="h-4 w-4 animate-spin" style="color: var(--warning);" />
        <span>
          {{ status === 'training' ? 'Training en cours' : 'Benchmark en cours' }}…
          La page se rafraîchit automatiquement.
        </span>
      </div>

      <!-- Failed banner -->
      <div
        v-if="status === 'failed'"
        class="mb-6 rounded-md border px-4 py-3 text-sm"
        style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 6%, var(--surface)); color: var(--ink);"
      >
        <p class="font-medium" style="color: var(--danger);">Itération en échec</p>
        <p class="mt-1 font-mono text-xs">{{ iteration.error || 'aucun détail' }}</p>
      </div>

      <div class="grid grid-cols-1 gap-8 lg:grid-cols-[1fr_320px]">
        <div class="flex flex-col gap-3">
          <IterationDrawerI1
            :cohort-id="cohortId"
            :iteration="iteration"
            :cohort="cohort"
            :progress="progress?.i1 ?? null"
          />
          <IterationDrawerI2
            :cohort-id="cohortId"
            :iteration="iteration"
            :progress="progress?.i2 ?? null"
            :locked="!i1Ready"
            lock-reason="Sélectionne d'abord une recipe (I1)."
          />
          <IterationDrawerI3
            :cohort-id="cohortId"
            :iteration="iteration"
            :progress="progress?.i3 ?? null"
            :locked="!i2Ready"
            lock-reason="Bake les augmentations d'abord (I2)."
          />
          <IterationDrawerI4
            :cohort-id="cohortId"
            :iteration="iteration"
            :progress="progress?.i4 ?? null"
            :locked="!i3Ready"
            lock-reason="Termine le training d'abord (I3)."
          />
        </div>

        <!-- Notes + verdict override sidebar -->
        <aside>
          <div
            class="rounded-lg border p-4"
            style="border-color: var(--surface-3); background: var(--surface);"
          >
            <p class="mb-2 text-[10px] font-medium uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
              Notes
            </p>
            <textarea
              v-model="notesDraft"
              rows="6"
              placeholder="Observations, intuitions, prochains tests…"
              class="w-full rounded-md border px-3 py-2 text-sm"
              style="border-color: var(--surface-3);"
            />
            <p class="mt-4 mb-2 text-[10px] font-medium uppercase" style="color: var(--ink-500);">
              Override du verdict (optionnel)
            </p>
            <select
              v-model="verdictOverrideDraft"
              class="w-full rounded-md border px-3 py-2 text-xs"
              style="border-color: var(--surface-3);"
            >
              <option :value="null">— auto —</option>
              <option value="better">better</option>
              <option value="worse">worse</option>
              <option value="mixed">mixed</option>
              <option value="no_change">no_change</option>
              <option value="baseline">baseline</option>
            </select>
            <button
              class="mt-3 flex w-full items-center justify-center gap-1.5 rounded-md px-3 py-2 text-xs font-medium"
              :style="{
                background: savingNotes ? 'var(--surface-2)' : 'var(--indigo-700)',
                color: savingNotes ? 'var(--ink-400)' : 'white',
                cursor: savingNotes ? 'wait' : 'pointer',
              }"
              :disabled="savingNotes"
              @click="saveNotes"
            >
              <Loader2 v-if="savingNotes" class="h-3 w-3 animate-spin" />
              <Save v-else class="h-3 w-3" />
              Sauvegarder
            </button>
          </div>
        </aside>
      </div>
    </template>
  </div>
</template>
