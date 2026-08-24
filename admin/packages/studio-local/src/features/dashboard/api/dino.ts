/**
 * L'écart de la banque d'ancres DINO, et le geste qui le referme.
 *
 * DEUX APIS, ET CE N'EST PAS UN OUBLI
 * ------------------------------------
 * `fetchDinoDrift` tape le CANONIQUE (`eurioApi`) : l'écart est du SQL pur,
 * donc lisible depuis le VPS comme depuis un téléphone, Mac éteint. Savoir ce
 * qui manque n'a pas à dépendre d'une machine allumée.
 *
 * `startDinoRebuild` / `fetchRebuildStatus` tapent l'API ML LOCALE (`:8042`) :
 * rebâtir exige torch, la banque et 6 Go d'images à réencoder. Ces routes
 * n'existent pas sur le VPS — c'est le bouton qui se grise, jamais le chiffre
 * qui disparaît.
 */
import { eurioApi } from '@/shared/api/eurio-api'
import { ML_API } from '@/features/training/composables/useTrainingApi'

export interface DinoDrift {
  anchors_kind: string
  encoder_version: string
  build_id: string | null
  built_at: string | null
  n_classes: number | null
  n_rows: number | null
  /** Crops tranchés par un humain depuis le build servi. */
  n_crops_validated_since: number
  n_classes_touched_since: number
  /** Classes qui n'ont que leur rendu Numista et gagneraient une vraie photo. */
  n_classes_would_gain_anchor: number
  /** Prédictions calculées AVANT le build : elles répondent sur une banque morte. */
  n_predictions_stale: number
  n_assets_without_prediction: number
  is_stale: boolean
}

export interface RebuildStatus {
  status: 'idle' | 'running' | 'done' | 'failed'
  job_id?: string | null
  step?: 'anchors' | 'predictions' | 'done' | null
  anchors_kind?: string | null
  encoder_version?: string | null
  build_id?: string | null
  n_anchors?: number | null
  n_predictions?: number | null
  started_at?: string | null
  finished_at?: string | null
  error?: string | null
}

export function fetchDinoDrift(): Promise<DinoDrift> {
  return eurioApi.get<DinoDrift>('/dino/drift')
}

/** 409 = un rebuild tourne déjà. On le laisse remonter : l'écran doit dire
 *  « déjà en cours », pas relancer en silence un job de vingt minutes. */
export async function startDinoRebuild(): Promise<RebuildStatus> {
  const resp = await fetch(`${ML_API}/dino/rebuild`, { method: 'POST' })
  if (!resp.ok) throw new Error(await resp.text())
  return resp.json() as Promise<RebuildStatus>
}

/** `null` = l'API ML locale ne répond pas (Mac éteint, mode hébergé). Ce n'est
 *  pas une erreur à afficher : la carte se contente alors de son écart. */
export async function fetchRebuildStatus(): Promise<RebuildStatus | null> {
  try {
    const resp = await fetch(`${ML_API}/dino/rebuild/status`)
    if (!resp.ok) return null
    return (await resp.json()) as RebuildStatus
  } catch {
    return null
  }
}
