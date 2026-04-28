// Sources API composable — types + mock data for the /sources admin page.
//
// V1 ships read-only with mocked data inline. The real backend endpoint
// `GET /sources/status` (cf. docs/sources/backend.md) will replace
// `fetchSourcesStatus` once shipped — the contract is the same.

import { ML_API } from '@/features/training/composables/useTrainingApi'

export type SourceId =
  | 'numista_match'
  | 'numista_enrich'
  | 'numista_images'
  | 'ebay'
  | 'lmdlp'
  | 'mdp'
  | 'bce'
  | 'wikipedia'

export type SourceKind = 'api' | 'scrape'

export type HealthState = 'healthy' | 'warning' | 'error'

export type CliHintKind = 'run' | 'dry-run' | 'list' | 'status' | 'reset'

export interface CliHint {
  kind: CliHintKind
  title: string
  command: string
  description: string
  expected_outcome: string
}

export interface QuotaPerKey {
  slot: number
  key_hash: string
  calls: number
  exhausted: boolean
}

export interface SourceQuota {
  window: 'monthly' | 'daily'
  period: string
  limit: number
  calls: number
  remaining: number
  pct_used: number
  exhausted: boolean
  per_key?: QuotaPerKey[]
}

export interface SourceDelta {
  /** eBay only: number of coins present in both runs (price comparison base). */
  n_stable: number | null
  n_new: number
  n_dropped: number
  /** eBay only: median % change of P50 across the stable sample. */
  delta_p50_median_pct: number | null
  delta_p50_p10_pct: number | null
  delta_p50_p90_pct: number | null
  swing_warning: boolean
}

export interface SourceTemporal {
  last_run_at: string | null
  last_run_kind: string | null
  days_since_last_run: number | null
  expected_cadence_days: number
  overdue: boolean
  delta: SourceDelta | null
}

export interface SourceCoverage {
  enriched: number
  total_target: number
  pct: number
  /** Free-form label for the coverage unit (e.g. "commémos", "années", "pays"). */
  unit: string
}

export interface SourceStatus {
  id: SourceId
  label: string
  /** Sub-label printed below the title (e.g. "API · cadence 30j"). */
  subtitle: string
  kind: SourceKind
  /** Sources sharing the same quota envelope (e.g. all 3 numista_* share 'numista'). */
  quota_group: string | null
  health: HealthState
  health_reason: string | null
  /** null when quota_group is set and quota is shown in a section banner instead. */
  quota: SourceQuota | null
  temporal: SourceTemporal
  coverage: SourceCoverage
  cli_hints: CliHint[]
  /**
   * Marks a source that's registered in the catalogue but has no implementation
   * yet (no scraper/script). The card is rendered greyed-out with a "à venir"
   * badge instead of health/temporal/coverage details.
   */
  is_future?: boolean
  /** Optional note explaining what's needed to bring the source online. */
  future_note?: string
}

export interface SourcesStatusResponse {
  sources: SourceStatus[]
  /** Per-quota-group aggregate, used for shared banners (e.g. Numista). */
  quota_groups: Record<string, SourceQuota>
}

// ─── Real fetch (used once backend endpoint exists) ──────────────────────

