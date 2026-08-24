<script setup lang="ts">
/**
 * L'accueil d'un ami — l'écran complet, SANS aucun accès réseau.
 *
 * POURQUOI CE COMPOSANT EST PUREMENT PRÉSENTATIONNEL
 * --------------------------------------------------
 * Il est monté deux fois : par `AccueilPage` (branché sur `/class-need` +
 * `/me/review-stats`) et par `AccueilMaquettePage` (sur des fixtures, avec ses
 * états vide / chargement / erreur). C'est ce qui rend la maquette utile plutôt
 * que jetable : ce qu'on regarde et tranche EST ce qu'on livre, à la donnée
 * près — pas une traduction à rattraper ensuite.
 *
 * L'ORDRE DES BLOCS EST LA DÉCISION (§5, §8)
 * ------------------------------------------
 * 1. « Tu ne peux rien casser » — EN HAUT, avant les chiffres. Le premier frein
 *    d'un ami n'est pas l'ergonomie, c'est la peur d'abîmer le projet de
 *    quelqu'un d'autre. On l'enlève avant de lui demander quoi que ce soit.
 * 2. Les trois chiffres, sur UNE ligne.
 * 3. L'aide, repliée.
 * 4. La liste, qui prend tout le reste — c'est là qu'il travaille.
 *
 * ⛔ Cette phrase vit ICI et nulle part ailleurs. L'écran de review continue
 * d'ignorer le `pending_arbitration` que le serveur renvoie : pas de bandeau par
 * décision, pas de compteur « en attente ». C'est la différence entre rassurer
 * une fois et fliquer en continu (§8).
 */
import BandeChiffres from './BandeChiffres.vue'
import PanneauAide from './PanneauAide.vue'
import PiecesATrier from './PiecesATrier.vue'
import type { PieceATrier } from '../composables/usePiecesATrier'

defineProps<{
  nTriees: number | null
  nCompletees: number | null
  butCommun: { atteint: number; total: number } | null
  pieces: PieceATrier[]
  chargement: boolean
  /** L'erreur de `/class-need` — celle qui prive l'écran de son travail. Ses
   *  compteurs, eux, s'affichent en « — » sans un mot : leur absence est une
   *  gêne, pas une panne, et un ami ne peut rien en faire. */
  erreur: string | null
}>()
</script>

<template>
  <div class="accueil">
    <p class="reassurance">
      Tu ne peux rien casser&nbsp;: tout ce que tu tries est relu.
    </p>

    <BandeChiffres
      :n-triees="nTriees" :n-completees="nCompletees" :but-commun="butCommun"
    />

    <PanneauAide />

    <!-- Une erreur se dit en clair et propose le geste qui la lève. Elle
         n'apparaît qu'à la place de la liste : c'est le seul bloc dont
         l'absence empêche de travailler. -->
    <p v-if="erreur" class="erreur">
      <b>Les pièces n'ont pas pu être chargées.</b>
      Recharge la page&nbsp;; si ça se reproduit, préviens Raphaël.
      <span class="detail">{{ erreur }}</span>
    </p>

    <PiecesATrier v-else :pieces="pieces" :chargement="chargement" />
  </div>
</template>

<style scoped>
/* Le fond est `--paper`, pas `--surface` : plus chaud d'un demi-ton que le
   reste de la console. Ce n'est pas une coquetterie — c'est le signal que cette
   page n'est pas un instrument d'opérateur mais la sienne. */
.accueil {
  background: var(--paper);
  min-height: 100%;
  padding: var(--space-7) var(--space-9) var(--space-11);
  max-width: 74rem;
}

.reassurance {
  font-family: var(--font-display);
  font-size: var(--text-xl);
  line-height: var(--leading-snug);
  letter-spacing: var(--tracking-tight);
  color: var(--indigo-700);
  max-width: 30ch;
}

.erreur {
  margin-top: var(--space-8);
  padding: var(--space-5) var(--space-6);
  border-left: 2px solid var(--danger);
  background: var(--surface-1);
  font-family: var(--font-ui);
  font-size: var(--text-sm);
  color: var(--ink-500);
  line-height: var(--leading-base);
  max-width: 60ch;
}
.erreur b { display: block; color: var(--ink); font-size: var(--text-base); }
.detail { display: block; margin-top: var(--space-3); color: var(--ink-300); }

@media (max-width: 720px) {
  .accueil { padding: var(--space-6) var(--space-4) var(--space-10); }
  .reassurance { font-size: var(--text-lg); }
}
</style>
