// Composable — studio bench du theme-matcher eBay.
//
// Backend : ml/api/bench_routes.py → GET /bench/theme-match. Rejoue le
// gold gelé (196 listings) à travers le pipeline et renvoie, par
// listing, le label humain + les sorties étape par étape, plus les
// métriques agrégées et le contexte des groupes (sœurs).
//
// La maille d'audit est la RECHERCHE eBay (pays · dénomination · année),
// pas le listing isolé : `buildSearchFunnels` regroupe les 196 listings
// en 5 entonnoirs, un par recherche.
//
// Local-only : dégrade proprement si le backend ML est éteint.

import { ML_API } from '@/features/training/composables/useTrainingApi'

export interface BenchMetrics {
  total: number
  n_valid: number
  n_false_discard: number
  false_discard_rate: number | null
  recall_rate: number | null
  n_auto_correct: number
  auto_attribution_rate: number | null
  n_kept_review: number
  review_rate: number | null
  n_auto_total: number
  precision: number | null
  n_auto_wrong: number
  n_junk: number
  n_correct_discard: number
  n_false_keep: number
  false_keep_rate: number | null
  lot_outcomes: Record<string, number>
  n_accept_rej: number
  n_matcher_rej: number
}

export interface BenchAccept {
  ok: boolean
  reason: string
}

export interface BenchMatcher {
  verdict: string // single | lot | ambiguous | no_match
  matched: string[]
  contradictions: string[]
}

export interface BenchListing {
  listing_id: string
  title: string
  marketplace: string | null
  group_year: number
  price: number | null
  currency: string | null
  bucket: string | null
  note: string | null
  verdict: string // label humain : coin:<eurio_id> | lot | not-a-coin | wrong-scope | ambiguous
  accept: BenchAccept
  matcher: BenchMatcher | null // null ssi accept a rejeté
  outcome: string // FALSE_DISCARD | auto_ok | auto_WRONG | review | junk_discarded | FALSE_KEEP | lot→…
  agreement: boolean
  image_url: string | null // photo de l'annonce eBay (CDN public)
}

export interface BenchGroupCoin {
  eurio_id: string
  theme: string | null
  i18n: Record<string, string>
  aliases: string[]
  obverse_url: string | null // face de la pièce (URL publique)
}

export interface BenchReplay {
  metrics: BenchMetrics
  listings: BenchListing[]
  groups: Record<string, BenchGroupCoin[]>
}

export class BenchApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'BenchApiError'
  }
}

// ── Run audit live (P10-F, 2026-05-26) ────────────────────────────────────
//
// Backend : GET /bench/runs/{run_id} (structure groups) + /listings (drill).
// Layout mime /bench studio mais sans gold humain : pas de scoring, juste
// l'entonnoir route_decision/route_reason persisté par le pipeline.

export interface BenchRunListing {
  source_image_id: string
  listing_title: string | null
  listing_year: number | null
  listing_price: number | null
  listing_currency: string | null
  target_eurio_id: string | null
  route_decision: string | null
  route_reason: string | null
  is_lot_suspected: boolean
  image_url: string | null
  source_url: string | null
  marketplace: string | null
}

export interface BenchRunGroupDrop {
  node_id: string
  stage: 'matcher' | 'router' | string
  label: string
  reason: string | null
  route_decision: string | null
  count: number
}

export interface BenchRunGroup {
  group_id: string
  country: string
  year: number
  denomination: number
  target_eurio_ids: string[]
  total_listings: number
  n_unmatched: number
  n_pending: number
  n_review_single: number
  n_review_lot: number
  n_auto: number
  n_quotes: number
  drops: BenchRunGroupDrop[]
}

export interface BenchRunSummary {
  run_id: string
  source: string
  started_at: string | null
  status: string
  total_listings: number
  total_unmatched: number
  total_pending: number
  total_review_single: number
  total_review_lot: number
  total_auto: number
  total_quotes: number
  n_groups: number
}

export interface BenchRunCoinContext {
  eurio_id: string
  display_name: string | null
  is_commemorative: boolean
  country: string | null
  year: number | null
  theme: string | null
  obverse_url: string | null
  i18n: Record<string, string>
  topics: { source: string; lang: string; topic: string }[]
  aliases: string[]
}

export interface BenchRunResponse {
  summary: BenchRunSummary
  groups: BenchRunGroup[]
  coins: Record<string, BenchRunCoinContext>
}

export interface BenchRunListingsResponse {
  listings: BenchRunListing[]
  listings_total: number
}

export interface BenchRunListingsQuery {
  country?: string | null
  year?: number | null
  eurio_id?: string | null
  route_decision?: string | null
  route_reason?: string | null
  unmatched_only?: boolean
  limit?: number
  offset?: number
}

