<script setup lang="ts">
/**
 * « Comment reconnaître une bonne image ? » — cinq cas, en images.
 *
 * POURQUOI CETTE AIDE VIT ICI, ET PAS DANS L'ÉCRAN DE REVIEW (§7)
 * ---------------------------------------------------------------
 * L'aide se range à l'endroit où on en a besoin, et ce principe tranche le
 * placement tout seul :
 *   - les REPÈRES SUR DES BOUTONS (recadrer, chercher, passer) sont des coach
 *     marks : hors de l'écran qui porte ces boutons, ils ne veulent rien dire ;
 *   - le MÉTIER — qu'est-ce qui fait qu'une image sert — s'apprend au calme,
 *     avant ou entre deux sessions. C'est ceci.
 *
 * POURQUOI DES IMAGES, ET POURQUOI CELLES-LÀ
 * ------------------------------------------
 * « Une image floue ne sert pas » est une phrase ; une image floue est une
 * leçon. Les cinq exemples sont de VRAIS crops déjà arbitrés, sortis du
 * canonique le 2026-08-24 — pas des illustrations fabriquées. Un contre-exemple
 * inventé enseigne un défaut qu'on ne rencontre jamais ; ceux-ci sont exactement
 * ce que la file sert.
 *
 * Ils sont copiés en dur dans le front (`src/assets/tuto/`, 5 WebP, 51 Ko au
 * total) et NON tirés du canonique à l'exécution. Une aide doit être stable :
 * un exemple qui change parce que la donnée a bougé n'enseigne plus rien, et une
 * URL présignée qui expire transformerait la leçon en cadres vides.
 *
 * POURQUOI UNE MODALE
 * -------------------
 * Dépliée en place, la grille d'exemples repousse la liste — donc son travail —
 * sous la ligne de flottaison, ce que le §5 refuse explicitement. La modale la
 * montre en grand, puis rend l'écran intact.
 */
import { onBeforeUnmount, ref, watch } from 'vue'

import autrePiece from '@/assets/tuto/autre-piece.webp'
import bonne from '@/assets/tuto/bonne.webp'
import illisible from '@/assets/tuto/illisible.webp'
import pasUnePiece from '@/assets/tuto/pas-une-piece.webp'
import plusieurs from '@/assets/tuto/plusieurs.webp'

interface Exemple {
  img: string
  verdict: 'oui' | 'non' | 'cherche'
  titre: string
  pourquoi: string
}

/**
 * ⛔ CHAQUE CAS PORTE SA RÉPONSE **ET** SON POURQUOI (§7). Une galerie de
 * « bien / pas bien » sans raison n'apprend qu'à imiter : devant le sixième cas,
 * qui ne ressemble à aucun des cinq, on ne sait toujours pas décider.
 *
 * Le dernier n'est pas un rejet, et c'est le plus important : contredire la
 * proposition est le geste où un ami apporte le plus. Une aide qui ne montrerait
 * que des images à écarter enseignerait à écarter.
 */
const EXEMPLES: Exemple[] = [
  {
    img: bonne, verdict: 'oui',
    titre: 'Celle-ci va',
    pourquoi: 'Une seule pièce, entière, bien au centre, et le motif se lit '
      + "sans effort. C'est tout ce qu'on demande.",
  },
  {
    img: plusieurs, verdict: 'non',
    titre: 'Plusieurs pièces',
    pourquoi: 'Une image qui contient trois pièces ne sert de référence à '
      + 'aucune des trois. Écarte-la.',
  },
  {
    img: pasUnePiece, verdict: 'non',
    titre: "Ce n'est pas une pièce",
    pourquoi: "La photo de la boîte, du certificat ou de l'emballage : il n'y a "
      + 'pas de pièce à reconnaître dessus.',
  },
  {
    img: illisible, verdict: 'non',
    titre: 'On ne voit pas le motif',
    pourquoi: 'Trop sombre, floue, ou couverte par un bandeau du vendeur. Si tu '
      + "n'arrives pas à reconnaître le dessin, l'app n'y arrivera pas non plus.",
  },
  {
    img: autrePiece, verdict: 'cherche',
    titre: "Ce n'est pas cette pièce-là",
    pourquoi: "L'image est bonne, mais ce n'est pas la pièce proposée. Ne "
      + 'l’écarte pas : cherche la bonne toi-même. C’est là que tu apportes le plus.',
  },
]

const VERDICTS: Record<Exemple['verdict'], string> = {
  oui: 'À garder',
  non: 'À écarter',
  cherche: 'À corriger',
}

const ouvert = ref(false)
const fermeture = ref<HTMLButtonElement | null>(null)

function surTouche(e: KeyboardEvent): void {
  if (ouvert.value && e.key === 'Escape') { e.preventDefault(); ouvert.value = false }
}
window.addEventListener('keydown', surTouche)
onBeforeUnmount(() => window.removeEventListener('keydown', surTouche))

watch(ouvert, async (v) => {
  // Le fond ne défile pas derrière la modale : sinon la molette emporte la page
  // et on rouvre sur un écran qui a bougé tout seul.
  document.body.style.overflow = v ? 'hidden' : ''
  if (!v) return
  await Promise.resolve()
  fermeture.value?.focus()
})
onBeforeUnmount(() => { document.body.style.overflow = '' })
</script>

