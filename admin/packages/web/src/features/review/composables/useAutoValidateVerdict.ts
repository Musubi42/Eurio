// Verdict auto-validation — DISPLAY ONLY.
//
// La décision (état par critère + niveau global) est calculée côté serveur —
// source unique : ml/training/foundation/auto_validate.py, exposée dans le
// champ `auto_validate_verdict` de la réponse dino-suggestions (C0 du redesign
// auto-validation, docs/work-in-progress/autovalidation-redesign.md). Ce module
// ne contient plus AUCUNE logique de décision : il mappe les états renvoyés par
// l'API vers libellés/couleurs/glyphes, et formate les valeurs Dino brutes pour
// l'affichage.

import type { DinoSuggestionsResponse } from './useDinoSuggestions'

// ─── Types ──────────────────────────────────────────────────────────────

export type AutoValidateLevel =
  | 'auto_candidate'
  | 'partial'
  | 'divergent'
  | 'unknown'

export type CriterionState = 'pass' | 'fail' | 'absent'

export type CriterionKey =
  | 'top1_target'
  | 'top1_country_sim'
  | 'country_spread'

/** Verdict de CONSENSUS (C3) — la décision de routage qui fait foi (= la lane
 *  posée en review_queue). C'est la source du badge depuis le polish front ;
 *  le `level` Dino 4-niveaux n'est plus que du détail par critère. */
export type ConsensusOutcome = 'accept' | 'needs_review' | 'reject'

export type ConsensusLane = 'auto_accept' | 'ccproxy' | 'manual'

/** Ligne affichable d'un critère Dino : état décidé par le serveur +
 *  valeur/seuil formatés pour l'affichage. */
export interface DinoCriterionDisplay {
  key: CriterionKey
  label: string
  state: CriterionState
  value: string // valeur formatée pour affichage
  hint: string // explication courte (seuil + valeur réelle)
}

// ─── Présentation des critères ──────────────────────────────────────────

const CRITERION_LABELS: Record<CriterionKey, string> = {
  top1_target: 'top1 = cible',
  top1_country_sim: 'sim ≥ seuil',
  country_spread: 'spread ≥ seuil',
}

/**
 * Fusionne les états décidés par le serveur (`auto_validate_verdict.criteria`)
 * avec les valeurs Dino brutes de la réponse pour produire les lignes
 * affichables. AUCUNE décision ici — les états viennent de l'API ; on ne fait
 * que sélectionner la valeur à montrer (band country-restricted, fallback
 * global, identique au serveur) et la formater.
 */
export function dinoCriteriaDisplay(
  dino: DinoSuggestionsResponse,
): DinoCriterionDisplay[] {
  const states = dino.auto_validate_verdict?.criteria ?? []
  const stateOf = (key: CriterionKey): CriterionState =>
    states.find((c) => c.key === key)?.state ?? 'absent'

  const target = dino.target_eurio_id
  const top1 = dino.top1_country_eurio_id ?? dino.top1_eurio_id
  const sim = dino.top1_country_sim ?? dino.top1_sim
  const spread = dino.country_spread ?? dino.spread
  const simMin = dino.verdict_thresholds.top1_country_sim_min
  const spreadMin = dino.verdict_thresholds.country_spread_min

  return [
    {
      key: 'top1_target',
      label: CRITERION_LABELS.top1_target,
      state: stateOf('top1_target'),
      value: top1 ?? '—',
      hint: target
        ? `cible ${target}` + (top1 ? ` · top1 ${top1}` : '')
        : 'pas de target connu',
    },
    {
      key: 'top1_country_sim',
      label: CRITERION_LABELS.top1_country_sim,
      state: stateOf('top1_country_sim'),
      value: sim !== null && sim !== undefined ? sim.toFixed(3) : '—',
      hint: `seuil ${simMin.toFixed(2)}`,
    },
    {
      key: 'country_spread',
      label: CRITERION_LABELS.country_spread,
      state: stateOf('country_spread'),
      value:
        spread !== null && spread !== undefined ? spread.toFixed(3) : '—',
      hint: `seuil ${spreadMin.toFixed(2)} (top1 − top2)`,
    },
  ]
}

// ─── Verdict de consensus (badge) ────────────────────────────────────────

export function outcomeLabel(outcome: ConsensusOutcome): string {
  switch (outcome) {
    case 'accept':
      return 'accepté'
    case 'needs_review':
      return 'à revoir'
    case 'reject':
      return 'rejeté'
  }
}

export function outcomeColor(outcome: ConsensusOutcome): string {
  switch (outcome) {
    case 'accept':
      return 'var(--success)'
    case 'needs_review':
      return 'var(--gold-600)'
    case 'reject':
      return 'var(--danger)'
  }
}

/** Libellé court de la lane de routage (audit sous le badge). */
export function laneLabel(lane: ConsensusLane): string {
  switch (lane) {
    case 'auto_accept':
      return 'auto-accept'
    case 'ccproxy':
      return 'ccproxy'
    case 'manual':
      return 'manuel'
  }
}

export function criterionStateColor(state: CriterionState): string {
  switch (state) {
    case 'pass':
      return 'var(--success)'
    case 'fail':
      return 'var(--danger)'
    case 'absent':
      return 'var(--ink-400)'
  }
}

export function criterionStateGlyph(state: CriterionState): string {
  switch (state) {
    case 'pass':
      return '✓'
    case 'fail':
      return '✗'
    case 'absent':
      return '⊘'
  }
}
