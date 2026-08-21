// Dérouler une file de lots UN PAR UN — la mécanique, sans l'écran.
//
// Deux hôtes s'en servent : le bandeau de la page cohorte et la page pêche.
// Ils affichent des choses différentes mais déroulent la même file, et
// dupliquer cette soixantaine de lignes aurait garanti qu'elles divergent —
// l'une saurait rouvrir le premier lot après un changement de périmètre,
// l'autre pas, et personne ne l'aurait vu avant d'y avoir perdu une session.
//
// Le lot courant vit dans l'URL (`?lot=`), comme le reste du périmètre :
// rechargement et retour arrière retombent au même endroit.
//
// ⚠️ Le périmètre voyage jusqu'à `GET /review-queue/lots/{key}` et détermine
// `prev/next_listing_key`. Sans lui, la nav déroule la file lot GLOBALE (5413
// items) et sort de la classe au premier « suivant ».

import { computed, ref, watch, type MaybeRefOrGetter, toValue } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { fetchLots } from './useLotReview'
import { queryParam } from './useQueryScope'

export interface LotChain {
  /** Le lot ouvert, ou `null` (pas encore ouvert / file épuisée). */
  heldLot: import('vue').ComputedRef<string | null>
  /** Vrai pendant la recherche du premier lot du périmètre. */
  loading: import('vue').Ref<boolean>
  /** Vrai quand le périmètre ne contient plus aucun lot ouvert. */
  exhausted: import('vue').Ref<boolean>
  /** À brancher sur `@navigate` de LotDetailView. */
  goto: (listingKey: string) => void
  /** À brancher sur `@exhausted` de LotDetailView. */
  finish: () => void
}

/**
 * @param scope   périmètre passé à l'API (`dino_class`/`dino_rank`,
 *                `design_group`, `target_eurio_id`, `cohort_id`). Un périmètre
 *                VIDE désactive l'ouverture automatique : sans lui, on
 *                ouvrirait un lot au hasard de la file globale.
 * @param active  vrai quand l'hôte est réellement en mode lot.
 */
export function useLotChain(
  scope: MaybeRefOrGetter<Record<string, string>>,
  active: MaybeRefOrGetter<boolean>,
): LotChain {
  const route = useRoute()
  const router = useRouter()

  const heldLot = computed(() => queryParam(route, 'lot'))
  const loading = ref(false)
  const exhausted = ref(false)

  /** Traduit le périmètre-URL en arguments de `fetchLots`. */
  function scopeArgs() {
    const sc = toValue(scope)
    return {
      dinoClass: sc.dino_class ?? null,
      dinoRank: sc.dino_rank ? Number(sc.dino_rank) : null,
      designGroup: sc.design_group ?? null,
      targetEurioId: sc.target_eurio_id ?? null,
      cohortId: sc.cohort_id ?? null,
      runIds: sc.run_id ? sc.run_id.split(',').filter(Boolean) : null,
      needOnly: sc.need_only === 'true',
    }
  }

  async function openFirst() {
    loading.value = true
    exhausted.value = false
    try {
      const resp = await fetchLots({ limit: 1, ...scopeArgs() })
      const first = resp.items[0]?.listing_key ?? null
      if (first) void router.replace({ query: { ...route.query, lot: first } })
      else exhausted.value = true
    } finally {
      loading.value = false
    }
  }

  function goto(listingKey: string) {
    void router.replace({ query: { ...route.query, lot: listingKey } })
  }

  function finish() {
    const q = { ...route.query }
    delete q.lot
    exhausted.value = true
    void router.replace({ query: q as Record<string, string> })
  }

  // Entrer en mode lot, ou changer de périmètre, ouvre le premier lot. Jamais
  // quand un lot est déjà à l'écran : ce serait ramener l'opérateur au début de
  // la file à chaque refetch.
  //
  // ⚠️ La source observée est le PÉRIMÈTRE SÉRIALISÉ, pas l'identifiant qui
  // vient de l'URL. Dans la page cohorte, l'URL porte la classe dès le premier
  // rendu alors que la classe elle-même n'arrive qu'après le préflight :
  // observer l'URL ferait passer l'unique déclenchement à un moment où le
  // périmètre est encore vide, et l'écran resterait sur « ouverture… » pour
  // toujours, sans la moindre erreur.
  watch(
    [() => JSON.stringify(toValue(scope)), () => toValue(active)],
    ([serialized, on]) => {
      if (!on || serialized === '{}') return
      if (heldLot.value) return
      void openFirst()
    },
    { immediate: true },
  )

  return { heldLot, loading, exhausted, goto, finish }
}
