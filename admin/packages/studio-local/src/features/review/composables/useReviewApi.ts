// Review queue API composable — backed by ml/api/review_queue_routes.py.
//
// Endpoints (cf. docs/sources-refacto/review-queue.md §"Endpoints API attendus") :
//   GET    /review-queue?status=open&limit=20&order=priority
//   GET    /review-queue/:id
//   POST   /review-queue/:id/decide
//   POST   /review-queue/:id/skip
//   POST   /review-queue/:id/reject
//   GET    /review-queue/stats
//
// ⛔ IL N'Y A PLUS DE REPLI SUR DES DONNÉES FICTIVES. Retiré le 2026-08-20,
// après l'avoir vu mordre.
//
// Ce module servait un `MOCK_QUEUE` de trente pièces inventées dès qu'un fetch
// échouait au niveau RÉSEAU (`TypeError`) — pensé pour le développement front
// sans backend. Ce qui s'est passé en vrai : le conteneur `eurio-api` a été
// recréé pendant une session de tri (`docker compose up -d --build`, quelques
// secondes d'indisponibilité). Les requêtes en vol ont échoué, la file s'est
// remplie de fausses pièces SLOVÈNES à 1 EUR — dans un écran cadré sur une
// pièce ESPAGNOLE — sans un mot à l'écran. L'opérateur a conclu que la
// fonctionnalité était cassée, et a « trié » quatre items qui n'existaient pas.
//
// Pire, côté écriture : `decide`/`skip`/`reject` renvoyaient un succès et se
// contentaient d'un `console.info('[mock fallback] …')`. On pouvait trancher
// quarante crops et n'en écrire aucun.
//
// La règle, désormais : une lecture qui échoue LÈVE, et l'écran le dit. Une
// écriture qui échoue LÈVE, et rien ne prétend qu'elle a eu lieu. Un écran
// vide et honnête vaut mieux qu'un écran plein et faux.

import { eurioApi, EurioApiError } from '@/shared/api/eurio-api'
import { ML_API } from '@/features/training/composables/useTrainingApi'

export type ReviewFace = 'obverse' | 'reverse' | 'unknown'
export type ReviewSource = 'ebay' | 'catawiki' | 'mdp' | 'lmdlp' | 'numista'
// Chunk C4 — taxonomie listing + état numismatique (cf. C2).
export type ListingKind = 'single' | 'lot' | 'coffret' | 'graded_slab'
export type ConditionTier = 'UNC' | 'TTB' | 'TB'

/** Prix de référence agrégé (coin_market_quotes) pour un tier d'état. */
export interface MarketQuote {
  condition: string
  p10: number | null
  p50: number | null
  p90: number | null
  sample_size: number
  period_start: string
}

export interface ReviewCandidate {
  eurio_id: string
  score: number
  label: string
  country: string
  denomination: string
  year: number | null
  canonical_thumb_url: string
}

export interface ReviewItem {
  id: string
  crop_url: string
  bbox: { x: number; y: number; w: number; h: number } | null
  source: ReviewSource
  source_ref: string
  listing_title: string
  listing_url: string | null
  listing_price: number | null
  candidates: ReviewCandidate[]
  face_detected: ReviewFace | null
  priority: number
  is_multi_coin_lot: boolean
  quality_score: number
  enqueued_at: string
  // eurio_id qui a piloté le scrape (parent source_image). 80 % des
  // reviews sont la cible — le drawer la pré-sélectionne au top de la
  // colonne suggestions pour gagner en vélocité. Optionnels car les
  // mocks legacy + sources sans target les laissent à null.
  target_eurio_id?: string | null
  target_candidate?: ReviewCandidate | null
  // Chunk 5b — pièces du groupe de découverte (2 € commémo, même pays +
  // année). Non vide seulement quand le theme-match n'a pas tranché
  // (target_candidate null, verdict ambigu) : le reviewer choisit la
  // sœur d'un clic au lieu de passer par la recherche libre.
  group_candidates?: ReviewCandidate[]
  // Review « N-contre-designs » — design groups avers standard du pays pour
  // un crop issu d'un scrape standard (listing_year null). Affichés en
  // priorité tout en haut : le reviewer tranche entre N designs (ex. ES →
  // Juan Carlos t1/t2 / Felipe VI) d'un clic. eurio_id = membre représentant
  // (la décision écrit ce membre → classe = son design_group). Vide pour les
  // crops commémo (année présente).
  standard_candidates?: ReviewCandidate[]
  // Chunk Cr — top-1 DINOv2 inliné (dinov2-vits14, 2eur_commemo).
  // Préférence country-band > global. null si pas de prédiction Dino ou
  // eurio_id mort. Sert au bouton « Accept Dino (D) » 1-clic dans
  // SingleReviewView — face hardcodée obverse (ancres = obverses Numista).
  dino_top1?: ReviewCandidate | null
  // Signaux de la banque des SUGGESTIONS (`2eur_all`) — celle qui couvre les
  // pièces courantes, contrairement à celle du verdict. Ils portent le tri
  // `order=dino` : les afficher est ce qui permet à l'opérateur de savoir
  // POURQUOI ce crop est en tête.
  sugg_top1_eurio_id?: string | null
  sugg_top1_sim?: number | null
  sugg_spread?: number | null
  // Chunk C4 — contexte listing pour la carte d'audit « Listing & marché ».
  // Issu de C1 (source_images) + C2 (listing_text_signals). Optionnels :
  // null sur les rows antérieures / les mocks.
  listing_kind?: ListingKind | null
  listing_kind_confidence?: number | null
  condition?: ConditionTier | null
  condition_confidence?: number | null
  listing_origin_date?: string | null
  sold_qty?: number | null
}

