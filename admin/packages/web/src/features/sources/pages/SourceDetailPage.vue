<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  ClipboardCopy,
  Clock,
  ExternalLink,
  FileText,
  Loader2,
  Play,
  Terminal,
  TestTube2,
  XCircle,
} from 'lucide-vue-next'
import {
  TriggerError,
  fetchSourceCommands,
  fetchSourceCoverage,
  fetchSourceDetail,
  fetchSourceImages,
  fetchSourceQuotes,
  fetchSourceRuns,
  pollSourceRun,
  triggerSourceRun,
  type RunSnapshot,
  type SourceCoverageDetail,
  type SourceDetailHeader,
  type SourceImage,
  type SourceQuote,
  type SourceRun,
} from '../composables/useSourceDetail'
import {
  getPipelineMeta,
  type CliHint,
  type HealthState,
  type SourceId,
} from '../composables/useSourcesApi'

// ─── Route + state ──────────────────────────────────────────────────────

const route = useRoute()
const router = useRouter()

const id = computed(() => (route.params.id as string) as SourceId)

type TabKey = 'runs' | 'donnees' | 'couverture' | 'commandes'
const activeTab = ref<TabKey>('runs')

const TABS: { key: TabKey; label: string }[] = [
  { key: 'runs', label: 'Runs' },
  { key: 'donnees', label: 'Données' },
  { key: 'couverture', label: 'Couverture' },
  { key: 'commandes', label: 'Commandes' },
]

const header = ref<SourceDetailHeader | null>(null)
const runs = ref<SourceRun[]>([])
const images = ref<SourceImage[]>([])
const quotes = ref<SourceQuote[]>([])
const coverage = ref<SourceCoverageDetail | null>(null)
const commands = ref<CliHint[]>([])

type DataSubTab = 'images' | 'quotes'
const dataTab = ref<DataSubTab>('images')

const loadError = ref<string | null>(null)

// ─── Derived ────────────────────────────────────────────────────────────

const pipelineMeta = computed(() => (header.value ? getPipelineMeta(header.value.id) : null))

const HEALTH_TONE: Record<HealthState, string> = {
  healthy: 'var(--success)',
  warning: 'var(--warning)',
  error: 'var(--danger)',
}

const HEALTH_LABEL: Record<HealthState, string> = {
  healthy: 'healthy',
  warning: 'attention',
  error: 'erreur',
}