export async function fetchBenchRun(runId: string): Promise<BenchRunResponse> {
  const url = `${ML_API}/bench/runs/${encodeURIComponent(runId)}`
  let resp: Response
  try {
    resp = await fetch(url)
  } catch {
    throw new BenchApiError(0, 'Backend ML injoignable — lance `go-task ml:api`.')
  }
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      if (body && typeof body === 'object' && 'detail' in body) {
        detail = String((body as { detail: unknown }).detail)
      }
    } catch { /* ignore */ }
    throw new BenchApiError(resp.status, detail)
  }
  return resp.json() as Promise<BenchRunResponse>
}

export async function fetchBenchRunListings(
  runId: string, q: BenchRunListingsQuery = {},
): Promise<BenchRunListingsResponse> {
  const params = new URLSearchParams()
  if (q.country) params.set('country', q.country)
  if (q.year != null) params.set('year', String(q.year))
  if (q.eurio_id) params.set('eurio_id', q.eurio_id)
  if (q.route_decision) params.set('route_decision', q.route_decision)
  if (q.route_reason) params.set('route_reason', q.route_reason)
  if (q.unmatched_only) params.set('unmatched_only', 'true')
  if (q.limit != null) params.set('limit', String(q.limit))
  if (q.offset != null) params.set('offset', String(q.offset))
  const qs = params.toString()
  const url = `${ML_API}/bench/runs/${encodeURIComponent(runId)}/listings${qs ? `?${qs}` : ''}`
  let resp: Response
  try {
    resp = await fetch(url)
  } catch {
    throw new BenchApiError(0, 'Backend ML injoignable.')
  }
  if (!resp.ok) {
    throw new BenchApiError(resp.status, `HTTP ${resp.status}`)
  }
  return resp.json() as Promise<BenchRunListingsResponse>
}


export async function fetchThemeMatchBench(): Promise<BenchReplay> {
  let resp: Response
  try {
    resp = await fetch(`${ML_API}/bench/theme-match`)
  } catch {
    throw new BenchApiError(0, 'Backend ML injoignable — lance `go-task ml:api`.')
  }
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      if (body && typeof body === 'object' && 'detail' in body) {
        detail = String((body as { detail: unknown }).detail)
      }
    } catch {
      // ignore
    }
    throw new BenchApiError(resp.status, detail)
  }
  return resp.json() as Promise<BenchReplay>
}

// ── Maille « recherche eBay » : l'entonnoir ────────────────────────────────

// Un groupe de listings tombés au même motif, à une étape du filtre.
export interface FunnelDrop {
  key: string // motif machine (noise_title, denomination, …)
  label: string // libellé lisible
  listings: BenchListing[]
  wrong: number // combien jetés à tort (label humain = pièce valide)
}

// Une branche d'attribution finale : auto vers une pièce, ou review.
export interface FunnelBranch {
  id: string // 'branch:<eurioId>' | 'branch:review'
  kind: 'auto' | 'review'
  eurioId: string | null
  label: string
  listings: BenchListing[]
  wrong: number // auto erronées, ou junk en review
}

// Un nœud sélectionnable de l'entonnoir → un jeu d'annonces à afficher.
export interface FunnelNode {
  id: string
  label: string
  listings: BenchListing[]
}

export interface SearchFunnel {
  year: number
  country: string
  denomination: string
  coins: BenchGroupCoin[]
  listings: BenchListing[]
  total: number
  // Étape 1 — accept_listing
  acceptDrops: FunnelDrop[]
  rejectedAccept: BenchListing[]
  accepted: BenchListing[]
  // Étape 2 — theme-matcher + garde-fou de contradiction
  matcherDrops: FunnelDrop[]
  contradicted: BenchListing[]
  retained: BenchListing[]
  // Étape 3 — attribution
  branches: FunnelBranch[]
  // Synthèse
  nDisagreements: number
}

const ACCEPT_LABELS: Record<string, string> = {
  noise_title: 'titre hors-scope',
  year_mismatch: 'millésime ≠ recherche',
  non_eur: 'devise ≠ EUR',
  no_price: 'pas de prix',
  below_face: 'prix trop bas',
  above_extreme: 'prix extrême',
}

const AXIS_LABELS: Record<string, string> = {
  country: 'pays',
  year: 'année',
  denomination: 'dénomination',
}

function isValid(l: BenchListing): boolean {
  // Une pièce « valide » selon le label humain = attribuable ou ambiguë.
  return l.verdict.startsWith('coin:') || l.verdict === 'ambiguous'
}

function groupDrops(
  listings: BenchListing[],
  keyOf: (l: BenchListing) => string,
  labelOf: (key: string) => string,
): FunnelDrop[] {
  const map = new Map<string, BenchListing[]>()
  for (const l of listings) {
    const k = keyOf(l)
    const arr = map.get(k) ?? []
    arr.push(l)
    map.set(k, arr)
  }
  return [...map.entries()]
    .map(([key, ls]) => ({
      key,
      label: labelOf(key),
      listings: ls,
      wrong: ls.filter(isValid).length,
    }))
    .sort((a, b) => b.listings.length - a.listings.length)
}

