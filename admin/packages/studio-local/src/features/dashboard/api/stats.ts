/**
 * API stats — `/stats/overview` (KPI dashboard). Rapatrié d'admin-vps (R1),
 * rebranché sur `eurioApi` (Bearer PAT en local / cookie OIDC en hébergé).
 *
 * Réponse partielle : chaque section n'est présente que si le user a le scope
 * correspondant (filtrage server-side dans `ml/serving/stats_routes.py`). Le front
 * rend une carte par section présente.
 */
import { eurioApi } from '@/shared/api/eurio-api'

export interface StatsOverview {
  coins?: { total: number; needs_review: number }
  sets?: { total: number; active: number }
  sources?: { total: number; runs_24h: number; last_run_at: string | null }
  review?: { total: number; by_status: Record<string, number> }
  users?: { total: number; active: number; by_role: Record<string, number> }
  tokens?: { mine_total: number; mine_active: number }
}

export const statsApi = {
  overview: () => eurioApi.get<StatsOverview>('/stats/overview'),
}
