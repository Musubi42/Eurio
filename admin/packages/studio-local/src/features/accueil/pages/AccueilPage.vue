<script setup lang="ts">
/**
 * `/` pour un ami — l'accueil branché sur la donnée.
 *
 * DEUX APPELS, ET AUCUN N'EST BLOQUANT POUR L'AUTRE
 * -------------------------------------------------
 * `/class-need` porte son TRAVAIL (la liste, le but commun) ;
 * `/me/review-stats` porte ses COMPTEURS. Ils partent ensemble et échouent
 * séparément : sans ses compteurs, il peut encore trier — sans la liste, non.
 * C'est pourquoi seule l'erreur de `/class-need` remonte à l'écran.
 *
 * ⛔ AUCUN FAIT N'EST CALCULÉ ICI, ni dans les composables : la liste, l'ordre
 * et les nombres viennent du back. Cette page assemble, elle ne compte pas.
 *
 * Route LÉGÈRE — `/class-need` et `/me/review-stats` sont du SQL pur servi par
 * le VPS. Rien de ce que voit un ami ne dépend d'un Mac allumé.
 */
import { onMounted, watch } from 'vue'

import { useClassNeed } from '@/features/besoin/composables/useClassNeed'
import { useCanonicalThumbs } from '@/shared/composables/useCanonicalThumbs'
import AccueilVue from '../components/AccueilVue.vue'
import { useMeReviewStats } from '../composables/useMeReviewStats'
import { usePiecesATrier } from '../composables/usePiecesATrier'

const besoin = useClassNeed()
const stats = useMeReviewStats()
const vignettes = useCanonicalThumbs()
const { pieces, butCommun } = usePiecesATrier(besoin.data, vignettes.urls)

onMounted(() => {
  besoin.load()
  stats.load()
})

// Les vignettes partent APRÈS la liste, et par-dessus : la liste s'affiche et se
// clique sans elles. Un ami qui arrive doit pouvoir trier avant que la moindre
// image ait fini de charger — c'est de l'illustration, pas de la donnée.
watch(pieces, (p) => {
  if (p.length) vignettes.load(p.map((x) => x.key))
})
</script>

<template>
  <AccueilVue
    :n-triees="stats.data.value?.n_sorted ?? null"
    :n-completees="stats.data.value?.n_classes_completed ?? null"
    :but-commun="butCommun"
    :pieces="pieces"
    :chargement="besoin.loading.value"
    :erreur="besoin.error.value"
  />
</template>
