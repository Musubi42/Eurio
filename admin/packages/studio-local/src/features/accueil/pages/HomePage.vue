<script setup lang="ts">
/**
 * `/` — deux écrans derrière une seule adresse.
 *
 * L'arbitre garde ses KPI ; un ami reçoit SA page (`ACCUEIL-AMI.md` §7). Le
 * discriminant est `review:arbitrate`, exactement celui qui décide déjà de la
 * quarantaine (D7) et du rendu des gestes lourds (D11, `useHeavyGate`) : c'est
 * le même « ami vs opérateur », et il n'y en a qu'un dans ce front.
 *
 * ⛔ ON N'AFFICHE RIEN TANT QUE LES SCOPES NE SONT PAS CONNUS. Sans cette garde,
 * `hasScope` est faux pendant l'aller-retour `/me` : l'arbitre verrait l'accueil
 * d'un ami se peindre puis disparaître à chaque chargement. Même raison que la
 * garde `scopesKnown` de la nav (`AppLayout`), et même remède.
 *
 * ⛔ UN SEUL DES DEUX EST MONTÉ. `v-if`/`v-else`, jamais `v-show` : la page KPI
 * tire `/stats/overview`, à quoi un ami n'a pas droit — la monter lui vaudrait
 * un 403 dans la console et une requête pour rien.
 */
import { computed } from 'vue'

import { useEurioSession } from '@/stores/eurio-session'
import AccueilPage from './AccueilPage.vue'
import DashboardPage from '@/features/dashboard/pages/DashboardPage.vue'

const session = useEurioSession()

/** Les scopes sont-ils connus ? Tant que non, on n'arbitre pas entre les deux
 *  écrans — on attend. Un statut d'échec (`missing`/`invalid`) compte comme
 *  connu : le bandeau de session dit déjà quoi faire, et l'accueil d'un ami est
 *  le moindre mal des deux écrans devant une session cassée. */
const decide = computed(() => session.status !== 'idle' && session.status !== 'loading')
const estArbitre = computed(() => session.hasScope('review:arbitrate'))
</script>

<template>
  <DashboardPage v-if="decide && estArbitre" />
  <AccueilPage v-else-if="decide" />
</template>
