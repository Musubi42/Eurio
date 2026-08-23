<script setup lang="ts">
// Vue Single du flow review (extraite de ReviewPage.vue lors du
// refacto Phase 2 R.0 — 2026-05-04). Contient la logique historique
// inchangée : queue + item courant + action bar + toast undo + help
// overlay + sélecteur libre. Le shell ReviewPage gère le toggle
// Single | Lot et le titre.

import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AlertTriangle, Keyboard, Search, Sparkles, Undo2, Wand2 } from 'lucide-vue-next'
import {
  autoCropReview,
  correctListing,
  decideReviewItem,
  fetchMarketQuotes,
  fetchReviewQueue,
  fetchReviewStats,
  moveReviewLaneToManual,
  rankCandidates,
  rejectReviewItem,
  requalifyReviewAsLot,
  skipReviewItem,
  type AutoCropResult,
  type ConditionTier,
  type ListingKind,
  type MarketQuote,
  type ReviewCandidate,
  type ReviewDecision,
  type ReviewFace,
  type ReviewItem,
  type ReviewStats,
} from '../composables/useReviewApi'
import { useReviewKeybinds } from '../composables/useReviewKeybinds'
import { queryNeedOnly, queryParam, queryRunIds } from '../composables/useQueryScope'
import type { CoinSearchEntry } from '../composables/useCoinsSearch'
import SplitCompare from '../components/SplitCompare.vue'
import CircleCropEditor from '../components/CircleCropEditor.vue'
import ReviewActionBar from '../components/ReviewActionBar.vue'
import { Boxes, Crop } from 'lucide-vue-next'
import DinoVerdict from '../components/DinoVerdict.vue'
import AutoValidateVerdict from '../components/AutoValidateVerdict.vue'
import ReviewRightColumn from '../components/ReviewRightColumn.vue'
import ListingContextCard from '../components/ListingContextCard.vue'
import TextSignals from '../components/TextSignals.vue'
import { useHeavyGate } from '@/shared/composables/useHeavyGate'
import { withCacheBust } from '@/shared/url'

// Ordre de cycle des corrections clavier (K / C).
const KIND_CYCLE: ListingKind[] = ['single', 'lot', 'coffret', 'graded_slab']
const CONDITION_CYCLE: ConditionTier[] = ['UNC', 'TTB', 'TB']
import type { DinoSuggestion } from '../composables/useDinoSuggestions'

// ─── Les DEUX axes de gating ────────────────────────────────────────────
//
// Ils répondent à des questions différentes et ne doivent jamais être
// confondus (review-collaborative-v2, lots 4 et 5) :
//
//   `canArbitrate`   — DROIT   : « cette personne a-t-elle le droit ? »
//                      Masque les gestes qui structurent le travail des autres.
//   `canRunHeavy`    — MACHINE : « ce poste peut-il ? »
//                      Gate les gestes qui encodent des pixels (cv2 sur :8042),
//                      indisponibles en hébergé jusqu'au lot 6b. Rendu par public
//                      (D11) : GRISÉ pour l'arbitre, ABSENT pour un ami —
//                      `showHeavyGesture`.
//
// Un ami sur son navigateur tombe sous les DEUX : il ne requalifie pas (droit)
// et ne recadre pas encore (machine). Les mélanger reviendrait à rendre un
// geste de recadrage « interdit » alors qu'il est seulement hors de portée —
// et il redeviendra possible pour lui au lot 6b, sans changer ses droits.

// D11 : `showHeavyGesture` porte la question « faut-il DESSINER ce geste lourd ? »
// — grisé pour l'arbitre, absent pour un ami. La règle vit dans `useHeavyGate`.
const { canArbitrate, canRunHeavy, showHeavyGesture } = useHeavyGate()

// ─── State ──────────────────────────────────────────────────────────────

const queue = ref<ReviewItem[]>([])
const currentIndex = ref(0)
// La file n'a pas pu être lue. Un état À PART de « vide » : une file vide veut
// dire « il n'y a plus rien à trancher », une file en erreur veut dire « on ne
// sait pas ». Les confondre, c'est ce que faisait le repli sur des données
// fictives — et l'écran servait alors des pièces slovènes inventées dans une
// classe espagnole, sans un mot.
const loadError = ref<string | null>(null)
// Pagination « infinie » : la queue se recharge à l'approche de la fin du batch
// local (cf. loadMore). `drained` = le backend n'a plus rien de nouveau pour ce
// scope (vrai écran vide). `loadingMore` garde-fou anti-concurrence.
const loadingMore = ref(false)
const drained = ref(false)
// Re-fetch déclenché quand le curseur arrive à PREFETCH_AHEAD items de la fin :
// le reviewer ne voit jamais « vide » alors qu'il reste des items côté serveur.
const PREFETCH_AHEAD = 5
const focusedCandidateIdx = ref<number | null>(null)
const freeSearchCandidate = ref<ReviewCandidate | null>(null)
const face = ref<ReviewFace>('obverse')
const stats = ref<ReviewStats | null>(null)
const showHelp = ref(false)
// Éditeur de re-crop manuel (overlay) + jeton de cache-bust pour rafraîchir
// le crop affiché après écrasement côté backend.
const showCropEditor = ref(false)
const cropBust = ref(0)
// Auto-crop score-guidé (touche A) : état pendant le calcul + dernier résultat
// (score baseline → best) affiché sur le bouton. Reset à chaque item.
const autoCropBusy = ref(false)
const autoCropResult = ref<AutoCropResult | null>(null)
// Mode de la colonne droite : 'auto' = Top N + DinoSuggestions ;
// 'free' = FreeSelectorPanel inline (cascade pays/dénom/année).
// Reset à 'auto' à chaque changement d'item.
const mode = ref<'auto' | 'free'>('auto')
// ─── Commit différé (modèle « undo Send ») ──────────────────────────────
// Une action (validate / reject / skip) n'est PAS POSTée immédiatement :
// elle devient une décision « en attente » et n'est commitée qu'après
// COMMIT_WINDOW_MS. Pendant la fenêtre, « Annuler » la supprime sans
// qu'aucune écriture serveur n'ait eu lieu — donc plus de re-décision
// d'un item déjà `done` (cf. bug 409). Au plus une décision en attente :
// une nouvelle action flush la précédente avant de s'armer.
const COMMIT_WINDOW_MS = 10_000

type PendingKind = 'decide' | 'reject' | 'skip'

interface PendingCommit {
  kind: PendingKind
  reviewId: string
  /** Index de l'item dans `queue` — sert au rewind exact de l'undo. */
  itemIndex: number
  /** Payload de décision (kind='decide' uniquement). */
  payload?: ReviewDecision
}

const PENDING_LABEL: Record<PendingKind, string> = {
  decide: 'Pièce validée',
  reject: 'Image rejetée',
  skip: 'Review reportée',
}

const pendingCommit = ref<PendingCommit | null>(null)
let commitTimer: ReturnType<typeof setTimeout> | null = null
// Bumpé à chaque action — sert de `key` au toast pour relancer son
// animation de compte à rebours même sur deux actions consécutives.
const toastNonce = ref(0)

