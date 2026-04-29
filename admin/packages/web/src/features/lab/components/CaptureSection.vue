<script setup lang="ts">
// Section §2 of CohortDetailPage. Drives the capture loop:
//   1. Show capture coverage per coin (✅ / ⚠ / ❌)
//   2. Generate the delta CSV (writes ml/state/cohort_csvs/<name>.csv)
//   3. Display the adb push/pull commands
//   4. Trigger the sync endpoint to dispatch normalized files into
//      ml/datasets/<numista_id>/captures/
//
// FS-derived: every refresh re-stats the captures dirs. No SQL state.

import {
  useCaptureManifestQuery,
  useGenerateCsvMutation,
  useSyncCapturesMutation,
} from '@/features/lab/composables/useLabQueries'
import type {
  CohortCsvResult,
  CohortStatus,
  CohortSyncResult,
} from '@/features/lab/types'
import { AlertTriangle, Check, Copy, Download, Loader2, RefreshCw, X } from 'lucide-vue-next'
import { computed, ref, toRefs } from 'vue'

const props = defineProps<{
  cohortId: string
  cohortName: string
  cohortStatus: CohortStatus
}>()
const { cohortId } = toRefs(props)

const manifestQuery = useCaptureManifestQuery(cohortId)
const manifest = computed(() => manifestQuery.data.value ?? null)
const loading = computed(() => manifestQuery.isFetching.value)

const csvMut = useGenerateCsvMutation(cohortId)
const csvResult = computed<CohortCsvResult | null>(() => csvMut.data.value ?? null)
const csvBusy = computed(() => csvMut.isPending.value)

const syncMut = useSyncCapturesMutation(cohortId)
const syncResult = computed<CohortSyncResult | null>(() => syncMut.data.value ?? null)
const syncBusy = computed(() => syncMut.isPending.value)

const overwrite = ref(false)
const customPullDir = ref('')

const error = computed(() => {
  const e = manifestQuery.error.value
    || csvMut.error.value
    || syncMut.error.value
  return (e as Error | null)?.message ?? null
})

const isReadOnly = computed(() => props.cohortStatus !== 'draft')

function reload() {
  manifestQuery.refetch()
}

const expectedSteps = computed(() => manifest.value?.expected_steps ?? [])

const coverage = computed(() => {
  const m = manifest.value
  if (!m || m.total_coins === 0) return 0
  return m.fully_captured / m.total_coins
})

function coinIcon(c: { num_files: number; numista_id: number | null }, expected: number): 'ok' | 'warn' | 'miss' | 'unmapped' {
  if (c.numista_id == null) return 'unmapped'
  if (c.num_files === 0) return 'miss'
  if (c.num_files >= expected) return 'ok'
  return 'warn'
}

async function genCsv() {
  await csvMut.mutateAsync().catch(() => { /* surfaced via error computed */ })
}

