<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Activity, AlertCircle, Boxes, FlaskConical, RefreshCw, Wifi, WifiOff } from 'lucide-vue-next'
import { checkMlApi } from '@/features/training/composables/useTrainingApi'
import {
  fetchCohorts,
  fetchDiversity,
  fetchPulse,
  fetchReadiness,
  type CohortResponse,
  type DiversityResponse,
  type PulseResponse,
  type ReadinessResponse,
  type Tier,
} from '../composables/useOperationsApi'

// ─── State ─────────────────────────────────────────────────────────────

const apiStatus = ref<'checking' | 'online' | 'offline'>('checking')
const loadError = ref<string | null>(null)
const loading = ref(false)

const pulse = ref<PulseResponse | null>(null)
const readiness = ref<ReadinessResponse | null>(null)
const diversity = ref<DiversityResponse | null>(null)
const cohorts = ref<CohortResponse | null>(null)

const tierFilter = ref<Tier | 'all'>('red')

// ─── Loaders ───────────────────────────────────────────────────────────

async function refreshAll() {
  loading.value = true
  loadError.value = null
  try {
    const [p, r, d, c] = await Promise.all([
      fetchPulse(7),
      fetchReadiness({ limit: 1000 }),
      fetchDiversity(),
      fetchCohorts(),
    ])
    pulse.value = p
    readiness.value = r
    diversity.value = d
    cohorts.value = c
  } catch (err) {
    loadError.value = err instanceof Error ? err.message : 'Erreur de chargement'
  } finally {
    loading.value = false
  }
}

async function refreshHealth() {
  apiStatus.value = 'checking'
  apiStatus.value = (await checkMlApi()) ? 'online' : 'offline'
}

onMounted(async () => {
  await refreshHealth()
  if (apiStatus.value === 'online') await refreshAll()
})

// ─── Derived ───────────────────────────────────────────────────────────

const pulseDailyTotals = computed(() => {
  if (!pulse.value) return []
  const map = new Map<string, { day: string; kept: number; raw: number; searches: number }>()
  for (const d of pulse.value.days) {
    const cur = map.get(d.day) ?? { day: d.day, kept: 0, raw: 0, searches: 0 }
    cur.kept += d.kept
    cur.raw += d.raw
    cur.searches += d.searches
    map.set(d.day, cur)
  }
  // Fill last 7 days even if 0
  const out: { day: string; kept: number; raw: number; searches: number }[] = []
  const today = new Date()
  for (let i = 6; i >= 0; i--) {
    const d = new Date(today)
    d.setDate(today.getDate() - i)
    const key = d.toISOString().slice(0, 10)
    out.push(map.get(key) ?? { day: key, kept: 0, raw: 0, searches: 0 })
  }
  return out
})

const maxDailyKept = computed(() =>
  Math.max(1, ...pulseDailyTotals.value.map((d) => d.kept)),
)

const filteredClasses = computed(() => {
  if (!readiness.value) return []
  if (tierFilter.value === 'all') return readiness.value.classes
  return readiness.value.classes.filter((c) => c.tier === tierFilter.value)
})

const maxHistogramCount = computed(() =>
  readiness.value
    ? Math.max(1, ...readiness.value.summary.histogram.map((b) => b.count))
    : 1,
)

function tierColor(t: Tier): string {
  if (t === 'green') return 'var(--success)'
  if (t === 'warn') return 'var(--warning, #d97706)'
  return 'var(--danger)'
}

function tierLabel(t: Tier): string {
  if (t === 'green') return '≥ 30'
  if (t === 'warn') return '5-29'
  return '< 5'
}

function fmtDate(s: string): string {
  return s.slice(5) // MM-DD
}

function fmtDateTime(s: string | null): string {
  if (!s) return '—'
  const d = new Date(s.replace(' ', 'T') + 'Z')
  if (isNaN(d.getTime())) return s
  const now = Date.now()
  const diffMin = Math.round((now - d.getTime()) / 60000)
  if (diffMin < 60) return `il y a ${diffMin}min`
  if (diffMin < 60 * 24) return `il y a ${Math.round(diffMin / 60)}h`
  return `il y a ${Math.round(diffMin / 60 / 24)}j`
}
</script>