// Bandeau d'alerte qui descend du haut de l'écran — feedback quand on
// presse ⏎ alors que la validation est bloquée.
const topNotice = ref<string | null>(null)
let topNoticeTimer: ReturnType<typeof setTimeout> | null = null

// Correction opt-in du contexte listing (C4). `null` = on garde la
// valeur heuristique C2 ; sinon = valeur corrigée à la main. Reset à
// chaque item. Flushé vers l'API au passage à l'item suivant.
const correctedKind = ref<ListingKind | null>(null)
const correctedCondition = ref<ConditionTier | null>(null)
// Quotes marché des candidats de l'item courant (clé = eurio_id).
const marketQuotes = ref<Record<string, MarketQuote[]>>({})

// ─── Derived ────────────────────────────────────────────────────────────

const currentItem = computed<ReviewItem | null>(
  () => queue.value[currentIndex.value] ?? null,
)

// URL du crop avec cache-bust : après un re-crop manuel, le fichier est écrasé
// au même chemin → sans ça le navigateur ressert l'ancienne image et l'écran ment.
// `withCacheBust` choisit le bon séparateur : les crops sont des URLs MinIO
// présignées, qui portent DÉJÀ une query string (cf. son en-tête).
const currentCropUrl = computed<string>(() =>
  withCacheBust(currentItem.value?.crop_url, cropBust.value),
)

const focusedCandidate = computed<ReviewCandidate | null>(() => {
  if (freeSearchCandidate.value) return freeSearchCandidate.value
  if (focusedCandidateIdx.value === null || !currentItem.value) return null
  return currentItem.value.candidates[focusedCandidateIdx.value] ?? null
})

const isQueueEmpty = computed(() => currentIndex.value >= queue.value.length)

// Valeurs affichées sur la carte listing : correction manuelle si elle
// existe, sinon l'heuristique C2.
const effectiveKind = computed<ListingKind | null>(
  () => correctedKind.value ?? currentItem.value?.listing_kind ?? null,
)
const effectiveCondition = computed<ConditionTier | null>(
  () => correctedCondition.value ?? currentItem.value?.condition ?? null,
)

// Quote marché pour la pièce du candidat focusé + l'état courant du
// listing — alimente le cross-check prix de la carte.
const focusedMarketQuote = computed<MarketQuote | null>(() => {
  const eid = focusedCandidate.value?.eurio_id
  const cond = effectiveCondition.value
  if (!eid || !cond) return null
  return (marketQuotes.value[eid] ?? []).find((q) => q.condition === cond) ?? null
})

// Optional cohort scope, driven by the `?cohort=<id>` query (set in ReviewPage).
const route = useRoute()
const cohortId = computed(() => queryParam(route, 'cohort'))
// ── PÊCHE (?dino_class=) — le périmètre par PRÉDICTION ─────────────────────
// Il remplace celui par cible côté API : « ce que la banque reconnaît » au lieu
// de « ce que le scrape visait ». C'est ce qui rend atteignables les crops
// qu'aucun scrape ne visait — sur l'italienne standard, 57 items dont 2 utiles
// deviennent 137 tous utiles.
const dinoClass = computed(() => queryParam(route, 'dino_class'))
const dinoRank = computed<number | null>(() => {
  const raw = queryParam(route, 'dino_rank')
  if (!raw) return null
  const n = Number.parseInt(raw, 10)
  // Trois paliers, pas un curseur : un rang inconnu ferait répondre 422 à
  // l'API. On retombe sur le plus strict plutôt que d'élargir sans le dire.
  return [1, 3, 5].includes(n) ? n : 1
})
// IDS explicites (?ids=a,b,c) : review déclenchée depuis la galerie enrichment
// d'une page coin (reflag → ces rows review_queue EXACTES). Prioritaire absolu
// sur eurio_id/cohort — robuste aux crops rescués. Vide → ignoré.

// WS1 : lane persistée à reviewer (manual/auto_accept). SingleReviewView
// EST l'écran manuel (auto_accept a sa page dédiée) → il filtre sur sa lane,
// donc le compteur de la lane décroît à chaque décision.
//
// Défaut = 'manual'. Sans ce défaut, /review/manual (lien dashboard, sans param)
// servait lane=null → toutes lanes par priorité → des items d'autres lanes
// (priorité plus haute) passaient devant et le reviewer tranchait hors-manuel en
// croyant faire du manuel : la carte « Queue manuelle » (n_pending − handled) restait alors
// mathématiquement figée (toute décision non-manuelle décrémente n_pending ET
// handled à parts égales). Bug PO 2026-06-15.
//
// EXCEPTION ?ids= (galerie enrichment) : sert des rows EXACTES toutes lanes
// confondues (crops rescués, target ≠ pièce assignée) → pas de filtre lane.
const lane = computed<string | null>(() => {
  const q = queryParam(route, 'lane')
  if (q && ['manual', 'auto_accept'].includes(q)) return q
  if (queryParam(route, 'ids')) return null
  // PÊCHE : le périmètre est la prédiction, pas la lane. Un crop rangé en
  // auto_accept est le même crop ; le laisser hors de la file rendrait le
  // compteur du bandeau faux et cacherait du stock sans le dire.
  if (dinoClass.value) return null
  // RUN (?run=) : même raison — le périmètre est le run, pas la lane. 202 des
  // 777 items du reprocess du 2026-08-21 étaient rangés en auto_accept ; les
  // cacher rendrait le compteur « n / 777 » faux sans le dire.
  if (runIds.value && runIds.value.length) return null
  return 'manual'
})
// Scope PAR PIÈCE (?eurio_id=) : review déclenchée depuis une row coin du
// cockpit. Ne sert QUE les crops de cette pièce → trancher fait bouger SA ligne
// (corrige « Reviewer N » qui servait toute la cohorte). Prioritaire backend.
const eurioId = computed(() => queryParam(route, 'eurio_id'))

const reviewIds = computed<string[] | null>(() => {
  const raw = queryParam(route, 'ids')
  if (!raw) return null
  const ids = raw.split(',').filter(Boolean)
  return ids.length ? ids : null
})

// ── Tri par ce que DINO reconnaît (?tri=dino) ───────────────────────────────
// Lu dans l'URL comme tout le reste du périmètre, pour que la page cohorte
// puisse le poser sans prop et que le rechargement le conserve.
const order = computed<'priority' | 'dino'>(
  () => (queryParam(route, 'tri') === 'dino' ? 'dino' : 'priority'),
)
const dinoMinSpread = computed<number | null>(() => {
  const raw = queryParam(route, 'dino_min')
  if (!raw) return null
  const n = Number.parseFloat(raw)
  return Number.isFinite(n) ? n : null
})
const dinoTop1Only = computed(() => queryParam(route, 'dino_top1') === '1')
// ── Périmètre PAR RUN SOURCE (?run=a,b) ─────────────────────────────────────
// Les crops créés par ces runs, et eux seuls. S'AJOUTE à tout le reste (lane,
// cible, pêche, tri) : c'est la même file, restreinte. Le compteur du bandeau
// (ReviewPage) lit le même param — cf. queryRunIds.
const runIds = computed(() => queryRunIds(route))
// ── Périmètre PAR BESOIN (?need=1) ──────────────────────────────────────────
// Les crops dont le top-1 DINO tombe dans une classe encore en besoin, et eux
// seuls : les classes pleines sont parquées, pas servies (D2/D3). Un ET.
const needOnly = computed(() => queryNeedOnly(route))

