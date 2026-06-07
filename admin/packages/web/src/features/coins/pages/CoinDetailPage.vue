<script setup lang="ts">
import {
  checkMlApiOnline,
  fetchCoinDetail,
  type CoinConfusionDetail,
} from '@/features/confusion/composables/useConfusionMap'
import { zoneCopy, zoneStyle } from '@/features/confusion/composables/useConfusionZone'
import {
  fetchCoin as apiFetchCoin,
  fetchCoinCredits,
  fetchCoinDescriptions,
  fetchCoinSourceStatus,
  postCoinRefresh,
  fetchRunSnapshot,
  fetchCoinEmbedding,
  fetchCoinI18n,
  fetchCoinMintReleasesFull,
  fetchCoinObservations,
  fetchCoinPrices,
  fetchCoinSeries,
  fetchCoinVariantGroup,
  fetchCoinDesignGroup,
  type CoinDescription,
  type SourceStatusResponse,
  type CreditsResponse,
  type MintReleaseFull,
  type ObservationsResponse,
  type VariantGroupEntry,
  type DesignGroupMember,
} from '@/features/coins/composables/useCoinsApi'
import type { Coin, CoinImage, CoinImageDict, CoinSeries, IssueType } from '@/shared/supabase/types'
import {
  ArrowLeft,
  ArrowUpRight,
  Brain,
  Calendar,
  Check,
  ChevronDown,
  Coins as CoinsIcon,
  Copy,
  ExternalLink,
  ImageOff,
  Info,
  Layers,
  Loader2,
  MapPin,
  Network,
  Play,
  RefreshCw,
  ShieldAlert,
  TrendingUp,
} from 'lucide-vue-next'
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { coinDisplayName } from '@/shared/utils/coin-display'
import EnrichmentGallery from '../components/EnrichmentGallery.vue'
import VariantBadge from '../components/VariantBadge.vue'

const route = useRoute()
const router = useRouter()

const coin = ref<Coin | null>(null)
const series = ref<CoinSeries | null>(null)
const loading = ref(true)
const error = ref<string | null>(null)
const selectedImage = ref<CoinImage | null>(null)

function onEnrichmentSelect(img: CoinImage) {
  selectedImage.value = img
}
const trainedModelVersion = ref<string | null>(null)

// Training enqueue
const ML_API = 'http://127.0.0.1:8042'
const enqueueState = ref<'idle' | 'loading' | 'success'>('idle')

// Confusion-map detail (Phase 1 ML scalability)
const confusion = ref<CoinConfusionDetail | null>(null)
const confusionLoading = ref(false)

// eBay market prices
interface MarketPrice {
  p25: number
  p50: number
  p75: number
  samples_count: number
  with_sales_count: number
  fetched_at: string
}
const marketPrice = ref<MarketPrice | null | undefined>(undefined) // undefined = loading, null = not fetched
const marketPriceLoading = ref(false)

// LMDLP catalogue prices — one entry per (eurio_id × quality)
interface LmdlpPrice {
  quality: string
  p50: number
  in_stock: boolean
  fetched_at: string
}
const lmdlpPrices = ref<LmdlpPrice[] | null | undefined>(undefined)

// i18n titles + aliases (audit i18n-147)
interface I18nRow {
  lang: string
  title: string
  source: string
  confidence: string
  model: string | null
}
interface AliasRow {
  lang: string
  alias: string
  source: string
  confidence: string
}
const i18nRows = ref<I18nRow[] | undefined>(undefined)
const aliasesRows = ref<AliasRow[] | undefined>(undefined)

// Descriptions officielles BCE (titre + description, 24 langues UE) + sélecteur
// de langue du header (chunk C — affichage données BCE).
const descriptions = ref<CoinDescription[] | undefined>(undefined)
const selectedLang = ref<string | null>(null)
const langMenuOpen = ref(false)

// Disponibilité de données par source (chunk 1 — chargement seul, rendu chunk 3).
const sourceStatus = ref<SourceStatusResponse | null | undefined>(undefined)

// Caractéristiques (observations + crédits) + Millésimes & tirages.
// undefined = chargement, null = erreur réseau (fail-silent).
const observations = ref<ObservationsResponse | null | undefined>(undefined)
const credits = ref<CreditsResponse | null | undefined>(undefined)
const mintReleases = ref<MintReleaseFull[] | null | undefined>(undefined)
// Groupe de variantes (badges header). On ne montre les badges que si le
// groupe a >1 membre (canonique + au moins une variante).
const variantMembers = ref<VariantGroupEntry[]>([])
const hasVariantGroup = computed(() => variantMembers.value.length > 1)

// Design group — pièces partageant l'AVERS (= classe ArcFace). Distinct des
// variantes (finitions ci-dessus). Section visible ssi >1 membre.
const designGroupId = ref<string | null>(null)
const designGroupLabel = ref<string | null>(null)
const designGroupMembers = ref<DesignGroupMember[]>([])
const hasDesignGroup = computed(() => designGroupMembers.value.length > 1)

const I18N_LANG_ORDER = ['fr', 'en', 'de', 'it', 'es', 'nl'] as const
const I18N_LANG_LABEL: Record<string, string> = {
  fr: 'Français', en: 'English', de: 'Deutsch',
  it: 'Italiano', es: 'Español', nl: 'Nederlands', xx: 'Universel',
}
// 24 langues officielles UE (descriptions BCE). Sert le sélecteur du header :
// ordre = 6 langues Eurio d'abord, puis le reste alphabétique.
const EURIO_LANGS = ['fr', 'en', 'de', 'it', 'es', 'nl']
const EU_LANG_LABEL: Record<string, string> = {
  bg: 'Български', cs: 'Čeština', da: 'Dansk', de: 'Deutsch', el: 'Ελληνικά',
  en: 'English', es: 'Español', et: 'Eesti', fi: 'Suomi', fr: 'Français',
  ga: 'Gaeilge', hr: 'Hrvatski', hu: 'Magyar', it: 'Italiano', lt: 'Lietuvių',
  lv: 'Latviešu', mt: 'Malti', nl: 'Nederlands', pl: 'Polski', pt: 'Português',
  ro: 'Română', sk: 'Slovenčina', sl: 'Slovenščina', sv: 'Svenska',
}

const issueLabel: Record<IssueType, string> = {
  'circulation':       'Circulation',
  'commemo-national':  'Commémo nationale',
  'commemo-common':    'Commémo commune',
  'starter-kit':       'Starter kit',
  'bu-set':            'BU set',
  'proof':             'Proof',
}

const roleLabel: Record<string, string> = {
  obverse: 'Avers',
  reverse: 'Revers',
  edge:    'Tranche',
  detail:  'Détail',
}

async function fetchCoin(eurioId: string) {
  loading.value = true
  error.value = null
  coin.value = null
  series.value = null
  selectedImage.value = null

  let data: Coin | null = null
  try {
    // L'API ml/ retourne un payload aligné sur la structure attendue par
    // l'UI (cross_refs reconstitué, images dans le format flat, has_*
    // booléens dérivés). On le cast en `Coin` Supabase pour minimiser
    // l'impact sur le reste du composant (compat layer P.8b).
    data = (await apiFetchCoin(eurioId)) as unknown as Coin
  } catch (e) {
    error.value = (e as Error).message
    loading.value = false
    return
  }
  if (!data) { error.value = 'Pièce introuvable'; loading.value = false; return }

  coin.value = data

  // Normalize coins.images → flat CoinImage[] (the format the UI uses below).
  // Three possible inputs:
  //   1. New per-eurio_id shape: { obverse: [{source,url,thumb_url,width,...}], reverse: [...] }
  //   2. Legacy Numista dict:    { obverse, reverse, obverse_thumb, reverse_thumb, [obverse_source] }
  //   3. Legacy flat array:      [{role, url, source}]
  // We sort variants by width desc when known so the default selection is the
  // highest-quality one per role.
  const raw = coin.value.images
  if (raw && !Array.isArray(raw)) {
    const obj = raw as Record<string, unknown>
    const normalized: CoinImage[] = []
    const isNewShape = Array.isArray(obj.obverse) || Array.isArray(obj.reverse)

    if (isNewShape) {
      for (const role of ['obverse', 'reverse'] as const) {
        const variants = (obj[role] as Array<Record<string, unknown>> | undefined) || []
        const sorted = [...variants].sort(
          (a, b) => ((b.width as number) ?? 0) - ((a.width as number) ?? 0),
        )
        for (const v of sorted) {
          if (typeof v.url === 'string') {
            normalized.push({
              url: v.url,
              role,
              source: (v.source as CoinImage['source']) ?? 'numista',
            })
          }
        }
      }
    } else {
      const dict = raw as CoinImageDict & { obverse_source?: string; reverse_source?: string }
      if (dict.obverse) normalized.push({
        url: dict.obverse, role: 'obverse',
        source: (dict.obverse_source as CoinImage['source']) ?? 'numista',
      })
      if (dict.reverse) normalized.push({
        url: dict.reverse, role: 'reverse',
        source: (dict.reverse_source as CoinImage['source']) ?? 'numista',
      })
    }
    coin.value.images = normalized
  }
  // Fusion avec les canoniques locales SQLite (ml/canonical_images/).
  // Le backend Supabase ne connaît que les images poussées via
  // push_to_supabase.py — les images BCE écrites par le pipeline local
  // n'y sont pas encore. On les fetch via l'API FastAPI pour les
  // afficher côte-à-côte avec Numista.
  await mergeLocalCanonicals(coin.value)
  const imgs = coin.value.images as CoinImage[]
  selectedImage.value = imgs[0] ?? null

  // Fetch series si applicable
  if (coin.value.series_id) {
    try {
      const s = await fetchCoinSeries(coin.value.eurio_id)
      if (s) series.value = s as unknown as CoinSeries
    } catch { /* non-blocking */ }
  }

  // Check training status (embedding existence + model_version)
  trainedModelVersion.value = null
  try {
    const emb = await fetchCoinEmbedding(coin.value.eurio_id)
    if (emb.model_version) trainedModelVersion.value = emb.model_version
  } catch { /* non-blocking */ }

  loading.value = false

  // Confusion map — non-blocking; prefer ML API if reachable, fallback to Supabase
  loadConfusion(coin.value.eurio_id)
  // eBay market prices — non-blocking
  loadMarketPrice(coin.value.eurio_id)
  // i18n titles + aliases — non-blocking
  loadI18nAndAliases(coin.value.eurio_id)
  // Caractéristiques + millésimes — non-blocking
  loadCharacteristics(coin.value.eurio_id)
  // Disponibilité par source — non-blocking
  loadSourceStatus(coin.value.eurio_id)
}

async function loadSourceStatus(eurioId: string) {
  sourceStatus.value = undefined
  try {
    sourceStatus.value = await fetchCoinSourceStatus(eurioId)
  } catch {
    sourceStatus.value = null
  }
}

// ─── Disponibilité par source : badges + refresh + polling ─────────────────
const refreshingSource = ref<string | null>(null)
const refreshError = ref<string | null>(null)

