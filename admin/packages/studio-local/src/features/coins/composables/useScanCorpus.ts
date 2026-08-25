/**
 * Corpus d'évaluation — les photos qui JUGENT une classe (`/scan-corpus/*`).
 *
 * Ces captures ne sont ni des canoniques Numista, ni des crops
 * d'enrichissement : ce sont les photos device sur lesquelles un modèle est
 * NOTÉ. La fiche pièce montrait déjà les deux premières familles ; celle-ci
 * manquait, donc rien à l'écran ne disait sur quoi le chiffre de r@1 était
 * calculé.
 *
 * ⚠️ **Un seul pool.** Décision PO du 2026-08-25 : « une photo de val pour une
 * classe, c'est une photo ». Les captures sont rendues MÉLANGÉES.
 * `bundle_source` reste lisible en détail sur la vignette — c'est de la
 * PROVENANCE (d'où vient la photo), jamais un axe de lecture ni un filtre mis
 * en avant. Ne pas le rétablir en regroupement.
 *
 * ⚠️ **La maille.** Pour une pièce courante, les photos appartiennent au
 * GROUPE DE DESSIN : `scope === 'design_group'` signifie qu'au moins une
 * capture montre une autre pièce du groupe. L'écran doit le dire (`scope_note`)
 * — sinon il montre les photos d'une pièce sous le nom d'une autre.
 *
 * ⛔ Lourd : ces routes vivent sur l'API ML locale `:8042`. La SECTION se gate
 * elle-même (`v-if="HAS_LOCAL_ML_API"`) ; on ne marque PAS la route
 * `coins/:eurio_id` en `meta.heavy`, ça griserait toute la fiche pièce en
 * hébergé.
 */
import { ML_API } from '@/shared/api/ml-api'
import { HAS_LOCAL_ML_API } from '@/shared/config/deploy-target'

/** `null` = personne n'a encore jugé la photo. */
export type EvalDecision = 'keep' | 'exclude' | null

export interface ScanCorpusDecision {
  id: number
  capture_id: string
  kind: 'remap' | 'eval_decision'
  old_value: string | null
  new_value: string | null
  reason: string | null
  decided_by: string | null
  decided_at: string
}

export interface ScanCapture {
  capture_id: string
  eurio_id: string
  /** Faux = la photo montre une AUTRE pièce du même groupe de dessin. */
  is_exact_match: boolean
  condition: string
  /** Provenance seule (`device_pull_20260429`…), pas un axe d'analyse. */
  bundle_source: string | null
  captured_at: string
  device_model: string | null
  raw_w: number | null
  raw_h: number | null
  crop_w: number | null
  crop_h: number | null
  /** Quatre normaliseurs cohabitent dans les crops stockés — le dire évite de
   *  prendre une différence de code pour une différence de prise de vue. */
  normalize_method: string | null
  /** FAIT : label juste à la CLASSE, faux à la PIÈCE. Pas un avis. */
  class_level_only: boolean
  /** AVIS humain sur l'exploitabilité de la photo comme juge. */
  eval_decision: EvalDecision
  eval_decision_by: string | null
  eval_decision_at: string | null
  eval_decision_reason: string | null
  notes: string | null
  crop_url: string
  raw_url: string
  decisions: ScanCorpusDecision[]
}

export interface ScanCorpusResponse {
  eurio_id: string
  class_id: string
  class_kind: 'eurio_id' | 'design_group_id'
  class_eurio_ids: string[]
  /** `coin` = toutes les photos sont celles de CETTE pièce. */
  scope: 'coin' | 'design_group'
  scope_note: string
  referential_available: boolean
  n_captures: number
  n_exact_match: number
  n_class_level_only: number
  n_excluded: number
  n_kept: number
  n_undecided: number
  captures: ScanCapture[]
}

const EMPTY: ScanCorpusResponse = {
  eurio_id: '',
  class_id: '',
  class_kind: 'eurio_id',
  class_eurio_ids: [],
  scope: 'coin',
  scope_note: '',
  referential_available: false,
  n_captures: 0,
  n_exact_match: 0,
  n_class_level_only: 0,
  n_excluded: 0,
  n_kept: 0,
  n_undecided: 0,
  captures: [],
}

/** Les URL rendues par l'API sont relatives à `:8042` — on les promeut ici,
 *  une seule fois, plutôt que dans le template (motif `useCoinAssets`). */
function promote(capture: ScanCapture): ScanCapture {
  return {
    ...capture,
    crop_url: `${ML_API}${capture.crop_url}`,
    raw_url: `${ML_API}${capture.raw_url}`,
  }
}

export async function fetchEvalCaptures(eurioId: string): Promise<ScanCorpusResponse> {
  if (!HAS_LOCAL_ML_API) return { ...EMPTY, eurio_id: eurioId }
  const resp = await fetch(
    `${ML_API}/scan-corpus/captures/${encodeURIComponent(eurioId)}`,
  )
  if (resp.status === 404) {
    // Pièce inconnue du référentiel : une section vide ferait croire « pas de
    // photos » là où le slug lui-même est mort.
    throw new Error(`Pièce inconnue du référentiel : ${eurioId}`)
  }
  if (!resp.ok) throw new Error(`fetchEvalCaptures: HTTP ${resp.status}`)
  const body = (await resp.json()) as ScanCorpusResponse
  return { ...body, captures: body.captures.map(promote) }
}

async function post(url: string, payload: unknown): Promise<ScanCapture> {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = (await resp.json()) as { detail?: string }
      if (body?.detail) detail = body.detail
    } catch {
      /* réponse non-JSON : le code HTTP reste le message */
    }
    throw new Error(detail)
  }
  const body = (await resp.json()) as { capture: ScanCapture }
  return promote(body.capture)
}

/** Réattribue une capture à une autre pièce. Le back refuse un `eurio_id`
 *  absent du référentiel (400) et journalise l'ancien → le nouveau. */
export function remapCapture(
  captureId: string,
  eurioId: string,
  opts: { classLevelOnly?: boolean | null; reason?: string } = {},
): Promise<ScanCapture> {
  return post(`${ML_API}/scan-corpus/captures/${encodeURIComponent(captureId)}/remap`, {
    eurio_id: eurioId,
    class_level_only: opts.classLevelOnly ?? null,
    reason: opts.reason ?? null,
  })
}

/** Garde / écarte une photo pour l'évaluation. `null` ré-ouvre l'avis.
 *  ⚠️ Le juge (`replay_corpus`) ne filtre pas encore sur cet avis — reste-à-faire. */
export function setEvalDecision(
  captureId: string,
  decision: EvalDecision,
  reason?: string,
): Promise<ScanCapture> {
  return post(
    `${ML_API}/scan-corpus/captures/${encodeURIComponent(captureId)}/eval-decision`,
    { decision, reason: reason ?? null },
  )
}