// L'hôte (ReviewPage) rafraîchit le compteur d'avancement par run après chaque
// décision ÉCRITE — émis une fois le POST revenu, jamais avant.
const emit = defineEmits<{ (e: 'decided'): void }>()

// Valider exige un candidat ET un type/état renseignés : on ne fige pas
// une attribution sans avoir tranché le contexte listing (C4).
// EXCEPTION (C4c) — en contexte cohort, la review est centrée « bonne pièce ? » :
// le contexte listing (prix/type/état, orienté référentiel marché) est masqué,
// donc valider n'exige qu'un candidat focusé.
const canValidate = computed(() => {
  if (!focusedCandidate.value) return false
  if (cohortId.value) return true
  return effectiveKind.value !== null && effectiveCondition.value !== null
})
const validateBlockedReason = computed<string | null>(() => {
  if (!focusedCandidate.value) {
    return 'Sélectionne un candidat (1-5) ou le sélecteur libre (F)'
  }
  if (!cohortId.value && (effectiveKind.value === null || effectiveCondition.value === null)) {
    return 'Renseigne le type (K) et l’état (C) du listing'
  }
  return null
})

// ─── Loaders ────────────────────────────────────────────────────────────

async function load() {
  loadError.value = null
  try {
    await loadInner()
  } catch (err) {
    // On VIDE la file : garder à l'écran un item d'un chargement précédent
    // ferait trancher sur un périmètre qui n'est plus celui affiché.
    queue.value = []
    drained.value = false
    loadError.value = err instanceof Error ? err.message : String(err)
  }
}

async function loadInner() {
  const [q, s] = await Promise.all([
    fetchReviewQueue({
      limit: 30,
      cohortId: cohortId.value,
      lane: lane.value,
      eurioId: eurioId.value,
      reviewIds: reviewIds.value,
      order: order.value,
      dinoMinSpread: dinoMinSpread.value,
      dinoTop1Only: dinoTop1Only.value,
      dinoClass: dinoClass.value,
      dinoRank: dinoRank.value,
      runIds: runIds.value,
      needOnly: needOnly.value,
    }),
    fetchReviewStats(),
  ])
  queue.value = q
  stats.value = s
  currentIndex.value = 0
  drained.value = q.length === 0
  loadingMore.value = false
  resetForCurrent()
}

// Charge le batch suivant et l'APPEND à la queue locale (pagination continue).
// Dédup obligatoire : le backend re-sert les items encore `open`, donc (a) les
// items non encore décidés qu'on tient déjà en file, et (b) la décision en
// attente (commit différé, status reste 'open' tant que sa fenêtre d'undo n'a
// pas flush). On exclut les deux pour ne jamais empiler de doublon.
async function loadMore() {
  if (loadingMore.value || drained.value || loadError.value) return
  loadingMore.value = true
  try {
    const more = await fetchReviewQueue({
      limit: 30,
      cohortId: cohortId.value,
      lane: lane.value,
      eurioId: eurioId.value,
      reviewIds: reviewIds.value,
      order: order.value,
      dinoMinSpread: dinoMinSpread.value,
      dinoTop1Only: dinoTop1Only.value,
      dinoClass: dinoClass.value,
      dinoRank: dinoRank.value,
      runIds: runIds.value,
      needOnly: needOnly.value,
    })
    const known = new Set(queue.value.map((r) => r.id))
    if (pendingCommit.value) known.add(pendingCommit.value.reviewId)
    const fresh = more.filter((r) => !known.has(r.id))
    if (fresh.length === 0) {
      drained.value = true
    } else {
      queue.value = [...queue.value, ...fresh]
    }
  } catch (err) {
    // Une pagination qui échoue ne doit pas se lire « plus rien à trancher ».
    loadError.value = err instanceof Error ? err.message : String(err)
  } finally {
    loadingMore.value = false
  }
}

function resetForCurrent() {
  freeSearchCandidate.value = null
  mode.value = 'auto'
  correctedKind.value = null
  correctedCondition.value = null
  cropBust.value = 0
  showCropEditor.value = false
  autoCropResult.value = null
  void loadMarketQuotes()
  // Pré-sélection : la pièce proposée (target_candidate, theme-match) bat
  // le top-1 auto-name. ~80 % des reviews valident la proposition —
  // pré-sélectionner évite un clic dans la majorité des cas.
  const target = currentItem.value?.target_candidate ?? null
  if (target) {
    freeSearchCandidate.value = target
    focusedCandidateIdx.value = null
  } else {
    const top1 = currentItem.value?.candidates[0]
    focusedCandidateIdx.value = top1 && top1.score >= 0.5 ? 0 : null
    // Pas de proposition theme-match, mais un ENSEMBLE de candidats connus
    // (pièces du groupe pays+année, ou designs standard du pays) : Dino sait
    // les départager même quand le top-K open-vocab abstient (la bonne réponse
    // est enterrée sous des pays voisins). On classe en ensemble fermé et on
    // pré-focus le gagnant. Async → garde-fou anti-race dans le helper.
    void autoRankGroupCandidates()
  }
  face.value = currentItem.value?.face_detected ?? 'obverse'
}

/** Départage Dino des candidats de groupe/standard quand aucune proposition
 *  theme-match n'existe. Pré-focus le gagnant (sim la plus haute). No-op s'il
 *  n'y a pas d'ensemble de candidats, ou si l'utilisateur a déjà choisi /
 *  changé d'item pendant le calcul. */
async function autoRankGroupCandidates() {
  const item = currentItem.value
  if (!item) return
  const pool = [...(item.group_candidates ?? []), ...(item.standard_candidates ?? [])]
  if (pool.length === 0) return
  const eurioIds = [...new Set(pool.map((c) => c.eurio_id))]
  const result = await rankCandidates(item.id, eurioIds)
  // Garde-fou : l'utilisateur a pu avancer d'item ou choisir une pièce pendant
  // l'encodage Dino → ne rien écraser dans ces cas.
  if (!result?.ranked.length) return
  if (currentItem.value?.id !== item.id) return
  if (freeSearchCandidate.value || focusedCandidateIdx.value !== null) return
  const winnerId = result.ranked[0].eurio_id
  const winner = pool.find((c) => c.eurio_id === winnerId)
  if (!winner) return
  freeSearchCandidate.value = winner
  focusedCandidateIdx.value = null
  const top = result.ranked[0]
  const runner = result.ranked[1]
  const pct = (s: number) => `${(s * 100).toFixed(0)}%`
  flashTopNotice(
    runner
      ? `Dino : ${winner.label} (${pct(top.sim)}) pré-sélectionné · ${pct(runner.sim)} pour le 2ᵉ`
      : `Dino : ${winner.label} (${pct(top.sim)}) pré-sélectionné`,
  )
}