// registry id → source courte refreshable (les autres = lecture seule).
const SOURCE_REFRESH: Record<string, 'bce' | 'numista' | 'jo'> = {
  bce_official: 'bce', numista_api: 'numista', eurlex_jo: 'jo',
}
const SOURCE_AXES: Record<string, string[]> = {
  bce_official: ['description', 'mintage', 'issuing_date', 'images'],
  numista_api: ['identity', 'mint_releases', 'prices', 'i18n', 'observations'],
  eurlex_jo: ['images', 'issuing_date', 'notice'],
  ebay_browse: ['quotes', 'listings'],
  lmdlp: ['quotes', 'refs'],
  wikipedia: ['url'],
}
const SOURCE_AXIS_LABELS: Record<string, string> = {
  description: 'Description', mintage: 'Tirage', issuing_date: 'Date', images: 'Image',
  identity: 'ID', mint_releases: 'Millésimes', prices: 'Cote', i18n: 'Titres',
  observations: 'Caractéristiques', quotes: 'Cote', listings: 'Annonces',
  refs: 'Réf', url: 'Lien', notice: 'Avis JO',
}
const SOURCE_STATE_LABEL: Record<string, string> = {
  never: 'Jamais récupéré', ok: 'Présent',
  empty_upstream: 'Pas encore publié', error: 'Échec du fetch',
}
function sourceAxes(source: string): string[] {
  return SOURCE_AXES[source] ?? []
}
function sourceStateStyle(state: string): string {
  if (state === 'ok') return 'border-color: var(--success); color: var(--success); background: var(--success-soft, transparent);'
  if (state === 'empty_upstream') return 'border-color: var(--gold); color: var(--gold-700, var(--gold)); background: var(--gold-50, transparent);'
  if (state === 'error') return 'border-color: var(--danger); color: var(--danger); background: color-mix(in srgb, var(--danger) 8%, transparent);'
  return 'border-color: var(--surface-3); color: var(--ink-400); background: var(--surface-1);'
}
function stateMessage(state: string): string {
  if (state === 'empty_upstream') return 'La source ne publie pas (encore) cette pièce.'
  if (state === 'error') return 'Le dernier fetch a échoué — réessaie.'
  return 'Aucune tentative — clique Rafraîchir pour récupérer.'
}

const bceState = computed(
  () => sourceStatus.value?.sources.find(s => s.source === 'bce_official')?.state ?? null,
)

async function refreshSource(short: 'bce' | 'numista' | 'jo') {
  if (!coin.value || refreshingSource.value) return
  const eid = coin.value.eurio_id
  refreshingSource.value = short
  refreshError.value = null
  try {
    const { run_id } = await postCoinRefresh(eid, short)
    // Poll le run jusqu'à fin (max ~6min @2s).
    for (let i = 0; i < 180; i++) {
      const snap = await fetchRunSnapshot(short, run_id).catch(() => null)
      if (!snap || snap.status !== 'running') break
      await new Promise(r => setTimeout(r, 2000))
    }
    // Recharge le statut + les données potentiellement modifiées.
    await loadSourceStatus(eid)
    await Promise.all([loadCharacteristics(eid), loadI18nAndAliases(eid)])
    if (coin.value) {
      await mergeLocalCanonicals(coin.value)
      const imgs = coin.value.images as CoinImage[]
      if (!selectedImage.value) selectedImage.value = imgs[0] ?? null
    }
  } catch (e) {
    refreshError.value = (e as Error).message?.includes('409')
      ? 'Un run est déjà en cours pour cette source.'
      : 'Échec du refresh.'
  } finally {
    refreshingSource.value = null
  }
}

async function loadCharacteristics(eurioId: string) {
  observations.value = undefined
  credits.value = undefined
  mintReleases.value = undefined
  variantMembers.value = []
  try {
    const [obs, cr, mr] = await Promise.all([
      fetchCoinObservations(eurioId),
      fetchCoinCredits(eurioId),
      fetchCoinMintReleasesFull(eurioId),
    ])
    observations.value = obs
    credits.value = cr
    mintReleases.value = mr.mint_releases
  } catch {
    observations.value = null
    credits.value = null
    mintReleases.value = null
  }
  // Groupe de variantes — non bloquant, fail-silent.
  try {
    const vg = await fetchCoinVariantGroup(eurioId)
    variantMembers.value = vg.members.length > 1 ? vg.members : []
  } catch {
    variantMembers.value = []
  }
  // Design group (pièces du même avers = classe ArcFace) — fail-silent.
  designGroupId.value = null
  designGroupLabel.value = null
  designGroupMembers.value = []
  try {
    const dg = await fetchCoinDesignGroup(eurioId)
    designGroupId.value = dg.design_group_id
    designGroupLabel.value = dg.designation
    designGroupMembers.value = dg.members
  } catch {
    designGroupMembers.value = []
  }
}

function goToVariant(member: VariantGroupEntry) {
  if (!member.is_self) router.push(`/coins/${encodeURIComponent(member.eurio_id)}`)
}

/**
 * Charge les images canoniques locales (`/referential/coin-canonicals/{eurio_id}`)
 * et les fusionne avec ce que Supabase a déjà retourné. Permet d'afficher
 * les images BCE (écrites par le pipeline local, pas encore pushées sur
 * Supabase) à côté des Numista déjà présentes. Échec réseau silencieux :
 * la galerie continue d'afficher les images Supabase.
 */
interface LocalCanonicalEntry {
  source: string
  role: string
  detail_url: string
  thumb_url: string
  file_present: boolean
}
async function mergeLocalCanonicals(c: Coin): Promise<void> {
  try {
    const resp = await fetch(
      `${ML_API}/referential/coin-canonicals/${encodeURIComponent(c.eurio_id)}`,
    )
    if (!resp.ok) return
    const entries = (await resp.json()) as LocalCanonicalEntry[]
    const merged: CoinImage[] = [...((c.images as CoinImage[] | undefined) ?? [])]
    for (const e of entries) {
      if (!e.file_present) continue
      const servedUrl = `${ML_API}${e.detail_url}`
      const existing = merged.find((i) => i.source === e.source && i.role === e.role)
      if (existing) {
        // Un fichier canonique local existe : on sert notre webp (SOT) plutôt
        // que l'URL d'origine — pour BCE c'est un hotlink ecb.europa.eu fragile.
        existing.url = servedUrl
      } else {
        merged.push({ url: servedUrl, role: e.role, source: e.source })
      }
    }
    c.images = merged
  } catch {
    // pas d'API locale joignable — on garde ce que Supabase a renvoyé.
  }
}

async function loadI18nAndAliases(eurioId: string) {
  i18nRows.value = undefined
  aliasesRows.value = undefined
  descriptions.value = undefined
  selectedLang.value = null
  try {
    const [resp, descResp] = await Promise.all([
      fetchCoinI18n(eurioId),
      fetchCoinDescriptions(eurioId),
    ])
    const i18nByLang = new Map<string, I18nRow>()
    for (const r of resp.names as unknown as I18nRow[]) i18nByLang.set(r.lang, r)
    const ordered: I18nRow[] = []
    for (const l of I18N_LANG_ORDER) {
      const row = i18nByLang.get(l)
      if (row) ordered.push(row)
    }
    i18nRows.value = ordered
    aliasesRows.value = resp.aliases as unknown as AliasRow[]
    descriptions.value = descResp.descriptions
  } catch {
    i18nRows.value = []
    aliasesRows.value = []
    descriptions.value = []
  }
}

async function loadConfusion(eurioId: string) {
  confusionLoading.value = true
  confusion.value = null
  try {
    const online = await checkMlApiOnline()
    confusion.value = await fetchCoinDetail(eurioId, online)
  } catch {
    confusion.value = null
  } finally {
    confusionLoading.value = false
  }
}

async function loadMarketPrice(eurioId: string) {
  marketPriceLoading.value = true
  marketPrice.value = undefined
  lmdlpPrices.value = undefined

  // P.8b — Option B (cf. findings) : l'API renvoie deux structures :
  //   - type_level : agrégation par condition (UNC/TTB/TB) — alimente le
  //     bloc "marketPrice" (ebay) et "lmdlpPrices" (lmdlp). Mapping :
  //       p10 → p25, p50 → p50, p90 → p75 (l'UI legacy parle quartiles ;
  //       l'API V2 parle déciles. Mapping cosmétique, valeurs portées
  //       directement.)
  //   - mint_release_level : prix granulaires par atelier × grade. Pas
  //     encore consommé par cette page (TODO follow-up : tableau riche
  //     pour DE Bremen 5×3, etc.).
  let prices: Awaited<ReturnType<typeof fetchCoinPrices>>
  try {
    prices = await fetchCoinPrices(eurioId)
  } catch {
    marketPrice.value = null
    lmdlpPrices.value = null
    marketPriceLoading.value = false
    return
  }
  const tl = prices.type_level

  // eBay : pick le bucket UNC (legacy default) le plus récent
  const ebay = tl
    .filter(r => r.source === 'ebay_browse')
    .sort((a, b) => b.period_start.localeCompare(a.period_start))[0]
  marketPrice.value = ebay
    ? {
        p25: ebay.p10 ?? 0,
        p50: ebay.p50 ?? 0,
        p75: ebay.p90 ?? 0,
        samples_count: ebay.sample_size,
        // with_sales_count : pas exposé par coin_market_quotes V2 ;
        // on prend sample_size comme proxy (les deux étaient égaux côté
        // pipeline eBay legacy).
        with_sales_count: ebay.sample_size,
        fetched_at: ebay.period_end,
      }
    : null

  // LMDLP : un row par condition (UNC/TTB/TB), latest per condition.
  const byQuality = new Map<string, LmdlpPrice>()
  const lmdlpRows = tl
    .filter(r => r.source === 'lmdlp' && r.p50 != null)
    .sort((a, b) => b.period_start.localeCompare(a.period_start))
  for (const r of lmdlpRows) {
    const q = r.condition_normalized
    if (byQuality.has(q)) continue
    byQuality.set(q, {
      quality: q,
      p50: r.p50 ?? 0,
      // coin_market_quotes V2 ne sépare pas "stock vs sold" ; on assume
      // qu'une row présente avec sample_size > 0 implique du stock.
      in_stock: r.sample_size > 0,
      fetched_at: r.period_end,
    })
  }
  lmdlpPrices.value = byQuality.size > 0 ? [...byQuality.values()] : null

  marketPriceLoading.value = false
}

onMounted(() => fetchCoin(route.params.eurio_id as string))
watch(() => route.params.eurio_id, (v) => { if (v) fetchCoin(v as string) })

function formatFaceValue(v: number): string {
  if (v >= 1) return `${v.toFixed(0)} €`
  return `${(v * 100).toFixed(0)} centimes`
}

function formatDate(iso: string | null) {
  if (!iso) return null
  return new Date(iso).toLocaleDateString('fr-FR', {
    year: 'numeric', month: 'long', day: 'numeric',
  })
}

function formatShortDate(iso: string) {
  return new Date(iso).toLocaleDateString('fr-FR', {
    year: 'numeric', month: 'short', day: 'numeric',
  })
}

