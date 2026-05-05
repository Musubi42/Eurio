// Verdict auto-validation = combinaison Dino + Texte par critère.
//
// V1 = display-only. Aucune décision n'est écrite en DB sur la base
// de ce verdict (le chunk 8 de docs/sources-refacto/auto-validation/
// vision.md branchera l'auto-accept). Ici on rend visible, critère par
// critère, ce qui converge et ce qui coince — pour que Raphaël puisse
// calibrer les seuils en regardant la review queue colorée.
//
// Seuils canoniques côté ml/foundation/thresholds.py, exposés via le
// champ `verdict_thresholds` de la réponse Dino — pas de constante en
// dur ici.

import type { DinoSuggestionsResponse } from './useDinoSuggestions'
import type { TextSignalsResponse, VsTargetVerdict } from './useTextSignals'

// ─── Verdict global ─────────────────────────────────────────────────────

/**
 * 3 niveaux explicites :
 *  - `auto_candidate` : tous les critères ✓ (Dino + Texte). Ce crop
 *    serait auto-accepté si chunk 8 était actif.
 *  - `partial`        : top1==target côté Dino mais ≥1 critère qui coince
 *    (sim faible, spread tassé, texte partial/absent). Review humaine
 *    facile.
 *  - `divergent`      : top1≠target OU texte contradict. Review humaine
 *    nécessaire (vrais cas).
 *  - `unknown`        : Dino n'a pas tourné OU pas de target — pas de
 *    décision possible.
 */
export type AutoValidateLevel =
  | 'auto_candidate'
  | 'partial'
  | 'divergent'
  | 'unknown'

export interface AutoValidateVerdict {
  level: AutoValidateLevel
  reason: string
}

// ─── Critères Dino (par ligne de DinoVerdict.vue) ───────────────────────

export type CriterionState = 'pass' | 'fail' | 'absent'

export interface DinoCriterion {
  key: 'top1_target' | 'top1_country_sim' | 'country_spread'
  label: string
  state: CriterionState
  value: string  // valeur formatée pour affichage
  hint: string   // explication courte (seuil + valeur réelle)
}

export interface DinoVerdict {
  /** True quand les 3 critères Dino passent (input pour le verdict global). */
  all_pass: boolean
  criteria: DinoCriterion[]
  /** True quand Dino a tourné (sinon on dégrade en "hors scope V1"). */
  has_data: boolean
  out_of_scope: boolean
}

// ─── Compute ────────────────────────────────────────────────────────────

/** Calcule l'état de chaque critère Dino + l'agrégat. */
export function computeDinoVerdict(
  dino: DinoSuggestionsResponse | null,
): DinoVerdict {
  if (!dino) {
    return {
      all_pass: false,
      has_data: false,
      out_of_scope: true,
      criteria: [],
    }
  }

  const target = dino.target_eurio_id
  const top1 = dino.top1_country_eurio_id ?? dino.top1_eurio_id
  const sim = dino.top1_country_sim ?? dino.top1_sim
  const spread = dino.country_spread ?? dino.spread
  const simMin = dino.verdict_thresholds.top1_country_sim_min
  const spreadMin = dino.verdict_thresholds.country_spread_min

  const top1TargetState: CriterionState = !target
    ? 'absent'
    : top1 === target
      ? 'pass'
      : 'fail'

  const simState: CriterionState =
    sim === null || sim === undefined
      ? 'absent'
      : sim >= simMin
        ? 'pass'
        : 'fail'

  const spreadState: CriterionState =
    spread === null || spread === undefined
      ? 'absent'
      : spread >= spreadMin
        ? 'pass'
        : 'fail'

  const criteria: DinoCriterion[] = [
    {
      key: 'top1_target',
      label: 'top1 = cible',
      state: top1TargetState,
      value: top1 ?? '—',
      hint: target
        ? `cible ${target}` + (top1 ? ` · top1 ${top1}` : '')
        : 'pas de target connu',
    },
    {
      key: 'top1_country_sim',
      label: 'sim ≥ seuil',
      state: simState,
      value: sim !== null && sim !== undefined ? sim.toFixed(3) : '—',
      hint: `seuil ${simMin.toFixed(2)}`,
    },
    {
      key: 'country_spread',
      label: 'spread ≥ seuil',
      state: spreadState,
      value:
        spread !== null && spread !== undefined ? spread.toFixed(3) : '—',
      hint: `seuil ${spreadMin.toFixed(2)} (top1 − top2)`,
    },
  ]

  const all_pass = criteria.every((c) => c.state === 'pass')

  return { all_pass, has_data: true, out_of_scope: false, criteria }
}

/** Verdict global combinant Dino + Texte. */
export function computeAutoValidateVerdict(
  dinoVerdict: DinoVerdict,
  textSignals: TextSignalsResponse | null,
): AutoValidateVerdict {
  // 1. Pas de données Dino → on ne peut rien dire.
  if (!dinoVerdict.has_data) {
    return {
      level: 'unknown',
      reason: 'Hors scope V1 (2€ commémo) ou Dino pas encore exécuté',
    }
  }

  const textVerdict: VsTargetVerdict | null =
    textSignals?.vs_target_verdict ?? null

  // 2. Texte contradictoire → divergent net (signal fort).
  if (textVerdict === 'contradict') {
    return {
      level: 'divergent',
      reason: 'Texte du listing contredit la cible',
    }
  }

  // 3. top1 ≠ target côté Dino → divergent.
  const top1TargetCriterion = dinoVerdict.criteria.find(
    (c) => c.key === 'top1_target',
  )
  if (top1TargetCriterion?.state === 'fail') {
    return { level: 'divergent', reason: 'Top1 Dino ≠ cible' }
  }
  if (top1TargetCriterion?.state === 'absent') {
    return { level: 'unknown', reason: 'Pas de target connu' }
  }

  // 4. Tous les critères Dino + texte convergent ou partial → auto_candidate.
  if (dinoVerdict.all_pass && textVerdict === 'convergent') {
    return {
      level: 'auto_candidate',
      reason: 'Dino + texte convergent (auto-acceptable si chunk 8 actif)',
    }
  }

  // 5. Reste : top1 OK mais quelque chose de tiède → partial.
  const failing = dinoVerdict.criteria.filter((c) => c.state === 'fail')
  const reasons: string[] = []
  if (failing.length) {
    reasons.push(failing.map((c) => c.label).join(', '))
  }
  if (textVerdict && textVerdict !== 'convergent') {
    reasons.push(`texte ${textVerdict}`)
  } else if (!textVerdict) {
    reasons.push('texte non comparé')
  }
  return {
    level: 'partial',
    reason: reasons.length ? reasons.join(' · ') : 'Convergence partielle',
  }
}

// ─── Visual helpers ─────────────────────────────────────────────────────

export function levelColor(level: AutoValidateLevel): string {
  switch (level) {
    case 'auto_candidate':
      return 'var(--success)'
    case 'partial':
      return 'var(--gold-600)'
    case 'divergent':
      return 'var(--danger)'
    case 'unknown':
      return 'var(--ink-400)'
  }
}

export function levelLabel(level: AutoValidateLevel): string {
  switch (level) {
    case 'auto_candidate':
      return 'auto-candidat'
    case 'partial':
      return 'partiel'
    case 'divergent':
      return 'divergent'
    case 'unknown':
      return 'inconnu'
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