<template>
  <div class="p-8">
    <!-- ═══ Header ═══ -->
    <header class="mb-6 flex items-start justify-between">
      <div>
        <h1
          class="font-display text-2xl italic font-semibold"
          style="color: var(--indigo-700);"
        >
          Operations
        </h1>
        <p class="mt-0.5 text-sm" style="color: var(--ink-500);">
          Pulse scrape, training-ready, diversité, cohortes
          <span
            class="ml-2 rounded-sm px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider"
            style="background: var(--surface-1); color: var(--ink-500); border: 1px solid var(--surface-3);"
          >
            J1 · MVP
          </span>
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
        <button
          v-if="apiStatus === 'online'"
          class="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium"
          style="border-color: var(--surface-3); color: var(--ink-500);"
          :disabled="loading"
          @click="refreshAll"
        >
          <RefreshCw class="h-3 w-3" :class="{ 'animate-spin': loading }" /> Refresh
        </button>
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
        ML API non jointe (http://127.0.0.1:8042)
      </p>
      <p class="mt-1 text-xs" style="color: var(--ink-500);">
        Lance
        <code style="background: var(--surface-1); padding: 1px 4px; border-radius: 3px;">go-task ml:api</code>
        puis clique sur réessayer.
      </p>
      <button
        class="mt-3 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium"
        style="background: var(--ink); color: var(--surface);"
        @click="refreshHealth"
      >
        <RefreshCw class="h-3 w-3" /> Réessayer
      </button>
    </div>

    <div
      v-if="loadError"
      class="mb-6 rounded-lg border px-5 py-3 text-sm"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);"
    >
      <AlertCircle class="mr-1 inline-block h-4 w-4 -mt-0.5" />
      {{ loadError }}
    </div>

    <template v-if="apiStatus === 'online' && pulse && readiness && diversity && cohorts">
      <!-- ════════════════════════════════════════════════════════════ -->
      <!-- ═══  Section 1 — PULSE eBay                                ═══ -->
      <!-- ════════════════════════════════════════════════════════════ -->
      <section class="mb-8">
        <h2
          class="mb-3 flex items-baseline gap-2 font-mono text-xs uppercase tracking-wider"
          style="color: var(--ink-500);"
        >
          <Activity class="h-3.5 w-3.5" style="color: var(--indigo-700);" />
          <span style="color: var(--indigo-700);">Pulse eBay</span>
          <span class="opacity-60">· {{ pulse.window_days }} derniers jours</span>
        </h2>

        <div
          class="rounded-lg border p-5"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <!-- Daily bars (totals across marketplaces) -->
          <div class="mb-5">
            <div class="mb-2 text-xs font-medium" style="color: var(--ink-500);">
              Items conservés par jour
            </div>
            <div class="flex items-end gap-2" style="height: 88px;">
              <div
                v-for="d in pulseDailyTotals"
                :key="d.day"
                class="flex flex-1 flex-col items-center justify-end"
              >
                <div
                  class="text-[10px] font-mono"
                  style="color: var(--ink-500);"
                >
                  {{ d.kept || '' }}
                </div>
                <div
                  class="w-full rounded-t-sm transition-all"
                  :style="{
                    height: `${(d.kept / maxDailyKept) * 60}px`,
                    background: d.kept ? 'var(--indigo-700)' : 'var(--surface-3)',
                    minHeight: d.kept ? '2px' : '2px',
                  }"
                ></div>
                <div class="mt-1 text-[10px] font-mono" style="color: var(--ink-500);">
                  {{ fmtDate(d.day) }}
                </div>
              </div>
            </div>
          </div>

          <!-- Per-marketplace totals -->
          <div class="grid grid-cols-1 gap-2 lg:grid-cols-2">
            <div
              v-for="m in pulse.by_marketplace"
              :key="m.marketplace"
              class="rounded-md border px-3 py-2 text-sm"
              style="border-color: var(--surface-3);"
            >
              <div class="flex items-center justify-between">
                <span class="font-mono text-xs font-semibold">{{ m.marketplace }}</span>
                <span class="font-mono text-xs" style="color: var(--ink-500);">
                  recall {{ m.recall_pct.toFixed(0) }}%
                </span>
              </div>
              <div class="mt-1 text-xs" style="color: var(--ink-500);">
                {{ m.searches }} searches → {{ m.kept }} kept ({{ m.raw }} raw)
              </div>
            </div>
            <div
              v-if="!pulse.by_marketplace.length"
              class="rounded-md border-2 border-dashed px-3 py-4 text-center text-xs"
              style="border-color: var(--surface-3); color: var(--ink-500);"
            >
              Aucune passe sur les {{ pulse.window_days }} derniers jours.
            </div>
          </div>

          <!-- Last run -->
          <div class="mt-4 flex items-center justify-between text-xs" style="color: var(--ink-500);">
            <div>
              Dernière exécution :
              <strong style="color: var(--ink);">{{ fmtDateTime(pulse.last_run.started_at) }}</strong>
              <span v-if="pulse.last_run.run_id" class="ml-2 font-mono">
                · run_id {{ pulse.last_run.run_id.slice(0, 8) }}
              </span>
              <span
                v-if="pulse.last_run.status"
                class="ml-2 rounded-sm px-1.5 py-0.5 font-mono text-[10px]"
                :style="{
                  background: pulse.last_run.status === 'success'
                    ? 'color-mix(in srgb, var(--success) 12%, var(--surface))'
                    : 'color-mix(in srgb, var(--warning, #d97706) 12%, var(--surface))',
                  color: pulse.last_run.status === 'success'
                    ? 'var(--success)' : 'var(--warning, #d97706)',
                }"
              >
                {{ pulse.last_run.status }}
              </span>
            </div>
            <router-link
              to="/sources/ebay"
              class="hover:underline"
              style="color: var(--indigo-700);"
            >
              Voir runs →
            </router-link>
          </div>
        </div>
      </section>

      <!-- ════════════════════════════════════════════════════════════ -->
      <!-- ═══  Section 2 — Training readiness                        ═══ -->
      <!-- ════════════════════════════════════════════════════════════ -->
      <section class="mb-8">
        <h2
          class="mb-3 flex items-baseline gap-2 font-mono text-xs uppercase tracking-wider"
          style="color: var(--ink-500);"
        >
          <Boxes class="h-3.5 w-3.5" style="color: var(--indigo-700);" />
          <span style="color: var(--indigo-700);">Training readiness</span>
          <span class="opacity-60">· seuil {{ readiness.summary.threshold }} sources / classe</span>
        </h2>

        <div
          class="rounded-lg border p-5"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <!-- Tier summary bandeau -->
          <div class="mb-4 grid grid-cols-3 gap-2">
            <button
              v-for="t in (['green', 'warn', 'red'] as Tier[])"
              :key="t"
              class="rounded-md border px-3 py-2 text-left transition-all"
              :style="{
                borderColor: tierFilter === t ? tierColor(t) : 'var(--surface-3)',
                background: tierFilter === t
                  ? `color-mix(in srgb, ${tierColor(t)} 8%, var(--surface))`
                  : 'var(--surface)',
              }"
              @click="tierFilter = tierFilter === t ? 'all' : t"
            >
              <div class="flex items-center justify-between">
                <span class="font-mono text-xs font-semibold" :style="{ color: tierColor(t) }">
                  {{ t === 'green' ? '✅ ≥ 30' : t === 'warn' ? '⚠️ 5-29' : '🔴 < 5' }}
                </span>
                <span class="font-mono text-lg font-bold" style="color: var(--ink);">
                  {{ t === 'green' ? readiness.summary.n_green
                     : t === 'warn' ? readiness.summary.n_warn
                     : readiness.summary.n_red }}
                </span>
              </div>
              <div class="mt-0.5 text-[10px]" style="color: var(--ink-500);">
                {{
                  Math.round(
                    ((t === 'green' ? readiness.summary.n_green
                      : t === 'warn' ? readiness.summary.n_warn
                      : readiness.summary.n_red) / readiness.summary.n_classes) * 100
                  )
                }}% sur {{ readiness.summary.n_classes }} classes
              </div>
            </button>
          </div>

          <!-- Histogram -->
          <div class="mb-5">
            <div class="mb-2 text-xs font-medium" style="color: var(--ink-500);">
              Distribution
            </div>
            <div class="space-y-1">
              <div
                v-for="b in readiness.summary.histogram"
                :key="b.bucket"
                class="flex items-center gap-2 text-xs"
              >
                <div class="w-16 font-mono text-right" style="color: var(--ink-500);">
                  {{ b.bucket }}
                </div>
                <div class="flex-1">
                  <div
                    class="h-4 rounded-sm"
                    :style="{
                      width: `${(b.count / maxHistogramCount) * 100}%`,
                      minWidth: b.count ? '2px' : '0',
                      background: b.lo >= 30
                        ? 'var(--success)'
                        : b.lo >= 5
                          ? 'var(--warning, #d97706)'
                          : 'var(--danger)',
                      opacity: b.count ? 0.7 : 0,
                    }"
                  ></div>
                </div>
                <div class="w-12 font-mono text-right">{{ b.count }}</div>
              </div>
            </div>
          </div>

          <!-- Table -->
          <div>
            <div class="mb-2 flex items-center justify-between text-xs">
              <span style="color: var(--ink-500);">
                {{ tierFilter === 'all' ? 'Toutes les classes' : `Classes ${tierLabel(tierFilter as Tier)} (priorité scrape)` }}
                · {{ filteredClasses.length }} affichées
              </span>
              <button
                v-if="tierFilter !== 'all'"
                class="hover:underline"
                style="color: var(--indigo-700);"
                @click="tierFilter = 'all'"
              >
                Tout afficher
              </button>
            </div>
            <div
              class="rounded-md border overflow-hidden"
              style="border-color: var(--surface-3);"
            >
              <div class="max-h-96 overflow-auto">
                <table class="w-full text-sm">
                  <thead
                    class="sticky top-0 text-xs uppercase font-mono"
                    style="background: var(--surface-1); color: var(--ink-500);"
                  >
                    <tr>
                      <th class="px-3 py-2 text-left">Classe</th>
                      <th class="px-3 py-2 text-left">Pays · année</th>
                      <th class="px-3 py-2 text-right">canon</th>
                      <th class="px-3 py-2 text-right">wild</th>
                      <th class="px-3 py-2 text-right">total</th>
                      <th class="px-3 py-2 text-center">tier</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="c in filteredClasses.slice(0, 200)"
                      :key="c.class_id"
                      class="border-t"
                      style="border-color: var(--surface-2);"
                    >
                      <td class="px-3 py-1.5 font-mono text-xs">
                        <router-link
                          :to="`/coins/${c.eurio_ids[0]}`"
                          class="hover:underline"
                          style="color: var(--indigo-700);"
                        >
                          {{ c.class_id }}
                        </router-link>
                      </td>
                      <td class="px-3 py-1.5 text-xs" style="color: var(--ink-500);">
                        {{ c.country || '—' }} · {{ c.year || '—' }}
                      </td>
                      <td class="px-3 py-1.5 text-right font-mono text-xs">{{ c.n_canon }}</td>
                      <td class="px-3 py-1.5 text-right font-mono text-xs">{{ c.n_wild }}</td>
                      <td class="px-3 py-1.5 text-right font-mono text-xs font-semibold">
                        {{ c.n_total }}
                      </td>
                      <td class="px-3 py-1.5 text-center">
                        <span
                          class="inline-block rounded-full px-2 py-0.5 text-[10px] font-mono"
                          :style="{
                            background: `color-mix(in srgb, ${tierColor(c.tier)} 12%, var(--surface))`,
                            color: tierColor(c.tier),
                          }"
                        >
                          {{ tierLabel(c.tier) }}
                        </span>
                      </td>
                    </tr>
                    <tr v-if="!filteredClasses.length">
                      <td colspan="6" class="px-3 py-6 text-center text-xs" style="color: var(--ink-500);">
                        Aucune classe dans ce tier.
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div
                v-if="filteredClasses.length > 200"
                class="border-t px-3 py-2 text-center text-xs"
                style="border-color: var(--surface-2); color: var(--ink-500);"
              >
                {{ filteredClasses.length - 200 }} autres classes non affichées
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ════════════════════════════════════════════════════════════ -->
      <!-- ═══  Section 3 — Diversité wild                            ═══ -->
      <!-- ════════════════════════════════════════════════════════════ -->
      <section class="mb-8">
        <h2
          class="mb-3 flex items-baseline gap-2 font-mono text-xs uppercase tracking-wider"
          style="color: var(--ink-500);"
        >
          <Boxes class="h-3.5 w-3.5" style="color: var(--indigo-700);" />
          <span style="color: var(--indigo-700);">Diversité wild</span>
          <span class="opacity-60">· marketplaces contribuant par classe</span>
        </h2>

        <div
          class="rounded-lg border p-5"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <div class="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <div>
              <div class="mb-2 text-xs font-medium" style="color: var(--ink-500);">
                Distribution n_marketplaces / classe
              </div>
              <div class="space-y-1">
                <div
                  v-for="b in diversity.buckets"
                  :key="b.n_marketplaces"
                  class="flex items-center gap-2 text-xs"
                >
                  <div class="w-32 text-right" style="color: var(--ink-500);">
                    {{ b.n_marketplaces }} marketplace{{ b.n_marketplaces > 1 ? 's' : '' }}
                  </div>
                  <div class="flex-1">
                    <div
                      class="h-3 rounded-sm"
                      :style="{
                        width: `${(b.n_classes / (diversity.buckets[0]?.n_classes || 1)) * 100}%`,
                        background: b.n_marketplaces === 0
                          ? 'var(--danger)'
                          : b.n_marketplaces >= 2
                            ? 'var(--success)'
                            : 'var(--warning, #d97706)',
                        opacity: 0.7,
                      }"
                    ></div>
                  </div>
                  <div class="w-12 font-mono text-right">{{ b.n_classes }}</div>
                </div>
              </div>
              <div
                v-if="diversity.suspicious_singletons > 0"
                class="mt-3 rounded-md border px-3 py-2 text-xs"
                style="border-color: var(--warning, #d97706); background: color-mix(in srgb, var(--warning, #d97706) 4%, var(--surface)); color: var(--warning, #d97706);"
              >
                <AlertCircle class="mr-1 inline-block h-3.5 w-3.5 -mt-0.5" />
                {{ diversity.suspicious_singletons }} classe(s) ≥30 wild mais 1 seul marketplace
                — risque over-fit sourcing
              </div>
            </div>

            <div>
              <div class="mb-2 text-xs font-medium" style="color: var(--ink-500);">
                Top marketplaces (7j)
              </div>
              <div class="space-y-1">
                <div
                  v-for="m in diversity.top_marketplaces_7d"
                  :key="m.marketplace"
                  class="flex items-center justify-between text-xs"
                >
                  <span class="font-mono">{{ m.marketplace }}</span>
                  <span class="font-mono" style="color: var(--ink-500);">{{ m.kept }} items</span>
                </div>
                <div
                  v-if="!diversity.top_marketplaces_7d.length"
                  class="text-xs italic"
                  style="color: var(--ink-500);"
                >
                  Aucun item dans la fenêtre 7j.
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ════════════════════════════════════════════════════════════ -->
      <!-- ═══  Section 4 — Bench cohort                              ═══ -->
      <!-- ════════════════════════════════════════════════════════════ -->
      <section class="mb-8">
        <h2
          class="mb-3 flex items-baseline gap-2 font-mono text-xs uppercase tracking-wider"
          style="color: var(--ink-500);"
        >
          <FlaskConical class="h-3.5 w-3.5" style="color: var(--indigo-700);" />
          <span style="color: var(--indigo-700);">Bench cohort</span>
          <span class="opacity-60">· statut des cohortes physiques</span>
        </h2>

        <div
          class="rounded-lg border p-5"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <div class="mb-4 grid grid-cols-2 gap-2">
            <div
              class="rounded-md border px-3 py-2"
              style="border-color: var(--surface-3);"
            >
              <div class="text-xs" style="color: var(--ink-500);">Frozen (prêtes bench)</div>
              <div class="font-mono text-lg font-bold" style="color: var(--success);">
                {{ cohorts.n_frozen }}
              </div>
            </div>
            <div
              class="rounded-md border px-3 py-2"
              style="border-color: var(--surface-3);"
            >
              <div class="text-xs" style="color: var(--ink-500);">Draft (en cours)</div>
              <div class="font-mono text-lg font-bold" style="color: var(--warning, #d97706);">
                {{ cohorts.n_draft }}
              </div>
            </div>
          </div>

          <div
            class="rounded-md border overflow-hidden"
            style="border-color: var(--surface-3);"
          >
            <table class="w-full text-sm">
              <thead
                class="text-xs uppercase font-mono"
                style="background: var(--surface-1); color: var(--ink-500);"
              >
                <tr>
                  <th class="px-3 py-2 text-left">Cohort</th>
                  <th class="px-3 py-2 text-left">Status</th>
                  <th class="px-3 py-2 text-left">Zone</th>
                  <th class="px-3 py-2 text-right">Members</th>
                  <th class="px-3 py-2 text-left">Frozen at</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="c in cohorts.cohorts"
                  :key="c.id"
                  class="border-t"
                  style="border-color: var(--surface-2);"
                >
                  <td class="px-3 py-1.5">
                    <router-link
                      :to="`/lab/cohorts/${c.id}`"
                      class="hover:underline"
                      style="color: var(--indigo-700);"
                    >
                      {{ c.name }}
                    </router-link>
                  </td>
                  <td class="px-3 py-1.5">
                    <span
                      class="inline-block rounded-full px-2 py-0.5 text-[10px] font-mono"
                      :style="{
                        background: c.status === 'frozen'
                          ? 'color-mix(in srgb, var(--success) 12%, var(--surface))'
                          : 'color-mix(in srgb, var(--warning, #d97706) 12%, var(--surface))',
                        color: c.status === 'frozen' ? 'var(--success)' : 'var(--warning, #d97706)',
                      }"
                    >
                      {{ c.status }}
                    </span>
                  </td>
                  <td class="px-3 py-1.5 text-xs" style="color: var(--ink-500);">
                    {{ c.zone || '—' }}
                  </td>
                  <td class="px-3 py-1.5 text-right font-mono text-xs">{{ c.n_members }}</td>
                  <td class="px-3 py-1.5 text-xs" style="color: var(--ink-500);">
                    {{ c.frozen_at || '—' }}
                  </td>
                </tr>
                <tr v-if="!cohorts.cohorts.length">
                  <td colspan="5" class="px-3 py-6 text-center text-xs" style="color: var(--ink-500);">
                    Aucune cohorte créée.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <p class="mt-3 text-[11px] italic" style="color: var(--ink-500);">
            Note : le comptage des captures vit sur le filesystem
            (<code style="background: var(--surface-1); padding: 1px 4px; border-radius: 3px;">ml/datasets/&lt;numista_id&gt;/captures/</code>),
            non centralisé. À ajouter dans un chunk séparé.
          </p>
        </div>
      </section>
    </template>
  </div>
</template>