function selectTarget() {
  const target = currentItem.value?.target_candidate ?? null
  if (!target) return
  freeSearchCandidate.value = target
  focusedCandidateIdx.value = null
}

// Commit garanti même si l'onglet se ferme pendant la fenêtre d'undo :
// `keepalive` laisse le POST se terminer après l'unload.
function flushBeforeUnload() {
  flushPending({ keepalive: true })
}

onMounted(() => {
  void load()
  window.addEventListener('beforeunload', flushBeforeUnload)
})

// Reload the queue when the cohort scope, the lane, the per-coin scope, or the
// explicit id list changes.
// Le tri fait partie du périmètre : l'oublier ici donnerait un premier écran
// trié puis une pagination qui ne l'est plus — panne muette parfaite.
watch([cohortId, lane, eurioId, reviewIds, order, dinoMinSpread, dinoTop1Only,
       dinoClass, dinoRank, () => runIds.value?.join(',') ?? null, needOnly], () => {
  void load()
})

// Pagination continue : dès que le curseur approche la fin du batch local,
// précharge la suite. Couvre aussi le dépassement (curseur ≥ longueur) si le
// reviewer va plus vite que le fetch. La garde loadingMore/drained évite les
// appels redondants.
watch(currentIndex, (idx) => {
  if (idx >= queue.value.length - PREFETCH_AHEAD) void loadMore()
})

// Démontage = changement de route OU bascule Single→Lot (v-if dans
// ReviewPage) : on flush la décision en attente plutôt que la perdre.
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', flushBeforeUnload)
  flushPending()
})

// ─── Actions ────────────────────────────────────────────────────────────

function focusCandidate(idx: number) {
  if (!currentItem.value) return
  if (idx < 0 || idx >= currentItem.value.candidates.length) return
  focusedCandidateIdx.value = idx
  freeSearchCandidate.value = null
}

function setFace(f: ReviewFace) {
  face.value = f
}

function advance() {
  flushCorrection()
  currentIndex.value += 1
  resetForCurrent()
}

/** Charge les quotes marché des candidats de l'item courant. */
async function loadMarketQuotes() {
  marketQuotes.value = {}
  // En contexte cohort, la carte listing (et son cross-check prix) est masquée
  // (C4c) → inutile de charger les quotes marché.
  if (cohortId.value) return
  const item = currentItem.value
  if (!item) return
  const ids = new Set<string>()
  if (item.target_candidate) ids.add(item.target_candidate.eurio_id)
  item.candidates.forEach((c) => ids.add(c.eurio_id))
  ;(item.group_candidates ?? []).forEach((c) => ids.add(c.eurio_id))
  if (ids.size === 0) return
  marketQuotes.value = await fetchMarketQuotes([...ids])
}

/** POST la correction listing si l'utilisateur a touché K / C. */
function flushCorrection() {
  const item = currentItem.value
  if (!item) return
  if (correctedKind.value === null && correctedCondition.value === null) return
  // Fire-and-forget : une correction d'audit ne bloque pas le flow.
  void correctListing(item.id, {
    listing_kind: correctedKind.value ?? undefined,
    condition: correctedCondition.value ?? undefined,
  })
}

function cycleKind() {
  if (!currentItem.value) return
  // Première frappe sur un listing sans type (—) → 1ʳᵉ valeur, pas le
  // cran suivant. Ensuite, cycle normal.
  const cur = effectiveKind.value
  correctedKind.value = cur === null
    ? KIND_CYCLE[0]
    : KIND_CYCLE[(KIND_CYCLE.indexOf(cur) + 1) % KIND_CYCLE.length]
}

function cycleCondition() {
  if (!currentItem.value) return
  const cur = effectiveCondition.value
  correctedCondition.value = cur === null
    ? CONDITION_CYCLE[0]
    : CONDITION_CYCLE[(CONDITION_CYCLE.indexOf(cur) + 1) % CONDITION_CYCLE.length]
}

function flashTopNotice(message: string) {
  if (topNoticeTimer) clearTimeout(topNoticeTimer)
  topNotice.value = message
  topNoticeTimer = setTimeout(() => {
    topNotice.value = null
  }, 2800)
}

function validateCurrent() {
  if (!currentItem.value) return
  if (!canValidate.value) {
    // ⏎ pressé mais validation bloquée → feedback visible.
    flashTopNotice(validateBlockedReason.value ?? 'Validation bloquée')
    return
  }
  if (!focusedCandidate.value) return  // garanti par canValidate — narrowing TS
  scheduleCommit('decide', currentItem.value.id, {
    eurio_id: focusedCandidate.value.eurio_id,
    face: face.value,
  })
  advance()
}

// Chunk Cr — accepter la suggestion DINOv2 top-1 en 1 clic.
// Face hardcodée à 'obverse' : les ancres Dino sont des obverses
// canoniques Numista — correct par construction pour les 2€ commémo.
// No-op si pas de suggestion Dino sur l'item courant.
function acceptDino() {
  const item = currentItem.value
  if (!item?.dino_top1) return
  scheduleCommit('decide', item.id, {
    eurio_id: item.dino_top1.eurio_id,
    face: 'obverse',
  })
  advance()
}

function rejectCurrent() {
  if (!currentItem.value) return
  scheduleCommit('reject', currentItem.value.id)
  advance()
}

function skipCurrent() {
  if (!currentItem.value) return
  scheduleCommit('skip', currentItem.value.id)
  advance()
}

// « Requalifier en lot » (L) — le crop était en review single mais l'annonce
// est en réalité un lot. On bascule TOUT le listing en kind='lot' (écriture
// immédiate, pas une décision) : les crops quittent la queue single → flow lot.
// On RELOAD (pas un simple advance) car les crops frères du listing basculent
// aussi et doivent disparaître de la queue locale.
async function requalifyCurrentAsLot() {
  const item = currentItem.value
  if (!item) return
  flushPending()
  try {
    const res = await requalifyReviewAsLot(item.id)
    flashTopNotice(
      res.n_requalified > 1
        ? `Listing requalifié en lot — ${res.n_requalified} crops basculés vers le flow lot`
        : 'Crop requalifié en lot',
    )
  } catch (err) {
    flashTopNotice(`Échec de la requalification : ${err instanceof Error ? err.message : String(err)}`)
    return
  }
  await load()
}

// WS1 : « Faire en manuel » — sort l'item de la lane courante (auto_accept /
// ccproxy) vers la lane manuelle (sticky). Écriture immédiate (pas de fenêtre
// d'undo : c'est un déplacement, pas une décision) puis on avance.
async function moveCurrentToManual() {
  const item = currentItem.value
  if (!item) return
  flushPending()
  try {
    await moveReviewLaneToManual(item.id)
  } catch (err) {
    flashTopNotice(`Échec du déplacement : ${err instanceof Error ? err.message : String(err)}`)
    return
  }
  advance()
}

