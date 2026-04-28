<script setup lang="ts">
import {
  checkMlApi,
  estimateDuration,
  fetchActiveRun,
  fetchClassDetail,
  fetchRunDetail,
  fetchRunLogs,
  fetchRuns,
  fetchStaging,
  fetchTrainedClasses,
  ML_API,
  startRun,
  stageRemoval,
  unstageClass,
  unstageRemoval,
  usePoller,
  type ClassRef,
  type EstimateResponse,
  type ModelClassSummary,
  type TrainingRun,
} from '../composables/useTrainingApi'
import {
  AlertTriangle,
  Brain,
  Check,
  ChevronRight,
  Circle,
  Download,
  Layers,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  TrendingUp,
  Wifi,
  WifiOff,
  X,
} from 'lucide-vue-next'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

// ─── API status ────────────────────────────────────────────────────────

const apiStatus = ref<'checking' | 'online' | 'offline'>('checking')

// Keep the current status while we probe in background — flipping to 'checking'
// every heartbeat unmounts the whole v-else-if="'online'" subtree and produces
// a visible blink. Only resolve to 'online' or 'offline' based on the probe.
async function refreshApiStatus(opts: { showProbe?: boolean } = {}) {
  if (opts.showProbe) apiStatus.value = 'checking'
  const online = await checkMlApi()
  apiStatus.value = online ? 'online' : 'offline'
}

// ─── State ─────────────────────────────────────────────────────────────

const staged = ref<ClassRef[]>([])
const removal = ref<ClassRef[]>([])
const trainedClasses = ref<ModelClassSummary[]>([])
const activeRun = ref<TrainingRun | null>(null)
const runs = ref<TrainingRun[]>([])
const runsTotal = ref(0)
const estimate = ref<EstimateResponse | null>(null)
const launchLoading = ref(false)
const launchError = ref<string | null>(null)

// Run detail drawer
const selectedRun = ref<TrainingRun | null>(null)
const selectedRunLogs = ref<string[]>([])

// Class detail drawer
const selectedClass = ref<ModelClassSummary | null>(null)
const selectedClassHistory = ref<{
  run_id: string
  version: number
  status: string
  started_at: string | null
  finished_at: string | null
  recall_at_1: number | null
  n_train_images: number | null
  n_val_images: number | null
}[]>([])

// ─── Fetch helpers ─────────────────────────────────────────────────────

async function refreshStaging() {
  if (apiStatus.value !== 'online') return
  const resp = await fetchStaging()
  staged.value = resp.staged
  removal.value = resp.removal
}

async function refreshClasses() {
  if (apiStatus.value !== 'online') return
  const resp = await fetchTrainedClasses()
  trainedClasses.value = resp.items
}

async function refreshRuns() {
  if (apiStatus.value !== 'online') return
  const resp = await fetchRuns(30, 0)
  runs.value = resp.items
  runsTotal.value = resp.total
}

async function refreshActive() {
  if (apiStatus.value !== 'online') return
  activeRun.value = await fetchActiveRun()
}

async function refreshEstimate() {
  if (apiStatus.value !== 'online') return
  try {
    estimate.value = await estimateDuration(staged.value.length, removal.value.length)
  } catch {
    estimate.value = null
  }
}

// Recompute estimate when staged/removal changes
watch([() => staged.value.length, () => removal.value.length], refreshEstimate)

const activeRunLogs = ref<string[]>([])

// Unified poller for the active run: fetches /training/runs/active (which
// already carries steps + epoch + epochs_total) and, if a run is live, its log
// tail in parallel. /training/runs/:id detail (epochs array, per_class_metrics)
// is only populated after the run completes, so we don't need it during live
// monitoring — we fetch it on-demand when the user opens the run drawer.
const activePoller = usePoller(
  async () => {
    const active = await fetchActiveRun()
    if (!active) return { run: null as TrainingRun | null, lines: [] as string[] }
    const logs = await fetchRunLogs(active.id, 60)
    return { run: active, lines: logs.lines }
  },
  2500,
  ({ run, lines }) => {
    const wasActive = activeRun.value !== null
    activeRun.value = run
    activeRunLogs.value = lines
    if (wasActive && run === null) {
      activePoller.stop()
      void refreshRuns()
      void refreshClasses()
      void refreshStaging()
    }
  },
)

// ─── Lifecycle ─────────────────────────────────────────────────────────

let healthPoller: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await refreshApiStatus({ showProbe: true })
  if (apiStatus.value === 'online') {
    await Promise.all([
      refreshStaging(),
      refreshClasses(),
      refreshRuns(),
      refreshActive(),
      refreshEstimate(),
    ])
    if (activeRun.value) {
      activePoller.start()
    }
  }
  healthPoller = setInterval(async () => {
    const wasOffline = apiStatus.value !== 'online'
    await refreshApiStatus()
    if (wasOffline && apiStatus.value === 'online') {
      await Promise.all([refreshStaging(), refreshClasses(), refreshRuns(), refreshActive()])
    }
  }, 10_000)
})

onUnmounted(() => {
  if (healthPoller) clearInterval(healthPoller)
  activePoller.stop()
})

// ─── Actions ───────────────────────────────────────────────────────────

async function unstage(classId: string) {
  await unstageClass(classId)
  await refreshStaging()
}

async function stageClassForRemoval(cls: ModelClassSummary) {
  const confirmed = confirm(
    `Supprimer "${cls.class_id}" du modèle ?\n\n` +
    `Cela déclenchera un ré-entraînement complet sans cette classe. ` +
    `Les embeddings Supabase seront purgés. L'app Android continuera à identifier avec l'ancien modèle jusqu'au prochain déploiement.`,
  )
  if (!confirmed) return
  await stageRemoval([{ class_id: cls.class_id, class_kind: cls.class_kind }])
  await refreshStaging()
}

async function removeClassNoConfirm(cls: ModelClassSummary) {
  if (removalIds.value.has(cls.class_id)) return
  await stageRemoval([{ class_id: cls.class_id, class_kind: cls.class_kind }])
  await refreshStaging()
}

async function removeAllClasses() {
  const targets = trainedClasses.value.filter(
    c => !removalIds.value.has(c.class_id),
  )
  if (!targets.length) return
  await stageRemoval(
    targets.map(c => ({ class_id: c.class_id, class_kind: c.class_kind })),
  )
  await refreshStaging()
}

async function cancelRemoval(classId: string) {
  await unstageRemoval(classId)
  await refreshStaging()
}

async function launch() {
  launchLoading.value = true
  launchError.value = null
  try {
    const run = await startRun()
    activeRun.value = run
    staged.value = []
    removal.value = []
    activePoller.start()
    await refreshRuns()
  } catch (err) {
    launchError.value = err instanceof Error ? err.message : String(err)
  } finally {
    launchLoading.value = false
  }
}