export interface ReviewDecision {
  eurio_id: string
  face: ReviewFace
  variant_kind?: string
  notes?: string
}

export interface ReviewStats {
  n_pending: number
  n_done_today: number
  median_seconds_per_decision: number
  n_done_this_week: number
}

// ─── Public API ─────────────────────────────────────────────────────────

/** Returns null on network error so callers can mock-fallback. */
async function safeFetch<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    const resp = await fetch(`${ML_API}${path}`, init)
    if (!resp.ok) {
      // 4xx/5xx with a real backend: surface the error to the caller.
      const detail = await resp.json().catch(() => ({ detail: `HTTP ${resp.status}` }))
      throw new ReviewApiError(resp.status, typeof detail === 'object' && detail && 'detail' in detail
        ? String((detail as { detail: unknown }).detail)
        : `HTTP ${resp.status}`)
    }
    return (await resp.json()) as T
  } catch (err) {
    if (err instanceof TypeError) return null  // network down → fallback
    throw err
  }
}

/** Lecture eurio-api (Bearer PAT). Échoue bruyamment — jamais de substitution.
 *
 * `status: 0` = échec RÉSEAU (canonique injoignable, conteneur en cours de
 * recréation, DNS, coupure). On le distingue d'un code HTTP pour que l'écran
 * puisse dire laquelle des deux choses s'est produite. */
async function fetchEurio<T>(path: string): Promise<T> {
  try {
    return await eurioApi.get<T>(path)
  } catch (err) {
    if (err instanceof EurioApiError) {
      throw new ReviewApiError(err.status, err.message)
    }
    if (err instanceof TypeError) {
      throw new ReviewApiError(
        0,
        'Canonique injoignable (eurio-api). Rien n\'est affiché plutôt que '
        + 'des données fausses — réessaie dans quelques secondes ; si ça '
        + 'persiste, vérifie que le conteneur tourne.',
      )
    }
    throw err
  }
}

/** ÉCRITURE review (TC2, Model B) : POST Bearer PAT vers le canonique, avec
 * `keepalive` (commit-on-unload, fenêtre d'undo).
 *
 * Échoue bruyamment. Une décision de review est la seule donnée du projet
 * qu'aucun calcul ne régénère : la perdre en silence est la pire chose que
 * cette couche puisse faire. */
async function fetchEurioWrite<T>(
  path: string,
  body?: unknown,
  opts: CommitOpts = {},
): Promise<T> {
  try {
    return await eurioApi.post<T>(path, body, { keepalive: opts.keepalive })
  } catch (err) {
    if (err instanceof EurioApiError) {
      throw new ReviewApiError(err.status, err.message)
    }
    if (err instanceof TypeError) {
      throw new ReviewApiError(
        0,
        'Canonique injoignable : la décision N\'A PAS été écrite. '
        + 'Réessaie — ne passe pas au crop suivant en croyant l\'avoir tranché.',
      )
    }
    throw err
  }
}

export class ReviewApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message)
  }
}

function promoteUrl(url: string): string {
  if (!url) return url
  return url.startsWith('http') ? url : `${ML_API}${url}`
}