// ─── Commit différé : scheduling / flush / undo ─────────────────────────

/** POST réel d'une décision. Tout échec est surfacé via le bandeau —
 *  jamais d'exception non catchée (cf. bug 409 décrit en aparté). */
async function commitPending(p: PendingCommit, opts: { keepalive?: boolean } = {}) {
  try {
    if (p.kind === 'decide' && p.payload) {
      await decideReviewItem(p.reviewId, p.payload, opts)
    } else if (p.kind === 'reject') {
      await rejectReviewItem(p.reviewId, opts)
    } else if (p.kind === 'skip') {
      await skipReviewItem(p.reviewId, opts)
    }
    emit('decided')
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    flashTopNotice(`Échec de l'enregistrement : ${msg}`)
  }
}

/** Commit immédiat de la décision en attente (timer écoulé, nouvelle
 *  action, démontage de la vue). Idempotent : sans pending, no-op. */
function flushPending(opts: { keepalive?: boolean } = {}) {
  if (!pendingCommit.value) return
  if (commitTimer) { clearTimeout(commitTimer); commitTimer = null }
  const p = pendingCommit.value
  pendingCommit.value = null
  void commitPending(p, opts)
}

/** Diffère une action : flush la précédente, arme le timer de commit. */
function scheduleCommit(kind: PendingKind, reviewId: string, payload?: ReviewDecision) {
  flushPending()
  pendingCommit.value = { kind, reviewId, itemIndex: currentIndex.value, payload }
  toastNonce.value++
  commitTimer = setTimeout(() => {
    commitTimer = null
    const p = pendingCommit.value
    pendingCommit.value = null
    if (p) void commitPending(p)
  }, COMMIT_WINDOW_MS)
}

/** Annule la décision en attente — aucune écriture n'a eu lieu, on
 *  rembobine simplement le curseur sur l'item concerné. */
function undoLast() {
  const p = pendingCommit.value
  if (!p) return
  if (commitTimer) { clearTimeout(commitTimer); commitTimer = null }
  pendingCommit.value = null
  currentIndex.value = p.itemIndex
  resetForCurrent()
}

// Auto-accept déterministe : navigation vers la page dédiée qui charge
// la preview enrichie (crops + canonicals) et permet la sélection
// granulaire avant écriture. Pas de confirm() natif — on ne valide pas
// 100+ items à l'aveugle.
const router = useRouter()
function onClickAutoAccept() {
  void router.push('/review/auto-accept')
}

function toggleMode() {
  mode.value = mode.value === 'auto' ? 'free' : 'auto'
}

function closeSearchOverlay() {
  if (showHelp.value) {
    showHelp.value = false
    return
  }
  if (mode.value === 'free') {
    mode.value = 'auto'
  }
}

function onSearchSelect(entry: CoinSearchEntry) {
  freeSearchCandidate.value = {
    eurio_id: entry.eurio_id,
    score: 1.0,
    label: entry.label,
    country: entry.country,
    denomination: entry.denomination,
    year: entry.year,
    canonical_thumb_url: entry.canonical_thumb_url ?? '',
  }
  focusedCandidateIdx.value = null
  // Une pièce a été pickée → repasse en mode auto pour montrer le banner
  // freeSearchCandidate + permettre la validation immédiate (⏎).
  mode.value = 'auto'
}

function onGroupSelect(c: ReviewCandidate) {
  // Pièce du groupe pickée (listing ambigu, pas de proposition) — même
  // voie que la sélection libre : devient le candidat focusé, validable
  // immédiatement (⏎).
  freeSearchCandidate.value = c
  focusedCandidateIdx.value = null
}

function onStandardSelect(c: ReviewCandidate) {
  // Design group standard pické (crop de scrape standard) — même voie que
  // la sélection libre : devient le candidat focusé, validable d'un ⏎.
  // c.eurio_id = membre représentant du groupe → la décision écrit ce
  // membre, dont la classe d'entraînement = COALESCE(design_group_id) = le
  // groupe (ex. es-1999 → es-2euro-juan-carlos-i-t1).
  freeSearchCandidate.value = c
  focusedCandidateIdx.value = null
}

function onDinoSelect(s: DinoSuggestion) {
  // Convertit une suggestion Dino en pseudo-ReviewCandidate puis prend
  // la voie "free search" (même UX que le sélecteur libre F).
  freeSearchCandidate.value = {
    eurio_id: s.eurio_id,
    score: s.sim,
    label: [s.country_name, s.year, s.theme].filter(Boolean).join(' · '),
    country: s.country ?? '',
    denomination: s.denomination ? `${s.denomination} EUR` : '',
    year: s.year,
    canonical_thumb_url: s.obverse_url ?? '',
  }
  focusedCandidateIdx.value = null
}

// ─── Keyboard ───────────────────────────────────────────────────────────

const keyboardEnabled = computed(() => !showHelp.value && !showCropEditor.value)

// Bumpé après un re-crop manuel pour forcer DinoSuggestions à refetcher
// (le backend a recalculé Dino sur le nouveau crop dans la même requête).
const dinoReloadKey = ref(0)

// Re-crop manuel validé : le crop a été écrasé côté backend → on bust le
// cache pour réafficher la nouvelle version, et on relance les suggestions
// Dino (recalculées server-side sur le crop recadré).
function onCropSaved() {
  cropBust.value = Date.now()
  dinoReloadKey.value += 1
}

// Auto-crop score-guidé (A) : balaye le rayon autour de la bbox, score chaque
// candidat avec la probe, écrit le meilleur SEULEMENT s'il bat franchement
// l'actuel. À tenter AVANT le recadrage manuel (E). Le résultat (score baseline
// → best) reste affiché sur le bouton.
async function runAutoCrop() {
  const item = currentItem.value
  if (!item || autoCropBusy.value) return
  autoCropBusy.value = true
  autoCropResult.value = null
  const pct = (s: number | null) => (s === null ? '—' : `${Math.round(s * 100)}%`)
  try {
    const res = await autoCropReview(item.id)
    // Garde-fou : l'utilisateur a pu avancer d'item pendant le calcul.
    if (currentItem.value?.id !== item.id) return
    autoCropResult.value = res
    if (res.applied) {
      cropBust.value = Date.now()   // réaffiche le nouveau crop (overwrite serveur)
      dinoReloadKey.value += 1      // crop changé → suggestions Dino à recalculer
      flashTopNotice(
        `Auto-crop appliqué : ${pct(res.baseline_score)} → ${pct(res.best_score)} (×${res.ratio?.toFixed(2)})`,
      )
    } else if (res.reason === 'already_optimal') {
      flashTopNotice(
        `Crop déjà optimal (${pct(res.baseline_score)}) — recadre à la main (E) si besoin`,
      )
    } else {
      flashTopNotice('Auto-crop : aucun meilleur cadrage trouvé — recadre à la main (E)')
    }
  } catch (err) {
    flashTopNotice(`Échec auto-crop : ${err instanceof Error ? err.message : String(err)}`)
  } finally {
    autoCropBusy.value = false
  }
}

