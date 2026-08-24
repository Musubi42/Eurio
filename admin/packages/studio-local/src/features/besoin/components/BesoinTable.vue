<script setup lang="ts">
// La liste des classes — une ligne, un verdict, un geste.
//
// Trois propriétés non négociables (O2), et chacune tient dans cette table :
//
// 1. ELLE DIT QUAND LE GOULOT N'EST PAS ELLE. Une classe sans candidat porte
//    `scrape` et n'offre pas de lien vers une file vide.
// 2. ELLE S'ARRÊTE À LA CIBLE. Une classe pleine sort du travail avec ses
//    parqués comptés — on ne ferme pas, on ne supprime pas (D3).
// 3. ELLE NE SE MENT PAS SUR ZÉRO. « rien scrapé », « pays désarmé »,
//    « N masqués » sont trois causes distinctes, jamais une case vide.
//
// ⛔ LE GESTE EST UN LIEN, JAMAIS UNE ACTION. Enfiler, scraper, rebâtir sont
// des ÉCRITURES : elles ne se déclenchent pas au fil d'une lecture.

import { computed, watch } from 'vue'
import { RouterLink } from 'vue-router'
import VignettePiece from '@/shared/ui/VignettePiece.vue'
import { useCanonicalThumbs } from '@/shared/composables/useCanonicalThumbs'
import {
  gestureHref, MARGIN_FLOOR, type ClassNeedRow,
} from '../composables/useClassNeed'

const props = defineProps<{
  rows: ClassNeedRow[]
}>()

/** Les pastilles de la colonne BANQUE. On dessine la CIBLE (8 ou 5), pas le
 *  plafond : c'est la cible qui décide du verdict (D2). */
function pips(r: ClassNeedRow): { filled: number; empty: number } {
  const filled = Math.min(r.have, r.target)
  return { filled, empty: Math.max(r.target - filled, 0) }
}

function margeLabel(r: ClassNeedRow): string {
  return r.best_margin == null ? '' : r.best_margin.toFixed(3)
}

/** Ce que la colonne CANDIDATS dit EN PLUS du compte. Un compte seul ment par
 *  omission : la file ES « 4 à l'unité » était faite de quatre annonces
 *  françaises à 0,023 de marge — quatre skips pour rien. */
function effet(r: ClassNeedRow): { text: string; kind: string; title: string } | null {
  if (r.bottleneck === 'pleine') {
    return {
      text: 'parqués — ni fermés ni supprimés',
      kind: 'none',
      title: `Cette classe a atteint sa cible (${r.target}). Ses ${r.pending} crops ouverts restent en base et retrouvables ; ils ne sont simplement plus servis (D2/D3). Ils serviront la voie A.`,
    }
  }
  if (r.pending === 0) {
    return {
      text: 'rien scrapé — jamais interrogé',
      kind: 'none',
      title: "Aucun crop en file pour cette classe : le goulot n'est pas la review, c'est qu'on n'a jamais interrogé eBay. C'est un sujet de scrape.",
    }
  }
  // O4a — tout le pool tombe sous les filtres : la classe relève du SCRAPE, et
  // la ligne doit dire POURQUOI. Sans ce cas, elle afficherait « 0 candidat »
  // à côté d'un `pending` non nul, ce qui se lit « bug », pas « écarté ».
  if (r.pending_scoped === 0) {
    return {
      text: `${r.pending} candidat${r.pending > 1 ? 's' : ''} écarté${r.pending > 1 ? 's' : ''} par les filtres`,
      kind: 'none',
      title: `Les ${r.pending} crops que la banque marque de cette classe ne survivent à aucun filtre : ${r.n_hidden_by_era} contredits par l'ère (le titre de l'annonce ne peut pas contenir cette pièce), ${r.n_hidden_by_country} hors du pays, ${r.n_hidden_by_denom} sous le seuil de dénomination. Il n'y a rien à trancher : c'est un sujet de scrape.`,
    }
  }
  if (r.n_hidden_by_era > 0) {
    const pays = r.n_hidden_by_country > 0 ? ` · ${r.n_hidden_by_country} par le pays` : ''
    return {
      text: `${r.n_hidden_by_era} écarté${r.n_hidden_by_era > 1 ? 's' : ''} par l'ère${pays}`,
      kind: 'hidden',
      title: `Le titre de ces annonces couvre des années où cette pièce ne pouvait pas exister (ère de la classe). L'intervalle du titre est comparé à l'ère, jamais année par année — « 1999–2012 » contient 2004. Mesuré : le filtre ne coûte aucun vrai positif sur les lots.`,
    }
  }
  if (r.country_disarmed) {
    return {
      text: `pays ${r.country ?? '?'} désarmé — il ne laissait rien`,
      kind: 'disarm',
      title: `Le filtre pays aurait vidé entièrement cette file : aucun des ${r.pending} candidats ne vient d'une annonce ${r.country}. Il s'est retiré, et le lien ci-contre le porte (pays=tous). Rappel : listing_country n'est pas le pays de l'annonce mais celui que la recherche VISAIT.`,
    }
  }
  if (r.n_hidden_by_country > 0) {
    return {
      text: `${r.n_hidden_by_country} masqué${r.n_hidden_by_country > 1 ? 's' : ''} par le filtre pays`,
      kind: 'hidden',
      title: `Le filtre pays (actif par défaut) écarte ${r.n_hidden_by_country} crop(s) d'annonces hors ${r.country}. Il coupe ~91 % des faux positifs pour ~5 % de vrais — surtout des coffrets multi-pays.`,
    }
  }
  if ((r.best_margin ?? 0) < MARGIN_FLOOR) {
    return {
      text: `marge max ${margeLabel(r)} — sous le seuil du verdict`,
      kind: 'weak',
      title: "Le modèle n'est net sur AUCUN candidat de cette file. Ce sont probablement des faux positifs, ou des pièces que la banque ne connaît pas. Regarder ailleurs d'abord.",
    }
  }
  return { text: `marge max ${margeLabel(r)}`, kind: 'ok', title: 'La meilleure marge de la file — elle dit si ça vaut le coup de regarder.' }
}

