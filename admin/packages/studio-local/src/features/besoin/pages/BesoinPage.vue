<script setup lang="ts">
// `/besoin` — le poste de pilotage de l'enrichissement DINO (O2, lot 3).
//
// Elle répond à trois questions, dans cet ordre, et à aucune autre :
//   1. où j'en suis      → l'histogramme et les deux paliers
//   2. ce que ça coûte   → le budget, en exemplaires
//   3. qu'est-ce que je fais → un verdict et un geste, par classe
//
// Ce qu'elle n'est PAS : un écran de review (on n'y tranche rien, elle oriente),
// le préflight de cohorte (voie A, `min_real` — les deux peuvent être en
// désaccord légitime sur la même classe), un auto-accept.
//
// Décision du PO (2026-08-23) : AUCUNE surface spécialisée. Pas de mode
// session, pas de refonte de la pêche, pas d'écran « émission commune ». On
// trie et on filtre ici ; on tranche dans les pages de review existantes.
//
// Route NON `heavy` : `/class-need` est du SQL pur sur le canonique. Savoir ce
// qui manque ne doit pas dépendre d'un Mac allumé (O2 §Où elle vit). Seuls les
// GESTES sont lourds, et ils se grisent tout seuls.

import { computed, onMounted, ref } from 'vue'
import { RotateCw } from 'lucide-vue-next'

import { useCapabilities } from '@/stores/capabilities'
import BesoinBandeau from '../components/BesoinBandeau.vue'
import BesoinTable from '../components/BesoinTable.vue'
import {
  applyFilters, EMPTY_FILTERS, useClassNeed, workOrder,
  type Bottleneck, type Filters, type Palier,
} from '../composables/useClassNeed'

const caps = useCapabilities()
const heavyLocked = computed(() => !caps.hasLocalMlApi)

const { data, loading, error, load, countries } = useClassNeed()

/** Le palier courant décide de l'ORDRE, pas du contenu (D7). */
const palier = ref<Palier>('couverture')
const filters = ref<Filters>({ ...EMPTY_FILTERS })

const rows = computed(() => {
  if (!data.value) return []
  return workOrder(applyFilters(data.value.classes, filters.value), palier.value)
})

const LIMIT = 200
const showAll = ref(false)
const shown = computed(() => (showAll.value ? rows.value : rows.value.slice(0, LIMIT)))

function setBottleneck(v: Bottleneck | 'tous') {
  filters.value = { ...filters.value, bottleneck: v }
}
function reset() {
  filters.value = { ...EMPTY_FILTERS }
}
const filtered = computed(
  () => JSON.stringify(filters.value) !== JSON.stringify(EMPTY_FILTERS),
)

onMounted(() => {
  void load()
  void caps.probe()
})
</script>

<template>
  <div class="page">
    <header class="head">
      <div>
        <h1>Besoin</h1>
        <p class="sub">
          Quelle classe je nourris maintenant, par quel geste, et quand j'arrête.
        </p>
      </div>
      <button type="button" class="refresh" :disabled="loading" @click="load()">
        <RotateCw class="h-3.5 w-3.5" :class="{ spin: loading }" />
        Relire
      </button>
    </header>

    <!-- ERREUR : jamais une liste vide. Une page muette se lit « rien à
         faire », ce qui est plausible et faux. -->
    <div v-if="error" class="msg msg--err">
      <b>Le canonique n'a pas répondu.</b>
      <p class="mono">{{ error }}</p>
      <p>
        Ce n'est pas « il n'y a rien à faire » — c'est que la lecture a échoué.
        La route est <code>GET /class-need</code> sur <code>eurio-api</code>.
        <button type="button" class="linkish" @click="load()">Réessayer</button>
      </p>
    </div>

    <!-- CHARGEMENT : la structure reste stable, pas de spinner plein écran.
         C'est un tableau de bord : sa forme ne doit pas sauter. -->
    <div v-else-if="loading && !data" class="skeleton">
      <div class="sk sk--line" />
      <div class="grid gap-3 md:grid-cols-3">
        <div class="sk sk--panel" /><div class="sk sk--panel" /><div class="sk sk--panel" />
      </div>
      <div class="sk sk--histo" />
      <p class="msg">Lecture du besoin sur le canonique…</p>
    </div>

    <!-- VIDE : un `all_needs` à zéro ligne veut dire que le couple
         (banque, encodeur) est faux, pas qu'il n'y a rien à faire. -->
    <div v-else-if="data && !data.classes.length" class="msg">
      <b>La banque lue ne contient aucune classe.</b>
      <p>
        <code>{{ data.build.anchors_kind }}</code> /
        <code>{{ data.build.encoder_version }}</code> — le couple est
        indissociable, et un JOIN à zéro ligne se lirait « tout est à scraper ».
      </p>
    </div>

    <template v-else-if="data">
      <BesoinBandeau
        :data="data" :rows="rows" :palier="palier" :heavy-locked="heavyLocked"
        @palier="palier = $event" @bottleneck="setBottleneck"
      />

      <!-- Les filtres, avec leur effet en clair : un périmètre qui rate se
           ferme, il ne s'ouvre pas — mais il DIT toujours ce qu'il montre. -->
      <div class="filters">
        <span class="flabel">filtres</span>
        <select v-model="filters.bottleneck" class="sel">
          <option value="tous">goulot : tous</option>
          <option value="review">review — à trancher</option>
          <option value="scrape">scrape — à chercher</option>
          <option value="pleine">pleine — parqués</option>
        </select>
        <select v-model="filters.country" class="sel">
          <option value="tous">pays : tous</option>
          <option v-for="c in countries" :key="c" :value="c">{{ c }}</option>
        </select>
        <select v-model="filters.family" class="sel">
          <option value="toutes">famille : toutes</option>
          <option value="nationale">nationale</option>
          <option value="portrait_standard">portrait standard</option>
          <option value="emission_commune">◈ émission commune</option>
        </select>
        <label class="chk" title="N'afficher que les classes dont au moins un candidat dépasse le seuil du verdict (0,05). En dessous, le modèle n'est net sur aucun.">
          <input v-model="filters.margeUtile" type="checkbox" />
          marge utile
        </label>
        <input v-model="filters.q" class="q" placeholder="classe ou libellé…" />

        <span class="count">
          <b>{{ rows.length }}</b> / {{ data.totals.n_classes }} classes
          <button v-if="filtered" type="button" class="linkish" @click="reset()">
            tout revoir
          </button>
        </span>
      </div>

      <BesoinTable :rows="shown" />

      <p v-if="!showAll && rows.length > LIMIT" class="more">
        {{ rows.length - LIMIT }} classes de plus ne sont pas affichées —
        <button type="button" class="linkish" @click="showAll = true">tout afficher</button>
        <span class="mono"> (le tri sert d'abord ce que l'action débloque)</span>
      </p>
    </template>
  </div>