// Badge du bouton : « 62%→91% » si appliqué, sinon le score actuel.
const autoCropBadge = computed<string | null>(() => {
  const r = autoCropResult.value
  if (!r) return null
  const pct = (s: number | null) => (s === null ? '—' : `${Math.round(s * 100)}%`)
  if (r.applied) return `${pct(r.baseline_score)}→${pct(r.best_score)}`
  if (r.baseline_score !== null) return `${pct(r.baseline_score)} ✓`
  return null
})

useReviewKeybinds(keyboardEnabled, {
  onCandidateFocus: focusCandidate,
  onValidate: validateCurrent,
  onReject: rejectCurrent,
  onSkip: skipCurrent,
  onOpenSearch: toggleMode,
  onCloseOverlay: closeSearchOverlay,
  onSetFace: setFace,
  onCycleKind: cycleKind,
  onCycleCondition: cycleCondition,
  onAcceptDino: acceptDino,
  // Masquer un bouton ne désarme PAS son raccourci : sans ces gardes, `L`
  // requalifierait encore un listing entier pour un ami, et `E`/`A` partiraient
  // vers un `:8042` injoignable — l'erreur réseau nue que le gating visuel
  // était censé éviter.
  onRecrop: () => {
    if (canRunHeavy.value && currentItem.value) showCropEditor.value = true
  },
  onAutoCrop: () => { if (canRunHeavy.value) void runAutoCrop() },
  onRequalifyLot: () => { if (canArbitrate.value) void requalifyCurrentAsLot() },
})
</script>

