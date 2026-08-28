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

import VignetteOr from '../components/VignetteOr.vue'
import {
  type AnnotationOr,
  estAnnotee,
  strateRetenue,
  useGoldCropApi,
} from '../composables/useGoldCropApi'

const version = ref('v1')
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
.gold-crop { padding: 1.5rem; max-width: 1400px; margin: 0 auto; }
header { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; }
h1 { font-size: 1.15rem; margin: 0 0 0.2rem; }
.doux { color: var(--text-muted, #9aa3b2); }
.erreur { color: #f87171; }
.pastille { padding: 0.15rem 0.6rem; border-radius: 99px; font-size: 0.75rem; font-weight: 600; }
.gele { background: rgba(96, 165, 250, 0.16); color: #60a5fa; }
.ouvert { background: rgba(255, 209, 102, 0.16); color: #ffd166; }
.vide { margin-top: 2rem; padding: 1.25rem; border: 1px dashed var(--border, #2f343d);
        border-radius: 10px; }
.vide pre { margin: 0.6rem 0 0; padding: 0.6rem 0.75rem; background: #0b0d10;
            border-radius: 6px; overflow-x: auto; font-size: 0.78rem; }
.bilan { display: flex; flex-wrap: wrap; gap: 1.5rem; margin: 1.25rem 0;
         padding: 0.9rem 1rem; border: 1px solid var(--border, #2f343d); border-radius: 10px; }
.bilan div { display: flex; flex-direction: column; }
.bilan b { font-size: 1.25rem; font-variant-numeric: tabular-nums; }
.bilan span { font-size: 0.72rem; color: var(--text-muted, #9aa3b2); }
.filtres { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; margin-bottom: 1rem; }
.filtres button { font: inherit; font-size: 0.78rem; padding: 0.25rem 0.6rem;
                  border: 1px solid var(--border, #2f343d); border-radius: 6px;
                  background: transparent; color: inherit; cursor: pointer; }
.filtres button.actif { background: #60a5fa; border-color: #60a5fa; color: #0b0d10; font-weight: 600; }
.sep { width: 1px; height: 1.2rem; background: var(--border, #2f343d); margin: 0 0.3rem; }
.bascule { font-size: 0.78rem; display: flex; gap: 0.35rem; align-items: center; cursor: pointer; }
.grille { display: grid; gap: 0.75rem;
          grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); }
</style>