<template>
  <section class="aide">
    <button
      class="entete" type="button" :aria-expanded="ouvert"
      @click="ouvert = true"
    >
      <span class="question">Comment reconnaître une bonne image&nbsp;?</span>
      <span class="action">Voir les exemples</span>
    </button>

    <div v-if="ouvert" class="voile" @click="ouvert = false">
      <article
        class="modale" role="dialog" aria-modal="true"
        aria-labelledby="aide-titre" @click.stop
      >
        <header class="tete">
          <h2 id="aide-titre" class="h">Comment reconnaître une bonne image&nbsp;?</h2>
          <button ref="fermeture" class="fermer" type="button" @click="ouvert = false">
            Fermer
          </button>
        </header>

        <div class="corps">
          <ul class="grille">
            <li v-for="e in EXEMPLES" :key="e.titre" class="cas">
              <img class="vue" :src="e.img" :alt="e.titre" width="224" height="224">
              <p class="verdict" :class="`verdict--${e.verdict}`">{{ VERDICTS[e.verdict] }}</p>
              <h3 class="cas-titre">{{ e.titre }}</h3>
              <p class="pourquoi">{{ e.pourquoi }}</p>
            </li>
          </ul>

          <div class="regles">
            <h3 class="regles-titre">En deux mots</h3>
            <ul>
              <li>
                <b>Mal cadrée ne veut pas dire mauvaise.</b>
                Si la photo est bonne mais la pièce de travers, recadre-la —
                c'est souvent le geste qui la sauve.
              </li>
              <li>
                <b>En cas de doute, passe.</b>
                Une image passée revient à quelqu'un d'autre. Une image mal
                rangée, il faut la retrouver.
              </li>
              <li>
                <b>Tu ne peux rien casser.</b>
                Tout ce que tu tries est relu avant d'entrer dans le projet.
              </li>
            </ul>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.aide { border-bottom: 1px solid var(--surface-3); }

.entete {
  display: flex; align-items: baseline; justify-content: space-between;
  gap: var(--space-4); width: 100%;
  padding: var(--space-4) var(--space-3);
  background: none; border: 0; cursor: pointer; text-align: left;
}
.entete:hover { background: var(--surface-1); }
.entete:focus-visible { outline: 2px solid var(--indigo-700); outline-offset: -2px; }

.question { font-family: var(--font-display); font-size: var(--text-base); color: var(--ink-700); }
.action {
  font-family: var(--font-ui); font-size: var(--text-xs); font-weight: 600;
  text-transform: uppercase; letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400); white-space: nowrap;
}
.entete:hover .action { color: var(--indigo-700); }

.voile {
  position: fixed; inset: 0; z-index: 50;
  display: flex; align-items: center; justify-content: center;
  padding: var(--space-6);
  background: rgba(14, 14, 31, 0.62);
  backdrop-filter: blur(3px);
}
.modale {
  width: min(66rem, 100%);
  max-height: 88vh;
  display: flex; flex-direction: column;
  background: var(--paper);
  border-radius: 10px;
  box-shadow: 0 18px 50px rgba(14, 14, 31, 0.35);
  overflow: hidden;
}

.tete {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--space-4);
  padding: var(--space-5) var(--space-6);
  border-bottom: 1px solid var(--surface-3);
}
.h {
  font-family: var(--font-display); font-size: var(--text-lg);
  color: var(--indigo-700);
}
.fermer {
  font-family: var(--font-ui); font-size: var(--text-xs); font-weight: 600;
  text-transform: uppercase; letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-500); background: none;
  border: 1px solid var(--surface-3); border-radius: 6px;
  padding: var(--space-2) var(--space-3); cursor: pointer;
}
.fermer:hover { color: var(--indigo-700); border-color: var(--indigo-700); }
.fermer:focus-visible { outline: 2px solid var(--indigo-700); outline-offset: 2px; }

.corps { overflow-y: auto; padding: var(--space-6); }

.grille {
  list-style: none; margin: 0; padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(11rem, 1fr));
  gap: var(--space-6);
}
.cas { min-width: 0; }
.vue {
  width: 100%; height: auto; aspect-ratio: 1;
  border-radius: 50%;
  background: var(--surface-2);
  display: block;
}
.verdict {
  margin-top: var(--space-3);
  font-family: var(--font-ui); font-size: 10px; font-weight: 600;
  text-transform: uppercase; letter-spacing: var(--tracking-eyebrow);
}
.verdict--oui { color: var(--success); }
.verdict--non { color: var(--danger); }
.verdict--cherche { color: var(--warning); }

.cas-titre {
  margin-top: var(--space-1);
  font-family: var(--font-display); font-size: var(--text-base); color: var(--ink);
}
.pourquoi {
  margin-top: var(--space-2);
  font-family: var(--font-ui); font-size: var(--text-sm);
  color: var(--ink-500); line-height: var(--leading-base);
}

.regles {
  margin-top: var(--space-8);
  padding-top: var(--space-5);
  border-top: 1px solid var(--surface-3);
  max-width: 60ch;
}
.regles-titre {
  font-family: var(--font-ui); font-size: var(--text-xs); font-weight: 600;
  text-transform: uppercase; letter-spacing: var(--tracking-eyebrow);
  color: var(--ink-400);
}
.regles ul {
  margin: var(--space-3) 0 0; padding-left: var(--space-5);
  font-family: var(--font-ui); font-size: var(--text-sm);
  color: var(--ink-500); line-height: var(--leading-base);
}
.regles li { margin-bottom: var(--space-3); }
.regles li::marker { color: var(--gold); }
.regles b { color: var(--ink); font-weight: 600; }

@media (max-width: 720px) {
  .voile { padding: var(--space-3); }
  .corps { padding: var(--space-4); }
  .grille { grid-template-columns: repeat(auto-fill, minmax(8.5rem, 1fr)); gap: var(--space-4); }
}
</style>
