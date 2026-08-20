<script setup lang="ts">
// La route `/review/lot/:listing_key` — un mince hôte autour de LotDetailView.
//
// Tout le travail est dans la vue ; cette page ne fait que traduire l'URL en
// props et l'événement de navigation en changement d'URL. Le PÉRIMÈTRE de la
// file voyage dans la query (`?design_group=`, `?cohort_id=`, `?dino_class=`…)
// et se propage à chaque saut : sans ça, « lot suivant » repartirait dans la
// file lot globale au premier clic, et l'écran ne dirait rien.
//
// Le même composant est monté par la page cohorte, qui garde le lot courant
// dans sa propre query plutôt que dans un paramètre de route.

import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LotDetailView from '../views/LotDetailView.vue'
import { queryParam } from '../composables/useQueryScope'

const route = useRoute()
const router = useRouter()

const listingKey = computed(() => {
  const k = route.params.listing_key
  return Array.isArray(k) ? k[0] : (k ?? '')
})

/** Les clés de périmètre reconnues par `GET /review-queue/lots{,/{key}}`. */
const SCOPE_KEYS = [
  'cohort_id', 'target_eurio_id', 'design_group',
  'dino_class', 'dino_rank', 'dino_min_spread',
] as const

const scope = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const k of SCOPE_KEYS) {
    const v = queryParam(route, k)
    if (v) out[k] = v
  }
  return out
})

function goto(key: string) {
  void router.replace({
    path: `/review/lot/${encodeURIComponent(key)}`,
    query: route.query,
  })
}

function leave() {
  // Plus de lot dans le périmètre : on rend la main à la grille, en gardant le
  // périmètre pour que l'écran d'arrivée montre la même chose que celui qu'on
  // quitte.
  void router.replace({ path: '/review', query: { ...route.query, mode: 'lot' } })
}
</script>

<template>
  <LotDetailView
    :key="listingKey"
    :listing-key="listingKey"
    :scope="scope"
    @navigate="goto"
    @exhausted="leave"
  />
</template>
