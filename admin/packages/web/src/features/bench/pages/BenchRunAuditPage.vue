<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  AlertTriangle, Coins, CornerDownRight, ExternalLink, Gavel,
  ImageOff, Inbox, MousePointerClick, RefreshCw, ScanLine, Sparkles,
} from 'lucide-vue-next'
import {
  type BenchRunGroup,
  type BenchRunGroupDrop,
  type BenchRunListing,
  type BenchRunResponse,
  fetchBenchRun,
  fetchBenchRunListings,
} from '../composables/useBenchApi'

const route = useRoute()
const runId = computed(() => String(route.params.runId))

const data = ref<BenchRunResponse | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)

const selectedGroupId = ref<string | null>(null)
const selectedNodeId = ref<string | null>(null)  // 'raw' | 'matched' | drop.node_id

const listings = ref<BenchRunListing[]>([])
const listingsTotal = ref(0)
const listingsLoading = ref(false)
const LIMIT = 50
const offset = ref(0)

const summary = computed(() => data.value?.summary ?? null)
const groups = computed(() => data.value?.groups ?? [])
const coins = computed(() => data.value?.coins ?? {})

const selectedGroup = computed<BenchRunGroup | null>(() =>
  groups.value.find(g => g.group_id === selectedGroupId.value) ?? null,
)