function promoteCandidateThumb(c: ReviewCandidate): ReviewCandidate {
  return { ...c, canonical_thumb_url: promoteUrl(c.canonical_thumb_url) }
}

function promoteItemUrls(r: ReviewItem): ReviewItem {
  return {
    ...r,
    crop_url: promoteUrl(r.crop_url),
    // Toutes les listes de candidats ont une vignette canonique (relative
    // /referential/… ou /images/… → préfixe ML_API requis). Avant, seuls
    // target_candidate et dino_top1 étaient promus → vignettes cassées dans
    // « candidats auto-name » et « pièces standards » à URL locale.
    candidates: r.candidates?.map(promoteCandidateThumb) ?? r.candidates,
    standard_candidates: r.standard_candidates?.map(promoteCandidateThumb),
    group_candidates: r.group_candidates?.map(promoteCandidateThumb),
    target_candidate: r.target_candidate
      ? promoteCandidateThumb(r.target_candidate)
      : r.target_candidate,
    dino_top1: r.dino_top1 ? promoteCandidateThumb(r.dino_top1) : r.dino_top1,
  }
}

export async function fetchReviewQueue(
  opts: {
    limit?: number
    cohortId?: string | null
    lane?: string | null
    eurioId?: string | null
    /** IDs review_queue explicites (galerie enrichment → review ciblée). */
    reviewIds?: string[] | null
    /**
     * `'dino'` = ce que le modèle rattache le plus nettement d'abord, les
     * crops jamais scorés en queue. Défaut `'priority'` (l'ordre historique).
     */
    order?: 'priority' | 'enqueued_at' | 'dino'
    /** Ne garder que les crops au-dessus de ce spread (palier d'auto-accept). */
    dinoMinSpread?: number | null
    /** Ne garder que ceux dont le top-1 tombe dans la classe travaillée. */
    dinoTop1Only?: boolean
    /**
     * PÊCHE — le périmètre devient « ce que la banque rattache à cette classe »
     * et REMPLACE le périmètre par cible (`eurioId` / `cohortId`). C'est ce qui
     * rend atteignables les crops qu'aucun scrape ne visait : sur l'italienne
     * standard, la file par cible sert 57 items dont 2 utiles, la pêche 137
     * tous utiles.
     */
    dinoClass?: string | null
    /** Position dans le top-k qui suffit à retenir un crop : 1, 3 ou 5. */
    dinoRank?: number | null
    /**
     * Restreindre aux annonces du PAYS DE LA CLASSE. **Actif par défaut côté
     * API** : mesuré le 2026-08-20, il fait passer la précision du top-1 de
     * 91,3 % à 99,1 % sur les courantes, en gardant 95 % des vrais positifs.
     * Passer `false` explicitement pour le lever.
     */
    dinoCountryOnly?: boolean
    /**
     * Ne servir que les crops CRÉÉS PAR CES RUNS de scrape (`image_assets.
     * run_id`). Se combine à tout le reste — c'est un ET, pas un remplacement.
     * Cf. `queryRunIds` (`?run=a,b`) et `fetchRunProgress` pour le compteur.
     */
    runIds?: string[] | null
    /**
     * Ne servir que les crops dont le top-1 DINO tombe dans une classe ENCORE
     * EN BESOIN ; les classes pleines sont parquées, jamais fermées (D2/D3).
     * Les crops sans prédiction sortent aussi. Cf. `queryNeedOnly` (`?need=1`).
     */
    needOnly?: boolean
  } = {},
): Promise<ReviewItem[]> {
  const limit = opts.limit ?? 30
  const params = new URLSearchParams({
    limit: String(limit),
    order: opts.order ?? 'priority',
  })
  if (opts.cohortId) params.set('cohort_id', opts.cohortId)
  if (opts.lane) params.set('lane', opts.lane)
  if (opts.eurioId) params.set('eurio_id', opts.eurioId)
  if (opts.reviewIds && opts.reviewIds.length) params.set('review_ids', opts.reviewIds.join(','))
  if (opts.dinoMinSpread != null) params.set('dino_min_spread', String(opts.dinoMinSpread))
  if (opts.dinoTop1Only) params.set('dino_top1_only', 'true')
  if (opts.dinoClass) params.set('dino_class', opts.dinoClass)
  if (opts.dinoRank) params.set('dino_rank', String(opts.dinoRank))
  if (opts.dinoCountryOnly === false) params.set('dino_country_only', 'false')
  if (opts.runIds && opts.runIds.length) params.set('run_id', opts.runIds.join(','))
  if (opts.needOnly) params.set('need_only', 'true')
  // Phase 2c-b : porté sur eurio-api (Bearer PAT).
  const items = await fetchEurio<ReviewItem[]>(`/review-queue?${params.toString()}`)
  return items.map(promoteItemUrls)
}

