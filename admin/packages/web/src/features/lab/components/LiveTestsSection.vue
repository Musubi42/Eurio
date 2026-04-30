<script setup lang="ts">
/**
 * §5 of IterationDetailPage — surfaces the on-device live test results.
 *
 * Flow: user runs the cohortTest APK, takes the prescribed snaps, then on
 * their dev machine runs `cohort-test:pull-tests ITERATION=<iid>` (the
 * command shown in the copy box below). That task pulls the JSONL from the
 * device and POSTs to /lab/cohorts/_/iterations/<iid>/live-tests/sync.
 *
 * Once synced, this section renders the per-coin × per-condition matrix and
 * the studio↔live delta — the metric that says whether the recipe holds up
 * outside the studio benchmark.
 */
import {
  useLiveTestsQuery,
  useSyncLiveTestsMutation,
} from '@/features/lab/composables/useLabQueries'
import type {
  LiveTestCondition,
  LiveTestEntry,
  LiveTestsReport,
} from '@/features/lab/types'
import { Check, Copy, Loader2, RefreshCw } from 'lucide-vue-next'
import { computed, ref } from 'vue'

const props = defineProps<{
  cohortId: string
  iterationId: string
}>()

const cohortId = computed(() => props.cohortId)
const iterationId = computed(() => props.iterationId)

const query = useLiveTestsQuery(cohortId, iterationId)
const sync = useSyncLiveTestsMutation(cohortId, iterationId)

const data = computed<LiveTestsReport | null>(() => query.data.value ?? null)
const summary = computed(() => data.value?.summary ?? null)
const conditions = computed<LiveTestCondition[]>(
  () => data.value?.conditions ?? ['bright', 'dim', 'tilt'],
)
const matrix = computed(() => data.value?.matrix ?? {})
const expectedCoins = computed(() => Object.keys(matrix.value).sort())

const pullCommand = computed(
  () =>
    `go-task -t app-android/Taskfile.yml cohort-test:pull-tests ITERATION=${
      iterationId.value
    }`,
)