async function load() {
  loading.value = true
  error.value = null
  try {
    data.value = await fetchBenchRun(runId.value)
    if (selectedGroupId.value == null && groups.value.length) {
      selectedGroupId.value = groups.value[0].group_id
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
    data.value = null
  } finally {
    loading.value = false
  }
}

async function loadListings() {
  if (!selectedGroup.value) {
    listings.value = []
    listingsTotal.value = 0
    return
  }
  listingsLoading.value = true
  const g = selectedGroup.value
  const q: Parameters<typeof fetchBenchRunListings>[1] = {
    country: g.country,
    year: g.year,
    limit: LIMIT,
    offset: offset.value,
  }
  // Map selectedNodeId vers les filtres backend
  if (selectedNodeId.value === 'matcher/unmatched') {
    q.unmatched_only = true
  } else if (selectedNodeId.value && selectedNodeId.value.includes('/')) {
    const [decision, reason] = selectedNodeId.value.split('/')
    q.route_decision = decision
    if (reason && reason !== 'none') q.route_reason = reason
  }
  // 'raw' (annonces brutes) / 'matched' (matchés) → pas de filtre supplémentaire
  if (selectedNodeId.value === 'matched') {
    // pas de unmatched_only, on garde le filtre country/year qui inclut les matchés
    // En pratique, filtrer "matched only" demanderait un flag dédié backend.
    // Pour V1, on laisse tous les listings du groupe → suffisant pour V.3
  }
  try {
    const r = await fetchBenchRunListings(runId.value, q)
    listings.value = r.listings
    listingsTotal.value = r.listings_total
  } finally {
    listingsLoading.value = false
  }
}

watch([selectedGroupId, selectedNodeId], () => {
  offset.value = 0
  loadListings()
})

onMounted(load)

function selectGroup(id: string) {
  if (selectedGroupId.value === id) return
  selectedGroupId.value = id
  selectedNodeId.value = null
}
function selectNode(id: string) {
  selectedNodeId.value = selectedNodeId.value === id ? null : id
}

function plateWidth(count: number, total: number): string {
  if (!total) return '46%'
  const pct = (count / total) * 100
  return `${Math.max(46, pct).toFixed(1)}%`
}

function priceFmt(p: number | null, cur: string | null): string {
  if (p == null) return '—'
  return `${p.toFixed(2)} ${cur ?? 'EUR'}`
}

function shortEurio(id: string): string {
  return id.replace(/^[a-z]{2}-\d{4}-2eur-/, '')
}

function nextPage() {
  if (offset.value + LIMIT < listingsTotal.value) {
    offset.value += LIMIT
    loadListings()
  }
}
function prevPage() {
  if (offset.value > 0) {
    offset.value = Math.max(0, offset.value - LIMIT)
    loadListings()
  }
}

function nodeLabel(id: string | null): string {
  if (!id) return 'tous les listings du groupe'
  if (id === 'raw') return 'annonces brutes'
  if (id === 'matched') return 'matchés à un coin'
  if (id === 'matcher/unmatched') return 'theme-matcher — unmatched'
  return id
}

function decisionTone(d: string | null): { color: string; bg: string } {
  if (d === 'pending') return { color: 'var(--ink-400)', bg: '#dcefe4' }
  if (d === 'review_lot') return { color: 'var(--gold-700)', bg: 'var(--gold-100)' }
  if (d === 'review_single') return { color: 'var(--indigo-700)', bg: 'var(--indigo-50, #e6e8f5)' }
  return { color: 'var(--ink)', bg: 'var(--surface-2)' }
}

// État local : track broken images for graceful fallback
const brokenImages = ref<Set<string>>(new Set())
function markBroken(id: string) {
  brokenImages.value = new Set([...brokenImages.value, id])
}
</script>

<template>
  <div class="flex h-full flex-col overflow-hidden" style="background: var(--surface-1);">
    <!-- En-tête -->
    <header
      class="flex flex-shrink-0 items-center justify-between border-b px-7 py-4"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <div>
        <h1
          class="flex items-center gap-2 text-[20px] italic"
          style="font-family: var(--font-display); font-weight: 600; color: var(--indigo-700);"
        >
          <Gavel class="h-5 w-5" />
          Audit run live — theme-matcher
        </h1>
        <p class="mt-0.5 text-[12px]" style="color: var(--ink-400);">
          Run <code class="font-mono text-[11px]">{{ runId.slice(0, 8) }}</code> rejoué groupe par groupe
          — pas de scoring (pas de gold humain), tu juges visuellement chaque décision.
        </p>
      </div>
      <button
        class="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[13px] transition-colors hover:bg-black/[0.03]"
        style="border-color: var(--surface-3); color: var(--ink-500);"
        :disabled="loading"
        @click="load"
      >
        <RefreshCw class="h-3.5 w-3.5" :class="loading ? 'animate-spin' : ''" />
        Recharger
      </button>
    </header>

    <div v-if="loading && !data" class="flex flex-1 items-center justify-center">
      <p class="italic" style="font-family: var(--font-display); color: var(--ink-400);">
        Chargement du run…
      </p>
    </div>

    <div v-else-if="error" class="flex flex-1 items-center justify-center">
      <div class="max-w-md text-center">
        <p class="text-[17px] italic"
           style="font-family: var(--font-display); color: var(--danger);">Audit indisponible</p>
        <p class="mt-1 text-[13px]" style="color: var(--ink-500);">{{ error }}</p>
        <button
          class="mt-3 rounded-lg border px-3 py-1.5 text-[13px]"
          style="border-color: var(--surface-3); color: var(--ink-500);"
          @click="load"
        >Réessayer</button>
      </div>
    </div>

    <div v-else-if="summary" class="flex flex-1 flex-col overflow-y-auto">
      <div class="mx-auto w-full max-w-[1400px] px-7 py-6">
        <!-- Métriques globales du run -->
        <section>
          <h2 class="mb-2 text-[11px] font-medium uppercase tracking-[0.12em]"
              style="color: var(--ink-400);">
            Bilan global du run — {{ summary.total_listings }} annonces sur {{ summary.n_groups }} recherches
          </h2>
          <div class="grid grid-cols-6 gap-3 rounded-2xl border p-3"
               style="border-color: var(--surface-3); background: var(--surface);">
            <div>
              <div class="text-[10px] font-medium uppercase tracking-wide"
                   style="color: var(--ink-400);">Annonces</div>
              <div class="text-[24px] leading-none"
                   style="font-family: var(--font-display); font-weight: 600; color: var(--ink);">
                {{ summary.total_listings }}
              </div>
            </div>
            <div>
              <div class="text-[10px] font-medium uppercase tracking-wide"
                   style="color: var(--ink-400);">Unmatched</div>
              <div class="text-[24px] leading-none"
                   style="font-family: var(--font-display); font-weight: 600; color: var(--danger);">
                {{ summary.total_unmatched }}
              </div>
              <div class="text-[10px]" style="color: var(--ink-400);">
                {{ summary.total_listings ? Math.round(summary.total_unmatched / summary.total_listings * 100) : 0 }} %
              </div>
            </div>
            <div>
              <div class="text-[10px] font-medium uppercase tracking-wide"
                   style="color: var(--ink-400);">Pending</div>
              <div class="text-[24px] leading-none"
                   style="font-family: var(--font-display); font-weight: 600; color: var(--ink-400);">
                {{ summary.total_pending }}
              </div>
            </div>
            <div>
              <div class="text-[10px] font-medium uppercase tracking-wide"
                   style="color: var(--ink-400);">Review (single + lot)</div>
              <div class="text-[24px] leading-none"
                   style="font-family: var(--font-display); font-weight: 600; color: var(--gold-700);">
                {{ summary.total_review_single + summary.total_review_lot }}
              </div>
              <div class="text-[10px]" style="color: var(--ink-400);">
                {{ summary.total_review_single }}s / {{ summary.total_review_lot }}l
              </div>
            </div>
            <div>
              <div class="text-[10px] font-medium uppercase tracking-wide"
                   style="color: var(--ink-400);">Auto</div>
              <div class="text-[24px] leading-none"
                   style="font-family: var(--font-display); font-weight: 600;"
                   :style="{ color: summary.total_auto ? 'var(--indigo-700)' : 'var(--ink-300)' }">
                {{ summary.total_auto }}
              </div>
              <div v-if="!summary.total_auto" class="text-[10px]" style="color: var(--ink-300);">
                désactivé V.3
              </div>
            </div>
            <div>
              <div class="text-[10px] font-medium uppercase tracking-wide"
                   style="color: var(--ink-400);">Quotes générés</div>
              <div class="text-[24px] leading-none"
                   style="font-family: var(--font-display); font-weight: 600; color: var(--indigo-700);">
                {{ summary.total_quotes }}
              </div>
            </div>
          </div>
        </section>

        <!-- Recherches eBay = discovery groups -->
        <section class="mt-7">
          <h2 class="mb-2 text-[11px] font-medium uppercase tracking-[0.12em]"
              style="color: var(--ink-400);">
            {{ groups.length }} recherches eBay — choisis-en une à auditer
          </h2>
          <div class="grid gap-2.5"
               :style="`grid-template-columns: repeat(${Math.min(groups.length, 6)}, 1fr);`">
            <button
              v-for="g in groups"
              :key="g.group_id"
              class="group relative overflow-hidden rounded-xl border px-4 py-3 text-left transition-all"
              :style="selectedGroupId === g.group_id
                ? 'border-color: var(--indigo-600); background: var(--surface); box-shadow: 0 1px 0 var(--indigo-600), 0 6px 16px -10px var(--indigo-900);'
                : 'border-color: var(--surface-3); background: var(--surface-1);'"
              @click="selectGroup(g.group_id)"
            >
              <div class="flex items-start justify-between">
                <div>
                  <div
                    class="text-[26px] leading-none"
                    :style="`font-family: var(--font-display); font-weight: 600; color: ${
                      selectedGroupId === g.group_id ? 'var(--indigo-700)' : 'var(--ink)'};`"
                  >{{ g.year }}</div>
                  <div
                    class="mt-0.5 text-[10.5px] uppercase tracking-[0.08em]"
                    style="color: var(--ink-400); font-family: var(--font-mono);"
                  >{{ g.country }} · {{ g.denomination }} €</div>
                </div>
                <span
                  v-if="g.n_unmatched > 0"
                  class="flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-semibold"
                  style="background: var(--danger-soft, #f6dcd6); color: var(--danger);"
                  :title="`${g.n_unmatched} listings unmatched`"
                >
                  <AlertTriangle class="h-2.5 w-2.5" />
                  {{ g.n_unmatched }}
                </span>
              </div>

              <!-- eurio_ids cibles de ce groupe -->
              <div class="mt-2.5 flex flex-wrap gap-1">
                <span
                  v-for="eid in g.target_eurio_ids"
                  :key="eid"
                  class="truncate rounded px-1.5 py-0.5 text-[10px]"
                  style="background: var(--surface-2); color: var(--ink-500);
                         font-family: var(--font-mono); max-width: 100%;"
                >{{ shortEurio(eid) }}</span>
              </div>

              <!-- Mini-bilan : brut → quotes -->
              <div class="mt-2.5 flex items-center gap-1 text-[11px]"
                   style="color: var(--ink-400);">
                <span style="font-family: var(--font-mono);">{{ g.total_listings }}</span>
                <span>brut</span>
                <span style="color: var(--ink-300);">→</span>
                <span style="font-family: var(--font-mono); color: var(--indigo-700);">
                  {{ g.n_quotes }}
                </span>
                <span>quotes</span>
              </div>
            </button>
          </div>
        </section>

        <!-- Entonnoir + détail -->
        <section
          v-if="selectedGroup"
          class="mt-6 overflow-hidden rounded-2xl border"
          style="border-color: var(--surface-3); background: var(--surface);"
        >
          <div class="flex items-baseline gap-2.5 border-b px-6 py-3.5"
               style="border-color: var(--surface-3);">
            <ScanLine class="h-4 w-4 self-center" style="color: var(--ink-400);" />
            <span class="text-[10.5px] font-medium uppercase tracking-[0.13em]"
                  style="color: var(--ink-400);">Recherche eBay</span>
            <span class="text-[19px]"
                  style="font-family: var(--font-display); font-weight: 600; color: var(--ink);">
              {{ selectedGroup.country }} · {{ selectedGroup.denomination }} € · {{ selectedGroup.year }}
            </span>
          </div>

          <div class="flex" style="height: min(80vh, 940px); min-height: 540px;">
            <!-- Colonne 1 — pièces visées -->
            <div class="flex w-[300px] flex-shrink-0 flex-col border-r"
                 style="border-color: var(--surface-3);">
              <div class="flex flex-shrink-0 items-center gap-2 border-b px-5 py-3"
                   style="border-color: var(--surface-3);">
                <Coins class="h-4 w-4" style="color: var(--ink-400);" />
                <h3 class="text-[13px] font-semibold" style="color: var(--ink);">Pièces visées</h3>
                <span class="text-[12px]" style="color: var(--ink-400);">
                  {{ selectedGroup.target_eurio_ids.length }}
                </span>
              </div>
              <div class="flex-1 space-y-4 overflow-y-auto px-4 py-4">
                <article
                  v-for="eid in selectedGroup.target_eurio_ids"
                  :key="eid"
                  class="flex flex-col overflow-hidden rounded-2xl border"
                  style="border-color: var(--surface-3); background: var(--surface);"
                >
                  <div class="flex aspect-square items-center justify-center overflow-hidden p-4"
                       style="background: var(--paper);">
                    <img
                      v-if="coins[eid]?.obverse_url"
                      :src="coins[eid]!.obverse_url!"
                      :alt="coins[eid]?.display_name ?? eid"
                      class="h-full w-full object-contain"
                      style="filter: drop-shadow(0 6px 14px rgba(14,14,31,0.18));"
                    />
                    <ImageOff v-else class="h-8 w-8" style="color: var(--ink-300);" />
                  </div>
                  <div class="border-t px-4 py-3" style="border-color: var(--surface-3);">
                    <div class="text-[12px]"
                         style="font-family: var(--font-mono); color: var(--indigo-700);">
                      {{ shortEurio(eid) }}
                    </div>
                    <div class="mt-0.5 text-[13px] italic leading-snug"
                         style="font-family: var(--font-display); font-weight: 600; color: var(--ink);">
                      {{ coins[eid]?.display_name ?? coins[eid]?.theme ?? eid }}
                    </div>
                    <div v-if="coins[eid]" class="mt-2 space-y-0.5">
                      <div v-for="(title, lang) in coins[eid].i18n" :key="lang"
                           class="flex gap-2 text-[11px]">
                        <span class="w-5 flex-shrink-0 uppercase"
                              style="color: var(--ink-300); font-family: var(--font-mono);">
                          {{ lang }}
                        </span>
                        <span style="color: var(--ink-500);">{{ title }}</span>
                      </div>
                    </div>
                    <div v-if="coins[eid]?.aliases?.length"
                         class="mt-2 flex flex-wrap items-center gap-1">
                      <span class="mr-0.5 text-[10px] uppercase tracking-wide"
                            style="color: var(--ink-400);">alias</span>
                      <span v-for="a in coins[eid].aliases" :key="a"
                            class="rounded px-1.5 py-0.5 text-[10px]"
                            style="background: var(--gold-100); color: var(--gold-700);
                                   font-family: var(--font-mono);">
                        {{ a }}
                      </span>
                    </div>
                  </div>
                </article>
              </div>
            </div>

            <!-- Colonne 2 — entonnoir -->
            <div class="w-[346px] flex-shrink-0 overflow-y-auto border-r px-5 py-6"
                 style="border-color: var(--surface-3); background: var(--surface-1);">
              <div class="flex flex-col items-center">
                <!-- Plaque : annonces brutes -->
                <button
                  class="rounded-xl border px-4 py-3 text-left transition-all"
                  :style="`width: 100%; ${selectedNodeId === 'raw'
                    ? 'border-color: var(--indigo-600); background: var(--indigo-50);'
                    : 'border-color: var(--ink-200); background: var(--surface);'}`"
                  @click="selectNode('raw')"
                >
                  <div class="flex items-baseline justify-between gap-3">
                    <span class="text-[10.5px] font-medium uppercase tracking-[0.09em]"
                          style="color: var(--ink-400);">Annonces brutes</span>
                    <span class="text-[23px] leading-none"
                          style="font-family: var(--font-display); font-weight: 600; color: var(--ink);">
                      {{ selectedGroup.total_listings }}
                    </span>
                  </div>
                </button>

                <!-- Transition : theme-matcher -->
                <div class="my-1 h-3 w-px" style="background: var(--surface-3);" />
                <button
                  class="w-full rounded-lg border px-3 py-2 text-left transition-all"
                  :disabled="selectedGroup.n_unmatched === 0"
                  :style="selectedGroup.n_unmatched === 0
                    ? 'border-color: var(--surface-3); background: var(--surface-1); cursor: default;'
                    : selectedNodeId === 'matcher/unmatched'
                      ? 'border-color: var(--indigo-600); background: var(--indigo-50);'
                      : 'border-color: var(--danger); background: var(--surface);'"
                  @click="selectedGroup.n_unmatched && selectNode('matcher/unmatched')"
                >
                  <div class="text-[11.5px] font-semibold" style="color: var(--ink);">
                    Filtre 1 — theme-matcher
                  </div>
                  <div class="mt-1 flex items-center gap-2 text-[11px]">
                    <span v-if="selectedGroup.n_unmatched"
                          style="color: var(--danger); font-family: var(--font-mono);">
                      ✗ {{ selectedGroup.n_unmatched }} unmatched
                    </span>
                    <span v-else style="color: var(--success);">tout matché</span>
                    <span class="ml-auto text-[10px]" style="color: var(--ink-400);">
                      target_eurio_id NULL
                    </span>
                  </div>
                </button>

                <!-- Plaque : matchés à un coin -->
                <div class="my-1 h-3 w-px" style="background: var(--surface-3);" />
                <button
                  class="rounded-xl border px-4 py-2.5 text-left transition-all"
                  :style="`width: ${plateWidth(selectedGroup.total_listings - selectedGroup.n_unmatched, selectedGroup.total_listings)}; ${selectedNodeId === 'matched'
                    ? 'border-color: var(--indigo-600); background: var(--indigo-50);'
                    : 'border-color: var(--indigo-300); background: var(--surface);'}`"
                  @click="selectNode('matched')"
                >
                  <div class="flex items-baseline justify-between gap-3">
                    <span class="text-[10.5px] font-medium uppercase tracking-[0.09em]"
                          style="color: var(--ink-400);">Matchés à un coin</span>
                    <span class="text-[21px] leading-none"
                          style="font-family: var(--font-display); font-weight: 600; color: var(--ink);">
                      {{ selectedGroup.total_listings - selectedGroup.n_unmatched }}
                    </span>
                  </div>
                </button>

                <!-- Transition : router (route_decision/route_reason) -->
                <div class="my-1 h-3 w-px" style="background: var(--surface-3);" />
                <div class="mb-2 flex items-center gap-1.5 text-[10.5px] font-medium uppercase tracking-[0.1em]"
                     style="color: var(--ink-400);">
                  <Sparkles class="h-3.5 w-3.5" /> Routing
                </div>
                <div class="w-full space-y-1.5">
                  <button
                    v-for="drop in selectedGroup.drops.filter(d => d.node_id !== 'matcher/unmatched')"
                    :key="drop.node_id"
                    class="flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left transition-all"
                    :style="selectedNodeId === drop.node_id
                      ? 'border-color: var(--indigo-600); background: var(--indigo-50);'
                      : drop.route_decision === 'pending'
                        ? 'border-color: var(--surface-3); background: var(--surface);'
                        : drop.route_decision === 'review_lot'
                          ? 'border-color: var(--gold-400); background: var(--surface);'
                          : 'border-color: var(--indigo-300); background: var(--surface);'"
                    @click="selectNode(drop.node_id)"
                  >
                    <CornerDownRight class="h-3.5 w-3.5 flex-shrink-0" style="color: var(--ink-300);" />
                    <span class="text-[10px] font-semibold uppercase tracking-[0.07em]"
                          :style="`color: ${
                            drop.route_decision === 'pending' ? 'var(--ink-400)'
                            : drop.route_decision === 'review_lot' ? 'var(--gold-700)'
                            : 'var(--indigo-700)'};`">
                      {{ drop.route_decision }}
                    </span>
                    <span class="truncate text-[11px]" style="color: var(--ink-500);">
                      {{ drop.reason ?? '—' }}
                    </span>
                    <span class="ml-auto text-[15px]"
                          style="font-family: var(--font-display); font-weight: 600; color: var(--ink);">
                      {{ drop.count }}
                    </span>
                  </button>
                </div>

                <!-- Plaque : quotes générés -->
                <div class="my-1 mt-3 h-3 w-px" style="background: var(--surface-3);" />
                <div class="rounded-xl border px-4 py-2.5"
                     :style="`width: ${plateWidth(selectedGroup.n_quotes, selectedGroup.total_listings)};
                              border-color: var(--indigo-600); background: var(--indigo-50);`">
                  <div class="flex items-baseline justify-between gap-3">
                    <span class="text-[10.5px] font-medium uppercase tracking-[0.09em]"
                          style="color: var(--indigo-700);">Quotes générés</span>
                    <span class="text-[21px] leading-none"
                          style="font-family: var(--font-display); font-weight: 600; color: var(--indigo-700);">
                      {{ selectedGroup.n_quotes }}
                    </span>
                  </div>
                </div>
              </div>
            </div>

            <!-- Colonne 3 — listings du nœud (grid de cards) -->
            <div class="min-w-0 flex-1 overflow-hidden">
              <div class="flex h-full flex-col">
                <div class="flex flex-shrink-0 items-center gap-2 border-b px-5 py-3"
                     style="border-color: var(--surface-3);">
                  <Inbox class="h-4 w-4" style="color: var(--ink-400);" />
                  <h3 class="text-[13px] font-semibold" style="color: var(--ink);">
                    Annonces — {{ nodeLabel(selectedNodeId) }}
                  </h3>
                  <span class="text-[12px]" style="color: var(--ink-400);">
                    {{ listingsTotal }}
                  </span>
                  <span v-if="listingsLoading" class="text-[11px]" style="color: var(--ink-400);">
                    chargement…
                  </span>
                </div>
                <div class="flex-1 overflow-y-auto px-5 py-5">
                  <div v-if="!listings.length"
                       class="flex h-full flex-col items-center justify-center gap-2 text-center">
                    <MousePointerClick class="h-7 w-7" style="color: var(--ink-300);" />
                    <p class="text-[13px] italic"
                       style="font-family: var(--font-display); color: var(--ink-400);">
                      Clique une étape de l'entonnoir<br />pour voir ses annonces.
                    </p>
                  </div>
                  <div v-else
                       class="grid gap-3.5"
                       style="grid-template-columns: repeat(auto-fill, minmax(185px, 1fr));">
                    <article
                      v-for="l in listings" :key="l.source_image_id"
                      class="flex flex-col overflow-hidden rounded-xl border"
                      :style="l.is_lot_suspected
                        ? 'border-color: var(--gold-400); background: var(--surface); box-shadow: 0 0 0 1px var(--gold-400);'
                        : 'border-color: var(--surface-3); background: var(--surface);'"
                    >
                      <!-- Photo carrée -->
                      <div class="relative flex aspect-square items-center justify-center overflow-hidden"
                           style="background: var(--surface-2);">
                        <img
                          v-if="l.image_url && !brokenImages.has(l.source_image_id)"
                          :src="l.image_url!"
                          :alt="l.listing_title ?? l.source_image_id"
                          class="h-full w-full object-contain"
                          loading="lazy"
                          @error="markBroken(l.source_image_id)"
                        />
                        <div v-else class="flex flex-col items-center gap-1">
                          <ImageOff class="h-6 w-6" style="color: var(--ink-300);" />
                          <span class="text-[10px]" style="color: var(--ink-400);">
                            pas d'image
                          </span>
                        </div>
                        <!-- Pastille décision -->
                        <span
                          class="absolute right-2 top-2 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
                          :style="`background: ${decisionTone(l.route_decision).bg};
                                   color: ${decisionTone(l.route_decision).color};`"
                        >{{ l.route_decision ?? '—' }}</span>
                      </div>
                      <!-- Méta -->
                      <div class="flex flex-1 flex-col gap-1.5 px-3 py-2.5">
                        <p
                          class="text-[12px] leading-snug"
                          style="color: var(--ink); display: -webkit-box;
                                 -webkit-line-clamp: 2; -webkit-box-orient: vertical;
                                 overflow: hidden;"
                        >{{ l.listing_title ?? '(sans titre)' }}</p>
                        <p
                          v-if="l.route_reason"
                          class="truncate text-[10.5px]"
                          :title="l.route_reason!"
                          style="font-family: var(--font-mono); color: var(--ink-500);"
                        >{{ l.route_reason }}</p>
                        <div class="mt-auto flex items-center gap-1.5 pt-1">
                          <span
                            v-if="l.marketplace"
                            class="rounded px-1 py-px text-[10px]"
                            style="background: var(--surface-2); color: var(--ink-400);
                                   font-family: var(--font-mono);"
                          >{{ l.marketplace }}</span>
                          <span class="text-[11px]" style="color: var(--ink-500);
                                                          font-family: var(--font-mono);">
                            {{ priceFmt(l.listing_price, l.listing_currency) }}
                          </span>
                          <a
                            v-if="l.source_url"
                            :href="l.source_url!"
                            target="_blank"
                            rel="noopener noreferrer"
                            class="ml-auto flex items-center gap-0.5 text-[11px] hover:underline"
                            style="color: var(--indigo-600);"
                            @click.stop
                          >
                            <ExternalLink class="h-3 w-3" /> eBay
                          </a>
                        </div>
                        <div v-if="l.target_eurio_id"
                             class="truncate text-[10px]"
                             :title="l.target_eurio_id!"
                             style="font-family: var(--font-mono); color: var(--indigo-700);">
                          → {{ shortEurio(l.target_eurio_id) }}
                        </div>
                      </div>
                    </article>
                  </div>
                </div>
                <div class="flex flex-shrink-0 items-center justify-between border-t px-5 py-2 text-[11px]"
                     style="border-color: var(--surface-3); color: var(--ink-400);">
                  <span>
                    {{ listings.length ? offset + 1 : 0 }}–{{ Math.min(offset + LIMIT, listingsTotal) }} / {{ listingsTotal }}
                  </span>
                  <div class="flex gap-2">
                    <button
                      class="rounded border px-2 py-0.5 disabled:opacity-40"
                      style="border-color: var(--surface-3);"
                      :disabled="offset === 0"
                      @click="prevPage"
                    >← Précédent</button>
                    <button
                      class="rounded border px-2 py-0.5 disabled:opacity-40"
                      style="border-color: var(--surface-3);"
                      :disabled="offset + LIMIT >= listingsTotal"
                      @click="nextPage"
                    >Suivant →</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>