function downloadCsv() {
  if (!csvResult.value) return
  const blob = new Blob([csvResult.value.csv_content], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${props.cohortName}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

async function copy(value: string) {
  try { await navigator.clipboard.writeText(value) } catch { /* ignore */ }
}

async function runSync() {
  await syncMut.mutateAsync({
    pull_dir: customPullDir.value.trim() || undefined,
    overwrite: overwrite.value,
  }).catch(() => { /* surfaced via error computed */ })
  // The mutation's onSuccess invalidates the manifest query; the
  // refetch is automatic. No need to call reload() manually.
}
</script>

<template>
  <section class="rounded-lg border" style="border-color: var(--surface-3); background: var(--surface);">
    <header class="flex items-center justify-between gap-4 border-b px-5 py-3" style="border-color: var(--surface-3);">
      <div>
        <p class="text-[10px] font-medium uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
          §2 Captures device
        </p>
        <h3 class="mt-0.5 font-display text-base italic" style="color: var(--ink);">
          Couverture canonique par pièce
        </h3>
      </div>
      <button
        class="flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs"
        style="border-color: var(--surface-3); color: var(--ink-500);"
        :disabled="loading"
        @click="reload"
      >
        <RefreshCw class="h-3 w-3" :class="loading ? 'animate-spin' : ''" />
        Rafraîchir
      </button>
    </header>

    <div class="flex flex-col gap-4 px-5 py-4">
      <!-- Canonicality warning -->
      <div
        class="flex items-start gap-2 rounded-md border-l-4 px-3 py-2 text-[12px]"
        style="border-color: var(--warning); background: color-mix(in srgb, var(--warning) 10%, var(--surface)); color: var(--ink);"
      >
        <AlertTriangle class="mt-0.5 h-3.5 w-3.5 flex-shrink-0" style="color: var(--warning);" />
        <div>
          <strong>Captures canoniques par pièce.</strong>
          Une fois prises, elles sont réutilisées par tous les cohorts contenant cette pièce.
          Pas de versioning v1 — modifier le protocole (angles, normalize, hardware) brise tous
          les benchmarks passés.
        </div>
      </div>

      <!-- Coverage bar -->
      <div v-if="manifest">
        <div class="mb-1.5 flex items-baseline justify-between text-xs">
          <span style="color: var(--ink);">
            <strong>{{ manifest.fully_captured }}</strong> / {{ manifest.total_coins }} coins capturés
            <span v-if="manifest.partial > 0" style="color: var(--warning);"> · {{ manifest.partial }} partiels</span>
            <span v-if="manifest.missing > 0" style="color: var(--danger);"> · {{ manifest.missing }} manquants</span>
          </span>
          <span class="font-mono" style="color: var(--ink-500);">{{ Math.round(coverage * 100) }}%</span>
        </div>
        <div class="h-2 overflow-hidden rounded-full" style="background: var(--surface-1);">
          <div
            class="h-full transition-all"
            :style="{ width: `${coverage * 100}%`, background: 'var(--success)' }"
          />
        </div>
      </div>

      <!-- Per-coin list -->
      <div v-if="manifest" class="grid grid-cols-1 gap-1 sm:grid-cols-2">
        <div
          v-for="c in manifest.per_coin"
          :key="c.eurio_id"
          class="flex items-center justify-between gap-2 rounded border px-2 py-1.5 text-[11px]"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <div class="flex min-w-0 items-center gap-1.5">
            <Check
              v-if="coinIcon(c, expectedSteps.length) === 'ok'"
              class="h-3 w-3"
              style="color: var(--success);"
            />
            <AlertTriangle
              v-else-if="coinIcon(c, expectedSteps.length) === 'warn'"
              class="h-3 w-3"
              style="color: var(--warning);"
            />
            <X
              v-else
              class="h-3 w-3"
              :style="{ color: c.numista_id == null ? 'var(--ink-400)' : 'var(--danger)' }"
            />
            <span class="truncate font-mono" style="color: var(--ink);">{{ c.eurio_id }}</span>
          </div>
          <div class="flex flex-shrink-0 items-center gap-2 font-mono" style="color: var(--ink-500);">
            <span v-if="c.numista_id == null" style="color: var(--ink-400);">no numista</span>
            <span v-else>{{ c.num_files }}/{{ expectedSteps.length }}</span>
          </div>
        </div>
      </div>

      <!-- Generate CSV -->
      <div v-if="!isReadOnly" class="flex flex-col gap-3">
        <div class="flex items-center gap-2">
          <button
            class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium"
            style="background: var(--indigo-700); color: white;"
            :disabled="csvBusy || (manifest?.missing ?? 0) + (manifest?.partial ?? 0) === 0"
            @click="genCsv"
          >
            <Loader2 v-if="csvBusy" class="h-3 w-3 animate-spin" />
            Générer CSV de capture (delta)
          </button>
          <button
            v-if="csvResult"
            class="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs"
            style="border-color: var(--surface-3); color: var(--ink);"
            @click="downloadCsv"
          >
            <Download class="h-3 w-3" />
            Télécharger
          </button>
        </div>

        <!-- Push / pull / sync flow -->
        <div
          v-if="csvResult"
          class="rounded-md border p-3"
          style="border-color: var(--surface-3); background: var(--surface-1);"
        >
          <p class="mb-2 text-[10px] uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            Étapes
          </p>
          <ol class="flex flex-col gap-2 text-[12px]" style="color: var(--ink);">
            <li>
              <strong>1.</strong> Push le CSV sur le téléphone
              <button
                class="ml-1 inline-flex items-center gap-1 rounded px-1 text-[10px]"
                style="background: var(--surface); color: var(--ink-500);"
                @click="copy(csvResult.push_command)"
              >
                <Copy class="h-2.5 w-2.5" /> copier
              </button>
              <pre class="mt-1 overflow-x-auto rounded bg-[var(--surface)] px-2 py-1 font-mono text-[10px]" style="color: var(--ink);">{{ csvResult.push_command }}</pre>
            </li>
            <li>
              <strong>2.</strong> Capture sur le téléphone (mode debug — relance l'app après le push)
            </li>
            <li>
              <strong>3.</strong> Pull les fichiers
              <button
                class="ml-1 inline-flex items-center gap-1 rounded px-1 text-[10px]"
                style="background: var(--surface); color: var(--ink-500);"
                @click="copy(csvResult.pull_command)"
              >
                <Copy class="h-2.5 w-2.5" /> copier
              </button>
              <pre class="mt-1 overflow-x-auto rounded bg-[var(--surface)] px-2 py-1 font-mono text-[10px]" style="color: var(--ink);">{{ csvResult.pull_command }}</pre>
            </li>
            <li>
              <strong>4.</strong> Synchronise — dispatche les fichiers normalisés vers
              <code class="font-mono text-[10px]">ml/datasets/&lt;numista_id&gt;/captures/</code>
              <div class="mt-1 flex flex-wrap items-center gap-2">
                <input
                  v-model="customPullDir"
                  type="text"
                  placeholder="debug_pull/<ts>/ (vide = dernier)"
                  class="flex-1 rounded border px-2 py-1 font-mono text-[10px]"
                  style="background: var(--surface); border-color: var(--surface-3); color: var(--ink);"
                />
                <label class="flex items-center gap-1 text-[10px]" style="color: var(--ink-500);">
                  <input v-model="overwrite" type="checkbox" />
                  écraser
                </label>
                <button
                  class="flex items-center gap-1 rounded-md px-3 py-1 text-xs font-medium"
                  style="background: var(--success); color: white;"
                  :disabled="syncBusy"
                  @click="runSync"
                >
                  <Loader2 v-if="syncBusy" class="h-3 w-3 animate-spin" />
                  Synchroniser
                </button>
              </div>
            </li>
          </ol>
          <p
            v-if="csvResult.skipped_no_numista.length > 0"
            class="mt-2 text-[10px]"
            style="color: var(--warning);"
          >
            ⚠ {{ csvResult.skipped_no_numista.length }} pièce(s) sans numista_id exclues du CSV.
          </p>
        </div>

        <!-- Sync result -->
        <div
          v-if="syncResult"
          class="rounded-md border p-3 text-[11px]"
          style="border-color: var(--success); background: color-mix(in srgb, var(--success) 8%, var(--surface));"
        >
          <p class="mb-1 text-[10px] uppercase" style="color: var(--success); letter-spacing: var(--tracking-eyebrow);">
            Sync OK · {{ syncResult.duration_s }}s
          </p>
          <p style="color: var(--ink);">
            <strong>{{ syncResult.normalized }}</strong> /  {{ syncResult.total_files }} normalisés ·
            <strong>{{ syncResult.captures_copied }}</strong> captures écrites
            <span v-if="syncResult.captures_skipped_existing > 0">
              · {{ syncResult.captures_skipped_existing }} skipped (existing)
            </span>
            <span v-if="syncResult.failures.length > 0" style="color: var(--danger);">
              · {{ syncResult.failures.length }} échecs
            </span>
          </p>
          <p v-if="syncResult.captures_unmapped_eurio_ids.length > 0" style="color: var(--warning);">
            ⚠ unmapped: {{ syncResult.captures_unmapped_eurio_ids.join(', ') }}
          </p>
        </div>
      </div>

      <p v-if="error" class="text-xs" style="color: var(--danger);">{{ error }}</p>
    </div>
  </section>
</template>