// Découpe les 196 listings du gold en un entonnoir par recherche eBay.
export function buildSearchFunnels(replay: BenchReplay): SearchFunnel[] {
  const byYear = new Map<number, BenchListing[]>()
  for (const l of replay.listings) {
    const arr = byYear.get(l.group_year) ?? []
    arr.push(l)
    byYear.set(l.group_year, arr)
  }

  return [...byYear.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([year, listings]) => {
      const coins = replay.groups[String(year)] ?? []
      const country = (coins[0]?.eurio_id.slice(0, 2) ?? 'be').toUpperCase()

      const rejectedAccept = listings.filter(l => !l.accept.ok)
      const accepted = listings.filter(l => l.accept.ok)
      const contradicted = accepted.filter(l => l.matcher?.verdict === 'no_match')
      const retained = accepted.filter(l => l.matcher?.verdict !== 'no_match')

      // Étape 3 — une branche auto par pièce + une branche review.
      const branches: FunnelBranch[] = []
      for (const coin of coins) {
        const ls = retained.filter(
          l => l.matcher?.verdict === 'single'
            && l.matcher.matched[0] === coin.eurio_id,
        )
        branches.push({
          id: `branch:${coin.eurio_id}`,
          kind: 'auto',
          eurioId: coin.eurio_id,
          label: shortEurio(coin.eurio_id),
          listings: ls,
          wrong: ls.filter(l => l.outcome === 'auto_WRONG').length,
        })
      }
      const review = retained.filter(
        l => l.matcher?.verdict === 'ambiguous' || l.matcher?.verdict === 'lot',
      )
      branches.push({
        id: 'branch:review',
        kind: 'review',
        eurioId: null,
        label: 'Review',
        listings: review,
        wrong: review.filter(l => l.outcome === 'FALSE_KEEP').length,
      })

      return {
        year,
        country,
        denomination: '2 €',
        coins,
        listings,
        total: listings.length,
        acceptDrops: groupDrops(
          rejectedAccept,
          l => l.accept.reason,
          k => ACCEPT_LABELS[k] ?? k,
        ),
        rejectedAccept,
        accepted,
        matcherDrops: groupDrops(
          contradicted,
          l => l.matcher?.contradictions[0] ?? 'inconnu',
          k => AXIS_LABELS[k] ?? k,
        ),
        contradicted,
        retained,
        branches,
        nDisagreements: listings.filter(l => !l.agreement).length,
      }
    })
}

// Résout un nœud sélectionné de l'entonnoir → les annonces à afficher.
// `id` stable entre recherches (changer d'année garde le nœud courant).
export function resolveFunnelNode(
  search: SearchFunnel,
  id: string | null,
): FunnelNode | null {
  if (id == null) return null
  switch (id) {
    case 'raw':
      return { id, label: 'Annonces brutes', listings: search.listings }
    case 'accept-drop':
      return { id, label: 'Rejetées — filtre 1', listings: search.rejectedAccept }
    case 'accepted':
      return { id, label: 'Passé le filtre 1', listings: search.accepted }
    case 'matcher-drop':
      return { id, label: 'Contredites — filtre 2', listings: search.contradicted }
    case 'retained':
      return { id, label: 'Retenu pour attribution', listings: search.retained }
    default: {
      const b = search.branches.find(br => br.id === id)
      return b
        ? { id, label: b.kind === 'auto' ? `Auto → ${b.label}` : 'Review', listings: b.listings }
        : null
    }
  }
}

// URL de l'annonce eBay d'origine, reconstruite depuis l'item_id
// (`v1|<numericId>|<var>`). ebay.com/itm/<id> redirige vers le bon TLD.
export function ebayItemUrl(listingId: string): string | null {
  const numericId = listingId.split('|')[1]
  return numericId ? `https://www.ebay.com/itm/${numericId}` : null
}

// ── Présentation ───────────────────────────────────────────────────────────

// `be-2018-2eur-50-years-…esro-2b` → `…esro-2b` (sans le préfixe pays/an).
export function shortEurio(id: string): string {
  return id.replace(/^[a-z]{2}-\d{4}-2eur-/, '')
}

export function verdictLabel(verdict: string): string {
  if (verdict.startsWith('coin:')) return shortEurio(verdict.slice(5))
  const labels: Record<string, string> = {
    lot: 'lot',
    'not-a-coin': 'pas une pièce',
    'wrong-scope': 'hors-scope',
    ambiguous: 'ambiguë',
  }
  return labels[verdict] ?? verdict
}