function formatAbsolute(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

function formatDuration(s: number): string {
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  const rest = s % 60
  return `${m}m${String(rest).padStart(2, '0')}`
}

function formatNumber(n: number): string {
  return n.toLocaleString('fr-FR')
}

const lastRun = computed(() => runs.value[0] ?? null)

// ─── Loaders ────────────────────────────────────────────────────────────

async function loadAll(sourceId: SourceId) {
  loadError.value = null
  try {
    const [h, r, c] = await Promise.all([
      fetchSourceDetail(sourceId),
      fetchSourceRuns(sourceId, { limit: 50 }),
      fetchSourceCoverage(sourceId),
    ])
    header.value = h
    runs.value = r
    coverage.value = c
    commands.value = fetchSourceCommands(sourceId)
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : 'Erreur de chargement'
  }
}

async function loadDataTab(sourceId: SourceId) {
  if (dataTab.value === 'images' && images.value.length === 0) {
    const { items } = await fetchSourceImages(sourceId, { page: 1, pageSize: 24 })
    images.value = items
  }
  if (dataTab.value === 'quotes' && quotes.value.length === 0) {
    const { items } = await fetchSourceQuotes(sourceId, { page: 1, pageSize: 25 })
    quotes.value = items
  }
}

watch([activeTab, id], () => {
  if (activeTab.value === 'donnees') void loadDataTab(id.value)
})

watch(dataTab, () => {
  void loadDataTab(id.value)
})

watch(id, (n) => {
  if (n) {
    images.value = []
    quotes.value = []
    void loadAll(n)
  }
})

onMounted(() => {
  void loadAll(id.value)
})

// ─── Actions ────────────────────────────────────────────────────────────

const copiedCommand = ref<string | null>(null)

async function copyCommand(cmd: string) {
  try {
    await navigator.clipboard.writeText(cmd)
    copiedCommand.value = cmd
    setTimeout(() => {
      if (copiedCommand.value === cmd) copiedCommand.value = null
    }, 1400)
  } catch {
    // ignore — clipboard may be unavailable in dev
  }
}

function viewLog(run: SourceRun) {
  // V1 mock — pas de modal logs (à câbler avec /sources/:id/runs/:run_id/log)
  console.info('[V1 mock] view log', run.log_path)
}

// Trigger Run / Dry run via POST /sources/:id/runs, then poll GET
// /sources/:id/runs/:run_id every 2s until status != 'running'. The
// run_logger context manager flips the row to success/partial/failed.
type RunMode = 'run' | 'dry'
const inflight = ref<RunMode | null>(null)
const liveRun = ref<RunSnapshot | null>(null)
const lastTriggerToast = ref<
  | { mode: RunMode; tone: 'success' | 'warning' | 'danger'; message: string; ts: number }
  | null
>(null)

function showToast(
  mode: RunMode,
  tone: 'success' | 'warning' | 'danger',
  message: string,
) {
  lastTriggerToast.value = { mode, tone, message, ts: Date.now() }
  setTimeout(() => {
    if (lastTriggerToast.value && Date.now() - lastTriggerToast.value.ts >= 4500) {
      lastTriggerToast.value = null
    }
  }, 4700)
}

async function triggerRun(mode: RunMode) {
  if (inflight.value) return
  inflight.value = mode
  liveRun.value = null
  try {
    const trig = await triggerSourceRun(id.value, { dryRun: mode === 'dry' })
    const final = await pollSourceRun(id.value, trig.run_id, {
      onTick: (snap) => { liveRun.value = snap },
    })
    const tone = final.status === 'success' ? 'success' : final.status === 'partial' ? 'warning' : 'danger'
    const summary = mode === 'dry'
      ? `${final.n_calls} discover call · ${final.error_summary ?? 'OK'}`
      : `+${final.n_raws_added} raws · +${final.n_crops_added} crops · +${final.n_review_enqueued} review · ${final.n_errors} errors`
    showToast(mode, tone, `${mode === 'dry' ? 'Dry run' : 'Run'} ${final.status} — ${summary}`)
    // Refresh runs table so the new row shows up.
    runs.value = await fetchSourceRuns(id.value, { limit: 50 })
  } catch (err) {
    if (err instanceof TriggerError) {
      const tone = err.status === 501 ? 'warning' : 'danger'
      showToast(mode, tone, err.message)
    } else {
      showToast(mode, 'danger', String(err))
    }
  } finally {
    inflight.value = null
  }
}

const RUN_STATUS_TONE: Record<SourceRun['status'], string> = {
  success: 'var(--success)',
  partial: 'var(--warning)',
  failed: 'var(--danger)',
  running: 'var(--indigo-500)',
}
</script>

<template>
  <div class="p-8">
    <!-- ═══ Back link ═══ -->
    <button
      class="mb-4 inline-flex items-center gap-1.5 text-xs transition-colors"
      style="color: var(--ink-400);"
      @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.color = 'var(--indigo-700)')"
      @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.color = 'var(--ink-400)')"
      @click="router.push('/sources')"
    >
      <ArrowLeft class="h-3 w-3" />
      Toutes les sources
    </button>

    <!-- ═══ Load error ═══ -->
    <div
      v-if="loadError"
      class="mb-6 rounded-lg border px-5 py-3 text-sm"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);"
    >
      Erreur lors du chargement : {{ loadError }}
    </div>

    <template v-if="header">
      <!-- ═══ Header dense persistant ═══ -->
      <header
        class="mb-6 rounded-lg border px-6 py-5"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <div class="flex flex-wrap items-start justify-between gap-6">
          <!-- Identity + pipeline meta -->
          <div class="min-w-0 flex-1">
            <h1
              class="font-display text-2xl italic font-semibold leading-tight"
              style="color: var(--indigo-700);"
            >
              {{ header.label }}
            </h1>
            <p class="mt-0.5 text-sm" style="color: var(--ink-500);">
              {{ header.subtitle }}
            </p>

            <p
              v-if="pipelineMeta"
              class="mt-3 font-mono text-[11px] uppercase tracking-wider"
              style="color: var(--ink-500);"
            >
              <span style="color: var(--ink-400);">Rôle&nbsp;·&nbsp;</span>
              <span class="normal-case tracking-normal" style="color: var(--indigo-700);">
                {{ pipelineMeta.role === 'referential' ? 'Référentiel canonique' : 'Enrichissement' }}
              </span>
              <span class="mx-2 opacity-40">|</span>
              <span style="color: var(--ink-400);">Produit&nbsp;·&nbsp;</span>
              <span class="normal-case tracking-normal" style="color: var(--indigo-700);">
                {{ pipelineMeta.produces.join(' · ') }}
              </span>
            </p>
          </div>

          <!-- Health pill + run actions -->
          <div class="flex shrink-0 flex-col items-end gap-2">
            <div
              class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium"
              :title="header.health_reason ?? undefined"
              :style="{
                borderColor: HEALTH_TONE[header.health],
                color: HEALTH_TONE[header.health],
                background: `color-mix(in srgb, ${HEALTH_TONE[header.health]} 6%, var(--surface))`,
              }"
            >
              <CheckCircle2 v-if="header.health === 'healthy'" class="h-3 w-3" />
              <AlertTriangle v-else-if="header.health === 'warning'" class="h-3 w-3" />
              <XCircle v-else class="h-3 w-3" />
              {{ HEALTH_LABEL[header.health] }}
            </div>

            <div class="flex items-center gap-2">
              <button
                class="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 font-mono text-[11px] uppercase tracking-wider transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                style="border-color: var(--surface-3); color: var(--ink-700); background: var(--surface-1);"
                :disabled="inflight !== null"
                :title="'Lance Discover seulement (compte les nouveautés sans rien écrire en aval)'"
                @click="triggerRun('dry')"
              >
                <Loader2 v-if="inflight === 'dry'" class="h-3 w-3 animate-spin" />
                <TestTube2 v-else class="h-3 w-3" />
                Dry run
              </button>
              <button
                class="inline-flex items-center gap-1.5 rounded-md px-3 py-1 font-mono text-[11px] uppercase tracking-wider text-white transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                style="background: var(--indigo-700);"
                :disabled="inflight !== null"
                :title="'Lance le pipeline complet (Discover → Persist → Download → Detect → Resolve → Enqueue)'"
                @click="triggerRun('run')"
              >
                <Loader2 v-if="inflight === 'run'" class="h-3 w-3 animate-spin" />
                <Play v-else class="h-3 w-3" />
                Run
              </button>
            </div>
          </div>
        </div>

        <!-- Live progress (while a run is in flight) -->
        <div
          v-if="inflight && liveRun"
          class="mt-3 flex items-center gap-2 rounded-md border px-3 py-1.5 font-mono text-[11px]"
          style="border-color: var(--indigo-500); color: var(--indigo-700); background: color-mix(in srgb, var(--indigo-500) 6%, var(--surface));"
        >
          <Loader2 class="h-3 w-3 animate-spin" />
          <span>
            Step <strong>{{ liveRun.current_step ?? '…' }}</strong>
            · raws +{{ liveRun.n_raws_added }} · crops +{{ liveRun.n_crops_added }}
            · review +{{ liveRun.n_review_enqueued }} · errors {{ liveRun.n_errors }}
          </span>
        </div>

        <!-- Trigger toast (result) -->
        <div
          v-if="lastTriggerToast && !inflight"
          class="mt-3 inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-xs"
          :style="{
            borderColor: `var(--${lastTriggerToast.tone === 'danger' ? 'danger' : lastTriggerToast.tone === 'warning' ? 'warning' : 'success'})`,
            color: `var(--${lastTriggerToast.tone === 'danger' ? 'danger' : lastTriggerToast.tone === 'warning' ? 'warning' : 'success'})`,
            background: `color-mix(in srgb, var(--${lastTriggerToast.tone === 'danger' ? 'danger' : lastTriggerToast.tone === 'warning' ? 'warning' : 'success'}) 6%, var(--surface))`,
          }"
        >
          <CheckCircle2 v-if="lastTriggerToast.tone === 'success'" class="h-3 w-3" />
          <AlertTriangle v-else-if="lastTriggerToast.tone === 'warning'" class="h-3 w-3" />
          <XCircle v-else class="h-3 w-3" />
          <span>{{ lastTriggerToast.message }}</span>
        </div>

        <!-- KPI strip -->
        <div
          class="mt-5 grid grid-cols-2 gap-x-6 gap-y-4 border-t pt-4 md:grid-cols-4"
          style="border-color: var(--surface-2);"
        >
          <div>
            <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
              Dernier fetch
            </p>
            <p class="mt-1 text-sm font-medium" style="color: var(--ink);">
              {{ formatAbsolute(header.last_run_at) }}
            </p>
            <p v-if="header.last_run_summary" class="font-mono text-[11px]" style="color: var(--ink-500);">
              {{ formatDuration(header.last_run_summary.duration_s) }} · {{ header.last_run_summary.n_calls }} calls
            </p>
          </div>
          <div>
            <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
              Δ images
            </p>
            <p class="mt-1 font-mono text-lg font-medium tabular-nums" style="color: var(--ink);">
              {{ header.last_run_summary ? `+${header.last_run_summary.n_images}` : '—' }}
            </p>
          </div>
          <div>
            <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
              Δ quotes
            </p>
            <p class="mt-1 font-mono text-lg font-medium tabular-nums" style="color: var(--ink);">
              {{ header.last_run_summary && header.last_run_summary.n_quotes > 0 ? `+${header.last_run_summary.n_quotes}` : '—' }}
            </p>
          </div>
          <div>
            <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
              Couverture
            </p>
            <p class="mt-1 font-mono text-lg font-medium tabular-nums" style="color: var(--ink);">
              {{ header.coverage_pct.toFixed(1) }}%
            </p>
            <p class="font-mono text-[11px]" style="color: var(--ink-500);">
              {{ header.coverage_label }}
            </p>
            <div
              class="mt-1.5 overflow-hidden rounded-full"
              style="height: 3px; background: var(--surface-2);"
            >
              <div
                class="h-full rounded-full transition-[width] duration-500 ease-out"
                :style="{
                  width: `${Math.min(100, header.coverage_pct)}%`,
                  background: header.coverage_pct >= 80
                    ? 'var(--success)'
                    : header.coverage_pct >= 40
                      ? 'var(--gold-600)'
                      : 'var(--ink-300)',
                }"
              />
            </div>
          </div>
        </div>

        <p
          class="mt-4 inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider"
          style="color: var(--ink-400);"
        >
          <Clock class="h-3 w-3" />
          Cadence cible · tous les {{ header.expected_cadence_days }} jours
        </p>
      </header>

      <!-- ═══ Tabs ═══ -->
      <nav
        class="mb-5 flex items-center gap-1 border-b"
        style="border-color: var(--surface-3);"
      >
        <button
          v-for="t in TABS"
          :key="t.key"
          class="-mb-px border-b-2 px-4 py-2.5 font-mono text-[11px] uppercase tracking-wider transition-colors"
          :style="{
            borderColor: activeTab === t.key ? 'var(--indigo-700)' : 'transparent',
            color: activeTab === t.key ? 'var(--indigo-700)' : 'var(--ink-500)',
          }"
          @click="activeTab = t.key"
        >
          {{ t.label }}
        </button>
      </nav>

      <!-- ═══ Tab : Runs ═══ -->
      <section v-if="activeTab === 'runs'">
        <!-- Hero last run -->
        <article
          v-if="lastRun"
          class="mb-6 rounded-lg border px-6 py-5"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <div class="flex items-start justify-between gap-6">
            <div>
              <p
                class="font-mono text-[10px] uppercase tracking-wider"
                style="color: var(--ink-500);"
              >
                <span style="color: var(--gold-600);">Dernier run</span>
                · {{ formatAbsolute(lastRun.started_at) }}
              </p>
              <div class="mt-2 flex flex-wrap items-baseline gap-x-6 gap-y-2">
                <span class="inline-flex items-baseline gap-1.5">
                  <span class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Durée</span>
                  <span class="font-mono text-base font-semibold tabular-nums" style="color: var(--ink);">
                    {{ formatDuration(lastRun.duration_s) }}
                  </span>
                </span>
                <span class="inline-flex items-baseline gap-1.5">
                  <span class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Calls</span>
                  <span class="font-mono text-base font-semibold tabular-nums" style="color: var(--ink);">
                    {{ formatNumber(lastRun.n_calls) }}
                  </span>
                </span>
                <span class="inline-flex items-baseline gap-1.5">
                  <span class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Images</span>
                  <span class="font-mono text-base font-semibold tabular-nums" style="color: var(--indigo-700);">
                    +{{ lastRun.n_images }}
                  </span>
                </span>
                <span v-if="id === 'ebay'" class="inline-flex items-baseline gap-1.5">
                  <span class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Quotes</span>
                  <span class="font-mono text-base font-semibold tabular-nums" style="color: var(--indigo-700);">
                    +{{ lastRun.n_quotes }}
                  </span>
                </span>
                <span class="inline-flex items-baseline gap-1.5">
                  <span class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Erreurs</span>
                  <span
                    class="font-mono text-base font-semibold tabular-nums"
                    :style="{ color: lastRun.n_errors > 0 ? 'var(--warning)' : 'var(--ink-400)' }"
                  >
                    {{ formatNumber(lastRun.n_errors) }}
                  </span>
                </span>
              </div>
            </div>
            <div class="flex shrink-0 flex-col items-end gap-2">
              <div
                class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-medium"
                :style="{
                  borderColor: RUN_STATUS_TONE[lastRun.status],
                  color: RUN_STATUS_TONE[lastRun.status],
                  background: `color-mix(in srgb, ${RUN_STATUS_TONE[lastRun.status]} 6%, var(--surface))`,
                }"
              >
                {{ lastRun.status }}
              </div>
              <button
                class="inline-flex items-center gap-1 rounded-md px-2 py-1 font-mono text-[11px]"
                style="background: var(--surface-1); color: var(--ink-700); border: 1px solid var(--surface-3);"
                @click="viewLog(lastRun)"
              >
                <FileText class="h-3 w-3" /> Voir log
              </button>
            </div>
          </div>
        </article>

        <!-- Runs table -->
        <div
          class="overflow-hidden rounded-lg border"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <table class="w-full text-left text-sm">
            <thead>
              <tr
                class="font-mono text-[10px] uppercase tracking-wider"
                style="background: var(--surface-1); color: var(--ink-500);"
              >
                <th class="px-4 py-2.5 font-medium">Started at</th>
                <th class="px-4 py-2.5 font-medium">Kind</th>
                <th class="px-4 py-2.5 text-right font-medium">Duration</th>
                <th class="px-4 py-2.5 text-right font-medium">Calls</th>
                <th class="px-4 py-2.5 text-right font-medium">Images</th>
                <th class="px-4 py-2.5 text-right font-medium">Quotes</th>
                <th class="px-4 py-2.5 text-right font-medium">Errors</th>
                <th class="px-4 py-2.5 font-medium">Status</th>
                <th class="px-4 py-2.5 font-medium">Filters</th>
                <th class="px-4 py-2.5 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="r in runs"
                :key="r.id"
                class="border-t"
                style="border-color: var(--surface-2);"
              >
                <td class="px-4 py-2 font-mono text-[12px] tabular-nums" style="color: var(--ink);">
                  {{ formatAbsolute(r.started_at) }}
                </td>
                <td class="px-4 py-2 text-[12px]" style="color: var(--ink-700);">
                  {{ r.kind }}
                </td>
                <td class="px-4 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink-700);">
                  {{ formatDuration(r.duration_s) }}
                </td>
                <td class="px-4 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink-700);">
                  {{ formatNumber(r.n_calls) }}
                </td>
                <td class="px-4 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink-700);">
                  {{ r.n_images || '—' }}
                </td>
                <td class="px-4 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink-700);">
                  {{ r.n_quotes || '—' }}
                </td>
                <td
                  class="px-4 py-2 text-right font-mono text-[12px] tabular-nums"
                  :style="{ color: r.n_errors > 0 ? 'var(--warning)' : 'var(--ink-400)' }"
                >
                  {{ r.n_errors || '—' }}
                </td>
                <td class="px-4 py-2 text-[12px]">
                  <span
                    class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-medium"
                    :style="{
                      color: RUN_STATUS_TONE[r.status],
                      background: `color-mix(in srgb, ${RUN_STATUS_TONE[r.status]} 8%, var(--surface))`,
                    }"
                  >
                    {{ r.status }}
                  </span>
                </td>
                <td class="px-4 py-2 font-mono text-[11px]" style="color: var(--ink-400);">
                  {{ Object.keys(r.filters).length ? JSON.stringify(r.filters) : '—' }}
                </td>
                <td class="px-4 py-2 text-right">
                  <button
                    class="inline-flex items-center gap-1 text-[11px] transition-colors"
                    style="color: var(--ink-400);"
                    @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.color = 'var(--indigo-700)')"
                    @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.color = 'var(--ink-400)')"
                    @click="viewLog(r)"
                  >
                    log <ExternalLink class="h-2.5 w-2.5" />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ═══ Tab : Données ═══ -->
      <section v-if="activeTab === 'donnees'">
        <div class="mb-4 inline-flex rounded-md border" style="border-color: var(--surface-3);">
          <button
            v-for="sub in (['images', 'quotes'] as DataSubTab[])"
            :key="sub"
            class="px-4 py-1.5 font-mono text-[11px] uppercase tracking-wider transition-colors"
            :style="{
              background: dataTab === sub ? 'var(--indigo-700)' : 'var(--surface)',
              color: dataTab === sub ? 'var(--surface)' : 'var(--ink-500)',
            }"
            @click="dataTab = sub"
          >
            {{ sub === 'images' ? 'Images' : 'Quotes' }}
          </button>
        </div>

        <!-- Images grid -->
        <div v-if="dataTab === 'images'">
          <div v-if="!images.length" class="py-12 text-center text-sm" style="color: var(--ink-400);">
            Chargement…
          </div>
          <div v-else class="grid grid-cols-4 gap-3 sm:grid-cols-6 lg:grid-cols-8">
            <article
              v-for="img in images"
              :key="img.id"
              class="group relative aspect-square overflow-hidden rounded-md border"
              style="border-color: var(--surface-3); background: var(--surface-1);"
            >
              <img
                :src="img.thumb_url"
                :alt="img.eurio_id ?? 'sans eurio_id'"
                class="h-full w-full object-cover"
              />
              <div
                class="pointer-events-none absolute inset-0 flex flex-col justify-end p-2 opacity-0 transition-opacity group-hover:opacity-100"
                style="background: linear-gradient(to top, rgba(14,14,31,.78), transparent 60%);"
              >
                <p class="font-mono text-[10px]" style="color: var(--surface);">
                  {{ img.eurio_id ?? '— sans label —' }}
                </p>
                <p class="font-mono text-[9px] opacity-80" style="color: var(--surface);">
                  q={{ img.quality_score?.toFixed(2) ?? '—' }}
                  · {{ img.training_eligible ? 'eligible' : 'excluded' }}
                </p>
              </div>
            </article>
          </div>
        </div>

        <!-- Quotes table -->
        <div v-else>
          <div
            v-if="!quotes.length"
            class="rounded-lg border-2 border-dashed px-6 py-12 text-center text-sm"
            style="border-color: var(--surface-3); color: var(--ink-400);"
          >
            <span v-if="id !== 'ebay'">Cette source ne produit pas de quotes.</span>
            <span v-else>Chargement…</span>
          </div>
          <div
            v-else
            class="overflow-hidden rounded-lg border"
            style="border-color: var(--surface-3); background: var(--surface);"
          >
            <table class="w-full text-left text-sm">
              <thead>
                <tr
                  class="font-mono text-[10px] uppercase tracking-wider"
                  style="background: var(--surface-1); color: var(--ink-500);"
                >
                  <th class="px-4 py-2.5 font-medium">eurio_id</th>
                  <th class="px-4 py-2.5 font-medium">Condition</th>
                  <th class="px-4 py-2.5 text-right font-medium">P10</th>
                  <th class="px-4 py-2.5 text-right font-medium">P50</th>
                  <th class="px-4 py-2.5 text-right font-medium">P90</th>
                  <th class="px-4 py-2.5 text-right font-medium">N</th>
                  <th class="px-4 py-2.5 font-medium">Période</th>
                  <th class="px-4 py-2.5 font-medium">Fetched</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="q in quotes"
                  :key="q.id"
                  class="border-t"
                  style="border-color: var(--surface-2);"
                >
                  <td class="px-4 py-2 font-mono text-[12px]" style="color: var(--ink);">{{ q.eurio_id }}</td>
                  <td class="px-4 py-2 text-[12px]" style="color: var(--ink-700);">{{ q.condition }}</td>
                  <td class="px-4 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink-400);">
                    {{ q.p10.toFixed(2) }}
                  </td>
                  <td class="px-4 py-2 text-right font-mono text-[12px] font-semibold tabular-nums" style="color: var(--ink);">
                    {{ q.p50.toFixed(2) }}
                  </td>
                  <td class="px-4 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink-400);">
                    {{ q.p90.toFixed(2) }}
                  </td>
                  <td class="px-4 py-2 text-right font-mono text-[12px] tabular-nums" style="color: var(--ink-700);">
                    {{ q.n }}
                  </td>
                  <td class="px-4 py-2 font-mono text-[11px]" style="color: var(--ink-500);">{{ q.period }}</td>
                  <td class="px-4 py-2 font-mono text-[11px]" style="color: var(--ink-500);">
                    {{ formatAbsolute(q.fetched_at) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <!-- ═══ Tab : Couverture ═══ -->
      <section v-if="activeTab === 'couverture' && coverage">
        <div class="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <article
            class="rounded-lg border px-6 py-5 lg:col-span-1"
            style="border-color: var(--surface-3); background: var(--surface);"
          >
            <p class="font-mono text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
              Couverture globale
            </p>
            <p class="mt-2 font-mono text-3xl font-semibold tabular-nums" style="color: var(--indigo-700);">
              {{ coverage.global.pct.toFixed(1) }}%
            </p>
            <p class="mt-1 text-sm" style="color: var(--ink-500);">
              {{ formatNumber(coverage.global.enriched) }} / {{ formatNumber(coverage.global.total) }} {{ coverage.global.unit }}
            </p>

            <div
              class="mt-4 overflow-hidden rounded-full"
              style="height: 6px; background: var(--surface-2);"
            >
              <div
                class="h-full rounded-full transition-[width] duration-500 ease-out"
                :style="{
                  width: `${Math.min(100, coverage.global.pct)}%`,
                  background: coverage.global.pct >= 80
                    ? 'var(--success)'
                    : coverage.global.pct >= 40
                      ? 'var(--gold-600)'
                      : 'var(--ink-300)',
                }"
              />
            </div>
          </article>

          <article
            class="rounded-lg border px-6 py-5 lg:col-span-2"
            style="border-color: var(--surface-3); background: var(--surface);"
          >
            <p
              class="mb-4 font-mono text-[10px] uppercase tracking-wider"
              style="color: var(--ink-500);"
            >
              Breakdown · par {{ coverage.breakdown_dimension }}
            </p>
            <div class="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 lg:grid-cols-4">
              <div v-for="b in coverage.breakdown" :key="b.key" class="text-sm">
                <div class="flex items-baseline justify-between">
                  <span class="font-mono text-[11px]" style="color: var(--ink-700);">{{ b.key }}</span>
                  <span class="font-mono text-[11px] tabular-nums" style="color: var(--ink-400);">
                    {{ b.enriched }}/{{ b.total }}
                  </span>
                </div>
                <div
                  class="mt-1 overflow-hidden rounded-full"
                  style="height: 3px; background: var(--surface-2);"
                >
                  <div
                    class="h-full rounded-full"
                    :style="{
                      width: `${b.pct}%`,
                      background: b.pct >= 80 ? 'var(--success)' : b.pct >= 40 ? 'var(--gold-600)' : 'var(--ink-300)',
                    }"
                  />
                </div>
              </div>
            </div>
          </article>
        </div>

        <article
          v-if="coverage.uncovered_eurio_ids.length"
          class="mt-6 rounded-lg border px-6 py-5"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <p
            class="mb-3 font-mono text-[10px] uppercase tracking-wider"
            style="color: var(--ink-500);"
          >
            <span style="color: var(--gold-600);">Non couvertes</span> · à cibler aux prochains runs
          </p>
          <div class="flex flex-wrap gap-2">
            <span
              v-for="eid in coverage.uncovered_eurio_ids"
              :key="eid"
              class="inline-flex items-center rounded-full border px-2.5 py-0.5 font-mono text-[10px]"
              style="border-color: var(--surface-3); background: var(--surface-1); color: var(--ink-700);"
            >
              {{ eid }}
            </span>
          </div>
        </article>
      </section>

      <!-- ═══ Tab : Commandes ═══ -->
      <section v-if="activeTab === 'commandes'">
        <p class="mb-4 max-w-2xl text-sm" style="color: var(--ink-500);">
          Les commandes ci-dessous sont les mêmes que sur la card de la page liste.
          Elles apparaissent ici avec le détail de leur <em>expected outcome</em>
          pour pouvoir les copier en pleine connaissance de cause.
        </p>

        <div class="grid gap-4 lg:grid-cols-2">
          <article
            v-for="cmd in commands"
            :key="cmd.command"
            class="rounded-lg border px-5 py-4"
            style="border-color: var(--surface-3); background: var(--surface);"
          >
            <div class="flex items-start justify-between gap-3">
              <div class="min-w-0">
                <p
                  class="inline-flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider"
                  :style="{
                    color: cmd.kind === 'reset' ? 'var(--danger)' : cmd.kind === 'dry-run' ? 'var(--gold-600)' : 'var(--indigo-700)',
                  }"
                >
                  <Terminal class="h-3 w-3" />
                  {{ cmd.kind }}
                </p>
                <h3 class="mt-1 font-display text-base font-semibold" style="color: var(--ink);">
                  {{ cmd.title }}
                </h3>
              </div>
              <button
                class="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px]"
                :style="{
                  borderColor: copiedCommand === cmd.command ? 'var(--success)' : 'var(--surface-3)',
                  color: copiedCommand === cmd.command ? 'var(--success)' : 'var(--ink-500)',
                  background: 'var(--surface-1)',
                }"
                @click="copyCommand(cmd.command)"
              >
                <ClipboardCopy class="h-3 w-3" />
                {{ copiedCommand === cmd.command ? 'Copié' : 'Copier' }}
              </button>
            </div>

            <pre
              class="mt-3 overflow-x-auto rounded-md px-3 py-2 font-mono text-[12px]"
              style="background: var(--ink); color: var(--surface);"
            ><code>{{ cmd.command }}</code></pre>

            <p class="mt-3 text-[12px]" style="color: var(--ink-700);">
              {{ cmd.description }}
            </p>
            <p
              class="mt-2 inline-flex items-start gap-1.5 text-[11px]"
              style="color: var(--ink-500);"
            >
              <ChevronRight class="mt-0.5 h-3 w-3 shrink-0" style="color: var(--gold-600);" />
              <span>
                <strong style="color: var(--ink-700);">Effet attendu&nbsp;:</strong>
                {{ cmd.expected_outcome }}
              </span>
            </p>
            <p
              v-if="cmd.kind === 'reset'"
              class="mt-2 inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-[11px]"
              style="background: color-mix(in srgb, var(--danger) 8%, var(--surface)); color: var(--danger);"
            >
              <AlertTriangle class="h-3 w-3" />
              Commande destructive — vérifier avant exécution
            </p>
          </article>
        </div>

        <div
          v-if="!commands.length"
          class="rounded-lg border-2 border-dashed px-6 py-12 text-center text-sm"
          style="border-color: var(--surface-3); color: var(--ink-400);"
        >
          Aucune commande déclarée pour cette source.
        </div>
      </section>
    </template>

    <div v-else-if="!loadError" class="py-16 text-center text-sm" style="color: var(--ink-400);">
      Chargement…
    </div>
  </div>
</template>
