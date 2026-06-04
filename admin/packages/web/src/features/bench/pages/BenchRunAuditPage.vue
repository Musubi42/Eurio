<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertTriangle, Coins, Crop as CropIcon, ExternalLink, Filter,
  Gavel, ImageOff, Inbox, MousePointerClick, RefreshCw, ScanLine, X,
} from 'lucide-vue-next'
import {
  type BenchRunGroup,
  type BenchRunListing,
  type BenchRunResponse,
  fetchBenchRun,
  fetchBenchRunListings,
} from '../composables/useBenchApi'
import BenchRunAuditCropPanel from '../components/BenchRunAuditCropPanel.vue'

const route = useRoute()
const router = useRouter()
const runId = computed(() => String(route.params.runId))

// Deep-link funnel lab (`?eurio_id=<coin>`) : pré-filtre l'audit sur le coin
// attribué. Pré-sélectionne sa recherche + restreint listings/crops à ce coin.
const eurioFilter = computed(() => {
  const q = route.query.eurio_id
  return typeof q === 'string' && q ? q : null
})
function clearEurioFilter() {
  const { eurio_id: _drop, ...rest } = route.query
  router.replace({ query: rest, hash: route.hash })
}

// Mode toggle (Filter = audit theme-matcher | Crop = audit forensics crop).
// Persisté en hash de l'URL pour partage et reload-stable.
type AuditMode = 'filter' | 'crop'
const mode = ref<AuditMode>(
  (route.hash === '#crop' ? 'crop' : 'filter') as AuditMode,
)
function setMode(m: AuditMode) {
  mode.value = m
  // Update hash without triggering full navigation.
  history.replaceState(history.state, '', m === 'crop' ? '#crop' : '#filter')
}

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
      // Deep-link coin → sa recherche ; sinon la première.
      const coinGroup = eurioFilter.value
        ? groups.value.find(g => g.target_eurio_ids.includes(eurioFilter.value!))
        : null
      selectedGroupId.value = (coinGroup ?? groups.value[0]).group_id
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
  // Deep-link coin : ne filtre QUE la vue par défaut (aucun nœud sélectionné).
  // Dès qu'on clique un nœud du funnel (routing ou unmatched), on montre le
  // bucket à l'échelle du GROUPE, pour que la liste corresponde au compteur du
  // badge (sinon le filtre eurio_id écarte silencieusement les non-attribuées
  // → clic « lot suspecté 5 » renvoyait 0). Cf. bug funnel deep-link.
  if (eurioFilter.value && !selectedNodeId.value) q.eurio_id = eurioFilter.value
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