function formatPrice(v: number): string {
  return v.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

const seriesMintingPeriod = computed(() => {
  if (!series.value) return null
  const start = new Date(series.value.minting_started_at).getFullYear()
  const end = series.value.minting_ended_at
    ? new Date(series.value.minting_ended_at).getFullYear()
    : null
  return end ? `${start} – ${end}` : `${start} – présent`
})

async function enqueueForTraining() {
  if (!coin.value) return
  const c = coin.value
  // The ArcFace class is the design_group when present (all members share the
  // label), else the eurio_id. No numista_id is needed — the resolver expands
  // the class into source numista dirs at augment time.
  if (!c.design_group_id && !c.cross_refs?.numista_id) return
  const classId = c.design_group_id || c.eurio_id
  const classKind: 'eurio_id' | 'design_group_id' =
    c.design_group_id ? 'design_group_id' : 'eurio_id'
  enqueueState.value = 'loading'
  try {
    const resp = await fetch(`${ML_API}/training/stage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items: [{ class_id: classId, class_kind: classKind }] }),
    })
    if (resp.ok) {
      enqueueState.value = 'success'
      setTimeout(() => router.push('/training'), 1000)
    } else {
      enqueueState.value = 'idle'
    }
  } catch {
    enqueueState.value = 'idle'
  }
}

// ─── Clipboard copy ───

const copiedToast = ref<{ label: string, value: string } | null>(null)
let copiedToastTimer: ReturnType<typeof setTimeout> | null = null

function copyToClipboard(value: string, label: string, event: Event) {
  event.stopPropagation()
  navigator.clipboard?.writeText(value)
  copiedToast.value = { label, value }
  if (copiedToastTimer) clearTimeout(copiedToastTimer)
  copiedToastTimer = setTimeout(() => { copiedToast.value = null }, 1500)
}

function goToConfusionCoin(eurioId: string) {
  router.push(`/coins/${encodeURIComponent(eurioId)}`)
}

const confusionNearest = computed(() => {
  if (!confusion.value) return null
  // The API contract puts nearest as first neighbor; fallback: find by nearest_eurio_id
  if (confusion.value.nearest_eurio_id) {
    const match = confusion.value.top_k_neighbors.find(
      n => n.eurio_id === confusion.value!.nearest_eurio_id,
    )
    if (match) return match
  }
  return confusion.value.top_k_neighbors[0] ?? null
})

const confusionOtherNeighbors = computed(() => {
  if (!confusion.value || !confusionNearest.value) return []
  return confusion.value.top_k_neighbors.filter(
    n => n.eurio_id !== confusionNearest.value!.eurio_id,
  )
})

const aliasesByLang = computed(() => {
  const map = new Map<string, AliasRow[]>()
  for (const a of aliasesRows.value ?? []) {
    if (!map.has(a.lang)) map.set(a.lang, [])
    map.get(a.lang)!.push(a)
  }
  const langOrder = [...I18N_LANG_ORDER, 'xx']
  return langOrder
    .map(l => ({ lang: l, items: map.get(l) ?? [] }))
    .filter(g => g.items.length > 0)
})

function aliasSourceStyle(source: string, confidence: string): { bg: string; fg: string } {
  if (source === 'llm' && confidence === 'low') return { bg: 'var(--warning-soft, #fff8e1)', fg: 'var(--warning, #f57f17)' }
  if (source === 'llm') return { bg: 'var(--surface-1)', fg: 'var(--ink-500)' }
  if (source === 'acronym') return { bg: 'var(--indigo-100, #e8eaf6)', fg: 'var(--indigo-700, #3f51b5)' }
  return { bg: 'var(--surface-1)', fg: 'var(--ink-500)' }
}

const crossRefLinks = computed(() => {
  if (!coin.value) return []
  const links: { label: string; url: string }[] = []
  const refs = coin.value.cross_refs
  if (refs.wikipedia_url) links.push({ label: 'Wikipedia', url: refs.wikipedia_url })
  if (refs.lmdlp_url) links.push({ label: 'La Monnaie de la Pièce', url: refs.lmdlp_url })
  if (refs.mdp_urls) refs.mdp_urls.forEach((u, i) =>
    links.push({ label: `Monnaie de Paris ${refs.mdp_urls!.length > 1 ? `#${i+1}` : ''}`, url: u }),
  )
  if (refs.numista_url) links.push({ label: 'Numista', url: refs.numista_url })
  if (refs.bce_comm_url) links.push({ label: 'BCE', url: refs.bce_comm_url })
  return links
})

type Topic = { source: string; lang: string; topic: string; method?: string | null; confidence?: string }

// Numista ID : champ top-level `numista_id` fiable (colonne coins.numista_id),
// fallback sur cross_refs (rarement peuplé). Sert au bloc Identifiants + lien.
const numistaId = computed(
  () => coin.value?.numista_id ?? coin.value?.cross_refs?.numista_id ?? null,
)

// F.2 — Liste complète des topics triée pour la section "Localisation".
// Pool de toutes les sources (Numista 6 langs + BCE EN, future BCE FR),
// tri stable : source priority numista > bce, puis lang priority
// fr > en > de > it > es > nl.
const TOPIC_LANG_ORDER: Record<string, number> = {
  fr: 1, en: 2, de: 3, it: 4, es: 5, nl: 6,
}
const TOPIC_SOURCE_ORDER: Record<string, number> = {
  numista_api: 1, bce_official: 2,
}
const coinTopicsList = computed(() => {
  const all = ((coin.value as any)?.topics as Topic[] | undefined) ?? []
  return [...all].sort((a, b) => {
    const sa = TOPIC_SOURCE_ORDER[a.source] ?? 9
    const sb = TOPIC_SOURCE_ORDER[b.source] ?? 9
    if (sa !== sb) return sa - sb
    const la = TOPIC_LANG_ORDER[a.lang] ?? 9
    const lb = TOPIC_LANG_ORDER[b.lang] ?? 9
    return la - lb
  })
})

// ─── Sélecteur de langue du header (titre + description BCE) ────────────────
// Langues dispo = union (titres Numista + topics Numista/BCE + descriptions
// BCE 24 langs). Ordre : 6 langues Eurio d'abord, puis le reste alphabétique.
const availableLangs = computed<string[]>(() => {
  const set = new Set<string>()
  for (const r of i18nRows.value ?? []) set.add(r.lang)
  for (const t of coinTopicsList.value) set.add(t.lang)
  for (const d of descriptions.value ?? []) set.add(d.lang)
  set.delete('xx')
  const eurio = EURIO_LANGS.filter((l) => set.has(l))
  const rest = [...set].filter((l) => !EURIO_LANGS.includes(l)).sort()
  return [...eurio, ...rest]
})

// Défaut = fr → en → 1re dispo, recalé si la pièce change.
watch(availableLangs, (langs) => {
  if (!langs.length) { selectedLang.value = null; return }
  if (selectedLang.value && langs.includes(selectedLang.value)) return
  selectedLang.value = langs.includes('fr') ? 'fr' : langs.includes('en') ? 'en' : langs[0]
}, { immediate: true })

// Quelles sources ont un titre pour cette langue (tag court du menu).
function langSourceTag(lang: string): string {
  const hasNumista =
    coinTopicsList.value.some((t) => t.source === 'numista_api' && t.lang === lang) ||
    (i18nRows.value ?? []).some((r) => r.lang === lang)
  const hasBce = (descriptions.value ?? []).some((d) => d.lang === lang)
  if (hasNumista && hasBce) return 'NUM·BCE'
  if (hasNumista) return 'NUM'
  return 'BCE'
}

// Titre affiché pour la langue sélectionnée. Numista prioritaire (topic verbeux
// > titre court), fallback BCE. `source` pilote le badge.
const selectedTitle = computed<{ text: string; source: string } | null>(() => {
  const l = selectedLang.value
  if (!l) return null
  const topic = coinTopicsList.value.find((t) => t.source === 'numista_api' && t.lang === l)
  if (topic) return { text: topic.topic, source: 'numista' }
  const name = (i18nRows.value ?? []).find((r) => r.lang === l)
  if (name && (name.source === 'numista' || name.source === 'numista_api')) {
    return { text: name.title, source: 'numista' }
  }
  const bce = (descriptions.value ?? []).find((d) => d.lang === l)
  if (bce) return { text: bce.title, source: 'bce' }
  if (name) return { text: name.title, source: name.source }  // i18n LLM (de/it/es/nl)
  return null
})

// Description officielle BCE (texte long) pour la langue sélectionnée.
const selectedDescription = computed<CoinDescription | null>(() => {
  const l = selectedLang.value
  if (!l) return null
  return (descriptions.value ?? []).find((d) => d.lang === l && d.description) ?? null
})

function pickLang(l: string) {
  selectedLang.value = l
  langMenuOpen.value = false
}

// Style du badge de source du titre (Numista indigo / BCE or / LLM neutre).
function titleBadgeStyle(source: string): string {
  if (source === 'bce') {
    return 'border-color: var(--gold); color: var(--gold-700, var(--gold)); background: var(--gold-50, transparent);'
  }
  if (source === 'numista') {
    return 'border-color: var(--indigo-300); color: var(--indigo-600); background: var(--indigo-50);'
  }
  return 'border-color: var(--surface-3); color: var(--ink-500); background: var(--surface-1);'
}
function titleBadgeLabel(source: string): string {
  if (source === 'bce') return 'BCE'
  if (source === 'numista') return 'Numista'
  return source.toUpperCase()
}

// ─── Caractéristiques & millésimes (extraction riche Numista) ──────────────

const ISSUE_TYPE_LABEL: Record<string, string> = {
  CIRC: 'Circulation', BU: 'BU', BE: 'Belle épreuve',
  PROOF: 'Proof', COIN_CARD: 'Coincard', OTHER: 'Autre',
}

// Libellé court de provenance (registry vocab → humain).
const SOURCE_LABEL: Record<string, string> = {
  numista_api: 'Numista', bce_official: 'BCE', eurlex_jo: 'JO / EUR-Lex',
  ebay_browse: 'eBay', lmdlp: 'LMDLP', wikipedia: 'Wikipedia', manual: 'Manuel',
}
function sourceLabel(source: string): string {
  return SOURCE_LABEL[source] ?? source
}

// Une ligne « caractéristique » : label, valeur, provenance.
interface CharacRow { label: string; value: string; source: string }
const characteristicsRows = computed<CharacRow[]>(() => {
  const o = observations.value
  if (!o) return []
  // provenance par type d'observation (1re source rencontrée).
  const srcByType = new Map<string, string>()
  for (const ob of o.observations) {
    if (!srcByType.has(ob.observation_type)) srcByType.set(ob.observation_type, ob.source)
  }
  const src = (t: string) => srcByType.get(t) ?? 'numista_api'
  const rows: CharacRow[] = []
  if (o.composition) rows.push({ label: 'Composition', value: o.composition, source: src('composition') })
  if (o.weight_g != null) rows.push({ label: 'Poids', value: `${o.weight_g} g`, source: src('weight_g') })
  if (o.diameter_mm != null) rows.push({ label: 'Diamètre', value: `${o.diameter_mm} mm`, source: src('diameter_mm') })
  if (o.thickness_mm != null) rows.push({ label: 'Épaisseur', value: `${o.thickness_mm} mm`, source: src('thickness_mm') })
  if (o.shape) rows.push({ label: 'Forme', value: o.shape, source: src('shape') })
  if (o.orientation) rows.push({ label: 'Orientation', value: o.orientation, source: src('orientation') })
  if (o.edge_description) rows.push({ label: 'Tranche', value: o.edge_description, source: src('edge_description') })
  if (o.edge_lettering) rows.push({ label: 'Tranche — inscription', value: o.edge_lettering, source: src('edge_lettering') })
  if (o.edge_lettering_translation) rows.push({ label: 'Tranche — traduction', value: o.edge_lettering_translation, source: src('edge_lettering_translation') })
  if (o.obverse_lettering) rows.push({ label: 'Avers — légende', value: o.obverse_lettering, source: src('obverse_lettering') })
  if (o.reverse_lettering) rows.push({ label: 'Revers — légende', value: o.reverse_lettering, source: src('reverse_lettering') })
  if (o.is_demonetized != null) rows.push({ label: 'Démonétisée', value: o.is_demonetized ? 'Oui' : 'Non (cours légal)', source: src('demonetization') })
  return rows
})

const hasCredits = computed(() => {
  const c = credits.value
  return Boolean(c && (c.designers.length || c.engravers.length || c.sculptors.length))
})

const hasCharacteristics = computed(
  () => characteristicsRows.value.length > 0 || hasCredits.value,
)

function mintageOf(release: MintReleaseFull): number | null {
  const obs = release.observations.find(o => o.fact_type === 'mintage')
  if (!obs) return null
  const v = obs.value
  return typeof v === 'number' ? v : null
}
function formatMintage(n: number): string {
  return n.toLocaleString('fr-FR')
}

// ─── Émission officielle BCE : tirage autorisé + date d'émission ───────────
// Lus depuis les observations Type-level (source bce_official). Affichés en
// regard du tableau Numista (par millésime) sans réconciliation.
interface BceMintage { value: number | null; raw_text: string | null; source: string }
const bceMintage = computed<BceMintage | null>(() => {
  const ob = observations.value?.observations.find(x => x.observation_type === 'mintage_official')
  if (!ob) return null
  const v = ob.value as { value?: number; raw_text?: string } | null
  return { value: typeof v?.value === 'number' ? v.value : null, raw_text: v?.raw_text ?? null, source: ob.source }
})

interface BceDate { year: number | null; month: number | null; day: number | null; raw_text: string | null; source: string }
const bceIssuingDate = computed<BceDate | null>(() => {
  const ob = observations.value?.observations.find(x => x.observation_type === 'issuing_date')
  if (!ob) return null
  const v = ob.value as { year?: number; month?: number; day?: number; raw_text?: string } | null
  return {
    year: v?.year ?? null, month: v?.month ?? null, day: v?.day ?? null,
    raw_text: v?.raw_text ?? null, source: ob.source,
  }
})

const hasBceEmission = computed(() => Boolean(bceMintage.value || bceIssuingDate.value))

const FR_MONTHS = [
  'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
  'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre',
]
// Date BCE normalisée selon la granularité dispo : « 15 mars 2007 » /
// « mars 2007 » / « 2007 ». raw_text en repli (ex. « Fourth quarter 2022 »).
function formatBceDate(d: BceDate): string {
  if (!d.year) return d.raw_text ?? '—'
  const m = d.month && d.month >= 1 && d.month <= 12 ? FR_MONTHS[d.month - 1] : null
  if (d.day && m) return `${d.day} ${m} ${d.year}`
  if (m) return `${m} ${d.year}`
  return String(d.year)
}

// Somme des tirages Numista (par millésime) — situe la divergence avec le total
// autorisé BCE, sans réconcilier (les deux restent affichés).
const numistaTotalMintage = computed<number | null>(() => {
  const rels = mintReleases.value
  if (!rels?.length) return null
  let sum = 0
  let any = false
  for (const r of rels) {
    const m = mintageOf(r)
    if (m != null) { sum += m; any = true }
  }
  return any ? sum : null
})
</script>

<template>
  <div class="mx-auto max-w-5xl p-8">
    <!-- Back -->
    <button
      class="mb-6 flex items-center gap-2 text-sm transition-opacity hover:opacity-70"
      style="color: var(--ink-500);"
      @click="router.back()"
    >
      <ArrowLeft class="h-4 w-4" />
      Retour au référentiel
    </button>

    <!-- Loading -->
    <div v-if="loading" class="grid grid-cols-1 gap-8 lg:grid-cols-2">
      <div class="aspect-square animate-pulse rounded-lg" style="background: var(--surface-1);" />
      <div class="space-y-3">
        <div class="h-8 w-3/4 animate-pulse rounded" style="background: var(--surface-1);" />
        <div class="h-4 w-1/2 animate-pulse rounded" style="background: var(--surface-1);" />
        <div class="h-4 w-2/3 animate-pulse rounded" style="background: var(--surface-1);" />
      </div>
    </div>

    <!-- Error -->
    <div v-else-if="error"
         class="flex flex-col items-center justify-center rounded-lg border-2 border-dashed py-16"
         style="border-color: var(--surface-3);">
      <ShieldAlert class="mb-3 h-8 w-8" style="color: var(--danger);" />
      <p class="font-display italic text-lg" style="color: var(--ink);">{{ error }}</p>
    </div>

    <!-- Content -->
    <div v-else-if="coin" class="grid grid-cols-1 gap-8 lg:grid-cols-2">

      <!-- ═══ LEFT : Images ═══ -->
      <div>
        <!-- Main image frame -->
        <div
          class="relative flex aspect-square items-center justify-center overflow-hidden rounded-lg"
          style="background: linear-gradient(160deg, var(--surface-1), var(--surface-2)); box-shadow: var(--shadow-card);"
        >
          <template v-if="selectedImage">
            <img
              :src="selectedImage.url"
              :alt="coin.theme ?? coin.eurio_id"
              class="h-full w-full object-contain p-8"
            />
            <!-- Role label -->
            <span
              class="absolute bottom-3 left-3 rounded-full px-3 py-1 text-[10px] font-mono font-medium uppercase tracking-wider"
              style="background: rgba(14,14,31,0.8); color: white; backdrop-filter: blur(4px);"
            >
              {{ roleLabel[selectedImage.role] ?? selectedImage.role }}
            </span>
            <span
              class="absolute bottom-3 right-3 rounded-full px-3 py-1 text-[10px] font-mono uppercase tracking-wider"
              style="background: rgba(14,14,31,0.8); color: rgba(255,255,255,0.6); backdrop-filter: blur(4px);"
            >
              src: {{ selectedImage.source }}
            </span>
          </template>
          <div v-else class="flex flex-col items-center gap-2" style="color: var(--ink-300);">
            <ImageOff class="h-12 w-12" />
            <p class="text-xs uppercase tracking-wider">Aucune image disponible</p>
            <p class="text-[10px]" style="color: var(--ink-400);">
              Pipeline Numista à venir (phase 4)
            </p>
          </div>
        </div>

        <!-- Thumbnails -->
        <div v-if="Array.isArray(coin.images) && coin.images.length > 1"
             class="mt-3 flex gap-2 overflow-x-auto">
          <button
            v-for="(img, i) in (coin.images as CoinImage[])"
            :key="i"
            class="flex h-16 w-16 flex-shrink-0 items-center justify-center rounded-md border-2 transition-all"
            :style="selectedImage === img
              ? 'border-color: var(--gold); background: var(--surface-1)'
              : 'border-color: var(--surface-3); background: var(--surface)'"
            @click="selectedImage = img"
          >
            <img :src="img.url" :alt="img.role" class="h-full w-full object-contain p-1" />
          </button>
        </div>

        <!-- Enrichment gallery (sous les thumbs référentiels) -->
        <EnrichmentGallery
          :eurio-id="coin.eurio_id"
          :selected-url="selectedImage?.url ?? null"
          @select="onEnrichmentSelect"
        />
      </div>

      <!-- ═══ RIGHT : Metadata ═══ -->
      <div>
        <!-- Header -->
        <div class="mb-5">
          <p class="mb-1 text-xs font-medium uppercase"
             style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            {{ coin.country }} · {{ coin.year }}
          </p>
          <div class="flex items-start gap-2">
            <!-- Sélecteur de langue (ISO-2, 24 langues UE) — pilote le titre + la description BCE -->
            <div v-if="availableLangs.length > 1" class="relative mt-1.5 flex-shrink-0">
              <button
                class="flex items-center gap-1 rounded-md border px-2 py-1 font-mono text-xs font-semibold uppercase transition-colors hover:border-current"
                style="border-color: var(--surface-3); color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);"
                :title="selectedLang ? (EU_LANG_LABEL[selectedLang] ?? selectedLang) : 'Langue'"
                @click="langMenuOpen = !langMenuOpen"
              >
                {{ selectedLang }}
                <ChevronDown class="h-3 w-3" />
              </button>
              <button v-if="langMenuOpen" class="fixed inset-0 z-10" @click="langMenuOpen = false" />
              <div
                v-if="langMenuOpen"
                class="absolute left-0 top-full z-20 mt-1 grid max-h-72 w-48 grid-cols-2 gap-0.5 overflow-y-auto rounded-lg border p-1"
                style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-md);"
              >
                <button
                  v-for="l in availableLangs"
                  :key="l"
                  class="flex items-center justify-between gap-1 rounded px-2 py-1 text-left transition-colors hover:bg-surface-1"
                  :style="l === selectedLang ? 'background: var(--surface-1);' : ''"
                  :title="EU_LANG_LABEL[l] ?? l"
                  @click="pickLang(l)"
                >
                  <span class="font-mono text-xs font-semibold uppercase" style="color: var(--ink);">{{ l }}</span>
                  <span class="font-mono text-[9px]" style="color: var(--ink-400);">{{ langSourceTag(l) }}</span>
                </button>
              </div>
            </div>
            <h1 class="font-display text-3xl italic font-semibold leading-tight"
                style="color: var(--indigo-700);">
              {{ selectedTitle?.text ?? coinDisplayName(coin as any) }}
            </h1>
            <span v-if="selectedTitle"
                  class="mt-2 inline-flex flex-shrink-0 items-center rounded-full border px-2 py-0.5 text-[9px] font-medium uppercase tracking-wider"
                  :style="titleBadgeStyle(selectedTitle.source)">
              {{ titleBadgeLabel(selectedTitle.source) }}
            </span>
          </div>
          <p class="mt-1 font-mono text-sm" style="color: var(--ink-400);">
            {{ formatFaceValue(coin.face_value) }}
          </p>
          <!-- Badges de variantes (canonique + coloured/hologram/mule/pattern).
               ℹ au survol = libellé ; clic = navigue vers la variante. -->
          <div v-if="hasVariantGroup" class="mt-3 flex flex-wrap items-center gap-1.5">
            <VariantBadge
              v-for="m in variantMembers"
              :key="m.eurio_id"
              :kind="m.variant_kind"
              :label="m.variant_label"
              :title="m.title"
              :active="m.is_self"
              @select="goToVariant(m)"
            />
          </div>
          <!-- Description officielle BCE pour la langue sélectionnée (24 langs UE).
               Pilotée par le sélecteur ; absente si la langue n'a pas de desc BCE. -->
          <div v-if="selectedDescription"
               class="mt-4 rounded-lg border p-4"
               style="border-color: var(--surface-3); background: var(--surface);">
            <div class="mb-2 flex items-center gap-2">
              <span class="inline-flex flex-shrink-0 items-center rounded-full border px-2 py-0.5 text-[9px] font-medium uppercase tracking-wider"
                    style="border-color: var(--gold); color: var(--gold-700, var(--gold)); background: var(--gold-50, transparent);">
                BCE
              </span>
              <span class="text-[10px] uppercase" style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
                Description officielle · {{ (EU_LANG_LABEL[selectedLang!] ?? selectedLang) }}
              </span>
            </div>
            <p class="text-sm leading-relaxed" style="color: var(--ink);">
              {{ selectedDescription.description }}
            </p>
          </div>
          <!-- Encart : description BCE indisponible (pas encore publiée / échec) -->
          <div v-else-if="bceState === 'empty_upstream' || bceState === 'error'"
               class="mt-4 flex items-center gap-2 rounded-lg border border-dashed p-3"
               style="border-color: var(--surface-3); background: var(--surface);">
            <span class="inline-flex flex-shrink-0 items-center rounded-full border px-2 py-0.5 text-[9px] font-medium uppercase tracking-wider"
                  style="border-color: var(--gold); color: var(--gold-700, var(--gold)); background: var(--gold-50, transparent);">
              BCE
            </span>
            <p class="text-xs" style="color: var(--ink-500);">
              {{ bceState === 'empty_upstream'
                ? 'Description officielle pas encore publiée côté BCE.'
                : 'Échec du dernier fetch BCE — réessaie via « Disponibilité des sources ».' }}
            </p>
          </div>
        </div>

        <!-- Gold separator -->
        <div class="mb-5 h-px w-16" style="background: var(--gold);" />

        <!-- Quick facts grid -->
        <div class="space-y-3">
          <!-- Face value -->
          <div class="flex items-start gap-3">
            <CoinsIcon class="mt-0.5 h-4 w-4 flex-shrink-0" style="color: var(--ink-400);" />
            <div class="flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Valeur faciale
              </p>
              <p class="font-mono text-sm" style="color: var(--ink);">
                {{ formatFaceValue(coin.face_value) }}
              </p>
            </div>
          </div>

          <!-- Country + year -->
          <div class="flex items-start gap-3">
            <MapPin class="mt-0.5 h-4 w-4 flex-shrink-0" style="color: var(--ink-400);" />
            <div class="flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Pays · année
              </p>
              <p class="text-sm" style="color: var(--ink);">
                <span class="font-mono uppercase">{{ coin.country }}</span> ·
                <span class="font-mono">{{ coin.year }}</span>
              </p>
            </div>
          </div>

          <!-- Issue type -->
          <div v-if="coin.issue_type" class="flex items-start gap-3">
            <Info class="mt-0.5 h-4 w-4 flex-shrink-0" style="color: var(--ink-400);" />
            <div class="flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Type d'émission
              </p>
              <p class="text-sm" style="color: var(--ink);">{{ issueLabel[coin.issue_type] }}</p>
            </div>
          </div>

          <!-- Series -->
          <div v-if="series" class="flex items-start gap-3">
            <Layers class="mt-0.5 h-4 w-4 flex-shrink-0" style="color: var(--ink-400);" />
            <div class="flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Série
              </p>
              <p class="text-sm" style="color: var(--ink);">
                {{ series.designation_i18n?.fr ?? series.designation }}
              </p>
              <p class="font-mono text-[11px]" style="color: var(--ink-400);">
                {{ series.id }} · {{ seriesMintingPeriod }}
                <span v-if="series.minting_ended_at">· frappe arrêtée</span>
              </p>
            </div>
          </div>

          <!-- Withdrawal -->
          <div v-if="coin.is_withdrawn" class="flex items-start gap-3">
            <ShieldAlert class="mt-0.5 h-4 w-4 flex-shrink-0" style="color: var(--danger);" />
            <div class="flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--danger);">
                Retirée de circulation
              </p>
              <p class="text-sm" style="color: var(--ink);">
                {{ formatDate(coin.withdrawn_at) }}
                <span v-if="coin.withdrawal_reason">· {{ coin.withdrawal_reason }}</span>
              </p>
            </div>
          </div>

          <!-- Mintage -->
          <div v-if="coin.mintage" class="flex items-start gap-3">
            <Calendar class="mt-0.5 h-4 w-4 flex-shrink-0" style="color: var(--ink-400);" />
            <div class="flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                Tirage
              </p>
              <p class="font-mono text-sm" style="color: var(--ink);">
                {{ coin.mintage.toLocaleString('fr-FR') }} ex.
              </p>
            </div>
          </div>
        </div>

        <!-- Design description -->
        <div v-if="coin.design_description" class="mt-6">
          <p class="mb-2 text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            Description du design
          </p>
          <p class="text-sm leading-relaxed" style="color: var(--ink);">
            {{ coin.design_description }}
          </p>
        </div>

        <!-- Cross references -->
        <div v-if="crossRefLinks.length > 0" class="mt-6">
          <p class="mb-2 text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            Références externes
          </p>
          <div class="flex flex-wrap gap-2">
            <a
              v-for="link in crossRefLinks"
              :key="link.url"
              :href="link.url"
              target="_blank"
              rel="noopener"
              class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors hover:bg-surface-1"
              style="border-color: var(--surface-3); color: var(--ink-500);"
            >
              {{ link.label }}
              <ExternalLink class="h-3 w-3" />
            </a>
          </div>
        </div>

        <!-- Training status -->
        <div class="mt-6">
          <p class="mb-2 text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            Reconnaissance ML
          </p>
          <div
            class="flex items-center justify-between rounded-lg border px-4 py-3"
            :style="{
              borderColor: trainedModelVersion ? 'var(--success)' : 'var(--surface-3)',
              background: trainedModelVersion
                ? 'color-mix(in srgb, var(--success) 6%, var(--surface))'
                : 'var(--surface)',
            }"
          >
            <div class="flex items-center gap-2.5">
              <Brain
                class="h-4 w-4"
                :style="{ color: trainedModelVersion ? 'var(--success)' : 'var(--ink-400)' }"
              />
              <div>
                <p class="text-sm font-medium" :style="{ color: trainedModelVersion ? 'var(--success)' : 'var(--ink-500)' }">
                  {{ trainedModelVersion ? 'Design entraîné' : 'Non entraîné' }}
                </p>
                <p v-if="trainedModelVersion" class="font-mono text-[10px]" style="color: var(--ink-400);">
                  Modèle {{ trainedModelVersion }}
                </p>
              </div>
            </div>
            <div v-if="coin.cross_refs?.numista_id" class="flex items-center gap-2">
              <button
                v-if="!trainedModelVersion"
                class="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all"
                :style="{
                  background: enqueueState === 'success' ? 'var(--success)' : 'var(--indigo-700)',
                  color: 'white',
                  opacity: enqueueState === 'loading' ? '0.7' : '1',
                }"
                :disabled="enqueueState !== 'idle'"
                @click="enqueueForTraining"
              >
                <Loader2 v-if="enqueueState === 'loading'" class="h-3 w-3 animate-spin" />
                <Check v-else-if="enqueueState === 'success'" class="h-3 w-3" />
                <Play v-else class="h-3 w-3" />
                {{ enqueueState === 'success' ? 'Ajouté !' : 'Entraîner' }}
              </button>
              <button
                class="flex items-center gap-1 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors hover:border-current"
                style="border-color: var(--surface-3); color: var(--ink-500);"
                @click="router.push('/training')"
              >
                Voir training
                <ArrowUpRight class="h-3 w-3" />
              </button>
            </div>
          </div>
        </div>

        <!-- Prix de marché eBay -->
        <div class="mt-6">
          <p class="mb-2 text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            Prix de marché eBay
          </p>

          <!-- Loading -->
          <div
            v-if="marketPriceLoading"
            class="h-20 animate-pulse rounded-lg"
            style="background: var(--surface-1);"
          />

          <!-- Not fetched yet -->
          <div
            v-else-if="marketPrice === null"
            class="flex items-center gap-3 rounded-lg border px-4 py-3"
            style="border-color: var(--surface-3); background: var(--surface);"
          >
            <TrendingUp class="h-4 w-4 flex-shrink-0" style="color: var(--ink-400);" />
            <p class="text-sm" style="color: var(--ink-500);">Pas encore fetchés</p>
          </div>

          <!-- Prices available -->
          <div
            v-else-if="marketPrice"
            class="rounded-lg border px-4 py-4"
            style="border-color: var(--surface-3); background: var(--surface);"
          >
            <!-- P25 / P50 / P75 row -->
            <div class="flex items-end gap-4">
              <!-- P25 -->
              <div class="flex-1 text-center">
                <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">P25</p>
                <p class="font-mono text-sm tabular-nums" style="color: var(--ink);">
                  {{ formatPrice(marketPrice.p25) }} €
                </p>
              </div>

              <!-- P50 — highlighted -->
              <div
                class="flex-1 rounded-md px-3 py-2 text-center"
                style="background: color-mix(in srgb, var(--gold) 10%, var(--surface));"
              >
                <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">P50 médiane</p>
                <p class="font-mono text-xl font-semibold tabular-nums" style="color: var(--indigo-700);">
                  {{ formatPrice(marketPrice.p50) }} €
                </p>
              </div>

              <!-- P75 -->
              <div class="flex-1 text-center">
                <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">P75</p>
                <p class="font-mono text-sm tabular-nums" style="color: var(--ink);">
                  {{ formatPrice(marketPrice.p75) }} €
                </p>
              </div>
            </div>

            <!-- Meta row -->
            <div class="mt-3 flex items-center justify-between border-t pt-3"
                 style="border-color: var(--surface-2);">
              <p class="text-[11px]" style="color: var(--ink-400);">
                {{ marketPrice.samples_count }} annonces analysées
              </p>
              <p class="font-mono text-[10px]" style="color: var(--ink-400);">
                {{ formatShortDate(marketPrice.fetched_at) }}
              </p>
            </div>
          </div>
        </div>

        <!-- Prix catalogue LMDLP — affiché séparément d'eBay -->
        <div v-if="lmdlpPrices && lmdlpPrices.length > 0" class="mt-6">
          <p class="mb-2 text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            Prix catalogue La Monnaie de la Pièce
          </p>
          <div
            class="rounded-lg border"
            style="border-color: var(--surface-3); background: var(--surface);"
          >
            <div
              v-for="(p, i) in lmdlpPrices"
              :key="p.quality"
              class="flex items-center justify-between px-4 py-2.5"
              :class="i > 0 ? 'border-t' : ''"
              style="border-color: var(--surface-2);"
            >
              <div class="flex items-center gap-2">
                <span class="font-mono text-xs uppercase" style="color: var(--ink);">
                  {{ p.quality }}
                </span>
                <span
                  v-if="!p.in_stock"
                  class="rounded-full px-1.5 py-0.5 text-[9px] font-medium uppercase"
                  style="background: var(--surface-1); color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
                >
                  rupture
                </span>
              </div>
              <p class="font-mono text-sm tabular-nums" style="color: var(--indigo-700);">
                {{ formatPrice(p.p50) }} €
              </p>
            </div>
            <div class="flex items-center justify-between border-t px-4 py-2"
                 style="border-color: var(--surface-2); background: var(--surface-1);">
              <p class="text-[11px]" style="color: var(--ink-400);">
                Prix catalogue par qualité (1 obs / qualité)
              </p>
              <p class="font-mono text-[10px]" style="color: var(--ink-400);">
                {{ formatShortDate(lmdlpPrices[0].fetched_at) }}
              </p>
            </div>
          </div>
        </div>

        <!-- Identifiants (copyables) -->
        <div class="mt-8 space-y-2">
          <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
            Identifiants
          </p>
          <div
            class="flex items-center justify-between gap-2 rounded-md border px-3 py-2"
            style="border-color: var(--surface-3); background: var(--surface-1);"
          >
            <div class="min-w-0 flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Eurio ID</p>
              <p class="truncate font-mono text-xs" style="color: var(--ink);" :title="coin.eurio_id">
                {{ coin.eurio_id }}
              </p>
            </div>
            <button
              class="flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition-colors hover:border-current"
              style="border-color: var(--surface-3); color: var(--ink-500);"
              :title="`Copier ${coin.eurio_id}`"
              @click="copyToClipboard(coin.eurio_id, 'EurioID', $event)"
            >
              <Copy class="h-3 w-3" />
              Copier
            </button>
          </div>

          <div
            v-if="numistaId"
            class="flex items-center justify-between gap-2 rounded-md border px-3 py-2"
            style="border-color: var(--surface-3); background: var(--surface-1);"
          >
            <div class="min-w-0 flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Numista ID</p>
              <a
                class="font-mono text-xs underline-offset-2 hover:underline"
                style="color: var(--ink);"
                :href="`https://en.numista.com/catalogue/pieces${numistaId}.html`"
                target="_blank"
                rel="noopener"
              >
                N{{ numistaId }}
              </a>
            </div>
            <button
              class="flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition-colors hover:border-current"
              style="border-color: var(--surface-3); color: var(--ink-500);"
              :title="`Copier ${numistaId}`"
              @click="copyToClipboard(String(numistaId), 'NumistaID', $event)"
            >
              <Copy class="h-3 w-3" />
              Copier
            </button>
          </div>

          <div
            v-if="coin.design_group_id"
            class="flex items-center justify-between gap-2 rounded-md border px-3 py-2"
            style="border-color: var(--surface-3); background: var(--surface-1);"
          >
            <div class="min-w-0 flex-1">
              <p class="text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">Design Group</p>
              <p class="truncate font-mono text-xs" style="color: var(--ink);" :title="coin.design_group_id">
                {{ coin.design_group_id }}
              </p>
            </div>
            <button
              class="flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition-colors hover:border-current"
              style="border-color: var(--surface-3); color: var(--ink-500);"
              :title="`Copier ${coin.design_group_id}`"
              @click="copyToClipboard(coin.design_group_id!, 'DesignGroupID', $event)"
            >
              <Copy class="h-3 w-3" />
              Copier
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Clipboard copy toast -->
    <Teleport to="body">
      <Transition name="copy-toast">
        <div
          v-if="copiedToast"
          class="fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 items-center gap-2 rounded-md border px-3 py-2 text-xs"
          style="background: var(--surface); border-color: var(--surface-3); box-shadow: var(--shadow-md); color: var(--ink)"
        >
          <Check class="h-3 w-3" style="color: var(--success)" />
          <span><strong>{{ copiedToast.label }}</strong> copié</span>
          <code
            class="truncate rounded px-1.5 py-0.5 font-mono text-[10px]"
            style="background: var(--surface-1); color: var(--ink-500); max-width: 320px;"
          >{{ copiedToast.value }}</code>
        </div>
      </Transition>
    </Teleport>

    <!-- ═══ Disponibilité des sources (état + refresh) ═══ -->
    <div v-if="coin" class="mt-12">
      <div class="mb-5 flex items-end justify-between border-b pb-3"
           style="border-color: var(--surface-3);">
        <div>
          <p class="text-[10px] uppercase"
             style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            Référentiel
          </p>
          <h2 class="mt-0.5 font-display text-2xl italic font-semibold"
              style="color: var(--indigo-700);">
            Disponibilité des sources
          </h2>
        </div>
        <p v-if="refreshError" class="text-xs" style="color: var(--danger);">{{ refreshError }}</p>
      </div>

      <div v-if="sourceStatus === undefined"
           class="h-24 animate-pulse rounded-lg" style="background: var(--surface-1);" />

      <div v-else-if="sourceStatus" class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <div v-for="s in sourceStatus.sources" :key="s.source"
             class="flex flex-col rounded-lg border p-4"
             style="border-color: var(--surface-3); background: var(--surface);">
          <div class="flex items-center justify-between gap-2">
            <span class="font-mono text-xs font-semibold uppercase"
                  style="color: var(--ink); letter-spacing: var(--tracking-eyebrow);">
              {{ sourceLabel(s.source) }}
            </span>
            <span class="rounded-full border px-2 py-0.5 text-[9px] font-medium uppercase tracking-wider"
                  :style="sourceStateStyle(s.state)">
              {{ SOURCE_STATE_LABEL[s.state] ?? s.state }}
            </span>
          </div>

          <!-- Axes présents (état ok) -->
          <div v-if="s.state === 'ok'" class="mt-2.5 flex flex-wrap gap-1">
            <span v-for="ax in sourceAxes(s.source)" :key="ax"
                  class="rounded px-1.5 py-0.5 text-[9px] font-medium"
                  :style="s.axes[ax]
                    ? 'background: var(--success-soft, #e8f5e9); color: var(--success, #2e7d32);'
                    : 'background: var(--surface-1); color: var(--ink-400);'">
              {{ SOURCE_AXIS_LABELS[ax] ?? ax }}
            </span>
          </div>
          <!-- Message d'état (autres) -->
          <p v-else class="mt-2.5 text-xs leading-snug" style="color: var(--ink-500);">
            {{ stateMessage(s.state) }}
          </p>

          <!-- Footer : dernière vérif + refresh -->
          <div class="mt-3 flex items-center justify-between gap-2 border-t pt-2.5"
               style="border-color: var(--surface-2);">
            <span class="font-mono text-[10px]" style="color: var(--ink-400);">
              {{ s.last_checked_at ? s.last_checked_at.slice(0, 10) : '—' }}
            </span>
            <button
              v-if="SOURCE_REFRESH[s.source]"
              class="flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium transition-colors hover:border-current disabled:opacity-50"
              style="border-color: var(--surface-3); color: var(--ink-500);"
              :disabled="refreshingSource !== null"
              @click="refreshSource(SOURCE_REFRESH[s.source])"
            >
              <RefreshCw class="h-3 w-3"
                         :class="refreshingSource === SOURCE_REFRESH[s.source] ? 'animate-spin' : ''" />
              {{ refreshingSource === SOURCE_REFRESH[s.source] ? 'Refresh…' : 'Rafraîchir' }}
            </button>
            <span v-else class="text-[10px] uppercase" style="color: var(--ink-400);">
              lecture seule
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ Localisation : titres traduits & alias ═══ -->
    <div v-if="coin" class="mt-12">
      <div class="mb-5 flex items-end justify-between border-b pb-3"
           style="border-color: var(--surface-3);">
        <div>
          <p class="text-[10px] uppercase"
             style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            Localisation
          </p>
          <h2 class="mt-0.5 font-display text-2xl italic font-semibold"
              style="color: var(--indigo-700);">
            Titres traduits & alias
          </h2>
        </div>
        <span v-if="availableLangs.length > 0"
              class="font-mono text-[10px] uppercase"
              style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);">
          {{ availableLangs.length }} langs · {{ coinTopicsList.length }} topics · {{ aliasesRows?.length ?? 0 }} alias
        </span>
      </div>

      <!-- Loading -->
      <div v-if="i18nRows === undefined"
           class="h-32 animate-pulse rounded-lg"
           style="background: var(--surface-1);" />

      <!-- Empty -->
      <div v-else-if="i18nRows.length === 0"
           class="flex items-center gap-3 rounded-lg border px-5 py-4"
           style="border-color: var(--surface-3); background: var(--surface);">
        <Info class="h-5 w-5" style="color: var(--ink-400);" />
        <p class="text-sm" style="color: var(--ink-500);">
          Aucune traduction enregistrée pour cette pièce.
        </p>
      </div>

      <!-- Content : 3 sections distinctes (F.2 — chantier D follow-up) :
           Titres (i18n short Numista) / Topics (verbeux multi-source) /
           Aliases (market vocab). Reflète le pool réel du theme matcher. -->
      <template v-else>
        <!-- 1️⃣  TOPICS — verbose commemorated_topic multi-source (Numista + BCE).
             Les titres courts par langue sont désormais portés par le sélecteur
             du header ; ici on garde le contexte commémoratif verbeux. -->
        <div v-if="coinTopicsList.length > 0">
          <p class="mb-3 text-[10px] uppercase tracking-wider"
             style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            Topics verbeux (commemorated_topic Numista + feature BCE)
          </p>
          <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div
              v-for="t in coinTopicsList"
              :key="`${t.source}|${t.lang}`"
              class="flex flex-col gap-2 rounded-lg border p-4"
              style="border-color: var(--surface-3); background: var(--surface);"
            >
              <div class="flex items-center justify-between">
                <span class="font-mono text-xs font-semibold uppercase"
                      style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
                  {{ t.lang }} · {{ I18N_LANG_LABEL[t.lang] ?? t.lang }}
                </span>
                <span
                  class="rounded-full border px-2 py-0.5 text-[9px] font-medium uppercase"
                  :style="t.source === 'bce_official'
                    ? 'border-color: var(--gold); color: var(--gold-700, var(--gold));'
                    : 'border-color: var(--indigo-300); color: var(--indigo-600); background: var(--indigo-50);'"
                >
                  {{ t.source === 'bce_official' ? 'BCE' : 'Numista' }}
                </span>
              </div>
              <p class="text-sm leading-snug" style="color: var(--ink);">
                {{ t.topic }}
              </p>
              <p v-if="t.method && t.method.startsWith('llm')"
                 class="font-mono text-[10px]"
                 style="color: var(--ink-400);">
                claude-opus-4-7
              </p>
            </div>
          </div>
        </div>

        <!-- 3️⃣  ALIASES — market vocabulary grouped by lang -->
        <div v-if="aliasesByLang.length > 0" class="mt-8">
          <p class="mb-3 text-[10px] uppercase tracking-wider"
             style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            Alias colloquiaux (vocabulaire marché theme-matcher)
          </p>
          <div class="space-y-3">
            <div
              v-for="group in aliasesByLang"
              :key="group.lang"
              class="flex items-baseline gap-3 rounded-lg border px-4 py-3"
              style="border-color: var(--surface-3); background: var(--surface);"
            >
              <span class="w-12 shrink-0 font-mono text-xs font-semibold uppercase"
                    style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
                {{ group.lang }}
              </span>
              <div class="flex flex-wrap gap-1.5">
                <span
                  v-for="a in group.items"
                  :key="a.alias"
                  class="rounded-md px-2 py-0.5 font-mono text-xs"
                  :style="{
                    background: aliasSourceStyle(a.source, a.confidence).bg,
                    color: aliasSourceStyle(a.source, a.confidence).fg,
                  }"
                  :title="`${a.source} · ${a.confidence}`"
                >
                  {{ a.alias }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </template>
    </div>

    <!-- ═══ Caractéristiques (observations + crédits) — pleine largeur ═══ -->
    <div v-if="coin" class="mt-12">
      <div class="mb-5 flex items-end justify-between border-b pb-3"
           style="border-color: var(--surface-3);">
        <div>
          <p class="text-[10px] uppercase"
             style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            Référentiel
          </p>
          <h2 class="mt-0.5 font-display text-2xl italic font-semibold"
              style="color: var(--indigo-700);">
            Caractéristiques
          </h2>
        </div>
      </div>

      <!-- Loading -->
      <div v-if="observations === undefined"
           class="h-24 animate-pulse rounded-lg" style="background: var(--surface-1);" />

      <!-- Empty -->
      <div v-else-if="!hasCharacteristics"
           class="rounded-lg border px-4 py-6 text-center text-sm"
           style="border-color: var(--surface-3); background: var(--surface); color: var(--ink-500);">
        Aucune caractéristique extraite (refetch Numista requis).
      </div>

      <!-- Content -->
      <div v-else class="grid gap-6 lg:grid-cols-2">
        <!-- Specs physiques + légendes -->
        <div v-if="characteristicsRows.length"
             class="rounded-lg border overflow-hidden"
             style="border-color: var(--surface-3); background: var(--surface);">
          <div v-for="(row, i) in characteristicsRows" :key="row.label"
               class="flex items-start justify-between gap-3 px-4 py-2.5"
               :class="i > 0 ? 'border-t' : ''" style="border-color: var(--surface-2);">
            <span class="text-xs uppercase tracking-wider flex-shrink-0"
                  style="color: var(--ink-500);">{{ row.label }}</span>
            <span class="flex items-center gap-2 text-right">
              <span class="text-sm" style="color: var(--ink);">{{ row.value }}</span>
              <span class="rounded-full px-1.5 py-0.5 text-[9px] font-medium uppercase flex-shrink-0"
                    style="background: var(--success-soft, #e8f5e9); color: var(--success, #2e7d32);"
                    :title="row.source">{{ sourceLabel(row.source) }}</span>
            </span>
          </div>
        </div>

        <!-- Crédits (designers / graveurs / sculpteurs) -->
        <div v-if="hasCredits"
             class="rounded-lg border px-4 py-4 space-y-4"
             style="border-color: var(--surface-3); background: var(--surface);">
          <template v-for="grp in [
            { label: 'Designers', items: credits!.designers },
            { label: 'Graveurs', items: credits!.engravers },
            { label: 'Sculpteurs', items: credits!.sculptors },
          ]" :key="grp.label">
            <div v-if="grp.items.length">
              <p class="mb-1.5 text-[10px] uppercase tracking-wider" style="color: var(--ink-500);">
                {{ grp.label }}
              </p>
              <div class="flex flex-wrap gap-2">
                <span v-for="c in grp.items" :key="c.name + (c.source_ref ?? '')"
                      class="flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs"
                      style="border-color: var(--surface-3); color: var(--ink);">
                  {{ c.name }}
                  <span v-if="c.source_ref" class="text-[9px] uppercase" style="color: var(--ink-400);">
                    {{ roleLabel[c.source_ref] ?? c.source_ref }}
                  </span>
                  <span class="rounded-full px-1.5 py-0.5 text-[9px] font-medium uppercase"
                        style="background: var(--success-soft, #e8f5e9); color: var(--success, #2e7d32);"
                        :title="c.source">{{ sourceLabel(c.source) }}</span>
                </span>
              </div>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- ═══ Tirages & émission (BCE total autorisé + Numista par millésime) ═══ -->
    <div v-if="coin" class="mt-12">
      <div class="mb-5 flex items-end justify-between border-b pb-3"
           style="border-color: var(--surface-3);">
        <div>
          <p class="text-[10px] uppercase"
             style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            Référentiel
          </p>
          <h2 class="mt-0.5 font-display text-2xl italic font-semibold"
              style="color: var(--indigo-700);">
            Tirages &amp; émission
          </h2>
        </div>
        <span v-if="mintReleases && mintReleases.length"
              class="text-xs" style="color: var(--ink-500);">
          {{ mintReleases.length }} millésime(s)
        </span>
      </div>

      <!-- Loading -->
      <div v-if="mintReleases === undefined"
           class="h-24 animate-pulse rounded-lg" style="background: var(--surface-1);" />

      <!-- Empty (ni BCE ni Numista) -->
      <div v-else-if="!hasBceEmission && (!mintReleases || mintReleases.length === 0)"
           class="rounded-lg border px-4 py-6 text-center text-sm"
           style="border-color: var(--surface-3); background: var(--surface); color: var(--ink-500);">
        Aucun tirage (refetch Numista / BCE requis).
      </div>

      <div v-else class="space-y-8">
        <!-- ── BCE : émission officielle (total autorisé + date) ── -->
        <div v-if="hasBceEmission">
          <div class="mb-2 flex items-center gap-2">
            <span class="inline-flex items-center rounded-full border px-2 py-0.5 text-[9px] font-medium uppercase tracking-wider"
                  style="border-color: var(--gold); color: var(--gold-700, var(--gold)); background: var(--gold-50, transparent);">
              BCE
            </span>
            <h3 class="font-display text-lg italic font-semibold" style="color: var(--indigo-700);">
              Émission officielle
            </h3>
          </div>
          <div class="rounded-lg border overflow-hidden"
               style="border-color: var(--surface-3); background: var(--surface);">
          <div v-if="bceMintage" class="flex items-start justify-between gap-3 px-4 py-2.5">
            <span class="text-xs uppercase tracking-wider" style="color: var(--ink-500);">Tirage autorisé</span>
            <span class="text-right">
              <span class="font-mono text-sm tabular-nums" style="color: var(--ink);">
                {{ bceMintage.value != null ? `${formatMintage(bceMintage.value)} ex.` : '—' }}
              </span>
              <span v-if="bceMintage.raw_text" class="block font-mono text-[10px]" style="color: var(--ink-400);">
                {{ bceMintage.raw_text }}
              </span>
            </span>
          </div>
          <div v-if="bceIssuingDate" class="flex items-start justify-between gap-3 border-t px-4 py-2.5"
               style="border-color: var(--surface-2);">
            <span class="text-xs uppercase tracking-wider" style="color: var(--ink-500);">Date d'émission</span>
            <span class="text-right">
              <span class="text-sm" style="color: var(--ink);">{{ formatBceDate(bceIssuingDate) }}</span>
              <span v-if="bceIssuingDate.raw_text && bceIssuingDate.raw_text !== formatBceDate(bceIssuingDate)"
                    class="block font-mono text-[10px]" style="color: var(--ink-400);">
                {{ bceIssuingDate.raw_text }}
              </span>
            </span>
          </div>
          </div>
        </div>

        <!-- ── Numista : millésimes (par atelier × type) ── -->
        <div v-if="mintReleases && mintReleases.length">
          <div class="mb-2 flex items-center gap-2">
            <span class="inline-flex items-center rounded-full border px-2 py-0.5 text-[9px] font-medium uppercase tracking-wider"
                  style="border-color: var(--indigo-300); color: var(--indigo-600); background: var(--indigo-50);">
              Numista
            </span>
            <h3 class="font-display text-lg italic font-semibold" style="color: var(--indigo-700);">
              Millésimes
            </h3>
          </div>
          <div class="rounded-lg border overflow-hidden"
               style="border-color: var(--surface-3); background: var(--surface);">
          <table class="w-full border-collapse text-sm">
            <thead>
              <tr style="background: var(--surface-1);">
                <th class="px-3 py-2 text-left text-[10px] font-medium uppercase tracking-wider" style="color: var(--ink-500);">Année</th>
                <th class="px-3 py-2 text-left text-[10px] font-medium uppercase tracking-wider" style="color: var(--ink-500);">Atelier</th>
                <th class="px-3 py-2 text-left text-[10px] font-medium uppercase tracking-wider" style="color: var(--ink-500);">Type</th>
                <th class="px-3 py-2 text-right text-[10px] font-medium uppercase tracking-wider" style="color: var(--ink-500);">Tirage</th>
                <th class="px-3 py-2 text-left text-[10px] font-medium uppercase tracking-wider" style="color: var(--ink-500);">Cote</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="rel in mintReleases" :key="rel.id"
                  class="border-t align-top" style="border-color: var(--surface-2);">
                <td class="px-3 py-2 font-mono font-semibold" style="color: var(--ink);">{{ rel.mint_year }}</td>
                <td class="px-3 py-2" style="color: var(--ink-500);">{{ rel.mint_id ?? '—' }}</td>
                <td class="px-3 py-2">
                  <span class="rounded-full px-2 py-0.5 text-[10px] font-medium uppercase"
                        style="background: var(--surface-1); color: var(--ink-500);">
                    {{ ISSUE_TYPE_LABEL[rel.issue_type] ?? rel.issue_type }}
                  </span>
                </td>
                <td class="px-3 py-2 text-right font-mono tabular-nums" style="color: var(--ink);">
                  {{ mintageOf(rel) != null ? formatMintage(mintageOf(rel)!) : '—' }}
                </td>
                <td class="px-3 py-2">
                  <div v-if="rel.prices.length" class="flex flex-wrap gap-1.5">
                    <span v-for="p in rel.prices" :key="p.grade_raw"
                          class="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs"
                          style="background: var(--surface-1);"
                          :title="`${p.grade_raw} · ${sourceLabel(p.source)} · ${formatShortDate(p.fetched_at)}`">
                      <span class="font-medium uppercase" style="color: var(--ink-500);">{{ p.grade_eurio ?? p.grade_raw }}</span>
                      <span class="font-mono tabular-nums" style="color: var(--ink);">
                        {{ formatPrice(p.price) }} {{ p.currency === 'EUR' ? '€' : p.currency }}
                      </span>
                    </span>
                  </div>
                  <span v-else style="color: var(--ink-400);">—</span>
                </td>
              </tr>
            </tbody>
            <tfoot v-if="numistaTotalMintage != null">
              <tr class="border-t" style="border-color: var(--surface-3); background: var(--surface-1);">
                <td class="px-3 py-2 text-[10px] font-medium uppercase tracking-wider" style="color: var(--ink-500);" colspan="3">
                  Total (somme millésimes)
                </td>
                <td class="px-3 py-2 text-right font-mono font-semibold tabular-nums" style="color: var(--ink);">
                  {{ formatMintage(numistaTotalMintage) }}
                </td>
                <td class="px-3 py-2"></td>
              </tr>
            </tfoot>
          </table>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══ Design group — pièces partageant l'avers (= classe ArcFace) — pleine largeur ═══ -->
    <div v-if="hasDesignGroup" class="mt-12">
      <div class="mb-5 flex items-end justify-between border-b pb-3"
           style="border-color: var(--surface-3);">
        <div>
          <p class="text-[10px] uppercase"
             style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            Design group · classe d'entraînement
          </p>
          <h2 class="mt-0.5 font-display text-2xl italic font-semibold"
              style="color: var(--indigo-700);">
            Pièces associées — même avers
          </h2>
        </div>
        <div class="text-right">
          <p class="text-sm font-medium" style="color: var(--ink);">{{ designGroupLabel }}</p>
          <p class="font-mono text-[10px] uppercase" style="color: var(--ink-400);">
            {{ designGroupMembers.length }} pièces · {{ designGroupId }}
          </p>
        </div>
      </div>
      <p class="mb-4 text-xs" style="color: var(--ink-500);">
        Même face nationale (avers), pays/années différents — regroupées en une seule classe
        ArcFace. Distinct des variantes de finition (badges en tête de fiche).
      </p>
      <div class="grid grid-cols-2 gap-4 md:grid-cols-4">
        <component
          :is="m.is_self ? 'div' : 'button'"
          v-for="m in designGroupMembers"
          :key="m.eurio_id"
          class="group flex flex-col overflow-hidden rounded-lg border text-left transition-all"
          :class="m.is_self ? '' : 'hover:-translate-y-0.5'"
          :style="`border-color: ${m.is_self ? 'var(--indigo-700)' : 'var(--surface-3)'}; background: var(--surface); box-shadow: var(--shadow-sm);`"
          @click="!m.is_self && goToConfusionCoin(m.eurio_id)"
        >
          <div
            class="relative flex aspect-square items-center justify-center overflow-hidden"
            style="background: linear-gradient(160deg, var(--surface-1), var(--surface-2));"
          >
            <img
              v-if="m.obverse_url"
              :src="m.obverse_url"
              :alt="m.title ?? m.eurio_id"
              class="h-full w-full object-contain p-4 transition-transform duration-300 group-hover:scale-105"
              loading="lazy"
            />
            <ImageOff v-else class="h-8 w-8" style="color: var(--ink-300);" />
            <span
              v-if="m.is_self"
              class="absolute right-2 top-2 rounded-full px-2 py-0.5 text-xs font-semibold"
              :style="{ background: 'var(--indigo-700)', color: 'white' }"
            >
              cette pièce
            </span>
          </div>
          <div class="flex flex-1 flex-col justify-between p-3">
            <p class="line-clamp-2 text-sm font-medium leading-snug" style="color: var(--ink);">
              {{ m.title ?? m.eurio_id }}
            </p>
            <span class="mt-2 font-mono text-[10px] uppercase" style="color: var(--ink-400);">
              {{ m.country }}{{ m.year ? ` · ${m.year}` : '' }}
            </span>
          </div>
        </component>
      </div>
    </div>

    <!-- ═══ Cartographie de confusion (Phase 1 ML scalability) — pleine largeur ═══ -->
    <div v-if="coin" class="mt-12">
      <div class="mb-5 flex items-end justify-between border-b pb-3"
           style="border-color: var(--surface-3);">
        <div>
          <p class="text-[10px] uppercase"
             style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            Cartographie de confusion
          </p>
          <h2 class="mt-0.5 font-display text-2xl italic font-semibold"
              style="color: var(--indigo-700);">
            Voisins visuels
          </h2>
        </div>
        <router-link
          to="/confusion"
          class="flex items-center gap-1 text-xs transition-opacity hover:opacity-70"
          style="color: var(--ink-500);"
        >
          Voir la carte complète
          <ArrowUpRight class="h-3 w-3" />
        </router-link>
      </div>

      <!-- Loading -->
      <div
        v-if="confusionLoading"
        class="h-64 animate-pulse rounded-lg"
        style="background: var(--surface-1);"
      />

      <!-- Unmapped -->
      <div
        v-else-if="!confusion"
        class="flex items-center gap-3 rounded-lg border px-5 py-4"
        style="border-color: var(--surface-3); background: var(--surface);"
      >
        <Network class="h-5 w-5" style="color: var(--ink-400);" />
        <div class="flex-1">
          <p class="text-sm font-medium" style="color: var(--ink);">Non cartographié</p>
          <p class="mt-0.5 text-xs" style="color: var(--ink-500);">
            Lance une cartographie depuis
            <router-link to="/confusion" class="underline" style="color: var(--indigo-700);">
              /confusion
            </router-link>
            pour évaluer la proximité visuelle de ce design.
          </p>
        </div>
      </div>

      <!-- Confusion content -->
      <template v-else>
        <!-- Zone banner (full-width) -->
        <div
          class="flex items-start gap-4 rounded-lg border p-5"
          :style="{
            borderColor: zoneStyle(confusion.zone).solid,
            background: zoneStyle(confusion.zone).soft,
          }"
        >
          <div
            class="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-full"
            :style="{ background: zoneStyle(confusion.zone).solid, color: 'white' }"
          >
            <span class="text-sm font-mono font-bold">{{ zoneStyle(confusion.zone).short }}</span>
          </div>
          <div class="flex-1">
            <div class="flex items-baseline gap-3">
              <p
                class="font-display text-xl italic font-semibold"
                :style="{ color: zoneStyle(confusion.zone).solid }"
              >
                {{ zoneStyle(confusion.zone).label }}
              </p>
              <span class="font-mono text-sm tabular-nums" :style="{ color: zoneStyle(confusion.zone).solid }">
                voisin @ {{ confusion.nearest_similarity.toFixed(3) }}
              </span>
            </div>
            <p class="mt-1.5 text-sm leading-snug" style="color: var(--ink);">
              {{ zoneCopy(confusion.zone, confusion.nearest_similarity) }}
            </p>
          </div>
        </div>

        <!-- Nearest neighbor — SIDE-BY-SIDE comparison (grand) -->
        <div v-if="confusionNearest" class="mt-6">
          <p class="mb-3 text-[10px] uppercase"
             style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            Voisin le plus proche
          </p>
          <div
            class="overflow-hidden rounded-lg border"
            style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-card);"
          >
            <!-- Image comparison -->
            <div class="grid grid-cols-1 md:grid-cols-2">
              <!-- Current coin (left) -->
              <div
                class="relative flex aspect-square items-center justify-center overflow-hidden"
                style="background: linear-gradient(160deg, var(--surface-1), var(--surface-2));"
              >
                <img
                  v-if="selectedImage?.url"
                  :src="selectedImage.url"
                  :alt="coin.theme ?? coin.eurio_id"
                  class="h-full w-full object-contain p-6"
                />
                <ImageOff v-else class="h-12 w-12" style="color: var(--ink-300);" />
                <span
                  class="absolute left-4 top-4 rounded-full px-3 py-1 text-[10px] font-mono font-medium uppercase"
                  style="background: rgba(14,14,31,0.85); color: white; letter-spacing: var(--tracking-eyebrow); backdrop-filter: blur(4px);"
                >
                  Cette pièce
                </span>
                <span
                  class="absolute bottom-4 left-4 rounded-full px-3 py-1 text-[10px] font-mono uppercase"
                  style="background: rgba(14,14,31,0.85); color: rgba(255,255,255,0.85); backdrop-filter: blur(4px);"
                >
                  {{ coin.country }} · {{ coin.year }}
                </span>
              </div>

              <!-- Nearest neighbor (right) -->
              <button
                class="group relative flex aspect-square items-center justify-center overflow-hidden transition-all hover:brightness-95 md:border-l"
                :style="{
                  background: 'linear-gradient(200deg, var(--surface-1), var(--surface-2))',
                  borderColor: 'var(--surface-3)',
                }"
                @click="goToConfusionCoin(confusionNearest.eurio_id)"
              >
                <img
                  v-if="confusionNearest.coin?.image_url"
                  :src="confusionNearest.coin.image_url"
                  :alt="confusionNearest.coin.theme ?? confusionNearest.eurio_id"
                  class="h-full w-full object-contain p-6 transition-transform duration-300 group-hover:scale-105"
                  loading="lazy"
                />
                <ImageOff v-else class="h-12 w-12" style="color: var(--ink-300);" />
                <span
                  class="absolute left-4 top-4 rounded-full px-3 py-1 text-[10px] font-mono font-medium uppercase"
                  :style="{
                    background: zoneStyle(confusion.zone).solid,
                    color: 'white',
                    letterSpacing: 'var(--tracking-eyebrow)',
                  }"
                >
                  Voisin
                </span>
                <span
                  v-if="confusionNearest.coin"
                  class="absolute bottom-4 left-4 rounded-full px-3 py-1 text-[10px] font-mono uppercase"
                  style="background: rgba(14,14,31,0.85); color: rgba(255,255,255,0.85); backdrop-filter: blur(4px);"
                >
                  {{ confusionNearest.coin.country }}{{ confusionNearest.coin.year ? ` · ${confusionNearest.coin.year}` : '' }}
                </span>
                <span
                  class="absolute right-4 top-4 flex items-center gap-1 rounded-full px-3 py-1 text-[10px] font-medium uppercase opacity-0 transition-opacity group-hover:opacity-100"
                  style="background: rgba(14,14,31,0.85); color: white; backdrop-filter: blur(4px); letter-spacing: var(--tracking-eyebrow);"
                >
                  Ouvrir
                  <ArrowUpRight class="h-3 w-3" />
                </span>
              </button>
            </div>

            <!-- Footer bar with meta + similarity -->
            <div
              class="flex items-center justify-between gap-4 border-t px-5 py-4"
              style="border-color: var(--surface-3); background: var(--surface-1);"
            >
              <button
                class="min-w-0 flex-1 text-left transition-opacity hover:opacity-80"
                @click="goToConfusionCoin(confusionNearest.eurio_id)"
              >
                <p class="truncate font-display italic text-lg font-semibold"
                   style="color: var(--ink);">
                  {{ confusionNearest.coin?.theme ?? confusionNearest.eurio_id }}
                </p>
                <p class="truncate font-mono text-[11px]" style="color: var(--ink-400);">
                  {{ confusionNearest.eurio_id }}
                </p>
              </button>
              <div class="flex flex-col items-end flex-shrink-0">
                <span
                  class="font-mono text-3xl font-semibold tabular-nums leading-none"
                  :style="{ color: zoneStyle(confusion.zone).solid }"
                >
                  {{ confusionNearest.similarity.toFixed(3) }}
                </span>
                <span
                  class="mt-1 font-mono text-[10px] uppercase"
                  style="color: var(--ink-400); letter-spacing: var(--tracking-eyebrow);"
                >
                  cosine similarity
                </span>
              </div>
            </div>
          </div>
        </div>

        <!-- Other neighbors — larger grid (4 columns on desktop) -->
        <div v-if="confusionOtherNeighbors.length > 0" class="mt-8">
          <p class="mb-3 text-[10px] uppercase"
             style="color: var(--ink-500); letter-spacing: var(--tracking-eyebrow);">
            Autres voisins proches
          </p>
          <div class="grid grid-cols-2 gap-4 md:grid-cols-4">
            <button
              v-for="n in confusionOtherNeighbors"
              :key="n.eurio_id"
              class="group flex flex-col overflow-hidden rounded-lg border text-left transition-all hover:-translate-y-0.5"
              style="border-color: var(--surface-3); background: var(--surface); box-shadow: var(--shadow-sm);"
              @click="goToConfusionCoin(n.eurio_id)"
            >
              <div
                class="relative flex aspect-square items-center justify-center overflow-hidden"
                style="background: linear-gradient(160deg, var(--surface-1), var(--surface-2));"
              >
                <img
                  v-if="n.coin?.image_url"
                  :src="n.coin.image_url"
                  :alt="n.coin.theme ?? n.eurio_id"
                  class="h-full w-full object-contain p-4 transition-transform duration-300 group-hover:scale-105"
                  loading="lazy"
                />
                <ImageOff v-else class="h-8 w-8" style="color: var(--ink-300);" />
                <span
                  class="absolute right-2 top-2 rounded-full px-2 py-0.5 font-mono text-xs font-semibold tabular-nums"
                  :style="{
                    background: 'rgba(14,14,31,0.85)',
                    color: 'white',
                    backdropFilter: 'blur(4px)',
                  }"
                >
                  {{ n.similarity.toFixed(3) }}
                </span>
              </div>
              <div class="flex flex-1 flex-col justify-between p-3">
                <p class="line-clamp-2 text-sm font-medium leading-snug" style="color: var(--ink);">
                  {{ n.coin?.theme ?? n.eurio_id }}
                </p>
                <div class="mt-2 flex items-center justify-between">
                  <span v-if="n.coin" class="font-mono text-[10px] uppercase" style="color: var(--ink-400);">
                    {{ n.coin.country }}{{ n.coin.year ? ` · ${n.coin.year}` : '' }}
                  </span>
                  <span
                    class="h-1.5 w-1.5 rounded-full"
                    :style="{ background: n.similarity >= 0.85 ? 'var(--danger)' : n.similarity >= 0.70 ? 'var(--warning)' : 'var(--success)' }"
                  />
                </div>
              </div>
            </button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.copy-toast-enter-active,
.copy-toast-leave-active {
  transition: transform 0.18s ease, opacity 0.18s ease;
}
.copy-toast-enter-from,
.copy-toast-leave-to {
  transform: translate(-50%, 16px);
  opacity: 0;
}
</style>