function gesteLabel(r: ClassNeedRow): string {
  if (r.bottleneck === 'review') return 'pêcher'
  // `scrape` n'a pas de libellé ici : son geste est un PLAN, rendu à part
  // (moitié ACHETER) parce qu'il se compose au grain groupe de découverte et
  // non à la classe. Une classe n'est jamais l'unité de coût d'un scrape.
  return 'voir les parqués'
}

const anyDisarmed = computed(() => props.rows.some((r) => r.country_disarmed))

// La vignette de la pièce, à gauche du `class_id`. Un identifiant est une clé,
// pas une pièce : voir l'objet dont la ligne parle coûte 26 px et évite d'aller
// vérifier ailleurs. Même composant et même route que l'accueil — une seule
// façon d'obtenir une vignette dans ce front.
const vignettes = useCanonicalThumbs()
watch(() => props.rows, (rows) => {
  if (rows.length) vignettes.load(rows.map((r) => r.class_id))
}, { immediate: true })
</script>

<template>
  <div>
    <table>
      <thead>
        <tr>
          <th style="width: 32%">Classe</th>
          <th style="width: 16%">Banque</th>
          <th style="width: 28%">Candidats</th>
          <th style="width: 10%">Goulot</th>
          <th>Geste</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.class_id" :class="{ parked: r.bottleneck === 'pleine' }">
          <td class="cls-cell">
            <VignettePiece
              :url="vignettes.urls.value[r.class_id]" :nom="r.label" :taille="26"
            />
            <!-- Le bloc texte reste UN bloc : `.lbl` est en `display: block` et
                 gère son ellipse. Le sortir en frère de la vignette dans un flex
                 le remettrait sur la ligne de l'identifiant. -->
            <span class="cls-texte">
              <span class="flag">{{ r.country ?? '··' }}</span>
              <span class="cls">{{ r.class_id }}</span>
              <span
                v-if="r.family === 'emission_commune'" class="ec"
                title="Émission commune : le même dessin frappé par 13 à 19 pays. L'image reconnaît le dessin à 97,7 % mais le pays à 64,4 % — ici c'est le TITRE de l'annonce qui tranche. Cible 5, pas 8 (D4)."
              >◈</span>
              <span class="lbl">{{ r.label }}</span>
            </span>
          </td>

          <td class="bank">
            {{ r.have }}/{{ r.target }}
            <span v-if="r.have >= r.cap" class="cap">⌐cap {{ r.cap }}</span>
            <span class="pips">
              <i v-for="i in pips(r).filled" :key="`f${i}`">●</i><u v-for="i in pips(r).empty" :key="`e${i}`">○</u>
            </span>
            <span
              v-if="r.accepted_pending > 0" class="acq"
              :title="`${r.accepted_pending} crop(s) validé(s) par un humain, PAS encore en banque : \`have\` ne bouge qu'au prochain build_dino_anchors. Le verdict, lui, les compte déjà (D8) — sinon la file resservirait une classe qu'on vient de remplir.`"
            >+{{ r.accepted_pending }}</span>
          </td>

          <td>
            <span class="cand" :class="{ 'cand--weak': r.pending_scoped === 0 || (r.best_margin ?? 0) < MARGIN_FLOOR }">
              {{ r.pending_scoped }}
            </span>
            <span v-if="effet(r)" class="eff" :class="`eff--${effet(r)!.kind}`" :title="effet(r)!.title">
              · {{ effet(r)!.text }}
            </span>
          </td>

          <td><span class="v" :class="`v--${r.bottleneck}`">{{ r.bottleneck }}</span></td>

          <td>
            <!-- Le geste mène à `/review/peche`, qui n'est PLUS lourde depuis le
                 lot 1 de review-collaborative-v2 (crops présignés + suggestions DINO
                 lues en base par le VPS). Le gate `heavyLocked` posé ici était donc
                 périmé : il barrait à un ami — et à lui seul — la file que cette
                 page vient de lui désigner, avec une infobulle qui lui parlait d'un
                 port et d'un Mac (D11). -->
            <RouterLink
              v-if="gestureHref(r)"
              class="geste" :to="gestureHref(r)!"
            >→ {{ gesteLabel(r) }}</RouterLink>
            <span
              v-else class="geste geste--none"
              :title="`Le geste d'une classe sans candidat n'est pas une file, c'est un PLAN : il se compose au grain groupe de découverte (pays · dénomination · année), pas à la classe — deux commémoratives d'un même pays et d'une même année ne coûtent qu'une recherche. Il vit dans la moitié ACHETER, en haut de cette page${r.country ? ` (pays ${r.country})` : ''}.`"
            >→ plan, en haut</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="5" class="empty">
            Aucune classe ne correspond à ces filtres.
            <b>Ce n'est pas « rien à faire »</b> — c'est le filtre qui mord.
            Lève-en un.
          </td>
        </tr>
      </tbody>
    </table>

    <p class="src">
      <b>banque</b> = <code>have</code> / <code>target</code>, <b>+N</b> =
      <code>accepted_pending</code> (D8) ·
      <b>candidats</b> = <code>pending_scoped</code> et l'effet des filtres ·
      <b>goulot</b> = <code>bottleneck</code>
      <span v-if="anyDisarmed">
        · les liens des lignes « désarmé » portent <code>pays=tous</code>, sans
        quoi la pêche réappliquerait son filtre et servirait zéro
      </span>
    </p>
  </div>