<template>
  <div class="flex flex-1 flex-col overflow-hidden">
    <!-- ═══ Sub-header : stats + actions ═══ -->
    <div
      class="flex flex-wrap items-center justify-between gap-4 border-b px-8 py-2.5"
      style="border-color: var(--surface-3); background: var(--surface);"
    >
      <div
        v-if="stats"
        class="flex items-center gap-5 font-mono text-[11px] tabular-nums"
        style="color: var(--ink-500);"
      >
        <span>
          <span class="font-semibold" style="color: var(--indigo-700);">{{ stats.n_done_today }}</span>
          <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">today</span>
        </span>
        <span class="opacity-50">·</span>
        <span>
          <span class="font-semibold" style="color: var(--ink);">{{ stats.median_seconds_per_decision.toFixed(1) }}s</span>
          <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">median</span>
        </span>
        <span class="opacity-50">·</span>
        <span>
          <span class="font-semibold" style="color: var(--ink);">{{ stats.n_pending.toLocaleString('fr-FR') }}</span>
          <span class="ml-1 uppercase tracking-wider" style="color: var(--ink-400);">left</span>
        </span>
      </div>
      <div v-else />

      <div class="flex items-center gap-2">
        <!-- Écriture en masse sur la file : réservé à l'arbitre (lot 5). -->
        <button
          v-if="canArbitrate"
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px] font-mono uppercase tracking-wider transition-colors"
          style="border-color: var(--surface-3); color: var(--indigo-700); background: var(--surface-1);"
          title="Auto-accept déterministe : Dino + texte convergent"
          @click="onClickAutoAccept"
        >
          <Wand2 class="h-3 w-3" />
          Auto-accept
        </button>
        <div
          class="mode-toggle inline-flex overflow-hidden rounded-md border"
          style="border-color: var(--surface-3); background: var(--surface-1);"
          :title="'Bascule mode · F'"
        >
          <button
            type="button"
            class="mode-btn"
            :class="{ active: mode === 'auto' }"
            @click="mode = 'auto'"
          >
            <Sparkles class="h-3 w-3" />
            Auto
          </button>
          <button
            type="button"
            class="mode-btn"
            :class="{ active: mode === 'free' }"
            @click="mode = 'free'"
          >
            <Search class="h-3 w-3" />
            Libre
            <span class="ml-1 font-mono text-[9px] uppercase tracking-wider opacity-70">F</span>
          </button>
        </div>
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[11px]"
          style="border-color: var(--surface-3); color: var(--ink-500); background: var(--surface-1);"
          @click="showHelp = !showHelp"
        >
          <Keyboard class="h-3 w-3" />
          ?
        </button>
      </div>
    </div>

    <!-- ═══ Chargement de la suite (batch local épuisé, fetch en vol) ═══ -->
    <section
      v-if="isQueueEmpty && !drained"
      class="flex flex-1 flex-col items-center justify-center px-8 py-16 text-center"
    >
      <p
        class="font-mono text-[11px] uppercase tracking-wider"
        style="color: var(--ink-400);"
      >
        Chargement de la suite…
      </p>
    </section>

    <!-- ═══ La file n'a pas pu être lue — À NE PAS CONFONDRE avec « vide » ═══ -->
    <section
      v-else-if="loadError"
      class="flex flex-1 flex-col items-center justify-center gap-4 px-8 py-16 text-center"
    >
      <p class="font-display text-4xl italic font-semibold" style="color: var(--danger);">
        La file n'a pas pu être lue.
      </p>
      <p class="max-w-xl text-sm" style="color: var(--ink-600);">{{ loadError }}</p>
      <p class="max-w-xl text-[11.5px]" style="color: var(--ink-400);">
        Rien n'est affiché plutôt que des données fausses. Jusqu'au 2026-08-20,
        cet écran servait ici une file de démonstration — trente pièces
        inventées — sans le signaler.
      </p>
      <button
        type="button"
        class="rounded-md border px-4 py-2 text-sm"
        style="border-color: var(--indigo-700); color: var(--indigo-700);"
        @click="load()"
      >Réessayer</button>
    </section>

    <!-- ═══ Empty state (queue réellement vidée) ═══ -->
    <section
      v-else-if="isQueueEmpty"
      class="flex flex-1 flex-col items-center justify-center px-8 py-16 text-center"
    >
      <p
        class="font-display text-5xl italic font-semibold"
        style="color: var(--indigo-700);"
      >
        Tout est résolu.
      </p>
      <p class="mt-4 max-w-md text-sm" style="color: var(--ink-500);">
        La queue est vide. La nouvelle ronde de scrapes alimentera la review
        à la prochaine cadence (cf. <code style="background: var(--surface-1); padding: 1px 4px; border-radius: 3px;">/sources</code>).
      </p>
      <p
        v-if="stats"
        class="mt-8 font-mono text-[10px] uppercase tracking-wider"
        style="color: var(--ink-400);"
      >
        {{ stats.n_done_this_week }} décidées cette semaine · {{ stats.median_seconds_per_decision.toFixed(1) }}s par décision en moyenne
      </p>
    </section>

    <!-- ═══ Review item ═══ -->
    <section
      v-else-if="currentItem"
      class="flex flex-1 flex-col overflow-hidden"
    >
      <div class="grid flex-1 gap-6 overflow-hidden px-8 py-6 lg:grid-cols-[minmax(0,1fr)_560px]">
          <!-- ── COLONNE GAUCHE ── -->
          <div class="flex min-h-0 flex-col gap-4 overflow-y-auto">
            <div class="flex items-center justify-end gap-2">
              <!-- Bascule TOUT le listing (donc les crops des autres) dans le
                   flow lot : geste structurant, réservé à l'arbitre (lot 5). -->
              <button
                v-if="canArbitrate"
                type="button"
                class="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-mono uppercase tracking-wider transition-colors"
                style="border-color: var(--surface-3); color: var(--ink-700); background: var(--surface-1);"
                title="Ce n'est pas un single mais un lot → bascule tout le listing dans le flow lot · L"
                @click="requalifyCurrentAsLot"
              >
                <Boxes class="h-3 w-3" />
                Requalifier en lot
                <span class="font-mono text-[9px] opacity-70">L</span>
              </button>
              <!-- Auto-crop et Recadrer encodent des pixels (cv2 sur :8042).
                   Rendu par public (D11) : GRISÉS pour l'arbitre — sur son poste
                   le geste existe, il lui manque juste l'API ML ; ABSENTS pour un
                   ami — le geste ne lui sera possible qu'au lot 6b, et un bouton
                   mort qui parle d'un port ne lui apprend rien. Ils ne sont
                   toujours pas *interdits* : c'est la machine qui manque. -->
              <button
                v-if="showHeavyGesture"
                type="button""
                class="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-mono uppercase tracking-wider transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                style="border-color: var(--surface-3); color: var(--indigo-700); background: var(--surface-1);"
                :title="canRunHeavy
                  ? 'Auto-crop score-guidé (probe) — à tenter avant le recadrage manuel · A'
                  : 'Auto-crop — disponible uniquement en local (API ML :8042)'"
                :disabled="autoCropBusy || !canRunHeavy"
                @click="runAutoCrop"
              >
                <Wand2 class="h-3 w-3" :class="{ 'animate-spin': autoCropBusy }" />
                Auto-crop
                <span
                  v-if="autoCropBadge"
                  class="font-mono text-[10px] normal-case"
                  style="color: var(--ink-500);"
                >{{ autoCropBadge }}</span>
                <span class="font-mono text-[9px] opacity-70">A</span>
              </button>
              <button
                v-if="showHeavyGesture"
                type="button"
                class="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-mono uppercase tracking-wider transition-colors disabled:cursor-not-allowed disabled:opacity-60"
                style="border-color: var(--surface-3); color: var(--indigo-700); background: var(--surface-1);"
                :title="canRunHeavy
                  ? 'Re-cropper manuellement (pièce mal cadrée) · E'
                  : 'Recadrage — disponible uniquement en local (API ML :8042)'"
                :disabled="!canRunHeavy"
                @click="showCropEditor = true"
              >
                <Crop class="h-3 w-3" />
                Recadrer
                <span class="font-mono text-[9px] opacity-70">E</span>
              </button>
            </div>
            <SplitCompare
              :crop-url="currentCropUrl"
              :canonical-url="focusedCandidate?.canonical_thumb_url ?? null"
              :bbox="currentItem.bbox"
            />

            <!-- Carte listing (prix/type/état/quote marché) : orientée
                 référentiel marché → masquée en contexte cohort (C4c), où la
                 review se limite à « bonne pièce ? ». -->
            <ListingContextCard
              v-if="!cohortId"
              :title="currentItem.listing_title"
              :source="currentItem.source"
              :price="currentItem.listing_price"
              :kind="effectiveKind"
              :kind-confidence="currentItem.listing_kind_confidence ?? null"
              :kind-corrected="correctedKind !== null"
              :condition="effectiveCondition"
              :condition-confidence="currentItem.condition_confidence ?? null"
              :condition-corrected="correctedCondition !== null"
              :origin-date="currentItem.listing_origin_date ?? null"
              :sold-qty="currentItem.sold_qty ?? null"
              :market-quote="focusedMarketQuote"
              :show-market="canArbitrate"
            />

            <AutoValidateVerdict
              v-if="currentItem"
              :review-id="currentItem.id"
            />

            <!-- Chunk Cr — suggestion DINOv2 top-1 : accept 1-clic.
                 Affiché seulement si dino_top1 non-null (83 % des singles).
                 Visuellement distinct (indigo) pour signaler l'origine ML.
                 Face hardcodée obverse (ancres Dino = obverses canoniques). -->
            <div
              v-if="currentItem?.dino_top1"
              class="flex items-center justify-between gap-3 rounded-md border px-3 py-2"
              style="border-color: var(--indigo-200, #c7d2fe); background: color-mix(in srgb, var(--indigo-700, #4338ca) 6%, var(--surface));"
            >
              <div class="flex min-w-0 flex-col gap-0.5">
                <span
                  class="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-wider"
                  style="color: var(--indigo-700);"
                >
                  <Sparkles class="h-3 w-3 shrink-0" />
                  Suggestion Dino
                </span>
                <span class="truncate font-mono text-[11px]" style="color: var(--ink);">
                  {{ currentItem.dino_top1.eurio_id }}
                </span>
                <span class="truncate text-[10px]" style="color: var(--ink-500);">
                  {{ currentItem.dino_top1.label }}
                  <span class="ml-1 font-mono opacity-70">sim={{ currentItem.dino_top1.score.toFixed(3) }}</span>
                </span>
              </div>
              <button
                type="button"
                class="inline-flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-semibold transition-colors"
                style="background: var(--indigo-700); color: var(--surface);"
                title="Accepter la suggestion DINOv2 top-1 (D)"
                @click="acceptDino"
              >
                <Sparkles class="h-3 w-3" />
                Accept Dino
                <kbd
                  class="ml-0.5 rounded px-1 py-0.5 font-mono text-[9px] uppercase"
                  style="background: rgba(255,255,255,0.2); letter-spacing: 0.05em;"
                >D</kbd>
              </button>
            </div>

            <TextSignals
              v-if="currentItem"
              :review-id="currentItem.id"
              variant="standard"
            />

            <DinoVerdict
              v-if="currentItem"
              :review-id="currentItem.id"
              :reload-key="dinoReloadKey"
              variant="standard"
            />
          </div>

          <!-- ── COLONNE DROITE (composant partagé avec lot) ── -->
          <ReviewRightColumn
            :target="currentItem.target_candidate ?? null"
            :candidates="currentItem.candidates"
            :group-candidates="currentItem.group_candidates ?? []"
            :standard-candidates="currentItem.standard_candidates ?? []"
            :mode="mode"
            :focused-candidate-idx="focusedCandidateIdx"
            :free-search-candidate="freeSearchCandidate"
            :review-id="currentItem.id"
            :dino-reload-key="dinoReloadKey"
            @target-focus="selectTarget"
            @candidate-focus="focusCandidate"
            @dino-select="onDinoSelect"
            @free-select="onSearchSelect"
            @group-select="onGroupSelect"
            @standard-select="onStandardSelect"
          />
      </div>

      <ReviewActionBar
        :face="face"
        :can-validate="canValidate"
        :validate-hint="validateBlockedReason"
        :focused-eurio-id="focusedCandidate?.eurio_id ?? null"
        @face="setFace"
        @validate="validateCurrent"
        @reject="rejectCurrent"
        @skip="skipCurrent"
      />
      <!-- WS1 : sortir l'item de la lane auto/ccproxy vers la queue manuelle -->
      <div v-if="lane && lane !== 'manual' && currentItem" class="mt-2 text-center">
        <button
          type="button"
          class="inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium"
          style="background: var(--surface-2); color: var(--ink-600);"
          title="Retire cet item de la lane courante et le met dans la queue manuelle (je le tranche moi-même)"
          @click="moveCurrentToManual"
        >
          <Undo2 class="h-3.5 w-3.5" /> Faire en manuel
        </button>
      </div>
    </section>

    <!-- ═══ Bandeau d'alerte (descend du haut) ═══ -->
    <Transition name="topnotice">
      <div
        v-if="topNotice"
        class="fixed left-1/2 top-0 z-40 -translate-x-1/2 inline-flex items-center gap-2.5 rounded-b-xl px-7 py-3.5 text-[14px] font-semibold shadow-xl"
        style="background: var(--warning); color: var(--ink);"
      >
        <AlertTriangle class="h-5 w-5" />
        {{ topNotice }}
      </div>
    </Transition>

    <!-- ═══ Toast undo — fenêtre de COMMIT_WINDOW_MS avant écriture ═══ -->
    <Transition name="toast">
      <div
        v-if="pendingCommit"
        :key="toastNonce"
        class="fixed bottom-20 left-1/2 z-20 -translate-x-1/2 inline-flex items-center gap-3 overflow-hidden rounded-full border px-4 py-2 text-[12px] shadow-lg"
        style="border-color: var(--surface-3); background: var(--ink); color: var(--surface);"
      >
        <span>
          <strong>{{ PENDING_LABEL[pendingCommit.kind] }}</strong>
          <span class="opacity-60">· enregistrement dans {{ COMMIT_WINDOW_MS / 1000 }} s</span>
        </span>
        <button
          type="button"
          class="inline-flex items-center gap-1 rounded-md px-2 py-0.5 font-mono text-[11px] transition-colors"
          style="background: var(--surface); color: var(--ink);"
          @click="undoLast"
        >
          <Undo2 class="h-3 w-3" /> Annuler
        </button>
        <!-- Compte à rebours CSS pur — aucun timer JS à nettoyer. -->
        <span
          class="undo-countdown"
          :style="{ animationDuration: COMMIT_WINDOW_MS + 'ms' }"
        />
      </div>
    </Transition>

    <!-- ═══ Éditeur de re-crop manuel (overlay) ═══ -->
    <CircleCropEditor
      v-if="showCropEditor && currentItem"
      :review-id="currentItem.id"
      @close="showCropEditor = false"
      @saved="onCropSaved"
    />

    <!-- ═══ Help overlay ═══ -->
    <div
      v-if="showHelp"
      class="fixed inset-0 z-30 flex items-center justify-center px-6"
      style="background: rgba(14,14,31,.65); backdrop-filter: blur(4px);"
      @click="showHelp = false"
    >
      <article
        class="max-w-md rounded-lg border p-6"
        style="border-color: var(--surface-3); background: var(--surface);"
        @click.stop
      >
        <h2 class="font-display text-lg italic font-semibold" style="color: var(--indigo-700);">
          Raccourcis
        </h2>
        <dl class="mt-4 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">1 – 5</dt>
          <dd style="color: var(--ink-500);">Focus candidat</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">⏎</dt>
          <dd style="color: var(--ink-500);">Valider avec candidat focusé</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">R</dt>
          <dd style="color: var(--ink-500);">Reject (image inutilisable)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">N</dt>
          <dd style="color: var(--ink-500);">Skip (repousser)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">F</dt>
          <dd style="color: var(--ink-500);">Bascule mode Auto / Sélection libre</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">O / V / U</dt>
          <dd style="color: var(--ink-500);">Face : avers / revers / inconnu</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">K</dt>
          <dd style="color: var(--ink-500);">Corriger le type de listing (cycle)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">C</dt>
          <dd style="color: var(--ink-500);">Corriger l'état de la pièce (cycle)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--indigo-700);">D</dt>
          <dd style="color: var(--ink-500);">Accepter la suggestion DINOv2 top-1 (si disponible)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--indigo-700);">A</dt>
          <dd style="color: var(--ink-500);">Auto-crop score-guidé (probe) — à tenter avant le recadrage manuel</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">E</dt>
          <dd style="color: var(--ink-500);">Recadrer le crop manuellement (⏎ valide le recadrage)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">L</dt>
          <dd style="color: var(--ink-500);">Requalifier en lot (le single est en fait un lot → flow lot)</dd>
          <dt class="font-mono text-[12px]" style="color: var(--ink-700);">Esc</dt>
          <dd style="color: var(--ink-500);">Fermer overlay</dd>
        </dl>
        <p class="mt-5 text-[11px]" style="color: var(--ink-400);">
          Cliquer ailleurs ou <kbd
            class="mx-1 inline-block rounded px-1 py-0.5 font-mono text-[10px]"
            style="background: var(--surface-1); border: 1px solid var(--surface-3);"
          >Esc</kbd> pour fermer.
        </p>
      </article>
    </div>

  </div>
