<script setup lang="ts">
/**
 * Trois chiffres sur UNE ligne — son effort, son effet, le but commun.
 *
 * ⛔ ELLE PREND DE LA HAUTEUR, PAS DE LA PLACE (`ACCUEIL-AMI.md` §5). Ce qui
 * doit dominer l'écran, c'est la LISTE : c'est là qu'il travaille. Trois cartes
 * de KPI empilées repousseraient son travail sous la ligne de flottaison, et
 * feraient de sa page un tableau de bord — précisément ce qu'elle n'est pas.
 *
 * POURQUOI DEUX CHIFFRES À LUI ET UN AU PROJET (§4)
 * ------------------------------------------------
 * Son EFFORT bouge à chaque décision. Son EFFET attend l'arbitrage, puis le
 * rebuild. Les fondre en un seul nombre le ferait travailler dans le vide
 * visible : vingt images triées un dimanche soir, rien qui bouge pendant une
 * semaine.
 *
 * Les deux siens sont en or — la couleur des *moments* chez Eurio. Le but
 * commun est en indigo : c'est la couleur de la marque, pas la sienne. Un ami
 * doit voir d'un coup d'œil ce qui lui appartient et ce qui appartient au
 * projet.
 *
 * ⛔ AUCUNE POLICE À CHASSE FIXE SUR CET ÉCRAN. Le monospace est la voix de
 * l'opérateur — `class_id`, marges, `pending_scoped`. Son absence est ce qui
 * fait que cette page ne ressemble pas à `/besoin`, et c'est délibéré.
 */
const props = defineProps<{
  /** SON EFFORT — `null` tant que ses compteurs n'ont pas répondu. */
  nTriees: number | null
  /** SON EFFET — pièces complétées auxquelles il a contribué. */
  nCompletees: number | null
  /** LE BUT COMMUN — `null` tant que `/class-need` n'a pas répondu. */
  butCommun: { atteint: number; total: number } | null
}>()

/** Le pourcentage de la règle du but commun. Borné : une règle qui déborde de
 *  son gabarit se lit « bug », pas « presque fini ». */
function pct(): number {
  if (!props.butCommun || props.butCommun.total === 0) return 0
  return Math.min(100, (props.butCommun.atteint / props.butCommun.total) * 100)
}

/** Le pluriel français : 0 et 1 prennent le SINGULIER. « 0 images triées » est
 *  une faute, et c'est l'accueil d'un débutant qui la porterait — le seul écran
 *  où le zéro est la valeur normale. */
function pluriel(n: number | null, un: string, plusieurs: string): string {
  return n !== null && Math.abs(n) < 2 ? un : plusieurs
}
</script>

<template>
  <section class="bande" aria-label="Ce que tu as fait, et où en est le projet">
    <!-- SON EFFORT -->
    <div class="unite">
      <p class="chiffre chiffre--sien">{{ nTriees ?? '—' }}</p>
      <p class="mot">{{ pluriel(nTriees, 'image triée', 'images triées') }}</p>
    </div>

    <!-- SON EFFET. « contribué », jamais « ajouté » : une pièce se complète à
         plusieurs, et avec les images validées avant lui. Un compteur qui
         s'approprierait la pièce mentirait dès le deuxième ami, et se
         contredirait entre leurs deux écrans (§4). -->
    <div class="unite">
      <p class="chiffre chiffre--sien">{{ nCompletees ?? '—' }}</p>
      <p class="mot">
        {{ pluriel(nCompletees, 'pièce complétée', 'pièces complétées') }}
        <span class="mot-suite">avec ton aide</span>
      </p>
    </div>

    <!-- LE BUT COMMUN -->
    <div class="unite unite--but">
      <p class="chiffre">{{ butCommun?.atteint ?? '—' }}</p>
      <p class="mot">
        sur {{ butCommun?.total ?? '—' }} pièces ont assez d'images
      </p>
      <div
        class="regle" role="img"
        :aria-label="butCommun
          ? `${butCommun.atteint} pièces sur ${butCommun.total} ont assez d'images`
          : 'progression indisponible'"
      >
        <span class="regle-faite" :style="{ width: `${pct()}%` }" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.bande {
  display: grid;
  grid-template-columns: auto auto 1fr;
  /* ⛔ `stretch`, et surtout PAS `end`. Les trois chiffres doivent partager leur
     ligne du haut : bottom-alignés, le bloc dont le libellé passe sur deux
     lignes (« pièces complétées avec ton aide ») remonte son chiffre de 17,5 px
     — mesuré au navigateur le 2026-08-24 — et la « bande de trois chiffres sur
     UNE ligne » du §5 n'en est plus une. `stretch` fait aussi courir les filets
     séparateurs sur toute la hauteur de la rangée. */
  align-items: stretch;
  gap: 0 var(--space-9);
  padding: var(--space-5) 0 var(--space-6);
  border-bottom: 1px solid var(--surface-3);
}
/* Les filets séparent, ils ne décorent pas : ils disent « ces trois nombres ne
   parlent pas de la même chose ». */
.unite + .unite { border-left: 1px solid var(--surface-3); padding-left: var(--space-9); }
.unite--but { min-width: 15rem; }

.chiffre {
  font-family: var(--font-display);
  font-size: var(--text-3xl);
  line-height: 0.95;
  letter-spacing: var(--tracking-tight);
  color: var(--indigo-700);
  font-variant-numeric: tabular-nums lining-nums;
}
.chiffre--sien { color: var(--gold-700); }

.mot {
  margin-top: var(--space-2);
  font-family: var(--font-ui);
  font-size: var(--text-sm);
  color: var(--ink-500);
  line-height: var(--leading-snug);
}
.mot-suite { color: var(--ink-400); }

.regle {
  margin-top: var(--space-3);
  height: 3px;
  background: var(--surface-3);
  border-radius: 999px;
  overflow: hidden;
}
.regle-faite {
  display: block;
  height: 100%;
  background: var(--indigo-700);
  border-radius: 999px;
  transition: width 600ms cubic-bezier(0.22, 1, 0.36, 1);
}
@media (prefers-reduced-motion: reduce) {
  .regle-faite { transition: none; }
}

/* Sous 900 px la ligne se casse — mais les trois unités restent lisibles comme
   trois faits distincts, filets compris. */
@media (max-width: 900px) {
  .bande { grid-template-columns: 1fr 1fr; gap: var(--space-6) var(--space-6); }
  .unite + .unite { padding-left: var(--space-6); }
  .unite--but { grid-column: 1 / -1; border-left: 0; padding-left: 0; }
}
@media (max-width: 560px) {
  .bande { grid-template-columns: 1fr; }
  .unite + .unite { border-left: 0; padding-left: 0; }
}
</style>
