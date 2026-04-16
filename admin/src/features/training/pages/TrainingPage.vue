<script setup lang="ts">
import {
  Activity,
  Brain,
  Check,
  Circle,
  Loader2,
  Trash2,
  Wifi,
  WifiOff,
  X,
} from 'lucide-vue-next'
import { computed, onMounted, onUnmounted, ref } from 'vue'

const ML_API = 'http://localhost:8042'

/* ─── Types ─── */

interface StepInfo {
  name: string
  status: 'pending' | 'running' | 'done' | 'failed'
  started_at: string | null
  finished_at: string | null
  detail: string | null
}

interface TrainingRun {
  id: string
  design_id: number
  design_name: string
  design_country: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  started_at: string | null
  finished_at: string | null
  error: string | null
  steps: StepInfo[]
  steps_completed: number
  steps_total: number
  epoch: number
  epochs_total: number
  loss: number | null
  recall_at_1: number | null
  recall_at_3: number | null
}

interface HealthData {
  status: string
  model_version: string | null
  last_trained_at: string | null
  supabase_connected: boolean
  designs_count: number
  trained_count: number
  queue_length: number
  active_count: number
}

/* ─── State ─── */

const apiStatus = ref<'checking' | 'online' | 'offline'>('checking')
const healthData = ref<HealthData | null>(null)

const activeRuns = ref<TrainingRun[]>([])
const queue = ref<TrainingRun[]>([])
const history = ref<TrainingRun[]>([])

const config = ref({ max_concurrent: 1, device: 'mps' })

// Augmented image previews for active runs: { design_id: url[] }
const augmentedPreviews = ref<Record<number, string[]>>({})

// History expansion
const expandedHistoryId = ref<string | null>(null)

/* ─── API calls ─── */

async function checkHealth() {
  try {
    const resp = await fetch(`${ML_API}/health`, { signal: AbortSignal.timeout(3000) })
    if (resp.ok) {
      healthData.value = await resp.json()
      apiStatus.value = 'online'
    } else {
      apiStatus.value = 'offline'
    }
  } catch {
    apiStatus.value = 'offline'
  }
}

async function fetchTrainStatus() {
  if (apiStatus.value !== 'online') return
  try {
    const resp = await fetch(`${ML_API}/train/status`)
    if (!resp.ok) return
    const data = await resp.json()
    activeRuns.value = data.active ?? []
    queue.value = data.queue ?? []
    history.value = data.history ?? []

    // Fetch augmented previews for active runs (once per design)
    for (const run of activeRuns.value) {
      if (
        !augmentedPreviews.value[run.design_id] &&
        run.steps[0]?.status === 'done'
      ) {
        fetchAugmentedImages(run.design_id)
      }
    }
  } catch {
    // API went down
  }
}

async function fetchAugmentedImages(designId: number) {
  try {
    const resp = await fetch(`${ML_API}/images/${designId}/augmented`)
    if (!resp.ok) return
    const data = await resp.json()
    const urls = (data.images ?? [])
      .slice(0, 8)
      .map((img: { url: string }) => `${ML_API}${img.url}`)
    augmentedPreviews.value = { ...augmentedPreviews.value, [designId]: urls }
  } catch {
    // ignore
  }
}

async function fetchConfig() {
  if (apiStatus.value !== 'online') return
  try {
    const resp = await fetch(`${ML_API}/train/config`)
    if (resp.ok) config.value = await resp.json()
  } catch {
    // ignore
  }
}