// ─── Avancement par run source ──────────────────────────────────────────

/** `total = open + done + skipped`. `skipped` = passé par l'opérateur : la
 *  row reste servie par la file (status `open`), mais elle est comptée à part
 *  pour que le compteur avance sur un run qu'on ne fait que parcourir. */
export interface RunProgressCounts {
  total: number
  open: number
  done: number
  skipped: number
}

/** Les rows OUVERTES que `need_only` écarte de la file (D2/D3) : top-1 dans
 *  une classe pleine, ou pas de top-1 du tout. Parquées, jamais fermées. */
export interface RunParked {
  full_class: number
  no_prediction: number
}

export interface RunProgress extends RunProgressCounts {
  run_ids: string[]
  need_only: boolean
  by_kind: Record<'single' | 'lot', RunProgressCounts> & Record<string, RunProgressCounts>
  /** Présent sous `need_only` seulement ; alors `total = open + done + skipped
   *  + parked.full_class + parked.no_prediction`. */
  parked: RunParked | null
}

/** Où en est la review des crops produits par ces runs — TOUTES les rows,
 *  pas seulement l'ouvert que sert `fetchReviewQueue`. Sous `needOnly`,
 *  `open` ne compte que ce que la file servira et `parked` dit le reste. */
export async function fetchRunProgress(
  runIds: string[],
  needOnly = false,
): Promise<RunProgress> {
  const params = new URLSearchParams({ run_id: runIds.join(',') })
  if (needOnly) params.set('need_only', 'true')
  return fetchEurio<RunProgress>(`/review-queue/run-progress?${params.toString()}`)
}

export async function fetchReviewItem(id: string): Promise<ReviewItem> {
  // Phase 2c-b : porté sur eurio-api.
  return promoteItemUrls(
    await fetchEurio<ReviewItem>(`/review-queue/${encodeURIComponent(id)}`),
  )
}

export async function fetchReviewStats(): Promise<ReviewStats> {
  // Phase 2c : porté sur eurio-api (Bearer PAT). Ces compteurs servaient
  // autrefois `n_pending: 1247` en dur quand le backend était absent — un
  // tableau de bord qui invente ses chiffres est pire qu'un tableau de bord
  // vide.
  return fetchEurio<ReviewStats>('/review-queue/stats')
}

// `keepalive` permet au POST de survivre à un unload de page (fermeture
// d'onglet pendant la fenêtre d'undo). Cf. SingleReviewView — commit
// différé.
export interface CommitOpts {
  keepalive?: boolean
}

export async function decideReviewItem(
  id: string,
  payload: ReviewDecision,
  opts: CommitOpts = {},
): Promise<void> {
  // TC2 (Model B) : écriture review portée sur eurio-api (Bearer PAT → canonique).
  await fetchEurioWrite<unknown>(
    `/review-queue/${encodeURIComponent(id)}/decide`, payload, opts,
  )
}

export async function skipReviewItem(id: string, opts: CommitOpts = {}): Promise<void> {
  await fetchEurioWrite<unknown>(
    `/review-queue/${encodeURIComponent(id)}/skip`, undefined, opts,
  )
}

export async function rejectReviewItem(id: string, opts: CommitOpts = {}): Promise<void> {
  await fetchEurioWrite<unknown>(
    `/review-queue/${encodeURIComponent(id)}/reject`, undefined, opts,
  )
}

/**
 * Corrige manuellement listing_kind et/ou condition d'un listing (C4).
 * Se propage à toutes les photos du listing côté backend. Fire-and-forget
 * côté appelant : un échec ne bloque pas le flow d'attribution.
 */
export async function correctListing(
  id: string,
  payload: { listing_kind?: ListingKind; condition?: ConditionTier },
): Promise<void> {
  // Direction A / C3 : correction canonique → VPS (jumeau lean
  // serving/review_queue/writes.py, chemin identique) via eurioApi.
  await fetchEurioWrite<unknown>(
    `/review-queue/${encodeURIComponent(id)}/correct-listing`,
    payload,
  )
}

