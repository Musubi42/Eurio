<script setup lang="ts">
/**
 * La liste — c'est elle qui domine l'écran, parce que c'est là qu'il travaille.
 *
 * LA SIGNATURE : LES IMAGES SE COMPTENT EN RONDS
 * ----------------------------------------------
 * Chaque pièce porte ses images de référence en pastilles pleines et vides. Un
 * collectionneur lit un rang de ronds sans légende — et le rond est la forme de
 * l'objet dont on parle. C'est le vocabulaire de `BesoinTable`, agrandi à
 * hauteur de lecture : le même fait, dit à quelqu'un qui n'a pas le lexique.
 *
 * ⛔ CHAQUE LIGNE MÈNE À DU TRAVAIL. Le filtre est posé en amont
 * (`usePiecesATrier`) : seules les pièces à goulot `review` arrivent ici. Un
 * ami qui clique et tombe sur une file vide n'a aucun moyen de comprendre
 * pourquoi — et il ne reviendra pas.
 *
 * ⛔ LE LEXIQUE (§6). Il lit « pièce », « image », « trier ». Jamais « classe »,
 * « crop », « trancher », « exemplaire », ni un `class_id`. Ce sont nos mots,
 * pas les siens.
 */
import VignettePiece from '@/shared/ui/VignettePiece.vue'
import type { PieceATrier } from '../composables/usePiecesATrier'

defineProps<{
  pieces: PieceATrier[]
  /** Vrai tant que `/class-need` n'a pas répondu — on ne montre pas une liste
   *  vide en attendant : une page muette se lit « il n'y a rien à faire », ce
   *  qui est plausible et faux. */
  chargement: boolean
}>()

/** Les pastilles d'une pièce. On dessine SA cible (8, ou 5 en émission
 *  commune) — jamais 8 en dur. */
function pastilles(p: PieceATrier): { pleines: number; vides: number } {
  const pleines = Math.min(p.acquis, p.cible)
  return { pleines, vides: Math.max(p.cible - pleines, 0) }
}
</script>

<template>
  <section class="liste" aria-label="Pièces à trier">
    <h2 class="titre">À trier maintenant</h2>

    <p v-if="chargement" class="attente">Chargement des pièces…</p>

    <ol v-else-if="pieces.length" class="rangs">
      <li v-for="p in pieces" :key="p.key" class="rang">
        <!-- La pièce, avant son nom. On trie des objets qu'on aime regarder :
             la voir vaut mieux que la lire, et c'est ce qui distingue cette
             liste d'un tableau d'opérateur. -->
        <VignettePiece :url="p.image" :nom="p.nom" :taille="40" />

        <span v-if="p.pays" class="pays">{{ p.pays }}</span>
        <span v-else class="pays pays--vide" aria-hidden="true">··</span>

        <span class="nom">{{ p.nom }}</span>

        <span class="compte">
          <span class="pastilles" aria-hidden="true">
            <i v-for="i in pastilles(p).pleines" :key="`p${i}`" class="pleine" />
            <i v-for="i in pastilles(p).vides" :key="`v${i}`" class="vide" />
          </span>
          <span class="fraction">
            {{ p.acquis }} <span class="barre">/</span> {{ p.cible }}
            <span class="sr-only">images de référence</span>
          </span>
        </span>

        <RouterLink class="trier" :to="p.href">
          Trier<span class="fleche" aria-hidden="true">→</span>
        </RouterLink>
      </li>
    </ol>

    <!-- Un écran vide est une invitation, pas un constat. Et surtout : ce n'est
         PAS « tu as fini » — c'est que rien n'attend un tri en ce moment. -->
    <p v-else class="vide-msg">
      Rien à trier pour l'instant.<br>
      <span class="vide-suite">
        Toutes les pièces qui attendaient un tri en ont eu un. Reviens plus
        tard&nbsp;: de nouvelles images arrivent régulièrement.
      </span>
    </p>
  </section>
</template>

<style scoped>
.liste { padding-top: var(--space-7); }

.titre {
  font-family: var(--font-ui);
  font-size: var(--text-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
  margin-bottom: var(--space-4);
}

.rangs { list-style: none; margin: 0; padding: 0; }

.rang {
  display: grid;
  grid-template-columns: 40px 2.25rem 1fr auto 5.5rem;
  align-items: center;
  gap: var(--space-4);
  padding: var(--space-4) var(--space-3);
  border-bottom: 1px solid var(--surface-2);
  transition: background 120ms ease;
}
.rang:hover { background: var(--surface-1); }

.pays {
  font-family: var(--font-ui);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--ink-400);
  border: 1px solid var(--surface-3);
  border-radius: 3px;
  padding: 2px 5px;
  text-align: center;
}
.pays--vide { color: var(--ink-200); border-color: var(--surface-2); }

.nom {
  font-family: var(--font-display);
  font-size: var(--text-base);
  color: var(--ink);
  line-height: var(--leading-snug);
}

.compte { display: flex; align-items: center; gap: var(--space-3); }

.pastilles { display: inline-flex; gap: 3px; }
.pastilles i {
  width: 9px; height: 9px; border-radius: 50%;
  display: inline-block;
}
.pleine { background: var(--indigo-700); }
.vide { border: 1px solid var(--surface-3); }

.fraction {
  font-family: var(--font-ui);
  font-size: var(--text-sm);
  color: var(--ink-500);
  font-variant-numeric: tabular-nums lining-nums;
  min-width: 3.25rem;
}
.barre { color: var(--ink-300); }

.trier {
  justify-self: end;
  font-family: var(--font-ui);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--indigo-700);
  text-decoration: none;
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--surface-3);
  border-radius: 6px;
  background: var(--surface);
  white-space: nowrap;
  transition: border-color 120ms ease, background 120ms ease;
}
.trier:hover { border-color: var(--indigo-700); background: var(--indigo-50); }
.trier:focus-visible { outline: 2px solid var(--indigo-700); outline-offset: 2px; }
.fleche { margin-left: var(--space-2); color: var(--ink-300); }
.trier:hover .fleche { color: var(--indigo-700); }

.attente, .vide-msg {
  padding: var(--space-9) var(--space-3);
  font-family: var(--font-ui);
  font-size: var(--text-base);
  color: var(--ink-700);
  line-height: var(--leading-base);
}
.vide-suite { font-size: var(--text-sm); color: var(--ink-500); }

.sr-only {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px;
  overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
}

@media (max-width: 720px) {
  .rang {
    grid-template-columns: 40px 2.25rem 1fr;
    row-gap: var(--space-3);
  }
  .compte { grid-column: 3; }
  .trier { grid-column: 3; justify-self: start; }
}
</style>