</template>

<style scoped>
table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
thead th {
  text-align: left; font-size: 10px; text-transform: uppercase;
  letter-spacing: 0.16em; color: var(--ink-400); font-weight: 600;
  padding: 0 12px 8px; border-bottom: 1px solid var(--surface-3); white-space: nowrap;
}
tbody td { padding: 9px 12px; border-bottom: 1px solid var(--surface-2); vertical-align: top; }
/* La vignette à gauche, le bloc texte à droite — et ce dernier reste un bloc,
   sinon le libellé remonte sur la ligne de l'identifiant. */
.cls-cell { display: flex; align-items: flex-start; gap: 8px; }
.cls-texte { min-width: 0; flex: 1; }
tbody tr:hover { background: var(--surface-1); }
tbody tr.parked { color: var(--ink-400); }
tbody tr.parked .cls { color: var(--ink-400); }

.cls { font-family: var(--font-mono); font-size: 11.5px; color: var(--ink-700); }
.lbl {
  display: block; margin-top: 2px; font-size: 10.5px; color: var(--ink-400);
  max-width: 44ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.flag {
  font-family: var(--font-mono); font-size: 10px; color: var(--ink-400);
  border: 1px solid var(--surface-3); border-radius: 3px; padding: 0 4px; margin-right: 5px;
}
.ec { color: var(--gold); font-size: 12px; margin-left: 4px; cursor: help; }

.bank { font-family: var(--font-mono); font-size: 11.5px; white-space: nowrap; }
.cap { color: var(--ink-300); font-size: 10px; }
.pips { letter-spacing: 1px; margin-left: 6px; }
.pips i { font-style: normal; color: var(--indigo-700); }
.pips u { text-decoration: none; color: var(--surface-3); }
.acq { color: var(--gold); font-size: 10.5px; margin-left: 5px; cursor: help; }

.cand { font-family: var(--font-mono); font-size: 11.5px; }
.cand--weak { color: var(--ink-400); }
.eff { display: block; margin-top: 2px; font-size: 10.5px; cursor: help; }
.eff--disarm { color: var(--warning); }
.eff--hidden { color: var(--ink-500); }
.eff--weak { color: var(--ink-400); }
.eff--none { color: var(--ink-400); }
.eff--ok { color: var(--ink-500); }

.v {
  font-size: 10.5px; font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.08em; padding: 2px 8px; border-radius: 999px; white-space: nowrap;
}
.v--review { background: rgba(47, 169, 113, 0.15); color: var(--success); }
.v--scrape { background: rgba(216, 138, 45, 0.15); color: var(--warning); }
.v--pleine { background: var(--surface-2); color: var(--ink-400); }

.geste {
  font-size: 11.5px; color: var(--indigo-700); text-decoration: underline;
  text-underline-offset: 2px; white-space: nowrap;
}
.geste--none { color: var(--ink-300); text-decoration: none; cursor: default; }

.empty { padding: 26px 12px; color: var(--ink-500); font-size: 13px; }
.empty b { color: var(--ink); }
.src {
  font-family: var(--font-mono); font-size: 10.5px; color: var(--ink-400);
  padding-top: 12px; line-height: 1.7;
}
.src b { color: var(--ink-500); font-weight: 500; }
code { background: var(--surface-2); border-radius: 3px; padding: 0 3px; }
</style>
