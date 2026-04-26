<script setup lang="ts">
import InputDiffChip from '@/features/lab/components/InputDiffChip.vue'
import PerConditionTable from '@/features/lab/components/PerConditionTable.vue'
import VerdictBadge from '@/features/lab/components/VerdictBadge.vue'
import {
  deleteIteration,
  fetchIteration,
  updateIteration,
} from '@/features/lab/composables/useLabApi'
import { fetchBenchmarkRun } from '@/features/benchmark/composables/useBenchmarkApi'
import type { BenchmarkRunDetail } from '@/features/benchmark/types'
import type { IterationDetail, Verdict } from '@/features/lab/types'
import { ArrowLeft, ExternalLink, Loader2, Save, Trash2 } from 'lucide-vue-next'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const cohortId = computed(() => String(route.params.cohortId))
const iterationId = computed(() => String(route.params.iterationId))

const iteration = ref<IterationDetail | null>(null)
const benchmark = ref<BenchmarkRunDetail | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

const notesDraft = ref<string>('')
const verdictOverrideDraft = ref<Verdict | null>(null)
const savingNotes = ref(false)

let pollInterval: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await reload()
  pollInterval = setInterval(() => {
    if (iteration.value && (iteration.value.status === 'training' || iteration.value.status === 'benchmarking')) {
      reload()
    }
  }, 4000)
})

onUnmounted(() => {
  if (pollInterval) clearInterval(pollInterval)
})