/**
 * Requalifie le crop courant — et tout son listing — en LOT (review_queue.kind
 * passe de 'single' à 'lot'). Les crops du listing quittent la queue single et
 * basculent dans le flow lot. Réservé au cas « ce single est en fait un lot ».
 */
export interface RequalifyLotResult {
  status: string
  listing_key: string
  n_requalified: number
  n_images: number
}

export async function requalifyReviewAsLot(id: string): Promise<RequalifyLotResult> {
  // Direction A / C3 : requalif canonique → VPS (jumeau lean) via eurioApi.
  return fetchEurioWrite<RequalifyLotResult>(
    `/review-queue/${encodeURIComponent(id)}/requalify-lot`,
  )
}

// ─── Re-crop manuel (chantier crop-quality-overhaul, Session B) ──────────

/** Contexte de l'éditeur de cercle : le RAW (sur lequel on dessine) + le
 *  cercle de départ (crop actuel), en px NATIFS du raw. */
export interface CropEditContext {
  asset_id: string
  source: string
  raw_url: string
  crop_url: string
  raw_width: number | null
  raw_height: number | null
  hint: { cx: number; cy: number; r: number } | null
  // Cercle dominant détecté dans le raw (source mono-pièce) : point de départ
  // de l'éditeur quand le crop stocké est mal dimensionné. null sur les lots.
  suggested_circle?: { cx: number; cy: number; r: number } | null
}

export interface ManualCropResult {
  asset_id: string
  cx: number
  cy: number
  r: number
  bbox: { x: number; y: number; w: number; h: number }
  width: number
  height: number
  detection_method: string
  crop_b64: string
  minio_ok: boolean
}

/** Charge le raw + le cercle de départ pour l'éditeur. Pas de fallback mock :
 *  l'éditeur n'a de sens qu'avec un vrai backend (raw en cache local). */
export async function fetchCropEditContext(reviewId: string): Promise<CropEditContext> {
  const real = await safeFetch<CropEditContext>(
    `/review-queue/${encodeURIComponent(reviewId)}/crop-edit-context`,
  )
  if (real === null) {
    throw new Error('Backend indisponible — le crop manuel requiert l’API ML locale.')
  }
  return {
    ...real,
    raw_url: promoteUrl(real.raw_url),
    crop_url: promoteUrl(real.crop_url),
  }
}

/** Re-croppe l'asset depuis un cercle (cx,cy,r) en px natifs du raw. Écrase le
 *  crop (cache + MinIO + DB) au format prod ; eurio_id préservé, review inchangée. */
export async function manualCrop(
  reviewId: string,
  circle: { cx: number; cy: number; r: number },
): Promise<ManualCropResult> {
  const real = await safeFetch<ManualCropResult>(
    `/review-queue/${encodeURIComponent(reviewId)}/manual-crop`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(circle),
    },
  )
  if (real === null) {
    throw new Error('Backend indisponible — le re-crop manuel n’a pas pu être enregistré.')
  }
  return real
}

// ─── Re-crop manuel keyé ASSET (page coin-detail, hors review queue) ─────
// Même cœur backend que la voie review (crop_edit.py), mais l'éditeur s'ouvre
// sur une vignette de la galerie enrichment : recadrage EN PLACE, statut +
// eurio_id préservés (un recadrage ≠ une décision). Cf. coin_assets_routes.

/** Charge le raw + le cercle de départ pour l'éditeur, depuis un asset_id. */
export async function fetchAssetCropEditContext(assetId: string): Promise<CropEditContext> {
  const real = await safeFetch<CropEditContext>(
    `/coins/assets/${encodeURIComponent(assetId)}/crop-edit-context`,
  )
  if (real === null) {
    throw new Error('Backend indisponible — le crop manuel requiert l’API ML locale.')
  }
  return {
    ...real,
    raw_url: promoteUrl(real.raw_url),
    crop_url: promoteUrl(real.crop_url),
  }
}

/** Re-croppe un asset en place (écrase cache + MinIO + DB au format prod). */
export async function manualCropAsset(
  assetId: string,
  circle: { cx: number; cy: number; r: number },
): Promise<ManualCropResult> {
  const real = await safeFetch<ManualCropResult>(
    `/coins/assets/${encodeURIComponent(assetId)}/manual-crop`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(circle),
    },
  )
  if (real === null) {
    throw new Error('Backend indisponible — le re-crop manuel n’a pas pu être enregistré.')
  }
  return real
}

