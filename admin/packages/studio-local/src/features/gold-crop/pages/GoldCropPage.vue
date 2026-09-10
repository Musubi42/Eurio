<script setup lang="ts">
// La référence visuelle du jeu d'or (chantier `juge-du-crop`).
//
// « J'aimerais bien observer cette planche de mes propres yeux puisque je pense
// être le meilleur juge de si c'est bon ou pas bon. » — le PO, 2026-08-28.
//
// Page de LECTURE : elle lit le canonique, donc elle marche depuis le front
// hébergé. L'annotation, elle, se fait dans l'outil local — c'est lui qui a les
// raws en cache et les poignées.
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import VignetteOr from '../components/VignetteOr.vue'
import {
  type AnnotationOr,
  TAILLE_TIRAGE,
  estAnnotee,
  strateRetenue,
  useGoldCropApi,
} from '../composables/useGoldCropApi'
import { N_DOUBLE } from '../composables/sha256'

// `?version=` comme la page d'annotation. Sans ça le hub reste collé à v1 —
// abandonnée par D13 — et les entrées qu'il propose (2ᵉ passe, réserve) ne
// s'ouvriraient jamais sur la version où la séance vit réellement.
const route = useRoute()
const version = ref(String(route.query.version || 'v1'))
const { jeu, chargement, erreur, charger } = useGoldCropApi(version.value)

const filtreStrate = ref<string | null>(null)
const filtreVerdict = ref<string | null>(null)
const montrerBande = ref(true)

const lignes = computed<AnnotationOr[]>(() => jeu.value?.annotations ?? [])
const passe1 = computed(() => lignes.value.filter((a) => a.passe === 1))

const strates = computed(() =>
  [...new Set(passe1.value.map(strateRetenue))].sort(),
)

const visibles = computed(() =>
  passe1.value.filter(
    (a) =>
      (!filtreStrate.value || strateRetenue(a) === filtreStrate.value) &&
      (!filtreVerdict.value ||
        (filtreVerdict.value === 'accept') === (a.resolution_status === 'manual')),
  ),
)

/** Ce qui se compte, et pourquoi. */
const bilan = computed(() => {
  const l = passe1.value
  const doubles = new Set(lignes.value.filter((a) => a.passe > 1).map((a) => a.asset_id))
  const obliq = l
    .filter((a) => a.a && a.b)
    .map((a) => a.b! / a.a!)
    .sort((x, y) => x - y)
  return {
    n: l.length,
    annotees: l.filter(estAnnotee).length,
    indecidables: l.filter((a) => a.indecidable === 1).length,
    acceptes: l.filter((a) => a.resolution_status === 'manual').length,
    strates_confirmees: l.filter((a) => a.strate_confirmee).length,
    doubles: doubles.size,
    // La médiane d'obliquité dit d'avance ce que le format coûtera : à
    // b/a = 0,90, aucune méthode ne peut dépasser BIoU ≈ 0,26 (ADR-017).
    ba_median: obliq.length ? obliq[obliq.length >> 1] : null,
  }
})

const gele = computed(() => !!jeu.value?.version?.frozen_at)

/**
 * L'avancement de la séance, d'un coup d'œil — et le chemin pour la reprendre.
 *
 * Il vit sur la page de LECTURE parce que c'est celle qu'on ouvre pour savoir
 * où on en est. La séance était à l'arrêt depuis dix jours sans que rien ne le
 * dise : un compteur qu'il faut aller chercher dans une base ne se regarde pas.
 */
const seance = computed(() => {
  const annotees = passe1.value.filter(estAnnotee).length
  const dates = lignes.value.map((a) => a.updated_at).filter(Boolean).sort()
  const p2 = new Set(lignes.value.filter((a) => a.passe === 2).map((a) => a.asset_id)).size
  return {
    annotees,
    cible: TAILLE_TIRAGE,
    derniere: dates.length ? dates[dates.length - 1].slice(0, 10) : null,
    complete: annotees >= TAILLE_TIRAGE,
    p2,
    n_double: N_DOUBLE,
  }
})

// `void` et non `() => charger()` : un hook de cycle de vie qui RETOURNE une
// promesse la confie à la gestion d'erreurs de Vue, laquelle la fait remonter
// jusqu'au test — alors même que `charger` attrape déjà tout. Le hook ne
// possède pas cette promesse, il ne doit pas la rendre.
onMounted(() => {
  void charger()
})
</script>

