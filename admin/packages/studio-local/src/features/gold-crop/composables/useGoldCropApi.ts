// Composable — le jeu d'or du cadrage (chantier `juge-du-crop`, L2).
//
// Lit le CANONIQUE (`GET /crop-gold/{version}`), donc **pas `heavy`** : la
// planche doit être regardable depuis le front hébergé, donc depuis un
// téléphone. Le ML local (`:8042`) n'entre nulle part ici.
//
// Les images viennent d'URLs MinIO présignées posées par l'API — c'est ce qui
// rend la galerie visible hors de la machine du ML.

import { ref, shallowRef } from 'vue'

import {
  EurioApiError,
  EurioApiTimeout,
  MissingPatError,
  eurioApi,
} from '@/shared/api/eurio-api'

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

/* ══ La séance d'annotation (D12 : elle passe dans le front hébergé) ══════════
 *
 * Portage un-pour-un du geste de l'outil local
 * (`ml/bench/gold_crop/annotate/index.html` + `serve.py`). Les comportements
 * ci-dessous ont chacun été payés une fois ; ils ne s'inventent pas à nouveau.
 */

/** Le cercle de repli quand `measure_tilt` n'a rien su proposer. */
export interface IndiceOr {
  cx: number
  cy: number
  r: number
}

/** Ce que l'API propose comme départ. `theta_deg` — convention `cv2.fitEllipse`. */
export interface PrefillOr {
  cx: number
  cy: number
  a: number
  b: number
  theta_deg: number
}

/** Une image du tirage, telle que servie par `GET /crop-gold/{v}/tirage`. */
export interface ImageTirage {
  asset_id: string
  role: 'tirage' | 'reserve'
  rn: number
  strate_tiree: string
  width: number
  height: number
  hint: IndiceOr
  prefill: PrefillOr | null
  prefill_reason: string | null
  source: string | null
  source_image_id: string
  raw_url: string
}

export interface TirageOr {
  gold_version: string
  n: number
  images: ImageTirage[]
}

/**
 * L'ellipse en cours d'édition, en pixels natifs du raw.
 *
 * ⚠️ Le champ s'appelle `theta` ICI et à l'ENVOI, et `theta_deg` en lecture
 * (`AnnotationOr`, `PrefillOr`). Ce n'est pas une coquille : c'est le contrat
 * de l'API, et le confondre écrit une ellipse sans angle — donc un `theta` nul
 * côté serveur, donc une ellipse fausse que rien n'affiche comme fausse.
 */
export interface EllipseEdition {
  cx: number
  cy: number
  a: number
  b: number
  theta: number
}

/** Le corps d'une annotation envoyée au canonique. */
export interface AnnotationEnvoi {
  asset_id: string
  ellipse: EllipseEdition | null
  indecidable: boolean
  passe: number
  strate_tiree: string | null
  strate_confirmee: string | null
  secondes: number | null
  prefill_modifie: boolean
  editor_version: string
}

/**
 * L'instrument qui écrit. L'outil local n'envoie rien et laisse le serveur
 * poser son propre défaut : les deux mains doivent rester distinguables dans la
 * table, sans quoi une divergence de tracé se lira comme du bruit d'annotateur
 * (même leçon que D5).
 */
export const EDITEUR_WEB = 'gold_web_v1'

/** Le tirage fait 60 images, 15 par strate — c'est sa définition, pas un total. */
export const TAILLE_TIRAGE = 60

export const STRATES = ['S1_facile', 'S2_capsule', 'S3_multi', 'S4_oblique'] as const

/** L'état local d'une image pendant la séance. */
export interface EtatAnnotation {
  asset_id: string
  strate_tiree: string | null
  strate_confirmee: string | null
  indecidable: boolean
  secondes: number
  ellipse: EllipseEdition | null
  prefill_modifie: boolean
}

/**
 * `a ≥ b`, toujours. Une ellipse dont le petit axe dépasse le grand est la même
 * ellipse tournée d'un quart de tour — mais `theta` cesse alors d'être l'angle
 * du GRAND axe, et tout ce qui lit l'or (le juge, la planche) suppose qu'il
 * l'est. On échange les axes et on ajoute 90°, puis on ramène l'angle dans
 * [0, 180) : une ellipse est invariante par demi-tour, `cv2.fitEllipse` rend
 * son angle dans cet intervalle, et deux tracés identiques doivent produire
 * deux nombres identiques (sinon `prefill_modifie` ment).
 */
export function normaliserEllipse(e: EllipseEdition): EllipseEdition {
  let { a, b, theta } = e
  if (b > a) {
    ;[a, b] = [b, a]
    theta += 90
  }
  theta = ((theta % 180) + 180) % 180
  return { cx: e.cx, cy: e.cy, a, b, theta }
}

