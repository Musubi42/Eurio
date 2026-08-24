/**
 * Les deux compteurs personnels — lecture de `GET /me/review-stats`.
 *
 * ⛔ CE FICHIER NE CALCULE AUCUN FAIT, comme `useClassNeed`. Les deux nombres
 * viennent du back, qui les tient de `shared.class_need`. Un total réagrégé
 * côté front finit par diverger, et personne ne sait plus lequel croire.
 *
 * POURQUOI DEUX NOMBRES ET PAS UN
 * -------------------------------
 * Un ami travaille en quarantaine : sa décision attend un arbitrage, et la
 * banque d'images ne bouge qu'au rebuild. Un compteur unique adossé au RÉSULTAT
 * resterait à zéro toute la semaine après une soirée de tri — l'inverse exact de
 * l'effet recherché. L'EFFORT est un fait sur son geste, l'EFFET un fait sur le
 * projet ; les séparer est ce qui permet d'être honnête sans décourager.
 * (`ACCUEIL-AMI.md` §4.)
 *
 * ROUTE LÉGÈRE : SQL pur sur le canonique, servie par le VPS. Rien ici ne
 * dépend d'un Mac allumé.
 */
import { ref, shallowRef } from 'vue'

import { eurioApi } from '@/shared/api/eurio-api'

export interface MeReviewStats {
  /** SON EFFORT — bouge à chaque décision, immédiatement. */
  n_sorted: number
  /** SON EFFET — bouge après arbitrage, puis rebuild. Ne redescend jamais. */
  n_classes_completed: number
  /** Les pièces qu'il a nourries, complétées ou non. */
  n_classes_touched: number
  anchors_kind: string
  encoder_version: string
}

export function useMeReviewStats() {
  const data = shallowRef<MeReviewStats | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function load(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      data.value = await eurioApi.get<MeReviewStats>('/me/review-stats')
    } catch (e) {
      // Ses compteurs sont la partie la moins essentielle de l'écran : leur
      // absence ne doit JAMAIS empêcher la liste de s'afficher. On garde
      // l'erreur pour le dire, et la page continue.
      data.value = null
      error.value = e instanceof Error ? e.message : String(e)
    } finally {
      loading.value = false
    }
  }

  return { data, loading, error, load }
}