</template>

<style scoped>
.page { padding: 24px 32px 80px; display: flex; flex-direction: column; gap: 16px; }
.head { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px; flex-wrap: wrap; }
h1 {
  font-family: var(--font-display); font-style: italic; font-size: 27px;
  font-weight: 600; color: var(--indigo-700); letter-spacing: -0.02em;
}
.sub { font-size: 12.5px; color: var(--ink-500); margin-top: 2px; }
.refresh {
  display: flex; align-items: center; gap: 6px; font-size: 12px;
  padding: 6px 12px; border-radius: 8px; border: 1px solid var(--surface-3);
  background: var(--surface); color: var(--ink-500); cursor: pointer;
}
.refresh:disabled { opacity: 0.5; cursor: wait; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.filters {
  display: flex; flex-wrap: wrap; gap: 8px; align-items: center;
  border: 1px solid var(--surface-3); border-radius: 12px;
  padding: 10px 14px; background: var(--surface-1);
}
.flabel {
  font-size: 10px; text-transform: uppercase; letter-spacing: 0.2em;
  color: var(--ink-400); font-weight: 600; margin-right: 4px;
}
.sel, .q {
  font-family: var(--font-mono); font-size: 11px; padding: 4px 8px;
  border-radius: 7px; border: 1px solid var(--surface-3);
  background: var(--surface); color: var(--ink);
}
.q { min-width: 20ch; }
.chk { display: flex; align-items: center; gap: 5px; font-size: 11.5px; color: var(--ink-500); cursor: pointer; }
.count { margin-left: auto; font-size: 11.5px; color: var(--ink-500); }
.count b { color: var(--ink); font-family: var(--font-mono); }

.msg { padding: 20px 4px; font-size: 13px; color: var(--ink-500); max-width: 78ch; line-height: 1.6; }
.msg b { color: var(--ink); }
.msg p { margin-top: 6px; }
.msg--err { border-left: 3px solid var(--danger); padding-left: 14px; }
.mono { font-family: var(--font-mono); font-size: 11px; }
code {
  font-family: var(--font-mono); font-size: 11px;
  background: var(--surface-2); border-radius: 4px; padding: 1px 5px;
}
.linkish {
  font-size: 12px; color: var(--indigo-700); text-decoration: underline;
  text-underline-offset: 2px; cursor: pointer; background: none; border: none; padding: 0 0 0 4px;
}
.more { font-size: 11.5px; color: var(--ink-500); padding-top: 8px; }

.skeleton { display: flex; flex-direction: column; gap: 16px; }
.sk { background: var(--surface-2); border-radius: 12px; animation: pulse 1.4s ease-in-out infinite; }
.sk--line { height: 28px; border-radius: 6px; }
.sk--panel { height: 128px; }
.sk--histo { height: 150px; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.55; } }
</style>