/** Le point de départ : le pré-remplissage s'il existe, sinon le cercle indice. */
export function ellipseDepuisPrefill(image: ImageTirage): EllipseEdition {
  const p = image.prefill
  if (p) {
    return normaliserEllipse({ cx: p.cx, cy: p.cy, a: p.a, b: p.b, theta: p.theta_deg })
  }
  const h = image.hint
  return { cx: h.cx, cy: h.cy, a: h.r, b: h.r, theta: 0 }
}

/** Deux ellipses au pixel (et au dixième de degré) près. */
export function memeEllipse(x: EllipseEdition, y: EllipseEdition): boolean {
  const p = (u: number, v: number) => Math.abs(u - v) < 1e-6
  return p(x.cx, y.cx) && p(x.cy, y.cy) && p(x.a, y.a) && p(x.b, y.b) && p(x.theta, y.theta)
}

/**
 * L'image sur laquelle reprendre : la première qui n'est ni tracée ni déclarée
 * indécidable.
 *
 * ⚠️ « Faite » = validée ou indécidable — surtout PAS « a une entrée ».
 * Confirmer une strate crée une entrée ; reprendre après elle sauterait une
 * image en silence. Vécu le 2026-08-28 : l'image 1 portait `strate_confirmee`
 * sans ellipse, la reprise ouvrait directement la 2.
 */
export function premiereAFaire(
  images: ImageTirage[],
  etats: Record<string, EtatAnnotation>,
): number {
  const i = images.findIndex((im) => {
    const e = etats[im.asset_id]
    return !(e && (e.ellipse || e.indecidable))
  })
  return i < 0 ? 0 : i
}

/** Une annotation déjà au canonique, ramenée dans l'état local de la séance. */
export function etatDepuisAnnotation(a: AnnotationOr): EtatAnnotation {
  return {
    asset_id: a.asset_id,
    strate_tiree: a.strate_tiree,
    strate_confirmee: a.strate_confirmee,
    indecidable: a.indecidable === 1,
    secondes: a.secondes ?? 0,
    ellipse:
      a.a != null && a.b != null && a.cx != null && a.cy != null
        ? { cx: a.cx, cy: a.cy, a: a.a, b: a.b, theta: a.theta_deg ?? 0 }
        : null,
    prefill_modifie: a.prefill_modifie === 1,
  }
}

/**
 * Un code brut n'apprend rien à qui annote. Ces cas-là ont chacun une cause
 * connue et une conduite à tenir ; les autres passent en clair.
 */
export function expliquerEchec(e: unknown): string {
  if (e instanceof EurioApiTimeout) return "l'API n'a pas répondu — l'annotation reste à l'écran, retente"
  if (e instanceof MissingPatError) return 'aucun jeton : renseigne VITE_EURIO_PAT dans .env.local'
  if (e instanceof EurioApiError) {
    const detail = typeof e.body === 'string' ? e.body : e.message
    if (detail.includes('1010')) return 'Cloudflare a refusé le client — recharge la page'
    if (e.status === 409) return "cette version d'or est GELÉE — plus une écriture n'entre"
    if (e.status === 401 || e.status === 403) return 'jeton refusé — reconnecte-toi'
    return `${e.status} · ${detail.slice(0, 80)}`
  }
  return e instanceof Error ? e.message.slice(0, 90) : String(e).slice(0, 90)
}

/** Ce que rend le canonique après un `PUT` — `n` = annotations retenues. */
export interface ReponseEcriture {
  n?: number
}

/**
 * Le versant écriture de la séance. Séparé de `useGoldCropApi` parce que la
 * planche (lecture seule) n'a aucune raison d'embarquer de quoi écrire.
 */
export function useGoldCropSeance(version = 'v1') {
  /** Le tirage : les 60 images, ordre `tirage` d'abord puis strate et rang. */
  async function chargerTirage(role: 'tirage' | 'reserve' = 'tirage'): Promise<TirageOr> {
    return eurioApi.get<TirageOr>(`/crop-gold/${version}/tirage?role=${role}`)
  }

  /** L'or déjà écrit, pour une passe donnée. */
  async function chargerJeu(passe: number): Promise<JeuDOr> {
    return eurioApi.get<JeuDOr>(`/crop-gold/${version}?passe=${passe}`)
  }

  /**
   * Une annotation, une écriture. La route est un upsert idempotent : envoyer
   * l'image courante seule suffit, et une image renvoyée deux fois ne compte
   * qu'une. On n'attend pas la fin de la séance — 40 minutes perdues sur un
   * onglet fermé, on ne les refait pas.
   */
  async function envoyerAnnotation(a: AnnotationEnvoi): Promise<ReponseEcriture> {
    return eurioApi.put<ReponseEcriture>(`/crop-gold/${version}/annotations`, {
      annotations: [{ ...a, ellipse: a.ellipse ? normaliserEllipse(a.ellipse) : null }],
      requete_sha256: null,
    })
  }

  return { chargerTirage, chargerJeu, envoyerAnnotation }
}
