/**
 * La moitié ACHETER de `/besoin` — lecture de `GET /scrape-plan/*` (lot 5).
 *
 * ⛔ ROUTE LOURDE, ET C'EST STRUCTUREL. Contrairement à `/class-need` (SQL pur
 * sur le canonique, servi par le VPS), ces deux routes lisent
 * `ml/state/eurio.local.db` — le **budget vrai** (`api_call_log`), qui est de
 * l'état d'observabilité PAR MACHINE et n'existe pas sur le VPS. Elles ne sont
 * montées que sur `:8042`.
 *
 * ⛔ MAIS LA PAGE `/besoin` RESTE NON-`heavy`. Elle s'affiche entièrement en
 * hébergé ; c'est ce bloc-ci, et lui seul, qui se grise (`heavyLocked` dérivé
 * de `useCapabilities`). Savoir ce qui manque ne doit pas dépendre d'un Mac
 * allumé — seul le CHIFFRAGE de l'achat en dépend.
 *
 * ⛔ CE FICHIER NE CALCULE AUCUN FAIT. Comptes par pays, coûts, rendement et
 * quota viennent du back, qui les tient de `shared.class_need` et de
 * `scripts.allocate_ebay_scrape`. Un total réagrégé ici finirait par diverger
 * de celui du back, et personne ne saurait lequel croire (leçon de
 * `useCohortFloor.ts`).
 *
 * ⛔ AUCUN LANCEMENT. Ces deux routes lisent ; l'allocateur est appelé en
 * dry-run et son `execute()` n'est jamais atteint. Le plan porte sa propre
 * commande — la lancer reste un geste de terminal, explicite, qui coûte de
 * l'argent.
 */
import { ref, shallowRef } from 'vue'

import { ML_API } from '@/shared/api/ml-api'

/** La banque lue — même bloc que `/class-need`, même raison : deux lectures à
 *  deux builds différents ne sont pas un désaccord, encore faut-il le prouver. */
export interface ScrapeBuildInfo {
  anchors_kind: string
  encoder_version: string
  build_id: string | null
  built_at: string | null
  n_anchors: number
}

/** Le rendement, REMESURÉ à chaque appel, avec les requêtes qui le produisent. */
export interface YieldMeasure {
  n_listings: number
  n_exemplars: number
  /** Annonces eBay par exemplaire posé. `null` si la banque est vide. */
  listings_per_exemplar: number | null
  query_listings: string
  query_exemplars: string
  query_exemplars_params: string[]
  /** Le repère du 2026-08-22 (7 662 / 1 160 = 6,6), transporté à côté du
   *  chiffre courant — jamais à sa place. */
  reference: number
  reference_listings: number
  reference_exemplars: number
}

/** Le quota du jour, lu là où il est vrai. `db_path` n'est PAS décoratif :
 *  c'est la réserve n°2 de FLOW-ADMIN §Station 1, rendue vérifiable. */
export interface QuotaReading {
  db_path: string
  source: string
  window: string
  period: string
  limit: number
  calls: number
  remaining: number
  safe_budget: number
  safety_factor: number
  /** Faux ⇒ `remaining` vaut 0, jamais le quota plein : c'est le bug B1. */
  readable: boolean
  error: string | null
}

export interface CountryNeed {
  country: string
  n_classes: number
  n_zero: number
  /** Jamais visées par une annonce eBay — celles-là se réparent en scrapant. */
  n_never_targeted: number
  /** Visées, sans résultat — les rescraper ne réglerait rien. */
  n_targeted_no_result: number
  sum_need: number
  n_groups: number
  n_groups_standard: number
  estimated_calls: number
  estimated_listings_palier1: number | null
}

export interface ScrapeTotals {
  n_classes: number
  n_zero: number
  n_never_targeted: number
  n_targeted_no_result: number
  sum_need: number
  n_groups: number
  estimated_calls: number
  estimated_listings_palier1: number | null
}

export interface ScrapePlanSummary {
  build: ScrapeBuildInfo
  totals: ScrapeTotals
  countries: CountryNeed[]
  measured_yield: YieldMeasure
  quota: QuotaReading
  reserves: string[]
  plan_command: string[]
}

export interface AllocationGroup {
  country: string
  year: number | null
  kind: 'standard' | 'commemorative'
  rep_eurio_id: string
  cost: number
  score: number
  need: number
  n_classes_needing: number
  n_zero: number
  n_regression: number
  pending: number
  last_searched: string | null
  classes: string[]
}

export interface Allocation {
  country: string | null
  budget: number
  budget_source: string
  cost: number
  n_groups: number
  groups: AllocationGroup[]
  skipped: { cooldown: string[]; empty_upstream: string[]; over_budget: string[] }
  review_covered_classes: string[]
  commands: string[][]
  quota: QuotaReading
  reserves: string[]
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${ML_API}${path}`)
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = (await res.json()) as { detail?: string }
      if (body?.detail) detail = body.detail
    } catch {
      // Corps non-JSON : le statut suffit, mais on ne le tait pas.
    }
    throw new Error(detail)
  }
  return (await res.json()) as T
}

export function useScrapePlan() {
  const summary = shallowRef<ScrapePlanSummary | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  const plan = shallowRef<Allocation | null>(null)
  const planFor = ref<string | null>(null)
  const planLoading = ref(false)
  const planError = ref<string | null>(null)

  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      summary.value = await getJson<ScrapePlanSummary>('/scrape-plan/summary')
    } catch (e) {
      // Jamais un bloc vide : « rien à acheter » est plausible et faux.
      summary.value = null
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  /** Ouvre le plan de l'allocateur pour un pays. LECTURE — rien ne part. */
  async function loadPlan(country: string | null): Promise<void> {
    planLoading.value = true
    planError.value = null
    planFor.value = country
    try {
      const qs = country ? `?country=${encodeURIComponent(country)}` : ''
      plan.value = await getJson<Allocation>(`/scrape-plan/allocation${qs}`)
    } catch (e) {
      plan.value = null
      planError.value = e instanceof Error ? e.message : String(e)
    } finally {
      planLoading.value = false
    }
  }

  function closePlan(): void {
    plan.value = null
    planFor.value = null
    planError.value = null
  }

  return {
    summary, loading, error, load,
    plan, planFor, planLoading, planError, loadPlan, closePlan,
  }
}

/** La commande d'un plan, telle qu'on la colle dans un terminal. Mise en forme
 *  d'un tableau que le BACK a écrit — aucun argument n'est inventé ici. */
export function shellCommand(argv: string[]): string {
  return argv.map((a) => (/[\s"']/.test(a) ? `'${a.replace(/'/g, "'\\''")}'` : a)).join(' ')
}