const copied = ref(false)
async function copyCommand() {
  try {
    await navigator.clipboard.writeText(pullCommand.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch (e) {
    alert(`Copie impossible : ${(e as Error).message}`)
  }
}

async function handleSync() {
  try {
    const result = await sync.mutateAsync()
    if (result.parse_errors.length > 0) {
      alert(
        `Sync OK mais ${result.parse_errors.length} ligne(s) rejetée(s):\n` +
          result.parse_errors.slice(0, 5).join('\n'),
      )
    }
  } catch (e) {
    alert(`Sync échoué : ${(e as Error).message}`)
  }
}

function formatPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return (v * 100).toFixed(1) + '%'
}

function formatDelta(d: number | null | undefined): string {
  if (d == null) return '—'
  const pp = (d * 100).toFixed(1)
  const sign = d >= 0 ? '+' : ''
  return `${sign}${pp}pp`
}

/** Color for the delta badge — green if close to studio, red if diverging. */
function deltaColor(d: number | null | undefined): string {
  if (d == null) return 'var(--ink-400)'
  const abs = Math.abs(d)
  if (abs < 0.05) return 'var(--success, #16a34a)'
  if (abs < 0.15) return 'var(--warning, #d97706)'
  return 'var(--danger, #dc2626)'
}

function cellLabel(entry: LiveTestEntry | undefined): string {
  if (!entry) return '—'
  if (entry.error) return '✗ err'
  return entry.is_correct ? '✓' : '✗'
}

function cellTitle(entry: LiveTestEntry | undefined): string {
  if (!entry) return 'pas encore testé'
  const top1 = entry.predicted_top1 ?? '∅'
  const sim = entry.similarity_top1 != null ? entry.similarity_top1.toFixed(3) : '—'
  const err = entry.error ? `\nerror: ${entry.error}` : ''
  return `top-1: ${top1} (sim ${sim})\nexpected: ${entry.expected_eurio_id}${err}`
}

function cellColor(entry: LiveTestEntry | undefined): string {
  if (!entry) return 'var(--surface-3)'
  if (entry.error) return 'var(--danger, #dc2626)'
  return entry.is_correct ? 'var(--success, #16a34a)' : 'var(--danger, #dc2626)'
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
          Live tests
        </p>
        <p class="text-sm" style="color: var(--ink-300);">
          R@1 device sur les conditions prescrites — comparé au studio benchmark
        </p>
      </div>
      <button
        type="button"
        class="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs"
        style="border-color: var(--surface-3); background: var(--surface);"
        :disabled="sync.isPending.value"
        @click="handleSync"
      >
        <Loader2 v-if="sync.isPending.value" class="h-3.5 w-3.5 animate-spin" />
        <RefreshCw v-else class="h-3.5 w-3.5" />
        Sync depuis device
      </button>
    </div>

    <div
      v-if="query.isLoading.value"
      class="flex items-center gap-2 rounded-lg border p-4 text-sm"
      style="border-color: var(--surface-3); color: var(--ink-400);"
    >
      <Loader2 class="h-4 w-4 animate-spin" />
      Chargement…
    </div>

    <div
      v-else-if="query.isError.value"
      class="rounded-lg border p-4 text-sm"
      style="border-color: var(--surface-3); color: var(--danger, #dc2626);"
    >
      Erreur de chargement : {{ (query.error.value as Error)?.message }}
    </div>

    <div v-else-if="data" class="space-y-4">
      <!-- Status + pull command -->
      <div
        class="rounded-lg border p-4"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <p class="mb-2 text-xs" style="color: var(--ink-400);">
          {{ summary?.total ?? 0 }} test(s) sync.
          {{
            data.log_present
              ? `Log local présent (${data.log_path}).`
              : 'Pas encore de log local — fais d\'abord les snaps sur device.'
          }}
        </p>
        <p class="mb-2 text-xs" style="color: var(--ink-400);">
          Sur la machine connectée au device :
        </p>
        <div class="relative">
          <pre
            class="overflow-x-auto rounded-md p-3 text-xs"
            style="background: var(--ink-900); color: var(--ink-100); font-family: ui-monospace, SFMono-Regular, Menlo, monospace;"
          >{{ pullCommand }}</pre>
          <button
            type="button"
            class="absolute right-2 top-2 inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px]"
            style="border-color: var(--surface-3); background: var(--surface); color: var(--ink-200);"
            @click="copyCommand"
          >
            <Check v-if="copied" class="h-3.5 w-3.5" />
            <Copy v-else class="h-3.5 w-3.5" />
            {{ copied ? 'Copié' : 'Copier' }}
          </button>
        </div>
      </div>

      <!-- Summary banner -->
      <div
        v-if="summary && summary.total > 0"
        class="flex flex-wrap items-center gap-4 rounded-lg border p-4 text-sm"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <div>
          <p class="text-[10px] uppercase" style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);">Studio R@1</p>
          <p class="text-lg font-semibold">{{ formatPct(summary.studio_r_at_1) }}</p>
        </div>
        <div>
          <p class="text-[10px] uppercase" style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);">Live R@1</p>
          <p class="text-lg font-semibold">
            {{ formatPct(summary.recall_at_1) }}
            <span class="text-xs font-normal" style="color: var(--ink-400);">
              ({{ summary.correct }}/{{ summary.total }})
            </span>
          </p>
        </div>
        <div>
          <p class="text-[10px] uppercase" style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);">Delta</p>
          <p
            class="text-lg font-semibold"
            :style="{ color: deltaColor(summary.delta) }"
          >
            {{ formatDelta(summary.delta) }}
          </p>
        </div>
      </div>

      <!-- Matrix coin × condition -->
      <div
        v-if="expectedCoins.length > 0"
        class="overflow-x-auto rounded-lg border"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <table class="w-full text-sm">
          <thead>
            <tr style="background: var(--surface-2);">
              <th class="px-3 py-2 text-left text-[11px] uppercase" style="color: var(--ink-400);">Pièce</th>
              <th
                v-for="cond in conditions"
                :key="cond"
                class="px-3 py-2 text-center text-[11px] uppercase"
                style="color: var(--ink-400);"
              >
                {{ cond }}
              </th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="eid in expectedCoins"
              :key="eid"
              class="border-t"
              style="border-color: var(--surface-3);"
            >
              <td class="px-3 py-2 font-mono text-xs" style="color: var(--ink-200);">
                {{ eid }}
              </td>
              <td
                v-for="cond in conditions"
                :key="cond"
                class="px-3 py-2 text-center"
              >
                <span
                  class="inline-flex min-w-[3.5rem] items-center justify-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-white"
                  :style="{ background: cellColor(matrix[eid]?.[cond]) }"
                  :title="cellTitle(matrix[eid]?.[cond])"
                >
                  <span>{{ cellLabel(matrix[eid]?.[cond]) }}</span>
                  <span
                    v-if="matrix[eid]?.[cond]?.similarity_top1 != null"
                    class="opacity-80"
                  >
                    {{ matrix[eid]![cond]!.similarity_top1!.toFixed(2) }}
                  </span>
                </span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div
        v-else
        class="rounded-lg border p-4 text-sm"
        style="border-color: var(--surface-3); color: var(--ink-400);"
      >
        Aucun test sync pour le moment. Fais les snaps sur device puis lance la
        commande Sync ci-dessus.
      </div>
    </div>
  </div>
</template>