async function updateConcurrency(value: number) {
  try {
    await fetch(`${ML_API}/train/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ max_concurrent: value, device: config.value.device }),
    })
    config.value.max_concurrent = value
  } catch {
    // ignore
  }
}

async function removeFromQueue(runId: string) {
  try {
    await fetch(`${ML_API}/train/queue/${runId}`, { method: 'DELETE' })
    await fetchTrainStatus()
  } catch {
    // ignore
  }
}

/* ─── Computed ─── */

const isIdle = computed(
  () => activeRuns.value.length === 0 && queue.value.length === 0,
)

/* ─── Helpers ─── */

function sourceImageUrl(designId: number): string {
  return `${ML_API}/images/${designId}/source`
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString('fr-FR', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatDuration(start: string | null, end: string | null): string {
  if (!start) return '—'
  const s = new Date(start).getTime()
  const e = end ? new Date(end).getTime() : Date.now()
  const diff = Math.round((e - s) / 1000)
  if (diff < 60) return `${diff}s`
  const min = Math.floor(diff / 60)
  const sec = diff % 60
  return `${min}m${sec.toString().padStart(2, '0')}s`
}

function formatMetric(v: number | null): string {
  if (v == null) return '—'
  return `${(v * 100).toFixed(1)}%`
}

function stepDuration(step: StepInfo): string {
  return formatDuration(step.started_at, step.finished_at)
}

function toggleHistory(runId: string) {
  expandedHistoryId.value = expandedHistoryId.value === runId ? null : runId
}

/* ─── Lifecycle ─── */

let healthInterval: ReturnType<typeof setInterval>
let statusInterval: ReturnType<typeof setInterval>

onMounted(async () => {
  await checkHealth()
  await fetchConfig()
  await fetchTrainStatus()

  healthInterval = setInterval(checkHealth, 30_000)
  statusInterval = setInterval(fetchTrainStatus, 2_000)
})

onUnmounted(() => {
  clearInterval(healthInterval)
  clearInterval(statusInterval)
})
</script>

<template>
  <div class="p-8">
    <!-- ═══ Header ═══ -->
    <div class="mb-6 flex items-start justify-between">
      <div>
        <h1
          class="font-display text-2xl italic font-semibold"
          style="color: var(--indigo-700)"
        >
          Training
        </h1>
        <p class="mt-0.5 text-sm" style="color: var(--ink-500)">
          <template v-if="healthData">
            {{ healthData.trained_count }} embeddings ·
            {{ healthData.designs_count }} designs dans Supabase
          </template>
          <template v-else>
            Connexion en cours…
          </template>
        </p>
      </div>

      <div class="flex items-center gap-4">
        <!-- Concurrency selector -->
        <div
          v-if="apiStatus === 'online'"
          class="flex items-center gap-2"
        >
          <span class="text-[11px] uppercase tracking-wider" style="color: var(--ink-500)">
            Concurrence
          </span>
          <select
            :value="config.max_concurrent"
            class="rounded-md border px-2 py-1 text-xs font-mono outline-none focus:ring-2"
            style="border-color: var(--surface-3); background: var(--surface); color: var(--ink); --tw-ring-color: var(--indigo-700)"
            @change="updateConcurrency(Number(($event.target as HTMLSelectElement).value))"
          >
            <option :value="1">1</option>
            <option :value="2">2</option>
            <option :value="3">3</option>
            <option :value="4">4</option>
          </select>
        </div>

        <!-- API Status -->
        <div
          class="flex items-center gap-2 rounded-full border px-3 py-1.5"
          :style="{
            borderColor: apiStatus === 'online' ? 'var(--success)' : 'var(--surface-3)',
            background: apiStatus === 'online'
              ? 'color-mix(in srgb, var(--success) 8%, var(--surface))'
              : 'var(--surface)',
          }"
        >
          <template v-if="apiStatus === 'checking'">
            <Loader2 class="h-3.5 w-3.5 animate-spin" style="color: var(--ink-400)" />
            <span class="text-xs" style="color: var(--ink-400)">Connexion…</span>
          </template>
          <template v-else-if="apiStatus === 'online'">
            <Wifi class="h-3.5 w-3.5" style="color: var(--success)" />
            <span class="text-xs font-medium" style="color: var(--success)">API ML</span>
            <span
              v-if="healthData?.model_version"
              class="font-mono text-[10px]"
              style="color: var(--ink-400)"
            >
              {{ healthData.model_version }}
            </span>
          </template>
          <template v-else>
            <WifiOff class="h-3.5 w-3.5" style="color: var(--ink-400)" />
            <span class="text-xs" style="color: var(--ink-400)">Hors ligne</span>
          </template>
        </div>
      </div>
    </div>

    <!-- ═══ API Offline ═══ -->
    <div
      v-if="apiStatus === 'offline'"
      class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-16"
      style="border-color: var(--surface-3)"
    >
      <Brain class="mb-3 h-10 w-10" style="color: var(--ink-300)" />
      <p class="font-display italic text-lg" style="color: var(--ink-400)">
        API ML hors ligne
      </p>
      <p class="mt-1 text-xs" style="color: var(--ink-400)">
        Lancez <code class="font-mono" style="color: var(--indigo-700)">go-task api</code>
        dans le dossier <code class="font-mono">ml/</code>
      </p>
    </div>

    <template v-if="apiStatus === 'online'">
      <!-- ═══ Section 1: Active Run(s) ═══ -->
      <template v-if="activeRuns.length > 0">
        <div
          v-for="run in activeRuns"
          :key="run.id"
          class="mb-6 overflow-hidden rounded-lg border"
          style="border-color: var(--indigo-700); background: var(--surface)"
        >
          <!-- Run header -->
          <div
            class="flex items-center gap-4 border-b px-5 py-4"
            style="border-color: var(--surface-2); background: color-mix(in srgb, var(--indigo-700) 4%, var(--surface))"
          >
            <img
              :src="sourceImageUrl(run.design_id)"
              :alt="run.design_name"
              class="h-12 w-12 rounded-lg object-contain"
              style="background: var(--surface-1)"
              @error="($event.target as HTMLImageElement).style.display = 'none'"
            />
            <div class="flex-1">
              <div class="flex items-center gap-2">
                <span
                  class="rounded-full px-1.5 py-0.5 text-[10px] font-mono font-bold uppercase"
                  style="background: rgba(26, 27, 75, 0.08); color: var(--indigo-700)"
                >
                  {{ run.design_country }}
                </span>
                <span class="font-mono text-xs" style="color: var(--ink-400)">
                  N{{ run.design_id }}
                </span>
              </div>
              <p class="text-sm font-medium" style="color: var(--ink)">
                {{ run.design_name }}
              </p>
            </div>
            <div class="text-right">
              <p class="font-mono text-xs" style="color: var(--ink-400)">
                {{ run.id }}
              </p>
              <p class="text-[10px]" style="color: var(--ink-500)">
                {{ formatDuration(run.started_at, null) }}
              </p>
            </div>
          </div>

          <!-- Pipeline stepper -->
          <div class="px-5 py-5">
            <div class="flex items-start">
              <template v-for="(step, idx) in run.steps" :key="idx">
                <!-- Step circle + label -->
                <div class="flex flex-col items-center" style="min-width: 90px">
                  <!-- Circle -->
                  <div
                    class="flex h-8 w-8 items-center justify-center rounded-full transition-all"
                    :style="{
                      background:
                        step.status === 'done' ? 'var(--success)'
                        : step.status === 'running' ? 'var(--indigo-700)'
                        : step.status === 'failed' ? 'var(--danger)'
                        : 'var(--surface-2)',
                      color: step.status === 'pending' ? 'var(--ink-400)' : 'white',
                    }"
                    :class="{ 'animate-pulse': step.status === 'running' }"
                  >
                    <Check v-if="step.status === 'done'" class="h-4 w-4" />
                    <Loader2
                      v-else-if="step.status === 'running'"
                      class="h-4 w-4 animate-spin"
                    />
                    <X v-else-if="step.status === 'failed'" class="h-4 w-4" />
                    <Circle v-else class="h-3 w-3" />
                  </div>
                  <!-- Label -->
                  <p
                    class="mt-1.5 text-center text-[10px] font-medium leading-tight"
                    :style="{
                      color:
                        step.status === 'running' ? 'var(--indigo-700)'
                        : step.status === 'done' ? 'var(--success)'
                        : step.status === 'failed' ? 'var(--danger)'
                        : 'var(--ink-400)',
                    }"
                  >
                    {{ step.name }}
                  </p>
                  <!-- Duration -->
                  <p
                    v-if="step.status === 'done' || step.status === 'running'"
                    class="font-mono text-[9px]"
                    style="color: var(--ink-400)"
                  >
                    {{ stepDuration(step) }}
                  </p>
                  <!-- Detail -->
                  <p
                    v-if="step.detail"
                    class="mt-0.5 text-center text-[9px]"
                    style="color: var(--ink-500)"
                  >
                    {{ step.detail }}
                  </p>
                </div>
                <!-- Connecting line -->
                <div
                  v-if="idx < run.steps.length - 1"
                  class="mt-4 h-0.5 flex-1"
                  :style="{
                    background:
                      step.status === 'done' ? 'var(--success)'
                      : step.status === 'running' ? 'var(--indigo-700)'
                      : 'var(--surface-2)',
                  }"
                />
              </template>
            </div>

            <!-- Training metrics (during training step) -->
            <div
              v-if="run.steps[2]?.status === 'running' && run.epochs_total > 0"
              class="mt-4 rounded-md border px-4 py-3"
              style="border-color: var(--surface-2); background: var(--surface-1)"
            >
              <div class="mb-2 flex items-center justify-between">
                <span class="text-xs font-medium" style="color: var(--ink)">
                  Epoch {{ run.epoch }} / {{ run.epochs_total }}
                </span>
                <span class="font-mono text-xs" style="color: var(--indigo-700)">
                  {{ Math.round((run.epoch / run.epochs_total) * 100) }}%
                </span>
              </div>
              <!-- Epoch progress bar -->
              <div class="mb-3 h-1.5 overflow-hidden rounded-full" style="background: var(--surface-2)">
                <div
                  class="h-full rounded-full transition-all duration-500"
                  style="background: var(--indigo-700)"
                  :style="{ width: `${(run.epoch / run.epochs_total) * 100}%` }"
                />
              </div>
              <!-- Metrics -->
              <div class="grid grid-cols-3 gap-4">
                <div>
                  <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500)">Loss</p>
                  <p class="font-mono text-sm" style="color: var(--ink)">
                    {{ run.loss != null ? run.loss.toFixed(4) : '—' }}
                  </p>
                </div>
                <div>
                  <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500)">R@1</p>
                  <p class="font-mono text-sm" style="color: var(--success)">
                    {{ formatMetric(run.recall_at_1) }}
                  </p>
                </div>
                <div>
                  <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500)">R@3</p>
                  <p class="font-mono text-sm" style="color: var(--ink)">
                    {{ formatMetric(run.recall_at_3) }}
                  </p>
                </div>
              </div>
            </div>

            <!-- Augmented image previews -->
            <div
              v-if="augmentedPreviews[run.design_id]?.length"
              class="mt-4"
            >
              <p class="mb-2 text-[10px] uppercase tracking-wider" style="color: var(--ink-500)">
                Aperçu des augmentations
              </p>
              <div class="flex gap-2 overflow-x-auto">
                <img
                  v-for="(url, i) in augmentedPreviews[run.design_id]"
                  :key="i"
                  :src="url"
                  class="h-16 w-16 flex-shrink-0 rounded-md object-cover"
                  style="background: var(--surface-1)"
                  loading="lazy"
                />
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- ═══ Section 2: Queue ═══ -->
      <div class="mb-6">
        <h2 class="mb-3 text-xs font-medium uppercase tracking-wider" style="color: var(--ink-500)">
          File d'attente
          <span v-if="queue.length > 0" class="ml-1 font-mono">
            ({{ queue.length }})
          </span>
        </h2>

        <div
          v-if="queue.length === 0 && activeRuns.length === 0"
          class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-12"
          style="border-color: var(--surface-3)"
        >
          <Activity class="mb-2 h-6 w-6" style="color: var(--ink-300)" />
          <p class="text-sm" style="color: var(--ink-400)">
            Aucun entraînement en cours
          </p>
          <p class="mt-1 text-xs" style="color: var(--ink-400)">
            Sélectionnez des designs depuis
            <router-link to="/coins" class="underline" style="color: var(--indigo-700)">
              Pièces
            </router-link>
          </p>
        </div>

        <div v-else-if="queue.length > 0" class="space-y-2">
          <div
            v-for="job in queue"
            :key="job.id"
            class="flex items-center gap-3 rounded-lg border px-4 py-3"
            style="border-color: var(--surface-3); background: var(--surface)"
          >
            <img
              :src="sourceImageUrl(job.design_id)"
              :alt="job.design_name"
              class="h-10 w-10 rounded-md object-contain"
              style="background: var(--surface-1)"
              @error="($event.target as HTMLImageElement).style.display = 'none'"
            />
            <div class="flex-1">
              <p class="text-sm font-medium" style="color: var(--ink)">
                {{ job.design_name }}
              </p>
              <div class="flex items-center gap-1.5">
                <span
                  class="rounded-full px-1.5 py-0.5 text-[10px] font-mono font-bold uppercase"
                  style="background: rgba(26, 27, 75, 0.08); color: var(--indigo-700)"
                >
                  {{ job.design_country }}
                </span>
                <span class="font-mono text-[10px]" style="color: var(--ink-400)">
                  N{{ job.design_id }}
                </span>
              </div>
            </div>
            <button
              class="flex h-7 w-7 items-center justify-center rounded-md transition-colors hover:bg-black/5"
              title="Retirer de la queue"
              @click="removeFromQueue(job.id)"
            >
              <Trash2 class="h-3.5 w-3.5" style="color: var(--ink-400)" />
            </button>
          </div>
        </div>
      </div>

      <!-- ═══ Section 3: History ═══ -->
      <div v-if="history.length > 0">
        <h2 class="mb-3 text-xs font-medium uppercase tracking-wider" style="color: var(--ink-500)">
          Historique
        </h2>

        <div class="overflow-hidden rounded-lg border" style="border-color: var(--surface-3)">
          <table class="w-full text-sm">
            <thead>
              <tr style="background: var(--surface-1); border-bottom: 1px solid var(--surface-3)">
                <th class="px-4 py-2.5 text-left text-[10px] font-medium uppercase tracking-wider" style="color: var(--ink-500)">Date</th>
                <th class="px-4 py-2.5 text-left text-[10px] font-medium uppercase tracking-wider" style="color: var(--ink-500)">Design</th>
                <th class="px-4 py-2.5 text-left text-[10px] font-medium uppercase tracking-wider" style="color: var(--ink-500)">Statut</th>
                <th class="px-4 py-2.5 text-right text-[10px] font-medium uppercase tracking-wider" style="color: var(--ink-500)">R@1</th>
                <th class="px-4 py-2.5 text-right text-[10px] font-medium uppercase tracking-wider" style="color: var(--ink-500)">Durée</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="run in history" :key="run.id">
                <tr
                  class="cursor-pointer transition-colors hover:bg-black/[0.02]"
                  style="border-bottom: 1px solid var(--surface-2)"
                  @click="toggleHistory(run.id)"
                >
                  <td class="px-4 py-2.5 font-mono text-xs" style="color: var(--ink-400)">
                    {{ formatDate(run.started_at) }}
                  </td>
                  <td class="px-4 py-2.5">
                    <div class="flex items-center gap-2">
                      <span class="font-mono text-[10px] uppercase" style="color: var(--ink-400)">
                        {{ run.design_country }}
                      </span>
                      <span class="text-xs" style="color: var(--ink)">
                        {{ run.design_name }}
                      </span>
                      <span class="font-mono text-[10px]" style="color: var(--ink-400)">
                        N{{ run.design_id }}
                      </span>
                    </div>
                  </td>
                  <td class="px-4 py-2.5">
                    <span
                      class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
                      :style="{
                        background: run.status === 'completed'
                          ? 'color-mix(in srgb, var(--success) 12%, var(--surface))'
                          : 'color-mix(in srgb, var(--danger) 12%, var(--surface))',
                        color: run.status === 'completed' ? 'var(--success)' : 'var(--danger)',
                      }"
                    >
                      <Check v-if="run.status === 'completed'" class="h-3 w-3" />
                      <X v-else class="h-3 w-3" />
                      {{ run.status === 'completed' ? 'Terminé' : 'Échoué' }}
                    </span>
                  </td>
                  <td class="px-4 py-2.5 text-right font-mono text-xs" style="color: var(--success)">
                    {{ formatMetric(run.recall_at_1) }}
                  </td>
                  <td class="px-4 py-2.5 text-right font-mono text-xs" style="color: var(--ink-400)">
                    {{ formatDuration(run.started_at, run.finished_at) }}
                  </td>
                </tr>
                <!-- Expanded detail -->
                <tr v-if="expandedHistoryId === run.id">
                  <td colspan="5" class="px-4 py-4" style="background: var(--surface-1)">
                    <!-- Mini stepper -->
                    <div class="flex items-center gap-1">
                      <template v-for="(step, idx) in run.steps" :key="idx">
                        <div class="flex items-center gap-1.5">
                          <div
                            class="flex h-5 w-5 items-center justify-center rounded-full"
                            :style="{
                              background:
                                step.status === 'done' ? 'var(--success)'
                                : step.status === 'failed' ? 'var(--danger)'
                                : 'var(--surface-2)',
                              color: step.status === 'pending' ? 'var(--ink-400)' : 'white',
                            }"
                          >
                            <Check v-if="step.status === 'done'" class="h-3 w-3" />
                            <X v-else-if="step.status === 'failed'" class="h-3 w-3" />
                            <Circle v-else class="h-2 w-2" />
                          </div>
                          <div class="text-[10px]">
                            <span :style="{ color: step.status === 'failed' ? 'var(--danger)' : 'var(--ink)' }">
                              {{ step.name }}
                            </span>
                            <span v-if="step.detail" class="ml-1" style="color: var(--ink-400)">
                              {{ step.detail }}
                            </span>
                            <span v-if="step.started_at" class="ml-1 font-mono" style="color: var(--ink-400)">
                              {{ stepDuration(step) }}
                            </span>
                          </div>
                        </div>
                        <div
                          v-if="idx < run.steps.length - 1"
                          class="mx-1 h-px w-3"
                          :style="{ background: step.status === 'done' ? 'var(--success)' : 'var(--surface-3)' }"
                        />
                      </template>
                    </div>
                    <p v-if="run.error" class="mt-2 text-xs" style="color: var(--danger)">
                      {{ run.error }}
                    </p>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Empty state when idle and no history -->
      <div
        v-if="isIdle && history.length === 0"
        class="mt-8 flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-16"
        style="border-color: var(--surface-3)"
      >
        <Brain class="mb-3 h-10 w-10" style="color: var(--ink-300)" />
        <p class="font-display italic text-lg" style="color: var(--ink-400)">
          Prêt pour l'entraînement
        </p>
        <p class="mt-1 text-xs" style="color: var(--ink-400)">
          Sélectionnez des designs depuis
          <router-link to="/coins" class="underline" style="color: var(--indigo-700)">
            Pièces
          </router-link>
          pour démarrer
        </p>
      </div>
    </template>
  </div>
</template>