async function openRunDetail(runId: string) {
  const [detail, logs] = await Promise.all([
    fetchRunDetail(runId),
    fetchRunLogs(runId, 0),
  ])
  selectedRun.value = detail
  selectedRunLogs.value = logs.lines
}

async function openClassDetail(cls: ModelClassSummary) {
  selectedClass.value = cls
  const detail = await fetchClassDetail(cls.class_id)
  selectedClassHistory.value = detail.runs
}

function closeRunDrawer() {
  selectedRun.value = null
  selectedRunLogs.value = []
}

function closeClassDrawer() {
  selectedClass.value = null
  selectedClassHistory.value = []
}

// ─── Derived ───────────────────────────────────────────────────────────

const removalIds = computed(() => new Set(removal.value.map(r => r.class_id)))

const currentModelVersion = computed(() => {
  const last = runs.value.find(r => r.status === 'completed')
  return last ? `v${last.version}-arcface` : null
})

const lastCompletedRun = computed(() => runs.value.find(r => r.status === 'completed') ?? null)

const isIdle = computed(() => activeRun.value === null)

// Re-running on the same class set (empty staging + empty removal) is allowed
// once there's a completed run — the runner resolves classes_after to
// classes_before in that case. Useful when iterating on training config
// (recipes, transforms, hyper-params) without changing the class set.
const canLaunch = computed(() =>
  apiStatus.value === 'online'
  && isIdle.value
  && (staged.value.length > 0 || removal.value.length > 0 || lastCompletedRun.value !== null),
)

const isRetrainSameClasses = computed(() =>
  staged.value.length === 0
  && removal.value.length === 0
  && lastCompletedRun.value !== null,
)

// ─── Formatting ────────────────────────────────────────────────────────

function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  const s = Math.round(seconds)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rem = s % 60
  if (m < 60) return rem === 0 ? `${m} min` : `${m} min ${rem}s`
  const h = Math.floor(m / 60)
  const mm = m % 60
  return `${h}h ${mm} min`
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('fr-FR', {
    dateStyle: 'short',
    timeStyle: 'short',
  })
}

function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  const diffMs = Date.now() - new Date(iso).getTime()
  const diffMin = Math.floor(diffMs / 60_000)
  if (diffMin < 1) return 'à l\'instant'
  if (diffMin < 60) return `il y a ${diffMin} min`
  const diffH = Math.floor(diffMin / 60)
  if (diffH < 24) return `il y a ${diffH}h`
  const diffD = Math.floor(diffH / 24)
  return `il y a ${diffD}j`
}

function formatPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

const stepStatusColor: Record<string, string> = {
  pending: 'var(--ink-400)',
  running: 'var(--indigo-700)',
  done: 'var(--success)',
  failed: 'var(--danger)',
  skipped: 'var(--ink-300)',
}

// ─── TFLite export (preserved) ────────────────────────────────────────

interface ExportStatus {
  running: boolean
  error: string | null
  tflite: { size_mb: number; compiled_at: string } | null
  compiled_classes: number
  available_classes: number
  trained_in_supabase: number
  delta: number
}

const exportStatus = ref<ExportStatus | null>(null)
const exportTriggered = ref(false)
const validateResult = ref<{ passed: boolean; output: string[] } | null>(null)
const validateLoading = ref(false)
const deployResult = ref<{ deployed: string[] } | null>(null)
const deployLoading = ref(false)
const uploadLoading = ref(false)
const uploadResult = ref<{ uploaded: { name: string; size_kb: number }[]; errors: { name: string; error: string }[] } | null>(null)

async function fetchExportStatus() {
  if (apiStatus.value !== 'online') return
  try {
    const resp = await fetch(`${ML_API}/export/status`)
    if (resp.ok) exportStatus.value = await resp.json()
  } catch {
    // ignore
  }
}

async function triggerExport() {
  exportTriggered.value = true
  try {
    const resp = await fetch(`${ML_API}/export/tflite`, { method: 'POST' })
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: 'Erreur export' }))
      alert(err.detail ?? 'Erreur export')
    }
    const poll = setInterval(async () => {
      await fetchExportStatus()
      if (exportStatus.value && !exportStatus.value.running) {
        clearInterval(poll)
        exportTriggered.value = false
      }
    }, 2000)
  } catch {
    exportTriggered.value = false
  }
}

async function validateTFLite() {
  validateLoading.value = true
  validateResult.value = null
  try {
    const resp = await fetch(`${ML_API}/export/validate`, { method: 'POST' })
    if (resp.ok) validateResult.value = await resp.json()
  } finally {
    validateLoading.value = false
  }
}

async function deployToAndroid() {
  deployLoading.value = true
  deployResult.value = null
  try {
    const resp = await fetch(`${ML_API}/export/deploy`, { method: 'POST' })
    if (resp.ok) {
      deployResult.value = await resp.json()
      await fetchExportStatus()
    }
  } finally {
    deployLoading.value = false
  }
}

async function uploadToSupabase() {
  uploadLoading.value = true
  uploadResult.value = null
  try {
    const resp = await fetch(`${ML_API}/export/upload-model`, { method: 'POST' })
    if (resp.ok) uploadResult.value = await resp.json()
  } finally {
    uploadLoading.value = false
  }
}

onMounted(fetchExportStatus)
</script>