<template>
  <div class="gold-crop">
    <header>
      <div>
        <h1>Jeu d'or du cadrage — {{ version }}</h1>
        <p class="doux">
          La référence contre laquelle toute méthode de crop sera jugée. Rien ici
          n'est calculé par une méthode : l'ellipse est tracée à la main.
        </p>
      </div>
      <div class="etat">
        <span v-if="gele" class="pastille gele" :title="jeu?.version?.snapshot_sha256 || ''">
          gelé le {{ jeu?.version?.frozen_at?.slice(0, 10) }}
        </span>
        <span v-else class="pastille ouvert">en cours d'annotation</span>
      </div>
    </header>

    <section v-if="!chargement && !erreur" class="seance">
      <div class="avance">
        <b>{{ seance.annotees }} / {{ seance.cible }}</b>
        <span class="doux">
          images annotées
          <template v-if="seance.derniere"> · dernière écriture le {{ seance.derniere }}</template>
          <template v-else> · la séance n'a pas commencé</template>
        </span>
      </div>
      <RouterLink
        v-if="!gele" class="bouton" :to="`/gold-crop/annoter?version=${version}`"
      >Annoter la séance →</RouterLink>
      <RouterLink
        v-if="!gele && seance.complete" class="bouton second"
        :to="`/gold-crop/annoter?version=${version}&passe=2`"
      >2ᵉ passe ({{ seance.p2 }} / {{ seance.n_double }}) →</RouterLink>
      <!-- La réserve (24 images) regarnit le tirage quand une image en sort par
           « indécidable » — 16 des 28 rejets de v2 (D14). Elle ne s'ouvre qu'une
           fois la passe 1 du tirage complète : l'annoter avant, c'est annoter des
           images dont on ne sait pas encore si elles serviront. -->
      <RouterLink
        v-if="!gele && seance.complete" class="bouton second"
        :to="`/gold-crop/annoter?version=${version}&role=reserve`"
      >Annoter la réserve →</RouterLink>
      <span v-else-if="!gele" class="doux">
        la 2ᵉ passe s'ouvre quand la 1ʳᵉ est complète — elle fixe le plafond du banc
      </span>
      <!-- Entrée de la PLANCHE. La route est `meta.heavy` : hors du poste du
           banc, `AppLayout` y rend `LocalOnlyNotice` au lieu d'une page vide —
           le gating ne se réinvente pas ici. -->
      <RouterLink class="lien-planche" to="/gold-crop/planche">
        Planche du banc (local) →
      </RouterLink>
    </section>

    <p v-if="chargement" class="doux">chargement…</p>
    <p v-else-if="erreur" class="erreur">{{ erreur }}</p>

    <template v-else-if="bilan.n === 0">
      <div class="vide">
        <b>Aucune annotation pour {{ version }}.</b>
        <p class="doux">
          La séance n'a pas encore eu lieu — ce n'est pas une panne. L'or se trace
          dans l'outil local :
        </p>
        <pre>cd ml &amp;&amp; python -m bench.gold_crop.annotate.serve --out state/gold_crop/{{ version }}</pre>
      </div>
    </template>

    <template v-else>
      <section class="bilan">
        <div><b>{{ bilan.annotees }}</b><span>/ {{ bilan.n }} annotées</span></div>
        <div><b>{{ bilan.acceptes }}</b><span>acceptées par l'humain</span></div>
        <div><b>{{ bilan.indecidables }}</b><span>indécidables</span></div>
        <div><b>{{ bilan.strates_confirmees }}</b><span>strates confirmées</span></div>
        <div :title="'La 2ᵉ passe fixe le plafond du banc : le bruit de la main.'">
          <b>{{ bilan.doubles }}</b><span>en double passe</span>
        </div>
        <div v-if="bilan.ba_median" :title="'À b/a = 0,90, le format plafonne la Boundary IoU à ≈ 0,26.'">
          <b>{{ bilan.ba_median.toFixed(3) }}</b><span>b/a médian</span>
        </div>
      </section>

      <section class="filtres">
        <button :class="{ actif: !filtreStrate }" @click="filtreStrate = null">
          toutes ({{ passe1.length }})
        </button>
        <button
          v-for="s in strates" :key="s"
          :class="{ actif: filtreStrate === s }"
          @click="filtreStrate = s"
        >
          {{ s }} ({{ passe1.filter((a) => strateRetenue(a) === s).length }})
        </button>
        <span class="sep"></span>
        <button :class="{ actif: !filtreVerdict }" @click="filtreVerdict = null">
          tous verdicts
        </button>
        <button :class="{ actif: filtreVerdict === 'accept' }" @click="filtreVerdict = 'accept'">
          acceptés
        </button>
        <button :class="{ actif: filtreVerdict === 'reject' }" @click="filtreVerdict = 'reject'">
          rejetés
        </button>
        <span class="sep"></span>
        <label class="bascule">
          <input v-model="montrerBande" type="checkbox" />
          montrer la bande du juge (0,08·a)
        </label>
      </section>

      <section class="grille">
        <VignetteOr
          v-for="a in visibles" :key="`${a.asset_id}-${a.passe}`"
          :annotation="a" :montrer-bande="montrerBande"
        />
      </section>
    </template>
  </div>
