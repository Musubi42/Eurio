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
import RunProgressLine from '../components/RunProgressLine.vue'
import { queryNeedOnly, queryParam, queryRunIds } from '../composables/useQueryScope'

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

// Périmètre par run : `?run=a,b` dans l'URL, `run_id=a,b` côté API. Le bandeau
// d'avancement se rafraîchit à chaque changement de lot — c'est-à-dire après
// chaque décision, puisque trancher un lot mène au suivant ou à la grille.
const runIds = computed(() => queryRunIds(route) ?? [])
// Périmètre par besoin : `?need=1` dans l'URL, `need_only=true` côté API —
// les voisins comme le compteur l'appliquent (D2/D3).
const needOnly = computed(() => queryNeedOnly(route))

const scope = computed<Record<string, string>>(() => {
  const out: Record<string, string> = {}
  for (const k of SCOPE_KEYS) {
    const v = queryParam(route, k)
    if (v) out[k] = v
  }
  if (runIds.value.length) out.run_id = runIds.value.join(',')
  if (needOnly.value) out.need_only = 'true'
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
  <div class="flex h-full flex-col">
    <RunProgressLine
      v-if="runIds.length"
      :run-ids="runIds"
      :need-only="needOnly"
      :refresh-key="listingKey"
    />
    <LotDetailView
      :key="listingKey"
      :listing-key="listingKey"
      :scope="scope"
      @navigate="goto"
      @exhausted="leave"
    />
  </div>
</template>