<template>
  <div class="p-8">
    <!-- ═══ Header ═══ -->
    <header class="mb-6 flex items-start justify-between">
      <div>
        <h1 class="font-display text-2xl italic font-semibold"
            style="color: var(--indigo-700);">
          Entraînement du modèle
        </h1>
        <p class="mt-0.5 text-sm" style="color: var(--ink-500);">
          ArcFace · {{ trainedClasses.length }} classes · pipeline non-incrémental
        </p>
      </div>
      <div class="flex items-center gap-3">
        <div
          class="flex items-center gap-2 rounded-full border px-3 py-1 text-xs"
          :style="{
            borderColor: apiStatus === 'online' ? 'var(--success)' : 'var(--danger)',
            color: apiStatus === 'online' ? 'var(--success)' : 'var(--danger)',
            background: apiStatus === 'online'
              ? 'color-mix(in srgb, var(--success) 6%, var(--surface))'
              : 'color-mix(in srgb, var(--danger) 6%, var(--surface))',
          }"
        >
          <Wifi v-if="apiStatus === 'online'" class="h-3 w-3" />
          <WifiOff v-else class="h-3 w-3" />
          {{ apiStatus === 'online' ? 'ML API connectée' : 'ML API hors-ligne' }}
        </div>
      </div>
    </header>

    <!-- ═══ Offline banner ═══ -->
    <div
      v-if="apiStatus === 'offline'"
      class="mb-6 rounded-lg border-2 border-dashed px-5 py-6 text-center"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface));"
    >
      <WifiOff class="mx-auto mb-2 h-6 w-6" style="color: var(--danger);" />
      <p class="text-sm font-medium" style="color: var(--danger);">
        ML API non jointe (http://localhost:8042)
      </p>
      <p class="mt-1 text-xs" style="color: var(--ink-500);">
        Lance <code style="background: var(--surface-1); padding: 1px 4px; border-radius: 3px;">go-task ml:api</code>
        puis clique sur réessayer.
      </p>
      <button
        class="mt-3 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium"
        style="background: var(--ink); color: var(--surface);"
        @click="refreshApiStatus({ showProbe: true })"
      >
        <RefreshCw class="h-3 w-3" /> Réessayer
      </button>
    </div>

    <template v-else-if="apiStatus === 'online'">
      <!-- ═══ Current model card ═══ -->
      <section class="mb-6">
        <div
          class="flex items-center justify-between rounded-lg border px-5 py-4"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <div class="flex items-center gap-4">
            <div
              class="flex h-11 w-11 items-center justify-center rounded-full"
              style="background: color-mix(in srgb, var(--indigo-700) 10%, var(--surface-1));"
            >
              <Brain class="h-5 w-5" style="color: var(--indigo-700);" />
            </div>
            <div>
              <p class="font-mono text-xs uppercase tracking-wider" style="color: var(--ink-500);">
                Modèle courant
              </p>
              <p class="font-display text-xl font-semibold" style="color: var(--ink);">
                {{ currentModelVersion ?? 'Pas encore entraîné' }}
              </p>
            </div>
          </div>
          <div class="flex items-center gap-6 text-right">
            <div>
              <p class="font-mono text-xs uppercase tracking-wider" style="color: var(--ink-500);">
                Classes
              </p>
              <p class="font-mono text-lg font-medium" style="color: var(--ink);">
                {{ trainedClasses.length }}
              </p>
            </div>
            <div>
              <p class="font-mono text-xs uppercase tracking-wider" style="color: var(--ink-500);">
                R@1
              </p>
              <p class="font-mono text-lg font-medium" style="color: var(--ink);">
                {{ formatPct(lastCompletedRun?.recall_at_1) }}
              </p>
            </div>
            <div>
              <p class="font-mono text-xs uppercase tracking-wider" style="color: var(--ink-500);">
                Dernier run
              </p>
              <p class="text-sm font-medium" style="color: var(--ink);">
                {{ lastCompletedRun ? formatRelative(lastCompletedRun.finished_at) : '—' }}
              </p>
            </div>
            <div>
              <p class="font-mono text-xs uppercase tracking-wider" style="color: var(--ink-500);">
                Durée
              </p>
              <p class="text-sm font-medium" style="color: var(--ink);">
                {{ lastCompletedRun && lastCompletedRun.epoch_duration_median_sec
                  ? formatDuration(lastCompletedRun.epoch_duration_median_sec * (Number(lastCompletedRun.config?.epochs) || 40))
                  : '—' }}
              </p>
            </div>
          </div>
        </div>
      </section>

      <!-- ═══ Warning banner ═══ -->
      <section
        class="mb-6 flex items-start gap-3 rounded-lg border px-5 py-3"
        style="border-color: var(--warning); background: color-mix(in srgb, var(--warning) 6%, var(--surface));"
      >
        <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" style="color: var(--warning);" />
        <div class="text-sm leading-snug" style="color: var(--ink);">
          <strong>Ajouter ou retirer un design = ré-entraînement complet.</strong>
          ArcFace ne permet pas d'incrémental : toutes les classes existantes seront ré-entraînées en même temps que les nouvelles. Les embeddings Supabase sont écrasés.
        </div>
      </section>

      <!-- ═══ Active run ═══ -->
      <section v-if="activeRun" class="mb-6">
        <h2 class="mb-3 text-xs font-medium uppercase tracking-wider" style="color: var(--ink-500);">
          Entraînement en cours · v{{ activeRun.version }}
        </h2>
        <div
          class="rounded-lg border px-5 py-4"
          style="border-color: var(--indigo-700); background: color-mix(in srgb, var(--indigo-700) 4%, var(--surface));"
        >
          <!-- Step progress -->
          <div class="mb-4 flex flex-wrap items-center gap-2">
            <div
              v-for="step in activeRun.steps ?? []"
              :key="step.step_index"
              class="flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium"
              :style="{
                borderColor: stepStatusColor[step.status],
                color: stepStatusColor[step.status],
                background: step.status === 'running'
                  ? 'color-mix(in srgb, var(--indigo-700) 12%, var(--surface))'
                  : 'var(--surface)',
              }"
            >
              <Loader2 v-if="step.status === 'running'" class="h-3 w-3 animate-spin" />
              <Check v-else-if="step.status === 'done'" class="h-3 w-3" />
              <X v-else-if="step.status === 'failed'" class="h-3 w-3" />
              <Circle v-else class="h-3 w-3" />
              {{ step.name }}
              <span v-if="step.detail" class="opacity-70">· {{ step.detail }}</span>
            </div>
          </div>

          <!-- Metrics row -->
          <div class="flex items-center gap-6 border-t pt-3" style="border-color: var(--surface-2);">
            <div>
              <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Epoch
              </p>
              <p class="font-mono text-sm font-medium" style="color: var(--ink);">
                {{ activeRun.epoch ?? 0 }} / {{ activeRun.epochs_total ?? (activeRun.config?.epochs ?? 40) }}
              </p>
            </div>
            <div>
              <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Loss
              </p>
              <p class="font-mono text-sm font-medium" style="color: var(--ink);">
                {{ activeRun.loss?.toFixed(4) ?? '—' }}
              </p>
            </div>
            <div>
              <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                R@1
              </p>
              <p class="font-mono text-sm font-medium" style="color: var(--ink);">
                {{ formatPct(activeRun.recall_at_1) }}
              </p>
            </div>
            <div class="flex-1 text-right">
              <p class="text-xs" style="color: var(--ink-500);">
                Démarré {{ formatRelative(activeRun.started_at) }}
              </p>
            </div>
          </div>

          <!-- Log tail (collapsible) -->
          <details class="mt-3">
            <summary class="cursor-pointer text-xs" style="color: var(--ink-500);">
              Logs ({{ activeRunLogs.length }} lignes)
            </summary>
            <div
              class="mt-2 max-h-48 overflow-y-auto rounded-md border p-2 font-mono text-[10px] leading-snug"
              style="border-color: var(--surface-3); background: var(--surface-1); color: var(--ink-500);"
            >
              <p v-for="(line, i) in activeRunLogs.slice(-60)" :key="i" class="whitespace-pre">
                {{ line }}
              </p>
            </div>
          </details>
        </div>
      </section>

      <!-- ═══ Staging + Launch ═══ -->
      <section class="mb-6">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-xs font-medium uppercase tracking-wider" style="color: var(--ink-500);">
            Prochain entraînement
          </h2>
          <p v-if="estimate" class="text-xs" style="color: var(--ink-500);">
            Estimation :
            <strong style="color: var(--ink);">{{ formatDuration(estimate.estimated_sec) }}</strong>
            · {{ estimate.current_classes }} → {{ estimate.new_classes }} classes
            <span v-if="estimate.basis === 'default'" class="ml-1 opacity-70">(estimation par défaut)</span>
          </p>
        </div>

        <div class="grid gap-4 md:grid-cols-2">
          <!-- Trained classes -->
          <div
            class="rounded-lg border px-4 py-3"
            style="border-color: var(--surface-3); background: var(--surface);"
          >
            <div class="mb-2 flex items-center justify-between">
              <p class="text-xs font-medium" style="color: var(--ink);">
                Classes actuelles · {{ trainedClasses.length }}
              </p>
              <div class="flex items-center gap-2">
                <button
                  v-if="trainedClasses.length > 0"
                  class="rounded px-2 py-0.5 font-mono text-[10px] uppercase hover:opacity-80"
                  :style="{
                    border: '1px solid var(--danger)',
                    color: 'var(--danger)',
                    background: 'transparent',
                  }"
                  :title="'Stage toutes les classes pour suppression'"
                  @click="removeAllClasses"
                >
                  Tout retirer
                </button>
                <span class="font-mono text-[10px]" style="color: var(--ink-400);">
                  entraînées
                </span>
              </div>
            </div>
            <div
              v-if="trainedClasses.length === 0"
              class="py-6 text-center text-xs"
              style="color: var(--ink-400);"
            >
              Aucune classe entraînée
            </div>
            <div v-else class="flex flex-wrap gap-1.5">
              <div
                v-for="cls in trainedClasses"
                :key="cls.class_id"
                class="flex items-center rounded-md border font-mono text-[10px] transition-colors"
                :style="{
                  borderColor: removalIds.has(cls.class_id) ? 'var(--danger)' : 'var(--surface-3)',
                  background: removalIds.has(cls.class_id)
                    ? 'color-mix(in srgb, var(--danger) 12%, var(--surface))'
                    : 'var(--surface)',
                  color: removalIds.has(cls.class_id) ? 'var(--danger)' : 'var(--ink)',
                }"
              >
                <button
                  class="flex items-center gap-1 px-2 py-1"
                  :style="{
                    textDecoration: removalIds.has(cls.class_id) ? 'line-through' : 'none',
                  }"
                  :title="`${cls.class_id} (${cls.class_kind})`"
                  @click="openClassDetail(cls)"
                >
                  <Layers v-if="cls.class_kind === 'design_group_id'" class="h-2.5 w-2.5" />
                  {{ cls.class_id }}
                </button>
                <button
                  v-if="!removalIds.has(cls.class_id)"
                  class="flex items-center px-1.5 py-1 hover:opacity-70"
                  :style="{ color: 'var(--ink-400)' }"
                  :title="`Retirer ${cls.class_id} du modèle`"
                  @click.stop="removeClassNoConfirm(cls)"
                >
                  <X class="h-2.5 w-2.5" />
                </button>
                <button
                  v-else
                  class="flex items-center px-1.5 py-1 hover:opacity-70"
                  :style="{ color: 'var(--danger)' }"
                  :title="`Annuler la suppression de ${cls.class_id}`"
                  @click.stop="cancelRemoval(cls.class_id)"
                >
                  <X class="h-2.5 w-2.5" />
                </button>
              </div>
            </div>
          </div>

          <!-- Staged + removal -->
          <div
            class="rounded-lg border px-4 py-3"
            style="border-color: var(--indigo-700); background: color-mix(in srgb, var(--indigo-700) 3%, var(--surface));"
          >
            <div class="mb-2 flex items-center justify-between">
              <p class="text-xs font-medium" style="color: var(--indigo-700);">
                Modifications staged
              </p>
              <span class="font-mono text-[10px]" style="color: var(--ink-400);">
                +{{ staged.length }} / -{{ removal.length }}
              </span>
            </div>

            <div v-if="staged.length === 0 && removal.length === 0" class="py-6 text-center">
              <p class="text-xs" style="color: var(--ink-400);">
                Aucune modification staged.
              </p>
              <router-link
                to="/coins"
                class="mt-2 inline-flex items-center gap-1 text-xs underline"
                style="color: var(--indigo-700);"
              >
                Ajouter depuis /coins →
              </router-link>
            </div>

            <div v-else class="space-y-2">
              <div v-if="staged.length > 0">
                <p class="mb-1 font-mono text-[10px] uppercase" style="color: var(--success);">
                  À ajouter ({{ staged.length }})
                </p>
                <div class="flex flex-wrap gap-1.5">
                  <div
                    v-for="c in staged"
                    :key="c.class_id"
                    class="flex items-center gap-1 rounded-md border px-2 py-1 font-mono text-[10px]"
                    :style="{
                      borderColor: 'var(--success)',
                      background: 'color-mix(in srgb, var(--success) 10%, var(--surface))',
                      color: 'var(--ink)',
                    }"
                  >
                    <Plus class="h-2.5 w-2.5" :style="{ color: 'var(--success)' }" />
                    <Layers v-if="c.class_kind === 'design_group_id'" class="h-2.5 w-2.5" />
                    {{ c.class_id }}
                    <button
                      class="ml-1 rounded hover:opacity-70"
                      :title="`Retirer ${c.class_id} du staging`"
                      @click="unstage(c.class_id)"
                    >
                      <X class="h-2.5 w-2.5" />
                    </button>
                  </div>
                </div>
              </div>

              <div v-if="removal.length > 0">
                <p class="mb-1 font-mono text-[10px] uppercase" style="color: var(--danger);">
                  À retirer ({{ removal.length }})
                </p>
                <div class="flex flex-wrap gap-1.5">
                  <div
                    v-for="c in removal"
                    :key="c.class_id"
                    class="flex items-center gap-1 rounded-md border px-2 py-1 font-mono text-[10px]"
                    :style="{
                      borderColor: 'var(--danger)',
                      background: 'color-mix(in srgb, var(--danger) 10%, var(--surface))',
                      color: 'var(--ink)',
                    }"
                  >
                    <Trash2 class="h-2.5 w-2.5" :style="{ color: 'var(--danger)' }" />
                    <Layers v-if="c.class_kind === 'design_group_id'" class="h-2.5 w-2.5" />
                    {{ c.class_id }}
                    <button
                      class="ml-1 rounded hover:opacity-70"
                      :title="`Annuler la suppression de ${c.class_id}`"
                      @click="cancelRemoval(c.class_id)"
                    >
                      <X class="h-2.5 w-2.5" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Launch bar -->
        <div class="mt-4 flex items-center justify-end gap-3">
          <p v-if="launchError" class="text-xs" style="color: var(--danger);">
            {{ launchError }}
          </p>
          <button
            class="flex items-center gap-2 rounded-md px-5 py-2.5 text-sm font-medium transition-all"
            :style="{
              background: canLaunch ? 'var(--indigo-700)' : 'var(--surface-2)',
              color: canLaunch ? 'white' : 'var(--ink-400)',
              cursor: canLaunch ? 'pointer' : 'not-allowed',
              opacity: launchLoading ? '0.7' : '1',
            }"
            :disabled="!canLaunch || launchLoading"
            @click="launch"
          >
            <Loader2 v-if="launchLoading" class="h-4 w-4 animate-spin" />
            <Play v-else class="h-4 w-4" />
            {{
              launchLoading
                ? 'Démarrage…'
                : activeRun
                  ? 'Entraînement en cours'
                  : isRetrainSameClasses
                    ? 'Re-entraîner sur les mêmes classes'
                    : 'Lancer l\'entraînement'
            }}
          </button>
        </div>
      </section>

      <!-- ═══ History ═══ -->
      <section class="mb-6">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-xs font-medium uppercase tracking-wider" style="color: var(--ink-500);">
            Historique · {{ runsTotal }} run{{ runsTotal > 1 ? 's' : '' }}
          </h2>
        </div>
        <div
          v-if="runs.length === 0"
          class="rounded-lg border-2 border-dashed py-8 text-center"
          style="border-color: var(--surface-3); color: var(--ink-400);"
        >
          <p class="text-sm">Aucun run dans l'historique.</p>
        </div>
        <div
          v-else
          class="overflow-hidden rounded-lg border"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b" style="border-color: var(--surface-3);">
                <th class="px-4 py-2 text-left font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                  Version
                </th>
                <th class="px-4 py-2 text-left font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                  Date
                </th>
                <th class="px-4 py-2 text-right font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                  Δ classes
                </th>
                <th class="px-4 py-2 text-right font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                  Après
                </th>
                <th class="px-4 py-2 text-right font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                  Durée
                </th>
                <th class="px-4 py-2 text-right font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                  R@1
                </th>
                <th class="px-4 py-2 text-left font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                  Statut
                </th>
                <th class="w-4"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in runs"
                :key="r.id"
                class="cursor-pointer border-b transition-colors hover:bg-[color-mix(in_srgb,var(--indigo-700)_3%,var(--surface))]"
                style="border-color: var(--surface-2);"
                @click="openRunDetail(r.id)"
              >
                <td class="px-4 py-2 font-mono text-xs" style="color: var(--ink);">
                  v{{ r.version }}
                </td>
                <td class="px-4 py-2 text-xs" style="color: var(--ink-500);">
                  {{ formatDate(r.started_at) }}
                </td>
                <td class="px-4 py-2 text-right font-mono text-xs">
                  <span v-if="(r.n_added ?? 0) > 0" style="color: var(--success);">
                    +{{ r.n_added }}
                  </span>
                  <span v-if="(r.n_added ?? 0) > 0 && (r.n_removed ?? 0) > 0" class="mx-1" style="color: var(--ink-400);">/</span>
                  <span v-if="(r.n_removed ?? 0) > 0" style="color: var(--danger);">
                    -{{ r.n_removed }}
                  </span>
                  <span v-if="(r.n_added ?? 0) === 0 && (r.n_removed ?? 0) === 0" style="color: var(--ink-400);">
                    —
                  </span>
                </td>
                <td class="px-4 py-2 text-right font-mono text-xs" style="color: var(--ink);">
                  {{ r.n_after ?? '—' }}
                </td>
                <td class="px-4 py-2 text-right font-mono text-xs" style="color: var(--ink-500);">
                  <template v-if="r.started_at && r.finished_at">
                    {{ formatDuration((new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 1000) }}
                  </template>
                  <template v-else>—</template>
                </td>
                <td class="px-4 py-2 text-right font-mono text-xs" style="color: var(--ink);">
                  {{ formatPct(r.recall_at_1) }}
                </td>
                <td class="px-4 py-2 text-xs">
                  <span
                    class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
                    :style="{
                      background: r.status === 'completed'
                        ? 'color-mix(in srgb, var(--success) 12%, var(--surface))'
                        : r.status === 'failed'
                          ? 'color-mix(in srgb, var(--danger) 12%, var(--surface))'
                          : r.status === 'running'
                            ? 'color-mix(in srgb, var(--indigo-700) 12%, var(--surface))'
                            : 'var(--surface-1)',
                      color: r.status === 'completed'
                        ? 'var(--success)'
                        : r.status === 'failed'
                          ? 'var(--danger)'
                          : r.status === 'running'
                            ? 'var(--indigo-700)'
                            : 'var(--ink-500)',
                    }"
                  >
                    {{ r.status }}
                  </span>
                </td>
                <td class="pr-3">
                  <ChevronRight class="h-3 w-3" style="color: var(--ink-400);" />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ═══ Export TFLite (preserved) ═══ -->
      <section v-if="exportStatus" class="mb-6">
        <h2 class="mb-3 text-xs font-medium uppercase tracking-wider" style="color: var(--ink-500);">
          Export TFLite
        </h2>
        <div
          class="rounded-lg border px-5 py-4"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <div class="flex items-center justify-between">
            <div>
              <div class="flex items-center gap-3">
                <Download class="h-4 w-4" style="color: var(--ink-400);" />
                <div>
                  <p class="text-sm font-medium" style="color: var(--ink);">Modèle Android</p>
                  <p class="text-xs" style="color: var(--ink-500);">
                    <template v-if="exportStatus.tflite">
                      {{ exportStatus.tflite.size_mb }} MB · compilé {{ formatRelative(exportStatus.tflite.compiled_at) }} · {{ exportStatus.compiled_classes }} classes
                    </template>
                    <template v-else>Aucun fichier TFLite compilé</template>
                  </p>
                </div>
              </div>
              <div v-if="exportStatus.delta > 0" class="ml-7 mt-2">
                <span
                  class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
                  style="background: color-mix(in srgb, var(--warning) 12%, var(--surface)); color: var(--warning);"
                >
                  <TrendingUp class="h-2.5 w-2.5" />
                  {{ exportStatus.delta }} design{{ exportStatus.delta > 1 ? 's' : '' }} non compilé{{ exportStatus.delta > 1 ? 's' : '' }}
                </span>
                <span class="ml-2 text-[10px]" style="color: var(--ink-400);">
                  {{ exportStatus.available_classes }} disponibles · {{ exportStatus.compiled_classes }} dans le TFLite
                </span>
              </div>
            </div>
            <button
              class="flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium transition-all"
              :style="{
                background: exportTriggered || exportStatus.running ? 'var(--surface-2)' : 'var(--indigo-700)',
                color: exportTriggered || exportStatus.running ? 'var(--ink-400)' : 'white',
                cursor: exportTriggered || exportStatus.running ? 'not-allowed' : 'pointer',
              }"
              :disabled="exportTriggered || exportStatus.running"
              @click="triggerExport"
            >
              <Loader2 v-if="exportTriggered || exportStatus.running" class="h-3.5 w-3.5 animate-spin" />
              <Download v-else class="h-3.5 w-3.5" />
              {{ exportTriggered || exportStatus.running ? 'Compilation…' : 'Compiler TFLite' }}
            </button>
          </div>

          <div class="mt-4 flex flex-wrap items-center gap-2 border-t pt-4" style="border-color: var(--surface-2);">
            <button
              class="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors hover:border-current"
              style="border-color: var(--surface-3); color: var(--ink-500);"
              :disabled="validateLoading"
              @click="validateTFLite"
            >
              <Loader2 v-if="validateLoading" class="h-3 w-3 animate-spin" />
              <Check v-else class="h-3 w-3" />
              {{ validateLoading ? 'Validation…' : 'Valider TFLite' }}
            </button>
            <button
              class="flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors hover:border-current"
              style="border-color: var(--surface-3); color: var(--indigo-700);"
              :disabled="deployLoading"
              @click="deployToAndroid"
            >
              <Loader2 v-if="deployLoading" class="h-3 w-3 animate-spin" />
              <Download v-else class="h-3 w-3" />
              {{ deployLoading ? 'Déploiement…' : 'Déployer vers Android' }}
            </button>
            <div class="h-4 w-px" style="background: var(--surface-3);" />
            <button
              class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all"
              :style="{
                background: uploadResult && !uploadResult.errors.length ? 'var(--success)' : 'var(--indigo-700)',
                color: 'white',
                opacity: uploadLoading ? '0.7' : '1',
              }"
              :disabled="uploadLoading"
              @click="uploadToSupabase"
            >
              <Loader2 v-if="uploadLoading" class="h-3 w-3 animate-spin" />
              <Check v-else-if="uploadResult && !uploadResult.errors.length" class="h-3 w-3" />
              <Download v-else class="h-3 w-3" />
              {{ uploadLoading ? 'Upload…' : uploadResult ? 'Synchronisé' : 'Upload Supabase' }}
            </button>
            <span v-if="deployResult" class="text-xs font-medium" style="color: var(--success);">
              {{ deployResult.deployed.length }} fichiers déployés
            </span>
          </div>

          <div
            v-if="uploadResult"
            class="mt-3 rounded-md border px-3 py-2"
            :style="{
              borderColor: uploadResult.errors.length ? 'var(--warning)' : 'var(--success)',
              background: uploadResult.errors.length
                ? 'color-mix(in srgb, var(--warning) 6%, var(--surface))'
                : 'color-mix(in srgb, var(--success) 6%, var(--surface))',
            }"
          >
            <p class="text-xs font-medium" :style="{ color: uploadResult.errors.length ? 'var(--warning)' : 'var(--success)' }">
              {{ uploadResult.uploaded.length }} fichier{{ uploadResult.uploaded.length > 1 ? 's' : '' }} uploadé{{ uploadResult.uploaded.length > 1 ? 's' : '' }}
            </p>
            <div class="mt-1 space-y-0.5">
              <p v-for="f in uploadResult.uploaded" :key="f.name" class="font-mono text-[10px]" style="color: var(--ink-500);">
                {{ f.name }} ({{ f.size_kb }} KB)
              </p>
            </div>
            <div v-if="uploadResult.errors.length" class="mt-2">
              <p v-for="e in uploadResult.errors" :key="e.name" class="text-[10px]" style="color: var(--danger);">
                {{ e.name }}: {{ e.error }}
              </p>
            </div>
          </div>

          <div
            v-if="validateResult"
            class="mt-3 rounded-md border px-3 py-2"
            :style="{
              borderColor: validateResult.passed ? 'var(--success)' : 'var(--danger)',
              background: validateResult.passed
                ? 'color-mix(in srgb, var(--success) 6%, var(--surface))'
                : 'color-mix(in srgb, var(--danger) 6%, var(--surface))',
            }"
          >
            <p class="text-xs font-medium" :style="{ color: validateResult.passed ? 'var(--success)' : 'var(--danger)' }">
              {{ validateResult.passed ? 'Validation réussie' : 'Validation échouée' }}
            </p>
            <div class="mt-1 max-h-32 overflow-y-auto font-mono text-[10px]" style="color: var(--ink-500);">
              <p v-for="(line, i) in validateResult.output.filter(l => l.trim())" :key="i">
                {{ line }}
              </p>
            </div>
          </div>

          <div
            v-if="exportStatus.error"
            class="mt-3 rounded-md px-3 py-2 text-xs"
            style="background: color-mix(in srgb, var(--danger) 8%, var(--surface)); color: var(--danger);"
          >
            {{ exportStatus.error }}
          </div>
        </div>
      </section>

      <!-- ═══ Cheat sheet : commandes CLI post-training ═══ -->
      <section class="mb-6">
        <h2 class="mb-3 text-xs font-medium uppercase tracking-wider" style="color: var(--ink-500);">
          Workflow CLI · post-training
        </h2>
        <div
          class="rounded-lg border px-5 py-4 text-xs"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <p class="mb-3" style="color: var(--ink-500);">
            Une fois le run d'entraînement terminé (status <span class="font-mono">completed</span>),
            enchaîne ces commandes dans l'ordre depuis la racine du repo pour bundler le modèle
            sur le téléphone :
          </p>
          <div class="space-y-3">
            <div class="flex flex-col gap-1">
              <code class="font-mono text-[11px] rounded px-2 py-1 w-fit" style="background: var(--surface-2); color: var(--indigo-700);">
                go-task ml:export
              </code>
              <p style="color: var(--ink-500);">
                Convertit <span class="font-mono">checkpoints/best_model.pth</span> (PyTorch)
                en <span class="font-mono">output/eurio_embedder_v1.tflite</span>. Lit le checkpoint
                ArcFace, exporte le backbone + head en TFLite via ONNX. Pas de re-training.
              </p>
            </div>
            <div class="flex flex-col gap-1">
              <code class="font-mono text-[11px] rounded px-2 py-1 w-fit" style="background: var(--surface-2); color: var(--indigo-700);">
                go-task ml:validate
              </code>
              <p style="color: var(--ink-500);">
                Compare embeddings PyTorch vs TFLite sur les images sources. Cosine sim doit être ≥ 0.99.
                Sanity check de conversion — ne mesure PAS la qualité du modèle, juste que la TFLite
                produit la même chose que le PyTorch original.
              </p>
            </div>
            <div class="flex flex-col gap-1">
              <code class="font-mono text-[11px] rounded px-2 py-1 w-fit" style="background: var(--surface-2); color: var(--indigo-700);">
                go-task ml:validate-per-class
              </code>
              <p style="color: var(--ink-500);">
                R@1 par classe sur 50 augmentations à la volée (recette de zone + rotation 0–360°).
                C'est la VRAIE éval qualité — combien de scans simulés sont correctement classés
                via les prototypes ArcFace déployés. Tourne aussi automatiquement en step 5 du run
                ; cette commande est pour la rejouer hors run.
              </p>
            </div>
            <div class="flex flex-col gap-1">
              <code class="font-mono text-[11px] rounded px-2 py-1 w-fit" style="background: var(--surface-2); color: var(--indigo-700);">
                go-task ml:deploy
              </code>
              <p style="color: var(--ink-500);">
                Copie le TFLite + <span class="font-mono">model_meta.json</span> +
                <span class="font-mono">coin_embeddings.json</span> (centroïdes) vers
                <span class="font-mono">app-android/src/main/assets/</span>. C'est ce qui finit dans l'APK.
              </p>
            </div>
            <div class="flex flex-col gap-1">
              <code class="font-mono text-[11px] rounded px-2 py-1 w-fit" style="background: var(--surface-2); color: var(--indigo-700);">
                go-task android:snapshot
              </code>
              <p style="color: var(--ink-500);">
                Refresh <span class="font-mono">catalog_snapshot.json</span> depuis Supabase
                (toutes les pièces du catalogue, leurs noms, années, URLs photos). À refaire
                quand le catalogue Supabase a changé, sinon les nouvelles pièces n'apparaîtront
                pas dans le vault Android.
              </p>
            </div>
            <div class="flex flex-col gap-1">
              <code class="font-mono text-[11px] rounded px-2 py-1 w-fit" style="background: var(--surface-2); color: var(--indigo-700);">
                go-task android:install
              </code>
              <p style="color: var(--ink-500);">
                Build l'APK debug + push sur le device connecté en USB / Wi-Fi. Combine
                <span class="font-mono">build</span> + <span class="font-mono">installDebug</span>
                Gradle. Le téléphone démarre le nouvel APK avec les assets tout frais.
              </p>
            </div>
          </div>
          <div class="mt-4 rounded border-l-2 px-3 py-2" style="border-color: var(--warning); background: color-mix(in srgb, var(--warning) 6%, var(--surface)); color: var(--ink-500);">
            <p class="font-medium" style="color: var(--warning);">⚠ Une seule règle</p>
            <p class="mt-1">
              Ne lance <span class="font-mono">go-task ml:train</span> ni
              <span class="font-mono">ml:train-arcface</span> à la main — ça écrase ton
              checkpoint actuel. L'entraînement passe toujours par le bouton "Lancer le run"
              ci-dessus, qui orchestre prepare → train → embeddings → seed → validate.
            </p>
          </div>
        </div>
      </section>
    </template>

    <!-- ═══ Run detail drawer ═══ -->
    <Teleport to="body">
      <Transition name="drawer">
        <div
          v-if="selectedRun"
          class="fixed inset-0 z-50 flex"
          @click.self="closeRunDrawer"
        >
          <div class="flex-1 bg-[rgba(0,0,0,0.3)]" @click="closeRunDrawer" />
          <div
            class="h-full w-[640px] overflow-y-auto border-l px-6 py-5"
            style="border-color: var(--surface-3); background: var(--surface);"
          >
            <header class="mb-4 flex items-start justify-between">
              <div>
                <p class="font-mono text-xs uppercase tracking-wider" style="color: var(--ink-500);">
                  Run détail
                </p>
                <h3 class="font-display text-xl font-semibold" style="color: var(--ink);">
                  v{{ selectedRun.version }}
                </h3>
                <p class="text-xs" style="color: var(--ink-500);">
                  {{ formatDate(selectedRun.started_at) }} → {{ formatDate(selectedRun.finished_at) }}
                </p>
              </div>
              <button class="rounded p-1 hover:bg-[var(--surface-1)]" @click="closeRunDrawer">
                <X class="h-4 w-4" style="color: var(--ink-400);" />
              </button>
            </header>

            <div
              v-if="selectedRun.error"
              class="mb-4 rounded-md border px-3 py-2 text-xs"
              style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 6%, var(--surface)); color: var(--danger);"
            >
              {{ selectedRun.error }}
            </div>

            <div class="mb-4 grid grid-cols-3 gap-2">
              <div
                v-for="(label, key) in { loss: 'Loss', recall_at_1: 'R@1', recall_at_3: 'R@3' } as const"
                :key="key"
                class="rounded-md border px-3 py-2"
                style="border-color: var(--surface-3); background: var(--surface-1);"
              >
                <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                  {{ label }}
                </p>
                <p class="font-mono text-sm font-medium" style="color: var(--ink);">
                  <template v-if="key === 'loss'">{{ selectedRun[key]?.toFixed(4) ?? '—' }}</template>
                  <template v-else>{{ formatPct(selectedRun[key]) }}</template>
                </p>
              </div>
            </div>

            <div class="mb-4">
              <p class="mb-2 font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Classes ajoutées
              </p>
              <div v-if="selectedRun.classes_added.length === 0" class="text-xs" style="color: var(--ink-400);">—</div>
              <div v-else class="flex flex-wrap gap-1">
                <span
                  v-for="c in selectedRun.classes_added"
                  :key="c.class_id"
                  class="rounded border px-1.5 py-0.5 font-mono text-[10px]"
                  style="border-color: var(--success); background: color-mix(in srgb, var(--success) 8%, var(--surface)); color: var(--ink);"
                >
                  +{{ c.class_id }}
                </span>
              </div>
              <p class="mb-2 mt-3 font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Classes retirées
              </p>
              <div v-if="selectedRun.classes_removed.length === 0" class="text-xs" style="color: var(--ink-400);">—</div>
              <div v-else class="flex flex-wrap gap-1">
                <span
                  v-for="c in selectedRun.classes_removed"
                  :key="c.class_id"
                  class="rounded border px-1.5 py-0.5 font-mono text-[10px]"
                  style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 8%, var(--surface)); color: var(--ink);"
                >
                  -{{ c.class_id }}
                </span>
              </div>
            </div>

            <div v-if="selectedRun.per_class_metrics?.length" class="mb-4">
              <p class="mb-2 font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Métriques per-class
              </p>
              <div class="overflow-hidden rounded-md border" style="border-color: var(--surface-3);">
                <table class="w-full text-xs">
                  <thead style="background: var(--surface-1);">
                    <tr>
                      <th class="px-3 py-1.5 text-left font-mono text-[10px] uppercase" style="color: var(--ink-500);">Classe</th>
                      <th class="px-3 py-1.5 text-right font-mono text-[10px] uppercase" style="color: var(--ink-500);">R@1</th>
                      <th class="px-3 py-1.5 text-right font-mono text-[10px] uppercase" style="color: var(--ink-500);">Train</th>
                      <th class="px-3 py-1.5 text-right font-mono text-[10px] uppercase" style="color: var(--ink-500);">Val</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="m in selectedRun.per_class_metrics" :key="m.class_id" class="border-t" style="border-color: var(--surface-2);">
                      <td class="truncate px-3 py-1 font-mono text-[11px]" style="color: var(--ink); max-width: 300px;" :title="m.class_id">
                        {{ m.class_id }}
                      </td>
                      <td class="px-3 py-1 text-right font-mono text-[11px]" style="color: var(--ink);">
                        {{ formatPct(m.recall_at_1) }}
                      </td>
                      <td class="px-3 py-1 text-right font-mono text-[11px]" style="color: var(--ink-500);">
                        {{ m.n_train_images ?? '—' }}
                      </td>
                      <td class="px-3 py-1 text-right font-mono text-[11px]" style="color: var(--ink-500);">
                        {{ m.n_val_images ?? '—' }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div v-if="selectedRun.epochs?.length" class="mb-4">
              <p class="mb-2 font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Courbe training
              </p>
              <div class="overflow-hidden rounded-md border" style="border-color: var(--surface-3);">
                <table class="w-full text-xs">
                  <thead style="background: var(--surface-1);">
                    <tr>
                      <th class="px-3 py-1.5 text-left font-mono text-[10px] uppercase" style="color: var(--ink-500);">Epoch</th>
                      <th class="px-3 py-1.5 text-right font-mono text-[10px] uppercase" style="color: var(--ink-500);">Loss</th>
                      <th class="px-3 py-1.5 text-right font-mono text-[10px] uppercase" style="color: var(--ink-500);">R@1</th>
                      <th class="px-3 py-1.5 text-right font-mono text-[10px] uppercase" style="color: var(--ink-500);">R@3</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="e in selectedRun.epochs" :key="e.epoch" class="border-t" style="border-color: var(--surface-2);">
                      <td class="px-3 py-1 font-mono text-[11px]" style="color: var(--ink);">{{ e.epoch }}</td>
                      <td class="px-3 py-1 text-right font-mono text-[11px]" style="color: var(--ink);">{{ e.train_loss?.toFixed(4) ?? '—' }}</td>
                      <td class="px-3 py-1 text-right font-mono text-[11px]" style="color: var(--ink);">{{ formatPct(e.recall_at_1) }}</td>
                      <td class="px-3 py-1 text-right font-mono text-[11px]" style="color: var(--ink);">{{ formatPct(e.recall_at_3) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <details class="mt-4">
              <summary class="cursor-pointer text-xs" style="color: var(--ink-500);">
                Logs ({{ selectedRunLogs.length }} lignes)
              </summary>
              <div
                class="mt-2 max-h-64 overflow-y-auto rounded-md border p-2 font-mono text-[10px] leading-snug"
                style="border-color: var(--surface-3); background: var(--surface-1); color: var(--ink-500);"
              >
                <p v-for="(line, i) in selectedRunLogs" :key="i" class="whitespace-pre">
                  {{ line }}
                </p>
              </div>
            </details>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- ═══ Class detail drawer ═══ -->
    <Teleport to="body">
      <Transition name="drawer">
        <div
          v-if="selectedClass"
          class="fixed inset-0 z-50 flex"
          @click.self="closeClassDrawer"
        >
          <div class="flex-1 bg-[rgba(0,0,0,0.3)]" @click="closeClassDrawer" />
          <div
            class="h-full w-[540px] overflow-y-auto border-l px-6 py-5"
            style="border-color: var(--surface-3); background: var(--surface);"
          >
            <header class="mb-4 flex items-start justify-between">
              <div>
                <p class="font-mono text-xs uppercase tracking-wider" style="color: var(--ink-500);">
                  Classe {{ selectedClass.class_kind }}
                </p>
                <h3 class="mt-1 font-mono text-lg font-semibold" style="color: var(--ink);">
                  {{ selectedClass.class_id }}
                </h3>
              </div>
              <button class="rounded p-1 hover:bg-[var(--surface-1)]" @click="closeClassDrawer">
                <X class="h-4 w-4" style="color: var(--ink-400);" />
              </button>
            </header>

            <div class="mb-4 grid grid-cols-3 gap-2">
              <div class="rounded-md border px-3 py-2" style="border-color: var(--surface-3); background: var(--surface-1);">
                <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">R@1</p>
                <p class="font-mono text-sm font-medium" style="color: var(--ink);">
                  {{ formatPct(selectedClass.recall_at_1) }}
                </p>
              </div>
              <div class="rounded-md border px-3 py-2" style="border-color: var(--surface-3); background: var(--surface-1);">
                <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Train imgs</p>
                <p class="font-mono text-sm font-medium" style="color: var(--ink);">
                  {{ selectedClass.n_train_images ?? '—' }}
                </p>
              </div>
              <div class="rounded-md border px-3 py-2" style="border-color: var(--surface-3); background: var(--surface-1);">
                <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Dernière version</p>
                <p class="font-mono text-sm font-medium" style="color: var(--ink);">
                  {{ selectedClass.last_trained_version ? `v${selectedClass.last_trained_version}` : '—' }}
                </p>
              </div>
            </div>

            <p class="mb-2 font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
              Historique runs
            </p>
            <div
              v-if="selectedClassHistory.length === 0"
              class="rounded-md border border-dashed px-3 py-4 text-center text-xs"
              style="border-color: var(--surface-3); color: var(--ink-400);"
            >
              Aucun run historique (classe jamais entraînée ?)
            </div>
            <div v-else class="space-y-1">
              <div
                v-for="h in selectedClassHistory"
                :key="h.run_id"
                class="flex items-center justify-between rounded-md border px-3 py-2 text-xs"
                style="border-color: var(--surface-3); background: var(--surface-1);"
              >
                <div>
                  <p class="font-mono" style="color: var(--ink);">v{{ h.version }}</p>
                  <p class="text-[10px]" style="color: var(--ink-500);">
                    {{ formatDate(h.finished_at) }} · {{ h.status }}
                  </p>
                </div>
                <div class="text-right">
                  <p class="font-mono" style="color: var(--ink);">
                    R@1 {{ formatPct(h.recall_at_1) }}
                  </p>
                  <p class="text-[10px]" style="color: var(--ink-500);">
                    {{ h.n_train_images ?? '—' }} train · {{ h.n_val_images ?? '—' }} val
                  </p>
                </div>
              </div>
            </div>

            <div class="mt-6 border-t pt-4" style="border-color: var(--surface-2);">
              <button
                v-if="!removalIds.has(selectedClass.class_id)"
                class="flex w-full items-center justify-center gap-2 rounded-md border px-3 py-2 text-xs font-medium transition-colors"
                style="border-color: var(--danger); color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface));"
                @click="stageClassForRemoval(selectedClass); closeClassDrawer()"
              >
                <Trash2 class="h-3.5 w-3.5" />
                Retirer du modèle (ré-entraînement requis)
              </button>
              <p
                v-else
                class="rounded-md border border-dashed py-2 text-center text-xs"
                style="border-color: var(--danger); color: var(--danger);"
              >
                Déjà marquée pour suppression au prochain run
              </p>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<style scoped>
.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 0.2s ease;
}
.drawer-enter-active > div:last-child,
.drawer-leave-active > div:last-child {
  transition: transform 0.22s ease;
}
.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}
.drawer-enter-from > div:last-child,
.drawer-leave-to > div:last-child {
  transform: translateX(100%);
}
</style>