</template>

<style scoped>
@keyframes fade-in {
  from {
    opacity: 0;
    transform: translateX(6px);
  }
  to {
    opacity: 1;
    transform: translateX(0);
  }
}

.toast-enter-active,
.toast-leave-active {
  transition: all 200ms ease-out;
}
.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translate(-50%, 8px);
}

/* Bandeau d'alerte : glisse depuis au-dessus de l'écran, s'arrête au top. */
.topnotice-enter-active,
.topnotice-leave-active {
  transition: opacity 220ms ease-out, transform 260ms cubic-bezier(0.16, 1, 0.3, 1);
}
.topnotice-enter-from,
.topnotice-leave-to {
  opacity: 0;
  transform: translate(-50%, -100%);
}

kbd {
  font-family: ui-monospace, SFMono-Regular, monospace;
}

/* Compte à rebours du toast undo : barre qui se vide en COMMIT_WINDOW_MS
   (durée posée inline). CSS pur — aucun timer JS à nettoyer. */
.undo-countdown {
  position: absolute;
  left: 0;
  bottom: 0;
  height: 2px;
  width: 100%;
  background: var(--gold-soft);
  transform-origin: left;
  animation-name: undo-countdown;
  animation-timing-function: linear;
  animation-fill-mode: forwards;
}
@keyframes undo-countdown {
  from {
    transform: scaleX(1);
  }
  to {
    transform: scaleX(0);
  }
}

.mode-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  font-size: 11px;
  color: var(--ink-500);
  background: transparent;
  cursor: pointer;
  transition: all 140ms ease;
}
.mode-btn:hover {
  color: var(--ink-700);
}
.mode-btn.active {
  color: var(--surface);
  background: var(--ink);
}
.mode-btn + .mode-btn {
  border-left: 0.5px solid var(--surface-3);
}
</style>
