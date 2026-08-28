// Composable — le jeu d'or du cadrage (chantier `juge-du-crop`, L2).
//
// Lit le CANONIQUE (`GET /crop-gold/{version}`), donc **pas `heavy`** : la
// planche doit être regardable depuis le front hébergé, donc depuis un
// téléphone. Le ML local (`:8042`) n'entre nulle part ici.
//
// Les images viennent d'URLs MinIO présignées posées par l'API — c'est ce qui
// rend la galerie visible hors de la machine du ML.

import { ref, shallowRef } from 'vue'

import { eurioApi } from '@/shared/api/eurio-api'

/** L'ellipse d'or, en pixels natifs du raw. `theta_deg` comme `cv2.fitEllipse`. */
export interface EllipseOr {
  cx: number
  cy: number
  a: number
  b: number
  theta_deg: number
}

export interface AnnotationOr extends Partial<EllipseOr> {
  asset_id: string
  gold_version: string
  passe: number
  actor: string
  indecidable: number
  strate_tiree: string | null
  strate_confirmee: string | null
  secondes: number | null
  prefill_modifie: number | null
  editor_version: string
  created_at: string
  updated_at: string
  // joints par l'API
  resolution_status: string
  quality_reason: string | null
  bbox_json: string | null
  detection_method: string | null
  source: string | null
  source_image_id: string
  raw_path: string | null
  raw_url: string
  width: number | null
  height: number | null
}

export interface VersionOr {
  gold_version: string
  created_at: string
  requete_sha256: string | null
  frozen_at: string | null
  snapshot_sha256: string | null
  snapshot_key: string | null
  note: string | null
}

export interface JeuDOr {
  gold_version: string
  version: VersionOr | null
  n: number
  annotations: AnnotationOr[]
}

/** La strate qui compte : celle que le PO a CONFIRMÉE, jamais celle du tirage. */
export function strateRetenue(a: AnnotationOr): string {
  return a.strate_confirmee || a.strate_tiree || '—'
}

export function estAnnotee(a: AnnotationOr): boolean {
  return a.indecidable === 1 || a.a != null
}

export function useGoldCropApi(version = 'v1') {
  const jeu = shallowRef<JeuDOr | null>(null)
  const chargement = ref(false)
  const erreur = ref<string | null>(null)

  async function charger(passe?: number) {
    chargement.value = true
    erreur.value = null
    try {
      const q = passe ? `?passe=${passe}` : ''
      jeu.value = await eurioApi.get<JeuDOr>(`/crop-gold/${version}${q}`)
    } catch (e) {
      // Un jeu d'or vide n'est PAS une erreur : c'est une séance pas encore
      // faite. Les confondre ferait afficher « panne » à quelqu'un qui doit
      // seulement aller annoter.
      erreur.value = e instanceof Error ? e.message : String(e)
      jeu.value = null
    } finally {
      chargement.value = false
    }
  }

  return { jeu, chargement, erreur, charger }
}