async function reload() {
  loading.value = true
  error.value = null
  try {
    const it = await fetchIteration(cohortId.value, iterationId.value)
    iteration.value = it
    notesDraft.value = it.notes || ''
    verdictOverrideDraft.value = it.verdict_override
    if (it.benchmark_run_id) {
      benchmark.value = await fetchBenchmarkRun(it.benchmark_run_id).catch(() => null)
    } else {
      benchmark.value = null
    }
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function saveNotes() {
  if (!iteration.value) return
  savingNotes.value = true
  try {
    await updateIteration(cohortId.value, iterationId.value, {
      notes: notesDraft.value,
      verdict_override: verdictOverrideDraft.value,
    })
    await reload()
  } catch (e) {
    alert(`Sauvegarde échouée : ${(e as Error).message}`)
  } finally {
    savingNotes.value = false
  }
}

async function handleDelete() {
  if (!iteration.value) return
  const ok = confirm(`Supprimer l'itération "${iteration.value.name}" ?`)
  if (!ok) return
  try {
    await deleteIteration(cohortId.value, iterationId.value)
    router.push(`/lab/cohorts/${cohortId.value}`)
  } catch (e) {
    alert(`Suppression échouée : ${(e as Error).message}`)
  }
}

function formatPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function formatDelta(v: number | undefined): string {
  if (v == null) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${(v * 100).toFixed(2)} pts`
}

function deltaColor(v: number | undefined): string {
  if (v == null) return 'var(--ink-400)'
  if (v > 0.005) return 'var(--success)'
  if (v < -0.005) return 'var(--danger)'
  return 'var(--ink-400)'
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('fr-FR', {
    day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

const inProgress = computed(() =>
  iteration.value?.status === 'training' || iteration.value?.status === 'benchmarking',
)

const deltaR1 = computed(() => iteration.value?.delta_vs_parent?.r_at_1)
const perZoneDelta = computed(() => iteration.value?.delta_vs_parent?.per_zone ?? {})
const perCoinDelta = computed(() => iteration.value?.delta_vs_parent?.per_coin ?? {})

watch(iteration, (it) => {
  if (it) {
    notesDraft.value = it.notes || ''
    verdictOverrideDraft.value = it.verdict_override
  }
})
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
        class="mb-8 flex items-center gap-3 rounded-md border px-4 py-3 text-sm"
        style="border-color: var(--warning); background: color-mix(in srgb, var(--warning) 6%, var(--surface)); color: var(--ink);"
      >
        <Loader2 class="h-4 w-4 animate-spin" style="color: var(--warning);" />
        <span>
          {{ iteration.status === 'training' ? 'Training en cours' : 'Benchmark en cours' }}…
          La page se rafraîchit automatiquement.
        </span>
      </div>

      <!-- Failed banner -->
      <div
        v-if="iteration.status === 'failed'"
        class="mb-8 rounded-md border px-4 py-3 text-sm"
        style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 6%, var(--surface)); color: var(--ink);"
      >
        <p class="font-medium" style="color: var(--danger);">Itération en échec</p>
        <p class="mt-1 font-mono text-xs">{{ iteration.error || 'aucun détail' }}</p>
      </div>

      <!-- Metrics + delta grid -->
      <section class="mb-10 grid grid-cols-2 gap-4 md:grid-cols-4">
        <article
          v-for="{ label, value, delta } in [
            { label: 'R@1', value: formatPct(iteration.benchmark_summary?.r_at_1 ?? null), delta: deltaR1 },
            { label: 'R@3', value: formatPct(iteration.benchmark_summary?.r_at_3 ?? null), delta: iteration.delta_vs_parent?.r_at_3 },
            { label: 'R@5', value: formatPct(iteration.benchmark_summary?.r_at_5 ?? null), delta: iteration.delta_vs_parent?.r_at_5 },
            { label: 'Spread moyen', value: iteration.benchmark_summary?.mean_spread != null ? iteration.benchmark_summary.mean_spread.toFixed(3) : '—', delta: undefined },
          ]"
          :key="label"
          class="rounded-lg border p-4"
          style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-sm);"
        >
          <p class="text-[10px] font-medium uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            {{ label }}
          </p>
          <p class="mt-1 font-display text-3xl font-semibold tabular-nums leading-none" style="color: var(--indigo-700);">
            {{ value }}
          </p>
          <p
            v-if="delta !== undefined"
            class="mt-1 font-mono text-xs tabular-nums"
            :style="{ color: deltaColor(delta) }"
          >
            {{ formatDelta(delta) }} vs parent
          </p>
        </article>
      </section>

      <div class="grid grid-cols-1 gap-8 lg:grid-cols-[1fr_360px]">
        <div class="space-y-10">
          <!-- Inputs card -->
          <section>
            <p
              class="mb-3 text-[10px] font-medium uppercase"
              style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
            >
              Inputs
            </p>
            <div
              class="rounded-lg border p-5"
              style="border-color: var(--surface-3); background: var(--surface);"
            >
              <dl class="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <dt class="text-[10px] uppercase" style="color: var(--ink-500);">Recette</dt>
                  <dd class="mt-1 font-mono" style="color: var(--ink);">
                    <a
                      v-if="iteration.recipe_id"
                      :href="`/augmentation?eurio_ids=${''}`"
                      target="_blank"
                      class="inline-flex items-center gap-1"
                      style="color: var(--indigo-700);"
                    >
                      {{ iteration.recipe_id }}
                      <ExternalLink class="h-3 w-3" />
                    </a>
                    <span v-else style="color: var(--ink-400);">aucune</span>
                  </dd>
                </div>
                <div>
                  <dt class="text-[10px] uppercase" style="color: var(--ink-500);">Variants / classe</dt>
                  <dd class="mt-1 font-mono" style="color: var(--ink);">{{ iteration.variant_count }}</dd>
                </div>
                <div>
                  <dt class="text-[10px] uppercase" style="color: var(--ink-500);">Training config</dt>
                  <dd class="mt-1 font-mono text-xs" style="color: var(--ink);">
                    {{ JSON.stringify(iteration.training_config) }}
                  </dd>
                </div>
                <div>
                  <dt class="text-[10px] uppercase" style="color: var(--ink-500);">Training run</dt>
                  <dd class="mt-1 font-mono" style="color: var(--ink);">
                    <a
                      v-if="iteration.training_run_id"
                      :href="`/training`"
                      class="inline-flex items-center gap-1"
                      style="color: var(--indigo-700);"
                    >
                      {{ iteration.training_summary?.version ? `v${iteration.training_summary.version}` : iteration.training_run_id }}
                      <ExternalLink class="h-3 w-3" />
                    </a>
                    <span v-else style="color: var(--ink-400);">pas encore</span>
                  </dd>
                </div>
              </dl>
              <div class="mt-4 border-t pt-4" style="border-color: var(--surface-3);">
                <p class="mb-2 text-[10px] uppercase" style="color: var(--ink-500);">
                  Δ inputs vs parent
                </p>
                <InputDiffChip :diff="iteration.diff_from_parent" />
              </div>
            </div>
          </section>

          <!-- Per zone delta -->
          <section v-if="Object.keys(perZoneDelta).length > 0">
            <p
              class="mb-3 text-[10px] font-medium uppercase"
              style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
            >
              Delta par zone
            </p>
            <div
              class="overflow-hidden rounded-lg border"
              style="border-color: var(--surface-3); background: var(--surface);"
            >
              <table class="w-full text-sm">
                <thead>
                  <tr class="border-b" style="border-color: var(--surface-3); background: var(--surface-1);">
                    <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">Zone</th>
                    <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">ΔR@1</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(delta, zone) in perZoneDelta" :key="zone" class="border-b" style="border-color: var(--surface-3);">
                    <td class="px-4 py-2 font-mono text-xs">{{ zone }}</td>
                    <td
                      class="px-4 py-2 text-right font-mono tabular-nums"
                      :style="{ color: deltaColor(delta) }"
                    >
                      {{ formatDelta(delta) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <!-- Per coin delta -->
          <section v-if="Object.keys(perCoinDelta).length > 0">
            <p
              class="mb-3 text-[10px] font-medium uppercase"
              style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
            >
              Delta par pièce
            </p>
            <div
              class="overflow-hidden rounded-lg border"
              style="border-color: var(--surface-3); background: var(--surface);"
            >
              <table class="w-full text-sm">
                <thead>
                  <tr class="border-b" style="border-color: var(--surface-3); background: var(--surface-1);">
                    <th class="px-4 py-2 text-left text-[10px] uppercase" style="color: var(--ink-500);">eurio_id</th>
                    <th class="px-4 py-2 text-right text-[10px] uppercase" style="color: var(--ink-500);">ΔR@1</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(delta, eid) in perCoinDelta" :key="eid" class="border-b" style="border-color: var(--surface-3);">
                    <td class="px-4 py-2 font-mono text-xs">{{ eid }}</td>
                    <td
                      class="px-4 py-2 text-right font-mono tabular-nums"
                      :style="{ color: deltaColor(delta) }"
                    >
                      {{ formatDelta(delta) }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <!-- Per condition (axis) metrics -->
          <section v-if="benchmark && Object.keys(benchmark.per_condition ?? {}).length > 0">
            <p
              class="mb-3 text-[10px] font-medium uppercase"
              style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
            >
              Par axe de variabilité (photos réelles)
            </p>
            <PerConditionTable :per-condition="benchmark.per_condition ?? {}" />
          </section>
        </div>

        <!-- Notes + verdict override sidebar -->
        <aside class="space-y-6">
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