// Filtre coin changé (clear, ou navigation coin→coin sans remount) : re-cible
// sa recherche ; si le groupe ne bouge pas, recharge ici pour (dé)appliquer le
// filtre eurio_id — sinon le watch ci-dessus s'en charge.
watch(eurioFilter, () => {
  const before = selectedGroupId.value
  if (eurioFilter.value && data.value) {
    const g = groups.value.find(gr => gr.target_eurio_ids.includes(eurioFilter.value!))
    if (g) selectedGroupId.value = g.group_id
  }
  if (selectedGroupId.value === before) {
    offset.value = 0
    loadListings()
  }
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

// ── Répartition du routing (partition des matchées) ──────────────────────
// matchedCount = total - unmatched ; les drops de routing se PARTAGENT ce
// total. On expose des helpers d'affichage : largeur de segment, couleur par
// décision, libellé humain de la raison.
type RunDrop = BenchRunGroup['drops'][number]

const matchedCount = computed(() =>
  selectedGroup.value
    ? selectedGroup.value.total_listings - selectedGroup.value.n_unmatched
    : 0,
)
const routingDrops = computed<RunDrop[]>(() =>
  selectedGroup.value
    ? selectedGroup.value.drops.filter((d) => d.node_id !== 'matcher/unmatched')
    : [],
)
// Total des annonces ROUTÉES (= somme des destins de routing). C'est l'axe
// "traitement des crops", INDÉPENDANT de l'attribution : il couvre matchées
// ET non-attribuées. Les % de routing sont donc relatifs à ce total, pas à
// matchedCount (sinon on dépasse 100 % — bug funnel v1).
const routedTotal = computed(() =>
  routingDrops.value.reduce((s, d) => s + d.count, 0),
)
function partPct(count: number): number {
  return routedTotal.value ? (count / routedTotal.value) * 100 : 0
}

// Couleur par décision (cohérente avec les pastilles existantes).
const DECISION_COLORS: Record<string, string> = {
  pending: 'var(--ink-300)',
  review_single: 'var(--indigo-600)',
  review_lot: 'var(--gold-400)',
}
function decisionColor(decision: string | null): string {
  if (decision && decision.startsWith('auto')) return 'var(--success)'
  return (decision && DECISION_COLORS[decision]) || 'var(--ink-400)'
}

// DESTINATION : où part l'annonce, déduit du route_decision (= état agrégé de
// ses crops). C'est la question de l'utilisateur « ça va où / et après ? ».
//   review_single|review_lot → file de review HUMAINE (page /review)
//   pending                  → nulle part : aucun crop produit, pas en review
//   auto_resolved            → résolu automatiquement (phash/nom)
//   rejected                 → écarté (tous crops rejetés)
const DESTINATION_LABELS: Record<string, string> = {
  review_single: 'En review · pièce seule',
  review_lot: 'En review · lot',
  pending: 'Bloqué · pas encore de crop',
  auto_resolved: 'Auto-résolu',
  rejected: 'Rejeté',
}
function destinationLabel(decision: string | null): string {
  return (decision && DESTINATION_LABELS[decision]) || decision || '—'
}

// Version courte pour le badge de carte (chip uppercase).
const DESTINATION_SHORT: Record<string, string> = {
  review_single: 'review',
  review_lot: 'review lot',
  pending: 'sans crop',
  auto_resolved: 'auto',
  rejected: 'rejeté',
}
function destinationShort(decision: string | null): string {
  return (decision && DESTINATION_SHORT[decision]) || decision || '—'
}

// Raison (le « pourquoi » de cette destination) — affichée en détail.
const REASON_LABELS: Record<string, string> = {
  no_crops_yet: 'aucune découpe produite par le crop',
  mixed_status: 'crops dans des états mixtes',
  multi_coin_photo: 'photo à plusieurs pièces',
  is_lot_suspected: 'lot suspecté (titre)',
  single_unmatched: 'pièce seule, non auto-attribuée',
  single_matched: 'pièce seule, attribuée',
  all_crops_rejected: 'tous les crops rejetés',
}
function reasonLabel(d: RunDrop): string {
  return (d.reason && REASON_LABELS[d.reason]) || d.reason || '—'
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
          <Gavel v-if="mode === 'filter'" class="h-5 w-5" />
          <CropIcon v-else class="h-5 w-5" />
          Audit run live — {{ mode === 'filter' ? 'theme-matcher' : 'crop forensics' }}
        </h1>
        <p class="mt-0.5 text-[12px]" style="color: var(--ink-400);">
          Run <code class="font-mono text-[11px]">{{ runId.slice(0, 8) }}</code>
          <template v-if="mode === 'filter'">
            rejoué groupe par groupe — pas de scoring (pas de gold humain),
            tu juges visuellement chaque décision.
          </template>
          <template v-else>
            — chaque <code class="font-mono text-[11px]">image_asset</code>
            avec sa bbox sur le raw, pour repérer les undercrops (rim mangé).
          </template>
        </p>
        <div
          v-if="eurioFilter"
          class="mt-2 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px]"
          style="border-color: var(--indigo-300); background: var(--indigo-50, #e6e8f5); color: var(--indigo-700);"
        >
          <Filter class="h-3 w-3" />
          <span style="font-family: var(--font-mono);">filtré · {{ shortEurio(eurioFilter) }}</span>
          <button
            class="ml-0.5 inline-flex items-center rounded-full p-0.5 transition-colors hover:bg-black/[0.06]"
            title="Retirer le filtre coin"
            @click="clearEurioFilter"
          >
            <X class="h-3 w-3" />
          </button>
        </div>
      </div>

      <div class="flex items-center gap-3">
        <!-- Mode toggle (Filter / Crop) -->
        <div class="mode-toggle">
          <button
            :class="{ active: mode === 'filter' }"
            @click="setMode('filter')"
          >
            <span class="mode-toggle__dot"></span>Filter
          </button>
          <button
            :class="{ active: mode === 'crop' }"
            @click="setMode('crop')"
          >
            <span class="mode-toggle__dot"></span>Crop
          </button>
        </div>

        <button
          v-if="mode === 'filter'"
          class="flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-[13px] transition-colors hover:bg-black/[0.03]"
          style="border-color: var(--surface-3); color: var(--ink-500);"
          :disabled="loading"
          @click="load"
        >
          <RefreshCw class="h-3.5 w-3.5" :class="loading ? 'animate-spin' : ''" />
          Recharger
        </button>
      </div>
    </header>

    <!-- ░ MODE CROP : panel forensics autonome ░ -->
    <div
      v-if="mode === 'crop'"
      class="flex flex-1 flex-col overflow-y-auto"
    >
      <div class="mx-auto w-full max-w-[1500px] px-7 py-6">
        <BenchRunAuditCropPanel :run-id="runId" :eurio-id="eurioFilter" />
      </div>
    </div>

    <!-- ░ MODE FILTER : audit theme-matcher (existant) ░ -->
    <div v-else-if="loading && !data" class="flex flex-1 items-center justify-center">
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
                  >{{ g.year ?? 'std' }}</div>
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
              {{ selectedGroup.country }} · {{ selectedGroup.denomination }} € · {{ selectedGroup.year ?? 'standard' }}
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

            <!-- Colonne 2 — RÉPARTITION (partition honnête, pas une cascade).
                 Les N matchées se PARTAGENT entre les destins de routing ;
                 la barre + la somme explicite lèvent l'illusion de rétrécissement. -->
            <div class="w-[360px] flex-shrink-0 overflow-y-auto border-r px-6 py-6"
                 style="border-color: var(--surface-3); background: var(--surface-1);">

              <!-- En-tête : total annonces de la recherche -->
              <div class="text-[10.5px] font-medium uppercase tracking-[0.12em]"
                   style="color: var(--ink-400);">Annonces de la recherche</div>
              <div class="mt-1 text-[34px] leading-none"
                   style="font-family: var(--font-display); font-weight: 600; color: var(--ink);">
                {{ selectedGroup.total_listings }}
              </div>

              <!-- ═══ AXE 1 — ATTRIBUTION (theme-matcher) : matchée vs non ═══ -->
              <div class="mt-5 flex items-baseline justify-between">
                <span class="text-[10.5px] font-medium uppercase tracking-[0.12em]"
                      style="color: var(--ink-400);">Attribution</span>
                <span class="text-[10px]" style="color: var(--ink-300); font-family: var(--font-mono);">theme-matcher</span>
              </div>
              <div class="mt-2 flex h-3.5 w-full overflow-hidden rounded-full"
                   style="background: var(--surface-2); box-shadow: inset 0 1px 2px rgba(14,14,31,0.08);">
                <div class="h-full"
                     :style="{ width: (matchedCount / selectedGroup.total_listings * 100) + '%', background: 'var(--indigo-600)' }" />
                <div class="h-full"
                     :style="{ width: (selectedGroup.n_unmatched / selectedGroup.total_listings * 100) + '%', background: 'var(--gold-400)' }" />
              </div>
              <div class="mt-2.5 space-y-1.5">
                <div class="flex items-center gap-3 rounded-lg border px-3 py-2"
                     style="border-color: var(--surface-3); background: var(--surface);">
                  <span class="h-2.5 w-2.5 flex-shrink-0 rounded-full" style="background: var(--indigo-600);" />
                  <span class="flex-1 text-[12.5px]" style="color: var(--ink);">matchées à un eurio_id</span>
                  <span class="text-[17px] leading-none"
                        style="font-family: var(--font-display); font-weight: 600; color: var(--ink);">{{ matchedCount }}</span>
                </div>
                <button
                  v-if="selectedGroup.n_unmatched"
                  class="flex w-full items-center gap-3 rounded-lg border px-3 py-2 text-left transition-all"
                  :style="selectedNodeId === 'matcher/unmatched'
                    ? 'border-color: var(--danger); background: var(--danger-soft, #f6dcd6);'
                    : 'border-color: var(--surface-3); background: var(--surface);'"
                  @click="selectNode('matcher/unmatched')"
                >
                  <span class="h-2.5 w-2.5 flex-shrink-0 rounded-full" style="background: var(--gold-400);" />
                  <span class="flex-1 text-[12.5px]" style="color: var(--ink);">non auto-attribuées — à trancher</span>
                  <span class="text-[17px] leading-none"
                        style="font-family: var(--font-display); font-weight: 600; color: var(--gold-700);">{{ selectedGroup.n_unmatched }}</span>
                </button>
              </div>
              <div class="mt-1.5 text-[10px]" style="color: var(--ink-400); font-family: var(--font-mono);">
                {{ matchedCount }} + {{ selectedGroup.n_unmatched }} = {{ selectedGroup.total_listings }}
              </div>

              <!-- ═══ AXE 2 — TRAITEMENT (routing des crops) — INDÉPENDANT ═══
                   Couvre TOUTES les annonces routées (matchées ET non) : c'est
                   pourquoi la somme = total, pas matchedCount. -->
              <div class="mt-6 flex items-baseline justify-between">
                <span class="text-[10.5px] font-medium uppercase tracking-[0.12em]"
                      style="color: var(--ink-400);">Traitement des crops</span>
                <span class="text-[10px]" style="color: var(--ink-300); font-family: var(--font-mono);">routing · axe distinct</span>
              </div>
              <p class="mt-0.5 text-[10px] italic" style="color: var(--ink-400);">
                indépendant de l'attribution — inclut matchées <i>et</i> non-attribuées
              </p>

              <!-- Barre empilée : largeurs ∝ count, somme = routedTotal -->
              <div class="mt-2 flex h-3.5 w-full overflow-hidden rounded-full"
                   style="background: var(--surface-2); box-shadow: inset 0 1px 2px rgba(14,14,31,0.08);">
                <button
                  v-for="d in routingDrops" :key="d.node_id"
                  class="h-full border-0 transition-all"
                  :style="{
                    width: partPct(d.count) + '%',
                    background: decisionColor(d.route_decision),
                    opacity: selectedNodeId && selectedNodeId !== d.node_id ? 0.3 : 1,
                  }"
                  :title="`${reasonLabel(d)} — ${d.count}`"
                  @click="selectNode(d.node_id)"
                />
              </div>
              <!-- Somme explicite : répond à « où sont passées les annonces ? » -->
              <div class="mt-1.5 text-[10px]" style="color: var(--ink-400); font-family: var(--font-mono);">
                {{ routingDrops.map(d => d.count).join(' + ') }} = {{ routedTotal }}
              </div>

              <!-- Légende cliquable : 1 destin/ligne, label humain + part -->
              <div class="mt-3.5 space-y-1.5">
                <button
                  v-for="d in routingDrops" :key="d.node_id"
                  class="flex w-full items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition-all"
                  :style="selectedNodeId === d.node_id
                    ? 'border-color: var(--indigo-600); background: var(--indigo-50); box-shadow: 0 1px 0 var(--indigo-600);'
                    : 'border-color: var(--surface-3); background: var(--surface);'"
                  @click="selectNode(d.node_id)"
                >
                  <span class="h-2.5 w-2.5 flex-shrink-0 rounded-full"
                        :style="{ background: decisionColor(d.route_decision) }" />
                  <span class="min-w-0 flex-1">
                    <span class="block text-[12.5px] leading-tight" style="color: var(--ink);">
                      {{ destinationLabel(d.route_decision) }}
                    </span>
                    <span class="text-[10px] leading-tight" style="color: var(--ink-400);">
                      {{ reasonLabel(d) }}
                    </span>
                  </span>
                  <span class="flex-shrink-0 text-right">
                    <span class="block text-[17px] leading-none"
                          style="font-family: var(--font-display); font-weight: 600; color: var(--ink);">
                      {{ d.count }}
                    </span>
                    <span class="text-[10px]" style="color: var(--ink-400); font-family: var(--font-mono);">
                      {{ partPct(d.count).toFixed(0) }} %
                    </span>
                  </span>
                </button>
              </div>

              <!-- Quotes : SORTI du funnel — résultat marché, pas un étage du tri -->
              <div class="mt-6 flex items-center justify-between rounded-xl border border-dashed px-4 py-3"
                   style="border-color: var(--indigo-300); background: var(--indigo-50);">
                <div>
                  <div class="text-[10.5px] font-medium uppercase tracking-[0.09em]"
                       style="color: var(--indigo-700);">Résultat marché</div>
                  <div class="mt-0.5 text-[10px]" style="color: var(--ink-400);">
                    prix générés — hors funnel
                  </div>
                </div>
                <span class="text-[24px] leading-none"
                      style="font-family: var(--font-display); font-weight: 600; color: var(--indigo-700);">
                  {{ selectedGroup.n_quotes }}
                </span>
              </div>

              <!-- Règles du theme-matcher : explicite la doctrine pour comprendre
                   pourquoi une annonce matche / ne matche pas (demande utilisateur). -->
              <details class="mt-4 rounded-xl border px-4 py-2.5"
                       style="border-color: var(--surface-3); background: var(--surface);">
                <summary class="cursor-pointer select-none text-[10.5px] font-medium uppercase tracking-[0.1em]"
                         style="color: var(--ink-500);">Règles du matcher</summary>
                <div class="mt-2.5 space-y-2 text-[11px] leading-snug" style="color: var(--ink-500);">
                  <p>
                    <b style="color: var(--ink);">Standards</b>
                    <span style="color: var(--ink-400);"> (recherche sans année)</span> :
                    annonce → l'ère du pays si <b>une seule</b> est identifiable (<i>single</i>) ;
                    sinon <i>ambiguous</i> → gardée en review, toutes les ères en candidats ;
                    jetée si commémo / hors-pays / aucune ère.
                  </p>
                  <p>
                    <b style="color: var(--ink);">Commémos</b>
                    <span style="color: var(--ink-400);"> (année précise)</span> :
                    <i>single</i> / <i>lot</i> / <i>ambiguous</i> gardées ;
                    jetée seulement sur contradiction franche pays · année · dénom (<i>no_match</i>).
                  </p>
                  <p style="color: var(--ink-400);">
                    Critères lus dans le titre : pays, année, dénomination, tokens de thème,
                    + marqueurs lot / set / coffret / « au choix ».
                  </p>
                </div>
              </details>
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
                        >{{ destinationShort(l.route_decision) }}</span>
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
                        <!-- Raison du non-match (annonces sans target) -->
                        <p
                          v-if="l.match_reason"
                          class="rounded px-1.5 py-1 text-[10.5px] leading-snug"
                          :title="l.match_reason!"
                          style="background: color-mix(in srgb, var(--gold-400) 16%, var(--surface));
                                 color: var(--gold-700);"
                        >⊘ {{ l.match_reason }}</p>
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

<style scoped>
/* Mode toggle pills (Filter / Crop) — design-system-aligned, editorial. */
.mode-toggle {
  display: inline-flex;
  align-items: center;
  padding: 4px;
  border: 1px solid var(--surface-3);
  background: var(--surface-1);
  border-radius: 999px;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.4);
}
.mode-toggle button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 16px 8px;
  border-radius: 999px;
  background: transparent;
  font-family: var(--font-display);
  font-style: italic;
  font-weight: 500;
  font-size: 14px;
  color: var(--ink-400);
  letter-spacing: -0.005em;
  transition: all 200ms cubic-bezier(0.16, 1, 0.3, 1);
}
.mode-toggle button:hover:not(.active) { color: var(--ink); }
.mode-toggle button.active {
  background: var(--ink);
  color: var(--surface);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08),
              0 6px 16px -8px var(--indigo-900);
}
.mode-toggle__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
  opacity: 0.5;
}
.mode-toggle button.active .mode-toggle__dot {
  background: var(--gold-300);
  opacity: 1;
}
</style>
