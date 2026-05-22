<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  Download,
  ExternalLink,
  Filter,
  Loader2,
  Package,
  Radar,
  Scissors,
  Trash2,
  X,
  XCircle,
} from 'lucide-vue-next'
import {
  assetFileUrl,
  fetchRunListings,
  rawFileUrl,
  RunListingsError,
  type RouteDecision,
  type RunListings,
} from '../composables/useRunListings'
import {
  fetchRunSearches,
  type DiscoverySearchItem,
  type RunSearches,
} from '../composables/useRunSearches'
import {
  fetchRunDiscarded,
  reasonLabel,
  reasonTone,
  type DiscardedListing,
  type RunDiscarded,
} from '../composables/useRunDiscarded'
import type { SourceId } from '../composables/useSourcesApi'

const route = useRoute()
const router = useRouter()

const sourceId = computed(() => route.params.id as SourceId)
const runId = computed(() => route.params.run_id as string)
const eurioFilter = computed(() => (route.query.eurio_id as string | undefined) || null)

const data = ref<RunListings | null>(null)
const searchesData = ref<RunSearches | null>(null)
const discardedData = ref<RunDiscarded | null>(null)
const loading = ref(true)
const errorMsg = ref<string | null>(null)

async function load() {
  loading.value = true
  errorMsg.value = null
  try {
    const [listings, searches, discarded] = await Promise.all([
      fetchRunListings(sourceId.value, runId.value, eurioFilter.value),
      fetchRunSearches(sourceId.value, runId.value, eurioFilter.value).catch(() => null),
      fetchRunDiscarded(sourceId.value, runId.value, { eurio_id: eurioFilter.value }).catch(() => null),
    ])
    data.value = listings
    searchesData.value = searches
    discardedData.value = discarded
  } catch (err) {
    if (err instanceof RunListingsError && err.status === 404) {
      errorMsg.value = `Run introuvable : ${runId.value}`
    } else {
      errorMsg.value = err instanceof Error ? err.message : String(err)
    }
    data.value = null
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch([sourceId, runId, eurioFilter], load)

// ─── Discovery searches helpers ─────────────────────────────────────────

const searchesOpen = ref(false)
const expandedSearchIds = ref<Set<string>>(new Set())

function toggleSearches() {
  searchesOpen.value = !searchesOpen.value
}

function toggleSearch(id: string) {
  if (expandedSearchIds.value.has(id)) expandedSearchIds.value.delete(id)
  else expandedSearchIds.value.add(id)
  // Trigger reactivity on Set:
  expandedSearchIds.value = new Set(expandedSearchIds.value)
}

const searchesSummary = computed(() => {
  const items = searchesData.value?.searches ?? []
  let nSuccess = 0
  let nEmpty = 0
  let nFailed = 0
  let nSummaries = 0   // N0 — eBay brut
  let nAfterGroups = 0 // N1 — post-getItemsByGroup
  let nRaw = 0         // N2 — post-theme drop
  let nKept = 0        // N3 — post-accept_listing
  for (const s of items) {
    if (s.status === 'success') nSuccess++
    else if (s.status === 'empty') nEmpty++
    else if (s.status === 'failed') nFailed++
    // Compat : si N0/N1 ne sont pas remplis (anciens runs), on retombe
    // sur n_raw_results pour ne pas afficher 0 partout.
    nSummaries += s.n_summaries ?? s.n_raw_results ?? 0
    nAfterGroups += s.n_after_groups ?? s.n_raw_results ?? 0
    nRaw += s.n_raw_results ?? 0
    nKept += s.n_kept_results ?? 0
  }
  return {
    total: items.length,
    nSuccess,
    nEmpty,
    nFailed,
    nSummaries,
    nAfterGroups,
    nRaw,
    nKept,
  }
})

const SEARCH_TONE: Record<DiscoverySearchItem['status'], string> = {
  success: 'var(--success)',
  empty: 'var(--warning)',
  failed: 'var(--danger)',
}

/** Périmètre d'une discovery search : groupe `(dénom · pays · année)`
 *  pour la découverte groupée, sinon l'eurio_id ciblé (legacy per-pièce),
 *  sinon '—'. Le groupe vit dans `query_filters.group` (cf. adapter eBay). */
function searchScopeLabel(s: DiscoverySearchItem): string {
  const g = (s.query_filters?.group ?? null) as
    | { denomination?: number; country?: string; year?: number }
    | null
  if (g && g.country && g.year != null) {
    const denom = g.denomination != null ? `${g.denomination}€` : '?'
    return `${denom} · ${g.country} · ${g.year}`
  }
  return s.target_eurio_id || '—'
}

// Feedback éphémère du bouton « copier » sur le browse_url.
const copiedUrlSearchId = ref<string | null>(null)
async function copyBrowseUrl(s: DiscoverySearchItem) {
  if (!s.browse_url) return
  await navigator.clipboard.writeText(s.browse_url)
  copiedUrlSearchId.value = s.id
  setTimeout(() => {
    if (copiedUrlSearchId.value === s.id) copiedUrlSearchId.value = null
  }, 1500)
}

// ─── Discarded listings helpers ──────────────────────────────────────────

const discardedOpen = ref(false)
const expandedDiscardedIds = ref<Set<string>>(new Set())
const reasonFilter = ref<string | null>(null)

function toggleDiscarded() {
  discardedOpen.value = !discardedOpen.value
}

function toggleDiscardedRow(id: string) {
  if (expandedDiscardedIds.value.has(id)) expandedDiscardedIds.value.delete(id)
  else expandedDiscardedIds.value.add(id)
  expandedDiscardedIds.value = new Set(expandedDiscardedIds.value)
}

function selectReason(reason: string | null) {
  reasonFilter.value = reasonFilter.value === reason ? null : reason
}

const filteredDiscarded = computed<DiscardedListing[]>(() => {
  const items = discardedData.value?.listings ?? []
  if (!reasonFilter.value) return items
  return items.filter((d) => d.reason === reasonFilter.value)
})

// ─── Counters ───────────────────────────────────────────────────────────

interface Counters {
  total: number
  downloadSuccess: number
  downloadFailed: number
  cropSuccess: number
  cropZero: number
  cropError: number
  routeAuto: number
  routeReviewLot: number
  routeReviewSingle: number
  routePending: number
  routeRejected: number
}

const counters = computed<Counters>(() => {
  const acc: Counters = {
    total: 0,
    downloadSuccess: 0,
    downloadFailed: 0,
    cropSuccess: 0,
    cropZero: 0,
    cropError: 0,
    routeAuto: 0,
    routeReviewLot: 0,
    routeReviewSingle: 0,
    routePending: 0,
    routeRejected: 0,
  }
  for (const l of data.value?.listings ?? []) {
    acc.total++
    if (l.download_status === 'success') acc.downloadSuccess++
    else if (l.download_status === 'failed') acc.downloadFailed++
    if (l.crop_status === 'success') acc.cropSuccess++
    else if (l.crop_status === 'zero_crops') acc.cropZero++
    else if (l.crop_status === 'error') acc.cropError++
    switch (l.route_decision) {
      case 'auto_resolved': acc.routeAuto++; break
      case 'review_lot': acc.routeReviewLot++; break
      case 'review_single': acc.routeReviewSingle++; break
      case 'pending': acc.routePending++; break
      case 'rejected': acc.routeRejected++; break
    }
  }
  return acc
})

// ─── Helpers ────────────────────────────────────────────────────────────

const ROUTE_TONE: Record<NonNullable<RouteDecision>, string> = {
  auto_resolved: 'var(--success)',
  review_lot: 'var(--gold-600)',
  review_single: 'var(--gold-600)',
  pending: 'var(--ink-400)',
  rejected: 'var(--danger)',
}

const ROUTE_LABEL: Record<NonNullable<RouteDecision>, string> = {
  auto_resolved: 'auto',
  review_lot: 'review · lot',
  review_single: 'review · single',
  pending: 'pending',
  rejected: 'rejected',
}

function formatPrice(p: number | null, c: string | null): string {
  if (p == null) return '—'
  const cur = c || 'EUR'
  return `${p.toFixed(2)} ${cur}`
}

function shortenUrl(u: string | null): string {
  if (!u) return ''
  try {
    const x = new URL(u)
    return `${x.host}${x.pathname.length > 32 ? x.pathname.slice(0, 32) + '…' : x.pathname}`
  } catch {
    return u.length > 60 ? u.slice(0, 60) + '…' : u
  }
}

function clearFilter() {
  router.replace({ path: route.path, query: {} })
}
</script>

<template>
  <div class="p-8">
    <button
      class="mb-4 inline-flex items-center gap-1.5 text-xs transition-colors"
      style="color: var(--ink-400);"
      @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.color = 'var(--indigo-700)')"
      @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.color = 'var(--ink-400)')"
      @click="router.push(`/sources/${sourceId}/runs/${runId}`)"
    >
      <ArrowLeft class="h-3 w-3" />
      Retour au breakdown
    </button>

    <div
      v-if="loading"
      class="flex items-center gap-2 py-16 text-sm"
      style="color: var(--ink-400);"
    >
      <Loader2 class="h-4 w-4 animate-spin" /> Chargement des listings…
    </div>

    <div
      v-else-if="errorMsg"
      class="rounded-lg border px-5 py-3 text-sm"
      style="border-color: var(--danger); background: color-mix(in srgb, var(--danger) 4%, var(--surface)); color: var(--danger);"
    >
      {{ errorMsg }}
    </div>

    <template v-else-if="data">
      <!-- Header -->
      <header
        class="mb-6 rounded-lg border px-6 py-5"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <div class="flex flex-wrap items-start justify-between gap-6">
          <div class="min-w-0 flex-1">
            <p
              class="font-mono text-[10px] uppercase tracking-wider"
              style="color: var(--ink-500);"
            >
              Run · <span style="color: var(--gold-600);">{{ data.source_id }}</span>
              · listings debug
            </p>
            <h1
              class="mt-1 font-mono text-base font-semibold leading-tight"
              style="color: var(--ink);"
            >
              {{ data.run_id }}
            </h1>
            <div
              v-if="eurioFilter"
              class="mt-3 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[11px]"
              style="border-color: var(--indigo-700); color: var(--indigo-700); background: color-mix(in srgb, var(--indigo-700) 6%, var(--surface));"
            >
              filtré · {{ eurioFilter }}
              <button
                class="-mr-1 ml-1 rounded-full p-0.5 transition-colors"
                style="color: var(--indigo-700);"
                @click="clearFilter"
                @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'color-mix(in srgb, var(--indigo-700) 12%, transparent)')"
                @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
                title="Voir tous les listings du run"
              >
                <X class="h-3 w-3" />
              </button>
            </div>
          </div>
        </div>

        <!-- Counters bar -->
        <div
          class="mt-5 flex flex-wrap gap-x-6 gap-y-2 font-mono text-[11px]"
          style="color: var(--ink-500);"
        >
          <span>
            <span style="color: var(--ink-400);">total&nbsp;:</span>
            <span style="color: var(--ink);">{{ counters.total }}</span>
          </span>
          <span>
            <Download class="inline h-3 w-3" />
            <span class="ml-1" style="color: var(--success);">{{ counters.downloadSuccess }} ok</span>
            <span v-if="counters.downloadFailed > 0" class="ml-1.5" style="color: var(--danger);">{{ counters.downloadFailed }} fail</span>
          </span>
          <span>
            <Scissors class="inline h-3 w-3" />
            <span class="ml-1" style="color: var(--success);">{{ counters.cropSuccess }} ok</span>
            <span v-if="counters.cropZero > 0" class="ml-1.5" style="color: var(--warning);">{{ counters.cropZero }} 0-crops</span>
            <span v-if="counters.cropError > 0" class="ml-1.5" style="color: var(--danger);">{{ counters.cropError }} err</span>
          </span>
          <span>
            <span style="color: var(--ink-400);">route&nbsp;:</span>
            <span v-if="counters.routeAuto > 0" class="ml-1" style="color: var(--success);">{{ counters.routeAuto }} auto</span>
            <span v-if="counters.routeReviewLot > 0" class="ml-1.5" style="color: var(--gold-600);">{{ counters.routeReviewLot }} rev.lot</span>
            <span v-if="counters.routeReviewSingle > 0" class="ml-1.5" style="color: var(--gold-600);">{{ counters.routeReviewSingle }} rev.single</span>
            <span v-if="counters.routePending > 0" class="ml-1.5" style="color: var(--ink-400);">{{ counters.routePending }} pending</span>
            <span v-if="counters.routeRejected > 0" class="ml-1.5" style="color: var(--danger);">{{ counters.routeRejected }} rejected</span>
          </span>
        </div>
      </header>

      <!-- Discovery searches (collapsible, toujours visible si on a des searches) -->
      <section
        v-if="searchesData && searchesData.searches.length"
        class="mb-6 overflow-hidden rounded-lg border"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <button
          class="flex w-full items-center justify-between gap-3 px-5 py-3 text-left transition-colors"
          @click="toggleSearches"
          @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--surface-1)')"
          @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
        >
          <div class="flex items-center gap-2">
            <ChevronRight
              class="h-3.5 w-3.5 transition-transform"
              :style="{ transform: searchesOpen ? 'rotate(90deg)' : 'rotate(0deg)', color: 'var(--ink-500)' }"
            />
            <Radar class="h-3.5 w-3.5" style="color: var(--indigo-700);" />
            <h2 class="font-mono text-[11px] uppercase tracking-wider" style="color: var(--ink);">
              Discovery searches
            </h2>
            <span
              class="font-mono text-[10px]"
              style="color: var(--ink-400);"
            >
              · {{ searchesSummary.total }} call{{ searchesSummary.total === 1 ? '' : 's' }}
            </span>
          </div>
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[11px]">
            <span v-if="searchesSummary.nSuccess > 0" style="color: var(--success);">
              {{ searchesSummary.nSuccess }} ok
            </span>
            <span v-if="searchesSummary.nEmpty > 0" style="color: var(--warning);">
              {{ searchesSummary.nEmpty }} empty
            </span>
            <span v-if="searchesSummary.nFailed > 0" style="color: var(--danger);">
              {{ searchesSummary.nFailed }} failed
            </span>
            <!-- Funnel ventilé : N0 → N1 → N2 → N3 (chunk 0 auto-validation). -->
            <span style="color: var(--ink-400);">
              ·
              <span style="color: var(--ink);" :title="`itemSummaries Browse (N0)`">{{ searchesSummary.nSummaries }}</span>
              <span style="color: var(--ink-400);"> summaries → </span>
              <span style="color: var(--ink);" :title="`+ getItemsByGroup top-K (N1)`">{{ searchesSummary.nAfterGroups }}</span>
              <span style="color: var(--ink-400);"> w/groups → </span>
              <span style="color: var(--ink);" :title="`post theme-token drop (N2)`">{{ searchesSummary.nRaw }}</span>
              <span style="color: var(--ink-400);"> post-theme → </span>
              <span style="color: var(--success);" :title="`post accept_listing (N3)`">{{ searchesSummary.nKept }}</span>
              <span style="color: var(--ink-400);"> kept</span>
            </span>
          </div>
        </button>

        <div v-if="searchesOpen" class="border-t" style="border-color: var(--surface-2);">
          <div
            v-for="s in searchesData.searches"
            :key="s.id"
            class="border-t first:border-t-0"
            style="border-color: var(--surface-2);"
          >
            <button
              class="flex w-full items-center gap-3 px-5 py-2.5 text-left font-mono text-[11px] transition-colors"
              @click="toggleSearch(s.id)"
              @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--surface-1)')"
              @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
            >
              <ChevronRight
                class="h-3 w-3 shrink-0 transition-transform"
                :style="{ transform: expandedSearchIds.has(s.id) ? 'rotate(90deg)' : 'rotate(0deg)', color: 'var(--ink-400)' }"
              />
              <span
                class="rounded-full px-1.5 py-0.5 text-[9px] uppercase"
                :style="{
                  color: SEARCH_TONE[s.status],
                  background: `color-mix(in srgb, ${SEARCH_TONE[s.status]} 10%, var(--surface))`,
                  border: `1px solid color-mix(in srgb, ${SEARCH_TONE[s.status]} 35%, var(--surface-3))`,
                }"
              >
                {{ s.status }}
              </span>
              <span style="color: var(--gold-600);">{{ searchScopeLabel(s) }}</span>
              <span
                v-if="s.marketplace"
                class="rounded px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wider"
                style="color: var(--ink-500); background: var(--surface-2);"
                :title="`Marketplace : ${s.marketplace}`"
              >{{ s.marketplace.replace('EBAY_', '') }}</span>
              <span style="color: var(--ink-400);">·</span>
              <span
                v-if="s.n_summaries != null"
                style="color: var(--ink-700);"
                :title="`itemSummaries Browse (N0)`"
              >{{ s.n_summaries }}</span>
              <span v-if="s.n_summaries != null" style="color: var(--ink-400);">→</span>
              <span
                v-if="s.n_after_groups != null && s.n_after_groups !== s.n_summaries"
                style="color: var(--ink-700);"
                :title="`+ groups (N1)`"
              >{{ s.n_after_groups }}</span>
              <span
                v-if="s.n_after_groups != null && s.n_after_groups !== s.n_summaries"
                style="color: var(--ink-400);"
              >→</span>
              <span style="color: var(--ink-700);" :title="`post theme drop (N2)`">{{ s.n_raw_results ?? '·' }}</span>
              <span style="color: var(--ink-400);">→</span>
              <span style="color: var(--success);" :title="`post accept_listing (N3)`">{{ s.n_kept_results ?? '·' }} kept</span>
              <span v-if="s.duration_ms != null" class="ml-auto" style="color: var(--ink-400);">
                {{ s.duration_ms }} ms
              </span>
            </button>

            <div
              v-if="expandedSearchIds.has(s.id)"
              class="px-5 pb-3 pl-12"
            >
              <dl
                class="grid gap-x-4 gap-y-1 font-mono text-[11px]"
                style="grid-template-columns: max-content 1fr; color: var(--ink-700);"
              >
                <dt style="color: var(--ink-400);">endpoint</dt>
                <dd>{{ s.endpoint || '—' }}</dd>
                <dt style="color: var(--ink-400);">q</dt>
                <dd style="word-break: break-word;">{{ s.query_q || '—' }}</dd>
                <template v-if="s.query_filters">
                  <dt style="color: var(--ink-400);">filters</dt>
                  <dd
                    class="rounded border px-2 py-1"
                    style="border-color: var(--surface-3); background: var(--surface-1); white-space: pre-wrap; word-break: break-word;"
                  >{{ JSON.stringify(s.query_filters, null, 2) }}</dd>
                </template>
                <template v-if="s.browse_url">
                  <dt style="color: var(--ink-400);">browse_url</dt>
                  <dd class="flex items-start gap-2">
                    <span class="min-w-0 flex-1" style="word-break: break-all;">{{ s.browse_url }}</span>
                    <button
                      type="button"
                      class="shrink-0 rounded border px-1.5 py-0.5 text-[10px] transition-colors"
                      style="border-color: var(--surface-3); color: var(--ink-500);"
                      @click.stop="copyBrowseUrl(s)"
                    >
                      {{ copiedUrlSearchId === s.id ? '✓ copié' : 'copier' }}
                    </button>
                    <a
                      :href="s.browse_url"
                      target="_blank"
                      rel="noopener"
                      class="shrink-0 rounded border px-1.5 py-0.5 text-[10px] transition-colors"
                      style="border-color: var(--surface-3); color: var(--indigo-700);"
                      @click.stop
                    >
                      ouvrir
                    </a>
                  </dd>
                </template>
                <template v-if="s.http_status != null">
                  <dt style="color: var(--ink-400);">http_status</dt>
                  <dd>{{ s.http_status }}</dd>
                </template>
                <dt style="color: var(--ink-400);">created_at</dt>
                <dd>{{ s.created_at }}</dd>
                <template v-if="s.error">
                  <dt style="color: var(--ink-400);">error</dt>
                  <dd style="color: var(--danger); word-break: break-word;">{{ s.error }}</dd>
                </template>
              </dl>
            </div>
          </div>
        </div>
      </section>

      <!-- Listings rejetés (chunk 0 auto-validation : visibilité du stream) -->
      <section
        v-if="discardedData && discardedData.total > 0"
        class="mb-6 overflow-hidden rounded-lg border"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <button
          class="flex w-full items-center justify-between gap-3 px-5 py-3 text-left transition-colors"
          @click="toggleDiscarded"
          @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--surface-1)')"
          @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
        >
          <div class="flex items-center gap-2">
            <ChevronRight
              class="h-3.5 w-3.5 transition-transform"
              :style="{ transform: discardedOpen ? 'rotate(90deg)' : 'rotate(0deg)', color: 'var(--ink-500)' }"
            />
            <Trash2 class="h-3.5 w-3.5" style="color: var(--danger);" />
            <h2 class="font-mono text-[11px] uppercase tracking-wider" style="color: var(--ink);">
              Listings rejetés pré-ingestion
            </h2>
            <span class="font-mono text-[10px]" style="color: var(--ink-400);">
              · {{ discardedData.total }} listing{{ discardedData.total === 1 ? '' : 's' }}
            </span>
          </div>
          <div class="flex flex-wrap items-center gap-1.5 font-mono text-[10px]">
            <span
              v-for="g in discardedData.by_reason"
              :key="g.reason"
              class="rounded-full px-2 py-0.5 cursor-pointer"
              :style="{
                color: reasonTone(g.reason),
                background: reasonFilter === g.reason
                  ? `color-mix(in srgb, ${reasonTone(g.reason)} 18%, var(--surface))`
                  : `color-mix(in srgb, ${reasonTone(g.reason)} 8%, var(--surface))`,
                border: `1px solid color-mix(in srgb, ${reasonTone(g.reason)} ${reasonFilter === g.reason ? '60' : '30'}%, var(--surface-3))`,
              }"
              :title="reasonLabel(g.reason)"
              @click.stop="selectReason(g.reason); discardedOpen = true"
            >
              {{ g.reason }} · {{ g.count }}
            </span>
          </div>
        </button>

        <div v-if="discardedOpen" class="border-t" style="border-color: var(--surface-2);">
          <!-- Reason filter active bar -->
          <div
            v-if="reasonFilter"
            class="flex items-center gap-2 border-b px-5 py-2 font-mono text-[11px]"
            style="border-color: var(--surface-2); background: var(--surface-1);"
          >
            <Filter class="h-3 w-3" :style="{ color: reasonTone(reasonFilter) }" />
            <span style="color: var(--ink-500);">Filtre&nbsp;:</span>
            <span :style="{ color: reasonTone(reasonFilter) }">{{ reasonFilter }}</span>
            <span style="color: var(--ink-400);">— {{ reasonLabel(reasonFilter) }}</span>
            <button
              class="ml-auto rounded-full p-0.5"
              style="color: var(--ink-400);"
              @click="selectReason(null)"
              @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'color-mix(in srgb, var(--ink-400) 12%, transparent)')"
              @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
              title="Retirer le filtre"
            >
              <X class="h-3 w-3" />
            </button>
          </div>

          <div
            v-for="d in filteredDiscarded"
            :key="d.id"
            class="border-t first:border-t-0"
            style="border-color: var(--surface-2);"
          >
            <button
              class="flex w-full items-center gap-3 px-5 py-2.5 text-left font-mono text-[11px] transition-colors"
              @click="toggleDiscardedRow(d.id)"
              @mouseenter="(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--surface-1)')"
              @mouseleave="(e) => ((e.currentTarget as HTMLElement).style.background = 'transparent')"
            >
              <ChevronRight
                class="h-3 w-3 shrink-0 transition-transform"
                :style="{ transform: expandedDiscardedIds.has(d.id) ? 'rotate(90deg)' : 'rotate(0deg)', color: 'var(--ink-400)' }"
              />
              <span
                class="rounded-full px-1.5 py-0.5 text-[9px] uppercase whitespace-nowrap"
                :style="{
                  color: reasonTone(d.reason),
                  background: `color-mix(in srgb, ${reasonTone(d.reason)} 10%, var(--surface))`,
                  border: `1px solid color-mix(in srgb, ${reasonTone(d.reason)} 35%, var(--surface-3))`,
                }"
                :title="reasonLabel(d.reason)"
              >
                {{ d.reason }}
              </span>
              <span style="color: var(--gold-600);" class="whitespace-nowrap">{{ d.target_eurio_id || '—' }}</span>
              <span style="color: var(--ink-400);">·</span>
              <span class="truncate" style="color: var(--ink);" :title="d.title || ''">
                {{ d.title || '— no title —' }}
              </span>
              <span
                v-if="d.price != null"
                class="ml-auto whitespace-nowrap"
                style="color: var(--ink-700);"
              >
                {{ d.price.toFixed(2) }} {{ d.currency || 'EUR' }}
              </span>
            </button>

            <div
              v-if="expandedDiscardedIds.has(d.id)"
              class="px-5 pb-3 pl-12"
            >
              <dl
                class="grid gap-x-4 gap-y-1 font-mono text-[11px]"
                style="grid-template-columns: max-content 1fr; color: var(--ink-700);"
              >
                <dt style="color: var(--ink-400);">source_ref</dt>
                <dd style="word-break: break-all;">{{ d.source_ref }}</dd>
                <template v-if="d.item_id">
                  <dt style="color: var(--ink-400);">item_id</dt>
                  <dd>{{ d.item_id }}</dd>
                </template>
                <template v-if="d.item_web_url">
                  <dt style="color: var(--ink-400);">url</dt>
                  <dd>
                    <a
                      :href="d.item_web_url"
                      target="_blank"
                      rel="noopener"
                      class="inline-flex items-center gap-1"
                      style="color: var(--indigo-700);"
                    >
                      voir l'annonce <ExternalLink class="h-2.5 w-2.5" />
                    </a>
                  </dd>
                </template>
                <dt style="color: var(--ink-400);">created_at</dt>
                <dd>{{ d.created_at }}</dd>
                <template v-if="d.raw_payload">
                  <dt style="color: var(--ink-400);">payload</dt>
                  <dd
                    class="rounded border px-2 py-1"
                    style="border-color: var(--surface-3); background: var(--surface-1); white-space: pre-wrap; word-break: break-word;"
                  >{{ JSON.stringify(d.raw_payload, null, 2) }}</dd>
                </template>
              </dl>
            </div>
          </div>

          <!-- Empty filtered -->
          <div
            v-if="reasonFilter && filteredDiscarded.length === 0"
            class="px-5 py-4 text-center font-mono text-[11px]"
            style="color: var(--ink-400);"
          >
            Aucun listing rejeté avec la raison <em>{{ reasonFilter }}</em>.
          </div>
        </div>
      </section>

      <!-- Empty state -->
      <div
        v-if="!data.listings.length"
        class="rounded-lg border-2 border-dashed px-6 py-12 text-center text-sm"
        style="border-color: var(--surface-3); color: var(--ink-400);"
      >
        Aucun listing pour ce run{{ eurioFilter ? ` sur ${eurioFilter}` : '' }}.
      </div>

      <!-- Cards -->
      <div v-else class="flex flex-col gap-4">
        <article
          v-for="l in data.listings"
          :key="l.source_image_id"
          class="overflow-hidden rounded-lg border"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <div class="flex flex-col gap-4 p-5 sm:flex-row">
            <!-- Thumbnail -->
            <div
              class="flex h-32 w-32 shrink-0 items-center justify-center overflow-hidden rounded-md border"
              style="border-color: var(--surface-3); background: var(--surface-1);"
            >
              <img
                v-if="l.download_status === 'success'"
                :src="rawFileUrl(sourceId, l.source_image_id)"
                :alt="l.source_ref"
                class="h-full w-full object-cover"
                loading="lazy"
              />
              <div
                v-else
                class="flex flex-col items-center gap-1 text-center"
                :style="{ color: l.download_status === 'failed' ? 'var(--danger)' : 'var(--ink-400)' }"
              >
                <XCircle v-if="l.download_status === 'failed'" class="h-6 w-6" />
                <AlertTriangle v-else class="h-6 w-6" />
                <span class="font-mono text-[10px] uppercase">
                  {{ l.download_status || 'no raw' }}
                </span>
              </div>
            </div>

            <!-- Body -->
            <div class="min-w-0 flex-1">
              <!-- Title row -->
              <div class="flex flex-wrap items-start justify-between gap-3">
                <div class="min-w-0">
                  <p
                    class="font-mono text-[10px] uppercase tracking-wider"
                    style="color: var(--ink-400);"
                  >
                    {{ l.source_ref }}
                  </p>
                  <h3
                    class="mt-0.5 truncate text-sm font-medium"
                    style="color: var(--ink);"
                    :title="l.listing_title || ''"
                  >
                    {{ l.listing_title || '— no title —' }}
                  </h3>
                </div>
                <a
                  v-if="l.source_url"
                  :href="l.source_url"
                  target="_blank"
                  rel="noopener"
                  class="inline-flex items-center gap-1 rounded-md border px-2 py-0.5 font-mono text-[10px] transition-colors"
                  style="border-color: var(--surface-3); color: var(--indigo-700); background: var(--surface);"
                  @mouseenter="(e) => { const el = e.currentTarget as HTMLElement; el.style.borderColor = 'var(--indigo-700)'; el.style.background = 'color-mix(in srgb, var(--indigo-700) 6%, var(--surface))'; }"
                  @mouseleave="(e) => { const el = e.currentTarget as HTMLElement; el.style.borderColor = 'var(--surface-3)'; el.style.background = 'var(--surface)'; }"
                >
                  ebay <ExternalLink class="h-2.5 w-2.5" />
                </a>
              </div>

              <!-- Metadata -->
              <p
                class="mt-1.5 font-mono text-[11px]"
                style="color: var(--ink-500);"
              >
                <span v-if="l.target_eurio_id">
                  <span style="color: var(--ink-400);">→</span>
                  <span style="color: var(--gold-600);">{{ l.target_eurio_id }}</span>
                </span>
                <span v-if="l.listing_country" class="ml-2">
                  <span style="color: var(--ink-400);">·</span> {{ l.listing_country }}
                </span>
                <span v-if="l.listing_year" class="ml-2">
                  <span style="color: var(--ink-400);">·</span> {{ l.listing_year }}
                </span>
                <span v-if="l.listing_price != null" class="ml-2">
                  <span style="color: var(--ink-400);">·</span>
                  <span style="color: var(--ink);">{{ formatPrice(l.listing_price, l.listing_currency) }}</span>
                </span>
                <span v-if="l.seller_id" class="ml-2">
                  <span style="color: var(--ink-400);">· seller</span> {{ l.seller_id }}
                </span>
              </p>

              <!-- Decision badges -->
              <div class="mt-3 flex flex-wrap items-center gap-1.5">
                <!-- Route decision -->
                <span
                  v-if="l.route_decision"
                  class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[10px]"
                  :style="{
                    color: ROUTE_TONE[l.route_decision] || 'var(--ink-500)',
                    background: `color-mix(in srgb, ${ROUTE_TONE[l.route_decision] || 'var(--ink-400)'} 10%, var(--surface))`,
                    border: `1px solid color-mix(in srgb, ${ROUTE_TONE[l.route_decision] || 'var(--ink-400)'} 35%, var(--surface-3))`,
                  }"
                  :title="l.route_reason || ''"
                >
                  <CheckCircle2 v-if="l.route_decision === 'auto_resolved'" class="h-2.5 w-2.5" />
                  <Package v-else-if="l.route_decision === 'review_lot'" class="h-2.5 w-2.5" />
                  {{ ROUTE_LABEL[l.route_decision] }}
                  <span v-if="l.route_reason" style="opacity: 0.7;">· {{ l.route_reason }}</span>
                </span>

                <!-- Lot suspected -->
                <span
                  v-if="l.is_lot_suspected"
                  class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[10px]"
                  style="border: 1px solid var(--surface-3); color: var(--gold-600); background: color-mix(in srgb, var(--gold-600) 8%, var(--surface));"
                  title="Le titre suggère un lot (is_lot_suspected = 1)"
                >
                  <Package class="h-2.5 w-2.5" /> lot suspected
                </span>

                <!-- Crops -->
                <span
                  class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[10px]"
                  :style="{
                    border: '1px solid var(--surface-3)',
                    color: l.crop_status === 'success' ? 'var(--ink-700)' : (l.crop_status === 'zero_crops' ? 'var(--warning)' : 'var(--danger)'),
                    background: 'var(--surface-1)',
                  }"
                  :title="l.crop_error || ''"
                >
                  <Scissors class="h-2.5 w-2.5" />
                  {{ l.n_crops_detected ?? 0 }} crop{{ (l.n_crops_detected ?? 0) === 1 ? '' : 's' }}
                  <span v-if="l.crop_status && l.crop_status !== 'success'" style="opacity: 0.7;">· {{ l.crop_status }}</span>
                </span>

                <!-- Download badge -->
                <span
                  v-if="l.download_status && l.download_status !== 'success'"
                  class="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[10px]"
                  :style="{
                    border: '1px solid var(--danger)',
                    color: 'var(--danger)',
                    background: 'color-mix(in srgb, var(--danger) 6%, var(--surface))',
                  }"
                  :title="l.download_error || ''"
                >
                  <Download class="h-2.5 w-2.5" />
                  download · {{ l.download_status }}
                  <span v-if="l.download_http_status" style="opacity: 0.7;">· {{ l.download_http_status }}</span>
                </span>
              </div>

              <!-- Error / endpoint detail -->
              <details
                v-if="l.download_error || l.crop_error || l.download_endpoint"
                class="mt-3"
              >
                <summary
                  class="cursor-pointer font-mono text-[10px] uppercase tracking-wider"
                  style="color: var(--ink-400);"
                >
                  trace
                </summary>
                <div
                  class="mt-1.5 rounded border px-2.5 py-1.5 font-mono text-[11px]"
                  style="border-color: var(--surface-3); background: var(--surface-1); color: var(--ink-700);"
                >
                  <p v-if="l.download_endpoint" style="word-break: break-all;">
                    <span style="color: var(--ink-400);">endpoint&nbsp;:</span>
                    {{ shortenUrl(l.download_endpoint) }}
                  </p>
                  <p v-if="l.download_error" class="mt-1" style="color: var(--danger); word-break: break-word;">
                    <span style="color: var(--ink-400);">download_error&nbsp;:</span>
                    {{ l.download_error }}
                  </p>
                  <p v-if="l.crop_error" class="mt-1" style="color: var(--warning); word-break: break-word;">
                    <span style="color: var(--ink-400);">crop_error&nbsp;:</span>
                    {{ l.crop_error }}
                  </p>
                </div>
              </details>

              <!-- Crops thumbnails -->
              <div v-if="l.crops.length" class="mt-3 flex flex-wrap gap-2">
                <div
                  v-for="c in l.crops"
                  :key="c.asset_id"
                  class="flex flex-col items-center gap-1"
                >
                  <div
                    class="h-14 w-14 overflow-hidden rounded border"
                    :style="{
                      borderColor: c.resolution_status === 'rejected' ? 'var(--danger)' : (c.review_id ? 'var(--gold-600)' : 'var(--surface-3)'),
                      background: 'var(--surface-1)',
                    }"
                  >
                    <img
                      :src="assetFileUrl(sourceId, c.asset_id)"
                      :alt="`crop ${c.crop_index}`"
                      class="h-full w-full object-cover"
                      loading="lazy"
                    />
                  </div>
                  <span
                    class="font-mono text-[9px] uppercase tracking-wider"
                    :style="{
                      color: c.resolution_status === 'rejected' ? 'var(--danger)'
                        : c.resolution_status?.startsWith('auto') ? 'var(--success)'
                        : c.review_id ? 'var(--gold-600)' : 'var(--ink-400)',
                    }"
                    :title="c.resolution_status || ''"
                  >
                    {{ c.review_kind || (c.resolution_status?.replace('auto_', '') ?? '·') }}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </article>
      </div>

      <!-- Légende -->
      <p class="mt-6 max-w-3xl font-mono text-[10px] leading-relaxed" style="color: var(--ink-400);">
        <strong style="color: var(--ink-500);">Légende&nbsp;</strong> ·
        Vue lecture seule pour debugger les décisions du pipeline. Chaque card = un listing eBay (= un raw + ses crops).
        Les badges affichent les verdicts persistés par les steps download / detect_crop / enqueue.
        Cliquer sur "ebay" ouvre le listing source. Pour reviewer, passer par <em>/review</em>.
      </p>
    </template>
  </div>
</template>