// ─── Départage Dino en ensemble fermé (candidats de groupe / standards) ──

export interface RankedCandidate {
  eurio_id: string
  sim: number
}

export interface RankCandidatesResult {
  anchors_kind: string
  encoder_version: string | null
  ranked: RankedCandidate[]
  /** eurio_ids fournis mais absents de la banque d'ancres (non classables). */
  missing: string[]
}

/**
 * Classe un ENSEMBLE FERMÉ de candidats (eurio_ids connus) par similarité Dino
 * au crop de la review. Sert à départager les pièces du groupe (pays+année) ou
 * les designs standard quand le top-K open-vocab abstient (la bonne réponse est
 * enterrée sous des pays voisins). Couche d'aide → renvoie null sur tout échec
 * (réseau, 4xx, hors-scope) plutôt que de bloquer le flow de review.
 */
export async function rankCandidates(
  reviewId: string,
  eurioIds: string[],
): Promise<RankCandidatesResult | null> {
  if (!eurioIds.length) return null
  try {
    return await safeFetch<RankCandidatesResult>(
      `/review-queue/${encodeURIComponent(reviewId)}/rank-candidates`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ eurio_ids: eurioIds }),
      },
    )
  } catch {
    return null
  }
}

// ─── Auto-crop score-guided (probe → balayage rayon → meilleur crop) ─────

export interface AutoCropResult {
  applied: boolean
  /** Score probe du crop actuel et du meilleur candidat (comparables). */
  baseline_score: number | null
  best_score: number | null
  /** Rayon retenu / rayon actuel (ex. 1.8 = pièce 1.8× plus grande). */
  ratio: number | null
  /** 'improved' (écrit) · 'already_optimal' (rien) · 'no_candidate'. */
  reason: string
}

/**
 * Auto-crop « propose & recrop » : balaye le rayon autour de la bbox actuelle,
 * score chaque candidat avec la probe gelée, et écrit le meilleur crop SEULEMENT
 * s'il bat franchement l'actuel (sinon « déjà optimal »). Outil à tenter avant le
 * recadrage manuel. Lève sur échec backend (l'appelant surface le message).
 */
export async function autoCropReview(reviewId: string): Promise<AutoCropResult> {
  const real = await safeFetch<AutoCropResult>(
    `/review-queue/${encodeURIComponent(reviewId)}/auto-crop`,
    { method: 'POST' },
  )
  if (real === null) {
    throw new Error('Backend indisponible — l’auto-crop requiert l’API ML locale.')
  }
  return real
}

// ─── Dashboard triage stats ──────────────────────────────────────────────

export interface TriageVerdictCounts {
  auto_candidate: number
  partial: number
  divergent: number
  unknown: number
}

export interface TriageStats {
  n_pending: number
  n_done_today: number
  n_done_today_auto_dino: number
  n_done_this_week: number
  by_verdict: TriageVerdictCounts
  // WS1 : compteurs par LANE PERSISTÉE (review_queue.lane). Source de vérité des
  // 2 cartes du cockpit (manual/auto_accept). by_verdict reste fourni
  // pour compat/debug, mais l'affichage vient de by_lane.
  by_lane: { manual: number; auto_accept: number }
  // Lots (kind='lot') PAR LANE — décompose la carte « Lots » (B3 : on ne cache
  // plus les lots manuels). Optionnel : backends antérieurs au chunk F6.
  by_lane_lot?: { manual: number; auto_accept: number }
  // Crops en review LOT (kind='lot') — flow distinct du single (cockpit cohort).
  n_lot_crops: number
  // Crops rejetés (récupérables via /review/recover) + items skippés (report
  // informationnel). Optionnels : backends antérieurs au chunk recover.
  n_rejected?: number
  n_skipped?: number
}

/**
 * Agrégat unique pour le dashboard `/review` : compte total queue +
 * répartition par verdict d'auto-validation (auto_candidate / partial /
 * divergent / unknown). Source de vérité partagée avec `runAutoAccept`.
 *
 * `cohortId` (optionnel) restreint tous les compteurs aux images dont le coin
 * theme-matché est dans la cohort — alimente les 3 cartes de la page cohort.
 */