</template>

<style scoped>
/* Le front admin est en thème CLAIR : les couleurs viennent de `shared/tokens.css`
   (R2), jamais d'hexadécimaux inventés. Premier jet stylé en sombre — le bloc de
   commande sortait noir sur noir, invisible. */
.gold-crop { padding: 1.5rem; max-width: 1400px; margin: 0 auto; color: var(--ink-700); }
header { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
h1 { font-size: var(--text-lg); margin: 0 0 0.2rem; font-family: var(--font-display); }
.doux { color: var(--ink-500); }
.erreur { color: var(--danger); }
.etat { flex: none; }
.pastille { display: inline-block; white-space: nowrap; padding: 0.15rem 0.6rem;
            border-radius: 99px; font-size: var(--text-xs); font-weight: 600; }
.gele { background: var(--indigo-100); color: var(--indigo-700); }
.ouvert { background: var(--gold-100); color: var(--gold-700); }
.seance { display: flex; align-items: center; gap: 1rem; flex-wrap: wrap; margin-top: 1rem;
          padding: 0.8rem 1rem; border: 1px solid var(--surface-3); border-radius: 10px;
          background: var(--surface-1); }
.avance { display: flex; flex-direction: column; margin-right: auto; }
.avance b { font-size: var(--text-lg); font-variant-numeric: tabular-nums; }
.avance .doux { font-size: var(--text-xs); }
.bouton { text-decoration: none; font-size: var(--text-sm); font-weight: 600;
          padding: 0.35rem 0.8rem; border-radius: 6px; background: var(--indigo-600);
          color: #fff; }
.bouton:hover { background: var(--indigo-700); }
.bouton.second { background: var(--surface); color: var(--indigo-700);
                 border: 1px solid var(--indigo-300); }
.lien-planche { flex-basis: 100%; font-size: var(--text-xs); color: var(--indigo-700); }
.vide { margin-top: 2rem; padding: 1.25rem; border: 1px dashed var(--surface-3);
        border-radius: 10px; background: var(--surface-1); }
.vide pre { margin: 0.6rem 0 0; padding: 0.6rem 0.75rem; background: var(--surface-3);
            color: var(--ink-700); border-radius: 6px; overflow-x: auto;
            font-family: var(--font-mono); font-size: var(--text-xs); }
.bilan { display: flex; flex-wrap: wrap; gap: 1.5rem; margin: 1.25rem 0;
         padding: 0.9rem 1rem; border: 1px solid var(--surface-3); border-radius: 10px;
         background: var(--surface-1); }
.bilan div { display: flex; flex-direction: column; }
.bilan b { font-size: var(--text-lg); font-variant-numeric: tabular-nums; }
.bilan span { font-size: var(--text-xs); color: var(--ink-500); }
.filtres { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; margin-bottom: 1rem; }
.filtres button { font: inherit; font-size: var(--text-xs); padding: 0.25rem 0.6rem;
                  border: 1px solid var(--surface-3); border-radius: 6px;
                  background: var(--surface); color: var(--ink-700); cursor: pointer; }
.filtres button:hover { background: var(--surface-2); }
.filtres button.actif { background: var(--indigo-600); border-color: var(--indigo-600);
                        color: #fff; font-weight: 600; }
.sep { width: 1px; height: 1.2rem; background: var(--surface-3); margin: 0 0.3rem; }
.bascule { font-size: var(--text-xs); display: flex; gap: 0.35rem; align-items: center;
           cursor: pointer; color: var(--ink-500); }
.grille { display: grid; gap: 0.75rem;
          grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); }
</style>