export async function fetchSourcesStatus(): Promise<SourcesStatusResponse> {
  const resp = await fetch(`${ML_API}/sources/status`)
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`)
  return resp.json() as Promise<SourcesStatusResponse>
}

// ─── Mock data (V1 — to be replaced by `fetchSourcesStatus` above) ───────

const NUMISTA_PER_KEY: QuotaPerKey[] = [
  { slot: 1, key_hash: 'a3b9c1f24e8d', calls: 1247, exhausted: false },
  { slot: 2, key_hash: 'd8e2f4901abc', calls: 0, exhausted: false },
]

const NUMISTA_QUOTA: SourceQuota = {
  window: 'monthly',
  period: '2026-04',
  limit: 1800,
  calls: 1247,
  remaining: 553,
  pct_used: 69.3,
  exhausted: false,
  per_key: NUMISTA_PER_KEY,
}

const EBAY_QUOTA: SourceQuota = {
  window: 'daily',
  period: '2026-04-26',
  limit: 5000,
  calls: 127,
  remaining: 4873,
  pct_used: 2.5,
  exhausted: false,
}

export const MOCK_SOURCES_STATUS: SourcesStatusResponse = {
  quota_groups: {
    numista: NUMISTA_QUOTA,
  },
  sources: [
    // ─── Numista — 3 cards sharing the monthly quota ─────────────────────
    {
      id: 'numista_match',
      label: 'Numista — Match',
      subtitle: 'API · détection nouvelles pièces',
      kind: 'api',
      quota_group: 'numista',
      quota: null,
      health: 'healthy',
      health_reason: null,
      temporal: {
        last_run_at: '2026-04-23T10:14:02Z',
        last_run_kind: 'batch_match',
        days_since_last_run: 3,
        expected_cadence_days: 14,
        overdue: false,
        delta: {
          n_stable: null,
          n_new: 2,
          n_dropped: 0,
          delta_p50_median_pct: null,
          delta_p50_p10_pct: null,
          delta_p50_p90_pct: null,
          swing_warning: false,
        },
      },
      coverage: { enriched: 1240, total_target: 1240, pct: 100, unit: 'pièces matchées' },
      cli_hints: [
        {
          kind: 'run',
          title: 'Run complet',
          command: 'go-task ml:batch-match',
          description: 'Match toutes les nouvelles pièces du référentiel sans numista_id',
          expected_outcome:
            'Met à jour cross_refs.numista_id sur les coins matchés, écrit ml/state/sources_runs.json',
        },
        {
          kind: 'dry-run',
          title: 'Aperçu candidats',
          command: 'go-task ml:batch-match-dry',
          description: 'Affiche les candidats proposés sans rien écrire',
          expected_outcome: 'Liste eurio_id → numista_id proposés en stdout',
        },
      ],
    },
    {
      id: 'numista_enrich',
      label: 'Numista — Enrichissement',
      subtitle: 'API · métadonnées canoniques',
      kind: 'api',
      quota_group: 'numista',
      quota: null,
      health: 'warning',
      health_reason: 'Pas d’enrichissement depuis 47 jours (cadence cible 30j)',
      temporal: {
        last_run_at: '2026-03-10T09:02:11Z',
        last_run_kind: 'enrich',
        days_since_last_run: 47,
        expected_cadence_days: 30,
        overdue: true,
        delta: null,
      },
      coverage: { enriched: 562, total_target: 1240, pct: 45.3, unit: 'pièces enrichies' },
      cli_hints: [
        {
          kind: 'run',
          title: 'Run complet',
          command: 'go-task ml:enrich-numista',
          description: 'Enrichit les pièces avec numista_id mais sans métadonnées',
          expected_outcome: 'Ajoute theme/designer/atelier dans coins, ~1 call par pièce',
        },
        {
          kind: 'dry-run',
          title: 'Aperçu',
          command: 'go-task ml:enrich-numista-dry',
          description: 'Preview sans écrire',
          expected_outcome: 'Affiche le payload Numista parsé en stdout',
        },
      ],
    },
    {
      id: 'numista_images',
      label: 'Numista — Images',
      subtitle: 'API · obverse/reverse',
      kind: 'api',
      quota_group: 'numista',
      quota: null,
      health: 'healthy',
      health_reason: null,
      temporal: {
        last_run_at: '2026-04-14T16:48:30Z',
        last_run_kind: 'images',
        days_since_last_run: 12,
        expected_cadence_days: 30,
        overdue: false,
        delta: null,
      },
      coverage: { enriched: 558, total_target: 1240, pct: 45.0, unit: 'pièces avec images' },
      cli_hints: [
        {
          kind: 'run',
          title: 'Run complet',
          command: 'go-task ml:batch-images',
          description: 'Télécharge obverse + reverse pour les pièces sans images',
          expected_outcome:
            'Écrit ml/datasets/<numista_id>/{obverse,reverse}.jpg, met à jour coins.images',
        },
        {
          kind: 'dry-run',
          title: 'Aperçu',
          command: 'go-task ml:batch-images-dry',
          description: 'Preview du fetch sans écrire ni télécharger',
          expected_outcome: 'Liste les pièces qui seraient traitées en stdout',
        },
      ],
    },
    // ─── Marché ──────────────────────────────────────────────────────────
    {
      id: 'ebay',
      label: 'eBay Browse',
      subtitle: 'API · prix marché actif',
      kind: 'api',
      quota_group: null,
      quota: EBAY_QUOTA,
      health: 'healthy',
      health_reason: null,
      temporal: {
        last_run_at: '2026-04-26T14:32:11Z',
        last_run_kind: 'scrape',
        days_since_last_run: 0,
        expected_cadence_days: 30,
        overdue: false,
        delta: {
          n_stable: 112,
          n_new: 4,
          n_dropped: 1,
          delta_p50_median_pct: 1.2,
          delta_p50_p10_pct: -8.4,
          delta_p50_p90_pct: 12.7,
          swing_warning: false,
        },
      },
      coverage: { enriched: 116, total_target: 517, pct: 22.4, unit: 'commémos enrichies' },
      cli_hints: [
        {
          kind: 'run',
          title: 'Run complet',
          command: 'go-task ml:scrape-ebay',
          description: 'Enrichit toutes les commémos ciblées (~500 calls)',
          expected_outcome:
            'INSERT dans coin_market_prices + ml/state/price_snapshots/ebay_<period>.json',
        },
        {
          kind: 'run',
          title: 'Échantillon (5 pièces)',
          command: 'go-task ml:scrape-ebay -- --limit 5',
          description: 'Limite le run à 5 pièces (test rapide, écrit en base si --sync-supabase)',
          expected_outcome: 'Snapshot partiel, ~5 calls eBay',
        },
        {
          kind: 'run',
          title: 'Run ciblé pays',
          command: 'go-task ml:scrape-ebay -- --countries=FR,DE,IT,ES,GR',
          description: 'Restreint à un sous-ensemble de pays',
          expected_outcome: 'INSERT partiel, snapshot fusionné dans le mois courant',
        },
      ],
    },
    // ─── Éditorial & référence ───────────────────────────────────────────
    {
      id: 'lmdlp',
      label: 'La Maison de la Pièce',
      subtitle: 'Scrape HTML · cotation FR',
      kind: 'scrape',
      quota_group: null,
      quota: null,
      health: 'healthy',
      health_reason: null,
      temporal: {
        last_run_at: '2026-04-08T11:20:00Z',
        last_run_kind: 'scrape',
        days_since_last_run: 18,
        expected_cadence_days: 90,
        overdue: false,
        delta: {
          n_stable: null,
          n_new: 0,
          n_dropped: 0,
          delta_p50_median_pct: null,
          delta_p50_p10_pct: null,
          delta_p50_p90_pct: null,
          swing_warning: false,
        },
      },
      coverage: { enriched: 487, total_target: 517, pct: 94.2, unit: 'cotations parsées' },
      cli_hints: [
        {
          kind: 'run',
          title: 'Scrape complet',
          command: 'go-task ml:scrape-lmdlp',
          description: 'Re-scrape l’intégralité du catalogue LMDLP',
          expected_outcome: 'Écrit ml/datasets/sources/lmdlp_<date>.json',
        },
      ],
    },
    {
      id: 'mdp',
      label: 'Monnaie de Paris',
      subtitle: 'Scrape HTML · catalogue officiel FR',
      kind: 'scrape',
      quota_group: null,
      quota: null,
      health: 'warning',
      health_reason: 'Overdue : 95 jours depuis le dernier scrape (cadence 90j)',
      temporal: {
        last_run_at: '2026-01-21T08:14:00Z',
        last_run_kind: 'scrape',
        days_since_last_run: 95,
        expected_cadence_days: 90,
        overdue: true,
        delta: null,
      },
      coverage: { enriched: 320, total_target: 517, pct: 61.9, unit: 'fiches parsées' },
      cli_hints: [
        {
          kind: 'run',
          title: 'Scrape complet',
          command: 'go-task ml:scrape-mdp',
          description: 'Re-scrape le catalogue Monnaie de Paris',
          expected_outcome: 'Écrit ml/datasets/sources/mdp_<date>.json',
        },
      ],
    },
    {
      id: 'bce',
      label: 'BCE',
      subtitle: 'Scrape HTML · annonces commémo officielles',
      kind: 'scrape',
      quota_group: null,
      quota: null,
      health: 'healthy',
      health_reason: null,
      temporal: {
        last_run_at: '2026-04-13T07:40:00Z',
        last_run_kind: 'scrape',
        days_since_last_run: 13,
        expected_cadence_days: 90,
        overdue: false,
        delta: {
          n_stable: null,
          n_new: 1,
          n_dropped: 0,
          delta_p50_median_pct: null,
          delta_p50_p10_pct: null,
          delta_p50_p90_pct: null,
          swing_warning: false,
        },
      },
      coverage: { enriched: 22, total_target: 22, pct: 100, unit: 'années couvertes' },
      cli_hints: [
        {
          kind: 'run',
          title: 'Scrape toutes années',
          command: 'go-task ml:scrape-bce',
          description: 'Re-scrape les pages commémo BCE de 2004 à l’année courante',
          expected_outcome: 'Écrit ml/datasets/sources/bce_comm_<year>_<date>.html',
        },
      ],
    },
    {
      id: 'wikipedia',
      label: 'Wikipedia',
      subtitle: 'Scrape HTML · backfill métadonnées par pays',
      kind: 'scrape',
      quota_group: null,
      quota: null,
      health: 'healthy',
      health_reason: null,
      temporal: {
        last_run_at: null,
        last_run_kind: null,
        days_since_last_run: null,
        expected_cadence_days: 365,
        overdue: false,
        delta: null,
      },
      coverage: { enriched: 0, total_target: 21, pct: 0, unit: 'pays' },
      cli_hints: [],
      is_future: true,
      future_note:
        'Source planifiée — pas encore de scraper. À écrire : ml/referential/scrape_wikipedia.py (page catalogue par pays, 21 pays eurozone).',
    },
  ],
}

/** Mock-aware fetcher used by SourcesPage during V1 (no backend yet). */
export async function fetchSourcesStatusMocked(): Promise<SourcesStatusResponse> {
  // Simulate a tiny network delay so loading states render briefly.
  await new Promise((r) => setTimeout(r, 120))
  return MOCK_SOURCES_STATUS
}