export async function fetchTriageStats(cohortId?: string | null): Promise<TriageStats> {
  const qs = cohortId ? `?cohort_id=${encodeURIComponent(cohortId)}` : ''
  // Phase 2c-b : porté sur eurio-api.
  const real = await fetchEurio<TriageStats>(`/review-queue/triage-stats${qs}`)
  if (real !== null) return real
  // Mock fallback (backend off) — zéros honnêtes.
  return {
    n_pending: 0,
    n_done_today: 0,
    n_done_today_auto_dino: 0,
    n_done_this_week: 0,
    by_verdict: { auto_candidate: 0, partial: 0, divergent: 0, unknown: 0 },
    by_lane: { manual: 0, auto_accept: 0 },
    by_lane_lot: { manual: 0, auto_accept: 0 },
    n_lot_crops: 0,
    n_rejected: 0,
    n_skipped: 0,
  }
}

/**
 * Déplace un item de review vers la lane MANUELLE (switch unidirectionnel, WS1).
 * Sticky côté backend (lane_source='human') : aucun recalcul Dino ne le re-route.
 */
export async function moveReviewLaneToManual(id: string): Promise<void> {
  // Direction A / C3 : mutation canonique du routage review → VPS (jumeau lean).
  await fetchEurioWrite<unknown>(
    `/review-queue/${encodeURIComponent(id)}/move-lane`,
  )
}

// ─── Récupération des crops rejetés (un-reject) ──────────────────────────

/** Un crop rejeté, récupérable via la grille /review/recover. */
export interface RejectedCrop {
  review_id: string
  image_asset_id: string
  crop_url: string
  listing_title: string | null
  quality_reason: string | null
  decided_at: string | null
  target_eurio_id: string | null
  target_label: string | null
}

export interface RestoreResult {
  restored: number
  skipped: string[]
}

/** Liste les crops rejetés d'une cohort (grille de récupération). */
export async function fetchRejectedCrops(
  cohortId?: string | null,
): Promise<RejectedCrop[]> {
  const qs = cohortId ? `?cohort_id=${encodeURIComponent(cohortId)}` : ''
  // Phase 2c : porté sur eurio-api. Les `crop_url` sont des chemins relatifs
  // /sources/{id}/assets/.../file — résolus vers ML_API local par promoteUrl
  // (le file-serving reste sur le poste dev — Phase 6).
  try {
    const real = await eurioApi.get<RejectedCrop[]>(`/review-queue/rejected${qs}`)
    return real.map((r) => ({ ...r, crop_url: promoteUrl(r.crop_url) }))
  } catch (err) {
    if (err instanceof EurioApiError) {
      throw new ReviewApiError(err.status, err.message)
    }
    return []  // network down → empty list
  }
}

/** Ré-ouvre des reviews rejetées : elles repassent en queue manuelle. */
export async function restoreRejected(reviewIds: string[]): Promise<RestoreResult> {
  // TC2 (Model B) : écriture portée sur eurio-api (Bearer PAT → canonique).
  const real = await fetchEurioWrite<RestoreResult>('/review-queue/restore', {
    review_ids: reviewIds,
  })
  if (real === null) {
    throw new Error('Backend indisponible — la remise en queue n’a pas pu être enregistrée.')
  }
  return real
}

// ─── Auto-accept déterministe (Dino + texte, pas de Claude) ──────────────

export interface AutoAcceptPreviewItem {
  review_id: string
  image_asset_id: string
  crop_url: string
  listing_title: string
  listing_url: string | null
  source: string
  target_eurio_id: string
  target_label: string
  target_thumb_url: string | null
  sim: number | null
  spread: number | null
  face_detected: string | null
  reason: string
}

export interface AutoAcceptResult {
  processed: number
  accepted: number
  by_category: Record<string, number>
  dry_run: boolean
  preview: AutoAcceptPreviewItem[]
}

/**
 * Itère la queue open et auto-décide les items dont le verdict combiné
 * (Dino + texte) est `auto_candidate`. En `dry_run=true`, ne touche à
 * rien et retourne en plus la liste `preview[]` enrichie (crop, target
 * canonical, sim/spread, listing) pour l'écran de revue manuelle.
 *
 * En `dry_run=false` avec `reviewIds`, seuls les IDs fournis sont auto-
 * acceptés (re-validation du verdict côté serveur — un ID qui a glissé
 * hors `auto_candidate` est silencieusement skip).
 */
