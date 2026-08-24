<script setup lang="ts">
/**
 * `/accueil/maquette` — l'accueil sur fixtures, tous ses états à un clic.
 *
 * CE QU'ELLE REMPLACE, ET POURQUOI ELLE N'EST PAS JETABLE
 * -------------------------------------------------------
 * R1 (proto-first) ne couvre que l'app Android : le proto est la PWA du
 * collectionneur, et `scene-parity.md` mappe chacune de ses scènes vers une
 * destination Compose. Un écran d'admin n'en a aucune. Mais l'INTENTION de R1
 * vaut ici aussi — « c'est là que se décide à quoi ressemble la première
 * minute » — et cette page la sert : elle monte le composant DÉFINITIF
 * (`AccueilVue`) sur des fixtures. Ce qu'on regarde est ce qu'on livre.
 *
 * Elle sert deux fois : maintenant pour trancher le visuel, et ensuite pour
 * regarder les cas limites qu'on ne sait pas provoquer en base — une file vide,
 * un ami à zéro, un `/class-need` qui tombe.
 *
 * ⛔ HORS NAV, et sans accès réseau. Aucun chiffre affiché ici n'est réel, et le
 * bandeau le dit — un écran de maquette qu'on prend pour la production est un
 * chiffre inventé qu'on croit.
 */
import { computed, ref } from 'vue'

import AccueilVue from '../components/AccueilVue.vue'
import { ETATS } from '../fixtures/accueil.mock'

const choisi = ref(ETATS[0].id)
const etat = computed(() => ETATS.find((e) => e.id === choisi.value) ?? ETATS[0])
</script>

<template>
  <div>
    <div class="barre">
      <p class="avert">
        <b>Maquette</b> — fixtures, aucun chiffre réel
      </p>
      <div class="onglets">
        <button
          v-for="e in ETATS" :key="e.id" type="button"
          class="onglet" :class="{ actif: e.id === choisi }"
          :title="e.enjeu" @click="choisi = e.id"
        >{{ e.titre }}</button>
      </div>
      <p class="enjeu">{{ etat.enjeu }}</p>
    </div>

    <AccueilVue
      :n-triees="etat.nTriees"
      :n-completees="etat.nCompletees"
      :but-commun="etat.butCommun"
      :pieces="etat.pieces"
      :chargement="etat.chargement"
      :erreur="etat.erreur"
    />
  </div>
</template>

<style scoped>
.barre {
  padding: var(--space-4) var(--space-9);
  background: var(--indigo-800);
  border-bottom: 2px solid var(--gold);
}
.avert {
  font-family: var(--font-mono);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: var(--tracking-eyebrow);
  color: var(--gold);
}
.avert b { color: var(--gold-300); }

.onglets { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-3); }
.onglet {
  font-family: var(--font-ui);
  font-size: var(--text-xs);
  color: var(--indigo-200);
  background: rgba(255, 255, 255, 0.06);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 999px;
  padding: 4px 12px;
  cursor: pointer;
}
.onglet:hover { color: #fff; border-color: rgba(255, 255, 255, 0.3); }
.onglet.actif { background: var(--gold); border-color: var(--gold); color: var(--indigo-900); }
.onglet:focus-visible { outline: 2px solid var(--gold-300); outline-offset: 2px; }

.enjeu {
  margin-top: var(--space-3);
  font-family: var(--font-ui);
  font-size: var(--text-xs);
  color: var(--indigo-200);
  max-width: 80ch;
}
</style>