export async function runAutoAccept(
  opts: { limit?: number; dryRun?: boolean; reviewIds?: string[]; cohortId?: string | null } = {},
): Promise<AutoAcceptResult> {
  const limit = opts.limit ?? 2000
  const dryRun = opts.dryRun ?? false
  const cohortQs = opts.cohortId ? `&cohort_id=${encodeURIComponent(opts.cohortId)}` : ''
  const qs = `limit=${limit}&dry_run=${dryRun}${cohortQs}`
  const real = await safeFetch<AutoAcceptResult>(
    `/review-queue/auto-accept/run?${qs}`,
    {
      method: 'POST',
      headers: opts.reviewIds ? { 'Content-Type': 'application/json' } : undefined,
      body: opts.reviewIds ? JSON.stringify({ review_ids: opts.reviewIds }) : undefined,
    },
  )
  if (real !== null) return real
  // Mock fallback — backend off : retourne 0 partout, ne ment pas.
  return {
    processed: 0,
    accepted: 0,
    by_category: { auto_candidate: 0, partial: 0, divergent: 0, unknown: 0 },
    dry_run: dryRun,
    preview: [],
  }
}

/** Derniers prix de référence par pièce (un par tier d'état). C4.
 * Phase 2b bonus : endpoint porté sur eurio-api (`/sources/ebay/market-quotes`). */
export async function fetchMarketQuotes(
  eurioIds: string[],
): Promise<Record<string, MarketQuote[]>> {
  if (eurioIds.length === 0) return {}
  const qs = encodeURIComponent(eurioIds.join(','))
  try {
    const real = await eurioApi.get<{ quotes: Record<string, MarketQuote[]> }>(
      `/sources/ebay/market-quotes?eurio_ids=${qs}`,
    )
    return real.quotes
  } catch {
    return {}
  }
}

// ─── Mock data ──────────────────────────────────────────────────────────


// ─── Pêche — ce que la banque propose pour une classe ──────────────────────

export interface DinoCandidatesSummary {
  class_id: string
  /** Étiquettes sous lesquelles la banque indexe la classe (voir bank_classes). */
  bank_class_ids: string[]
  rank: number
  min_spread: number | null
  n_open_single: number
  n_open_lot: number
  /** La meilleure marge disponible dans chaque file — un compte seul ment par
   *  omission : « 4 à l'unité » peut être quatre faux positifs à 0,02. */
  best_spread_single: number | null
  best_spread_lot: number | null
  /** Le pays sur lequel le filtre mord, `null` s'il est levé. */
  country: string | null
  /** Combien de crops le filtre pays MASQUE — un filtre actif par défaut qui
   *  ne dit pas ce qu'il retire ment par omission. */
  n_other_country: number
  /** needs_review SANS ligne de review ouverte : invisibles partout. */
  n_orphans: number
  orphan_asset_ids: string[]
  /** Compté comme le préflight compte `n_ebay` — le même fait, le même nombre. */
  n_training_eligible: number
}

/**
 * Combien de crops la banque rattache à cette classe, et où ils sont.
 *
 * Sert les compteurs du bandeau en mode pêche : ceux du funnel comptent le
 * périmètre PAR CIBLE, qui n'est pas celui qu'on est en train de dérouler.
 * Afficher « 15 à l'unité » au-dessus d'une file qui en sert 137 serait
 * exactement le genre d'écran plausible et faux que cette page combat.
 */
export async function fetchDinoCandidates(
  classId: string,
  opts: {
    rank?: number
    minSpread?: number | null
    /** `false` lève le filtre pays (actif par défaut côté API). */
    countryOnly?: boolean
  } = {},
): Promise<DinoCandidatesSummary | null> {
  const params = new URLSearchParams({ dino_class: classId })
  if (opts.rank) params.set('dino_rank', String(opts.rank))
  if (opts.minSpread != null) params.set('dino_min_spread', String(opts.minSpread))
  if (opts.countryOnly === false) params.set('dino_country_only', 'false')
  try {
    return await fetchEurio<DinoCandidatesSummary>(
      `/review-queue/dino-candidates/summary?${params.toString()}`,
    )
  } catch {
    // Seule exception au « échouer bruyamment » de ce module, et elle est
    // délibérée : c'est un COMPTEUR d'en-tête, pas la file. `null` s'affiche
    // « … », c'est-à-dire « on ne sait pas » — un état honnête. Inventer un
    // nombre serait mentir ; faire tomber l'écran priverait l'opérateur d'une
    // file qui, elle, a très bien répondu.
    return null
  }
}
